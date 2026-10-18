# Deployment Plan: Restaurant Recommender (Railway + Vercel)

How to put the app online: the FastAPI backend on **Railway**, the web frontend on **Vercel**. Companion to [implementation-plan.md](implementation-plan.md) and [architecture.md](architecture.md). Written against the code on `feat/phase-4-engine` (commit `92c5ece`) and the platform docs as of October 2026.

**Status (2026-10-18).** Code changes D0.1 to D0.9 are done and committed on `feat/phase-4-engine` (`25e4558`..`b9f0423` and the two after it), 359 tests passing. Still to do: D0.0 (own repo, needs your go-ahead to create and push), a real `docker build` (Docker isn't installed on the dev machine; a clean non-editable install run with environment variables only was used instead), and D1 to D3 on the platforms.

**Where the code lives.** https://github.com/raviiitb0606-pm/Zomato-m9 (step D0.0 done): the project files and its own commit history only, split out of the local folder that began as a clone of the course repo.

---

## 1. Target setup

```
 Browser ──► Vercel (your-app.vercel.app)
               ├─ /, /static/*                → static files (index.html, app.css, app.js)
               └─ /meta, /recommend, /health  → proxied to Railway, with a secret header
                                                    │
                                                    ▼
                                    Railway (xyz.up.railway.app)
                                    uvicorn recommender.api:app, 1 replica
                                    restaurants.parquet + meta.json baked into the image
                                                    │
                                                    ▼
                                                 Groq API
```

**Key decisions**

| Decision | Choice | Why |
|---|---|---|
| How the page reaches the API | Vercel proxies `/meta`, `/recommend`, `/health` to Railway | The page keeps calling same-origin paths, so no CORS and no API URL in the JavaScript. Visitors' IPs are forwarded (`x-real-ip`, `x-forwarded-for`). |
| Who may call the API | Only Vercel: it attaches `x-origin-secret`, and the backend rejects calls without it | Every `/recommend` spends the Groq quota (8K tokens/min, 200K/day). An open Railway URL lets anyone drain it. |
| Railway build | A `Dockerfile` at the repo root | Railway always builds a Dockerfile when it finds one. Config-as-code (`railway.toml`) is deprecated on Railway; a Dockerfile is explicit and testable locally. |
| Data | Ship `restaurants.parquet` (505 KB) and `meta.json` (4 KB) in the image | `data/` is gitignored, and the API refuses to start without it. Re-running ingestion on every build would download the whole Hugging Face dataset. |
| Replicas | 1 | The rate limiter, LLM budget and response cache live in memory. One instance is plenty for this load. |
| Streamlit page | Not deployed | The new web page replaces it. Vercel can't host Streamlit anyway. |

---

## 2. Decide before starting

| Question | Default if undecided |
|---|---|
| **New GitHub repo:** name and visibility, under `raviiitb0606-pm`. | Private repo `restaurant-recommender`. Railway and Vercel can both deploy private repos once given access. |
| **What goes in it.** Only the project (`src/`, `tests/`, `app/`, `docs/`, `pyproject.toml`, `.env.example`, `.gitignore`), not the course content (`course/`, course `README.md`, `CLAUDE.md`, `CURRICULUM.md`, `GETTING_STARTED.md`). | Project files only, keeping the 23 project commits as history. |
| **Can the derived dataset go in the repo?** The Hugging Face page for `ManikaSaini/zomato-restaurant-recommendation` states **no licence** (no dataset card; 51,717 rows, 574 MB). | **Decided: option A** (commit the 505 KB output), which suits the **private** repo. If the repo is ever made public, take the two data files out first and switch to option B. |
| **Model.** `.env` uses `openai/gpt-oss-120b`; the code default is `openai/gpt-oss-20b`. Implementation plan Phase 7 task 5 picks the default. | `openai/gpt-oss-120b`, the one measured in prompt v3. |
| **Custom domain** | None at first; use `*.vercel.app`. |

---

## 3. Phase D0: changes before deploying

Each step is one small commit with its tests. Steps 4 to 6 are Phase 7 hardening items from the implementation plan; they are **required** before a public URL exists, because of the Groq limits.

### D0.0 Give the project its own repo
- In a temporary clone (the working folder stays untouched), keep only the project paths and drop the course-only commits, which keeps the 23 project commits.
- Add a short project `README.md` (setup, run, test); the full README is implementation plan Phase 7 task 6.
- Create the GitHub repo and push `main`. Point this folder's `origin` at the new repo, or keep working from the new clone.
- Railway and Vercel then connect to this repo (D1 step 1, D2 step 1).

### D0.1 Slim the runtime dependencies
The server never imports `datasets` or `streamlit`, which make the image much larger.
- `pyproject.toml`: move `datasets` to an `ingest` extra and `streamlit` to a `streamlit` extra. `dev` installs both, so the tests still run.
- Check: `pip install .` in a clean venv, then start the API. Run the full test suite with `pip install -e ".[dev]"`.

### D0.2 Put the frontend assets in `web/static/`
`index.html` loads `/static/app.css` and `/static/app.js`. Moving those two files into `src/recommender/web/static/` makes the same URLs work on both servers: FastAPI mounts `web/static` at `/static`, and Vercel serves the folder as is.
- Narrow `package-data` to `web/*.html` and `web/static/*`, so `vercel.json` (step D0.9) isn't packaged.
- Check: the web UI tests pass; `GET /static/app.js` returns 200.

### D0.3 Ship the data
- **Option A (simple, chosen):** un-ignore and commit `data/restaurants.parquet` and `data/meta.json`. Private repo only (section 2).
- **Option B (no data in git):** a first Docker stage installs the `ingest` extra and runs `python -m recommender.ingestion.cli`, and the final stage copies only the two files. This is slower to build and needs Hugging Face reachable at build time.
- Either way, set `DATA_DIR=/app/data`. In an installed (non-editable) package, `config.PROJECT_ROOT` points into `site-packages`, so a relative `DATA_DIR` would resolve to the wrong place.

### D0.4 Reject API calls that didn't come through Vercel
- New setting `ORIGIN_SECRET` (optional; when unset, as in local development, nothing is checked).
- Middleware: when it is set, `/meta` and `/recommend` require a matching `x-origin-secret` header and otherwise get 403. Compare with `hmac.compare_digest`. `/health` stays open for Railway's health check.
- Also when it is set: turn off `/docs` and `/openapi.json` (`docs_url=None`).
- Tests: no header, wrong header, right header, and `/health` without a header.

### D0.5 Protect the Groq quota (implementation plan Phase 7, tasks 1 and 2)
1. **Response cache.** An in-memory LRU keyed on the normalised preferences + `PROMPT_VERSION` + model (edge cases CAC-01 to CAC-07). Fallback responses are not cached.
2. **Per-visitor rate limit on `/recommend`**, for example 5 a minute and 60 a day per IP, returning 429 with a friendly message. The IP comes from `x-real-ip`, which Vercel sets. This header is trustworthy only because D0.4 guarantees the request came through Vercel.
3. **Global LLM budget.** Wrap the Groq client so it refuses calls past roughly 3 a minute (a search reserves about 2K of the 8K tokens/min) and about 100 a day. A refused call raises `LLMError`, so the engine's existing fallback serves the pre-ranked results with the "AI ranking is unavailable" note instead of an error.
- The page needs one addition: show the 429 message ("Too many searches, try again in a minute").

### D0.6 Bound the request time
- Add an overall deadline per request (edge case NET-08), for example 25 seconds. Today a slow Groq call can stack timeouts and retries: SDK retry plus the malformed-reply retry, at 30 seconds each.
- Production values: `LLM_TIMEOUT_SECONDS=12`, and the page's 60-second timeout stays as the outer bound.
- Vercel doesn't document a timeout for external rewrites on its rewrites page. Measure it in D2 (step 5).

### D0.7 Logging (implementation plan Phase 7, task 3)
Configure app logging at INFO so Railway shows, per request: request shape, shortlist size, latency, fallback flag, token usage and cache hit or miss. Never log `extras` text or the API key.

### D0.8 Dockerfile and `.dockerignore`
```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY data/restaurants.parquet data/meta.json ./data/
# Railway sets PORT. One worker: the cache and limits are in memory.
CMD ["sh", "-c", "exec uvicorn recommender.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
```
- `.dockerignore`: `.venv`, `.git`, `.env`, `course/`, `docs/`, `tests/`, `app/`, `node_modules`, `__pycache__`.
- Check locally:
  ```bash
  docker build -t recommender .
  docker run --rm -p 8000:8000 -e LLM_API_KEY=$GROQ_KEY -e LLM_MODEL=openai/gpt-oss-120b recommender
  curl localhost:8000/health && curl localhost:8000/meta | head -c 200
  ```
  Also confirm the image has no `.env` inside: `docker run --rm recommender ls -a /app`.

### D0.9 `vercel.json` at the repo root
Vercel builds from the repo root, which has `pyproject.toml`, so without this file it tries to deploy the FastAPI app (`FASTAPI_ENTRYPOINT_NOT_FOUND`). The file makes the project a plain static site and forwards the API paths with the secret header (only `routes` transforms can add the header):
```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": null,
  "installCommand": "",
  "outputDirectory": "src/recommender/web",
  "routes": [
    {
      "src": "/(meta|recommend|health)",
      "dest": "https://zomato-m9-production-e838.up.railway.app/$1",
      "transforms": [
        { "type": "request.headers", "op": "set", "target": { "key": "x-origin-secret" },
          "args": "$ORIGIN_SECRET", "env": ["ORIGIN_SECRET"] }
      ]
    }
  ]
}
```
- `framework: null` is "Other"; `installCommand: ""` skips the install; `outputDirectory` is the folder that gets published. Requests the route doesn't match fall through to those files.
- If `ORIGIN_SECRET` isn't set in Vercel, the literal text `$ORIGIN_SECRET` is sent, and a Railway service with the secret set answers 403.
- Nothing else may sit in `src/recommender/web/`: all of it is public.

**D0 exit check:** full test suite green; the Docker image runs locally with only environment variables; the page at `localhost:8000` works against it; a `/recommend` call without the secret gets 403 when `ORIGIN_SECRET` is set.

---

## 4. Phase D1: backend on Railway

1. **Create the service.** New Project → Deploy from GitHub repo → pick the repo (section 2). Railway finds the root `Dockerfile` and builds it.
2. **Variables** (service → Variables):

   | Variable | Value | Notes |
   |---|---|---|
   | `LLM_API_KEY` | Groq key | Secret. Use a key made for production, not your local one. |
   | `LLM_MODEL` | `openai/gpt-oss-120b` | Section 2. |
   | `CANDIDATE_CAP` | `10` | Already the default; set it explicitly anyway. |
   | `LLM_REASONING_EFFORT` | `low` | |
   | `LLM_TIMEOUT_SECONDS` | `12` | D0.6. |
   | `ORIGIN_SECRET` | output of `openssl rand -hex 32` | The same value goes into Vercel. |
   | `DATA_DIR` | `/app/data` | Set in the Dockerfile too. |
   | `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_PER_DAY` | `5` / `60` | Per visitor. These are the defaults; set them to make them visible. |
   | `LLM_CALLS_PER_MINUTE` / `LLM_CALLS_PER_DAY` | `3` / `100` | Across all users. Defaults. |
   | `RESPONSE_CACHE_SIZE` | `256` | Default. |
   | `REQUEST_DEADLINE_SECONDS` | `25` | Lower it if D2 step 5 finds Vercel's proxy timeout is shorter. |
   | `LOG_LEVEL` | `INFO` | Default. |

   Don't set `PORT`: Railway provides it.
3. **Settings → Deploy:** health check path `/health`. Restart policy: on failure. Replicas: 1.
4. **Settings → Build → Watch paths:** `src/**`, `data/**`, `pyproject.toml`, `Dockerfile`. Course-content and docs commits then don't redeploy the API.
5. **Networking → Generate domain**, giving `https://<name>.up.railway.app` (here `zomato-m9-production-e838.up.railway.app`), and put it in the root `vercel.json` (D0.9).
6. **Verify:**
   ```bash
   curl https://<railway-domain>/health                      # {"status":"ok"}
   curl -i https://<railway-domain>/meta                      # 403: no secret
   curl -s https://<railway-domain>/meta -H "x-origin-secret: $SECRET" | head -c 200
   ```
   The deploy log should show a clean start. A missing key or missing data stops it with `StartupError`, and Railway then keeps the previous deployment running.

---

## 5. Phase D2: frontend on Vercel

1. **New Project** → import the same repo. Leave **Root Directory** empty (the repo root): the root `vercel.json` sets the framework, install command and output folder, and overrides the dashboard.
2. **Environment variable:** `ORIGIN_SECRET` (same value as on Railway) for Production and Preview.
3. **Ignored build step** (Settings → Git), so backend-only commits don't rebuild the site: `git diff --quiet HEAD^ HEAD -- src/recommender/web vercel.json`.
4. **Deploy a preview** from the feature branch and test it before production:
   - The page loads, the form fills from `/meta`, and a search returns cards.
   - The browser's network tab shows calls to `/recommend` on the Vercel domain, never the Railway URL.
5. **Measure the proxy timeout** (D0.6): temporarily set `LLM_TIMEOUT_SECONDS=30` on Railway and make a request slow, for example with a very low TPM budget so the Groq SDK waits on `retry-after`. Note how long Vercel waits before returning 504. Keep the backend deadline below it.
6. **Promote to production** once the preview passes.

---

## 6. Phase D3: go-live checks

Run against the production Vercel URL:

- [ ] `/health` returns `{"status":"ok"}` through Vercel.
- [ ] Normal search (Bangalore, medium, Italian, 4.0+, "family-friendly, quick service"): 5 cards; facts match the dataset; AI summary shown.
- [ ] Relaxed search (BTM, medium, Chinese, 4.5+): the loosened-filters banner is shown.
- [ ] No-result search (Banashankari, Kerala): empty state, and no Groq call in the logs.
- [ ] Phone width: no horizontal scrolling; the form folds into the search summary.
- [ ] Direct call to Railway `/recommend` without the secret: 403.
- [ ] Six quick searches from one browser: the sixth gets the rate-limit message (D0.5).
- [ ] The same search twice: the second is a cache hit in the logs, and Groq usage doesn't grow.
- [ ] Railway logs show token usage and no `extras` text.
- [ ] Optional: run the smoke eval subset (E-01, E-09, E-14, R-01) against the production URL. It costs about 4 LLM calls.

---

## 7. Running it

- **Deploys:** pushing to the production branch rebuilds whichever side changed (watch paths and the ignored build step). Backend and frontend can ship separately, as long as the API contract stays backwards-compatible. New fields are fine; the page ignores ones it doesn't know.
- **Rollback:** Railway → Deployments → redeploy the previous one. Vercel → Deployments → Instant Rollback or promote the previous one.
- **Groq budget:** watch daily usage in the Groq console. At around 1.6K tokens per uncached search, 200K a day is about 125 searches. The D0.5 budget turns anything beyond that into fallback results rather than errors.
- **Rotating secrets:**
  - Groq key: create a new key, update `LLM_API_KEY` on Railway (this redeploys), then revoke the old key.
  - `ORIGIN_SECRET`: have the backend accept the old and new values, update Vercel, then remove the old value.
- **Data refresh:** re-run ingestion locally, commit the two files (option A), and push; Railway redeploys.
- **Cost:** Railway bills by usage after its trial, and Vercel's Hobby plan is free for personal, non-commercial projects. Check both pricing pages before going live, as plans change.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| The public URL is used to drain the Groq quota | D0.4 origin secret, D0.5 per-IP limit and global budget, cache. |
| Groq rate limits hit under real traffic | The budget wrapper keeps calls under the per-minute limit; over budget, users get pre-ranked results with a note, not errors. |
| Vercel's proxy times out on slow LLM calls | The D0.6 deadline; the timeout is measured in D2 step 5. |
| The image lacks the web files or data (non-editable install) | `package-data` in D0.2; `DATA_DIR` set absolutely; the local Docker check in D0.8. |
| A secret leaks via logs or the image | `.dockerignore` excludes `.env`; logs carry no key or `extras`; Railway variables hold secrets. |
| More than one replica splits the in-memory limits | Keep 1 replica. Moving the limits and cache to Redis is the path if traffic ever needs more. |
| Course files or history end up in the project repo | D0.0 filters to project paths only; check the file list before pushing. |

---

## References

- Railway config reference (builders, health check, restart policy): https://docs.railway.com/reference/config-as-code
- Vercel rewrites, external origins, forwarded visitor headers, restricting the origin: https://vercel.com/docs/rewrites
- Vercel `vercel.json` routes and transforms: https://vercel.com/docs/project-configuration/vercel-json

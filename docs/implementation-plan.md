# Implementation Plan: AI-Powered Restaurant Recommendation System

Phase-wise plan for building the system described in [architecture.md](architecture.md) to meet [problemStatement.md](problemStatement.md). Each phase ends with something runnable and a clear exit check, so work can stop or be reviewed at any phase boundary.

## Overview

| Phase | Name | Outcome | Depends on |
|---|---|---|---|
| 0 | Project setup | Installable package, config, test runner | none |
| 1 | Data ingestion | Clean `restaurants.parquet` and `meta.json` | 0 |
| 2 | Store and filtering | Preferences in, shortlist out (no LLM) | 1 |
| 3 | LLM client and prompt | Ranked, explained JSON from a shortlist | 0 (can run alongside 2) |
| 4 | Recommendation engine | End-to-end recommendation with validation and fallback | 2, 3 |
| 5 | API | `/recommend`, `/meta`, `/health` | 4 |
| 6 | UI | Streamlit form and result cards | 5 |
| 7 | Hardening and release | Caching, rate limit, logging, README, quality pass | 6 |

Working rules for every phase: small commits (one thing each), tests written with the code, feature branch rather than `main`, and no phase is marked done until its exit check has been run.

---

## Phase 0: Project setup

**Goal:** an empty but working skeleton that everything else plugs into.

**Tasks**
1. Create the layout from architecture section 4: `src/recommender/`, `app/`, `data/`, `tests/`.
2. Write `pyproject.toml` with Python 3.11+ and dependencies: `datasets`, `pandas`, `pyarrow`, `anthropic`, `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `streamlit`, `httpx`, `pytest`.
3. Add `config.py` using `pydantic-settings`: `ANTHROPIC_API_KEY`, `LLM_MODEL`, `SHORTLIST_SIZE` (default 20), `DATA_DIR`, `LLM_TIMEOUT_S`.
4. Add `.env.example`, and `.gitignore` entries for `.env`, `data/`, `__pycache__`.
5. Add `schemas.py` with the Pydantic models: `Preferences`, `Restaurant`, `Recommendation`, `RecommendationResponse`. Include the validation rules from section 5.6.
6. Add one smoke test so `pytest` runs green.

**Exit check:** `pip install -e .` works in a fresh virtualenv, `pytest` passes, and `Preferences` rejects an invalid budget and an out-of-range rating.

**Risks:** none significant.

---

## Phase 1: Data ingestion

**Goal:** turn the Hugging Face dataset into a clean local file the rest of the system can trust.

**Tasks**
1. `ingestion/load.py`: load `ManikaSaini/zomato-restaurant-recommendation` into a DataFrame.
2. **Schema discovery (do this before writing the cleaner).** Print the columns, dtypes, null counts, and 20 sample rows. Record the real column names, the cities covered, the format of the rating and cost fields, and whether any field can carry "family-friendly" or "quick service" signal. Update the mapping table in architecture section 5.1 if it differs.
3. `ingestion/clean.py`: implement the canonical schema: `id`, `name`, `city`, `locality`, `cuisines` (list), `cost_for_two`, `budget_tier`, `rating`, `votes`, `tags`.
   - Parse rating strings such as `"4.1/5"`. Treat `NEW`, `-`, and blanks as null.
   - Strip commas from costs and cast to int.
   - Normalize city names and map aliases.
   - Split and lowercase cuisines.
   - De-duplicate on `id`, keeping the highest vote count.
4. Compute budget tier thresholds from cost percentiles (33rd and 66th) and assign `budget_tier`. Rows with no cost get null.
5. `ingestion/cli.py`: write `data/restaurants.parquet` and `data/meta.json` (cities, cuisines, thresholds). Print a summary: rows in, rows dropped and why, rows out.
6. Tests: a small fixture of messy rows covering rating formats, missing cost, duplicates, and city aliases.

**Exit check:** `python -m recommender.ingestion.cli` produces both files; the summary shows plausible counts; tests pass; opening the Parquet shows no unparsed rating or cost strings.

**Risks:**
- The dataset's schema or coverage differs from the assumptions. Mitigation: task 2 comes first, and the rest of the phase follows what it finds.
- The dataset covers few cities, which limits the location input. Mitigation: record the actual city list and note it in the README.
- Too many rows are dropped for missing rating or cost. Mitigation: report drop counts; decide whether to keep null-rating rows (excluded only when a minimum rating is set).

---

## Phase 2: Store and filtering

**Goal:** given preferences, return a sensible shortlist without any LLM involvement.

**Tasks**
1. `store.py`: load the Parquet file once, hold it in memory, expose `query(prefs)`, `get(ids)`, and `meta()`. Fail with a clear message if the file is missing.
2. `filtering.py`:
   - Hard filters: city (and locality if given), budget tier, minimum rating, cuisine overlap (case-insensitive).
   - Pre-ranking score: Bayesian-average rating that accounts for vote count.
   - Keep the top `SHORTLIST_SIZE`.
3. Relaxation logic in the fixed order from section 5.4: return what passes; if zero, relax rating by 0.5, then budget by one tier; record each relaxed constraint; if still zero, return empty.
4. A small dev script (`python -m recommender.filtering --city ... --budget ...`) that prints the shortlist as a table.
5. Table-driven tests for each filter, the pre-ranking order, and the relaxation sequence.

**Exit check:** for at least five different preference sets, the dev script prints a shortlist that looks right by eye. Relaxation reports the constraints it loosened. Tests pass.

**Risks:**
- A cuisine typed by the user doesn't match the dataset's spelling. Mitigation: the UI will use values from `meta.json`; here, match case-insensitively.
- The Bayesian prior (the "average" rating and the vote weight) is arbitrary. Mitigation: start with the dataset mean and a vote weight near the median; tune only if results look off.

---

## Phase 3: LLM client and prompt (Groq)

**Goal:** get a ranked, explained JSON answer from the model for a given shortlist. This phase needs only a hardcoded shortlist, so it can run in parallel with Phase 2.

**Provider:** [Groq](https://console.groq.com/docs) through its official `groq` Python SDK. Default model `openai/gpt-oss-20b`, a production model that supports strict structured outputs. `openai/gpt-oss-120b` is the larger candidate for the Phase 7 comparison. Use production models only: Groq's preview models "may be discontinued at short notice".

**Tasks**
1. **Swap the provider set up in Phase 0.**
   - In `pyproject.toml`, replace `anthropic` with `groq`.
   - In `config.py` and `.env.example`, replace `ANTHROPIC_API_KEY` with `LLM_API_KEY` (still a `SecretStr`; `GROQ_API_KEY` also accepted) and set the `LLM_MODEL` default to `openai/gpt-oss-20b`. Read `LLM_TIMEOUT_SECONDS` and `CANDIDATE_CAP` (the old `LLM_TIMEOUT_S` and `SHORTLIST_SIZE` still work). Add `LLM_REASONING_EFFORT` (default `low`) and `LLM_MAX_COMPLETION_TOKENS` (default 1024).
   - Update architecture sections 2, 3 and 10, which name Anthropic.
2. `llm/base.py`: `LLMClient` interface with `complete(system, user, response_schema) -> str`. It stays provider-neutral so the engine and tests don't depend on Groq.
3. `llm/groq_client.py`: `client.chat.completions.create(...)` with:
   - **Response format:** `response_format={"type": "json_schema", "json_schema": {"name": "recommendations", "strict": True, "schema": ...}}`. Strict mode uses constrained decoding, so the reply always matches the schema. The schema needs every property in `required` and `additionalProperties: false` on every object.
   - **Reasoning:** `reasoning_effort` from config (`low` keeps latency and token use down) and `include_reasoning=False` (we only want the answer).
   - **Temperature:** the model default (0.6). Groq recommends 0.5–0.7 for reasoning models, so not the 0.2–0.3 from the original plan. Run-to-run stability is measured by eval M-24 instead.
   - **Limits and retries:** a completion-token cap, a timeout from `LLM_TIMEOUT_S`, and one retry with backoff on transient errors (429, 5xx, connection) honouring the `retry-after` header.
   - **Usage logging:** log `usage` (prompt and completion tokens) from each response, to check against the rate limits.
4. `prompt.py`: the system message and user template from section 6.
   - Pass only the needed fields with short keys.
   - Put the user's `extras` in a clearly delimited block.
   - Define a `PROMPT_VERSION` constant.
   - Define the response JSON schema here too, next to the prompt it belongs to. Still ask for JSON in the prompt: Groq's JSON object mode requires it, which matters if we ever fall back to a model without strict support.
   - Optionally, build the schema per request with the shortlist IDs as an `enum`, so the model can't invent IDs. Check that Groq's strict mode accepts `enum` first. The engine validates IDs either way.
5. A fake client (`llm/fake.py`) returning canned JSON for tests.
6. Snapshot tests for the rendered prompt and the response schema on a fixed input.
7. A manual script that sends a hardcoded 10-restaurant shortlist to the real model and prints the result, the latency and the token usage. Needs `GROQ_API_KEY` in `.env`.

**Exit check:** the manual script returns valid JSON in the expected shape, ranks only the supplied IDs, and writes explanations that cite real attributes from the data. Tokens per request are recorded and compared with the account's rate limits. The snapshot tests pass.

**Risks:**
- **Rate limits.** Groq's documented base limits for the GPT-OSS models are 30 requests/min, 1K requests/day, **8K tokens/min** and 200K tokens/day, and the free tier may be lower (check the account's limits page). Reasoning tokens count too. A 20-restaurant prompt could use several thousand tokens, allowing only a few requests a minute. Mitigations:
  - `reasoning_effort=low` and compact candidate JSON;
  - measure tokens in the exit check and lower `SHORTLIST_SIZE` (for example to 10–12) if needed;
  - a 429 retries once after `retry-after`, then the Phase 4 fallback applies;
  - the Phase 7 cache avoids repeat calls.
  - The eval suite (about 96 calls) has to be paced to fit the limits.
- **Models change quickly on Groq.** The model is an env var, and only production models are used. Strict structured outputs only work on some models (the GPT-OSS models at the time of writing). On another model, use JSON object mode; the parser and the Phase 4 retry and fallback handle malformed output.
- **Unsupported claims.** Explanations may claim facts the data doesn't hold (for example "great ambience"). Mitigation: the system prompt forbids this and tells the model to say when the data can't answer an extra preference; check it in the Phase 7 quality pass.

---

## Phase 4: Recommendation engine

**Goal:** the full backend path in one function: `recommend(prefs) -> RecommendationResponse`.

**Tasks**
1. `engine.py` steps, per section 5.5: get the shortlist; if empty, return an empty response without calling the LLM; build the prompt; call the LLM; parse JSON; validate IDs against the shortlist; attach name, cuisine, rating, and cost from the store; assign ranks.
2. Failure handling per section 8:
   - Malformed JSON: retry once with the parse error appended, then fall back.
   - LLM error or timeout: fall back to the pre-ranked shortlist with a templated explanation and `llm_fallback: true`.
   - Unknown IDs: drop them; top up from the pre-ranked shortlist if fewer than `top_k` remain.
3. Pass `relaxed_constraints` through to the response.
4. Tests with the fake client: valid output, malformed output, unknown IDs, duplicate IDs, an exception, and an empty shortlist.
5. A CLI entry point to run one real recommendation from the terminal.

**Exit check:** all engine tests pass; one real run from the CLI returns `top_k` recommendations whose facts match the dataset rows.

**Risks:**
- Latency from the LLM call. Mitigation: shortlist size cap and a timeout; measure here and record the baseline.
- The model reorders results so the pre-ranking no longer matters. This is the intended behaviour; the fallback keeps the pre-ranking order.

---

## Phase 5: API

**Goal:** expose the engine over HTTP with a stable contract.

**Tasks**
1. `api.py` with FastAPI:
   - `POST /recommend` taking `Preferences`, returning `RecommendationResponse`.
   - `GET /meta` returning cities, cuisines, and budget thresholds.
   - `GET /health`.
2. Load the store and check the API key at startup (lifespan), failing with a clear message if either is missing.
3. Map errors to responses: validation errors become 422; an unexpected failure becomes 500 with a generic message and no internals.
4. CORS settings only if the UI will be served from another origin.
5. Tests with `TestClient` against a small fixture Parquet and the fake LLM client.

**Exit check:** `uvicorn` starts; the interactive docs page works; `curl` on `/recommend` with the example body from section 5.6 returns the documented shape; tests pass.

**Risks:** none significant beyond configuration mistakes at startup, which the startup checks catch.

---

## Phase 6: UI

**Goal:** a person can fill in a form and read recommendations.

**Tasks**
1. `app/streamlit_app.py`: fetch `/meta` for the dropdown values; form with location, budget, cuisine (multi-select), minimum rating (slider), and extras (text, 300 characters max).
2. Results area: summary at the top, then one card per recommendation showing name, cuisine, rating, estimated cost, and the explanation.
3. States: loading spinner, empty result message, a notice listing any relaxed constraints, a note when `llm_fallback` is true, and an error banner when the API is unreachable.
4. API base URL from an environment variable.

**Exit check:** run the API and UI together, walk through three scenarios (a normal search, a search that triggers relaxation, a search with no results), and confirm every field named in the problem statement's output section is visible.

**Risks:**
- Streamlit reruns the whole script on each interaction and can fire duplicate requests. Mitigation: submit through a form button and keep results in session state.

---

## Phase 7: Hardening and release

**Goal:** make it safe to hand to someone else.

**Tasks**
1. Response cache: in-memory LRU keyed on a hash of normalized preferences, with a size limit.
2. Rate limiting on `/recommend`.
3. Logging: request shape, shortlist size, latency, fallback flag, and token usage. No free-text `extras` or API key in logs by default.
4. Quality pass: build 10–15 representative preference sets (include a thin-result case, a no-result case, and an adversarial `extras` string such as "ignore previous instructions"). Run them and check that:
   - every recommended restaurant exists in the dataset,
   - explanations only cite data that is present,
   - injected instructions don't change the output format or add restaurants.
   Save the cases and outputs so later prompt or model changes can be compared against them.
5. Compare two candidate models (a smaller and a larger one) on that set for quality, latency, and cost; set the default `LLM_MODEL`.
6. README: setup, ingestion, running the API and UI, configuration, the limits of the dataset, and how to run the tests.
7. Test as a new user: fresh clone, fresh virtualenv, follow only the README.

**Exit check:** the fresh-clone walkthrough works end to end using only the README; the quality set passes review; the full test suite is green.

**Risks:**
- Model quality or cost isn't acceptable at the default. Mitigation: the model is an env var, so the fix is configuration plus a re-run of the saved cases.

---

## Cross-cutting checklist

- Keep facts in responses sourced from the dataset, never from the model.
- Keep the prompt template and `PROMPT_VERSION` in one place.
- Add or update tests in the same commit as the code they cover.
- Update `architecture.md` when a phase finds something that contradicts it (especially the schema in Phase 1).

## Open decisions to resolve along the way

| Decision | Resolve in | Default if undecided |
|---|---|---|
| Real dataset schema and city coverage | Phase 1, task 2 | **Resolved:** Bangalore only, 12,453 outlets; mapping and findings in architecture 5.1 |
| Keep rows with null rating? | Phase 1 | **Resolved:** kept (24% of outlets); exclude only when a minimum rating is set |
| Neighbourhood-level search in v1? | Phase 2 | **Resolved:** yes. Location is the city or a neighbourhood, and a neighbourhood includes its sub-areas (architecture 5.4) |
| Default model | Phase 7, task 5 | Groq `openai/gpt-oss-20b`; compare with `openai/gpt-oss-120b` |
| Hosting beyond local | After Phase 7 | Local only |

# Architecture: AI-Powered Restaurant Recommendation System

Companion to [problemStatement.md](problemStatement.md). This document describes how to build the system: components, data flow, interfaces, prompt design, and a build order.

## 1. Goals and constraints

- Turn structured preferences (location, budget, cuisine, minimum rating, free-text extras) into a ranked, explained shortlist of restaurants.
- Ground every recommendation in the real dataset. The LLM ranks and explains. It must not invent restaurants or facts.
- Keep the deterministic work (filtering) in code and the judgment work (ranking, explanation, matching soft preferences like "family-friendly") in the LLM.
- Stay small: a single deployable service, no database server, no vector store in v1.

## 2. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best fit for the data and LLM libraries |
| Data loading | `datasets` (Hugging Face), `pandas` | Direct access to the dataset; easy cleaning and filtering |
| Local store | Parquet file in `data/` | Fast reload, no DB to run; ingestion runs once |
| LLM | Groq (`groq` SDK), default `openai/gpt-oss-20b`, model set by `LLM_MODEL` | Fast; strict structured outputs on the GPT-OSS models; swappable behind one interface |
| Backend | FastAPI + Pydantic | Typed request/response models, auto docs |
| UI | Streamlit (v1) | One file, form plus result cards, no frontend build |
| Config | `.env` + `pydantic-settings` | Keys and model name out of code |
| Tests | `pytest` | Unit tests on ingestion and filtering, mocked LLM tests |

The LLM client sits behind a small interface (`LLMClient.complete(system, user, response_schema) -> str`), so the provider can be swapped without touching the rest of the code. Groq counts each request's full `max_completion_tokens` against the tokens-per-minute limit, so each call asks only for what its reply needs: 500 + 85 tokens per pick (925 for 5 picks, 1,350 for 10), up to `LLM_MAX_COMPLETION_TOKENS` (default 1400).

## 3. High-level architecture

```
                    ┌───────────────────────────────────────────┐
                    │                  UI (Streamlit)           │
                    │  preference form  →  result cards         │
                    └───────────────┬───────────────▲───────────┘
                                    │ POST /recommend│ JSON
                    ┌───────────────▼───────────────┴───────────┐
                    │              API (FastAPI)                │
                    │  validate → orchestrate → format response │
                    └───────┬───────────────────────────▲───────┘
                            │                           │
              ┌─────────────▼────────┐        ┌─────────┴────────────┐
              │  Integration layer   │        │  Recommendation      │
              │  filter + shortlist  │        │  engine (LLM)        │
              │  + prompt builder    ├───────►│  rank + explain      │
              └─────────────▲────────┘ prompt └─────────┬────────────┘
                            │                           │ Groq API
              ┌─────────────┴────────┐
              │   Restaurant store   │
              │ (Parquet, in memory) │
              └─────────────▲────────┘
                            │ one-off / on refresh
              ┌─────────────┴────────┐
              │  Data ingestion      │
              │  HF dataset → clean  │
              └──────────────────────┘
```

The request path is: UI → API → integration layer (filter, shortlist, build prompt) → recommendation engine (LLM call, parse, validate) → API → UI.

## 4. Repository layout

```
.
├── docs/
│   ├── problemStatement.md
│   └── architecture.md
├── src/
│   └── recommender/
│       ├── config.py            # settings (env vars)
│       ├── schemas.py           # Pydantic models: Preferences, Restaurant, Recommendation
│       ├── ingestion/
│       │   ├── load.py          # pull dataset from Hugging Face
│       │   ├── clean.py         # normalize fields, drop bad rows
│       │   └── cli.py           # `python -m recommender.ingestion.cli`
│       ├── store.py             # load Parquet, expose lookup/query
│       ├── filtering.py         # hard filters + shortlist ranking
│       ├── prompt.py            # prompt template + builder
│       ├── llm/
│       │   ├── base.py          # LLMClient interface
│       │   ├── groq_client.py
│       │   ├── fake.py          # scripted client for tests
│       │   └── manual.py        # one real call: Phase 3 exit check
│       ├── engine.py            # orchestrates shortlist → LLM → parse → validate
│       └── api.py               # FastAPI app
├── app/
│   └── streamlit_app.py         # UI
├── data/                        # generated Parquet (gitignored)
├── tests/
├── .env.example
└── pyproject.toml
```

## 5. Components

### 5.1 Data ingestion

Runs offline, once, and again whenever the dataset is refreshed.

1. **Load** the dataset with `datasets.load_dataset("ManikaSaini/zomato-restaurant-recommendation")` and convert to a DataFrame.
2. **Inspect the real schema first.** Done in Phase 1; findings below.
3. **Clean and normalize** into a canonical schema (mapping confirmed against the real dataset):

| Canonical field | Source column | Cleaning |
|---|---|---|
| `id` | `url` | 12-char SHA-1 of the URL without its query string, which identifies one outlet |
| `name` | `name` | repair mojibake (repeated UTF-8/Latin-1 encoding, stray Windows-1252 bytes); collapse whitespace; drop rows without a name |
| `city` | `url` path segment | `zomato.com/bangalore/…` → "Bangalore", with aliases (`bengaluru`). Vanity URLs (`zomato.com/barleyz`) carry no city and inherit it when the dataset has exactly one city; otherwise they are dropped |
| `locality` | `location` | 93 neighbourhoods; falls back to `listed_in(city)` when missing (21 rows) |
| `cuisines` | `cuisines` | split on comma, strip, de-duplicate. Original casing kept for display (the source is already consistent); matching is case-insensitive |
| `cost_for_two` | `approx_cost(for two people)` | strip commas/₹, cast to int; missing, zero, or negative → null. Indian rupees |
| `budget_tier` | derived | `low` / `medium` / `high` from cost quantiles (see 5.3) |
| `rating` | `rate` | parse `"4.1/5"`, `"4.1 /5"`; `NEW`, `-`, blank, or outside 0–5 → null |
| `votes` | `votes` | cast to int, missing → 0 |
| `tags` | `rest_type`, `listed_in(type)`, `online_order`, `book_table` | lowercase list, **unioned across all listings of the outlet**; flags become `online ordering` / `table booking` |
| `popular_dishes` | `dish_liked` | split on comma (present for ~37% of outlets). Added because it gives explanations specific, grounded detail |

Not kept: `address`, `phone`, `reviews_list`, `menu_item` (large free text or personal data, not needed for recommendations).

4. **De-duplicate** on `id`. Each outlet appears once per Zomato listing (Delivery, Dine-out, …, per area), and those rows disagree on rating and votes because they were scraped at different times. Scalar fields come from the listing with the most votes; tags are the union of all listings.
5. **Write** `data/restaurants.parquet`, plus `data/meta.json` with cities, localities, cuisines and tags (most common first), and budget thresholds. The UI uses it to populate dropdowns. Both files are written to a temp file and renamed, so a failed run never leaves a partial file.

**Dataset findings (Phase 1):**

- 51,717 raw rows → **12,453 outlets**. No rows are dropped.
- **Bangalore only.** Every URL with a city segment is `/bangalore/`. `listed_in(city)` is not a city but one of 30 Zomato search areas; `location` holds 93 neighbourhoods. Requests for other cities (e.g. Delhi in the problem statement) can't be served from this data, so the "location" preference is in practice a Bangalore neighbourhood. Phase 2 filtering needs to match on `locality` (see 5.4).
- 24% of outlets have no rating (mostly `NEW`); 1% have no cost.
- Budget thresholds: low ≤ ₹300 < medium ≤ ₹500 < high (cost for two), giving a 41% / 31% / 28% split.
- Soft-preference signal: `quick bites`, `delivery`, `takeaway`, `casual dining`, `fine dining`, `buffet`, `table booking`, `pub`/`bar` exist as tags. Nothing in the data says "family-friendly"; explanations must say so rather than guess.
- 691 outlets share a name and locality with another outlet, e.g. two A2B listings in BTM. They have different Zomato URLs, ratings and costs, so they are kept as separate outlets.

### 5.2 Restaurant store

Loads the Parquet file into a pandas DataFrame at API startup and keeps it in memory. The dataset is small enough that no database is needed. It exposes `query(prefs) -> DataFrame` and `get(ids)`. If the data grows past memory, swap in SQLite or DuckDB behind the same interface.

### 5.3 Budget mapping

Budget is a user-facing tier, but the data holds a cost figure. During ingestion, compute tier thresholds from the cost distribution (for example the 33rd and 66th percentiles of `cost_for_two`) and save them in `meta.json`. Do not hardcode currency values. Rows with no cost get `budget_tier = null` and are excluded from budget-filtered queries.

### 5.4 Integration layer

Two jobs: reduce the dataset to a shortlist, then build the prompt.

**Hard filters (deterministic, in code):**

- **Location** is matched, ignoring case and spacing, against the city (with aliases: "Bengaluru" → Bangalore) or a neighbourhood. Since the data is Bangalore only, "Bangalore" means the whole city and a neighbourhood narrows it. A neighbourhood also covers its sub-areas: "Koramangala" includes "Koramangala 1st–8th Block", and "Whitefield" includes "ITPL Main Road, Whitefield". Sub-area matching only applies once the input is itself a known neighbourhood, so a bare word like "Old" or "Road" matches nothing. An unknown location returns an empty result with a message.
- `budget_tier` equals the requested budget, if one is given. Rows with no cost are excluded only when a budget is set.
- `rating >= min_rating` when `min_rating > 0`. Unrated restaurants never meet a minimum; with no minimum they are included.
- Cuisine overlaps any requested cuisine (case-insensitive). If none of the requested cuisines exist in the data, return an empty result with a message. If only some are unknown, match the rest and say so.

**Shortlist ranking (cheap pre-ranking so the prompt stays small):**

- Score = Bayesian average: `(votes × rating + m × C) / (votes + m)`, where C is the mean rating (3.63) and m the median vote count of rated restaurants (53). Both are computed from the data at load time. A 5.0 from 3 votes scores below a 4.5 from 2,000. Unrated restaurants sort last.
- Ties break by votes, then name, then id, so the same input always gives the same shortlist.
- Keep the top N (`CANDIDATE_CAP`, default 10) and pass those to the LLM.

**Empty or thin results, in order:**

1. If some but fewer than `top_k` pass, return them and say "Only N restaurants matched." No relaxation.
2. If zero pass, relax in a fixed order and report each step in `relaxed_constraints`: first the rating, down by 0.5 (never below 0); then, still with the lower rating, the budget widens by one neighbouring tier (low → low or medium, high → high or medium, medium → medium or low: going under budget is safer than going over). Location and cuisine are never relaxed.
3. If still zero, return an empty list and a message, with no relaxations listed. Do not call the LLM.

**Prompt builder** (see section 6) turns the shortlist and preferences into the final prompt.

### 5.5 Recommendation engine

`engine.recommend(prefs) -> RecommendationResponse`:

1. Call the integration layer to get the shortlist.
2. Build the prompt and call the LLM with low temperature (0.2–0.3), a token cap, and a timeout.
3. Parse the response as JSON.
4. **Validate against the shortlist.** Every returned `id` must exist in the shortlist. Drop any that don't, which guards against hallucinated restaurants.
5. **Attach the facts from the store, not from the LLM.** Name, cuisine, rating, and cost in the response come from the dataset row. Only the `rank`, `explanation`, and optional `summary` come from the LLM.
6. On a malformed response, retry once with the parse error appended. If that fails, fall back to the pre-ranked shortlist with a templated explanation and flag `llm_fallback: true`. An LLM error (timeout, rate limit) falls back straight away: the SDK has already retried transient errors once.
7. Unknown or duplicate ids are dropped (ids match ignoring case and spaces), and the gap is filled from the pre-ranked shortlist. Each recommendation carries `explanation_source`: `"llm"`, or `"template"` when the explanation is generated from the data, so the UI never presents boilerplate as AI reasoning. `llm_fallback` is true when no explanation came from the model. Templated explanations leave out missing values ("Not yet rated", no cost) rather than printing `None`. Explanations over 500 characters are trimmed at a sentence.

### 5.6 API

`POST /recommend`

Request:

```json
{
  "location": "Bangalore",
  "budget": "medium",
  "cuisine": ["Italian"],
  "min_rating": 4.0,
  "extras": "family-friendly, quick service",
  "top_k": 5
}
```

Response:

```json
{
  "summary": "Short overall take on the shortlist.",
  "recommendations": [
    {
      "rank": 1,
      "id": "a1b2c3",
      "name": "Example Trattoria",
      "locality": "Indiranagar",
      "zomato_url": "https://www.zomato.com/bangalore/example-trattoria-indiranagar",
      "cuisine": ["Italian", "Pizza"],
      "rating": 4.4,
      "estimated_cost": 800,
      "explanation": "Why this fits the user's preferences.",
      "explanation_source": "llm"
    }
  ],
  "relaxed_constraints": [],
  "llm_fallback": false,
  "message": null
}
```

`GET /meta` returns cities, localities, cuisines, and budget thresholds for the form. `GET /health` is for liveness checks.

Errors: invalid input is a 422 listing each bad field (without echoing the value); a body over 16 KB is a 413; an unexpected failure is a 500 with a generic message. Missing data or API key stops the server at startup.

Input validation (Pydantic): `budget` must be one of `low|medium|high`; `min_rating` is 0–5; `top_k` is 1–10; `extras` is capped at 300 characters.

### 5.7 UI

The web UI is a single page served by the API itself (`GET /`, assets under `/static`), so it needs no CORS and no build step: `src/recommender/web/` holds `index.html`, `app.css` and `app.js`. The design is the Stitch "Saffron & Slate" dark theme (`docs/stitch_bangalore_restaurant_ai_recommender/design/`).

- A form: location (select, from `/meta`), budget (segmented control with the real price bands), cuisine (chips, picked from the dataset's cuisines, max 10), minimum rating (slider), extras (300 characters, with a counter).
- Results: the summary above one card per recommendation: rank, name, neighbourhood, cuisine tags, rating, estimated cost for two, and the AI explanation ("Standard description" when the model gave none).
- States: loading skeletons, empty result, a notice for relaxed constraints, a note when `llm_fallback` is true, and an error banner with Retry. On small screens the form folds into a summary of the search after results arrive.
- Dataset and model text is inserted as text, never as HTML.

The earlier Streamlit page (`app/streamlit_app.py`) still works against the same API.

## 6. Prompt design

The prompt has three parts.

**System message**

- Role: a restaurant recommendation assistant.
- Rules: recommend only from the supplied list; refer to restaurants by `id`; do not state facts that are not in the data; if the user's extra preferences can't be judged from the data, say so rather than guessing.
- Output: JSON only, matching the schema below.

**User message**

```
User preferences:
- Location: {location}
- Budget: {budget}
- Cuisine: {cuisine}
- Minimum rating: {min_rating}
- Extras: {extras}

Candidate restaurants (JSON):
[
  {"id": "...", "name": "...", "cuisines": [...], "rating": 4.4, "votes": 1200,
   "cost_for_two": 800, "tags": [...], "locality": "..."},
  ...
]

Pick the best {top_k} for this user, ranked best first. For each, write 1–2 sentences
explaining why it fits, citing specific attributes from the data. Then write a
one-sentence summary.
```

**Expected output**

```json
{
  "summary": "...",
  "ranking": [
    {"id": "...", "explanation": "..."}
  ]
}
```

Notes:

- Send only the fields the model needs, with short keys, to keep tokens down.
- The user's free-text `extras` is untrusted input. Put it in a clearly delimited field, and treat anything in it as data. Since the engine only accepts IDs from the shortlist and takes facts from the store, a prompt-injection attempt can at worst reorder or reword results.
- Keep the prompt template in `prompt.py` and version it, so changes can be compared against saved test cases.

## 7. Data flow for one request

1. The user submits the form. The UI calls `POST /recommend`.
2. The API validates the body into a `Preferences` model.
3. The store applies the hard filters. The shortlist ranker keeps the top 10.
4. If the shortlist is empty, the relaxation steps run. If it is still empty, return an empty response.
5. The prompt builder renders the prompt. The LLM client calls the model.
6. The engine parses and validates the JSON, drops unknown IDs, and joins each ID to its dataset row.
7. The API returns the response. The UI renders the cards.

## 8. Error handling and resilience

| Failure | Behaviour |
|---|---|
| Dataset not ingested | API fails at startup with a message to run the ingestion CLI |
| No restaurants match | Relax constraints, report them; if still none, empty list with message |
| LLM timeout / API error | One retry with backoff, then fallback to the pre-ranked shortlist (`llm_fallback: true`) |
| Malformed LLM JSON | One retry with the error, then fallback |
| LLM returns unknown IDs | Drop them; fill from the pre-ranked shortlist if fewer than `top_k` remain |
| Missing API key | Fail at startup with a clear message |

## 9. Performance and cost

- Filtering is in-memory pandas over a few tens of thousands of rows, so it should take milliseconds.
- Each request is one LLM call. Cost and latency scale with shortlist size, so keep N small: 10 by default, which fits Groq's 8K tokens/minute limit.
- Baseline (Phase 4, `openai/gpt-oss-120b` on Groq, 10 candidates, reasoning effort low): 1.5–2.0 s per call, about 1,450–1,750 prompt and 480–690 completion tokens.
- Cache responses by a hash of the normalized preferences (in-memory LRU) so repeated searches don't call the model again.
- Use a smaller, faster model for the default and make the model name an env var, so quality can be traded against cost without code changes.

## 10. Security and privacy

- The API key lives in `.env` and is never logged or sent to the browser. `.env` is gitignored.
- Validate and length-limit all inputs. Never interpolate raw user text outside the delimited prompt field.
- No user accounts or personal data are stored. Logs record request shape and latency, not free-text `extras`, unless debug logging is turned on.
- Add basic rate limiting on `/recommend`, since each call costs money.

## 11. Testing strategy

- **Ingestion**: golden-file tests on small sample rows (rating strings, missing cost, duplicate rows, city aliases).
- **Filtering**: table-driven tests for each filter and for the relaxation order.
- **Prompt**: snapshot test of the rendered prompt for a fixed input.
- **Engine**: tests with a fake `LLMClient` returning valid JSON, malformed JSON, unknown IDs, and raising errors, to cover validation and fallback.
- **API**: FastAPI `TestClient` against a small fixture Parquet file.
- **Quality check (manual or scripted)**: a fixed set of 10–15 representative preference sets, reviewed by eye after prompt or model changes. Check that explanations only cite facts present in the data.

## 12. Build order

1. **Ingestion**: load, inspect schema, clean, write Parquet and `meta.json`. Done when the CLI produces a clean file and the tests pass.
2. **Store and filtering**: query by preferences, shortlist ranking, relaxation. Done when a CLI call prints a sensible shortlist.
3. **LLM client and prompt**: get a ranked, explained JSON result from a hardcoded shortlist.
4. **Engine**: connect filtering, prompt, LLM, validation, and fallback. Done when the fake-LLM tests pass and one real call works end to end.
5. **API**: `/recommend`, `/meta`, `/health`.
6. **UI**: form and result cards against the running API.
7. **Hardening**: caching, rate limiting, logging, README with setup and run steps.

## 13. Open questions

- ~~The exact dataset columns and city coverage need checking in step 1.~~ Resolved in Phase 1: see the findings in 5.1. The dataset is Bangalore only.
- Whether "additional preferences" such as "family-friendly" can be judged from the dataset's tags, or only loosely inferred. If the data has little signal, the explanations should say so.
- Whether to support multiple cities or neighbourhood-level search in v1.
- Which model to default to, after a cost and quality comparison on the test set.

## 14. Possible extensions (out of scope for v1)

- Semantic retrieval with embeddings for free-text queries like "cozy place for a date".
- Conversational follow-ups ("something cheaper", "more vegetarian options").
- User feedback capture to tune the shortlist scoring.
- Map view and distance-based ranking.

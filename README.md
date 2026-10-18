# Restaurant Finder (Bangalore)

AI restaurant recommendations over Zomato data for Bangalore. You pick a location, budget, cuisines, a minimum rating and any extra wishes; the app filters the dataset, and an LLM (Groq, `openai/gpt-oss-120b`) ranks the best matches and explains each pick using only the restaurant's data.

- **Backend:** FastAPI (`src/recommender/`): filtering, prompt, LLM client, validation and fallback, cache, rate limits.
- **Frontend:** one static page (`src/recommender/web/`), served by the API locally and by Vercel in production.
- **Data:** `data/restaurants.parquet` and `data/meta.json`, built from the Hugging Face dataset `ManikaSaini/zomato-restaurant-recommendation` by `python -m recommender.ingestion.cli`.

## Run it locally

Needs Python 3.11+ and a Groq API key (https://console.groq.com/keys).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then set LLM_API_KEY
uvicorn recommender.api:app   # open http://127.0.0.1:8000/
```

The API docs are at http://127.0.0.1:8000/docs. Limits are on by default (5 searches a minute per visitor, 3 LLM calls a minute overall); set them to 0 in `.env` while developing.

## Tests

```bash
pytest
```

The browser tests in `tests/test_web_ui.py` use Playwright with an installed Chrome (or `playwright install chromium`) and skip themselves when no browser is available.

## Docs

- `docs/problemStatement.md`: what the app must do
- `docs/architecture.md`: components, data flow, API contract
- `docs/implementation-plan.md`: the build, phase by phase
- `docs/edge-case.md`, `docs/eval.md`: edge cases and the evaluation plan
- `docs/deployment-plan.md`: deploying the API to Railway and the page to Vercel
- `docs/stitch_bangalore_restaurant_ai_recommender/`: the Stitch design the page is built from

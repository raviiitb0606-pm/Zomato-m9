"""HTTP API over the engine (architecture.md §5.6).

Run: uvicorn recommender.api:app
The web UI is at http://127.0.0.1:8000/ and the interactive API docs at /docs.

No CORS: the web UI is served from this same origin, and the Streamlit UI calls the API
from its server process (SRV-09).
"""

import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from recommender.config import Settings, get_settings
from recommender.engine import Engine
from recommender.llm.base import LLMError
from recommender.schemas import Meta, Preferences, RecommendationResponse
from recommender.store import DataNotFoundError

# A full Preferences body is under 2 KB (API-65). Chunked bodies skip this check.
MAX_BODY_BYTES = 16 * 1024
WEB_DIR = Path(__file__).parent / "web"


class StartupError(RuntimeError):
    """The data or the API key is missing, so the API cannot serve."""


router = APIRouter()


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


# Sync on purpose: FastAPI runs it in a thread pool, so a slow LLM call
# doesn't block /health (SRV-07).
@router.post("/recommend")
def recommend(prefs: Preferences, engine: Engine = Depends(get_engine)) -> RecommendationResponse:
    return engine.recommend(prefs)


@router.get("/meta")
def meta(engine: Engine = Depends(get_engine)) -> Meta:
    return Meta.model_validate(engine.store.meta())


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/", include_in_schema=False)
def web_ui() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


async def _body_size_limit(request: Request, call_next):
    size = request.headers.get("content-length", "")
    if size.isdigit() and int(size) > MAX_BODY_BYTES:
        return JSONResponse({"detail": f"Request body is over {MAX_BODY_BYTES} bytes."}, status_code=413)
    return await call_next(request)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # The default handler echoes each bad `input`: a NaN there turns the 422 into a 500,
    # and extras may hold personal data (API-59).
    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)


def _origin_guard(secret: str):
    """Reject requests that didn't come through Vercel. /health stays open for Railway."""
    expected = secret.encode()

    async def check(request: Request, call_next):
        if request.url.path != "/health":
            given = request.headers.get("x-origin-secret", "").encode()
            if not hmac.compare_digest(given, expected):
                return JSONResponse({"detail": "Forbidden."}, status_code=403)
        return await call_next(request)

    return check


async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
    # Starlette re-raises after this, so the traceback still reaches the server log (SRV-06).
    return JSONResponse({"detail": "Internal server error."}, status_code=500)


def create_app(engine: Engine | None = None, settings: Settings | None = None) -> FastAPI:
    """Without `engine` (tests pass a fake one), it is built from settings at startup."""
    settings = settings or get_settings()
    secret = settings.origin_secret.get_secret_value() if settings.origin_secret else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            app.state.engine = engine or Engine.from_settings(settings)
        except (DataNotFoundError, LLMError) as exc:
            raise StartupError(f"API cannot start: {exc}") from None
        yield

    # Behind Vercel the API isn't meant to be browsed, so the interactive docs go too.
    docs = {} if secret is None else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Restaurant Recommender", version="0.1.0", lifespan=lifespan, **docs)
    app.include_router(router)
    # web/static is also what Vercel serves at /static, so the page works on both.
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.middleware("http")(_body_size_limit)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _internal_error)
    if secret is not None:
        app.middleware("http")(_origin_guard(secret))  # added last, so it runs first
    return app


app = create_app()

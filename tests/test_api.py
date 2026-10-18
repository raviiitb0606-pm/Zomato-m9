import json

import pytest
from fastapi.testclient import TestClient

from recommender.api import MAX_BODY_BYTES, StartupError, create_app
from recommender.config import Settings
from recommender.engine import Engine
from recommender.llm.base import LLMError
from recommender.llm.fake import FakeLLMClient, reply_json

# The request body from architecture.md §5.6.
EXAMPLE = {
    "location": "Bangalore", "budget": "medium", "cuisine": ["Italian"],
    "min_rating": 4.0, "extras": "family-friendly, quick service", "top_k": 5,
}
RESPONSE_KEYS = {"summary", "recommendations", "relaxed_constraints", "llm_fallback", "message"}
ITEM_KEYS = {"rank", "id", "name", "locality", "cuisine", "rating", "estimated_cost", "explanation", "explanation_source"}


def strict_json(text: str):
    """Rejects NaN and Infinity, which json.loads accepts by default (ENG-06)."""
    def reject(token):
        raise ValueError(f"invalid JSON constant {token}")
    return json.loads(text, parse_constant=reject)


@pytest.fixture
def fake():
    return FakeLLMClient()  # tests queue replies on fake.replies


@pytest.fixture
def client(store, fake):
    app = create_app(engine=Engine(store, fake))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# --- /recommend --------------------------------------------------------------

def test_example_body_returns_documented_shape(client, fake):
    fake.replies.append(reply_json([1], summary="One Italian pick."))  # r6, the only candidate
    resp = client.post("/recommend", json=EXAMPLE)
    assert resp.status_code == 200
    body = strict_json(resp.text)
    assert set(body) == RESPONSE_KEYS
    assert [set(item) for item in body["recommendations"]] == [ITEM_KEYS]
    assert body["recommendations"][0] == {
        "rank": 1, "id": "r6", "name": "Mid Italian", "locality": "Indiranagar", "cuisine": ["Italian", "Pizza"],
        "rating": 4.0,
        "estimated_cost": 450, "explanation": "Explanation for 1.", "explanation_source": "llm",
    }
    assert body["summary"] == "One Italian pick." and body["llm_fallback"] is False
    assert body["message"] == "Only 1 restaurant matched."


def test_llm_failure_still_returns_200_with_fallback(client, fake):
    fake.replies.append(LLMError("timeout"))
    resp = client.post("/recommend", json={"location": "BTM", "top_k": 3})
    assert resp.status_code == 200
    body = strict_json(resp.text)  # r5 has a null rating: must serialise as null, not NaN
    assert body["llm_fallback"] is True and len(body["recommendations"]) == 3


def test_no_match_returns_empty_list_without_calling_llm(client, fake):
    resp = client.post("/recommend", json={"location": "Paris"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommendations"] == [] and "Bangalore" in body["message"]
    assert fake.calls == []


def test_unknown_fields_are_ignored(client, fake):
    fake.replies.append(reply_json([1]))
    assert client.post("/recommend", json={**EXAMPLE, "debug": True}).status_code == 200


@pytest.mark.parametrize("change", [
    {"location": None},
    {"location": ""},
    {"budget": "cheap"},
    {"budget": 500},
    {"min_rating": 5.5},
    {"min_rating": "high"},
    {"min_rating": float("nan")},
    {"top_k": 0},
    {"top_k": 11},
    {"extras": "x" * 301},
    {"cuisine": 5},
    {"cuisine": [f"c{i}" for i in range(11)]},
])
def test_invalid_preferences_are_422(client, fake, change):
    body = {k: v for k, v in {**EXAMPLE, **change}.items() if v is not None}
    resp = client.post("/recommend", content=json.dumps(body), headers={"content-type": "application/json"})
    assert resp.status_code == 422
    errors = resp.json()["detail"]
    assert errors and all("loc" in e and "input" not in e for e in errors)
    assert fake.calls == []


@pytest.mark.parametrize("content,content_type", [
    ("not json", "application/json"),
    ("", "application/json"),
    ("location=BTM", "application/x-www-form-urlencoded"),
])
def test_bad_body_is_422(client, content, content_type):
    resp = client.post("/recommend", content=content, headers={"content-type": content_type})
    assert resp.status_code == 422


def test_oversized_body_is_413(client, fake):
    resp = client.post("/recommend", json={**EXAMPLE, "padding": "x" * MAX_BODY_BYTES})
    assert resp.status_code == 413 and fake.calls == []


def test_unexpected_error_is_a_generic_500(client, fake):
    fake.replies.append(RuntimeError("boom at /secret/path"))
    resp = client.post("/recommend", json=EXAMPLE)
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error."}


def test_wrong_method_is_405(client):
    assert client.get("/recommend").status_code == 405


# --- /meta and /health -------------------------------------------------------

def test_meta_returns_form_values_only(client):
    body = client.get("/meta").json()
    assert set(body) == {"cities", "localities", "cuisines", "budget_thresholds"}
    assert body["cities"] == ["Bangalore"]
    assert "Indiranagar" in body["localities"] and "Italian" in body["cuisines"]
    assert body["budget_thresholds"] == {"low_max": 300, "medium_max": 500}


def test_web_page_and_assets_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert '/static/app.css' in page.text and '/static/app.js' in page.text
    for asset in ("/static/app.css", "/static/app.js"):
        assert client.get(asset).status_code == 200
    assert client.get("/static/index.html").status_code == 404  # only the assets folder is mounted


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_docs_page_is_served(client):
    assert client.get("/docs").status_code == 200
    assert "/recommend" in client.get("/openapi.json").json()["paths"]


# --- rate limit ----------------------------------------------------------------

@pytest.fixture
def limited(store, fake):
    app = create_app(engine=Engine(store, fake), settings=settings(rate_limit_per_minute=2, rate_limit_per_day=0))
    with TestClient(app) as c:
        yield c


def test_third_search_in_a_minute_gets_429(limited, fake):
    fake.replies.extend([LLMError("x"), LLMError("x")])
    for _ in range(2):
        assert limited.post("/recommend", json={"location": "BTM"}).status_code == 200
    resp = limited.post("/recommend", json={"location": "BTM"})
    assert resp.status_code == 429 and resp.json() == {"detail": "Too many searches. Try again in a minute."}
    assert 1 <= int(resp.headers["retry-after"]) <= 60
    assert len(fake.calls) == 2  # the refused search never reached the engine


def test_limits_are_per_visitor(limited, fake):
    fake.replies.extend([LLMError("x")] * 3)
    for ip in ("1.1.1.1", "1.1.1.1", "2.2.2.2"):
        assert limited.post("/recommend", json={"location": "BTM"}, headers={"x-real-ip": ip}).status_code == 200
    assert limited.post("/recommend", json={"location": "BTM"}, headers={"x-real-ip": "1.1.1.1"}).status_code == 429


def test_invalid_input_and_other_routes_are_not_counted(limited, fake):
    for _ in range(3):
        assert limited.post("/recommend", json={"location": ""}).status_code == 422
        assert limited.get("/meta").status_code == 200
    fake.replies.append(LLMError("x"))
    assert limited.post("/recommend", json={"location": "BTM"}).status_code == 200


def test_zero_limits_turn_the_limiter_off(store, fake):
    app = create_app(engine=Engine(store, fake), settings=settings(rate_limit_per_minute=0, rate_limit_per_day=0))
    assert app.state.limiter is None


# --- origin secret -----------------------------------------------------------

SECRET = "s3cret-value"


@pytest.fixture
def guarded(store, fake):
    app = create_app(engine=Engine(store, fake), settings=settings(origin_secret=SECRET))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("headers", [{}, {"x-origin-secret": "wrong"}, {"x-origin-secret": ""}])
@pytest.mark.parametrize("method,path", [("get", "/meta"), ("post", "/recommend"), ("get", "/")])
def test_calls_without_the_secret_are_refused(guarded, fake, headers, method, path):
    resp = getattr(guarded, method)(path, headers=headers, **({"json": EXAMPLE} if method == "post" else {}))
    assert resp.status_code == 403 and resp.json() == {"detail": "Forbidden."}
    assert fake.calls == []


def test_calls_with_the_secret_work(guarded, fake):
    fake.replies.append(reply_json([1]))
    ok = {"x-origin-secret": SECRET}
    assert guarded.get("/meta", headers=ok).status_code == 200
    assert guarded.post("/recommend", json=EXAMPLE, headers=ok).status_code == 200


def test_health_needs_no_secret(guarded):
    assert guarded.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
def test_docs_are_off_behind_the_secret(guarded, path):
    assert guarded.get(path, headers={"x-origin-secret": SECRET}).status_code == 404


def test_blank_secret_means_no_check(store, fake):
    with TestClient(create_app(engine=Engine(store, fake), settings=settings(origin_secret="  "))) as c:
        assert c.get("/meta").status_code == 200 and c.get("/docs").status_code == 200


# --- startup -----------------------------------------------------------------

def settings(**kw):
    # Explicit values beat a developer's real .env and shell variables.
    return Settings(_env_file=None, **{"llm_api_key": "gsk_test", **kw})


def test_startup_builds_engine_from_settings(data_dir):
    with TestClient(create_app(settings=settings(data_dir=data_dir, shortlist_size=7))) as c:
        assert c.get("/meta").status_code == 200
        assert c.app.state.engine.shortlist_size == 7


def test_startup_fails_without_data(tmp_path):
    with pytest.raises(StartupError, match="ingestion.cli"):
        with TestClient(create_app(settings=settings(data_dir=tmp_path))):
            pass


def test_startup_fails_without_api_key(data_dir):
    with pytest.raises(StartupError, match="LLM_API_KEY is not set"):
        with TestClient(create_app(settings=settings(data_dir=data_dir, llm_api_key=None))):
            pass

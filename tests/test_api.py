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


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_docs_page_is_served(client):
    assert client.get("/docs").status_code == 200
    assert "/recommend" in client.get("/openapi.json").json()["paths"]


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

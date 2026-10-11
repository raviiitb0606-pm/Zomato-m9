import json
import logging

import pytest

from recommender.config import Settings
from recommender.engine import (
    FALLBACK_SUMMARY, MAX_EXPLANATION_CHARS, Engine, main, template_explanation,
)
from recommender.llm.base import LLMError, MalformedReplyError
from recommender.llm.fake import FakeLLMClient, reply_json
from recommender.schemas import Preferences

BTM = Preferences(location="BTM", top_k=3)


def preranked(store, prefs=BTM):
    return [r.id for r in store.query(prefs).restaurants]


def engine(store, *replies):
    fake = FakeLLMClient(*replies)
    return Engine(store, fake), fake


def ids(resp):
    return [r.id for r in resp.recommendations]


def reply(*items, summary="LLM summary."):
    return json.dumps({"summary": summary,
                       "ranking": [{"id": i, "explanation": e} for i, e in items]})


# --- happy path --------------------------------------------------------------

def test_valid_reply_uses_model_order_and_store_facts(store):
    eng, fake = engine(store, reply(("r3", "Cheap and South Indian."), ("r1", "Very popular."),
                                    ("r7", "Chinese, high rating.")))
    resp = eng.recommend(BTM)
    assert ids(resp) == ["r3", "r1", "r7"]  # the model's order, not the pre-ranking
    assert [r.rank for r in resp.recommendations] == [1, 2, 3]
    first = resp.recommendations[0]
    assert (first.name, first.cuisine, first.rating, first.estimated_cost) == ("Cheap Eats", ["South Indian"], 3.8, 150)
    assert first.explanation == "Cheap and South Indian." and first.explanation_source == "llm"
    assert resp.summary == "LLM summary." and resp.llm_fallback is False
    assert len(fake.calls) == 1


def test_model_cannot_change_facts(store):
    eng, _ = engine(store, reply(("r1", "Rated 5.0 and free!"), ("r2", "x"), ("r3", "y")))
    rec = eng.recommend(BTM).recommendations[0]
    assert rec.rating == 4.5 and rec.estimated_cost == 400  # from the store, not the text


def test_extra_picks_are_cut_to_top_k(store):
    eng, _ = engine(store, reply_json(["r1", "r2", "r3", "r5", "r7"]))
    assert ids(eng.recommend(BTM)) == ["r1", "r2", "r3"]


# --- empty shortlist ---------------------------------------------------------

@pytest.mark.parametrize("prefs", [
    Preferences(location="Delhi"),
    Preferences(location="BTM", cuisine=["Martian"]),
    Preferences(location="Indiranagar", budget="high", cuisine=["Pizza"], min_rating=4.7),
])
def test_empty_shortlist_never_calls_llm(store, prefs):
    eng, fake = engine(store)  # no replies queued: any call would fail the test
    resp = eng.recommend(prefs)
    assert resp.recommendations == [] and resp.message and fake.calls == []


# --- malformed replies -------------------------------------------------------

def test_malformed_then_valid_retries_once_with_the_error(store):
    eng, fake = engine(store, "not json", reply_json(["r2", "r1", "r3"]))
    resp = eng.recommend(BTM)
    assert ids(resp) == ["r2", "r1", "r3"] and resp.llm_fallback is False
    assert len(fake.calls) == 2
    assert "could not be used" in fake.calls[1]["user"] and fake.calls[1]["user"].startswith(fake.calls[0]["user"])


def test_malformed_twice_falls_back_to_preranking(store):
    eng, fake = engine(store, "not json", '{"summary": "x"}')
    resp = eng.recommend(BTM)
    assert ids(resp) == preranked(store)[:3]
    assert resp.llm_fallback is True and resp.summary == FALLBACK_SUMMARY
    assert {r.explanation_source for r in resp.recommendations} == {"template"}
    assert len(fake.calls) == 2


def test_provider_schema_rejection_gets_the_retry(store):
    eng, fake = engine(store, MalformedReplyError("did not match the JSON schema"), reply_json(["r2", "r1", "r3"]))
    resp = eng.recommend(BTM)
    assert ids(resp) == ["r2", "r1", "r3"] and resp.llm_fallback is False
    assert len(fake.calls) == 2 and "did not match the JSON schema" in fake.calls[1]["user"]


def test_provider_schema_rejection_twice_falls_back(store):
    eng, fake = engine(store, MalformedReplyError("a"), MalformedReplyError("b"))
    assert eng.recommend(BTM).llm_fallback is True and len(fake.calls) == 2


def test_retry_prompt_stays_short(store):
    eng, fake = engine(store, "x" * 5000, reply_json(["r1", "r2", "r3"]))
    eng.recommend(BTM)
    assert len(fake.calls[1]["user"]) - len(fake.calls[0]["user"]) < 400


# --- LLM errors --------------------------------------------------------------

def test_llm_error_falls_back_without_a_second_call(store):
    eng, fake = engine(store, LLMError("timeout"))
    resp = eng.recommend(BTM)
    assert ids(resp) == preranked(store)[:3] and resp.llm_fallback is True
    assert len(fake.calls) == 1


def test_error_on_retry_falls_back(store):
    eng, fake = engine(store, "garbage", LLMError("rate limited"))
    assert eng.recommend(BTM).llm_fallback is True and len(fake.calls) == 2


def test_unexpected_exceptions_propagate(store):
    eng, _ = engine(store, RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        eng.recommend(BTM)


# --- id validation -----------------------------------------------------------

def test_unknown_ids_dropped_and_topped_up_from_preranking(store, caplog):
    eng, _ = engine(store, reply(("r2", "Good."), ("fake-bistro", "Invented."), ("r4", "Wrong area.")))
    with caplog.at_level(logging.INFO, logger="recommender.engine"):
        resp = eng.recommend(BTM)
    top_up = [i for i in preranked(store) if i != "r2"][:2]
    assert ids(resp) == ["r2", *top_up]
    assert [r.explanation_source for r in resp.recommendations] == ["llm", "template", "template"]
    assert resp.llm_fallback is False and resp.summary == "LLM summary."
    assert "dropped 2" in caplog.text


def test_duplicate_ids_keep_the_first(store):
    eng, _ = engine(store, reply(("r1", "First."), ("r1", "Again."), ("r2", "Second.")))
    resp = eng.recommend(BTM)
    assert ids(resp)[:2] == ["r1", "r2"] and resp.recommendations[0].explanation == "First."
    assert len(set(ids(resp))) == 3


def test_ids_matched_ignoring_case_and_spaces(store):
    eng, _ = engine(store, reply_json([" R1 ", "r2", "R3"]))
    assert ids(eng.recommend(BTM)) == ["r1", "r2", "r3"]


def test_all_ids_unknown_counts_as_fallback(store):
    eng, _ = engine(store, reply_json(["x", "y", "z"]))
    resp = eng.recommend(BTM)
    assert ids(resp) == preranked(store)[:3] and resp.llm_fallback is True and resp.summary == FALLBACK_SUMMARY


# --- explanations ------------------------------------------------------------

def test_blank_explanation_gets_a_template(store):
    eng, _ = engine(store, reply(("r1", "   "), ("r2", "Fine."), ("r3", "Fine.")))
    rec = eng.recommend(BTM).recommendations[0]
    assert rec.explanation_source == "template" and rec.explanation.startswith("Rated 4.5")


def test_long_explanation_trimmed_at_a_sentence(store):
    long = "Great pick. " * 80
    eng, _ = engine(store, reply(("r1", long), ("r2", "x"), ("r3", "y")))
    text = eng.recommend(BTM).recommendations[0].explanation
    assert len(text) <= MAX_EXPLANATION_CHARS and text.endswith(".")


@pytest.mark.parametrize("rid,expected", [
    ("r1", "Rated 4.5 from 2,000 votes; serves North Indian, Chinese; about ₹400 for two; in BTM."),
    ("r5", "Not yet rated; serves North Indian; about ₹300 for two; in BTM."),
    ("r8", "Rated 4.1 from 50 votes; serves Biryani; in HSR."),
])
def test_template_explanation_omits_missing_values(store, rid, expected):
    assert template_explanation(store.get([rid])[0]) == expected


# --- pass-through and serialisation -----------------------------------------

def test_relaxed_constraints_and_message_pass_through(store):
    prefs = Preferences(location="Indiranagar", budget="high", cuisine=["Pizza"], min_rating=4.3)
    eng, _ = engine(store, reply_json(["r6"]))
    resp = eng.recommend(prefs)
    assert resp.relaxed_constraints == ["min_rating relaxed from 4.3 to 3.8",
                                        "budget relaxed from high to high or medium"]
    assert resp.message == "Only 1 restaurant matched." and ids(resp) == ["r6"]


def test_json_has_nulls_not_nan(store):
    eng, _ = engine(store, LLMError("down"))
    resp = eng.recommend(Preferences(location="BTM", top_k=5))
    data = json.loads(resp.model_dump_json())  # strict: NaN would be invalid JSON
    unrated = next(r for r in data["recommendations"] if r["id"] == "r5")
    assert unrated["rating"] is None and "NaN" not in resp.model_dump_json()


# --- CLI ---------------------------------------------------------------------

def test_cli_prints_results_and_checks_facts(store, capsys):
    eng, _ = engine(store, reply_json(["r1", "r7", "r2"]))
    assert main(["--location", "BTM", "--top-k", "3"], engine=eng) == 0
    out = capsys.readouterr().out
    assert "1. Popular" in out and "facts match dataset: yes" in out and "llm_fallback=False" in out


def test_cli_rejects_bad_input(store):
    assert main(["--location", "BTM", "--top-k", "50"], engine=engine(store)[0]) == 2

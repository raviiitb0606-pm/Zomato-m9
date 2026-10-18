import logging

import pytest

from recommender.cache import ResponseCache, cache_key
from recommender.config import Settings
from recommender.engine import Engine
from recommender.llm.base import LLMError
from recommender.llm.fake import FakeLLMClient, reply_json
from recommender.prompt import PROMPT_VERSION
from recommender.schemas import Preferences, RecommendationResponse

BTM = Preferences(location="BTM", top_k=3)


def engine(store, *replies, size=8):
    fake = FakeLLMClient(*replies)
    return Engine(store, fake, cache=ResponseCache(size)), fake


def test_repeat_search_is_served_from_the_cache(store):
    eng, fake = engine(store, reply_json([1, 2, 3]))
    first = eng.recommend(BTM)
    assert eng.recommend(BTM) == first
    assert len(fake.calls) == 1


def test_case_spacing_and_cuisine_order_share_a_key():  # CAC-01
    a = Preferences(location="BTM", cuisine=["Chinese", "North Indian"], extras="quick  service")
    b = Preferences(location=" btm ", cuisine=["north indian", "CHINESE"], extras="Quick service")
    assert cache_key(a, "m") == cache_key(b, "m")


@pytest.mark.parametrize("change", [
    {"extras": "family-friendly"},  # CAC-02
    {"budget": "low"},
    {"min_rating": 4.0},
    {"top_k": 5},
    {"cuisine": ["Chinese"]},
])
def test_different_searches_get_different_keys(change):
    assert cache_key(BTM, "m") != cache_key(BTM.model_copy(update=change), "m")


def test_key_includes_prompt_version_and_model():  # CAC-06
    key = cache_key(BTM, "openai/gpt-oss-120b")
    assert PROMPT_VERSION in key and key != cache_key(BTM, "openai/gpt-oss-20b")


def test_fallback_answers_are_not_cached(store):  # CAC-03
    eng, fake = engine(store, LLMError("down"), reply_json([1, 2, 3]))
    assert eng.recommend(BTM).llm_fallback is True
    assert eng.recommend(BTM).llm_fallback is False  # the LLM was asked again
    assert len(fake.calls) == 2


def test_empty_results_are_not_cached(store):  # CAC-04
    eng, _ = engine(store)
    eng.recommend(Preferences(location="Delhi"))
    assert len(eng.cache) == 0


def test_least_recently_used_entry_is_evicted():  # CAC-07
    cache = ResponseCache(2)
    for name in ("a", "b"):
        cache.put((name,), RecommendationResponse(summary=name))
    cache.get(("a",))  # a is now the most recent
    cache.put(("c",), RecommendationResponse(summary="c"))
    assert cache.get(("b",)) is None and cache.get(("a",)).summary == "a" and len(cache) == 2


def test_callers_cannot_change_a_cached_answer(store):
    eng, _ = engine(store, reply_json([1, 2, 3]))
    eng.recommend(BTM).recommendations.clear()
    assert len(eng.recommend(BTM).recommendations) == 3


def test_each_search_logs_its_shape_but_not_the_extras(store, caplog):
    eng, _ = engine(store, reply_json([1, 2, 3]))
    prefs = BTM.model_copy(update={"extras": "call me on 98450 12345"})
    with caplog.at_level(logging.INFO, logger="recommender.engine"):
        eng.recommend(prefs)
        eng.recommend(prefs)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("search ")]
    assert len(lines) == 2
    assert "location='BTM'" in lines[0] and "extras_chars=22" in lines[0] and "shortlist=5" in lines[0]
    assert "fallback=False cache=miss" in lines[0] and "cache=hit" in lines[1] and "shortlist=-" in lines[1]
    assert "98450" not in caplog.text


def test_settings_size_zero_turns_the_cache_off(monkeypatch, data_dir):
    monkeypatch.setattr("recommender.llm.groq_client.GroqClient.from_settings", lambda s: FakeLLMClient())
    s = Settings(_env_file=None, data_dir=data_dir)
    assert Engine.from_settings(s.model_copy(update={"response_cache_size": 0})).cache is None
    assert Engine.from_settings(s).cache.max_size == 256

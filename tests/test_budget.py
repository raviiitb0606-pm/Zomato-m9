from datetime import date

import pytest

from recommender.config import Settings
from recommender.engine import Engine
from recommender.llm.base import LLMError
from recommender.llm.budget import BudgetedLLMClient, BudgetExceeded
from recommender.llm.fake import FakeLLMClient, reply_json
from recommender.schemas import Preferences


class Clock:
    def __init__(self):
        self.t, self.day = 1000.0, date(2026, 10, 18)

    def __call__(self):
        return self.t


def budgeted(per_minute=2, per_day=5, replies=10):
    clock = Clock()
    fake = FakeLLMClient(*["ok"] * replies)
    return BudgetedLLMClient(fake, per_minute, per_day, clock=clock, today=lambda: clock.day), fake, clock


def call(client):
    return client.complete("S", "U", {}, 100)


def test_passes_calls_through_with_the_cap():
    client, fake, _ = budgeted()
    assert call(client) == "ok" and fake.calls[0]["max_tokens"] == 100


def test_per_minute_cap_refuses_without_calling_the_llm():
    client, fake, clock = budgeted(per_minute=2)
    call(client), call(client)
    with pytest.raises(BudgetExceeded, match="2 calls a minute"):
        call(client)
    assert len(fake.calls) == 2
    clock.t += 60  # the window has moved on
    assert call(client) == "ok"


def test_per_day_cap_resets_at_midnight_utc():
    client, _, clock = budgeted(per_minute=0, per_day=2)
    call(client), call(client)
    with pytest.raises(BudgetExceeded, match="2 calls today"):
        call(client)
    clock.day = date(2026, 10, 19)
    assert call(client) == "ok"


def test_zero_means_no_cap():
    client, fake, _ = budgeted(per_minute=0, per_day=0, replies=20)
    for _ in range(20):
        call(client)
    assert len(fake.calls) == 20


def test_budget_exceeded_is_an_llm_error_so_the_engine_falls_back(store):
    client, fake, _ = budgeted(per_minute=1)
    eng = Engine(store, client)
    fake.replies[:] = [reply_json([1, 2, 3])]
    assert issubclass(BudgetExceeded, LLMError)
    assert eng.recommend(Preferences(location="BTM", top_k=3)).llm_fallback is False
    resp = eng.recommend(Preferences(location="HSR", top_k=1))  # over the cap
    assert resp.llm_fallback is True and len(fake.calls) == 1


def test_wrapper_exposes_the_inner_clients_attributes():
    fake = FakeLLMClient()
    fake.model = "openai/gpt-oss-120b"
    assert BudgetedLLMClient(fake, 1, 1).model == "openai/gpt-oss-120b"


def test_engine_from_settings_wraps_the_client(monkeypatch, data_dir):
    monkeypatch.setattr("recommender.llm.groq_client.GroqClient.from_settings", lambda s: FakeLLMClient())
    s = Settings(_env_file=None, data_dir=data_dir)
    llm = Engine.from_settings(s).llm
    assert isinstance(llm, BudgetedLLMClient) and (llm.per_minute, llm.per_day) == (3, 100)
    off = s.model_copy(update={"llm_calls_per_minute": 0, "llm_calls_per_day": 0})
    assert isinstance(Engine.from_settings(off).llm, FakeLLMClient)

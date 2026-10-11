import logging
from types import SimpleNamespace

import groq
import httpx
import pytest

from recommender.config import Settings
from recommender.llm.base import LLMError
from recommender.llm.fake import FakeLLMClient, reply_json
from recommender.llm.groq_client import GroqClient
from recommender.prompt import RESPONSE_SCHEMA

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def fake_sdk(content='{"summary": "", "ranking": []}', finish="stop", exc=None):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if exc:
            raise exc
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40),
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def client(model="openai/gpt-oss-20b", **sdk_kw):
    sdk, calls = fake_sdk(**sdk_kw)
    return GroqClient("gsk_test", model, reasoning_effort="low", max_completion_tokens=900, client=sdk), calls


def test_gpt_oss_gets_strict_schema_and_reasoning_controls():
    c, calls = client()
    c.complete("SYS", "USER", RESPONSE_SCHEMA)
    kw = calls[0]
    assert kw["model"] == "openai/gpt-oss-20b"
    assert kw["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert kw["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "recommendations", "strict": True, "schema": RESPONSE_SCHEMA},
    }
    assert kw["reasoning_effort"] == "low" and kw["include_reasoning"] is False
    assert kw["max_completion_tokens"] == 900
    assert "temperature" not in kw  # model default (Groq advises 0.5-0.7 for reasoning models)


def test_other_models_get_json_mode_only():
    c, calls = client(model="llama-3.3-70b-versatile")
    c.complete("SYS", "USER", RESPONSE_SCHEMA)
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in calls[0] and "include_reasoning" not in calls[0]


def test_returns_content_and_records_usage():
    c, _ = client(content='{"ok": 1}')
    assert c.complete("S", "U", {}) == '{"ok": 1}'
    assert c.last_usage.prompt_tokens == 120 and c.last_latency_s is not None


def test_usage_logged_without_prompt_text(caplog):
    c, _ = client()
    with caplog.at_level(logging.INFO, logger="recommender.llm.groq_client"):
        c.complete("SYS", "secret user extras", {})
    assert "prompt_tokens=120" in caplog.text and "completion_tokens=40" in caplog.text
    assert "secret user extras" not in caplog.text


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_reply_is_an_error(content):
    c, _ = client(content=content, finish="length")
    with pytest.raises(LLMError, match="finish_reason=length"):
        c.complete("S", "U", {})


@pytest.mark.parametrize("exc", [
    groq.APIConnectionError(request=REQUEST),
    groq.APITimeoutError(request=REQUEST),
    groq.RateLimitError("rate limited", response=httpx.Response(429, request=REQUEST), body=None),
    groq.AuthenticationError("bad key", response=httpx.Response(401, request=REQUEST), body=None),
])
def test_sdk_errors_become_llm_errors(exc):
    c, _ = client(exc=exc)
    with pytest.raises(LLMError) as info:
        c.complete("S", "U", {})
    assert info.value.__cause__ is exc


def test_real_sdk_configured_with_one_retry_and_timeout():
    c = GroqClient("gsk_test", "openai/gpt-oss-20b", timeout_s=12)
    assert c._client.max_retries == 1 and c._client.timeout == 12


def test_from_settings_needs_a_key():
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        GroqClient.from_settings(Settings(_env_file=None, llm_api_key=None))


def test_from_settings_uses_config():
    s = Settings(_env_file=None, llm_api_key="gsk_x", llm_model="openai/gpt-oss-120b",
                 llm_reasoning_effort="medium", llm_max_completion_tokens=700, llm_timeout_s=9)
    c = GroqClient.from_settings(s)
    assert (c.model, c.reasoning_effort, c.max_completion_tokens) == ("openai/gpt-oss-120b", "medium", 700)
    assert c._client.timeout == 9


# --- FakeLLMClient -----------------------------------------------------------

def test_fake_client_replays_in_order_and_records_calls():
    fake = FakeLLMClient(reply_json(["a"]), LLMError("boom"))
    assert '"a"' in fake.complete("S", "U", {"k": 1})
    with pytest.raises(LLMError):
        fake.complete("S2", "U2", {})
    assert [c["user"] for c in fake.calls] == ["U", "U2"]
    with pytest.raises(AssertionError):
        fake.complete("S", "U", {})

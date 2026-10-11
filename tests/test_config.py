import pytest
from pydantic import ValidationError

from recommender.config import PROJECT_ROOT, Settings

ENV_VARS = [
    "LLM_API_KEY", "GROQ_API_KEY", "LLM_MODEL", "LLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_S",
    "LLM_REASONING_EFFORT", "LLM_MAX_COMPLETION_TOKENS", "CANDIDATE_CAP", "SHORTLIST_SIZE", "DATA_DIR",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**env):
    # _env_file=None keeps a developer's real .env out of the tests.
    return Settings(_env_file=None, **env)


def test_defaults():
    s = make()
    assert s.llm_api_key is None
    assert s.llm_model == "openai/gpt-oss-20b"
    assert s.llm_reasoning_effort == "low"
    assert s.shortlist_size == 20
    assert s.data_dir == PROJECT_ROOT / "data"


@pytest.mark.parametrize("env,field,expected", [
    ({"LLM_API_KEY": "gsk_a"}, "llm_api_key", "gsk_a"),
    ({"GROQ_API_KEY": "gsk_b"}, "llm_api_key", "gsk_b"),
    ({"LLM_TIMEOUT_SECONDS": "12"}, "llm_timeout_s", 12.0),
    ({"LLM_TIMEOUT_S": "13"}, "llm_timeout_s", 13.0),
    ({"CANDIDATE_CAP": "12"}, "shortlist_size", 12),
    ({"SHORTLIST_SIZE": "11"}, "shortlist_size", 11),
    ({"LLM_MODEL": "openai/gpt-oss-120b"}, "llm_model", "openai/gpt-oss-120b"),
    ({"LLM_MAX_COMPLETION_TOKENS": "512"}, "llm_max_completion_tokens", 512),
])
def test_reads_env_names_and_fallbacks(monkeypatch, env, field, expected):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    value = getattr(make(), field)
    assert (value.get_secret_value() if field == "llm_api_key" else value) == expected


def test_relative_data_dir_resolves_from_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # CFG-04: cwd must not matter
    assert make(data_dir="data").data_dir == PROJECT_ROOT / "data"


@pytest.mark.parametrize("field,value", [
    ("shortlist_size", 0),
    ("shortlist_size", 51),
    ("llm_timeout_s", 0),
    ("shortlist_size", "lots"),
    ("llm_reasoning_effort", "extreme"),
    ("llm_max_completion_tokens", 10),
])
def test_rejects_bad_values(field, value):
    with pytest.raises(ValidationError):
        make(**{field: value})


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_api_key_counts_as_missing(monkeypatch, blank):
    monkeypatch.setenv("LLM_API_KEY", blank)
    assert make().llm_api_key is None


def test_api_key_hidden_in_repr():
    s = make(llm_api_key="gsk_secret-value")
    assert "gsk_secret-value" not in repr(s)
    assert s.llm_api_key.get_secret_value() == "gsk_secret-value"

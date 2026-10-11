import pytest
from pydantic import ValidationError

from recommender.config import PROJECT_ROOT, Settings

ENV_VARS = ["ANTHROPIC_API_KEY", "LLM_MODEL", "SHORTLIST_SIZE", "DATA_DIR", "LLM_TIMEOUT_S"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**env):
    # _env_file=None keeps a developer's real .env out of the tests.
    return Settings(_env_file=None, **env)


def test_defaults():
    s = make()
    assert s.anthropic_api_key is None
    assert s.shortlist_size == 20
    assert s.data_dir == PROJECT_ROOT / "data"


def test_reads_env(monkeypatch):
    monkeypatch.setenv("SHORTLIST_SIZE", "12")
    monkeypatch.setenv("LLM_MODEL", "some-model")
    s = make()
    assert s.shortlist_size == 12
    assert s.llm_model == "some-model"


def test_relative_data_dir_resolves_from_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # CFG-04: cwd must not matter
    assert make(data_dir="data").data_dir == PROJECT_ROOT / "data"


@pytest.mark.parametrize("field,value", [
    ("shortlist_size", 0),
    ("shortlist_size", 51),
    ("llm_timeout_s", 0),
    ("shortlist_size", "lots"),
])
def test_rejects_bad_values(field, value):
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_api_key_hidden_in_repr():
    s = make(anthropic_api_key="sk-secret-value")
    assert "sk-secret-value" not in repr(s)
    assert s.anthropic_api_key.get_secret_value() == "sk-secret-value"

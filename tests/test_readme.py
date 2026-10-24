"""The README quotes the live prompt and schema; this keeps it from going stale."""

import json

from recommender.config import PROJECT_ROOT
from recommender.prompt import PROMPT_VERSION, RESPONSE_SCHEMA, SYSTEM_PROMPT

README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_quotes_the_current_system_prompt():
    assert SYSTEM_PROMPT.rstrip("\n") in README
    assert f"### System prompt (v{PROMPT_VERSION})" in README
    assert f'PROMPT_VERSION = "{PROMPT_VERSION}"' in README


def test_readme_quotes_the_current_response_schema():
    assert json.dumps(RESPONSE_SCHEMA, indent=2) in README

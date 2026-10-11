"""UI tests: the real Streamlit script, talking to the real API app with a fake LLM."""

import importlib.util
import time

import httpx
import pytest
import streamlit as st
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from recommender.api import create_app
from recommender.config import PROJECT_ROOT
from recommender.engine import Engine
from recommender.llm.base import LLMError
from recommender.llm.fake import FakeLLMClient, reply_json

APP = str(PROJECT_ROOT / "app" / "streamlit_app.py")

# Importing runs only the helpers: the page itself is behind `if __name__ == "__main__"`.
_spec = importlib.util.spec_from_file_location("streamlit_app", APP)
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)


@pytest.fixture
def fake():
    return FakeLLMClient()


@pytest.fixture
def api(monkeypatch, store, fake):
    """Point the app's httpx.Client at the API app in-process. Returns a switch to take it down."""
    app = create_app(engine=Engine(store, fake))
    state = {"up": True}

    def client(base_url, timeout):
        if not state["up"]:
            raise httpx.ConnectError("connection refused")
        return TestClient(app, base_url=base_url, raise_server_exceptions=False)

    monkeypatch.setattr(httpx, "Client", client)
    st.cache_data.clear()
    return state


def page():
    return AppTest.from_file(APP, default_timeout=10).run()


def search(at, location="BTM", **fields):
    at.selectbox[0].set_value(location)
    if "budget" in fields:
        at.radio[0].set_value(fields["budget"])
    if "cuisine" in fields:
        at.multiselect[0].set_value(fields["cuisine"])
    if "min_rating" in fields:
        at.slider[0].set_value(fields["min_rating"])
    at.button[0].click()
    return at.run()


def text(at) -> str:
    return "\n".join(e.value for kind in ("markdown", "info", "warning", "error", "caption")
                     for e in getattr(at, kind))


# --- form --------------------------------------------------------------------

def test_form_is_filled_from_meta(api):
    at = page()
    assert not at.exception
    assert at.selectbox[0].options[:2] == ["Bangalore (all areas)", "BTM"]
    assert at.radio[0].options == ["Any", "Low", "Medium", "High"]
    assert "Italian" in at.multiselect[0].options
    assert at.text_area[0].max_chars == 300


def test_meta_failure_shows_error_and_no_form(api):
    api["up"] = False
    at = page()
    assert "Can't reach the recommendation server" in at.error[0].value
    assert not at.selectbox and at.button[0].label == "Retry"


# --- results -----------------------------------------------------------------

def test_normal_search_shows_summary_and_every_card_field(api, fake):
    fake.replies.append(reply_json([1, 2, 3], summary="Three good picks."))
    at = search(page())
    assert not at.exception and not at.error
    out = text(at)
    assert "Three good picks\\." in out
    assert "**1\\. Popular**" in out
    assert "**Cuisine:** North Indian, Chinese" in out
    assert "**Rating:** 4.5 / 5" in out and "**Estimated cost for two:** ₹400" in out
    assert "Explanation for 1\\." in out
    assert [m.value[:6] for m in at.markdown if m.value.startswith("**")
            and m.value[2:3].isdigit()] == [f"**{i}\\. " for i in range(1, 6)]  # 3 picks, topped up to top_k
    assert at.button[0].disabled is False  # usable again after the search


def test_null_rating_and_cost_are_spelled_out(api, fake):
    fake.replies.extend([LLMError("down"), LLMError("down")])
    out = text(search(page()))  # BTM has five places, r5 unrated
    assert "**Rating:** not rated" in out
    out = text(search(page(), location="HSR"))
    assert "**Estimated cost for two:** not available" in out
    assert "None" not in out and "nan" not in out


def test_relaxation_is_stated_above_results(api, fake):
    fake.replies.append(reply_json([1]))
    at = search(page(), location="Indiranagar", budget="High", cuisine=["Pizza"], min_rating=4.3)
    assert "minimum rating lowered from 4\\.3 to 3\\.8" in at.warning[0].value
    assert "budget widened from high to high or medium" in at.warning[0].value
    assert "Only 1 restaurant matched" in text(at)


def test_no_result_shows_a_message(api, fake):
    at = search(page(), location="Indiranagar", cuisine=["Biryani"])
    assert "No restaurants" in at.info[0].value
    assert fake.calls == []


def test_fallback_says_descriptions_are_generic(api, fake):
    fake.replies.append(LLMError("timeout"))
    out = text(search(page()))
    assert "AI ranking is unavailable" in out and "**1\\." in out


@pytest.mark.parametrize("seconds_since_last,calls", [(0.2, 1), (10, 2)])
def test_click_right_after_a_search_is_dropped(api, fake, seconds_since_last, calls):
    fake.replies.extend([reply_json([1, 2, 3]), reply_json([1])])
    at = search(page())
    # A double-click's second click is processed just after the first search ends.
    at.session_state["search_ended_at"] = time.monotonic() - seconds_since_last
    at.button[0].click()
    at = at.run()
    assert len(fake.calls) == calls and at.button[0].disabled is False


def test_api_down_at_search_keeps_the_form(api):
    at = page()
    api["up"] = False
    at = search(at, location="Indiranagar", budget="High")
    assert "Can't reach the recommendation server" in at.error[0].value
    assert at.selectbox[0].value == "Indiranagar" and at.radio[0].value == "High"
    assert at.button[0].disabled is False


def test_new_search_error_clears_old_results(api, fake):
    fake.replies.append(reply_json([1, 2, 3]))
    at = search(page())
    api["up"] = False
    at.session_state["search_ended_at"] = time.monotonic() - 10  # a real pause between searches
    at = search(at)
    assert at.error and "Popular" not in text(at)


# --- helpers -----------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "Ignore *All* Rules_Cafe #1",
    "[click](http://evil.example) <script>alert(1)</script>",
    "Price $5 to $10 | `code` ~~gone~~ :red[x]",
])
def test_plain_escapes_every_markdown_character(raw):
    escaped = ui.plain(raw)
    assert escaped.replace("\\", "") == raw.replace("\\", "")
    for ch in "*_#[]()<>$|`~:":
        assert ch not in escaped.replace(f"\\{ch}", "")


def test_budget_captions_use_thresholds():
    assert ui.budget_captions({"low_max": 300, "medium_max": 500}) == ["", "up to ₹300", "₹301–500", "over ₹500"]


@pytest.mark.parametrize("value,fn,expected", [
    (None, "format_rating", "not rated"),
    (4.0, "format_rating", "4 / 5"),
    (None, "format_cost", "not available"),
    (1500, "format_cost", "₹1,500"),
])
def test_formatting(value, fn, expected):
    assert getattr(ui, fn)(value) == expected

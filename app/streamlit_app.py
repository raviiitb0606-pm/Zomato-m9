"""Streamlit UI over the API (architecture.md §5.7).

Start the API first (uvicorn recommender.api:app), then: streamlit run app/streamlit_app.py
API_BASE_URL (environment variable) points at the API; default http://127.0.0.1:8000.
"""

import os
import re
import time

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
# The API's worst case is an LLM timeout plus retries; past this the user gets a message, not a spinner (UI-05).
REQUEST_TIMEOUT_S = 60
# Same limits as Preferences, so the API never has to reject what the form allows.
MAX_EXTRAS = 300
MAX_CUISINES = 10
BUDGETS = {"Any": None, "Low": "low", "Medium": "medium", "High": "high"}
DOUBLE_CLICK_WINDOW_S = 1.5

_MARKDOWN_CHARS = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


class ApiError(Exception):
    """A problem to show the user as is."""


def plain(text: str) -> str:
    """Dataset and model text shown literally: no markdown, links, HTML or maths (UI-30, UI-31)."""
    return _MARKDOWN_CHARS.sub(r"\\\1", text)


def call_api(method: str, path: str, **kwargs) -> dict:
    try:
        with httpx.Client(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT_S) as client:
            resp = client.request(method, path, **kwargs)
    except httpx.TimeoutException:
        raise ApiError("The server took too long to answer. Try again in a moment.") from None
    except httpx.HTTPError:
        raise ApiError(f"Can't reach the recommendation server at {API_BASE_URL}. "
                       "Check that it is running (`uvicorn recommender.api:app`), then try again.") from None
    if resp.status_code == 422:
        errors = resp.json().get("detail", [])
        raise ApiError("The server rejected the search: " + "; ".join(e.get("msg", "") for e in errors))
    if resp.status_code != 200:
        raise ApiError(f"The server had a problem (HTTP {resp.status_code}). Try again.")
    return resp.json()


@st.cache_data(ttl=600, show_spinner=False)
def load_meta() -> dict:
    return call_api("GET", "/meta")  # errors are not cached, so a retry calls again


def budget_captions(thresholds: dict) -> list[str]:
    low, mid = thresholds["low_max"], thresholds["medium_max"]
    return ["", f"up to ₹{low}", f"₹{low + 1}–{mid}", f"over ₹{mid}"]


def describe_relaxation(change: str) -> str:
    return change.replace("min_rating relaxed", "minimum rating lowered").replace("budget relaxed", "budget widened")


def format_rating(rating: float | None) -> str:
    return "not rated" if rating is None else f"{rating:g} / 5"


def format_cost(cost: int | None) -> str:
    return "not available" if cost is None else f"₹{cost:,}"


def show_results(result: dict) -> None:
    if result["relaxed_constraints"]:
        changes = "; ".join(describe_relaxation(c) for c in result["relaxed_constraints"])
        st.warning(plain(f"Nothing matched exactly, so the search was loosened: {changes}."))
    if not result["recommendations"]:
        st.info(plain(result["message"] or "No restaurants match this search."))
        return
    if result["message"]:
        st.info(plain(result["message"]))
    if result["llm_fallback"]:
        st.info("AI ranking is unavailable right now, so these are sorted by rating and reviews, "
                "with standard descriptions.")
    if result["summary"]:
        st.markdown(plain(result["summary"]))
    for rec in result["recommendations"]:
        with st.container(border=True):
            st.markdown(f"**{rec['rank']}\\. {plain(rec['name'])}**")
            st.markdown(
                f"**Cuisine:** {plain(', '.join(rec['cuisine'])) or 'not listed'}  \n"
                f"**Rating:** {format_rating(rec['rating'])}  \n"
                f"**Estimated cost for two:** {format_cost(rec['estimated_cost'])}"
            )
            st.markdown(plain(rec["explanation"]))
            if rec["explanation_source"] == "template" and not result["llm_fallback"]:
                st.caption("Standard description: the AI gave no explanation for this one.")


def _start_search() -> None:
    # One request per click (UI-03). This runs before the rerun, so the button renders disabled
    # while searching. A double-click's second click is only processed after the first search
    # ends, so a click that soon after the last search is dropped.
    # A disabled submit button returns False, so the page keys off `searching`, not the button.
    ended = st.session_state.get("search_ended_at")
    if ended is None or time.monotonic() - ended > DOUBLE_CLICK_WINDOW_S:
        st.session_state.searching = True


def main() -> None:
    st.set_page_config(page_title="Restaurant Finder", page_icon="🍽️")
    st.title("Restaurant Finder")

    try:
        meta = load_meta()
    except ApiError as exc:
        st.error(str(exc))
        st.button("Retry")  # any click reruns the script
        st.stop()

    st.caption(f"Zomato restaurants in {', '.join(meta['cities'])}, ranked and explained by AI.")
    cities = set(meta["cities"])

    # A form, so the search runs only on submit, not on every widget change (UI-04).
    with st.form("search"):
        location = st.selectbox(
            "Location", meta["cities"] + meta["localities"],
            format_func=lambda loc: f"{loc} (all areas)" if loc in cities else loc,
        )
        budget = st.radio("Budget for two", list(BUDGETS), horizontal=True,
                          captions=budget_captions(meta["budget_thresholds"]))
        cuisine = st.multiselect("Cuisine", meta["cuisines"], max_selections=MAX_CUISINES,
                                 placeholder="Any cuisine")
        min_rating = st.slider("Minimum rating", 0.0, 5.0, 0.0, 0.1, format="%.1f",
                               help="0 means any rating, including places not yet rated.")
        extras = st.text_area("Anything else?", max_chars=MAX_EXTRAS,
                              placeholder="For example: family-friendly, quick service")
        st.form_submit_button("Find restaurants", type="primary",
                              disabled=st.session_state.get("searching", False), on_click=_start_search)

    if st.session_state.get("searching"):
        prefs = {"location": location, "budget": BUDGETS[budget], "cuisine": cuisine,
                 "min_rating": min_rating, "extras": extras}
        # Old results are cleared either way, so they never sit under different inputs (UI-32).
        try:
            with st.spinner("Finding restaurants…"):
                st.session_state.result, st.session_state.error = call_api("POST", "/recommend", json=prefs), None
        except ApiError as exc:
            st.session_state.result, st.session_state.error = None, str(exc)
        finally:
            st.session_state.searching = False
            st.session_state.search_ended_at = time.monotonic()
        st.rerun()  # re-render with the button enabled again

    if st.session_state.get("error"):
        st.error(st.session_state.error)
    if st.session_state.get("result"):
        show_results(st.session_state.result)


if __name__ == "__main__":
    main()

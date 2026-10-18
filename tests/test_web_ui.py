"""Web UI tests: the real page in a real browser, served by the real API app with a fake LLM.

Skipped when Playwright or a browser is missing (pip install -e ".[dev]"; uses installed
Chrome, else Playwright's own Chromium from `playwright install chromium`).
"""

import json
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn

from recommender.api import create_app
from recommender.engine import Engine
from recommender.llm.base import LLMError
from recommender.llm.fake import FakeLLMClient, reply_json

sync_api = pytest.importorskip("playwright.sync_api")

RESULTS = ".card:not(.skeleton), .empty, .banner.error"


@contextmanager
def serve(app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "server did not start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        for kwargs in ({"channel": "chrome"}, {}):
            try:
                b = p.chromium.launch(**kwargs)
                break
            except Exception as exc:  # no Chrome, or no bundled Chromium
                reason = str(exc).splitlines()[0]
        else:
            pytest.skip(f"no browser for the web UI tests: {reason}")
        yield b
        b.close()


@pytest.fixture
def fake():
    return FakeLLMClient()  # tests queue replies on fake.replies


@pytest.fixture
def site(store, fake):
    with serve(create_app(engine=Engine(store, fake))) as url:
        yield url


def open_page(browser, url, width=1280):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.errors = []
    page.on("pageerror", lambda exc: page.errors.append(str(exc)))
    page.goto(url)
    return page


@pytest.fixture
def page(browser, site):
    page = open_page(browser, site)
    page.wait_for_function("document.querySelectorAll('#location option').length > 1")
    yield page
    assert page.errors == []
    page.close()


def search(page, location="BTM", budget=None, cuisines=(), rating=None, extras=None, click="click"):
    page.select_option("#location", location)
    if budget:
        page.check(f"input[name=budget][value={budget}]")
    for c in cuisines:
        page.fill("#cuisine-input", c)
        page.keyboard.press("Enter")
    if rating is not None:
        page.locator("#min-rating").fill(str(rating))
    if extras is not None:
        page.fill("#extras", extras)
    getattr(page.locator("#submit"), click)()
    page.wait_for_selector(RESULTS)


def texts(page, selector):
    return page.locator(selector).all_inner_texts()


# --- form ------------------------------------------------------------------------

def test_form_is_filled_from_meta(page):
    options = texts(page, "#location option")
    assert options[:2] == ["Bangalore (all areas)", "BTM"]
    assert texts(page, ".seg-sub") == ["All prices", "up to ₹300", "₹301–500", "over ₹500"]
    assert page.locator("#intro").is_visible()


def test_rating_badge_and_extras_counter(page):
    assert page.inner_text("#rating-badge") == "Any"
    page.locator("#min-rating").fill("4")
    assert page.inner_text("#rating-badge") == "4.0+"
    page.fill("#extras", "quick service")
    assert page.inner_text("#extras-count") == "13/300"
    assert page.get_attribute("#extras", "maxlength") == "300"


def test_cuisine_chips_take_only_known_cuisines(page):
    page.fill("#cuisine-input", "ital")
    page.keyboard.press("Enter")
    assert texts(page, "#cuisine-chips .chip") == []  # not a dataset cuisine
    for c in ("italian", "Pizza", "Italian"):
        page.fill("#cuisine-input", c)
        page.keyboard.press("Enter")
    assert texts(page, "#cuisine-chips .chip") == ["Italian", "Pizza"]  # canonical spelling, no duplicate
    assert page.inner_text("#cuisine-count") == "2/10"
    page.click("button[aria-label='Remove Italian']")
    page.focus("#cuisine-input")
    page.keyboard.press("Backspace")
    assert texts(page, "#cuisine-chips .chip") == []


# --- results -------------------------------------------------------------------

def test_search_shows_summary_and_every_card_field(page, fake):
    fake.replies.append(reply_json([1, 2, 3], summary="Three good picks."))
    search(page, cuisines=["North Indian"], extras="quick service")
    assert page.inner_text(".summary-text") == "Three good picks."
    assert page.inner_text(".summary-label") == "AI SUMMARY"
    first = page.locator(".card").first
    assert first.locator(".card-name").text_content() == "1. Popular"  # "1. " is for screen readers
    assert first.locator(".card-place").inner_text() == "BTM"
    assert first.locator(".tag").all_inner_texts() == ["North Indian", "Chinese"]
    assert first.locator(".rating").inner_text().replace("\n", " ") == "4.5 / 5"
    assert first.locator(".cost").inner_text() == "₹400 for two"
    assert first.locator(".why").inner_text() == "Explanation for 1."
    sent = json.loads(fake.calls[0]["user"].split("Preferences: ", 1)[1].split("\n", 1)[0])
    assert sent["cuisines"] == ["North Indian"] and sent["extras"] == "quick service"
    assert page.locator("#submit").is_enabled()


def test_model_and_data_text_is_shown_literally(page, fake):
    fake.replies.append(json.dumps({
        "summary": "<img src=x onerror=\"document.title='pwned'\"> **bold**",
        "ranking": [{"id": 1, "explanation": "<script>document.title='pwned'</script>"}],
    }))
    search(page)
    assert page.inner_text(".summary-text") == "<img src=x onerror=\"document.title='pwned'\"> **bold**"
    assert page.locator(".summary-text img, .why script").count() == 0
    assert page.title() == "Restaurant Finder"


def test_null_rating_and_cost_are_spelled_out(page, fake):
    fake.replies.extend([LLMError("down"), LLMError("down")])
    search(page)  # BTM includes r5, not yet rated
    assert "Not rated" in texts(page, ".rating")
    search(page, location="HSR")  # r8 has no cost
    assert texts(page, ".cost") == ["Cost for two not available"]
    assert "None" not in page.inner_text("#results") and "NaN" not in page.inner_text("#results")


def test_relaxation_is_stated_above_results(page, fake):
    fake.replies.append(reply_json([1]))
    search(page, location="Indiranagar", budget="high", cuisines=["Pizza"], rating=4.3)
    assert page.inner_text(".banner.warning") == ("Nothing matched exactly, so the search was loosened: "
                                                   "minimum rating lowered from 4.3 to 3.8; "
                                                   "budget widened from high to high or medium.")
    assert page.inner_text(".note") == "Only 1 restaurant matched."
    # The banner comes before the results.
    order = page.evaluate("[...document.querySelectorAll('#results > *')].map(n => n.className)")
    assert order.index("banner warning") < order.index("cards")


def test_no_result_shows_empty_state_without_calling_the_llm(page, fake):
    search(page, location="Indiranagar", cuisines=["Biryani"])
    assert page.inner_text(".empty-title") == "No restaurants match these preferences."
    assert fake.calls == []


def test_fallback_says_descriptions_are_generic(page, fake):
    fake.replies.append(LLMError("timeout"))
    search(page)
    assert page.inner_text(".banner.info").startswith("AI ranking is unavailable right now")
    assert set(texts(page, ".why-label")) == {"STANDARD DESCRIPTION"}
    assert page.inner_text(".summary-label") == "SUMMARY"


# --- errors --------------------------------------------------------------------

def test_server_error_shows_banner_and_retry_recovers(page, fake):
    fake.replies.extend([RuntimeError("bug"), reply_json([1, 2, 3])])
    search(page)
    assert page.inner_text(".banner.error").startswith("The server had a problem (HTTP 500)")
    page.click(".banner.error button")
    page.wait_for_selector(".card:not(.skeleton)")
    assert page.locator(".card").count() == 5


def test_unreachable_server_shows_banner_and_keeps_the_form(page):
    page.route("**/recommend", lambda route: route.abort())
    search(page, location="Indiranagar", budget="high", extras="rooftop")
    assert page.inner_text(".banner.error").startswith("Can't reach the recommendation server")
    assert page.input_value("#location") == "Indiranagar"
    assert page.is_checked("input[name=budget][value=high]") and page.input_value("#extras") == "rooftop"
    assert page.locator("#submit").is_enabled()


def test_meta_failure_disables_the_form_until_retry_works(browser, site):
    page = open_page(browser, site)
    page.route("**/meta", lambda route: route.abort())
    page.reload()
    page.wait_for_selector(".banner.error")
    assert page.locator("#location").is_disabled() and page.locator("#submit").is_disabled()
    page.unroute("**/meta")
    page.click(".banner.error button")
    page.wait_for_function("document.querySelectorAll('#location option').length > 1")
    assert page.locator("#submit").is_enabled() and page.locator("#intro").is_visible()
    assert page.errors == []
    page.close()


def test_double_click_sends_one_request(page, fake):
    fake.replies.extend([reply_json([1, 2, 3]), reply_json([1, 2, 3])])
    posts = []
    page.on("request", lambda r: posts.append(r) if r.url.endswith("/recommend") else None)
    search(page, click="dblclick")
    page.wait_for_timeout(300)
    assert len(posts) == 1 and len(fake.calls) == 1


# --- small screens --------------------------------------------------------------

def test_phone_width_folds_the_form_into_a_summary(browser, site, fake):
    page = open_page(browser, site, width=390)
    page.wait_for_function("document.querySelectorAll('#location option').length > 1")
    fake.replies.append(reply_json([1, 2, 3]))
    search(page, budget="medium", cuisines=["North Indian", "Chinese"], rating=4)
    assert page.locator("#search").is_hidden() and page.locator("#search-summary").is_visible()
    assert texts(page, "#summary-chips .summary-chip") == ["BTM", "Medium · ₹301–500", "North Indian +1", "Min 4.0"]
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.click("#edit-search")
    assert page.locator("#search").is_visible()
    assert page.errors == []
    page.close()

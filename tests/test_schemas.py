import pytest
from pydantic import ValidationError

from recommender.schemas import Preferences, RecommendationResponse

BASE = {"location": "Bangalore"}


def prefs(**kw):
    return Preferences(**{**BASE, **kw})


# Exit check (implementation-plan.md, Phase 0).

@pytest.mark.parametrize("budget", ["cheap", "mid", "expensive", "", 500])
def test_rejects_invalid_budget(budget):
    with pytest.raises(ValidationError):
        prefs(budget=budget)


@pytest.mark.parametrize("rating", [-0.1, 5.1, float("nan"), float("inf"), "high"])
def test_rejects_out_of_range_rating(rating):
    with pytest.raises(ValidationError):
        prefs(min_rating=rating)


# Other validation rules (architecture.md §5.6, edge-case.md §2).

def test_defaults():
    p = prefs()
    assert (p.budget, p.cuisine, p.min_rating, p.extras, p.top_k) == (None, [], 0.0, "", 5)


@pytest.mark.parametrize("raw,expected", [("Medium", "medium"), (" HIGH ", "high"), (None, None)])
def test_budget_casefold(raw, expected):
    assert prefs(budget=raw).budget == expected


def test_numeric_string_rating_coerced():
    assert prefs(min_rating="4.0").min_rating == 4.0


@pytest.mark.parametrize("location", ["", "   ", "x" * 101])
def test_rejects_bad_location(location):
    with pytest.raises(ValidationError):
        Preferences(location=location)


def test_location_stripped():
    assert Preferences(location="  Delhi ").location == "Delhi"


def test_missing_location():
    with pytest.raises(ValidationError):
        Preferences()


@pytest.mark.parametrize("raw,expected", [
    ("Italian", ["Italian"]),
    (["Italian", "italian ", "Chinese", ""], ["Italian", "Chinese"]),
    (None, []),
])
def test_cuisine_normalized(raw, expected):
    assert prefs(cuisine=raw).cuisine == expected


@pytest.mark.parametrize("raw", [5, [5]])
def test_rejects_non_string_cuisine(raw):
    with pytest.raises(ValidationError):
        prefs(cuisine=raw)


def test_rejects_too_many_cuisines():
    with pytest.raises(ValidationError):
        prefs(cuisine=[f"c{i}" for i in range(11)])


def test_extras_length_limit():
    assert len(prefs(extras="a" * 300).extras) == 300
    with pytest.raises(ValidationError):
        prefs(extras="a" * 301)


@pytest.mark.parametrize("raw", ["   ", "?!...", None])
def test_extras_without_content_become_empty(raw):
    assert prefs(extras=raw).extras == ""


@pytest.mark.parametrize("top_k", [0, -1, 11])
def test_rejects_bad_top_k(top_k):
    with pytest.raises(ValidationError):
        prefs(top_k=top_k)


def test_unknown_fields_ignored():
    assert not hasattr(prefs(foo="bar"), "foo")


def test_architecture_example_request_parses():
    p = Preferences(
        location="Bangalore", budget="medium", cuisine=["Italian"],
        min_rating=4.0, extras="family-friendly, quick service", top_k=5,
    )
    assert p.cuisine == ["Italian"]


def test_empty_response_shape():
    r = RecommendationResponse().model_dump()
    assert r == {
        "summary": "", "recommendations": [], "relaxed_constraints": [],
        "llm_fallback": False, "message": None,
    }

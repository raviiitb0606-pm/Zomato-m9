import pandas as pd
import pytest

from recommender.filtering import BUDGET_RELAX, prepare, shortlist
from recommender.schemas import Preferences


def ids(result):
    return [r.id for r in result.restaurants]


def q(store, size=20, **kw):
    return store.query(Preferences(**kw), size=size)


# --- location ----------------------------------------------------------------

@pytest.mark.parametrize("location", ["Bangalore", " bangalore ", "BENGALURU", "Bengaluru"])
def test_city_and_aliases_match_everything(store, location):
    assert q(store, location=location).matched == 12


@pytest.mark.parametrize("location,expected", [
    ("BTM", {"r1", "r2", "r3", "r5", "r7"}),
    (" btm ", {"r1", "r2", "r3", "r5", "r7"}),
    ("Indiranagar", {"r4", "r6"}),
    ("Koramangala", {"r9", "r10"}),             # covers its numbered blocks
    ("Koramangala 5th Block", {"r9"}),          # a block alone stays a block
    ("Whitefield", {"r11", "r12"}),             # plus "ITPL Main Road, Whitefield"
])
def test_locality(store, location, expected):
    assert set(ids(q(store, location=location))) == expected


@pytest.mark.parametrize("location", ["Delhi", "Paris", "Koram", "Road"])  # no partial-word matches
def test_unknown_location_is_empty_with_message_and_never_relaxed(store, location):
    r = q(store, location=location, budget="high", min_rating=4.9)
    assert r.restaurants == [] and r.relaxed_constraints == []
    assert location in r.message and "Bangalore" in r.message


# --- hard filters ------------------------------------------------------------

@pytest.mark.parametrize("budget,expected", [
    ("low", {"r3", "r5"}),
    ("medium", {"r1", "r2"}),
    ("high", {"r7"}),
    (None, {"r1", "r2", "r3", "r5", "r7"}),
])
def test_budget(store, budget, expected):
    assert set(ids(q(store, location="BTM", budget=budget))) == expected


def test_no_cost_rows_excluded_only_when_budget_set(store):
    assert "r8" in ids(q(store, location="HSR"))
    assert q(store, location="HSR", budget="low").restaurants == []  # r8 is HSR's only place


@pytest.mark.parametrize("min_rating,expected", [
    (0, {"r1", "r2", "r3", "r5", "r7"}),        # 0 = no filter; unrated included
    (4.0, {"r1", "r2", "r7"}),                  # unrated never meets a minimum
    (4.5, {"r1", "r2"}),
])
def test_min_rating(store, min_rating, expected):
    assert set(ids(q(store, location="BTM", min_rating=min_rating))) == expected


@pytest.mark.parametrize("cuisine,expected", [
    (["north indian"], {"r1", "r2", "r5"}),
    (["Chinese", "Italian"], {"r1", "r4", "r6", "r7"}),  # any of them
    ([], set(f"r{i}" for i in range(1, 13))),
])
def test_cuisine_overlap(store, cuisine, expected):
    assert set(ids(q(store, location="Bangalore", cuisine=cuisine))) == expected


def test_unknown_cuisine_is_empty_with_message(store):
    r = q(store, location="Bangalore", cuisine=["Martian"], min_rating=4.9)
    assert r.restaurants == [] and r.relaxed_constraints == [] and "Martian" in r.message


def test_partly_unknown_cuisine_matches_the_rest(store):
    r = q(store, location="Bangalore", cuisine=["Martian", "Italian"])
    assert set(ids(r)) == {"r4", "r6"} and "Martian" in r.message


# --- pre-ranking -------------------------------------------------------------

def test_many_votes_beat_few_votes_and_unrated_last(store):
    # 4.5 from 2,000 votes outranks 5.0 from 3 votes; unrated sorts last.
    assert ids(q(store, location="BTM", cuisine=["North Indian"])) == ["r1", "r2", "r5"]


def test_scores_attached(store):
    r = q(store, location="BTM", cuisine=["North Indian"])
    assert r.restaurants[0].score > r.restaurants[1].score and r.restaurants[2].score is None


def test_shortlist_cut_to_size(store):
    r = q(store, location="Bangalore", size=3)
    assert len(r.restaurants) == 3 and r.matched == 12


def test_ties_break_deterministically():
    df = pd.DataFrame({
        "id": ["b", "a", "c"], "name": ["Same", "Same", "Alpha"], "city": "Bangalore",
        "locality": "BTM", "cuisines": [["X"]] * 3, "cost_for_two": 100,
        "budget_tier": "low", "rating": 4.0, "votes": 10, "tags": [[]] * 3,
        "popular_dishes": [[]] * 3,
    })
    r = shortlist(prepare(df), Preferences(location="BTM"), 10)
    assert ids(r) == ["c", "a", "b"]  # equal score and votes: by name, then id


def test_zero_votes_everywhere_does_not_crash():
    df = pd.DataFrame({
        "id": ["a", "b"], "name": ["A", "B"], "city": "Bangalore", "locality": "BTM",
        "cuisines": [["X"], ["X"]], "cost_for_two": 100, "budget_tier": "low",
        "rating": [4.0, 3.0], "votes": 0, "tags": [[], []], "popular_dishes": [[], []],
    })
    assert ids(shortlist(prepare(df), Preferences(location="BTM"), 10)) == ["a", "b"]


# --- relaxation --------------------------------------------------------------

def test_relax_rating_first(store):
    r = q(store, location="Indiranagar", budget="high", cuisine=["Italian"], min_rating=4.9)
    assert ids(r) == ["r4"]
    assert r.relaxed_constraints == ["min_rating relaxed from 4.9 to 4.4"]


def test_relax_rating_then_budget(store):
    r = q(store, location="Indiranagar", budget="high", cuisine=["Pizza"], min_rating=4.3)
    assert ids(r) == ["r6"]
    assert r.relaxed_constraints == [
        "min_rating relaxed from 4.3 to 3.8",
        "budget relaxed from high to high or medium",
    ]


def test_still_nothing_after_relaxing(store):
    r = q(store, location="Indiranagar", budget="high", cuisine=["Pizza"], min_rating=4.7)
    assert r.restaurants == [] and r.relaxed_constraints == []
    assert "even after loosening" in r.message


@pytest.mark.parametrize("budget,cuisine,expected", [
    ("low", ["Chinese"], "r1"),         # low -> medium
    ("medium", ["South Indian"], "r3"), # medium -> low (cheaper side)
    ("high", ["North Indian"], "r1"),   # high -> medium
])
def test_budget_relax_direction(store, budget, cuisine, expected):
    r = q(store, location="BTM", budget=budget, cuisine=cuisine)
    assert ids(r)[0] == expected
    assert r.relaxed_constraints == [f"budget relaxed from {budget} to {budget} or {BUDGET_RELAX[budget]}"]


def test_rating_relax_clamps_at_zero(store):
    r = q(store, location="BTM", budget="low", cuisine=["North Indian"], min_rating=0.3)
    assert ids(r) == ["r5"]  # only an unrated place; dropping the minimum lets it in
    assert r.relaxed_constraints == ["min_rating relaxed from 0.3 to 0"]


def test_location_and_cuisine_never_relaxed(store):
    r = q(store, location="HSR", cuisine=["Italian"], budget="high", min_rating=4.5)
    assert r.restaurants == []  # Italian exists elsewhere, but HSR stays HSR


def test_thin_results_reported_not_relaxed(store):
    r = q(store, location="BTM", cuisine=["Chinese"], top_k=5)
    assert set(ids(r)) == {"r1", "r7"}
    assert r.relaxed_constraints == [] and r.message == "Only 2 restaurants matched."


def test_enough_results_have_no_message(store):
    assert q(store, location="Bangalore", top_k=5).message is None


def test_query_does_not_mutate_store(store):
    before = store._df.copy()
    q(store, location="BTM", budget="low", min_rating=4.9)
    pd.testing.assert_frame_equal(store._df, before)

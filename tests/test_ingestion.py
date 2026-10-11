import json
import math

import pandas as pd
import pyarrow.parquet as pq
import pytest

from recommender.config import Settings
from recommender.ingestion import cli
from recommender.ingestion.clean import (
    COLUMNS, REQUIRED_COLUMNS, assign_tier, budget_thresholds, clean, fix_text,
    outlet_key, parse_cost, parse_rating, split_list,
)


def mojibake(s: str, times: int = 3) -> str:
    for _ in range(times):
        s = s.encode("utf-8").decode("latin-1")
    return s


def raw_row(**kw) -> dict:
    row = {
        "url": "https://www.zomato.com/bangalore/place-a?context=abc",
        "name": "Place A",
        "online_order": "Yes",
        "book_table": "No",
        "rate": "4.1/5",
        "votes": 100,
        "location": "BTM",
        "rest_type": "Quick Bites",
        "dish_liked": "Dosa, Vada",
        "cuisines": "South Indian, Chinese",
        "approx_cost(for two people)": "300",
        "listed_in(type)": "Delivery",
        "listed_in(city)": "BTM",
    }
    row.update(kw)
    return row


def frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=REQUIRED_COLUMNS)


# --- field parsers -----------------------------------------------------------

@pytest.mark.parametrize("raw", ["4.1/5", "4.1 /5", " 4.1 / 5 ", "4.1", 4.1, "4,1/5"])
def test_parse_rating_formats(raw):
    assert parse_rating(raw) == 4.1


@pytest.mark.parametrize("raw", ["NEW", "new", "-", "", "  ", None, math.nan, "N/A", "6.2/5", "41/5", "-1"])
def test_parse_rating_nulls_and_out_of_range(raw):
    assert parse_rating(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("1,200", 1200), ("₹1,200", 1200), ("1200.0", 1200), (" 800 ", 800), (800, 800),
])
def test_parse_cost(raw, expected):
    assert parse_cost(raw) == expected


@pytest.mark.parametrize("raw", [None, math.nan, "", "0", "-5", "abc"])
def test_parse_cost_invalid(raw):
    assert parse_cost(raw) is None


@pytest.mark.parametrize("raw,expected", [
    (mojibake("Café Felix"), "Café Felix"),
    (mojibake("Piñata", 1), "Piñata"),
    ("Brother\x92s Bar", "Brother’s Bar"),
    ("  Two   spaces  ", "Two spaces"),
    ("Plain", "Plain"),
    ("", None),
    (None, None),
])
def test_fix_text(raw, expected):
    assert fix_text(raw) == expected


def test_split_list():
    assert split_list("North Indian,  chinese,,north indian , ") == ["North Indian", "chinese"]
    assert split_list(None) == []


def test_outlet_key():
    assert outlet_key("https://www.zomato.com/Bangalore/Place-A/?context=1") == "www.zomato.com/bangalore/place-a"
    assert outlet_key("") is None
    assert outlet_key(None) is None


# --- budget tiers ------------------------------------------------------------

def test_budget_thresholds_use_real_values():
    assert budget_thresholds(pd.Series([100, 200, 300, 400, 500, 600, None])) == (200, 400)


def test_tiers_defined_when_costs_are_lumpy():
    low_max, medium_max = budget_thresholds(pd.Series([300] * 10))
    assert {assign_tier(300, low_max, medium_max), assign_tier(301, low_max, medium_max)} == {"low", "high"}


def test_boundaries_inclusive():
    assert [assign_tier(c, 300, 500) for c in (300, 301, 500, 501, None)] == ["low", "medium", "medium", "high", None]


def test_thresholds_need_costs():
    with pytest.raises(ValueError):
        budget_thresholds(pd.Series([None, None], dtype="float64"))


# --- clean() -----------------------------------------------------------------

def test_duplicates_merge_to_most_voted_listing_with_all_tags():
    df, _, report = clean(frame(
        raw_row(votes=50, rate="3.5/5", **{"listed_in(type)": "Delivery"}),
        raw_row(url="https://www.zomato.com/bangalore/place-a?context=xyz", votes=90,
                rate="4.0 /5", book_table="Yes", **{"listed_in(type)": "Dine-out"}),
    ))
    assert len(df) == 1 and report.duplicates_merged == 1
    row = df.iloc[0]
    assert row.rating == 4.0 and row.votes == 90
    assert list(row.tags) == ["delivery", "dine-out", "online ordering", "quick bites", "table booking"]


def test_canonical_columns_and_values():
    df, thresholds, _ = clean(frame(raw_row()))
    assert list(df.columns) == COLUMNS
    row = df.iloc[0]
    assert (row["name"], row.city, row.locality) == ("Place A", "Bangalore", "BTM")
    assert list(row.cuisines) == ["South Indian", "Chinese"]
    assert list(row.popular_dishes) == ["Dosa", "Vada"]
    assert row.cost_for_two == 300 and row.budget_tier == "low"
    assert len(row.id) == 12


def test_nulls_kept_not_dropped():
    df, _, report = clean(frame(
        raw_row(),
        raw_row(url="https://www.zomato.com/bangalore/b", rate="NEW",
                **{"approx_cost(for two people)": None}),
    ))
    assert report.rows_out == 2 and not report.dropped
    nulls = df[df.rating.isna()]
    assert len(nulls) == 1 and pd.isna(nulls.iloc[0].cost_for_two) and pd.isna(nulls.iloc[0].budget_tier)


def test_invalid_rating_counted():
    _, _, report = clean(frame(raw_row(rate="6.2/5"), raw_row(url="https://www.zomato.com/bangalore/b", rate="NEW")))
    assert report.invalid_ratings == 1


def test_missing_name_and_url_dropped_and_counted():
    df, _, report = clean(frame(
        raw_row(),
        raw_row(url="https://www.zomato.com/bangalore/b", name="   "),
        raw_row(url=None),
    ))
    assert len(df) == 1
    assert report.dropped["no name"] == 1 and report.dropped["no url"] == 1


def test_vanity_url_inherits_single_city():
    df, _, report = clean(frame(raw_row(), raw_row(url="https://www.zomato.com/barleyz", name="Barleyz")))
    assert set(df.city) == {"Bangalore"} and not report.dropped


def test_vanity_url_dropped_when_dataset_has_several_cities():
    df, _, report = clean(frame(
        raw_row(),
        raw_row(url="https://www.zomato.com/delhi/b", name="B"),
        raw_row(url="https://www.zomato.com/barleyz", name="Barleyz"),
    ))
    assert set(df.city) == {"Bangalore", "Delhi"} and report.dropped["no city"] == 1


def test_city_alias():
    df, _, _ = clean(frame(raw_row(url="https://www.zomato.com/bengaluru/x")))
    assert df.iloc[0].city == "Bangalore"


def test_locality_falls_back_to_listing_area():
    df, _, _ = clean(frame(raw_row(location=None, **{"listed_in(city)": "Koramangala 5th Block"})))
    assert df.iloc[0].locality == "Koramangala 5th Block"


def test_mojibake_name_repaired():
    df, _, _ = clean(frame(raw_row(name=mojibake("Café Felix"))))
    assert df.iloc[0]["name"] == "Café Felix"


def test_missing_columns_fail_loudly():
    with pytest.raises(ValueError, match="rate"):
        clean(frame(raw_row()).drop(columns=["rate"]))


def test_nothing_left_fails_loudly():
    with pytest.raises(ValueError):
        clean(frame(raw_row(name=None)))


def test_deterministic():
    raw = frame(raw_row(), raw_row(url="https://www.zomato.com/bangalore/b", name="B", votes=7))
    a, _, _ = clean(raw)
    b, _, _ = clean(raw.iloc[::-1])
    pd.testing.assert_frame_equal(a, b)


# --- cli ---------------------------------------------------------------------

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, data_dir=tmp_path))
    return tmp_path


def test_main_writes_parquet_and_meta(data_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_raw", lambda: frame(
        raw_row(),
        raw_row(url="https://www.zomato.com/bangalore/b", name="B", rate="NEW",
                cuisines="Chinese", **{"approx_cost(for two people)": "1,500"}),
    ))
    assert cli.main() == 0

    table = pq.read_table(data_dir / cli.PARQUET_NAME)
    assert table.num_rows == 2
    assert table.column("rating").null_count == 1  # real null, not NaN
    meta = json.loads((data_dir / cli.META_NAME).read_text(encoding="utf-8"))
    assert meta["cities"] == ["Bangalore"]
    assert meta["cuisines"][0] == "Chinese"  # most common first
    assert set(meta["budget_thresholds"]) == {"low_max", "medium_max"}
    assert "Restaurants out:    2" in capsys.readouterr().out
    assert not list(data_dir.glob(".*.*"))  # no temp files left behind


def test_failed_load_keeps_existing_files(data_dir, monkeypatch):
    existing = data_dir / cli.PARQUET_NAME
    existing.write_bytes(b"previous good build")

    def boom():
        raise ConnectionError("offline")

    monkeypatch.setattr(cli, "load_raw", boom)
    assert cli.main() == 1
    assert existing.read_bytes() == b"previous good build"


def test_failed_clean_writes_nothing(data_dir, monkeypatch):
    monkeypatch.setattr(cli, "load_raw", lambda: frame(raw_row(name=None)))
    assert cli.main() == 1
    assert not (data_dir / cli.PARQUET_NAME).exists()

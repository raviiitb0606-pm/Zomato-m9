import json

import pandas as pd
import pytest

from recommender.config import Settings
from recommender.filtering import main as filtering_main
from recommender.schemas import Restaurant
from recommender.store import META_NAME, PARQUET_NAME, DataNotFoundError, RestaurantStore


@pytest.mark.parametrize("missing", [PARQUET_NAME, META_NAME])
def test_missing_file_explains_how_to_fix(data_dir, missing):
    (data_dir / missing).unlink()
    with pytest.raises(DataNotFoundError, match="recommender.ingestion.cli"):
        RestaurantStore.load(data_dir)


def test_corrupt_parquet(data_dir):
    (data_dir / PARQUET_NAME).write_bytes(b"not parquet")
    with pytest.raises(DataNotFoundError, match="Could not read"):
        RestaurantStore.load(data_dir)


def test_missing_columns(data_dir):
    df = pd.read_parquet(data_dir / PARQUET_NAME).drop(columns=["rating"])
    df.to_parquet(data_dir / PARQUET_NAME)
    with pytest.raises(DataNotFoundError, match="rating"):
        RestaurantStore.load(data_dir)


def test_meta_out_of_sync(data_dir):
    meta = json.loads((data_dir / META_NAME).read_text())
    meta["cities"] = ["Delhi"]
    (data_dir / META_NAME).write_text(json.dumps(meta))
    with pytest.raises(DataNotFoundError, match="does not match"):
        RestaurantStore.load(data_dir)


def test_get_keeps_order_and_skips_unknown(store):
    got = store.get(["r4", "nope", "r1"])
    assert [r.id for r in got] == ["r4", "r1"]
    assert all(type(r) is Restaurant for r in got)


def test_nulls_come_back_as_none(store):
    r5, r8 = store.get(["r5", "r8"])
    assert r5.rating is None
    assert r8.cost_for_two is None and r8.budget_tier is None
    assert isinstance(store.get(["r1"])[0].cost_for_two, int)


def test_meta_is_a_copy(store):
    store.meta()["cities"].append("Delhi")
    assert store.meta()["cities"] == ["Bangalore"]


def test_dev_script(data_dir, monkeypatch, capsys):
    monkeypatch.setattr("recommender.store.get_settings", lambda: Settings(_env_file=None, data_dir=data_dir))
    assert filtering_main(["--city", "BTM", "--cuisine", "North Indian,Chinese", "--size", "2"]) == 0
    out = capsys.readouterr().out
    assert "Matched 4, showing 2" in out and "Popular" in out


def test_dev_script_rejects_bad_input():
    assert filtering_main(["--location", "BTM", "--min-rating", "9"]) == 2

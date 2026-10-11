"""In-memory restaurant store over the files ingestion writes (architecture.md §5.2)."""

import copy
import json
from pathlib import Path

import pandas as pd

from recommender.config import get_settings
from recommender.filtering import Shortlist, prepare, shortlist, to_restaurant
from recommender.ingestion.clean import COLUMNS
from recommender.schemas import Preferences, Restaurant

PARQUET_NAME = "restaurants.parquet"
META_NAME = "meta.json"

REBUILD_HINT = "Run `python -m recommender.ingestion.cli` to build it."


class DataNotFoundError(RuntimeError):
    """The data files are missing, unreadable, or inconsistent."""


class RestaurantStore:
    def __init__(self, df: pd.DataFrame, meta: dict):
        self._df = prepare(df)
        self._by_id = self._df.set_index("id", drop=False)
        self._meta = meta

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "RestaurantStore":
        data_dir = data_dir or get_settings().data_dir
        parquet, meta_path = data_dir / PARQUET_NAME, data_dir / META_NAME
        for path in (parquet, meta_path):
            if not path.exists():
                raise DataNotFoundError(f"{path} not found. {REBUILD_HINT}")
        try:
            df = pd.read_parquet(parquet)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise DataNotFoundError(f"Could not read data in {data_dir}: {exc}. {REBUILD_HINT}") from exc

        missing = [c for c in COLUMNS if c not in df.columns]
        if missing:
            raise DataNotFoundError(f"{parquet} is missing columns {missing}. {REBUILD_HINT}")
        if not set(meta.get("cities", [])) <= set(df["city"].dropna()):
            raise DataNotFoundError(f"{meta_path} does not match {parquet}. {REBUILD_HINT}")
        return cls(df, meta)

    def meta(self) -> dict:
        return copy.deepcopy(self._meta)

    def query(self, prefs: Preferences, size: int | None = None) -> Shortlist:
        return shortlist(self._df, prefs, size or get_settings().shortlist_size)

    def get(self, ids: list[str]) -> list[Restaurant]:
        """Restaurants for `ids`, in the same order; unknown ids are skipped."""
        return [
            to_restaurant(self._by_id.loc[i].to_dict())
            for i in ids
            if i in self._by_id.index
        ]

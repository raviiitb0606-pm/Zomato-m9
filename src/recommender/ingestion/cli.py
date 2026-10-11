"""Build data/restaurants.parquet and data/meta.json: `python -m recommender.ingestion.cli`."""

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

from recommender.config import get_settings
from recommender.ingestion.clean import CleanReport, clean
from recommender.ingestion.load import DATASET_ID, load_raw

PARQUET_NAME = "restaurants.parquet"
META_NAME = "meta.json"


def build_meta(df: pd.DataFrame, thresholds: tuple[int, int]) -> dict:
    by_freq = lambda col: [v for v, _ in Counter(x for xs in df[col] for x in xs).most_common()]
    return {
        "source": DATASET_ID,
        "restaurants": len(df),
        "cities": sorted(df["city"].dropna().unique().tolist()),
        "localities": sorted(df["locality"].dropna().unique().tolist()),
        "cuisines": by_freq("cuisines"),  # most common first
        "tags": by_freq("tags"),
        "budget_thresholds": {"low_max": thresholds[0], "medium_max": thresholds[1]},
    }


def _atomic_write(path: Path, write) -> None:
    # Write next to the target, then rename, so a crash never leaves a partial file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    os.close(fd)
    try:
        write(tmp)
        os.chmod(tmp, 0o644)  # mkstemp creates 0600
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_outputs(df: pd.DataFrame, meta: dict, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(data_dir / PARQUET_NAME, lambda p: df.to_parquet(p, index=False))
    _atomic_write(
        data_dir / META_NAME,
        lambda p: Path(p).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"),
    )


def summary(df: pd.DataFrame, meta: dict, report: CleanReport) -> str:
    tiers = df["budget_tier"].value_counts(dropna=False)
    costed = int(df["cost_for_two"].notna().sum())
    pct = lambda n, d: f"{n} ({n / d:.0%})" if d else str(n)
    lines = [
        f"Rows in:            {report.rows_in}",
        *(f"Dropped ({r}):  {n}" for r, n in report.dropped.items() if n),
        f"Duplicates merged:  {report.duplicates_merged}",
        f"Restaurants out:    {report.rows_out}",
        f"No rating:          {pct(int(df['rating'].isna().sum()), len(df))}"
        f"  (unparseable: {report.invalid_ratings})",
        f"No cost:            {pct(int(df['cost_for_two'].isna().sum()), len(df))}",
        f"Budget thresholds:  low <= {meta['budget_thresholds']['low_max']}"
        f" < medium <= {meta['budget_thresholds']['medium_max']} < high",
        "Budget tiers:       " + ", ".join(
            f"{t}: {pct(int(tiers.get(t, 0)), costed)}" for t in ("low", "medium", "high")
        ),
        f"Cities:             {', '.join(meta['cities'])}",
        f"Localities:         {len(meta['localities'])}",
        f"Cuisines:           {len(meta['cuisines'])}",
    ]
    return "\n".join(lines)


def main() -> int:
    data_dir = get_settings().data_dir
    try:
        raw = load_raw()
    except Exception as exc:  # network, auth, dataset moved
        print(f"Could not load {DATASET_ID}: {exc}", file=sys.stderr)
        return 1
    try:
        df, thresholds, report = clean(raw)
    except ValueError as exc:
        print(f"Cleaning failed, nothing written: {exc}", file=sys.stderr)
        return 1
    meta = build_meta(df, thresholds)
    write_outputs(df, meta, data_dir)
    print(summary(df, meta, report))
    print(f"\nWrote {data_dir / PARQUET_NAME} and {data_dir / META_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

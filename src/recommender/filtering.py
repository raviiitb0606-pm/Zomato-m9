"""Hard filters, pre-ranking and relaxation (architecture.md §5.4).

Dev script: python -m recommender.filtering --location BTM --budget medium --cuisine "North Indian"
"""

import argparse
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from recommender.ingestion.clean import CITY_ALIASES
from recommender.schemas import Preferences, Restaurant

TIERS = ("low", "medium", "high")
# Relaxing the budget adds one neighbouring tier. Medium widens to the cheaper side:
# going under budget is safer than going over.
BUDGET_RELAX = {"low": "medium", "medium": "low", "high": "medium"}
RATING_STEP = 0.5


class ScoredRestaurant(Restaurant):
    score: float | None = None  # vote-weighted rating used for pre-ranking


@dataclass
class Shortlist:
    restaurants: list[ScoredRestaurant] = field(default_factory=list)
    matched: int = 0  # how many passed the filters before the shortlist cut
    relaxed_constraints: list[str] = field(default_factory=list)
    message: str | None = None


def _norm(value) -> str | None:
    return " ".join(value.split()).casefold() if isinstance(value, str) else None


def _mask(series: pd.Series) -> pd.Series:
    # Nullable comparisons yield <NA> for missing values; treat those as "no match".
    return series.fillna(False).astype(bool)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Add matching keys and the pre-ranking score. Done once, when data is loaded."""
    df = df.copy()
    df["_city"] = df["city"].map(_norm)
    df["_locality"] = df["locality"].map(_norm)
    df["_cuisines"] = df["cuisines"].map(lambda xs: frozenset(_norm(x) for x in xs))

    # Bayesian average: few votes pull a rating toward the dataset mean, so a
    # 5.0 from 3 votes doesn't outrank a 4.5 from 2,000.
    rating = df["rating"].to_numpy(dtype=float, na_value=np.nan)
    votes = df["votes"].to_numpy(dtype=float)
    rated = ~np.isnan(rating)
    prior_mean = float(rating[rated].mean()) if rated.any() else 0.0
    prior_votes = max(float(np.median(votes[rated])) if rated.any() else 1.0, 1.0)
    df["_score"] = (votes * rating + prior_votes * prior_mean) / (votes + prior_votes)
    return df


def resolve_location(location: str, df: pd.DataFrame) -> tuple[str, str] | None:
    """Map user input to ("_city" | "_locality", key), or None if unknown."""
    key = _norm(location)
    key = _norm(CITY_ALIASES.get(key, key))
    if (df["_city"] == key).any():
        return "_city", key
    if (df["_locality"] == key).any():
        return "_locality", key
    return None


def _location_mask(df: pd.DataFrame, col: str, key: str) -> pd.Series:
    if col == "_city":
        return _mask(df[col] == key)
    # A neighbourhood also covers its sub-areas: "koramangala" -> "koramangala 5th block",
    # "whitefield" -> "itpl main road, whitefield".
    loc = df[col].fillna("")
    return (loc == key) | loc.str.startswith(key + " ") | loc.str.endswith(", " + key)


def _apply(df: pd.DataFrame, tiers: set[str] | None, min_rating: float) -> pd.DataFrame:
    keep = pd.Series(True, index=df.index)
    if tiers:
        keep &= _mask(df["budget_tier"].isin(tiers))
    if min_rating > 0:
        keep &= _mask(df["rating"] >= min_rating)  # unrated never meets a minimum
    return df[keep]


def to_restaurant(row: dict, cls: type[Restaurant] = Restaurant) -> Restaurant:
    def plain(v):
        if isinstance(v, (list, tuple, np.ndarray)):
            return [str(x) for x in v]
        if v is None or pd.isna(v):
            return None
        return v.item() if hasattr(v, "item") else v

    fields = cls.model_fields
    return cls(**{k: plain(v) for k, v in row.items() if k in fields})


def shortlist(df: pd.DataFrame, prefs: Preferences, size: int) -> Shortlist:
    """Filter a prepare()d frame, relax if nothing matches, return the top `size`."""
    loc = resolve_location(prefs.location, df)
    if loc is None:
        cities = ", ".join(sorted(df["city"].dropna().unique()))
        return Shortlist(message=(
            f'No restaurants found for "{prefs.location}". This data covers {cities} only: '
            "choose the city or one of its neighbourhoods."
        ))
    base = df[_location_mask(df, *loc)]

    notes: list[str] = []
    wanted = {_norm(c) for c in prefs.cuisine}
    if wanted:
        known = frozenset().union(*df["_cuisines"])
        unknown = [c for c in prefs.cuisine if _norm(c) not in known]
        if len(unknown) == len(prefs.cuisine):
            return Shortlist(message=f"No restaurants in this data serve {', '.join(unknown)}.")
        if unknown:
            notes.append(f"No restaurants serve {', '.join(unknown)}; matched the other cuisines.")
        base = base[base["_cuisines"].map(lambda s: not s.isdisjoint(wanted))]

    # Relax in a fixed order, only when nothing matches. Location and cuisine stay hard.
    tiers = {prefs.budget} if prefs.budget else None
    min_rating = prefs.min_rating
    relaxed: list[str] = []
    matches = _apply(base, tiers, min_rating)
    if matches.empty and min_rating > 0:
        new_rating = max(0.0, min_rating - RATING_STEP)
        relaxed.append(f"min_rating relaxed from {min_rating:g} to {new_rating:g}")
        min_rating = new_rating
        matches = _apply(base, tiers, min_rating)
    if matches.empty and prefs.budget:
        extra = BUDGET_RELAX[prefs.budget]
        relaxed.append(f"budget relaxed from {prefs.budget} to {prefs.budget} or {extra}")
        tiers = {prefs.budget, extra}
        matches = _apply(base, tiers, min_rating)

    if matches.empty:
        tried = " even after loosening the rating and budget" if relaxed else ""
        return Shortlist(message=" ".join(notes + [f"No restaurants match these preferences{tried}."]))

    if len(matches) < prefs.top_k:
        notes.append(f"Only {len(matches)} restaurant{'s' if len(matches) != 1 else ''} matched.")

    ranked = matches.sort_values(
        ["_score", "votes", "name", "id"],
        ascending=[False, False, True, True],
        na_position="last",
        kind="stable",
    ).head(size)
    restaurants = [
        to_restaurant({**row, "score": row["_score"]}, ScoredRestaurant)
        for row in ranked.to_dict("records")
    ]
    return Shortlist(
        restaurants=restaurants,
        matched=len(matches),
        relaxed_constraints=relaxed,
        message=" ".join(notes) or None,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Print the shortlist for a set of preferences.")
    p.add_argument("--location", "--city", required=True, help="Bangalore or a neighbourhood")
    p.add_argument("--budget", choices=TIERS)
    p.add_argument("--cuisine", action="append", default=[], help="repeatable, or comma-separated")
    p.add_argument("--min-rating", type=float, default=0.0)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--size", type=int, help="shortlist size (default: SHORTLIST_SIZE)")
    args = p.parse_args(argv)

    from pydantic import ValidationError

    from recommender.store import RestaurantStore  # store imports this module

    cuisines = [c for arg in args.cuisine for c in arg.split(",")]
    try:
        prefs = Preferences(location=args.location, budget=args.budget, cuisine=cuisines,
                            min_rating=args.min_rating, top_k=args.top_k)
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 2
    result = RestaurantStore.load().query(prefs, size=args.size)

    print(f"Matched {result.matched}, showing {len(result.restaurants)}")
    for r in result.relaxed_constraints:
        print(f"Relaxed: {r}")
    if result.message:
        print(f"Note: {result.message}")
    if result.restaurants:
        table = pd.DataFrame([{
            "name": r.name[:32],
            "locality": (r.locality or "")[:22],
            "cuisines": ", ".join(r.cuisines)[:34],
            "cost": r.cost_for_two,
            "tier": r.budget_tier,
            "rating": r.rating,
            "votes": r.votes,
            "score": None if r.score is None else round(r.score, 2),
        } for r in result.restaurants])
        table.index += 1
        print(table.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())

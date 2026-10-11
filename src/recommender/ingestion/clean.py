"""Turn raw Zomato rows into one clean row per outlet (architecture.md §5.1)."""

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import pandas as pd

REQUIRED_COLUMNS = [
    "url", "name", "online_order", "book_table", "rate", "votes", "location",
    "rest_type", "dish_liked", "cuisines", "approx_cost(for two people)",
    "listed_in(type)", "listed_in(city)",
]

# URL city slug -> canonical city name.
CITY_ALIASES = {"bangalore": "Bangalore", "bengaluru": "Bangalore"}

NULL_RATINGS = {"", "NEW", "-"}

COLUMNS = [
    "id", "name", "city", "locality", "cuisines", "cost_for_two", "budget_tier",
    "rating", "votes", "tags", "popular_dishes",
]


@dataclass
class CleanReport:
    rows_in: int = 0
    dropped: Counter = field(default_factory=Counter)
    duplicates_merged: int = 0
    invalid_ratings: int = 0
    rows_out: int = 0


def fix_text(value) -> str | None:
    """Undo repeated UTF-8-read-as-Latin-1 encoding and collapse whitespace."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value)
    for _ in range(10):
        try:
            fixed = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if fixed == s:
            break
        s = fixed
    # Leftover C1 control bytes are Windows-1252 punctuation (e.g. \x92 -> ’).
    s = "".join(
        bytes([ord(c)]).decode("cp1252", errors="ignore") if 0x80 <= ord(c) <= 0x9F else c
        for c in s
    )
    s = " ".join(s.split())
    return s or None


def parse_rating(value) -> float | None:
    """'4.1/5', '4.1 /5', '4.1', 4.1 -> 4.1; 'NEW', '-', blanks, out-of-range -> None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).replace(" ", "").replace(",", ".")
    if s.upper() in NULL_RATINGS:
        return None
    s = s.removesuffix("/5")
    try:
        r = float(s)
    except ValueError:
        return None
    return r if 0 <= r <= 5 else None


def parse_cost(value) -> int | None:
    """'1,200', '₹1,200', '800', 800.0 -> int; missing, zero, negative, junk -> None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).replace(",", "").replace("₹", "").strip()
    try:
        c = int(float(s))
    except ValueError:
        return None
    return c if c > 0 else None


def split_list(value) -> list[str]:
    """'A, b,,A ' -> ['A', 'b']: strip, drop blanks, de-duplicate case-insensitively."""
    text = fix_text(value)
    if not text:
        return []
    seen, out = set(), []
    for item in text.split(","):
        item = item.strip()
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            out.append(item)
    return out


def outlet_key(url) -> str | None:
    """Zomato URL without its query string identifies one outlet."""
    if not isinstance(url, str) or not url.strip():
        return None
    parts = urlsplit(url.strip())
    return f"{parts.netloc}{parts.path}".rstrip("/").lower() or None


def city_from_key(key: str) -> str | None:
    # "www.zomato.com/bangalore/jalsa-banashankari" -> Bangalore.
    # Vanity URLs ("www.zomato.com/barleyz") carry no city -> None.
    segments = key.split("/")
    if len(segments) < 3:
        return None
    slug = segments[1]
    return CITY_ALIASES.get(slug, slug.replace("-", " ").title() or None)


def row_tags(row) -> set[str]:
    tags = {t.lower() for t in split_list(row["rest_type"])}
    if isinstance(row["listed_in(type)"], str) and row["listed_in(type)"].strip():
        tags.add(row["listed_in(type)"].strip().lower())
    if str(row["online_order"]).strip().lower() == "yes":
        tags.add("online ordering")
    if str(row["book_table"]).strip().lower() == "yes":
        tags.add("table booking")
    return tags


def budget_thresholds(costs: pd.Series) -> tuple[int, int]:
    """33rd and 66th percentile of cost, taken as real values from the data."""
    costs = costs.dropna()
    if costs.empty:
        raise ValueError("no costs to compute budget thresholds from")
    low_max = int(costs.quantile(0.33, interpolation="lower"))
    medium_max = int(costs.quantile(0.66, interpolation="lower"))
    return low_max, medium_max


def assign_tier(cost, low_max: int, medium_max: int) -> str | None:
    if cost is None or pd.isna(cost):
        return None
    if cost <= low_max:
        return "low"
    return "medium" if cost <= medium_max else "high"


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, tuple[int, int], CleanReport]:
    """Return (outlets, (low_max, medium_max), report). Raises on unusable input."""
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"dataset is missing expected columns: {missing}")

    report = CleanReport(rows_in=len(raw))
    df = raw[REQUIRED_COLUMNS].copy()

    df["key"] = df["url"].map(outlet_key)
    df["name_clean"] = df["name"].map(fix_text)
    # Missing strings arrive as NaN, not None, so test with isinstance rather than truthiness.
    df["city"] = df["key"].map(lambda k: city_from_key(k) if isinstance(k, str) else None)
    # In a single-city dataset, vanity URLs belong to that city; otherwise they are dropped.
    known_cities = df["city"].dropna().unique()
    if len(known_cities) == 1:
        df["city"] = df["city"].fillna(known_cities[0])

    for reason, col in [("no url", "key"), ("no name", "name_clean"), ("no city", "city")]:
        mask = df[col].isna()  # recomputed on what is left after earlier drops
        if mask.any():
            report.dropped[reason] += int(mask.sum())
            df = df[~mask]
    if df.empty:
        raise ValueError("no rows left after cleaning")

    df["rating_clean"] = df["rate"].map(parse_rating)
    raw_present = df["rate"].map(
        lambda v: isinstance(v, str) and v.replace(" ", "").upper() not in NULL_RATINGS
    ).astype(bool)
    report.invalid_ratings = int((raw_present & df["rating_clean"].isna()).sum())

    df["votes_clean"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0).clip(lower=0).astype(int)
    df["tags_row"] = df.apply(row_tags, axis=1)

    # One row per outlet: scalars from its most-voted listing, tags from all listings.
    df = df.sort_values(["votes_clean", "key"], ascending=[False, True], kind="stable")
    tags_by_key = df.groupby("key")["tags_row"].agg(lambda s: sorted(set().union(*s)))
    best = df.drop_duplicates("key", keep="first").set_index("key")
    report.duplicates_merged = len(df) - len(best)

    out = pd.DataFrame({
        "id": [hashlib.sha1(k.encode()).hexdigest()[:12] for k in best.index],
        "name": best["name_clean"].values,
        "city": best["city"].values,
        # Fall back to the Zomato listing area when the neighbourhood is missing.
        "locality": [fix_text(loc) or fix_text(area)
                     for loc, area in zip(best["location"], best["listed_in(city)"])],
        "cuisines": best["cuisines"].map(split_list).values,
        "cost_for_two": pd.array(best["approx_cost(for two people)"].map(parse_cost).values, dtype="Int64"),
        "rating": pd.array(best["rating_clean"].values, dtype="Float64"),
        "votes": best["votes_clean"].values,
        "tags": tags_by_key.loc[best.index].values,
        "popular_dishes": best["dish_liked"].map(split_list).values,
    })
    if out["id"].duplicated().any():
        raise ValueError("outlet id collision; widen the id hash")

    thresholds = budget_thresholds(out["cost_for_two"].astype("float64"))
    out["budget_tier"] = pd.array(
        [assign_tier(c, *thresholds) for c in out["cost_for_two"]], dtype="string"
    )
    out = out[COLUMNS].sort_values("id", kind="stable").reset_index(drop=True)
    report.rows_out = len(out)
    return out, thresholds, report

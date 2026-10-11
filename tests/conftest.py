import pandas as pd
import pytest

from recommender.ingestion import cli
from recommender.ingestion.clean import COLUMNS
from recommender.store import RestaurantStore

# (id, name, locality, cuisines, cost, tier, rating, votes)
FIXTURE = [
    ("r1", "Popular", "BTM", ["North Indian", "Chinese"], 400, "medium", 4.5, 2000),
    ("r2", "Hyped", "BTM", ["North Indian"], 450, "medium", 5.0, 3),
    ("r3", "Cheap Eats", "BTM", ["South Indian"], 150, "low", 3.8, 500),
    ("r4", "Fancy", "Indiranagar", ["Italian"], 1500, "high", 4.6, 800),
    ("r5", "New Place", "BTM", ["North Indian"], 300, "low", None, 0),
    ("r6", "Mid Italian", "Indiranagar", ["Italian", "Pizza"], 450, "medium", 4.0, 100),
    ("r7", "Pricey BTM", "BTM", ["Chinese"], 1200, "high", 4.2, 300),
    ("r8", "No Cost", "HSR", ["Biryani"], None, None, 4.1, 50),
    ("r9", "Block Five", "Koramangala 5th Block", ["Cafe"], 600, "high", 4.3, 400),
    ("r10", "Plain Kora", "Koramangala", ["Cafe"], 350, "medium", 3.9, 90),
    ("r11", "ITPL Diner", "ITPL Main Road, Whitefield", ["Cafe"], 300, "low", 3.7, 60),
    ("r12", "Whitefield Plain", "Whitefield", ["Cafe"], 300, "low", 3.6, 30),
]


def fixture_frame() -> pd.DataFrame:
    df = pd.DataFrame([
        {"id": i, "name": n, "city": "Bangalore", "locality": loc, "cuisines": cu,
         "cost_for_two": cost, "budget_tier": tier, "rating": rating, "votes": votes,
         "tags": [], "popular_dishes": []}
        for i, n, loc, cu, cost, tier, rating, votes in FIXTURE
    ])
    df["cost_for_two"] = df["cost_for_two"].astype("Int64")
    df["rating"] = df["rating"].astype("Float64")
    return df[COLUMNS]


@pytest.fixture
def data_dir(tmp_path):
    # Written and read back through the real path, so dtypes match production.
    df = fixture_frame()
    cli.write_outputs(df, cli.build_meta(df, (300, 500)), tmp_path)
    return tmp_path


@pytest.fixture
def store(data_dir):
    return RestaurantStore.load(data_dir)

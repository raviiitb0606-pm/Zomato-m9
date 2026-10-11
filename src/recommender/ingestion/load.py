"""Pull the raw Zomato dataset from Hugging Face."""

import pandas as pd
from datasets import load_dataset

DATASET_ID = "ManikaSaini/zomato-restaurant-recommendation"


def load_raw() -> pd.DataFrame:
    # Downloads on first run, then reuses the local Hugging Face cache.
    ds = load_dataset(DATASET_ID, split="train")
    return ds.to_pandas()

"""Feature engineering shared by training and live scoring.

Using one function for both is what stops training and production from
quietly drifting apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import reference as ref

CATEGORIES = {
    "industry": sorted(ref.INDUSTRY_WEIGHTS),
    "asset_category": sorted(ref.ASSETS),
    "condition": ["New", "Used"],
}
# Deliberately left out: state, entity type and channel. They have no clear
# credit rationale, and location-based pricing raises fairness questions.
# A feature has to earn its place with a business reason, not just a signal.
NUMERIC = ["credit_score", "abn_age_months", "loan_amount", "term_months", "balloon_pct",
           "balloon_gap", "asset_age_years", "asset_age_at_end", "lvr"]
FEATURES = NUMERIC + list(CATEGORIES)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Turn application fields into model inputs."""
    d = df.copy()
    price = d["asset_price"].astype(float)
    years = d["term_months"].astype(float) / 12
    submitted_year = pd.to_datetime(d.get("submitted_date", pd.Timestamp.today())).dt.year \
        if "submitted_date" in d else pd.Timestamp.today().year
    if "asset_age_years" not in d:
        d["asset_age_years"] = submitted_year - d["asset_year"].astype(float)
    dep = d["asset_category"].map({k: v["depreciation"] for k, v in ref.ASSETS.items()}).astype(float)
    expected_value_at_end = price * (1 - dep) ** years

    out = pd.DataFrame(index=d.index)
    out["credit_score"] = d["credit_score"].astype(float)
    out["abn_age_months"] = d["abn_age_months"].astype(float)
    out["loan_amount"] = d["loan_amount"].astype(float)
    out["term_months"] = d["term_months"].astype(float)
    out["balloon_pct"] = d["balloon_amount"].astype(float) / price
    # How far the balloon sits above what the asset should be worth when it falls due.
    out["balloon_gap"] = np.maximum(d["balloon_amount"].astype(float) - expected_value_at_end, 0) / price
    out["asset_age_years"] = d["asset_age_years"].astype(float)
    out["asset_age_at_end"] = out["asset_age_years"] + years
    out["lvr"] = d["loan_amount"].astype(float) / price
    for col, levels in CATEGORIES.items():
        out[col] = pd.Categorical(d[col], categories=levels)
    return out[FEATURES]

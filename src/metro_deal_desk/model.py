"""Credit risk model: LightGBM with per-application explanations.

Explanations are SHAP values computed by LightGBM's built-in TreeSHAP
(`pred_contrib=True`), so no extra dependency is needed. Each value is how
much a feature pushed this application's log-odds of default up or down
compared with the average application.
"""
from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from .features import FEATURES, NUMERIC, build_features

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "credit_model.txt"
CARD_PATH = MODEL_DIR / "model_card.json"

# Business logic the model must respect, whatever the data says:
# a better credit score or a longer trading history never raises risk; a bigger
# balloon gap, an older asset at the end of term or a higher loan-to-value
# ratio never lowers it.
MONOTONE = {"credit_score": -1, "abn_age_months": -1, "balloon_gap": 1, "asset_age_at_end": 1, "lvr": 1}

PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=15, min_child_samples=80,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
              monotone_constraints=[MONOTONE.get(f, 0) for f in FEATURES],
              monotone_constraints_method="advanced", verbose=-1, seed=42)

RISK_GRADES = [(0.02, "A"), (0.04, "B"), (0.07, "C"), (0.12, "D"), (1.01, "E")]


def time_split(df: pd.DataFrame, test_share: float = 0.2):
    """Train on older applications, test on the newest, as a lender would."""
    d = df.sort_values("submitted_date", kind="stable")
    cut = int(len(d) * (1 - test_share))
    return d.iloc[:cut], d.iloc[cut:]


def train(history: pd.DataFrame, save: bool = True):
    train_df, test_df = time_split(history)
    fit_df, val_df = time_split(train_df, test_share=0.15)  # for early stopping
    X_fit, X_val, X_test = (build_features(x) for x in (fit_df, val_df, test_df))
    booster = lgb.train(PARAMS, lgb.Dataset(X_fit, fit_df["defaulted"]), num_boost_round=2000,
                        valid_sets=[lgb.Dataset(X_val, val_df["defaulted"])],
                        callbacks=[lgb.early_stopping(100, verbose=False)])
    p_test = booster.predict(X_test, num_iteration=booster.best_iteration)
    card = {
        "model": "LightGBM gradient boosted trees",
        "trained_on": f"{len(fit_df):,} synthetic applications "
                      f"({fit_df['submitted_date'].min()} to {fit_df['submitted_date'].max()})",
        "validated_on": f"{len(val_df):,} applications for early stopping "
                        f"({val_df['submitted_date'].min()} to {val_df['submitted_date'].max()})",
        "tested_on": f"{len(test_df):,} newer applications "
                     f"({test_df['submitted_date'].min()} to {test_df['submitted_date'].max()})",
        "test_auc": round(float(roc_auc_score(test_df["defaulted"], p_test)), 3),
        "test_brier": round(float(brier_score_loss(test_df["defaulted"], p_test)), 4),
        "test_default_rate": round(float(test_df["defaulted"].mean()), 4),
        "mean_predicted_pd": round(float(p_test.mean()), 4),
        "best_iteration": booster.best_iteration,
        "features": FEATURES,
        "monotone_constraints": MONOTONE,
        "risk_grades": {g: t for t, g in RISK_GRADES},
        "data": "Synthetic. Not trained on any real lender's data.",
    }
    if save:
        MODEL_DIR.mkdir(exist_ok=True)
        booster.save_model(str(MODEL_PATH), num_iteration=booster.best_iteration)
        CARD_PATH.write_text(json.dumps(card, indent=2))
        # Training-time snapshot used by monitoring.py to spot drift later.
        from . import monitoring
        monitoring.save_reference(monitoring.build_reference(train_df, booster.predict(
            build_features(train_df), num_iteration=booster.best_iteration)))
    return booster, card, (train_df, test_df, p_test)


_BOOSTER = None


def load() -> lgb.Booster:
    global _BOOSTER
    if _BOOSTER is None:
        _BOOSTER = lgb.Booster(model_file=str(MODEL_PATH))
    return _BOOSTER


def predict_pd(apps: pd.DataFrame, booster: lgb.Booster | None = None) -> np.ndarray:
    return (booster or load()).predict(build_features(apps))


def risk_grade(pd_value: float) -> str:
    return next(g for t, g in RISK_GRADES if pd_value < t)


# --- Explanations -----------------------------------------------------------
def _describe(feature: str, row: pd.Series) -> str:
    v = row[feature]
    years = lambda m: f"{m / 12:.1f} years" if m >= 24 else f"{m:.0f} months"
    phrases = {
        "credit_score": lambda: f"Director credit score of {v:.0f}",
        "abn_age_months": lambda: f"Business trading for {years(v)}",
        "loan_amount": lambda: f"Loan size of ${v:,.0f}",
        "term_months": lambda: f"{v:.0f}-month term",
        "balloon_pct": lambda: f"Balloon of {v:.0%} of the asset price" if v > 0 else "No balloon",
        "balloon_gap": lambda: ("Balloon is above the asset's expected resale value at the end of the term"
                                if v > 0 else "Balloon is covered by the asset's expected resale value"),
        "asset_age_years": lambda: f"Asset is {v:.0f} years old" if v >= 1 else "Asset is new",
        "asset_age_at_end": lambda: f"Asset will be {v:.0f} years old at the end of the term",
        "lvr": lambda: f"Loan is {v:.0%} of the asset price",
        "industry": lambda: f"{v} industry",
        "asset_category": lambda: f"Asset type: {v}",
        "condition": lambda: f"{v} asset",
        "state": lambda: f"Located in {v}",
        "entity_type": lambda: f"Borrower is a {str(v).lower()}",
        "channel": lambda: f"Submitted through a {str(v).lower()}",
    }
    return phrases[feature]()


def explain(apps: pd.DataFrame, top_n: int = 3, booster: lgb.Booster | None = None) -> list[dict]:
    """Top reasons pushing each application's risk up and down."""
    X = build_features(apps)
    contrib = (booster or load()).predict(X, pred_contrib=True)[:, :-1]  # last column is the baseline
    out = []
    for i in range(len(X)):
        row, c = X.iloc[i], contrib[i]
        order = np.argsort(-c)
        up = [{"feature": FEATURES[j], "reason": _describe(FEATURES[j], row), "impact": round(float(c[j]), 3)}
              for j in order[:top_n] if c[j] > 0.02]
        down = [{"feature": FEATURES[j], "reason": _describe(FEATURES[j], row), "impact": round(float(c[j]), 3)}
                for j in order[::-1][:top_n] if c[j] < -0.02]
        out.append({"raises_risk": up, "lowers_risk": down})
    return out


def shap_values(apps: pd.DataFrame, booster: lgb.Booster | None = None) -> pd.DataFrame:
    X = build_features(apps)
    contrib = (booster or load()).predict(X, pred_contrib=True)[:, :-1]
    return pd.DataFrame(contrib, columns=FEATURES, index=apps.index)


if __name__ == "__main__":
    hist = pd.read_csv(ROOT / "data" / "synthetic" / "applications_history.csv")
    _, card, _ = train(hist)
    print(json.dumps({k: card[k] for k in ["test_auc", "test_brier", "test_default_rate",
                                           "mean_predicted_pd", "best_iteration"]}, indent=2))

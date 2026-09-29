"""Portfolio stress test: what happens to the approved book in a downturn?

For each approved application:
  stressed log-odds = baseline log-odds + ln(scenario multiplier) x industry sensitivity
  expected loss     = PD x LGD x exposure

Scenario multipliers and industry sensitivities are measured from real SBA
loan vintages (cycle_calibration.py). Loss given default (LGD) by asset type,
and how much it rises in a downturn, are labelled assumptions.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .decision import APPROVE_BELOW, DECLINE_FROM

ROOT = Path(__file__).resolve().parents[2]
CYCLE = ROOT / "data" / "calibration" / "cycle_sensitivity.json"

# ASSUMPTION: share of the balance lost if a secured loan defaults, after the
# asset is repossessed and sold. Mainstream vehicles resell easily; specialised
# equipment (fit-outs, medical, CNC) does not.
LGD = {"Car / SUV": 0.35, "Ute / van": 0.35, "Truck": 0.40, "Earthmoving equipment": 0.40,
       "Agricultural machinery": 0.35, "Trailer": 0.45, "Other equipment": 0.60}
# ASSUMPTION: in the worst scenario, used asset prices fall and LGD rises by up
# to 10 percentage points ("downturn LGD"), scaled by scenario severity.
DOWNTURN_LGD_UPLIFT = 0.10


def load_calibration() -> dict:
    return json.loads(CYCLE.read_text())


def scenarios() -> list[dict]:
    cal = load_calibration()
    return [{"key": k, **v} for k, v in cal["scenarios"].items()]


def _severity(multiplier: float, cal: dict) -> float:
    """0 at or below baseline, 1 at the GFC scenario."""
    worst = np.log(cal["scenarios"]["gfc"]["odds_multiplier"])
    return float(np.clip(np.log(multiplier) / worst, 0, 1))


def stressed_pd(pd_values, industries, multiplier: float, cal: dict | None = None) -> np.ndarray:
    cal = cal or load_calibration()
    sens = {k: v["sensitivity"] for k, v in cal["industry_sensitivity"].items()}
    p = np.clip(np.asarray(pd_values, dtype=float), 1e-6, 1 - 1e-6)
    beta = np.array([sens.get(i, 1.0) for i in industries])
    z = np.log(p / (1 - p)) + np.log(multiplier) * beta
    return 1 / (1 + np.exp(-z))


def lgd(asset_categories, multiplier: float = 1.0, cal: dict | None = None) -> np.ndarray:
    cal = cal or load_calibration()
    base = np.array([LGD.get(a, 0.5) for a in asset_categories])
    return np.clip(base + DOWNTURN_LGD_UPLIFT * _severity(multiplier, cal), 0, 1)


def run(book: pd.DataFrame, scenario: str | None = "gfc", multiplier: float | None = None) -> dict:
    """Stress a book of scored applications.

    book needs columns: industry, asset_category, loan_amount, pd.
    Give either a named scenario or a custom odds multiplier.
    """
    cal = load_calibration()
    if multiplier is None:
        if scenario not in cal["scenarios"]:
            raise ValueError(f"Unknown scenario '{scenario}'. Options: {', '.join(cal['scenarios'])}")
        multiplier = cal["scenarios"][scenario]["odds_multiplier"]
        label = cal["scenarios"][scenario]["label"]
    else:
        label = f"Custom (odds x{multiplier:g})"

    b = book.dropna(subset=["pd"]).copy()
    b["pd_stressed"] = stressed_pd(b["pd"], b["industry"], multiplier, cal)
    b["lgd_base"] = lgd(b["asset_category"], 1.0, cal)
    b["lgd_stressed"] = lgd(b["asset_category"], multiplier, cal)
    b["el_base"] = b["pd"] * b["lgd_base"] * b["loan_amount"]
    b["el_stressed"] = b["pd_stressed"] * b["lgd_stressed"] * b["loan_amount"]
    exposure = float(b["loan_amount"].sum())

    def band(p):
        return np.where(p < APPROVE_BELOW, "Approve", np.where(p < DECLINE_FROM, "Refer", "Decline"))

    b["band_base"], b["band_stressed"] = band(b["pd"]), band(b["pd_stressed"])
    migration = (pd.crosstab(b["band_base"], b["band_stressed"])
                 .reindex(index=["Approve", "Refer", "Decline"], columns=["Approve", "Refer", "Decline"], fill_value=0))

    by_ind = (b.groupby("industry")
              .agg(loans=("pd", "size"), exposure=("loan_amount", "sum"),
                   pd_base=("pd", "mean"), pd_stressed=("pd_stressed", "mean"),
                   el_base=("el_base", "sum"), el_stressed=("el_stressed", "sum"))
              .assign(el_uplift=lambda t: t["el_stressed"] / t["el_base"])
              .sort_values("el_stressed", ascending=False))

    r2 = lambda x: round(float(x), 2)
    return {
        "scenario": scenario if multiplier == cal["scenarios"].get(scenario, {}).get("odds_multiplier") else "custom",
        "label": label, "odds_multiplier": multiplier,
        "loans": int(len(b)), "exposure": r2(exposure),
        "baseline": {"avg_pd_pct": r2(100 * b["pd"].mean()), "expected_defaults": r2(b["pd"].sum()),
                     "expected_loss": r2(b["el_base"].sum()),
                     "expected_loss_pct": r2(100 * b["el_base"].sum() / exposure)},
        "stressed": {"avg_pd_pct": r2(100 * b["pd_stressed"].mean()), "expected_defaults": r2(b["pd_stressed"].sum()),
                     "expected_loss": r2(b["el_stressed"].sum()),
                     "expected_loss_pct": r2(100 * b["el_stressed"].sum() / exposure)},
        "would_no_longer_auto_approve_pct": r2(100 * ((b["band_base"] == "Approve") & (b["band_stressed"] != "Approve")).sum()
                                               / max((b["band_base"] == "Approve").sum(), 1)),
        "decision_migration": {i: {c: int(migration.loc[i, c]) for c in migration.columns} for i in migration.index},
        "by_industry": [{"industry": k, "loans": int(r.loans), "exposure": r2(r.exposure),
                         "avg_pd_base_pct": r2(100 * r.pd_base), "avg_pd_stressed_pct": r2(100 * r.pd_stressed),
                         "expected_loss_base": r2(r.el_base), "expected_loss_stressed": r2(r.el_stressed),
                         "loss_multiple": r2(r.el_uplift)} for k, r in by_ind.iterrows()],
        "assumptions": {"lgd_by_asset": LGD, "downturn_lgd_uplift_at_gfc": DOWNTURN_LGD_UPLIFT,
                        "exposure": "full loan amount at default (conservative simplification)"},
    }

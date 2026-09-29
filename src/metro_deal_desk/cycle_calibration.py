"""Recession calibration from the real SBA data.

Two things are measured and saved to data/calibration/cycle_sensitivity.json:

1. Scenario severity. Each stress scenario is tied to a real SBA loan vintage,
   expressed as an odds multiplier against the through-the-cycle average
   (the level the synthetic book is calibrated to).
2. Industry sensitivity. How much harder each industry was hit in the crisis
   vintages (2006-2008) than in calm ones (2000-2003), relative to the average
   industry. Small industries are shrunk toward average so a handful of loans
   cannot produce an extreme number.

Needs the raw SBA CSV (not in the repo). The output JSON is committed, so the
API and tests do not need the raw data.

Run from the repo root:
    python -m metro_deal_desk.cycle_calibration
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SBA_EFFECTS = ROOT / "data" / "calibration" / "sba_effects.json"
OUT = ROOT / "data" / "calibration" / "cycle_sensitivity.json"
RAW_CANDIDATES = [ROOT / "data" / "raw" / "SBAnational.csv",
                  ROOT.parent / "should_this_loan_be_approved" / "SBAnational.csv"]

INDUSTRY_MAP = {  # same grouping as notebook 01
    "11": "Agriculture", "21": "Mining", "23": "Construction & trades",
    "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
    "42": "Wholesale trade", "44": "Retail trade", "45": "Retail trade",
    "48": "Transport & logistics", "49": "Transport & logistics",
    "54": "Professional services", "56": "Admin & support services",
    "62": "Health care", "72": "Hospitality", "81": "Other services",
}
SHRINK_LOANS = 2000  # credibility weight: an industry needs about this many loans to be trusted fully

# Scenario -> SBA vintages it is modelled on.
SCENARIOS = {
    "benign": {"label": "Benign (like 2000-2002)", "vintages": [2000, 2001, 2002]},
    "baseline": {"label": "Baseline (through the cycle)", "vintages": None},
    "mild": {"label": "Mild downturn (like 2005)", "vintages": [2005]},
    "severe": {"label": "Severe downturn (like 2006)", "vintages": [2006]},
    "gfc": {"label": "GFC (like 2007)", "vintages": [2007]},
}


def _load_sba() -> pd.DataFrame:
    raw = next(p for p in RAW_CANDIDATES if p.exists())
    df = pd.read_csv(raw, low_memory=False)
    d = pd.to_datetime(df["DisbursementDate"], format="%d-%b-%y", errors="coerce")
    df["disbursed"] = d.where(d.dt.year <= 2014, d - pd.DateOffset(years=100))
    df = df[df["MIS_Status"].notna()].copy()
    df["default"] = (df["MIS_Status"] == "CHGOFF").astype(int)
    df["sector"] = df["NAICS"].astype(str).str[:2]
    keep = (df["disbursed"].between("2000-01-01", "2010-12-31") & df["Term"].between(1, 239)
            & (df["sector"] != "0") & ~df["RevLineCr"].isin(["Y", "T"]) & df["NewExist"].isin([1, 2]))
    s = df[keep].copy()
    s["vintage"] = s["disbursed"].dt.year
    s["industry"] = s["sector"].map(INDUSTRY_MAP).fillna("Other")
    return s


def build() -> dict:
    sba = _load_sba()
    effects = json.loads(SBA_EFFECTS.read_text())
    vint_or = {int(k): v for k, v in effects["cycle_stress_odds_ratio_by_vintage"].items()}

    # Through-the-cycle average log odds, weighted by how many loans each vintage had.
    counts = sba["vintage"].value_counts()
    log_or = pd.Series({y: np.log(o) for y, o in vint_or.items()})
    ttc = float((log_or * counts.reindex(log_or.index)).sum() / counts.sum())

    scenarios = {}
    for key, sc in SCENARIOS.items():
        lvl = ttc if sc["vintages"] is None else float(np.mean([log_or[y] for y in sc["vintages"]]))
        scenarios[key] = {"label": sc["label"], "odds_multiplier": round(float(np.exp(lvl - ttc)), 3),
                          "based_on_vintages": sc["vintages"] or "2000-2010 average"}

    # Industry sensitivity: crisis vs calm odds, relative to all industries.
    era = np.where(sba["vintage"].between(2000, 2003), "calm",
                   np.where(sba["vintage"].between(2006, 2008), "crisis", None))
    e = sba.assign(era=era).dropna(subset=["era"])
    odds = lambda p: p / (1 - p)
    rate = e.groupby(["industry", "era"])["default"].mean().unstack()
    n = e.groupby("industry").size()
    overall = e.groupby("era")["default"].mean()
    log_all = np.log(odds(overall["crisis"]) / odds(overall["calm"]))
    raw_beta = np.log(odds(rate["crisis"]) / odds(rate["calm"])) / log_all
    weight = n / (n + SHRINK_LOANS)
    beta = weight * raw_beta + (1 - weight) * 1.0

    out = {
        "source": effects["source"],
        "method": ("Scenario odds multipliers compare an SBA vintage's odds of default with the loan-weighted "
                   "2000-2010 average, controlling for industry, size and business age (notebook 01). Industry "
                   "sensitivity compares crisis vintages (2006-2008) with calm ones (2000-2003), relative to all "
                   f"industries, shrunk toward 1 with a credibility weight of n / (n + {SHRINK_LOANS})."),
        "scenarios": scenarios,
        "industry_sensitivity": {k: {"sensitivity": round(float(beta[k]), 3),
                                     "crisis_vs_calm_odds_ratio": round(float(np.exp(raw_beta[k] * log_all)), 2),
                                     "sba_loans": int(n[k])} for k in beta.index},
    }
    OUT.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    r = build()
    for k, v in r["scenarios"].items():
        print(f"{v['label']:32s} odds x{v['odds_multiplier']}")
    for k, v in sorted(r["industry_sensitivity"].items(), key=lambda kv: kv[1]["sensitivity"]):
        print(f"  {k:26s} {v['sensitivity']:.2f}  (n={v['sba_loans']:,})")

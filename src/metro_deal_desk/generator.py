"""Synthetic loan applications shaped like an Australian vehicle and equipment lender.

All data produced here is SYNTHETIC. Relative risk effects are calibrated
against the US SBA dataset (data/calibration/sba_effects.json); levels,
prices and mixes come from Australian public sources or labelled assumptions
in reference.py.

Run from the repo root:
    python -m metro_deal_desk.generator
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import reference as ref

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION = ROOT / "data" / "calibration" / "sba_effects.json"
OUT_DIR = ROOT / "data" / "synthetic"
TODAY = pd.Timestamp("2026-09-28")

# Loan size bands in AUD, mapped to the SBA USD bands (scaled roughly for
# inflation and currency since the 2000s). ASSUMPTION.
SIZE_BANDS_AUD = [(0, 30_000, "<25k"), (30_000, 60_000, "25-50k"),
                  (60_000, 120_000, "50-100k"), (120_000, 300_000, "100-250k"),
                  (300_000, np.inf, "250k+")]


# --- Helpers ----------------------------------------------------------------
def _choice(rng, weights: dict, size: int):
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return rng.choice(keys, size=size, p=p / p.sum())


def abn_is_valid(abn: str) -> bool:
    """Australian Business Number checksum (ATO algorithm)."""
    if not isinstance(abn, str) or len(abn) != 11 or not abn.isdigit():
        return False
    digits = [int(c) for c in abn]
    digits[0] -= 1
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    return sum(d * w for d, w in zip(digits, weights)) % 89 == 0


def _make_abns(rng, n: int) -> list[str]:
    """Random 11-digit numbers that pass the ABN checksum.

    These are random numbers. Any match with a real ABN is coincidental.
    """
    w = np.array([10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19])
    out: list[str] = []
    while len(out) < n:
        d = rng.integers(0, 10, (n * 120, 11))
        d[:, 0] = rng.integers(1, 10, len(d))
        check = d.copy(); check[:, 0] -= 1
        ok = d[(check @ w) % 89 == 0]
        out += ["".join(map(str, row)) for row in ok[: n - len(out)]]
    return out


def _postcode(rng, state: str) -> str:
    lo, hi = ref.POSTCODE_RANGES[state][rng.integers(len(ref.POSTCODE_RANGES[state]))]
    return f"{rng.integers(lo, hi + 1):04d}"


def monthly_repayment(principal, annual_rate, term_months, balloon):
    """Level monthly repayment with a balloon due at the end of the term."""
    r = np.asarray(annual_rate) / 12
    n = np.asarray(term_months)
    pv_balloon = np.asarray(balloon) / (1 + r) ** n
    return (np.asarray(principal) - pv_balloon) * r / (1 - (1 + r) ** -n)


def size_band(amount):
    out = np.empty(len(amount), dtype=object)
    for lo, hi, label in SIZE_BANDS_AUD:
        out[(amount >= lo) & (amount < hi)] = label
    return out


# --- Applications -----------------------------------------------------------
def generate_applications(n: int, seed: int = 42, start: str = "2023-10-01",
                          end: str = "2026-09-27", n_brokers: int = 150) -> pd.DataFrame:
    """Generate n clean applications (the fields a broker would submit)."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(index=range(n))

    days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    df["submitted_date"] = pd.Timestamp(start) + pd.to_timedelta(np.sort(rng.integers(0, days + 1, n)), unit="D")
    df["channel"] = rng.choice(["Broker", "Dealer"], n, p=[0.85, 0.15])
    # A few large brokers send most deals (Pareto-like volume).
    broker_w = 1 / np.arange(1, n_brokers + 1) ** 0.8
    df["broker_id"] = [f"BRK-{i:03d}" for i in rng.choice(np.arange(1, n_brokers + 1), n, p=broker_w / broker_w.sum())]

    df["state"] = _choice(rng, ref.STATE_WEIGHTS, n)
    df["postcode"] = [_postcode(rng, s) for s in df["state"]]
    df["entity_type"] = _choice(rng, ref.ENTITY_TYPES, n)
    df["abn"] = _make_abns(rng, n)
    # Months since ABN registration: about 15% two years or less.
    df["abn_age_months"] = np.clip(np.round(rng.lognormal(np.log(70), 1.0, n)), 1, 480).astype(int)
    df["industry"] = _choice(rng, ref.INDUSTRY_WEIGHTS, n)
    # Director's consumer credit score, Equifax-style 0-1200 scale.
    df["credit_score"] = np.clip(np.round(rng.normal(730, 140, n)), 200, 1200).astype(int)

    # Asset
    cat = np.array([_choice(rng, ref.INDUSTRY_ASSET_MIX[i], 1)[0] for i in df["industry"]])
    df["asset_category"] = cat
    rows = []
    for c in cat:
        a = ref.ASSETS[c]
        model, fuel = a["models"][rng.integers(len(a["models"]))]
        is_new = rng.random() < (0.55 if c in ("Car / SUV", "Ute / van") else 0.45)
        age = 0 if is_new else int(rng.integers(1, 11))
        new_price = rng.uniform(*a["new_price"])
        price = new_price * (1 - a["depreciation"]) ** age
        term = int(rng.choice(a["terms"]))
        balloon_pct = rng.choice([0.0, rng.uniform(*a["balloon_range"])], p=[0.45, 0.55])
        rows.append((model, fuel, "New" if is_new else "Used", age, round(price, -2), term, balloon_pct))
    a = pd.DataFrame(rows, columns=["asset_model", "fuel_type", "condition", "asset_age_years",
                                    "asset_price", "term_months", "balloon_pct"])
    df = pd.concat([df, a], axis=1)
    df["asset_year"] = df["submitted_date"].dt.year - df["asset_age_years"]
    df["asset_description"] = df["asset_year"].astype(str) + " " + df["asset_model"]

    # Deal structure
    deposit_pct = rng.choice([0.0, 0.05, 0.10, 0.20], n, p=[0.55, 0.15, 0.2, 0.1])
    fees = rng.uniform(0, 0.04, n)  # on-road costs, brokerage and fees capitalised
    df["loan_amount"] = np.round(df["asset_price"] * (1 - deposit_pct + fees), -2)
    df["balloon_amount"] = np.round(df["asset_price"] * df["balloon_pct"], -2)
    df["lvr"] = df["loan_amount"] / df["asset_price"]

    # Risk-based pricing (what the broker is quoted).
    rate = (0.075 - (df["credit_score"] - 730) / 100 * 0.008
            + np.where(df["condition"] == "Used", 0.006, 0)
            + np.where(df["abn_age_months"] < 24, 0.01, 0)
            + np.where(df["loan_amount"] < 30_000, 0.01, 0)
            + rng.normal(0, 0.004, n))
    df["interest_rate"] = np.round(np.clip(rate, ref.RATE_FLOOR, ref.RATE_CEILING), 4)
    df["monthly_repayment"] = np.round(monthly_repayment(
        df["loan_amount"], df["interest_rate"], df["term_months"], df["balloon_amount"]), 2)

    df.insert(0, "application_id", [f"APP-{i:06d}" for i in range(1, n + 1)])
    return df.drop(columns=["balloon_pct", "asset_model"])


# --- Hidden default process -------------------------------------------------
def _risk_logit(df: pd.DataFrame, cal: dict, rng) -> np.ndarray:
    """Log-odds of default before the intercept. Never shown to the model."""
    ind_or = {k: v["odds_ratio"] for k, v in cal["industry"].items()}
    size_or = cal["loan_size_odds_ratio_usd"]
    z = np.log(df["industry"].map(ind_or).to_numpy())                          # SBA
    z += np.log(pd.Series(size_band(df["loan_amount"].to_numpy())).map(size_or).to_numpy())  # SBA

    age = df["abn_age_months"].to_numpy()
    z += np.where(age <= 24, np.log(cal["new_business_odds_ratio"]), 0)       # SBA
    z += np.where(age < 12, 0.25, 0)                                           # ASSUMPTION: first year riskiest

    z += -0.6 * (df["credit_score"].to_numpy() - 730) / 100                    # ASSUMPTION: about 0.55x odds per +100 points

    # Asset-finance logic (ASSUMPTIONS, replacing the SBA term effect)
    dep = df["asset_category"].map({k: v["depreciation"] for k, v in ref.ASSETS.items()}).to_numpy()
    years = df["term_months"].to_numpy() / 12
    value_at_end = df["asset_price"].to_numpy() * (1 - dep) ** years
    balloon_gap = np.maximum(df["balloon_amount"].to_numpy() - value_at_end, 0) / df["asset_price"].to_numpy()
    z += 3.0 * balloon_gap                                                     # balloon above expected resale value
    z += 0.08 * (years - 4)                                                    # longer terms repay principal more slowly
    z += np.where(df["asset_age_years"].to_numpy() + years > 12, 0.35, 0)     # old at end of term
    z += np.where(df["lvr"].to_numpy() > 1.0, 0.2, 0) - np.where(df["lvr"].to_numpy() <= 0.85, 0.3, 0)

    # Interactions
    balloon_pct = df["balloon_amount"].to_numpy() / df["asset_price"].to_numpy()
    z += np.where((age <= 24) & (balloon_pct >= 0.3), 0.35, 0)
    z += np.where((df["industry"].to_numpy() == "Construction & trades") & (df["asset_category"].to_numpy() == "Earthmoving equipment"), 0.2, 0)

    # Unobserved factors: broker quality and everything else the form cannot see.
    brokers = df["broker_id"].unique()
    broker_effect = dict(zip(brokers, rng.normal(0, 0.35, len(brokers))))
    z += df["broker_id"].map(broker_effect).to_numpy()
    z += rng.normal(0, 0.7, len(df))
    return z


def assign_outcomes(df: pd.DataFrame, seed: int = 7, target_rate: float = ref.TARGET_DEFAULT_RATE,
                    cycle_odds_ratio: float = 1.0) -> pd.DataFrame:
    """Add true default probability and a sampled default outcome.

    cycle_odds_ratio scales everyone's odds, for stress scenarios; the SBA
    2007 vintage had 5.35x the odds of the 2000 vintage.
    """
    cal = json.loads(CALIBRATION.read_text())
    rng = np.random.default_rng(seed)
    z = _risk_logit(df, cal, rng)
    lo, hi = -15.0, 5.0                                   # solve intercept for target rate
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (1 / (1 + np.exp(-(mid + z)))).mean() < target_rate else (lo, mid)
    logit = mid + z + np.log(cycle_odds_ratio)
    out = df.copy()
    out["true_pd"] = 1 / (1 + np.exp(-logit))
    out["defaulted"] = (rng.random(len(df)) < out["true_pd"]).astype(int)
    return out


# --- Data quality problems --------------------------------------------------
DQ_ISSUES = ["missing_abn", "abn_checksum_fail", "balloon_exceeds_loan", "new_asset_too_old",
             "postcode_state_mismatch", "invalid_term", "loan_far_above_asset_value",
             "asset_description_typo", "duplicate_submission"]


def _typo(rng, text: str) -> str:
    word_idx = [i for i, ch in enumerate(text) if ch.isalpha()]
    i = word_idx[rng.integers(len(word_idx))]
    return text[:i] + text[i + 1:] if rng.random() < 0.5 else text[:i] + text[i + 1:i + 2] + text[i] + text[i + 2:]


def inject_dq_issues(df: pd.DataFrame, rate: float = 0.07, seed: int = 11):
    """Corrupt a share of rows the way real broker submissions go wrong.

    Returns (corrupted_df, truth) where truth lists which issue went where,
    so the validator can be tested against a known answer.
    """
    rng = np.random.default_rng(seed)
    out = df.copy()
    out["abn"] = out["abn"].astype(object)
    out["postcode"] = out["postcode"].astype(object)
    idx = rng.choice(out.index, int(len(out) * rate), replace=False)
    issues = rng.choice(DQ_ISSUES, len(idx))
    truth, dupes = [], []
    other_state = {"NSW": "VIC", "VIC": "QLD", "QLD": "NSW", "WA": "SA", "SA": "WA", "TAS": "VIC", "ACT": "NSW", "NT": "QLD"}
    for i, issue in zip(idx, issues):
        r = out.loc[i]
        if issue == "missing_abn":
            out.at[i, "abn"] = None
        elif issue == "abn_checksum_fail":
            a = list(r["abn"]); a[-1] = str((int(a[-1]) + 1) % 10); out.at[i, "abn"] = "".join(a)
        elif issue == "balloon_exceeds_loan":
            out.at[i, "balloon_amount"] = round(r["loan_amount"] * rng.uniform(1.05, 1.5), -2)
        elif issue == "new_asset_too_old":
            out.at[i, "condition"] = "New"
            out.at[i, "asset_year"] = int(r["submitted_date"].year - rng.integers(4, 12))
            out.at[i, "asset_description"] = f"{out.at[i, 'asset_year']} {r['asset_description'].split(' ', 1)[1]}"
        elif issue == "postcode_state_mismatch":
            out.at[i, "postcode"] = _postcode(rng, other_state[r["state"]])
        elif issue == "invalid_term":
            out.at[i, "term_months"] = int(rng.choice([6, 65, 100, 120]))
        elif issue == "loan_far_above_asset_value":
            out.at[i, "loan_amount"] = round(r["asset_price"] * rng.uniform(1.4, 2.0), -2)
        elif issue == "asset_description_typo":
            out.at[i, "asset_description"] = _typo(rng, r["asset_description"])
        elif issue == "duplicate_submission":
            dupes.append(i)
            continue
        truth.append((r["application_id"], issue))
    # A broker resubmits the same deal under a new reference a day later.
    dup_rows = out.loc[dupes].copy()
    dup_rows["submitted_date"] = dup_rows["submitted_date"] + pd.Timedelta(days=1)
    dup_rows["application_id"] = [f"{a}-R" for a in dup_rows["application_id"]]
    truth += [(a, "duplicate_submission") for a in dup_rows["application_id"]]
    out = pd.concat([out, dup_rows]).sort_values("submitted_date", kind="stable").reset_index(drop=True)
    for c in ["lvr", "monthly_repayment"]:  # derived fields are recomputed downstream
        out = out.drop(columns=c, errors="ignore")
    return out, pd.DataFrame(truth, columns=["application_id", "injected_issue"])


# --- Main -------------------------------------------------------------------
def build(n_history: int = 20_000, n_incoming: int = 2_000) -> dict:
    """Write the synthetic datasets to data/synthetic/."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    everything = generate_applications(n_history + n_incoming, seed=42)
    everything = assign_outcomes(everything)
    everything["submitted_date"] = everything["submitted_date"].dt.normalize()

    # Older applications were funded and have known outcomes (the training book).
    # The most recent ones are the live queue: outcomes unknown, and they arrive
    # raw from brokers, so some contain data quality problems.
    history = everything.iloc[:n_history].drop(columns=["true_pd", "lvr", "monthly_repayment"])
    incoming = everything.iloc[n_history:].drop(columns=["defaulted", "true_pd"])
    incoming_raw, truth = inject_dq_issues(incoming)

    history.to_csv(OUT_DIR / "applications_history.csv", index=False)
    incoming_raw.to_csv(OUT_DIR / "applications_incoming_raw.csv", index=False)
    truth.to_csv(OUT_DIR / "incoming_dq_truth.csv", index=False)
    return {"history": history, "incoming_raw": incoming_raw, "truth": truth}


if __name__ == "__main__":
    d = build()
    h = d["history"]
    print(f"history: {len(h):,} rows, default rate {h['defaulted'].mean():.2%}")
    print(f"incoming: {len(d['incoming_raw']):,} rows, {len(d['truth'])} injected issues")
    print(f"written to {OUT_DIR.relative_to(ROOT)}")

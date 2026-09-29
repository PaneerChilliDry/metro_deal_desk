"""Model monitoring: is today's flow of applications still like the data the
model was trained on?

Uses the Population Stability Index (PSI), a standard check in credit risk.
For each feature, compare the share of applications in each bucket now with
the share at training time:

    PSI = sum over buckets of (actual% - expected%) x ln(actual% / expected%)

Common rule of thumb: under 0.10 stable, 0.10 to 0.25 worth watching,
over 0.25 a real shift that should trigger a model review.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = ROOT / "models" / "monitoring_reference.json"

NUMERIC = ["loan_amount", "term_months", "pd"]
CATEGORICAL = ["industry", "asset_category"]
LABELS = {"loan_amount": "Loan amount", "term_months": "Loan term", "pd": "Model score (PD)",
          "industry": "Industry mix", "asset_category": "Asset mix"}
EPS = 1e-4  # avoids log(0) when a bucket is empty


def build_reference(history: pd.DataFrame, reference_pd: np.ndarray) -> dict:
    """Snapshot of the training-time distributions, saved next to the model."""
    ref = {"created_from": f"{len(history):,} training applications", "numeric": {}, "categorical": {}}
    data = history.assign(pd=np.nan)
    for col in NUMERIC:
        values = np.asarray(reference_pd) if col == "pd" else data[col].to_numpy(dtype=float)
        edges = np.unique(np.quantile(values, np.linspace(0, 1, 11)))
        edges[0], edges[-1] = -np.inf, np.inf
        counts = np.histogram(values, bins=edges)[0]
        ref["numeric"][col] = {"edges": [None if np.isinf(e) else float(e) for e in edges],
                               "expected": (counts / counts.sum()).round(6).tolist()}
    for col in CATEGORICAL:
        ref["categorical"][col] = history[col].value_counts(normalize=True).round(6).to_dict()
    return ref


def save_reference(ref: dict) -> None:
    REFERENCE_PATH.parent.mkdir(exist_ok=True)
    REFERENCE_PATH.write_text(json.dumps(ref, indent=2))


def psi(expected, actual) -> float:
    e = np.clip(np.asarray(expected, dtype=float), EPS, None)
    a = np.clip(np.asarray(actual, dtype=float), EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def status(value: float) -> str:
    return "Stable" if value < 0.10 else ("Watch" if value < 0.25 else "Shift")


SIMULATIONS = {
    "construction_boom": "Construction & trades rises to 45% of applications (for example, a building boom or a new broker group)",
    "bigger_loans": "Loan amounts 40% larger across the board (for example, rising vehicle prices)",
    "riskier_mix": "Model scores 30% higher across the board (for example, weaker applicants arriving)",
}


def simulate(current: pd.DataFrame, name: str, seed: int = 0) -> pd.DataFrame:
    """Apply a hypothetical shift to show what the monitor does when things change.
    Used for demonstration only; results are labelled as simulated."""
    rng = np.random.default_rng(seed)
    d = current.copy()
    if name == "construction_boom":
        is_c = d["industry"] == "Construction & trades"
        target = int(0.45 * len(d))
        extra = d[is_c].sample(max(target - int(is_c.sum()), 0), replace=True, random_state=seed)
        keep = d[~is_c].sample(len(d) - target, random_state=seed)
        d = pd.concat([d[is_c], extra, keep]).reset_index(drop=True)
    elif name == "bigger_loans":
        d["loan_amount"] = d["loan_amount"] * 1.4
    elif name == "riskier_mix":
        d["pd"] = np.clip(d["pd"] * 1.3 * rng.uniform(0.9, 1.1, len(d)), 0, 0.99)
    else:
        raise ValueError(f"Unknown simulation '{name}'. Options: {', '.join(SIMULATIONS)}")
    return d


def drift_report(current: pd.DataFrame, ref: dict | None = None) -> dict:
    """PSI for each monitored feature, current applications vs training time."""
    ref = ref or json.loads(REFERENCE_PATH.read_text())
    rows = []
    for col, spec in ref["numeric"].items():
        vals = current[col].dropna().to_numpy(dtype=float)
        if not len(vals):
            continue
        edges = [(-np.inf if e is None and i == 0 else np.inf if e is None else e)
                 for i, e in enumerate(spec["edges"])]
        counts = np.histogram(vals, bins=edges)[0]
        v = psi(spec["expected"], counts / counts.sum())
        rows.append({"feature": col, "label": LABELS[col], "psi": round(v, 4), "status": status(v),
                     "applications": int(len(vals))})
    for col, expected in ref["categorical"].items():
        cats = list(expected)
        actual = current[col].value_counts(normalize=True).reindex(cats, fill_value=0)
        v = psi([expected[c] for c in cats], actual.to_numpy())
        rows.append({"feature": col, "label": LABELS[col], "psi": round(v, 4), "status": status(v),
                     "applications": int(current[col].notna().sum())})
    worst = max(rows, key=lambda r: r["psi"]) if rows else None
    return {"reference": ref["created_from"],
            "overall_status": worst["status"] if worst else "No data",
            "thresholds": {"stable_below": 0.10, "shift_above": 0.25},
            "features": rows}

"""Batch pipeline: score the incoming queue and write files for the dashboard.

Run from the repo root:
    python -m metro_deal_desk.pipeline
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import decision, model, validation

ROOT = Path(__file__).resolve().parents[2]
SYN = ROOT / "data" / "synthetic"
OUT = ROOT / "data" / "scored"


def _read_raw(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"abn": str, "postcode": str})


def score_queue(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (scored, rejection_log). One flat row per application, ready
    to import into a spreadsheet-like tool such as Base44."""
    booster = model.load()
    dups = validation.find_duplicates(raw)
    rows, log = [], []
    for idx, r in raw.iterrows():
        app = r.to_dict()
        res = decision.assess(app, booster=booster)
        if dups.loc[idx]:  # needs the whole batch, so checked here rather than in assess()
            dup_issue = validation.Issue("duplicate_submission", "reject", "application_id",
                                         "This looks like a resubmission of an application received in the last 7 days.")
            res = {**res, "dq_status": "Rejected", "dq_issues": res["dq_issues"] + [dup_issue.to_dict()],
                   "decision": "Returned", "pd": None, "risk_grade": None, "reasons": None, "policy": [],
                   "broker_note": f"{app['application_id']} looks like a resubmission of an application received "
                                  "in the last 7 days, so it has not been assessed again. No action needed if the "
                                  "original is still current."}
        for i in res["dq_issues"]:
            log.append({"application_id": app["application_id"], "submitted_date": app["submitted_date"],
                        "broker_id": app["broker_id"], **i})
        up = (res["reasons"] or {}).get("raises_risk", [])
        down = (res["reasons"] or {}).get("lowers_risk", [])
        rows.append({
            "application_id": app["application_id"], "submitted_date": app["submitted_date"],
            "broker_id": app["broker_id"], "abn": app["abn"], "channel": app["channel"], "state": app["state"],
            "industry": app["industry"], "asset_category": app["asset_category"],
            "asset_description": app["asset_description"], "condition": app["condition"],
            "fuel_type": app["fuel_type"], "asset_price": app["asset_price"], "loan_amount": app["loan_amount"],
            "term_months": app["term_months"], "balloon_amount": app["balloon_amount"],
            "abn_age_months": app["abn_age_months"], "credit_score": app["credit_score"],
            "dq_status": res["dq_status"],
            "dq_messages": " | ".join(i["message"] for i in res["dq_issues"]),
            "decision": res["decision"],
            "pd": res["pd"], "risk_grade": res["risk_grade"],
            "risk_reason_1": up[0]["reason"] if len(up) > 0 else "",
            "risk_reason_2": up[1]["reason"] if len(up) > 1 else "",
            "risk_reason_3": up[2]["reason"] if len(up) > 2 else "",
            "strength_1": down[0]["reason"] if len(down) > 0 else "",
            "strength_2": down[1]["reason"] if len(down) > 1 else "",
            "policy_flags": " | ".join(p["message"] for p in res["policy"]),
            "policy_count": len(res["policy"]),
            "indicative_rate": res["indicative_rate"], "monthly_repayment": res["monthly_repayment"],
            "broker_note": res["broker_note"],
            "reasons_json": json.dumps(res["reasons"]) if res["reasons"] else "",
        })
    return pd.DataFrame(rows), pd.DataFrame(log)


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = _read_raw(SYN / "applications_incoming_raw.csv")
    scored, log = score_queue(raw)
    scored.to_csv(OUT / "scored_queue.csv", index=False)
    log.to_csv(OUT / "rejection_log.csv", index=False)
    return {"scored": scored, "log": log}


if __name__ == "__main__":
    r = run()
    s = r["scored"]
    print(s["decision"].value_counts().to_string())
    print(f"{len(r['log'])} data quality issues logged; files in {OUT.relative_to(ROOT)}")

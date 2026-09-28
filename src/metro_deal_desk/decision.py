"""Triage: combine data quality, model score and policy into one decision,
and write a plain-English note for the broker.

Order of checks:
  1. Data quality: a rejected submission is returned to the broker unscored.
  2. Model: estimated probability of default (PD) and the reasons behind it.
  3. Policy: fixed rules that can refer or decline whatever the score.
  4. Decision: Approve, Refer (to a credit officer) or Decline.

The broker note is built from a template using only the reasons above, so it
never states anything the system did not actually find. An LLM can reword it
for tone (done in the Base44 front end), but not change its content.
"""
from __future__ import annotations

import pandas as pd

from . import model, policy, validation
from .generator import monthly_repayment

APPROVE_BELOW = 0.05   # PD under 5%: eligible for automatic approval
DECLINE_FROM = 0.12    # PD of 12% or more: decline

FEATURE_FIX = {
    "lvr": "A deposit would lower the amount borrowed against the asset.",
    "balloon_pct": "A smaller balloon would lower the risk.",
    "balloon_gap": "A smaller balloon would lower the risk.",
    "term_months": "A shorter term would lower the risk.",
    "asset_age_at_end": "A newer asset or a shorter term would lower the risk.",
    "asset_age_years": "A newer asset would lower the risk.",
    "abn_age_months": "Evidence of trading history (bank statements or BAS) will help the credit review.",
    "credit_score": "An explanation of any adverse items on the director's credit file will help the credit review.",
}


RULE_FEATURES = {
    "trading_history": ("abn_age_months",),
    "credit_score_floor": ("credit_score",),
    "balloon_limit": ("balloon_pct", "balloon_gap"),
    "asset_age_at_end": ("asset_age_at_end", "asset_age_years"),
    "loan_to_value": ("lvr",),
    "auto_decision_limit": ("loan_amount",),
}


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text and not text[:2].isupper() else text


def _prepare(app: dict) -> dict:
    a = dict(app)
    if a.get("asset_age_years") in (None, "") or pd.isna(a.get("asset_age_years")):
        year = pd.to_datetime(a.get("submitted_date"), errors="coerce")
        year = year.year if not pd.isna(year) else pd.Timestamp.today().year
        a["asset_age_years"] = max(0, year - int(float(a["asset_year"])))
    return a


def _money(x) -> str:
    return f"${float(x):,.0f}"


def broker_note(app: dict, decision: str, pd_value: float | None, grade: str | None,
                reasons: dict | None, rules: list, dq_issues: list) -> str:
    ref_ = app.get("application_id", "this application")
    if decision == "Returned":
        rejects = [issue.message for issue in dq_issues if issue.severity == "reject"]
        fixes = " ".join(f"({n}) {msg}" for n, msg in enumerate(rejects, start=1))
        what = "a correction" if len(rejects) == 1 else "some corrections"
        return (f"{ref_} needs {what} before it can be assessed: {fixes} "
                "Please update and resubmit; nothing has been assessed yet.")

    # Skip model reasons that repeat a policy breach (same underlying fact).
    covered = {f for r in rules for f in RULE_FEATURES.get(r.rule, ())}
    ups = [r for r in reasons["raises_risk"] if r["feature"] not in covered]
    downs = [_lower_first(r["reason"]) for r in reasons["lowers_risk"] if r["feature"] not in covered]
    deal = f"{_money(app['loan_amount'])} over {int(float(app['term_months']))} months"

    if decision == "Approve":
        strengths = "; ".join(downs[:3]) if downs else "the overall profile"
        return (f"Good news: {ref_} ({deal}) is approved subject to standard settlement documents. "
                f"Risk grade {grade}. Main strengths: {strengths}.")

    fixes = [r.fix for r in rules]
    fixes += [FEATURE_FIX[r["feature"]] for r in ups if r["feature"] in FEATURE_FIX]
    if decision == "Decline":
        fixes = [f for f in fixes if not f.startswith("No change needed")]
    fixes = list(dict.fromkeys(fixes))  # de-duplicate, keep order
    concerns = [r.message for r in rules] + [r["reason"] for r in ups]
    concern_text = " ".join(f"({i + 1}) {c.rstrip('.')}." for i, c in enumerate(concerns[:4]))
    fix_text = (" What could help: " + " ".join(fixes[:3])) if fixes else ""
    positives = f" In its favour: {'; '.join(downs[:2])}." if downs else ""

    if decision == "Refer":
        return (f"{ref_} ({deal}) has been referred to a credit officer, risk grade {grade}. "
                f"Points they will look at: {concern_text}{positives}{fix_text}")
    return (f"We can't approve {ref_} ({deal}) as submitted, risk grade {grade}. "
            f"Main reasons: {concern_text}{positives}{fix_text}")


def assess(app: dict, booster=None) -> dict:
    """Full triage for one application."""
    dq = validation.validate(app)
    base = {"application_id": app.get("application_id"), "dq_status": validation.status(dq),
            "dq_issues": [i.to_dict() for i in dq]}
    if base["dq_status"] == "Rejected":
        return {**base, "decision": "Returned", "pd": None, "risk_grade": None,
                "reasons": None, "policy": [], "indicative_rate": None, "monthly_repayment": None,
                "broker_note": broker_note(app, "Returned", None, None, None, [], dq)}

    a = _prepare(app)
    frame = pd.DataFrame([a])
    p = float(model.predict_pd(frame, booster)[0])
    reasons = model.explain(frame, booster=booster)[0]
    rules = policy.check_policy(a)
    grade = model.risk_grade(p)

    if any(r.outcome == "decline" for r in rules) or p >= DECLINE_FROM:
        decision = "Decline"
    elif rules or p >= APPROVE_BELOW:
        decision = "Refer"
    else:
        decision = "Approve"

    rate = a.get("interest_rate")
    repay = None
    if rate not in (None, "") and not pd.isna(rate):
        repay = round(float(monthly_repayment(float(a["loan_amount"]), float(rate),
                                              float(a["term_months"]), float(a["balloon_amount"]))), 2)
    return {**base, "decision": decision, "pd": round(p, 4), "risk_grade": grade, "reasons": reasons,
            "policy": [r.to_dict() for r in rules],
            "indicative_rate": None if repay is None else float(rate), "monthly_repayment": repay,
            "broker_note": broker_note(a, decision, p, grade, reasons, rules, dq)}

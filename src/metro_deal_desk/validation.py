"""Data quality rules for broker submissions.

Each rule looks at one application and returns an Issue if something is wrong.
Severity decides what happens next:
  reject  - the application is returned to the broker to fix; it is not scored
  warn    - the application is scored, but the issue is shown to credit staff

Rules are plain functions so they are easy to read, test and extend.
"""
from __future__ import annotations

import difflib
import math
from dataclasses import asdict, dataclass

import pandas as pd

from . import reference as ref
from .generator import abn_is_valid

VALID_TERMS = {12, 24, 36, 48, 60, 72, 84}
REQUIRED = ["abn", "state", "postcode", "industry", "asset_category", "condition", "asset_year",
            "asset_description", "asset_price", "loan_amount", "term_months", "balloon_amount",
            "abn_age_months", "credit_score"]
KNOWN_MODELS = sorted({m for a in ref.ASSETS.values() for m, _ in a["models"]})


@dataclass
class Issue:
    rule: str
    severity: str  # "reject" or "warn"
    field: str
    message: str

    def to_dict(self):
        return asdict(self)


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _abn(v) -> str:
    if _missing(v):
        return ""
    s = str(v).replace(" ", "")
    return s[:-2] if s.endswith(".0") else s  # CSV readers can turn ABNs into floats


def _postcode_in_state(postcode, state) -> bool:
    try:
        pc = int(str(postcode).split(".")[0])
    except ValueError:
        return False
    return any(lo <= pc <= hi for lo, hi in ref.POSTCODE_RANGES.get(state, []))


# --- Rules ------------------------------------------------------------------
def check_required(app):
    return [Issue("required_field", "reject", f, f"{f} is missing.") for f in REQUIRED if _missing(app.get(f))
            and f != "abn"]


def check_abn(app):
    abn = _abn(app.get("abn"))
    if not abn:
        return [Issue("missing_abn", "reject", "abn", "ABN is missing. An ABN is required for commercial finance.")]
    if not abn_is_valid(abn):
        return [Issue("abn_checksum_fail", "reject", "abn",
                      f"ABN {abn} is not a valid ABN (fails the ATO checksum). Please check for a typo.")]
    return []


def check_postcode(app):
    state, pc = app.get("state"), app.get("postcode")
    if _missing(state) or _missing(pc):
        return []
    if state not in ref.POSTCODE_RANGES:
        return [Issue("unknown_state", "reject", "state", f"State '{state}' is not an Australian state or territory.")]
    if not _postcode_in_state(pc, state):
        pc_str = f"{int(float(pc)):04d}" if _num(pc) is not None else str(pc)
        return [Issue("postcode_state_mismatch", "reject", "postcode",
                      f"Postcode {pc_str} is not in {state}. Please check the address.")]
    return []


def check_term(app):
    t = _num(app.get("term_months"))
    if t is not None and t not in VALID_TERMS:
        return [Issue("invalid_term", "reject", "term_months",
                      f"Term of {t:.0f} months is not offered. Terms run from 12 to 84 months in 12-month steps.")]
    return []


def check_balloon(app):
    b, loan = _num(app.get("balloon_amount")), _num(app.get("loan_amount"))
    if b is not None and loan and b >= loan:
        return [Issue("balloon_exceeds_loan", "reject", "balloon_amount",
                      f"Balloon (${b:,.0f}) is not less than the loan amount (${loan:,.0f}).")]
    if b is not None and b < 0:
        return [Issue("negative_balloon", "reject", "balloon_amount", "Balloon cannot be negative.")]
    return []


def check_loan_vs_asset(app):
    loan, price = _num(app.get("loan_amount")), _num(app.get("asset_price"))
    if loan is not None and loan <= 0:
        return [Issue("non_positive_loan", "reject", "loan_amount", "Loan amount must be greater than zero.")]
    if loan and price and loan > 1.3 * price:
        return [Issue("loan_far_above_asset_value", "reject", "loan_amount",
                      f"Loan (${loan:,.0f}) is {loan / price:.0%} of the asset price (${price:,.0f}). "
                      "Check the amounts; more than 130% cannot be secured by the asset.")]
    return []


def check_new_asset_year(app):
    year = _num(app.get("asset_year"))
    submitted = pd.to_datetime(app.get("submitted_date"), errors="coerce")
    ref_year = submitted.year if not pd.isna(submitted) else pd.Timestamp.today().year
    if app.get("condition") == "New" and year is not None and year < ref_year - 1:
        return [Issue("new_asset_too_old", "reject", "condition",
                      f"Asset is marked New but the year is {year:.0f}. Should it be Used?")]
    if year is not None and year > ref_year + 1:
        return [Issue("asset_year_in_future", "reject", "asset_year", f"Asset year {year:.0f} is in the future.")]
    return []


def check_asset_description(app):
    desc = app.get("asset_description")
    if _missing(desc):
        return []
    model = str(desc).split(" ", 1)[1] if str(desc)[:4].isdigit() and " " in str(desc) else str(desc)
    if model in KNOWN_MODELS:
        return []
    close = difflib.get_close_matches(model, KNOWN_MODELS, n=1, cutoff=0.8)
    hint = f" Did you mean '{close[0]}'?" if close else ""
    return [Issue("unrecognised_asset", "warn", "asset_description",
                  f"Asset '{model}' is not in the asset catalogue.{hint}")]


RULES = [check_required, check_abn, check_postcode, check_term, check_balloon,
         check_loan_vs_asset, check_new_asset_year, check_asset_description]


def validate(app: dict) -> list[Issue]:
    """Run every rule on one application."""
    issues: list[Issue] = []
    for rule in RULES:
        issues += rule(app)
    return issues


def status(issues: list[Issue]) -> str:
    if any(i.severity == "reject" for i in issues):
        return "Rejected"
    return "Warning" if issues else "Pass"


# --- Batch ------------------------------------------------------------------
def find_duplicates(df: pd.DataFrame, window_days: int = 7) -> pd.Series:
    """Flag a submission that repeats an earlier one (same ABN, asset and
    amount) within the window. The first submission is kept as the original."""
    d = df.copy()
    d["_abn"] = d["abn"].map(_abn)
    d["_date"] = pd.to_datetime(d["submitted_date"])
    d = d.sort_values("_date", kind="stable")
    key = ["_abn", "asset_description", "loan_amount"]
    prev = d.groupby(key, dropna=False)["_date"].shift()
    dup = prev.notna() & ((d["_date"] - prev).dt.days <= window_days)
    return dup.reindex(df.index).fillna(False)


def validate_batch(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a DataFrame of submissions. Returns one row per application
    with dq_status, dq_issue_count and a readable list of issues."""
    dups = find_duplicates(df)
    rows = []
    for idx, app in df.iterrows():
        issues = validate(app.to_dict())
        if dups.loc[idx]:
            issues.append(Issue("duplicate_submission", "reject", "application_id",
                                "This looks like a resubmission of an application already received in the last 7 days."))
        rows.append({"application_id": app["application_id"], "dq_status": status(issues),
                     "dq_issue_count": len(issues), "dq_rules": ";".join(i.rule for i in issues),
                     "dq_messages": " | ".join(i.message for i in issues)})
    return pd.DataFrame(rows, index=df.index)

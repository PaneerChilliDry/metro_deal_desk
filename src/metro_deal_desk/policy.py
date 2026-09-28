"""Credit policy rules.

Lenders never let a model decide alone. These fixed rules run alongside the
risk score and can refer or decline a deal whatever the score says. The
limits are illustrative, chosen to be typical of asset finance; they are not
any real lender's policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

BALLOON_LIMIT = {"Car / SUV": 0.35, "Ute / van": 0.35, "Truck": 0.25,
                 "Earthmoving equipment": 0.15, "Agricultural machinery": 0.15,
                 "Trailer": 0.10, "Other equipment": 0.10}
MIN_TRADING_MONTHS = 24
MAX_ASSET_AGE_AT_END = 15
MAX_LVR = 1.10
MIN_CREDIT_SCORE = 500
AUTO_DECISION_LIMIT = 250_000


@dataclass
class PolicyResult:
    rule: str
    outcome: str      # "refer" or "decline"
    message: str      # what is wrong
    fix: str          # what the broker could change

    def to_dict(self):
        return asdict(self)


def check_policy(app: dict) -> list[PolicyResult]:
    out: list[PolicyResult] = []
    price, loan = float(app["asset_price"]), float(app["loan_amount"])
    balloon, term = float(app["balloon_amount"]), float(app["term_months"])
    cat = app["asset_category"]
    age_now = float(app.get("asset_age_years", 0) or 0)

    limit = BALLOON_LIMIT.get(cat, 0.10)
    if balloon / price > limit:
        out.append(PolicyResult(
            "balloon_limit", "refer",
            f"Balloon is {balloon / price:.0%} of the asset price; the limit for {cat.lower()} is {limit:.0%}.",
            f"Reduce the balloon to ${limit * price:,.0f} or less."))

    if float(app["abn_age_months"]) < MIN_TRADING_MONTHS:
        out.append(PolicyResult(
            "trading_history", "refer",
            f"Business has traded for {float(app['abn_age_months']):.0f} months; "
            f"{MIN_TRADING_MONTHS} months is required for automatic approval.",
            "Provide 6 months of business bank statements or an accountant's letter for credit review."))

    age_end = age_now + term / 12
    if age_end > MAX_ASSET_AGE_AT_END:
        shorter = max(12, int((MAX_ASSET_AGE_AT_END - age_now) * 12) // 12 * 12)
        out.append(PolicyResult(
            "asset_age_at_end", "refer",
            f"Asset would be {age_end:.0f} years old at the end of the term (limit {MAX_ASSET_AGE_AT_END}).",
            f"Shorten the term to {shorter} months or finance a newer asset."))

    if loan / price > MAX_LVR:
        out.append(PolicyResult(
            "loan_to_value", "refer",
            f"Loan is {loan / price:.0%} of the asset price (limit {MAX_LVR:.0%}).",
            f"A deposit of ${loan - MAX_LVR * price:,.0f} would bring it within limit."))

    if float(app["credit_score"]) < MIN_CREDIT_SCORE:
        out.append(PolicyResult(
            "credit_score_floor", "decline",
            f"Director credit score of {float(app['credit_score']):.0f} is below the minimum of {MIN_CREDIT_SCORE}.",
            "A guarantor with a stronger credit history may allow the deal to be reconsidered."))

    if loan > AUTO_DECISION_LIMIT:
        out.append(PolicyResult(
            "auto_decision_limit", "refer",
            f"Loan of ${loan:,.0f} is above the ${AUTO_DECISION_LIMIT:,.0f} automatic decision limit.",
            "No change needed; a senior credit officer will review it."))
    return out


# Documented for the README and dashboard.
POLICY_SUMMARY = [
    ("Balloon limit", "refer", "Balloon above 35% (cars, utes), 25% (trucks), 15% (earthmoving, agricultural) or 10% (other)"),
    ("Trading history", "refer", f"ABN registered under {MIN_TRADING_MONTHS} months"),
    ("Asset age at end of term", "refer", f"Asset older than {MAX_ASSET_AGE_AT_END} years when the loan ends"),
    ("Loan to value", "refer", f"Loan above {MAX_LVR:.0%} of the asset price"),
    ("Credit score floor", "decline", f"Director credit score below {MIN_CREDIT_SCORE}"),
    ("Automatic decision limit", "refer", f"Loan above ${AUTO_DECISION_LIMIT:,}"),
]

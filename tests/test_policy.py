from metro_deal_desk import policy


def outcomes(app):
    return {r.rule: r.outcome for r in policy.check_policy({**app, "asset_age_years": 2026 - app["asset_year"]})}


def test_clean_application_has_no_breaches(good_app):
    assert outcomes(good_app) == {}


def test_balloon_limit_refers_and_suggests_amount(good_app):
    res = policy.check_policy({**good_app, "balloon_amount": 25000, "asset_age_years": 0})
    b = next(r for r in res if r.rule == "balloon_limit")
    assert b.outcome == "refer"
    assert "$19,250" in b.fix  # 35% of $55,000


def test_new_business_is_referred(good_app):
    assert outcomes({**good_app, "abn_age_months": 10})["trading_history"] == "refer"


def test_low_credit_score_declines(good_app):
    assert outcomes({**good_app, "credit_score": 450})["credit_score_floor"] == "decline"


def test_old_asset_at_end_of_term(good_app):
    app = {**good_app, "condition": "Used", "asset_year": 2014, "term_months": 60}
    assert outcomes(app)["asset_age_at_end"] == "refer"


def test_large_loan_goes_to_senior_credit(good_app):
    app = {**good_app, "asset_price": 320000, "loan_amount": 300000, "balloon_amount": 0}
    assert outcomes(app)["auto_decision_limit"] == "refer"

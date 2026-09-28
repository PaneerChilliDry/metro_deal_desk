"""Behaviour tests: the model must respect basic credit logic."""
import numpy as np
import pandas as pd
import pytest

from metro_deal_desk import model


def pd_for(app, **changes):
    return float(model.predict_pd(pd.DataFrame([{**app, **changes}]))[0])


def test_probability_in_range(good_app):
    p = pd_for(good_app)
    assert 0 < p < 1


@pytest.mark.parametrize("industry", ["Construction & trades", "Retail trade", "Health care", "Hospitality"])
def test_better_credit_score_never_raises_risk(good_app, industry):
    scores = range(300, 1201, 50)
    pds = [pd_for(good_app, credit_score=s, industry=industry) for s in scores]
    assert all(b <= a + 1e-12 for a, b in zip(pds, pds[1:]))


def test_longer_trading_history_never_raises_risk(good_app):
    pds = [pd_for(good_app, abn_age_months=m) for m in [3, 6, 12, 24, 48, 96, 240]]
    assert all(b <= a + 1e-12 for a, b in zip(pds, pds[1:]))


def test_higher_loan_to_value_never_lowers_risk(good_app):
    # Hold the loan amount fixed (loan size is its own feature) and vary the
    # asset price instead, with no balloon so nothing else moves.
    loan = good_app["loan_amount"]
    pds = [pd_for(good_app, balloon_amount=0, asset_price=loan / r) for r in [0.6, 0.8, 1.0, 1.1, 1.2]]
    assert all(b >= a - 1e-12 for a, b in zip(pds, pds[1:]))


def test_explanations_add_up_to_the_prediction(good_app):
    """SHAP values plus the baseline must reproduce the model's log-odds exactly."""
    X = model.build_features(pd.DataFrame([good_app]))
    contrib = model.load().predict(X, pred_contrib=True)[0]
    p = model.load().predict(X)[0]
    assert np.isclose(contrib.sum(), np.log(p / (1 - p)), atol=1e-6)


def test_risk_grades():
    assert [model.risk_grade(p) for p in [0.01, 0.03, 0.05, 0.10, 0.30]] == ["A", "B", "C", "D", "E"]

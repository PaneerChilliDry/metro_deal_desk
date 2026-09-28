from metro_deal_desk import decision


def test_clean_low_risk_application_is_approved(good_app):
    r = decision.assess(good_app)
    assert r["decision"] == "Approve"
    assert r["pd"] < decision.APPROVE_BELOW
    assert r["broker_note"].startswith("Good news")
    assert r["monthly_repayment"] > 0


def test_bad_data_is_returned_unscored(good_app):
    r = decision.assess({**good_app, "abn": None})
    assert r["decision"] == "Returned"
    assert r["pd"] is None
    assert "ABN is missing" in r["broker_note"]


def test_policy_referral_overrides_a_good_score(good_app):
    r = decision.assess({**good_app, "abn_age_months": 10})
    assert r["decision"] == "Refer"
    assert any(p["rule"] == "trading_history" for p in r["policy"])


def test_policy_decline(good_app):
    r = decision.assess({**good_app, "credit_score": 420})
    assert r["decision"] == "Decline"
    assert "below the minimum" in r["broker_note"]


def test_note_only_mentions_real_reasons(good_app):
    r = decision.assess({**good_app, "balloon_amount": 25000})
    assert r["decision"] == "Refer"
    assert "Reduce the balloon to $19,250" in r["broker_note"]
    for reason in r["reasons"]["raises_risk"]:
        if reason["feature"] not in ("balloon_pct", "balloon_gap"):
            assert reason["reason"] in r["broker_note"]


def test_note_has_no_em_dashes(good_app):
    for change in [{}, {"abn": None}, {"abn_age_months": 10}, {"credit_score": 420}]:
        assert "—" not in decision.assess({**good_app, **change})["broker_note"]

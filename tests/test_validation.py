import pandas as pd
import pytest

from metro_deal_desk import validation
from metro_deal_desk.generator import abn_is_valid


def rules(app):
    return {i.rule for i in validation.validate(app)}


def test_clean_application_passes(good_app):
    assert validation.validate(good_app) == []


def test_abn_checksum():
    assert abn_is_valid("25892415116")
    assert not abn_is_valid("25892415117")
    assert not abn_is_valid("123")
    assert not abn_is_valid(None)


@pytest.mark.parametrize("change, expected_rule", [
    ({"abn": None}, "missing_abn"),
    ({"abn": "25892415117"}, "abn_checksum_fail"),
    ({"postcode": "3000"}, "postcode_state_mismatch"),        # Melbourne postcode, NSW state
    ({"state": "XYZ"}, "unknown_state"),
    ({"term_months": 65}, "invalid_term"),
    ({"balloon_amount": 60000}, "balloon_exceeds_loan"),
    ({"loan_amount": 90000}, "loan_far_above_asset_value"),
    ({"loan_amount": 0}, "non_positive_loan"),
    ({"asset_year": 2015}, "new_asset_too_old"),             # marked New
    ({"asset_year": 2030}, "asset_year_in_future"),
    ({"credit_score": None}, "required_field"),
])
def test_each_rule_rejects(good_app, change, expected_rule):
    issues = validation.validate({**good_app, **change})
    assert expected_rule in {i.rule for i in issues}
    assert validation.status(issues) == "Rejected"


def test_typo_is_a_warning_with_suggestion(good_app):
    issues = validation.validate({**good_app, "asset_description": "2026 Toyta RAV4 Hybrid"})
    assert [i.rule for i in issues] == ["unrecognised_asset"]
    assert validation.status(issues) == "Warning"
    assert "Toyota RAV4 Hybrid" in issues[0].message


def test_abn_read_as_float_from_csv_is_handled(good_app):
    assert "abn_checksum_fail" not in rules({**good_app, "abn": 25892415116.0})


def test_duplicate_within_window_is_flagged_but_original_is_not(good_app):
    later = {**good_app, "application_id": "TEST-002", "submitted_date": "2026-09-03"}
    much_later = {**good_app, "application_id": "TEST-003", "submitted_date": "2026-10-20"}
    dups = validation.find_duplicates(pd.DataFrame([good_app, later, much_later]))
    assert dups.tolist() == [False, True, False]


def test_validator_matches_answer_key():
    """Every problem injected by the generator is caught, and clean rows are not flagged."""
    from metro_deal_desk.generator import ROOT
    raw = pd.read_csv(ROOT / "data/synthetic/applications_incoming_raw.csv", dtype={"abn": str, "postcode": str})
    truth = pd.read_csv(ROOT / "data/synthetic/incoming_dq_truth.csv")
    v = validation.validate_batch(raw).assign(application_id=raw["application_id"])
    flagged = set(v.loc[v["dq_status"] != "Pass", "application_id"])
    assert flagged == set(truth["application_id"])

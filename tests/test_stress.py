import numpy as np
import pandas as pd
import pytest

from metro_deal_desk import stress


@pytest.fixture
def book():
    return pd.DataFrame({
        "industry": ["Construction & trades", "Agriculture", "Health care", "Retail trade"],
        "asset_category": ["Ute / van", "Agricultural machinery", "Car / SUV", "Other equipment"],
        "loan_amount": [60000, 150000, 45000, 30000],
        "pd": [0.03, 0.02, 0.01, 0.045],
    })


def test_baseline_scenario_changes_nothing(book):
    r = stress.run(book, "baseline")
    assert r["stressed"]["expected_loss"] == pytest.approx(r["baseline"]["expected_loss"])


def test_scenarios_are_ordered_by_severity(book):
    losses = [stress.run(book, s)["stressed"]["expected_loss"] for s in ["benign", "baseline", "mild", "severe", "gfc"]]
    assert losses == sorted(losses)


def test_stress_raises_every_loans_pd(book):
    p = stress.stressed_pd(book["pd"], book["industry"], 2.8)
    assert np.all(p > book["pd"].to_numpy())


def test_more_cyclical_industries_are_hit_harder():
    base = [0.03, 0.03]
    agri, construction = stress.stressed_pd(base, ["Agriculture", "Construction & trades"], 2.8)
    assert construction > agri


def test_lgd_rises_in_downturn():
    assert stress.lgd(["Truck"], 2.8)[0] > stress.lgd(["Truck"], 1.0)[0]
    assert stress.lgd(["Truck"], 1.0)[0] == pytest.approx(0.40)


def test_scenarios_come_from_real_vintages():
    s = {x["key"]: x for x in stress.scenarios()}
    assert s["baseline"]["odds_multiplier"] == 1.0
    assert s["gfc"]["based_on_vintages"] == [2007]
    assert s["gfc"]["odds_multiplier"] > 2


def test_unknown_scenario(book):
    with pytest.raises(ValueError):
        stress.run(book, "apocalypse")

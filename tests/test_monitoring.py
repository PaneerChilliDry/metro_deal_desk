import pandas as pd
import pytest

from metro_deal_desk import monitoring


@pytest.fixture(scope="module")
def queue():
    from metro_deal_desk.generator import ROOT
    return pd.read_csv(ROOT / "data/scored/scored_queue.csv")


def test_psi_is_zero_for_identical_distributions():
    assert monitoring.psi([0.2, 0.3, 0.5], [0.2, 0.3, 0.5]) == pytest.approx(0)


def test_psi_grows_with_the_shift():
    small = monitoring.psi([0.5, 0.5], [0.55, 0.45])
    large = monitoring.psi([0.5, 0.5], [0.8, 0.2])
    assert 0 < small < large


def test_status_thresholds():
    assert [monitoring.status(v) for v in [0.05, 0.15, 0.4]] == ["Stable", "Watch", "Shift"]


def test_live_queue_is_stable(queue):
    assert monitoring.drift_report(queue)["overall_status"] == "Stable"


@pytest.mark.parametrize("sim, feature", [("construction_boom", "industry"),
                                           ("bigger_loans", "loan_amount"),
                                           ("riskier_mix", "pd")])
def test_monitor_catches_simulated_shifts(queue, sim, feature):
    report = monitoring.drift_report(monitoring.simulate(queue, sim))
    flagged = {f["feature"] for f in report["features"] if f["status"] != "Stable"}
    assert feature in flagged

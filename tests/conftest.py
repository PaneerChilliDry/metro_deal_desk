import pytest

from metro_deal_desk.generator import abn_is_valid

# A synthetic ABN (random number that passes the checksum) used across tests.
GOOD_ABN = "25892415116"
assert abn_is_valid(GOOD_ABN)


@pytest.fixture
def good_app():
    """A clean, low-risk application that should be approved."""
    return {
        "application_id": "TEST-001", "submitted_date": "2026-09-01", "broker_id": "BRK-TEST",
        "channel": "Broker", "abn": GOOD_ABN, "entity_type": "Company", "abn_age_months": 96,
        "industry": "Health care", "state": "NSW", "postcode": "2541", "credit_score": 850,
        "asset_category": "Car / SUV", "asset_description": "2026 Toyota RAV4 Hybrid", "fuel_type": "Hybrid",
        "condition": "New", "asset_year": 2026, "asset_price": 55000, "loan_amount": 50000,
        "term_months": 48, "balloon_amount": 10000, "interest_rate": 0.079,
    }


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """API client backed by a fresh, seeded database in a temp folder."""
    from fastapi.testclient import TestClient
    from metro_deal_desk import api, db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(api.app) as client:
        yield client

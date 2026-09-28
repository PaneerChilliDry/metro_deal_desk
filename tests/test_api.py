def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_submit_and_fetch(api_client, good_app):
    r = api_client.post("/applications", json=good_app)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "Approve"
    fetched = api_client.get(f"/applications/{good_app['application_id']}").json()
    assert fetched["decision"] == "Approve"
    assert fetched["result"]["broker_note"] == body["broker_note"]


def test_id_is_generated_when_missing(api_client, good_app):
    app = {k: v for k, v in good_app.items() if k != "application_id"}
    assert api_client.post("/applications", json=app).json()["application_id"].startswith("API-")


def test_same_id_twice_is_a_conflict(api_client, good_app):
    api_client.post("/applications", json=good_app)
    assert api_client.post("/applications", json=good_app).status_code == 409


def test_resubmission_is_returned_as_duplicate(api_client, good_app):
    api_client.post("/applications", json=good_app)
    again = {**good_app, "application_id": "TEST-RESUBMIT"}
    r = api_client.post("/applications", json=again).json()
    assert r["decision"] == "Returned"
    assert r["dq_issues"][0]["rule"] == "duplicate_submission"


def test_bad_business_data_returns_200_with_messages(api_client, good_app):
    r = api_client.post("/applications", json={**good_app, "postcode": "3000"})
    assert r.status_code == 200
    assert r.json()["decision"] == "Returned"


def test_wrong_types_are_rejected_by_schema(api_client, good_app):
    assert api_client.post("/applications", json={**good_app, "industry": "Space tourism"}).status_code == 422
    assert api_client.post("/applications", json={**good_app, "credit_score": "high"}).status_code == 422


def test_list_filter(api_client):
    rows = api_client.get("/applications", params={"decision": "Decline", "limit": 5}).json()
    assert 0 < len(rows) <= 5 and all(r["decision"] == "Decline" for r in rows)


def test_missing_application_404(api_client):
    assert api_client.get("/applications/NOPE").status_code == 404


def test_quote(api_client):
    r = api_client.post("/quote", json={"loan_amount": 60000, "interest_rate": 0.089,
                                        "term_months": 60, "balloon_amount": 15000}).json()
    assert abs(r["monthly_repayment"] - 1043.19) < 0.01
    bad = api_client.post("/quote", json={"loan_amount": 60000, "interest_rate": 0.089,
                                          "term_months": 60, "balloon_amount": 70000})
    assert bad.status_code == 422


def test_portfolio_summary(api_client):
    s = api_client.get("/portfolio/summary").json()
    assert set(s) == {"decision_mix", "by_industry", "broker_scorecard", "dq_by_rule", "weekly_volume"}
    assert sum(r["applications"] for r in s["decision_mix"]) >= 2000


def test_reference_endpoints(api_client):
    assert len(api_client.get("/policy").json()) >= 6
    assert "test_auc" in api_client.get("/model").json()
    assert "Ute / van" in api_client.get("/reference/options").json()["asset_category"]

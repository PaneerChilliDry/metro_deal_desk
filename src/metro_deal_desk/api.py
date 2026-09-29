"""Metro Deal Desk REST API.

Run locally from the repo root:
    uvicorn metro_deal_desk.api:app --reload
then open http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import db, decision, model, monitoring, policy, stress
from . import reference as ref
from .generator import monthly_repayment

Industry = Literal[tuple(sorted(ref.INDUSTRY_WEIGHTS))]
AssetCategory = Literal[tuple(sorted(ref.ASSETS))]


class ApplicationIn(BaseModel):
    """What a broker or dealer submits. Field names mirror Metro's public enquiry
    form, plus the details a commercial credit assessment needs.

    Types are checked here (wrong types get a 422). Business rules, such as a
    valid ABN or a postcode that matches the state, are checked by the data
    quality layer and come back as a 'Returned' decision with clear messages.
    """
    application_id: Optional[str] = Field(None, description="Leave blank to have one generated")
    submitted_date: Optional[date] = Field(None, description="Defaults to today")
    broker_id: str = Field("BRK-DEMO", examples=["BRK-012"])
    channel: Literal["Broker", "Dealer"] = "Broker"
    abn: Optional[str] = Field(None, description="11-digit Australian Business Number", examples=["25892415116"])
    entity_type: Literal["Company", "Sole trader", "Trust", "Partnership"] = "Company"
    abn_age_months: int = Field(..., ge=0, le=1200, description="Months since ABN registration", examples=[36])
    industry: Industry = Field(..., examples=["Construction & trades"])
    state: str = Field(..., examples=["NSW"])
    postcode: str = Field(..., examples=["2541"])
    credit_score: int = Field(..., ge=0, le=1200, description="Director's credit score (0 to 1200)", examples=[720])
    asset_category: AssetCategory = Field(..., examples=["Ute / van"])
    asset_description: str = Field(..., examples=["2025 Toyota HiLux SR5"])
    fuel_type: Optional[str] = Field(None, examples=["Diesel"])
    condition: Literal["New", "Used"] = Field(..., examples=["Used"])
    asset_year: int = Field(..., ge=1950, le=2100, examples=[2025])
    asset_price: float = Field(..., gt=0, examples=[62000])
    loan_amount: float = Field(..., examples=[60000])
    term_months: int = Field(..., ge=1, examples=[60])
    balloon_amount: float = Field(0, examples=[15000])
    interest_rate: Optional[float] = Field(None, ge=0, le=0.5, description="Indicative annual rate, e.g. 0.089",
                                           examples=[0.089])


class QuoteIn(BaseModel):
    loan_amount: float = Field(..., gt=0, examples=[60000])
    interest_rate: float = Field(..., gt=0, le=0.5, examples=[0.089])
    term_months: int = Field(..., ge=12, le=84, examples=[60])
    balloon_amount: float = Field(0, ge=0, examples=[15000])


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    model.load()
    yield


app = FastAPI(
    title="Metro Deal Desk API",
    version="0.1.0",
    description=("Triage for vehicle and equipment finance applications: data quality checks, an explainable "
                 "credit risk score, policy rules and a plain-English note for the broker.\n\n"
                 "**All data is synthetic.** This is a portfolio project, not Metro Finance software."),
    lifespan=lifespan,
)
# Open CORS so a browser front end (Base44) can call the API. A real service
# would restrict this to known origins and add authentication.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health", tags=["Service"])
def health():
    card = json.loads(model.CARD_PATH.read_text())
    return {"status": "ok", "model_test_auc": card["test_auc"]}


@app.post("/applications", tags=["Applications"])
def submit_application(app_in: ApplicationIn):
    """Assess an application and store the result."""
    a = app_in.model_dump()
    a["application_id"] = a["application_id"] or f"API-{uuid.uuid4().hex[:8].upper()}"
    a["submitted_date"] = str(a["submitted_date"] or date.today())
    if db.get(a["application_id"]):
        raise HTTPException(409, f"Application {a['application_id']} already exists.")

    original = db.find_recent_duplicate(a["abn"], a["asset_description"], a["loan_amount"], a["submitted_date"])
    if original:
        result = {"application_id": a["application_id"], "dq_status": "Rejected",
                  "dq_issues": [{"rule": "duplicate_submission", "severity": "reject", "field": "application_id",
                                 "message": f"Matches {original}, submitted in the last 7 days."}],
                  "decision": "Returned", "pd": None, "risk_grade": None, "reasons": None, "policy": [],
                  "indicative_rate": None, "monthly_repayment": None,
                  "broker_note": f"This looks like a resubmission of {original}, so it has not been assessed "
                                 "again. No action is needed if the original is still current."}
    else:
        result = decision.assess(a)
    db.save(a, result)
    return result


@app.get("/applications", tags=["Applications"])
def list_applications(decision_filter: Optional[Literal["Approve", "Refer", "Decline", "Returned"]] = Query(None, alias="decision"),
                      limit: int = Query(50, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """Most recent applications first, optionally filtered by decision."""
    return db.list_applications(decision_filter, limit, offset)


@app.get("/applications/{application_id}", tags=["Applications"])
def get_application(application_id: str):
    row = db.get(application_id)
    if not row:
        raise HTTPException(404, f"Application {application_id} not found.")
    return row


@app.post("/quote", tags=["Tools"])
def quote(q: QuoteIn):
    """Monthly repayment for a loan with an optional balloon, as a dealer quote tool would show."""
    if q.balloon_amount >= q.loan_amount:
        raise HTTPException(422, "Balloon must be less than the loan amount.")
    m = float(monthly_repayment(q.loan_amount, q.interest_rate, q.term_months, q.balloon_amount))
    return {"monthly_repayment": round(m, 2),
            "total_repayments": round(m * q.term_months + q.balloon_amount, 2),
            "total_interest": round(m * q.term_months + q.balloon_amount - q.loan_amount, 2)}


@app.get("/portfolio/summary", tags=["Portfolio"])
def portfolio_summary():
    """Decision mix, risk by industry, broker scorecard, data quality by rule and weekly volume (SQL in sql/portfolio.sql)."""
    return db.portfolio_summary()


@app.get("/stress/scenarios", tags=["Risk"])
def stress_scenarios():
    """Downturn scenarios, each tied to a real SBA loan vintage."""
    return stress.scenarios()


@app.get("/stress", tags=["Risk"])
def stress_test(scenario: Literal["benign", "baseline", "mild", "severe", "gfc"] = "gfc",
                multiplier: Optional[float] = Query(None, gt=0, le=10, description="Custom odds multiplier; overrides scenario"),
                book: Literal["approved", "all_scored"] = "approved"):
    """Expected losses and decision changes for the book under a downturn scenario."""
    decisions = ("Approve",) if book == "approved" else ("Approve", "Refer", "Decline")
    return {"book": book, **stress.run(db.book(decisions), scenario=scenario, multiplier=multiplier)}


@app.get("/monitoring/drift", tags=["Risk"])
def drift(simulate: Optional[Literal["construction_boom", "bigger_loans", "riskier_mix"]] = None):
    """Population Stability Index for incoming applications vs the training data.
    Use `simulate` to see how the monitor reacts to a hypothetical shift."""
    current = db.book(("Approve", "Refer", "Decline", "Returned"))
    if simulate:
        current = monitoring.simulate(current, simulate)
    report = monitoring.drift_report(current)
    return {"simulated": simulate, "simulation_note": monitoring.SIMULATIONS.get(simulate), **report}


@app.get("/policy", tags=["Reference"])
def policy_rules():
    return [{"rule": r, "outcome": o, "triggered_when": t} for r, o, t in policy.POLICY_SUMMARY] + [
        {"rule": "Model score", "outcome": "refer", "triggered_when": f"PD from {decision.APPROVE_BELOW:.0%} to under {decision.DECLINE_FROM:.0%}"},
        {"rule": "Model score", "outcome": "decline", "triggered_when": f"PD of {decision.DECLINE_FROM:.0%} or more"},
    ]


@app.get("/model", tags=["Reference"])
def model_card():
    return json.loads(model.CARD_PATH.read_text())


@app.get("/reference/options", tags=["Reference"])
def options():
    """Allowed values for dropdowns in a front end."""
    return {"industry": sorted(ref.INDUSTRY_WEIGHTS), "asset_category": sorted(ref.ASSETS),
            "state": sorted(ref.STATE_WEIGHTS), "condition": ["New", "Used"], "channel": ["Broker", "Dealer"],
            "entity_type": sorted(ref.ENTITY_TYPES), "term_months": [12, 24, 36, 48, 60, 72, 84],
            "asset_models": {k: [m for m, _ in v["models"]] for k, v in ref.ASSETS.items()}}

# Metro Deal Desk

[![Tests](https://github.com/PaneerChilliDry/metro_deal_desk/actions/workflows/ci.yml/badge.svg)](https://github.com/PaneerChilliDry/metro_deal_desk/actions/workflows/ci.yml)

Loan application triage for vehicle and equipment finance: a REST API, data quality checks, an explainable credit risk model, policy rules and broker feedback notes.

All data in this project is synthetic, calibrated against public sources. Work in progress.

## Project structure

```
notebooks/
  01_sba_profiling.ipynb        Real-world risk effects from 273k US SBA loans
  02_synthetic_generator.ipynb  Generates and checks the synthetic applications
  03_model_and_decisions.ipynb  Model training, calibration, explanations, validator test, triage
src/metro_deal_desk/
  reference.py                  Asset catalogue, mixes, rates, sources and assumptions
  generator.py                  Synthetic applications, hidden default process, data quality injection
  validation.py                 Data quality rules (reject or warn) and duplicate detection
  features.py                   Feature engineering shared by training and live scoring
  model.py                      LightGBM credit model with monotone constraints and SHAP reasons
  policy.py                     Credit policy rules (refer or decline)
  decision.py                   Combines everything into Approve / Refer / Decline / Returned plus a broker note
  pipeline.py                   Scores the live queue and writes files for the dashboard
  db.py                         SQLite store for applications, decisions and data quality issues
  api.py                        FastAPI service
sql/
  portfolio.sql                 Portfolio analytics queries (decision mix, broker scorecard, and more)
tests/                          pytest suite (validation, policy, model behaviour, decisions, API)
.github/workflows/ci.yml        Runs the tests on every push
render.yaml                     Deployment config for Render
models/
  credit_model.txt              Trained model
  model_card.json               What it was trained on, test results, constraints
data/
  raw/                          Source data (not committed; see below)
  calibration/sba_effects.json  Effects exported from notebook 01
  synthetic/                    Generated datasets (see below)
  scored/                       Scored live queue and rejection log
```

Rebuild everything, in order:

```
python -m metro_deal_desk.generator   # synthetic data
python -m metro_deal_desk.model       # train and save the model
python -m metro_deal_desk.pipeline    # score the live queue
```

## How a decision is made

1. **Data quality.** Rules check each submission (valid ABN, postcode matches state, balloon below loan, term offered, "new" assets are actually new, and so on). Serious problems return it to the broker unscored; minor ones are flagged. On the synthetic queue it caught all 140 injected problems with no false alarms on 1,864 clean submissions.
2. **Risk model.** LightGBM estimates the probability of default. It is tested on the newest 20% of applications (AUC 0.728, well calibrated) and constrained so a better credit score or longer trading history can never raise risk. SHAP values give the top reasons for each score.
3. **Credit policy.** Fixed rules (balloon limits, trading history, asset age at end of term, loan to value, credit score floor, automatic decision limit) can refer or decline whatever the score.
4. **Decision and broker note.** Approve (PD under 5%), Refer (5 to 12%, or any policy referral) or Decline (12% or more, or a policy decline). The note is built only from the reasons found, with specific fixes such as the balloon amount that would bring a deal within policy.

## API

Interactive docs at `/docs` once running. Main endpoints:

| Method | Path | What it does |
|---|---|---|
| POST | `/applications` | Submit an application; returns decision, risk score, reasons, policy flags and broker note |
| GET | `/applications` | Recent applications, filter with `?decision=Refer` |
| GET | `/applications/{id}` | One application with its full result |
| POST | `/quote` | Monthly repayment for a loan with a balloon |
| GET | `/portfolio/summary` | Decision mix, risk by industry, broker scorecard, data quality by rule, weekly volume |
| GET | `/policy`, `/model`, `/reference/options` | Policy rules, model card, allowed values for forms |
| GET | `/health` | Service check |

Business-rule problems (bad ABN, postcode in the wrong state) return 200 with a `Returned` decision and clear messages, so a broker portal can show them. Wrong types (text where a number belongs) return 422. Resubmitting the same deal within 7 days is caught as a duplicate.

The database is SQLite, seeded with the scored synthetic queue on start-up. On Render's free tier the disk is temporary, so API submissions reset when the service restarts.

## Setup

```
python -m venv .venv
.venv\Scripts\activate        (Windows)   or   source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                          # 50 tests
uvicorn metro_deal_desk.api:app --reload        # then open http://127.0.0.1:8000/docs
```

`requirements.txt` holds only what the API needs (used for deployment); `requirements-dev.txt` adds testing and notebook tools.

The SBA dataset (`SBAnational.csv`, 179 MB) is not in the repo. Download it from Kaggle ("Should This Loan be Approved or Denied?") and place it in `data/raw/`.

## Data provenance

All application data is synthetic. It is not Metro Finance data and does not describe real businesses. ABNs are random numbers that pass the ATO checksum; any match with a real ABN is coincidental.

| Dataset | Rows | Contents |
|---|---|---|
| `applications_history.csv` | 20,000 | Past applications with a `defaulted` outcome, used for training |
| `applications_incoming_raw.csv` | about 2,000 | Live queue as brokers submit it, with deliberate data problems and no outcome |
| `incoming_dq_truth.csv` | about 140 | Which incoming rows were corrupted and how (answer key for the validator) |

How it is built:

- **Relative risk** by industry, business age and loan size is measured from real US SBA loans (notebook 01).
- **Levels** come from Australian sources: lifetime default set at about 5%, anchored on prime auto ABS 30+ day arrears of 1.3 to 1.8% in 2026; interest rates of about 7 to 14% based on published secured business loan rates.
- **Asset-finance effects** (balloon above expected resale value, asset age at end of term, loan term, credit score) are labelled assumptions in `generator.py`.
- **Unobserved factors** (broker quality and random noise) are added so a model cannot simply relearn the formula. A logistic regression reaches AUC 0.71 against a ceiling of 0.79 set by the true hidden probability.

Limitations: model performance on this data says nothing about performance on real lending data; SBA effects come from US government-guaranteed loans in the 2000s; the credit score, balloon and asset-age effects are designed, not measured.

## Data sources

- Li, M., Mickel, A. and Taylor, S. (2018), "Should This Loan be Approved or Denied?: A Large Dataset with Class Assignment Guidelines", *Journal of Statistics Education*, 26:1, 55-66. CC BY 4.0.
- Aquasia (2026), *Australian Auto ABS Fundamentals*, citing S&P Global SPIN: 30+ day arrears 1.32% (May 2026).
- Morningstar DBRS (2026), *Australian Auto Loan ABS Performance Tracker Q1 2026*: prime arrears 1.80%.
- Mozo (2026), *Business Loans Australia*: secured business loans 6.8 to 9.5% p.a. at major banks.
- FCAI VFACTS 2025 via AfMA: SUVs 60.7%, light commercials 22.6%, battery EVs 8.3% of new vehicle sales.

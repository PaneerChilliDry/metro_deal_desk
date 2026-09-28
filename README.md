# Metro Deal Desk

Loan application triage for vehicle and equipment finance: a REST API, data quality checks, an explainable credit risk model, policy rules and broker feedback notes.

All data in this project is synthetic, calibrated against public sources. Work in progress.

## Project structure

```
notebooks/
  01_sba_profiling.ipynb        Real-world risk effects from 273k US SBA loans
  02_synthetic_generator.ipynb  Generates and checks the synthetic applications
src/metro_deal_desk/
  reference.py                  Asset catalogue, mixes, rates, sources and assumptions
  generator.py                  Synthetic applications, hidden default process, data quality injection
data/
  raw/                          Source data (not committed; see below)
  calibration/sba_effects.json  Effects exported from notebook 01
  synthetic/                    Generated datasets (see below)
```

To regenerate the synthetic data: `python -m metro_deal_desk.generator`

## Setup

```
python -m venv .venv
.venv\Scripts\activate        (Windows)   or   source .venv/bin/activate
pip install -r requirements.txt
```

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

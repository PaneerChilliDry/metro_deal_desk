"""Reference data for the synthetic generator.

Every number here is either (a) measured from the SBA dataset (see
notebooks/01_sba_profiling.ipynb and data/calibration/sba_effects.json),
(b) taken from a cited Australian public source, or (c) a labelled modelling
assumption. None of it is Metro Finance data.
"""

# --- Industries -------------------------------------------------------------
# Share of applications by industry. ASSUMPTION: skewed toward the trades,
# transport and agriculture, which dominate vehicle and equipment finance.
INDUSTRY_WEIGHTS = {
    "Construction & trades": 22,
    "Transport & logistics": 16,
    "Professional services": 10,
    "Agriculture": 8,
    "Manufacturing": 7,
    "Retail trade": 7,
    "Hospitality": 6,
    "Other services": 6,
    "Wholesale trade": 5,
    "Health care": 5,
    "Admin & support services": 5,
    "Other": 2,
    "Mining": 1,
}

# --- Assets -----------------------------------------------------------------
# new_price: (low, high) AUD for a new unit. depreciation: annual rate.
# ASSUMPTION: indicative market ranges, not a price guide.
ASSETS = {
    "Car / SUV": {
        "models": [("Toyota RAV4 Hybrid", "Hybrid"), ("Mazda CX-5", "Petrol"),
                   ("Hyundai Tucson", "Petrol"), ("Kia Sportage", "Petrol"),
                   ("Tesla Model Y", "Electric"), ("BYD Atto 3", "Electric"),
                   ("Toyota Camry Hybrid", "Hybrid"), ("MG ZS EV", "Electric")],
        "new_price": (35_000, 75_000), "depreciation": 0.15,
        "terms": [36, 48, 60], "balloon_range": (0.0, 0.40),
    },
    "Ute / van": {
        "models": [("Toyota HiLux SR5", "Diesel"), ("Ford Ranger XLT", "Diesel"),
                   ("Isuzu D-Max", "Diesel"), ("Mitsubishi Triton", "Diesel"),
                   ("Toyota HiAce", "Diesel"), ("Ford Transit Custom", "Diesel"),
                   ("BYD Shark 6", "Plug-in hybrid")],
        "new_price": (40_000, 80_000), "depreciation": 0.12,
        "terms": [36, 48, 60], "balloon_range": (0.0, 0.40),
    },
    "Truck": {
        "models": [("Isuzu NPR 45-155", "Diesel"), ("Hino 300 Series", "Diesel"),
                   ("Fuso Canter", "Diesel"), ("Volvo FH", "Diesel"),
                   ("Kenworth T610", "Diesel")],
        "new_price": (70_000, 350_000), "depreciation": 0.12,
        "terms": [48, 60, 72, 84], "balloon_range": (0.0, 0.30),
    },
    "Earthmoving equipment": {
        "models": [("Kubota KX040 excavator", "Diesel"), ("CAT 305 mini excavator", "Diesel"),
                   ("Bobcat S650 skid steer", "Diesel"), ("Komatsu PC55 excavator", "Diesel")],
        "new_price": (50_000, 220_000), "depreciation": 0.10,
        "terms": [36, 48, 60], "balloon_range": (0.0, 0.20),
    },
    "Agricultural machinery": {
        "models": [("John Deere 6120M tractor", "Diesel"), ("Kubota M7 tractor", "Diesel"),
                   ("Case IH Farmall tractor", "Diesel"), ("New Holland T6 tractor", "Diesel")],
        "new_price": (60_000, 300_000), "depreciation": 0.09,
        "terms": [48, 60, 72], "balloon_range": (0.0, 0.20),
    },
    "Trailer": {
        "models": [("Tandem box trailer", "None"), ("Tipper trailer", "None"),
                   ("Flat top trailer", "None")],
        "new_price": (5_000, 60_000), "depreciation": 0.08,
        "terms": [24, 36, 48, 60], "balloon_range": (0.0, 0.10),
    },
    "Other equipment": {
        "models": [("Toyota 8FG25 forklift", "LPG"), ("Commercial kitchen fit-out", "None"),
                   ("Dental chair", "None"), ("CNC router", "None"),
                   ("Rooftop solar PV system", "None"), ("Espresso machine", "None")],
        "new_price": (10_000, 120_000), "depreciation": 0.15,
        "terms": [24, 36, 48, 60], "balloon_range": (0.0, 0.10),
    },
}

# Which assets each industry tends to finance. ASSUMPTION.
INDUSTRY_ASSET_MIX = {
    "Construction & trades": {"Ute / van": 50, "Earthmoving equipment": 20, "Truck": 10, "Trailer": 10, "Car / SUV": 10},
    "Transport & logistics": {"Truck": 55, "Ute / van": 20, "Trailer": 20, "Other equipment": 5},
    "Agriculture": {"Agricultural machinery": 45, "Ute / van": 30, "Truck": 10, "Trailer": 15},
    "Mining": {"Ute / van": 40, "Earthmoving equipment": 40, "Truck": 20},
    "Manufacturing": {"Other equipment": 45, "Truck": 20, "Ute / van": 25, "Car / SUV": 10},
    "Wholesale trade": {"Ute / van": 40, "Truck": 35, "Other equipment": 15, "Car / SUV": 10},
    "Retail trade": {"Ute / van": 40, "Car / SUV": 30, "Other equipment": 30},
    "Hospitality": {"Other equipment": 55, "Ute / van": 25, "Car / SUV": 20},
    "Professional services": {"Car / SUV": 70, "Other equipment": 20, "Ute / van": 10},
    "Health care": {"Car / SUV": 50, "Other equipment": 50},
    "Admin & support services": {"Ute / van": 45, "Car / SUV": 35, "Other equipment": 20},
    "Other services": {"Ute / van": 45, "Car / SUV": 35, "Other equipment": 20},
    "Other": {"Car / SUV": 40, "Ute / van": 40, "Other equipment": 20},
}

# --- Geography --------------------------------------------------------------
# ASSUMPTION: roughly proportional to state population (ABS).
STATE_WEIGHTS = {"NSW": 31, "VIC": 26, "QLD": 21, "WA": 11, "SA": 7, "TAS": 2, "ACT": 1.5, "NT": 0.5}

# Australia Post postcode ranges (simplified).
POSTCODE_RANGES = {
    "NSW": [(2000, 2599), (2619, 2899)],
    "ACT": [(2600, 2618), (2900, 2920)],
    "VIC": [(3000, 3999)],
    "QLD": [(4000, 4999)],
    "SA": [(5000, 5799)],
    "WA": [(6000, 6797)],
    "TAS": [(7000, 7799)],
    "NT": [(800, 899)],
}

ENTITY_TYPES = {"Company": 45, "Sole trader": 35, "Trust": 15, "Partnership": 5}

# --- Pricing ----------------------------------------------------------------
# Mozo (2026): secured business loans at major banks 6.8-9.5% p.a.
# Non-bank asset finance prices above that for weaker credit. ASSUMPTION:
# risk-based pricing from about 7% to 14% p.a.
RATE_FLOOR, RATE_CEILING = 0.069, 0.14

# --- Default level ----------------------------------------------------------
# Australian prime auto ABS 30+ day arrears: 1.32% (May 2026, Aquasia citing
# S&P SPIN) and 1.80% (Q1 2026, Morningstar DBRS). Lifetime default is higher
# than a point-in-time arrears rate. ASSUMPTION: 5% of loans default over
# their life, which also leaves enough defaults to train a model on.
TARGET_DEFAULT_RATE = 0.05

SOURCES = {
    "sba": "Li, Mickel and Taylor (2018), Journal of Statistics Education 26:1 (CC BY 4.0)",
    "arrears_sp": "Aquasia, Australian Auto ABS Fundamentals (2026), citing S&P SPIN",
    "arrears_dbrs": "Morningstar DBRS, Australian Auto Loan ABS Performance Tracker Q1 2026",
    "rates": "Mozo, Business Loans Australia 2026",
    "vehicle_mix": "FCAI VFACTS 2025 via AfMA: SUVs 60.7%, light commercials 22.6%, BEV 8.3% of new sales",
}

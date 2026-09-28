"""SQLite store for applications and decisions.

Plain SQL through the standard library, so every query is visible. The
schema is standard SQL and would move to Postgres with minor changes.

On first use the database is seeded with the scored synthetic queue, so the
portfolio endpoints have data even on a fresh (or free-tier, ephemeral) server.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("DEAL_DESK_DB", ROOT / "data" / "deal_desk.db"))
SQL_FILE = ROOT / "sql" / "portfolio.sql"
SCORED = ROOT / "data" / "scored"

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    application_id    TEXT PRIMARY KEY,
    submitted_date    TEXT NOT NULL,
    received_at       TEXT NOT NULL DEFAULT (datetime('now')),
    source            TEXT NOT NULL,            -- 'seed' or 'api'
    broker_id         TEXT,
    channel           TEXT,
    state             TEXT,
    industry          TEXT,
    asset_category    TEXT,
    asset_description TEXT,
    abn               TEXT,
    loan_amount       REAL,
    term_months       INTEGER,
    balloon_amount    REAL,
    dq_status         TEXT NOT NULL,
    decision          TEXT NOT NULL,
    pd                REAL,
    risk_grade        TEXT,
    broker_note       TEXT,
    result_json       TEXT
);
CREATE INDEX IF NOT EXISTS ix_app_dup ON applications (abn, asset_description, loan_amount);
CREATE INDEX IF NOT EXISTS ix_app_decision ON applications (decision);

CREATE TABLE IF NOT EXISTS dq_issues (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications (application_id),
    rule           TEXT NOT NULL,
    severity       TEXT NOT NULL,
    field          TEXT,
    message        TEXT
);
"""

COLUMNS = ["application_id", "submitted_date", "source", "broker_id", "channel", "state", "industry",
           "asset_category", "asset_description", "abn", "loan_amount", "term_months", "balloon_amount",
           "dq_status", "decision", "pd", "risk_grade", "broker_note", "result_json"]


@contextmanager
def connect(path: Path | None = None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init(path: Path | None = None, seed: bool = True) -> None:
    with connect(path) as con:
        con.executescript(SCHEMA)
        empty = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0
        if seed and empty and (SCORED / "scored_queue.csv").exists():
            _seed(con)


def _seed(con) -> None:
    q = pd.read_csv(SCORED / "scored_queue.csv", dtype={"abn": str})
    q["source"] = "seed"
    q["result_json"] = q["reasons_json"].map(lambda r: json.dumps({"reasons": json.loads(r)}) if isinstance(r, str) and r else "")
    rows = q.reindex(columns=COLUMNS).astype(object).where(q.reindex(columns=COLUMNS).notna(), None)
    con.executemany(f"INSERT INTO applications ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                    rows.itertuples(index=False, name=None))
    log = pd.read_csv(SCORED / "rejection_log.csv")
    con.executemany("INSERT INTO dq_issues (application_id, rule, severity, field, message) VALUES (?, ?, ?, ?, ?)",
                    log[["application_id", "rule", "severity", "field", "message"]].itertuples(index=False, name=None))


def save(app: dict, result: dict, path: Path | None = None) -> None:
    rec = {
        "application_id": result["application_id"], "submitted_date": str(app["submitted_date"]),
        "source": "api", "broker_id": app.get("broker_id"), "channel": app.get("channel"),
        "state": app.get("state"), "industry": app.get("industry"), "asset_category": app.get("asset_category"),
        "asset_description": app.get("asset_description"), "abn": app.get("abn"),
        "loan_amount": app.get("loan_amount"), "term_months": app.get("term_months"),
        "balloon_amount": app.get("balloon_amount"), "dq_status": result["dq_status"],
        "decision": result["decision"], "pd": result["pd"], "risk_grade": result["risk_grade"],
        "broker_note": result["broker_note"], "result_json": json.dumps(result),
    }
    with connect(path) as con:
        con.execute(f"INSERT OR REPLACE INTO applications ({', '.join(COLUMNS)}) "
                    f"VALUES ({', '.join('?' * len(COLUMNS))})", [rec[c] for c in COLUMNS])
        con.execute("DELETE FROM dq_issues WHERE application_id = ?", [rec["application_id"]])
        con.executemany("INSERT INTO dq_issues (application_id, rule, severity, field, message) VALUES (?, ?, ?, ?, ?)",
                        [(rec["application_id"], i["rule"], i["severity"], i["field"], i["message"])
                         for i in result["dq_issues"]])


def find_recent_duplicate(abn: str, asset_description: str, loan_amount: float, submitted_date: str,
                          days: int = 7, path: Path | None = None) -> str | None:
    """Return the ID of an earlier matching submission within the window, if any."""
    sql = """
        SELECT application_id FROM applications
        WHERE abn = ? AND asset_description = ? AND loan_amount = ?
          AND julianday(?) - julianday(submitted_date) BETWEEN 0 AND ?
          AND decision <> 'Returned'
        ORDER BY submitted_date DESC LIMIT 1
    """
    with connect(path) as con:
        row = con.execute(sql, [abn, asset_description, loan_amount, submitted_date, days]).fetchone()
    return row[0] if row else None


def get(application_id: str, path: Path | None = None) -> dict | None:
    with connect(path) as con:
        row = con.execute("SELECT * FROM applications WHERE application_id = ?", [application_id]).fetchone()
    if not row:
        return None
    d = dict(row)
    raw = d.pop("result_json") or ""
    d["result"] = json.loads(raw) if raw else None  # full result for API submissions; reasons only for seeded rows
    return d


def list_applications(decision: str | None = None, limit: int = 50, offset: int = 0,
                      path: Path | None = None) -> list[dict]:
    sql = ("SELECT application_id, submitted_date, source, broker_id, industry, asset_description, loan_amount, "
           "dq_status, decision, pd, risk_grade FROM applications")
    args: list = []
    if decision:
        sql += " WHERE decision = ?"
        args.append(decision)
    sql += " ORDER BY submitted_date DESC, application_id DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    with connect(path) as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def _named_queries() -> dict[str, str]:
    text = SQL_FILE.read_text()
    parts = re.split(r"^-- name: (\w+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def portfolio_summary(path: Path | None = None) -> dict:
    with connect(path) as con:
        return {name: [dict(r) for r in con.execute(sql).fetchall()] for name, sql in _named_queries().items()}

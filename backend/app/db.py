import sqlite3
from collections.abc import Iterator
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('individual', 'business')),
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id                TEXT PRIMARY KEY,
    source_account_id TEXT NOT NULL REFERENCES accounts(id),
    target_account_id TEXT NOT NULL REFERENCES accounts(id),
    amount_cents      INTEGER NOT NULL CHECK (amount_cents > 0),
    currency          TEXT NOT NULL,
    timestamp         TEXT NOT NULL,   -- when the transfer happened (UTC)
    ingested_at       TEXT NOT NULL,   -- when GraphGuard received it (UTC)
    CHECK (source_account_id <> target_account_id)
);

CREATE INDEX IF NOT EXISTS idx_tx_source ON transactions(source_account_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_tx_target ON transactions(target_account_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_tx_time   ON transactions(timestamp);

CREATE TABLE IF NOT EXISTS alerts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key          TEXT NOT NULL UNIQUE,   -- fingerprint of rule + evidence
    rule               TEXT NOT NULL,
    risk_score         INTEGER NOT NULL,
    priority           TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    summary            TEXT NOT NULL,
    accounts_json      TEXT NOT NULL,
    contributions_json TEXT NOT NULL,          -- the "why this score" checklist
    window_start       TEXT NOT NULL,
    window_end         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'new'
                       CHECK (status IN ('new', 'in_review', 'escalated', 'dismissed')),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

-- Evidence links: which transactions support which alert (many-to-many)
CREATE TABLE IF NOT EXISTS alert_evidence (
    alert_id       INTEGER NOT NULL REFERENCES alerts(id),
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    PRIMARY KEY (alert_id, transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_tx ON alert_evidence(transaction_id);

-- Analyst opinions live apart from evidence on purpose
CREATE TABLE IF NOT EXISTS alert_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id   INTEGER NOT NULL REFERENCES alerts(id),
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Investigation timeline: every change, who did it, and why
CREATE TABLE IF NOT EXISTS alert_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id    INTEGER NOT NULL REFERENCES alerts(id),
    event       TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    actor       TEXT NOT NULL,
    comment     TEXT,
    created_at  TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may set up and use a connection on
    # different threads. Safe here because every request gets its own connection.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores FKs unless enabled per connection
    return conn


def init_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed."""
    conn = connect(get_settings().database_path)
    try:
        yield conn
    finally:
        conn.close()
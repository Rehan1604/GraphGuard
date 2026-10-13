"""Plain (blocking) code that handles ONE incoming event end to end:
store it -> look for patterns around it -> save/update alerts."""
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app import repository as core
from app.alerts import repository as alert_repo
from app.alerts.models import AlertSummary
from app.db import connect
from app.detection.engine import run_detection
from app.detection.models import DetectionConfig
from app.ml.service import score_findings_if_enabled
from app.schemas import AccountCreate, Transaction, TransactionCreate
from app.simulation.generator import SIM_PREFIX


@dataclass
class IngestResult:
    transaction: Transaction
    created: bool  # False = we had already seen this exact event
    alerts: list[tuple[AlertSummary, str]]  # (alert, "created" | "updated")


def lookback_minutes(cfg: DetectionConfig) -> int:
    """No pattern is longer than this, so older history can't matter to a new event."""
    return max(cfg.cycle_window_minutes, cfg.chain_hop_window_minutes * cfg.max_chain_hops, cfg.burst_window_minutes)


def ingest_event(db_path: Path, tx: TransactionCreate, config: DetectionConfig | None = None) -> IngestResult:
    cfg = config or DetectionConfig()
    conn = connect(db_path)
    try:
        stored, created = core.create_transaction(conn, tx)  # idempotent by transaction id
        if not created:
            return IngestResult(stored, False, [])  # duplicate: do nothing else

        recent = core.transactions_since(conn, stored.timestamp - timedelta(minutes=lookback_minutes(cfg)))
        findings = [f for f in run_detection(recent, cfg).findings if stored.id in f.transaction_ids]

        alerts: list[tuple[AlertSummary, str]] = []
        seen: set[int] = set()
        triage = score_findings_if_enabled(findings, recent, lookback_minutes(cfg))
        for alert_id, outcome in alert_repo.save_findings_detailed(conn, findings, triage):
            if outcome != "unchanged" and alert_id not in seen:
                seen.add(alert_id)
                alerts.append((alert_repo.get_alert_summary(conn, alert_id), outcome))
        return IngestResult(stored, True, alerts)
    finally:
        conn.close()


def ensure_sim_accounts(db_path: Path, specs: list[AccountCreate]) -> None:
    conn = connect(db_path)
    try:
        for spec in specs:
            try:
                core.create_account(conn, spec)
            except core.DuplicateAccountError:
                pass
    finally:
        conn.close()


def reset_simulated_data(db_path: Path) -> None:
    """Delete ONLY what the simulator made (ids starting 'SIM-'). Your own data is untouched."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT alert_id FROM alert_evidence WHERE transaction_id LIKE ?", (SIM_PREFIX + "%",)
        ).fetchall()
        ids = [(r[0],) for r in rows]
        for table in ("alert_history", "alert_notes", "alert_evidence"):
            conn.executemany(f"DELETE FROM {table} WHERE alert_id = ?", ids)
        conn.executemany("DELETE FROM alerts WHERE id = ?", ids)
        conn.execute("DELETE FROM transactions WHERE id LIKE ?", (SIM_PREFIX + "%",))
        conn.execute("DELETE FROM accounts WHERE id LIKE ?", (SIM_PREFIX + "%",))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()
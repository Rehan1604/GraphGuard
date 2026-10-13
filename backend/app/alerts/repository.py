import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Literal

from app import repository as core
from app.alerts.models import (
    AlertDetail,
    AlertSummary,
    HistoryEvent,
    MlDriver,
    Note,
    NoteCreate,
    ScanSummary,
    StatusChange,
)
from app.alerts.workflow import ALLOWED_TRANSITIONS, COMMENT_REQUIRED, check_transition
from app.detection.models import Finding, ScoreContribution
from app.ml.model import TriageScore

Outcome = Literal["created", "updated", "unchanged"]


class AlertNotFoundError(Exception):
    pass


def _dedup_key(rule: str, tx_ids: set[str]) -> str:
    """Same rule + same evidence -> same fingerprint -> same alert."""
    return hashlib.sha256(f"{rule}|{','.join(sorted(tx_ids))}".encode()).hexdigest()[:32]


def _add_history(conn, alert_id, event, actor, comment=None, from_status=None, to_status=None):
    conn.execute(
        """INSERT INTO alert_history
           (alert_id, event, from_status, to_status, actor, comment, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (alert_id, event, from_status, to_status, actor, comment, core.now_iso()),
    )


def _evidence_ids(conn, alert_id: int) -> set[str]:
    rows = conn.execute("SELECT transaction_id FROM alert_evidence WHERE alert_id = ?", (alert_id,))
    return {r["transaction_id"] for r in rows}


def _store_finding_fields(f: Finding) -> tuple:
    return (
        f.risk_score,
        f.priority,
        f.summary,
        json.dumps(f.accounts),
        json.dumps([c.model_dump() for c in f.contributions]),
        core.to_iso(f.window_start),
        core.to_iso(f.window_end),
    )


def _ml_fields(score: TriageScore | None) -> tuple:
    if score is None:
        return (None, None, None, None)
    drivers = [{"label": d.label, "value": d.value, "effect": d.effect, "direction": d.direction} for d in score.drivers]
    return (round(score.probability, 4), score.verdict, score.model_version, json.dumps(drivers))


def upsert_finding(conn: sqlite3.Connection, f: Finding, triage: TriageScore | None = None) -> tuple[int, Outcome]:
    """Turn a detection finding into a stored alert WITHOUT creating duplicates.
    (Does not commit: save_findings commits once at the end.)"""
    ids = set(f.transaction_ids)
    key = _dedup_key(f.rule, ids)

    exact = conn.execute("SELECT id FROM alerts WHERE dedup_key = ?", (key,)).fetchone()
    if exact:
        return exact["id"], "unchanged"

    marks = ",".join("?" * len(ids))
    candidates = conn.execute(
        f"""SELECT DISTINCT a.id FROM alerts a
            JOIN alert_evidence e ON e.alert_id = a.id
            WHERE a.rule = ? AND e.transaction_id IN ({marks})""",
        [f.rule, *ids],
    ).fetchall()
    existing = {c["id"]: _evidence_ids(conn, c["id"]) for c in candidates}

    # Already covered by a bigger alert? Then nothing new to say.
    for alert_id, ev in existing.items():
        if ids <= ev:
            return alert_id, "unchanged"

    # Same story, but it grew? Update that alert instead of opening a second one.
    for alert_id, ev in existing.items():
        if ev < ids:
            score, priority, summary, accounts, contributions, w_start, w_end = _store_finding_fields(f)
            old_status = conn.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,)).fetchone()["status"]
            new_status = "new" if old_status == "dismissed" else old_status
            conn.execute(
                """UPDATE alerts SET dedup_key=?, risk_score=?, priority=?, summary=?,
                   accounts_json=?, contributions_json=?, window_start=?, window_end=?,
                   status=?, updated_at=?, ml_score=?, ml_verdict=?, ml_model=?, ml_drivers_json=? WHERE id=?""",
                (key, score, priority, summary, accounts, contributions, w_start, w_end,
                 new_status, core.now_iso(), *_ml_fields(triage), alert_id),
            )
            for tx_id in ids - ev:
                conn.execute(
                    "INSERT OR IGNORE INTO alert_evidence (alert_id, transaction_id) VALUES (?, ?)",
                    (alert_id, tx_id),
                )
            _add_history(conn, alert_id, "evidence_grew", "system",
                         comment=f"Pattern grew from {len(ev)} to {len(ids)} transactions")
            if new_status != old_status:
                _add_history(conn, alert_id, "status_changed", "system",
                             comment="Reopened automatically because new evidence arrived",
                             from_status=old_status, to_status=new_status)
            return alert_id, "updated"

    score, priority, summary, accounts, contributions, w_start, w_end = _store_finding_fields(f)
    now = core.now_iso()
    cur = conn.execute(
        """INSERT INTO alerts (dedup_key, rule, risk_score, priority, summary, accounts_json,
           contributions_json, window_start, window_end, status, created_at, updated_at,
           ml_score, ml_verdict, ml_model, ml_drivers_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?)""",
        (key, f.rule, score, priority, summary, accounts, contributions, w_start, w_end, now, now, *_ml_fields(triage)),
    )
    alert_id = cur.lastrowid
    for tx_id in ids:
        conn.execute(
            "INSERT INTO alert_evidence (alert_id, transaction_id) VALUES (?, ?)", (alert_id, tx_id)
        )
    _add_history(conn, alert_id, "created", "system", comment="Alert raised by detection rules")
    return alert_id, "created"


def save_findings_detailed(
    conn: sqlite3.Connection, findings: list[Finding], triage: list[TriageScore | None] | None = None
) -> list[tuple[int, Outcome]]:
    """Save findings all-or-nothing. Returns (alert_id, outcome) for each.
    `triage` (optional) holds one model score per finding, in the same order."""
    results: list[tuple[int, Outcome]] = []
    scores = triage or [None] * len(findings)
    try:
        for f, t in zip(findings, scores):
            results.append(upsert_finding(conn, f, t))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return results


def save_findings(
    conn: sqlite3.Connection, findings: list[Finding], triage: list[TriageScore | None] | None = None
) -> ScanSummary:
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for _, outcome in save_findings_detailed(conn, findings, triage):
        counts[outcome] += 1
    return ScanSummary(findings=len(findings), **counts)

_STATUS_ORDER = ("in_review", "escalated", "dismissed")
_SUMMARY_SQL = """SELECT a.*, (SELECT COUNT(*) FROM alert_evidence e WHERE e.alert_id = a.id) AS evidence_count
                  FROM alerts a"""


def _summary(row: sqlite3.Row) -> AlertSummary:
    return AlertSummary(
        id=row["id"], rule=row["rule"], risk_score=row["risk_score"], priority=row["priority"],
        summary=row["summary"], accounts=json.loads(row["accounts_json"]), status=row["status"],
        window_start=datetime.fromisoformat(row["window_start"]),
        window_end=datetime.fromisoformat(row["window_end"]),
        evidence_count=row["evidence_count"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        ml_score=row["ml_score"], ml_verdict=row["ml_verdict"],
    )


def list_alerts(conn, status=None, priority=None, rule=None, limit=100, offset=0) -> list[AlertSummary]:
    clauses, params = [], []
    for column, value in (("a.status", status), ("a.priority", priority), ("a.rule", rule)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    sql = _SUMMARY_SQL + (" WHERE " + " AND ".join(clauses) if clauses else "")
    sql += " ORDER BY a.risk_score DESC, a.id DESC LIMIT ? OFFSET ?"
    return [_summary(r) for r in conn.execute(sql, [*params, limit, offset]).fetchall()]


def _notes(conn, alert_id: int) -> list[Note]:
    rows = conn.execute("SELECT * FROM alert_notes WHERE alert_id = ? ORDER BY id", (alert_id,))
    return [Note(id=r["id"], alert_id=r["alert_id"], author=r["author"], body=r["body"],
                 created_at=datetime.fromisoformat(r["created_at"])) for r in rows]


def _history(conn, alert_id: int) -> list[HistoryEvent]:
    rows = conn.execute("SELECT * FROM alert_history WHERE alert_id = ? ORDER BY id", (alert_id,))
    return [HistoryEvent(id=r["id"], event=r["event"], from_status=r["from_status"],
                         to_status=r["to_status"], actor=r["actor"], comment=r["comment"],
                         created_at=datetime.fromisoformat(r["created_at"])) for r in rows]


def get_alert_detail(conn, alert_id: int) -> AlertDetail | None:
    row = conn.execute(_SUMMARY_SQL + " WHERE a.id = ?", (alert_id,)).fetchone()
    if row is None:
        return None
    evidence_rows = conn.execute(
        """SELECT t.* FROM alert_evidence e JOIN transactions t ON t.id = e.transaction_id
           WHERE e.alert_id = ? ORDER BY t.timestamp, t.id""",
        (alert_id,),
    ).fetchall()
    return AlertDetail(
        **_summary(row).model_dump(),
        ml_model=row["ml_model"],
        ml_drivers=[MlDriver(**d) for d in json.loads(row["ml_drivers_json"] or "[]")],
        contributions=[ScoreContribution(**c) for c in json.loads(row["contributions_json"])],
        evidence=[core.row_to_transaction(r) for r in evidence_rows],
        notes=_notes(conn, alert_id),
        history=_history(conn, alert_id),
        allowed_next_statuses=[x for x in _STATUS_ORDER if x in ALLOWED_TRANSITIONS.get(row["status"], set())],
        comment_required_for=[x for x in _STATUS_ORDER if x in COMMENT_REQUIRED],
    )


def add_note(conn, alert_id: int, data: NoteCreate) -> Note:
    if conn.execute("SELECT 1 FROM alerts WHERE id = ?", (alert_id,)).fetchone() is None:
        raise AlertNotFoundError(alert_id)
    cur = conn.execute(
        "INSERT INTO alert_notes (alert_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (alert_id, data.author, data.body, core.now_iso()),
    )
    conn.commit()
    return next(n for n in _notes(conn, alert_id) if n.id == cur.lastrowid)


def change_status(conn, alert_id: int, data: StatusChange) -> AlertDetail:
    row = conn.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise AlertNotFoundError(alert_id)
    comment = data.comment.strip() if data.comment and data.comment.strip() else None
    check_transition(row["status"], data.status, comment)  # raises if not allowed
    conn.execute(
        "UPDATE alerts SET status = ?, updated_at = ? WHERE id = ?",
        (data.status, core.now_iso(), alert_id),
    )
    _add_history(conn, alert_id, "status_changed", data.actor, comment, row["status"], data.status)
    conn.commit()
    return get_alert_detail(conn, alert_id)  # type: ignore[return-value]

def get_alert_summary(conn: sqlite3.Connection, alert_id: int) -> AlertSummary:
    return _summary(conn.execute(_SUMMARY_SQL + " WHERE a.id = ?", (alert_id,)).fetchone())
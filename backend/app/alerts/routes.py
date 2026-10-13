import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app import repository as core
from app.alerts import repository as repo
from app.alerts.models import (
    AlertDetail,
    AlertSummary,
    Note,
    NoteCreate,
    ScanSummary,
    Status,
    StatusChange,
)
from app.alerts.workflow import CommentRequiredError, InvalidTransitionError
from app.db import get_db
from app.ratelimit import rate_limited
from app.detection.engine import run_detection
from app.detection.models import DetectionConfig
from app.ml.service import score_findings_if_enabled
from app.simulation.ingest import lookback_minutes

router = APIRouter(prefix="/api/alerts")
Db = Annotated[sqlite3.Connection, Depends(get_db)]


@router.post("/scan", response_model=ScanSummary, dependencies=[Depends(rate_limited)])
def scan(db: Db, config: DetectionConfig | None = None) -> ScanSummary:
    """Run the detection rules and save what they find as alerts.
    Safe to repeat: identical patterns never create duplicate alerts."""
    transactions = core.all_transactions_chronological(db)
    result = run_detection(transactions, config)
    triage = score_findings_if_enabled(result.findings, transactions, lookback_minutes(result.config))
    return repo.save_findings(db, result.findings, triage)


@router.get("", response_model=list[AlertSummary])
def list_alerts(
    db: Db,
    status: Status | None = None,
    priority: Literal["low", "medium", "high"] | None = None,
    rule: Literal["pass_through_chain", "cycle", "burst", "fan"] | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AlertSummary]:
    return repo.list_alerts(db, status, priority, rule, limit, offset)


@router.get("/{alert_id}", response_model=AlertDetail)
def get_alert(alert_id: int, db: Db) -> AlertDetail:
    alert = repo.get_alert_detail(db, alert_id)
    if alert is None:
        raise HTTPException(404, f"Alert {alert_id} not found")
    return alert


@router.post("/{alert_id}/notes", response_model=Note, status_code=201)
def add_note(alert_id: int, payload: NoteCreate, db: Db) -> Note:
    try:
        return repo.add_note(db, alert_id, payload)
    except repo.AlertNotFoundError:
        raise HTTPException(404, f"Alert {alert_id} not found")


@router.post("/{alert_id}/status", response_model=AlertDetail)
def change_status(alert_id: int, payload: StatusChange, db: Db) -> AlertDetail:
    try:
        return repo.change_status(db, alert_id, payload)
    except repo.AlertNotFoundError:
        raise HTTPException(404, f"Alert {alert_id} not found")
    except InvalidTransitionError as exc:
        raise HTTPException(409, str(exc))
    except CommentRequiredError as exc:
        raise HTTPException(422, str(exc))
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.detection.models import ScoreContribution
from app.schemas import Transaction

Status = Literal["new", "in_review", "escalated", "dismissed"]
Author = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class NoteCreate(BaseModel):
    author: Author = "analyst"
    body: NoteText


class Note(NoteCreate):
    id: int
    alert_id: int
    created_at: datetime


class StatusChange(BaseModel):
    status: Status
    comment: str | None = Field(None, max_length=1000)
    actor: Author = "analyst"


class HistoryEvent(BaseModel):
    id: int
    event: str
    from_status: str | None
    to_status: str | None
    actor: str
    comment: str | None
    created_at: datetime


class AlertSummary(BaseModel):
    id: int
    rule: str
    risk_score: int
    priority: Literal["low", "medium", "high"]
    summary: str
    accounts: list[str]
    status: Status
    window_start: datetime
    window_end: datetime
    evidence_count: int
    created_at: datetime
    updated_at: datetime


class AlertDetail(AlertSummary):
    contributions: list[ScoreContribution]  # why the score is what it is
    evidence: list[Transaction]  # FACTS from the data
    notes: list[Note]  # OPINIONS from people
    history: list[HistoryEvent]  # the investigation timeline
    allowed_next_statuses: list[Status]  # the server decides which buttons the UI shows
    comment_required_for: list[Status]

class ScanSummary(BaseModel):
    findings: int
    created: int
    updated: int
    unchanged: int
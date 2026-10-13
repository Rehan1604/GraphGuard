from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


class Fact(BaseModel):
    """A statement computed directly from the stored data. Verified (the triage fact reports a model's estimate, and says so)."""

    id: str  # F1, F2, ...
    text: str
    kind: Literal["summary", "evidence", "score", "triage"]


class Passage(BaseModel):
    """A piece of the guidance library that retrieval picked. Educational, not about this alert."""

    id: str  # K1, K2, ...
    source: str  # file name
    title: str
    section: str
    text: str
    score: float
    via: Literal["similarity", "rule_default"]


class CaseMatch(BaseModel):
    """A past alert in this workspace that an analyst already reviewed, found because its comment is similar in meaning."""

    id: str  # C1, C2, ...
    alert_id: int
    rule: str
    status: str  # dismissed | escalated
    summary: str
    comment: str  # the reviewer's own words; shown here, never sent to an AI provider
    score: float


class RetrievalInfo(BaseModel):
    embedder: str
    note: str
    library_passages: int


class Section(BaseModel):
    heading: str
    items: list[str]


class Explanation(BaseModel):
    """The ONLY part that can be machine-written, and it says so."""

    mode: Literal["ai", "rule_based"]
    label: str
    provider: str | None = None
    model: str | None = None
    sections: list[Section]
    citations: list[str]
    invalid_citations_removed: list[str]
    warnings: list[str]
    privacy_note: str | None = None


class AssistantAnswer(BaseModel):
    alert_id: int
    question: str
    facts: list[Fact]
    guidance: list[Passage]
    similar_cases: list[CaseMatch] = []
    retrieval: RetrievalInfo | None = None
    explanation: Explanation
    disclaimer: str


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    use_ai: bool = True


class AssistantStatus(BaseModel):
    ai_configured: bool
    provider: str
    model: str | None
    problem: str | None
    privacy: str
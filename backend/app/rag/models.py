from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


class Fact(BaseModel):
    """A statement computed directly from the stored transactions. Verified."""

    id: str  # F1, F2, ...
    text: str
    kind: Literal["summary", "evidence", "score"]


class Passage(BaseModel):
    """A piece of the guidance library that retrieval picked. Educational, not about this alert."""

    id: str  # K1, K2, ...
    source: str  # file name
    title: str
    section: str
    text: str
    score: float
    via: Literal["similarity", "rule_default"]


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
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DetectionConfig(BaseModel):
    """Every threshold the rules use. Change a number here -> behaviour changes."""

    # Rule 1: pass-through chains
    pass_through_ratio: Decimal = Field(Decimal("0.8"), gt=0, le=1)
    chain_hop_window_minutes: int = Field(30, ge=1)
    min_chain_hops: int = Field(3, ge=2)
    max_chain_hops: int = Field(6, ge=2)
    # Rule 2: cycles
    cycle_window_minutes: int = Field(120, ge=1)
    min_cycle_length: int = Field(3, ge=2)
    max_cycle_length: int = Field(5, ge=2)
    # Rules 3 and 4: bursts and many-counterparty accounts
    burst_window_minutes: int = Field(10, ge=1)
    burst_min_transactions: int = Field(6, ge=2)
    fan_min_counterparties: int = Field(5, ge=2)

    @model_validator(mode="after")
    def check_ranges(self) -> "DetectionConfig":
        if self.max_chain_hops < self.min_chain_hops:
            raise ValueError("max_chain_hops must be >= min_chain_hops")
        if self.max_cycle_length < self.min_cycle_length:
            raise ValueError("max_cycle_length must be >= min_cycle_length")
        return self


class ScoreContribution(BaseModel):
    reason: str
    points: int


class Finding(BaseModel):
    """A suspicious PATTERN worth a human look. Not proof of anything."""

    rule: Literal["pass_through_chain", "cycle", "burst", "fan"]
    accounts: list[str]  # for burst/fan, the first one is the account in focus
    transaction_ids: list[str]  # the evidence
    window_start: datetime
    window_end: datetime
    contributions: list[ScoreContribution]
    risk_score: int  # sum of contributions, capped at 100. NOT a probability.
    priority: Literal["low", "medium", "high"]
    summary: str


class DetectionResult(BaseModel):
    config: DetectionConfig
    transactions_analyzed: int
    accounts_in_graph: int
    connected_groups: int
    findings: list[Finding]


def build_finding(rule, accounts, txs, contributions, summary) -> Finding:
    score = min(100, sum(c.points for c in contributions))
    priority = "high" if score >= 70 else "medium" if score >= 40 else "low"
    return Finding(
        rule=rule,
        accounts=accounts,
        transaction_ids=[t.id for t in txs],
        window_start=min(t.timestamp for t in txs),
        window_end=max(t.timestamp for t in txs),
        contributions=contributions,
        risk_score=score,
        priority=priority,
        summary=summary,
    )
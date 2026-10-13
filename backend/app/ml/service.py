"""The one place the rest of the app talks to the triage model. If the model is switched off,
missing, or broken, every function here quietly returns None and the rules carry on alone."""
from __future__ import annotations

from app.config import get_settings
from app.detection.models import DetectionConfig, Finding
from app.ml.model import TriageScore, get_model
from app.schemas import Transaction


def score_findings_if_enabled(
    findings: list[Finding], transactions: list[Transaction], lookback_minutes: int
) -> list[TriageScore | None]:
    settings = get_settings()
    if not settings.ml_enabled or not findings:
        return [None] * len(findings)
    model = get_model(str(settings.ml_model_path) if settings.ml_model_path else None)
    if model is None:
        return [None] * len(findings)
    try:
        return list(model.score_findings(findings, transactions, lookback_minutes))
    except Exception:  # scoring is advisory; it must never stop an alert being saved
        return [None] * len(findings)


def lookback_for(cfg: DetectionConfig) -> int:
    from app.simulation.ingest import lookback_minutes

    return lookback_minutes(cfg)

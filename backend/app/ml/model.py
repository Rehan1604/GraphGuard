"""The trained triage model: load it, score alerts, explain a score.

What it is: a classifier that looks at an alert the rules already raised and estimates how likely it is
to be a real planted pattern rather than a benign look-alike or a coincidence. It re-ranks and labels
alerts. It never creates or hides one.

What the number means: a probability CALIBRATED ON THE SYNTHETIC BENCHMARK. On real data it would need
to be re-trained and re-checked. It is a review-priority aid, not a verdict about any person."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from app.detection.models import Finding
from app.ml.features import FEATURE_SETS, LABELS, extract_features
from app.schemas import Transaction

log = logging.getLogger("graphguard.ml")
ARTIFACT_DIR = Path(__file__).parent / "artifacts"
DEFAULT_MODEL = ARTIFACT_DIR / "triage.joblib"


@dataclass(frozen=True)
class Driver:
    feature: str
    label: str
    value: float
    effect: float  # change in probability caused by this feature (positive = raised it)

    @property
    def direction(self) -> str:
        return "raises" if self.effect > 0 else "lowers"


@dataclass(frozen=True)
class TriageScore:
    probability: float
    verdict: str  # "likely_true" | "likely_benign"
    drivers: list[Driver]
    model_version: str


class TriageModel:
    def __init__(self, bundle: dict, metadata: dict):
        self.pipeline = bundle["pipeline"]
        self.calibrator = bundle["calibrator"]
        self.threshold: float = bundle["threshold"]
        self.feature_names: tuple[str, ...] = tuple(bundle["feature_names"])
        self.medians: dict[str, float] = bundle["medians"]
        self.metadata = metadata
        self.version: str = metadata.get("version", "unknown")

    # --- scoring ---------------------------------------------------------------------------
    def _matrix(self, rows: list[dict[str, float]]) -> np.ndarray:
        return np.array([[r[n] for n in self.feature_names] for r in rows], dtype=float)

    def probabilities(self, rows: list[dict[str, float]]) -> list[float]:
        if not rows:
            return []
        raw = self.pipeline.predict_proba(self._matrix(rows))[:, 1]
        return [float(p) for p in self.calibrator.predict(raw)]

    def explain(self, row: dict[str, float], top: int = 4) -> list[Driver]:
        """Occlusion: replace one feature at a time with its typical (training median) value and see how much
        the probability moves. Large movement = that feature mattered for THIS alert. It is an approximation
        of influence, not a proof of cause."""
        base = self.probabilities([row])[0]
        variants = []
        for name in self.feature_names:
            variant = dict(row)
            variant[name] = self.medians[name]
            variants.append(variant)
        shifted = self.probabilities(variants)
        drivers = [
            Driver(n, LABELS.get(n, n), round(row[n], 3), round(base - p, 4))
            for n, p in zip(self.feature_names, shifted)
        ]
        drivers = [d for d in drivers if abs(d.effect) >= 0.005]
        drivers.sort(key=lambda d: -abs(d.effect))
        return drivers[:top]

    def score_findings(
        self, findings: list[Finding], transactions: list[Transaction], lookback_minutes: int
    ) -> list[TriageScore]:
        by_id = {t.id: t for t in transactions}
        rows = [
            extract_features(f, [by_id[i] for i in f.transaction_ids if i in by_id], transactions, lookback_minutes)
            for f in findings
        ]
        probs = self.probabilities(rows)
        return [
            TriageScore(p, "likely_true" if p >= self.threshold else "likely_benign", self.explain(r), self.version)
            for p, r in zip(probs, rows)
        ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_model(bundle: dict, metadata: dict, path: Path = DEFAULT_MODEL) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    metadata = {**metadata, "sha256": _sha256(path)}
    path.with_suffix(".json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")


def load_model(path: Path = DEFAULT_MODEL) -> TriageModel | None:
    """Load a model, or return None (rules-only mode) if it is missing, altered, or unreadable.
    The model file is a pickle, which can run code when loaded, so its fingerprint must match the one
    recorded at training time. Only load model files you trained or trust."""
    meta_path = path.with_suffix(".json")
    if not path.exists() or not meta_path.exists():
        log.info("no triage model at %s; running with rules only", path)
        return None
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("sha256") != _sha256(path):
            log.warning("triage model fingerprint mismatch; refusing to load %s", path)
            return None
        return TriageModel(joblib.load(path), metadata)
    except Exception as exc:  # a broken model must never break alerting
        log.warning("could not load triage model (%s); running with rules only", type(exc).__name__)
        return None


@lru_cache(maxsize=4)
def get_model(path: str | None = None) -> TriageModel | None:
    return load_model(Path(path) if path else DEFAULT_MODEL)


def feature_names_for(kind: str) -> tuple[str, ...]:
    return FEATURE_SETS[kind]

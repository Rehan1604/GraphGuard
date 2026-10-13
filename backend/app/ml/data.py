"""Build labelled training examples: one row per alert the rules raise on a benchmark dataset.

Label 1 = the alert matches a planted pattern. Label 0 = it does not (a benign look-alike, a near-miss,
or a coincidence in ordinary traffic). The labels come from the benchmark's answer key; the model never
sees the answer key, only the features."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.detection.engine import run_detection
from app.detection.models import DetectionConfig, Finding
from app.evaluation.baseline import Detection
from app.evaluation.dataset import LabelledDataset, build_benchmark
from app.evaluation.metrics import matches
from app.ml.features import extract_features
from app.simulation.ingest import lookback_minutes


@dataclass
class LabelledFinding:
    seed: int
    finding: Finding
    category: str  # "true_pattern", a look-alike name such as "payroll", a near-miss name, or "background"
    label: int
    features: dict[str, float] = field(default_factory=dict)

    @property
    def detection(self) -> Detection:
        return Detection(self.finding.rule, frozenset(self.finding.transaction_ids))


@dataclass
class SeedData:
    dataset: LabelledDataset
    rows: list[LabelledFinding]


def categorise(finding: Finding, dataset: LabelledDataset) -> tuple[str, int]:
    det = Detection(finding.rule, frozenset(finding.transaction_ids))
    for role, label in (("positive", 1), ("benign_lookalike", 0), ("near_miss", 0)):
        for e in dataset.episodes:
            if e.role == role and matches(det, e):
                return ("true_pattern" if label else e.name), label
    return "background", 0


def collect_seed(seed: int, cfg: DetectionConfig | None = None) -> SeedData:
    cfg = cfg or DetectionConfig()
    dataset = build_benchmark(seed)
    by_id = {t.id: t for t in dataset.transactions}
    lookback = lookback_minutes(cfg)
    rows = []
    for f in run_detection(dataset.transactions, cfg).findings:
        category, label = categorise(f, dataset)
        evidence = [by_id[i] for i in f.transaction_ids if i in by_id]
        rows.append(LabelledFinding(seed, f, category, label, extract_features(f, evidence, dataset.transactions, lookback)))
    return SeedData(dataset, rows)


def collect_many(seeds: list[int], cfg: DetectionConfig | None = None) -> dict[int, SeedData]:
    return {s: collect_seed(s, cfg) for s in seeds}

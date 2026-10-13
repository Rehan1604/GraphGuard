import random
import time
from datetime import timedelta
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel

from app.detection.engine import run_detection
from app.detection.models import DetectionConfig
from app.evaluation.baseline import Detection, baseline_detect
from app.evaluation.dataset import Episode, LabelledDataset, build_benchmark, dataset_from_simulator
from app.evaluation.metrics import DelayStats, DetectorResult, Rate, StreamHit, measure_delay, score_detector
from app.ml.service import score_findings_if_enabled
from app.schemas import Transaction
from app.simulation.ingest import lookback_minutes

CAVEATS = [
    "This is a SYNTHETIC benchmark. It measures how well the rules find patterns that I planted, using my own assumptions about what such patterns look like. It says nothing reliable about accuracy on real banking data.",
    "Precision depends on how many benign look-alikes I chose to plant. Change that mix and precision changes. It is a property of this test, not a discovery about the rules.",
    "The near-miss episodes were designed to sit just outside our own thresholds, so passing them shows the thresholds behave as written. It is a sanity check, not independent evidence.",
    "Look-alikes such as a split bill or a marketplace payout have exactly the same shape as the patterns we flag. A pattern rule cannot tell them apart without extra information such as account history.",
    "Detection delay is measured in event time (the timestamps in the data), not in computer speed.",
    "The planted patterns were generated to fit inside the rules' thresholds, so high recall for the graph engine is expected by construction and is NOT evidence that it would find real patterns. The informative numbers are the false positives and how results move when thresholds change.",
    "How a 'match' is defined changes the story. Strict matching needs half of a pattern; lenient matching counts any overlap. Both are shown.",
]


class DatasetSummary(BaseModel):
    name: str
    seed: int
    transactions: int
    background_transactions: int
    episodes_by_role: dict[str, int]
    positives_by_kind: dict[str, int]


class NegativeControl(BaseModel):
    description: str
    recall: Rate


class SweepPoint(BaseModel):
    value: float
    findings: int
    precision: float | None
    recall: float | None
    f1: float | None


class Sweep(BaseModel):
    """Change ONE threshold, keep everything else fixed, and watch precision and recall move."""

    parameter: str
    description: str
    default: float
    points: list[SweepPoint]


SWEEPS = [
    ("chain_hop_window_minutes", "Max minutes allowed between money arriving and leaving, in a chain", [5, 10, 15, 30, 60, 120]),
    ("burst_min_transactions", "Transfers inside the window that count as a burst", [3, 4, 5, 6, 8, 10]),
]


class Timing(BaseModel):
    """Machine-dependent: will differ on your laptop. Not part of the reproducible results."""

    streaming_seconds: float
    milliseconds_per_transaction: float


class TriageEvaluation(BaseModel):
    """The rule alerts re-filtered by the trained triage model, scored exactly like the rules alone."""

    model_version: str
    threshold: float
    result: DetectorResult
    alerts_removed: int
    seed_overlaps_training: bool  # True = this world was used to train or tune the model, so these numbers are optimistic
    recorded: dict[str, Any]  # what was measured when the model was trained, on separate held-out worlds
    caveats: list[str]


TRIAGE_CAVEATS = [
    "The model was trained on synthetic worlds from the same generator as this benchmark. Held-out worlds are new random draws, not new kinds of world.",
    "It filters out alerts it recognises as the benign look-alike types it was trained on. Withholding a look-alike type during training, it removed none of that type: it has not learned a general idea of 'benign'.",
    "Removing alerts costs recall: some genuine patterns are filtered out. Both numbers are shown so the trade is visible.",
    "The score is a probability calibrated on the benchmark. It is a review-priority aid, not a statement about anyone's intent.",
]


class EvaluationReport(BaseModel):
    dataset: DatasetSummary
    graph: DetectorResult
    triage: TriageEvaluation | None = None
    baseline: DetectorResult
    delay: DelayStats
    sweeps: list[Sweep]
    negative_control: NegativeControl
    timing: Timing
    caveats: list[str]


def stream_detect(transactions: list[Transaction], cfg: DetectionConfig) -> list[StreamHit]:
    """Replay the transactions one at a time, exactly as the live system would, recording every alert as it appears."""
    ordered = sorted(transactions, key=lambda t: (t.timestamp, t.id))
    lookback = timedelta(minutes=lookback_minutes(cfg))
    hits: list[StreamHit] = []
    left = 0
    for i, tx in enumerate(ordered):
        while ordered[left].timestamp < tx.timestamp - lookback:
            left += 1
        for f in run_detection(ordered[left : i + 1], cfg).findings:
            if tx.id in f.transaction_ids:
                hits.append(StreamHit(rule=f.rule, transaction_ids=f.transaction_ids, detected_at=tx.timestamp, arrival_index=i))
    return hits


def threshold_sweeps(dataset: LabelledDataset, base: DetectionConfig) -> list[Sweep]:
    sweeps = []
    for parameter, description, values in SWEEPS:
        points = []
        for value in values:
            cfg = base.model_copy(update={parameter: value})
            dets = [Detection(f.rule, frozenset(f.transaction_ids)) for f in run_detection(dataset.transactions, cfg).findings]
            r = score_detector("sweep", dets, dataset)
            points.append(SweepPoint(value=value, findings=r.findings, precision=r.precision.value, recall=r.recall.value, f1=r.f1))
        sweeps.append(Sweep(parameter=parameter, description=description, default=float(getattr(base, parameter)), points=points))
    return sweeps


def negative_control(dataset: LabelledDataset, detections: list[Detection], seed: int) -> NegativeControl:
    """Check the scoring itself: move every planted pattern's label onto RANDOM transactions of the same size.
    A sound evaluation must now report recall near zero. If it didn't, the metric would be broken."""
    rng = random.Random(seed)
    ids = [t.id for t in dataset.transactions]
    fake = [
        Episode(e.name, e.kind, e.role, e.accepts, frozenset(rng.sample(ids, len(e.transaction_ids))), e.start, e.end)
        for e in dataset.episodes if e.role == "positive"
    ]
    scored = score_detector("control", detections, LabelledDataset("control", seed, dataset.transactions, fake))
    return NegativeControl(
        description="Same detector, same scoring, but the answer key is moved onto random transactions. Recall should collapse.",
        recall=scored.recall,
    )


def _triage_evaluation(dataset: LabelledDataset, findings, cfg: DetectionConfig) -> TriageEvaluation | None:
    from app.config import get_settings
    from app.ml.model import get_model

    settings = get_settings()
    model = get_model(str(settings.ml_model_path) if settings.ml_model_path else None) if settings.ml_enabled else None
    if model is None or not findings:
        return None
    scores = score_findings_if_enabled(findings, dataset.transactions, lookback_minutes(cfg))
    if any(s is None for s in scores):
        return None
    kept = [f for f, s in zip(findings, scores) if s.probability >= model.threshold]
    meta = model.metadata
    used = set(meta.get("train_seeds", [])) | set(meta.get("validation_seeds", []))
    metrics = meta.get("metrics", {})
    return TriageEvaluation(
        model_version=model.version,
        threshold=model.threshold,
        result=score_detector("Graph engine + ML triage", [Detection(f.rule, frozenset(f.transaction_ids)) for f in kept], dataset),
        alerts_removed=len(findings) - len(kept),
        seed_overlaps_training=dataset.name == "benchmark" and dataset.seed in used,
        recorded={k: metrics.get(k) for k in (
            "episode_level_test_rules_only", "episode_level_test_with_triage", "leave_one_lookalike_out",
            "ablation_with_amount_size_features")},
        caveats=TRIAGE_CAVEATS,
    )


def run_evaluation(dataset: LabelledDataset, config: DetectionConfig | None = None) -> EvaluationReport:
    cfg = config or DetectionConfig()
    # Detectors receive ONLY the transactions. The episodes (answer key) are used afterwards, for scoring.
    findings = run_detection(dataset.transactions, cfg).findings
    graph_dets = [Detection(f.rule, frozenset(f.transaction_ids)) for f in findings]
    triage = _triage_evaluation(dataset, findings, cfg)
    start = time.perf_counter()
    hits = stream_detect(dataset.transactions, cfg)
    elapsed = time.perf_counter() - start

    roles: dict[str, int] = {}
    for e in dataset.episodes:
        roles[e.role] = roles.get(e.role, 0) + 1
    kinds: dict[str, int] = {}
    for e in dataset.episodes:
        if e.role == "positive":
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
    n = max(len(dataset.transactions), 1)
    return EvaluationReport(
        dataset=DatasetSummary(
            name=dataset.name, seed=dataset.seed, transactions=len(dataset.transactions),
            background_transactions=dataset.background_count, episodes_by_role=roles, positives_by_kind=dict(sorted(kinds.items())),
        ),
        graph=score_detector("Graph engine (chain, cycle, burst, fan)", graph_dets, dataset),
        triage=triage,
        baseline=score_detector("Baseline (large transfer, velocity, counterparties)", baseline_detect(dataset.transactions), dataset),
        delay=measure_delay(dataset, hits),
        sweeps=threshold_sweeps(dataset, cfg),
        negative_control=negative_control(dataset, graph_dets, dataset.seed),
        timing=Timing(streaming_seconds=round(elapsed, 3), milliseconds_per_transaction=round(elapsed / n * 1000, 3)),
        caveats=CAVEATS,
    )


class SeedSummary(BaseModel):
    """The same experiment repeated on many random datasets: how much do the numbers wobble?"""

    seeds: list[int]
    metrics: dict[str, dict[str, float]]  # "graph.precision" -> {mean, min, max}


def summarize_seeds(seeds: list[int]) -> SeedSummary:
    series: dict[str, list[float]] = {}
    for seed in seeds:
        data = build_benchmark(seed)
        dets = [Detection(f.rule, frozenset(f.transaction_ids)) for f in run_detection(data.transactions).findings]
        for label, result in (("graph", score_detector("graph", dets, data)), ("baseline", score_detector("baseline", baseline_detect(data.transactions), data))):
            for metric, value in (("precision", result.precision.value), ("recall", result.recall.value), ("f1", result.f1)):
                if value is not None:
                    series.setdefault(f"{label}.{metric}", []).append(value)
    return SeedSummary(
        seeds=seeds,
        metrics={k: {"mean": round(sum(v) / len(v), 4), "min": min(v), "max": max(v)} for k, v in series.items()},
    )


@lru_cache(maxsize=16)
def cached_report(dataset: Literal["benchmark", "simulator"], seed: int, n_events: int) -> EvaluationReport:
    data = build_benchmark(seed) if dataset == "benchmark" else dataset_from_simulator(seed, n_events)
    return run_evaluation(data)


def format_report(r: EvaluationReport) -> str:
    def pct(x: Rate) -> str:
        return f"{x.numerator}/{x.denominator}" + (f" = {x.value:.1%}" if x.value is not None else " = n/a")

    d = r.dataset
    lines = [
        f"Dataset: {d.name} (seed {d.seed}): {d.transactions} transactions, {d.background_transactions} background",
        f"Episodes: {d.episodes_by_role}  planted patterns: {d.positives_by_kind}",
        "",
    ]
    for res in (r.graph, r.baseline):
        c = res.confusion
        lines += [
            f"== {res.name}",
            f"  precision  {pct(res.precision)}  (findings that match a planted pattern / all {res.findings} findings)",
            f"  recall     {pct(res.recall)}  (planted patterns found / planted patterns); lenient (any overlap): {pct(res.recall_lenient)}",
            f"  F1         {res.f1}",
            f"  per pattern: " + ", ".join(f"{k} {pct(v)}" for k, v in res.per_kind_recall.items()),
            f"  confusion over labelled episodes: TP {c.true_positive}  FN {c.false_negative}  FP {c.false_positive}  TN {c.true_negative}",
            f"  false-positive findings {res.false_positive_findings}: {res.false_positives_from_benign_lookalikes} matched benign look-alikes, "
            f"{res.false_positives_from_near_misses} matched near-misses, {res.false_positives_mixed_overlap} touched labelled activity without matching, "
            f"{res.false_positives_background_only} pure background ({res.background_only_findings_per_1000_background} per 1,000 background transactions)",
            f"  benign look-alikes flagged {pct(res.benign_lookalikes_flagged)}; near-misses flagged {pct(res.near_misses_flagged)}",
            "",
        ]
    dl = r.delay
    lines += [
        f"Delay (event time), {dl.detected} patterns found while streaming: median {dl.median_minutes_from_first_transfer} min after the first transfer "
        f"(max {dl.max_minutes_from_first_transfer}); median {dl.median_minutes_after_last_transfer} min after the last transfer; "
        f"flagged before the pattern finished: {pct(dl.flagged_before_pattern_finished)}",
    ]
    if r.triage is not None:
        t = r.triage
        lines += [
            f"== Graph engine + ML triage ({t.model_version}, cut-off {t.threshold:.2f}): {t.alerts_removed} alerts removed",
            f"  precision  {pct(t.result.precision)}   recall {pct(t.result.recall)}   F1 {t.result.f1}",
            *(["  WARNING: this world was used to train or tune the model, so these numbers are optimistic."] if t.seed_overlaps_training else []),
        ]
    for sw in r.sweeps:
        lines.append(f"Sweep {sw.parameter} (default {sw.default:g}):  " + "  ".join(
            f"{p.value:g}->P {p.precision if p.precision is not None else 'n/a'} R {p.recall if p.recall is not None else 'n/a'} ({p.findings} findings)" for p in sw.points))
    lines += [
        f"Negative control recall: {pct(r.negative_control.recall)}  (should be near zero)",
        f"Timing (this machine only): {r.timing.milliseconds_per_transaction} ms per transaction while streaming",
        "",
        "READ THIS: " + r.caveats[0],
    ]
    return "\n".join(lines)
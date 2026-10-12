"""Scoring: compare what a detector reported with the answer key."""
from datetime import datetime
from statistics import median

from pydantic import BaseModel

from app.evaluation.baseline import Detection
from app.evaluation.dataset import Episode, LabelledDataset

MIN_COVERAGE = 0.5  # a finding must contain at least half of the episode's transactions...
MIN_PURITY = 0.5  # ...and at least half of the finding must belong to the episode


class Rate(BaseModel):
    """A fraction with its numerator AND denominator shown, so nobody has to guess what it is a fraction of."""

    numerator: int
    denominator: int
    value: float | None  # None when the denominator is 0 (a rate of "nothing out of nothing" is undefined, not 0)


def rate(numerator: int, denominator: int) -> Rate:
    return Rate(numerator=numerator, denominator=denominator, value=round(numerator / denominator, 4) if denominator else None)


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return 0.0 if precision + recall == 0 else round(2 * precision * recall / (precision + recall), 4)


def matches(detection: Detection, episode: Episode) -> bool:
    if detection.kind != "*" and detection.kind not in episode.accepts:
        return False
    overlap = len(detection.transaction_ids & episode.transaction_ids)
    if overlap == 0:
        return False
    return overlap / len(episode.transaction_ids) >= MIN_COVERAGE and overlap / len(detection.transaction_ids) >= MIN_PURITY


class Confusion(BaseModel):
    """Counted over LABELLED episodes only: planted patterns (positives) and the two kinds of non-pattern."""

    true_positive: int  # planted pattern, flagged
    false_negative: int  # planted pattern, missed
    false_positive: int  # non-pattern episode, flagged
    true_negative: int  # non-pattern episode, left alone


class DetectorResult(BaseModel):
    name: str
    findings: int  # how many alerts an analyst would have to read
    precision: Rate  # findings that match a planted pattern / all findings
    recall: Rate  # planted patterns found / planted patterns (strict matching)
    recall_lenient: Rate  # same, but ANY overlap with the pattern's transactions counts as "found"
    f1: float | None
    per_kind_recall: dict[str, Rate]
    confusion: Confusion
    false_positive_findings: int  # = the four numbers below added up
    false_positives_from_benign_lookalikes: int  # matched a legitimate look-alike
    false_positives_from_near_misses: int  # matched a near-miss
    false_positives_mixed_overlap: int  # touched labelled transactions but matched nothing (e.g. a lone big transfer inside a pattern)
    false_positives_background_only: int  # touched no labelled transaction at all: a pure coincidence in ordinary traffic
    benign_lookalikes_flagged: Rate  # look-alike episodes flagged / look-alike episodes
    near_misses_flagged: Rate
    background_only_findings_per_1000_background: float | None


def score_detector(name: str, detections: list[Detection], dataset: LabelledDataset) -> DetectorResult:
    positives = [e for e in dataset.episodes if e.role == "positive"]
    near = [e for e in dataset.episodes if e.role == "near_miss"]
    benign = [e for e in dataset.episodes if e.role == "benign_lookalike"]

    def flagged(episode: Episode) -> bool:
        return any(matches(d, episode) for d in detections)

    tp_findings = fp_benign = fp_near = fp_mixed = fp_background = 0
    for d in detections:
        if any(matches(d, e) for e in positives):
            tp_findings += 1
        elif any(matches(d, e) for e in benign):
            fp_benign += 1
        elif any(matches(d, e) for e in near):
            fp_near += 1
        elif any(d.transaction_ids & e.transaction_ids for e in dataset.episodes):
            fp_mixed += 1
        else:
            fp_background += 1

    found = [e for e in positives if flagged(e)]
    lenient = [e for e in positives if any(d.transaction_ids & e.transaction_ids for d in detections)]
    precision, recall = rate(tp_findings, len(detections)), rate(len(found), len(positives))
    kinds = sorted({e.kind for e in positives})
    per_kind = {k: rate(sum(1 for e in found if e.kind == k), sum(1 for e in positives if e.kind == k)) for k in kinds}
    wrongly_flagged = sum(flagged(e) for e in near + benign)
    background = dataset.background_count
    return DetectorResult(
        name=name,
        findings=len(detections),
        precision=precision,
        recall=recall,
        recall_lenient=rate(len(lenient), len(positives)),
        f1=f1(precision.value, recall.value),
        per_kind_recall=per_kind,
        confusion=Confusion(
            true_positive=len(found), false_negative=len(positives) - len(found),
            false_positive=wrongly_flagged, true_negative=len(near + benign) - wrongly_flagged,
        ),
        false_positive_findings=len(detections) - tp_findings,
        false_positives_from_benign_lookalikes=fp_benign,
        false_positives_from_near_misses=fp_near,
        false_positives_mixed_overlap=fp_mixed,
        false_positives_background_only=fp_background,
        benign_lookalikes_flagged=rate(sum(flagged(e) for e in benign), len(benign)),
        near_misses_flagged=rate(sum(flagged(e) for e in near), len(near)),
        background_only_findings_per_1000_background=round(fp_background / background * 1000, 2) if background else None,
    )


class StreamHit(BaseModel):
    rule: str
    transaction_ids: list[str]
    detected_at: datetime  # event time of the transaction that triggered it
    arrival_index: int


class DelayStats(BaseModel):
    detected: int  # patterns found while streaming
    median_minutes_from_first_transfer: float | None
    max_minutes_from_first_transfer: float | None
    median_minutes_after_last_transfer: float | None  # negative = flagged BEFORE the pattern finished
    flagged_before_pattern_finished: Rate
    median_by_kind: dict[str, float]


def measure_delay(dataset: LabelledDataset, hits: list[StreamHit]) -> DelayStats:
    """Event-time delay (timestamps, not computer speed): how long after a pattern's first transfer did the alert appear?"""
    from_start: list[float] = []
    after_end: list[float] = []
    by_kind: dict[str, list[float]] = {}
    for e in (e for e in dataset.episodes if e.role == "positive"):
        for h in hits:  # hits are in arrival order, so the first match is the earliest alert
            if matches(Detection(h.rule, frozenset(h.transaction_ids)), e):
                a = (h.detected_at - e.start).total_seconds() / 60
                b = (h.detected_at - e.end).total_seconds() / 60
                from_start.append(a)
                after_end.append(b)
                by_kind.setdefault(e.kind, []).append(a)
                break
    return DelayStats(
        detected=len(from_start),
        median_minutes_from_first_transfer=round(median(from_start), 2) if from_start else None,
        max_minutes_from_first_transfer=round(max(from_start), 2) if from_start else None,
        median_minutes_after_last_transfer=round(median(after_end), 2) if after_end else None,
        flagged_before_pattern_finished=rate(sum(1 for x in after_end if x < 0), len(after_end)),
        median_by_kind={k: round(median(v), 2) for k, v in sorted(by_kind.items())},
    )
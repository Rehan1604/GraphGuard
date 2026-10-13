"""Turn one rule finding into numbers a model can learn from.

The rules say WHAT shape was seen. These features describe HOW the shape looks: how even the
amounts are, how regular the timing is, whether money flows out of one account or into it, and
how much else was happening around the same accounts. Account names and transaction ids are
never used, so the model cannot learn to recognise a particular account.

The same function builds features for training and for live alerts, so the two cannot drift apart."""
from __future__ import annotations

import math
from collections import Counter
from datetime import timedelta
from statistics import mean, median, pstdev

from app.detection.models import Finding
from app.schemas import Transaction

RULES = ("pass_through_chain", "cycle", "burst", "fan")

# Shape-only features: they describe structure and rhythm, not how big the money is.
SHAPE_FEATURES = (
    "is_chain", "is_cycle", "is_burst", "is_fan",
    "rule_points", "n_transactions", "n_accounts", "span_minutes",
    "amount_cv", "amount_min_max_ratio", "amount_near_median_share",
    "gap_mean_minutes", "gap_max_minutes", "gap_cv",
    "ratio_mean", "ratio_min",
    "distinct_sources", "distinct_targets", "top_pair_share", "outward_share",
    "context_other_transactions", "evidence_share_of_activity",
)
# Scale features: they describe how large the amounts are. Useful, but easy to overfit to
# whatever amounts a data generator happens to use, so training reports results with and without.
SCALE_FEATURES = ("log_total_amount", "log_mean_amount", "log_min_amount", "log_max_amount")

FEATURE_SETS = {"shape": SHAPE_FEATURES, "shape_and_scale": SHAPE_FEATURES + SCALE_FEATURES}

LABELS = {
    "is_chain": "pattern is a pass-through chain",
    "is_cycle": "pattern is a circular flow",
    "is_burst": "pattern is a burst",
    "is_fan": "pattern is many counterparties",
    "rule_points": "rule risk points",
    "n_transactions": "number of transfers",
    "n_accounts": "number of accounts",
    "span_minutes": "minutes from first to last transfer",
    "amount_cv": "variation between amounts",
    "amount_min_max_ratio": "smallest amount relative to largest",
    "amount_near_median_share": "share of amounts close to the typical amount",
    "gap_mean_minutes": "average minutes between transfers",
    "gap_max_minutes": "longest pause between transfers",
    "gap_cv": "irregularity of timing",
    "ratio_mean": "how much each transfer passes on (average)",
    "ratio_min": "how much each transfer passes on (weakest hop)",
    "distinct_sources": "different sending accounts",
    "distinct_targets": "different receiving accounts",
    "top_pair_share": "share of transfers between the busiest pair",
    "outward_share": "share of transfers leaving the focus account",
    "context_other_transactions": "other activity around these accounts",
    "evidence_share_of_activity": "share of nearby activity that is this pattern",
    "log_total_amount": "total amount (log scale)",
    "log_mean_amount": "average amount (log scale)",
    "log_min_amount": "smallest amount (log scale)",
    "log_max_amount": "largest amount (log scale)",
}


def _cv(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return pstdev(values) / m if m else 0.0


def extract_features(
    finding: Finding, evidence: list[Transaction], context: list[Transaction], lookback_minutes: int
) -> dict[str, float]:
    """`evidence` = the finding's own transactions. `context` = transactions known at that time
    (anything is fine; only those near these accounts, inside the look-back window, are used)."""
    ev = sorted(evidence, key=lambda t: (t.timestamp, t.id))
    n = len(ev)
    amounts = [float(t.amount) for t in ev] or [0.0]
    times = [t.timestamp for t in ev]
    start, end = (times[0], times[-1]) if ev else (finding.window_start, finding.window_end)

    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])] or [0.0]
    ratios = [min(max(b / a, 0.0), 5.0) for a, b in zip(amounts, amounts[1:]) if a > 0] or [1.0]
    med = median(amounts)
    near_median = sum(1 for a in amounts if med and abs(a - med) <= 0.1 * med) / max(n, 1)

    pairs = Counter((t.source_account_id, t.target_account_id) for t in ev)
    focus = finding.accounts[0] if finding.accounts else ""
    evidence_ids = {t.id for t in ev}
    accounts = set(finding.accounts)
    horizon = start - timedelta(minutes=lookback_minutes)
    others = sum(
        1 for t in context
        if t.id not in evidence_ids and horizon <= t.timestamp <= end
        and (t.source_account_id in accounts or t.target_account_id in accounts)
    )

    row = {
        **{f"is_{name}": float(finding.rule == rule) for name, rule in
           (("chain", "pass_through_chain"), ("cycle", "cycle"), ("burst", "burst"), ("fan", "fan"))},
        "rule_points": float(finding.risk_score),
        "n_transactions": float(n),
        "n_accounts": float(len(accounts)),
        "span_minutes": (end - start).total_seconds() / 60,
        "amount_cv": _cv(amounts),
        "amount_min_max_ratio": min(amounts) / max(amounts) if max(amounts) else 0.0,
        "amount_near_median_share": near_median,
        "gap_mean_minutes": mean(gaps),
        "gap_max_minutes": max(gaps),
        "gap_cv": _cv(gaps),
        "ratio_mean": mean(ratios),
        "ratio_min": min(ratios),
        "distinct_sources": float(len({t.source_account_id for t in ev})),
        "distinct_targets": float(len({t.target_account_id for t in ev})),
        "top_pair_share": (max(pairs.values()) / n) if n else 0.0,
        "outward_share": (sum(1 for t in ev if t.source_account_id == focus) / n) if n else 0.0,
        "context_other_transactions": float(others),
        "evidence_share_of_activity": n / (n + others) if n + others else 0.0,
        "log_total_amount": math.log10(sum(amounts) + 1),
        "log_mean_amount": math.log10(mean(amounts) + 1),
        "log_min_amount": math.log10(min(amounts) + 1),
        "log_max_amount": math.log10(max(amounts) + 1),
    }
    return row


def to_vector(row: dict[str, float], names: tuple[str, ...]) -> list[float]:
    return [row[name] for name in names]

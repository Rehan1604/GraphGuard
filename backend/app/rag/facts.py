"""Verified facts about an alert, computed from its stored transactions. No AI involved."""
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

from app.alerts.models import AlertDetail
from app.rag.models import Fact
from app.schemas import Transaction

RULE_LABELS = {
    "pass_through_chain": "Pass-through chain",
    "cycle": "Circular flow",
    "burst": "Transfer burst",
    "fan": "Many counterparties",
}
MAX_LISTED_TRANSFERS = 8


def _time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _money(amount: Decimal, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def _total(txs: list[Transaction]) -> str:
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for t in txs:
        sums[t.currency] += t.amount
    return " + ".join(_money(v, c) for c, v in sorted(sums.items())) or "0.00"


def _minutes(a: datetime, b: datetime) -> int:
    return round(abs((b - a).total_seconds()) / 60)


def build_facts(detail: AlertDetail, name: Callable[[str], str] = lambda a: a) -> list[Fact]:
    """`name` lets the caller swap real account ids for aliases. Fact ids and structure never change."""
    ev = sorted(detail.evidence, key=lambda t: (t.timestamp, t.id))
    facts: list[Fact] = []

    def add(text: str, kind: str) -> None:
        facts.append(Fact(id=f"F{len(facts) + 1}", text=text, kind=kind))  # type: ignore[arg-type]

    add(
        f"Rule: {RULE_LABELS.get(detail.rule, detail.rule)}. Risk score {detail.risk_score}/100, priority "
        f"{detail.priority}. The score is the sum of the rule's points, not a probability of fraud.",
        "summary",
    )
    if detail.ml_score is not None:
        reasons = "; ".join(f"{d.label} {d.direction} the estimate" for d in detail.ml_drivers[:3])
        verdict = "likely a genuine pattern" if detail.ml_verdict == "likely_true" else "likely a benign look-alike or coincidence"
        add(
            f"ML triage model {detail.ml_model} estimates a {detail.ml_score:.0%} likelihood that this alert matches a genuine "
            f"pattern (verdict: {verdict})." + (f" Main drivers: {reasons}." if reasons else "")
            + " The estimate is calibrated on synthetic benchmark data; it ranks alerts for review and is not a probability of wrongdoing.",
            "triage",
        )
    if ev:
        accounts = {a for t in ev for a in (t.source_account_id, t.target_account_id)}
        add(
            f"{len(ev)} transactions between {_time(ev[0].timestamp)} and {_time(ev[-1].timestamp)} "
            f"({_minutes(ev[0].timestamp, ev[-1].timestamp)} minutes), involving {len(accounts)} accounts, "
            f"{_total(ev)} in total.",
            "evidence",
        )

    if detail.rule in ("pass_through_chain", "cycle"):
        _path_facts(detail, ev, name, add)
    elif detail.rule in ("burst", "fan") and detail.accounts:
        _focus_facts(detail, ev, name, add)

    for c in detail.contributions:
        add(f"Score contribution +{c.points}: {c.reason}.", "score")
    return facts


def _path_facts(detail, ev, name, add) -> None:
    path = detail.accounts
    if detail.rule == "cycle" and path:
        add(f"Loop: {' -> '.join(name(a) for a in path + [path[0]])}.", "evidence")

    by_pair: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for t in ev:
        by_pair[(t.source_account_id, t.target_account_id)].append(t)

    ordered: list[Transaction] = []
    n_hops = len(path) if detail.rule == "cycle" else len(path) - 1
    for i in range(max(n_hops, 0)):
        pair = (path[i], path[(i + 1) % len(path)])
        if by_pair.get(pair):
            ordered.append(by_pair[pair].pop(0))

    for i, t in enumerate(ordered[:MAX_LISTED_TRANSFERS]):
        text = f"Transfer {i + 1}: {name(t.source_account_id)} sent {_money(t.amount, t.currency)} to {name(t.target_account_id)} at {_time(t.timestamp)}"
        if detail.rule == "pass_through_chain" and i > 0:
            prev = ordered[i - 1]
            share = t.amount / prev.amount * 100 if prev.amount else Decimal(0)
            text += (
                f", {_minutes(prev.timestamp, t.timestamp)} minutes after {name(t.source_account_id)} received "
                f"{_money(prev.amount, prev.currency)}, forwarding {share:.1f}% of it"
            )
        add(text + ".", "evidence")
    if len(ordered) > MAX_LISTED_TRANSFERS:
        add(f"{len(ordered) - MAX_LISTED_TRANSFERS} further transfers are not listed here.", "evidence")

    if detail.rule == "cycle" and ordered:
        low, high = min(t.amount for t in ordered), max(t.amount for t in ordered)
        share = low / high * 100 if high else Decimal(0)
        add(
            f"Amounts around the loop range from {_money(low, ordered[0].currency)} to "
            f"{_money(high, ordered[0].currency)} (the smallest is {share:.1f}% of the largest).",
            "evidence",
        )


def _focus_facts(detail, ev, name, add) -> None:
    focus = detail.accounts[0]
    sent = [t for t in ev if t.source_account_id == focus]
    received = [t for t in ev if t.target_account_id == focus]
    others = sorted({t.target_account_id if t.source_account_id == focus else t.source_account_id for t in ev})
    shown = ", ".join(name(a) for a in others[:5]) + (f" and {len(others) - 5} more" if len(others) > 5 else "")
    add(f"Account in focus: {name(focus)}. It sent {len(sent)} and received {len(received)} of these transactions.", "evidence")
    add(f"{name(focus)} dealt with {len(others)} distinct counterparties: {shown}.", "evidence")
    add(f"Total sent by {name(focus)}: {_total(sent)}. Total received: {_total(received)}.", "evidence")
    if ev:
        low, high = min(ev, key=lambda t: t.amount), max(ev, key=lambda t: t.amount)
        add(f"Individual amounts range from {_money(low.amount, low.currency)} to {_money(high.amount, high.currency)}.", "evidence")
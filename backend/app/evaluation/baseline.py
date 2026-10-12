"""The simple detector we compare against: it only counts things about single transactions and single
accounts. It cannot follow money across several accounts, so it has no idea what a chain or a loop is."""
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

from app.schemas import Transaction

LARGE_TRANSFER_THRESHOLD = Decimal("5000.00")  # an arbitrary round number: the usual "flag big payments" rule
VELOCITY_WINDOW_MIN, VELOCITY_MIN_TX = 10, 6
COUNTERPARTY_WINDOW_MIN, COUNTERPARTY_MIN = 10, 5


@dataclass(frozen=True)
class Detection:
    """Anything a detector reports. `kind` is the pattern it claims, or "*" for 'something is odd'."""

    kind: str
    transaction_ids: frozenset[str]


def large_transfers(txs: list[Transaction]) -> list[Detection]:
    return [Detection("*", frozenset([t.id])) for t in txs if t.amount >= LARGE_TRANSFER_THRESHOLD]


def _per_account(txs: list[Transaction]) -> dict[str, list[Transaction]]:
    out: dict[str, list[Transaction]] = {}
    for t in sorted(txs, key=lambda t: (t.timestamp, t.id)):
        out.setdefault(t.source_account_id, []).append(t)
        out.setdefault(t.target_account_id, []).append(t)
    return out


def _windows(history: list[Transaction], minutes: int, qualifies) -> list[list[Transaction]]:
    times = [t.timestamp.timestamp() for t in history]
    found, i = [], 0
    while i < len(history):
        j = bisect_right(times, times[i] + minutes * 60) - 1
        chunk = history[i : j + 1]
        if qualifies(chunk):
            found.append(chunk)
            i = j + 1
        else:
            i += 1
    return found


def velocity(txs: list[Transaction]) -> list[Detection]:
    """Too many transactions on one account in a short time."""
    out = []
    for history in _per_account(txs).values():
        for chunk in _windows(history, VELOCITY_WINDOW_MIN, lambda c: len(c) >= VELOCITY_MIN_TX):
            out.append(Detection("burst", frozenset(t.id for t in chunk)))
    return out


def counterparties(txs: list[Transaction]) -> list[Detection]:
    """Too many different accounts dealing with one account in a short time."""
    out = []
    for account, history in _per_account(txs).items():
        def crowd(chunk, account=account):
            return len({t.target_account_id if t.source_account_id == account else t.source_account_id for t in chunk}) >= COUNTERPARTY_MIN

        for chunk in _windows(history, COUNTERPARTY_WINDOW_MIN, crowd):
            out.append(Detection("fan", frozenset(t.id for t in chunk)))
    return out


def baseline_detect(txs: list[Transaction]) -> list[Detection]:
    return large_transfers(txs) + velocity(txs) + counterparties(txs)
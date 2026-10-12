from bisect import bisect_right
from decimal import Decimal

from app.detection.graph import TransactionGraph
from app.detection.models import DetectionConfig, Finding, ScoreContribution, build_finding
from app.schemas import Transaction

NEAR_FULL_FORWARD = Decimal("0.95")  # "forwarded almost everything"
SIMILAR_AMOUNTS = Decimal("0.9")  # smallest/largest amount ratio counted as "similar"


def _minutes(td_seconds: float) -> int:
    return round(td_seconds / 60)

def _one_per_route(routes: list[list[Transaction]], key_of, window_seconds: float) -> list[list[Transaction]]:
    """Several parallel transfers between the same two accounts make many different transaction sets that
    trace the SAME route. Keep one per route per time window: the earliest combination, so the choice does
    not change when later transfers arrive. (Found by the evaluation: one loop was reported 7 times.)"""
    ordered = sorted(routes, key=lambda r: (tuple(t.timestamp for t in r), tuple(t.id for t in r)))
    last_start: dict = {}
    kept = []
    for route in ordered:
        key = key_of(route)
        previous = last_start.get(key)
        if previous is not None and (route[0].timestamp - previous).total_seconds() < window_seconds:
            continue
        last_start[key] = route[0].timestamp
        kept.append(route)
    return kept


def _loop_key(cycle: list[Transaction]) -> tuple[str, ...]:
    """The accounts of a loop, rotated so the same loop always gives the same key whichever transfer came first."""
    accounts = [t.source_account_id for t in cycle]
    i = accounts.index(min(accounts))
    return tuple(accounts[i:] + accounts[:i])

# --------------------------------------------------------------------------
# Rule 1: pass-through chains  (A -> B -> C -> D, money keeps moving quickly)
# --------------------------------------------------------------------------
def find_pass_through_chains(tg: TransactionGraph, cfg: DetectionConfig) -> list[Finding]:
    window = cfg.chain_hop_window_minutes * 60

    def valid_next_hops(prev: Transaction) -> list[Transaction]:
        start = prev.timestamp.timestamp()
        candidates = tg.outgoing_between(prev.target_account_id, start, start + window)
        # forwards between ratio*incoming and the full incoming amount
        return [n for n in candidates if prev.amount * cfg.pass_through_ratio <= n.amount <= prev.amount]

    chains: list[list[Transaction]] = []

    def extend(path: list[Transaction], seen_accounts: set[str]) -> None:
        extended = False
        if len(path) < cfg.max_chain_hops:
            for nxt in valid_next_hops(path[-1]):
                if nxt.target_account_id in seen_accounts:
                    continue  # no loops here; loops belong to the cycle rule
                extended = True
                extend(path + [nxt], seen_accounts | {nxt.target_account_id})
        if not extended and len(path) >= cfg.min_chain_hops:
            chains.append(path)

    for tx in tg.transactions:
        extend([tx], {tx.source_account_id, tx.target_account_id})

    # Keep only the longest version of each chain (drop pieces of bigger chains)
    id_lists = [[t.id for t in c] for c in chains]

    def is_piece_of_bigger(ids: list[str]) -> bool:
        for other in id_lists:
            if len(other) > len(ids) and any(
                other[i : i + len(ids)] == ids for i in range(len(other) - len(ids) + 1)
            ):
                return True
        return False

    maximal = [c for c in chains if not is_piece_of_bigger([t.id for t in c])]
    route_of = lambda c: (c[0].source_account_id, *(t.target_account_id for t in c))  # noqa: E731
    findings = []
    for chain in _one_per_route(maximal, route_of, window * cfg.max_chain_hops):
        hops = len(chain)
        accounts = [chain[0].source_account_id] + [t.target_account_id for t in chain]
        span = (chain[-1].timestamp - chain[0].timestamp).total_seconds()
        contributions = [
            ScoreContribution(
                reason=f"Money passed through {hops} transfers across {len(accounts)} accounts",
                points=30,
            )
        ]
        extra = min(hops - cfg.min_chain_hops, 3)
        if extra > 0:
            contributions.append(ScoreContribution(reason=f"{extra} hop(s) beyond the minimum", points=10 * extra))
        if all(chain[i + 1].amount >= chain[i].amount * NEAR_FULL_FORWARD for i in range(hops - 1)):
            contributions.append(
                ScoreContribution(reason="Every hop forwarded at least 95% of what came in", points=10)
            )
        if span <= window:
            contributions.append(
                ScoreContribution(
                    reason=f"Whole chain finished within {cfg.chain_hop_window_minutes} minutes", points=10
                )
            )
        findings.append(
            build_finding(
                "pass_through_chain",
                accounts,
                chain,
                contributions,
                f"Money moved {' -> '.join(accounts)} in {_minutes(span)} minutes, "
                f"each hop forwarding at least {cfg.pass_through_ratio:.0%} of what arrived.",
            )
        )
    return findings


# --------------------------------------------------------------------------
# Rule 2: cycles  (A -> B -> C -> A, money returns to where it started)
# --------------------------------------------------------------------------
def find_cycles(tg: TransactionGraph, cfg: DetectionConfig) -> list[Finding]:
    window = cfg.cycle_window_minutes * 60
    found: dict[frozenset[str], list[Transaction]] = {}

    for start in tg.transactions:
        t0 = start.timestamp.timestamp()
        origin = start.source_account_id

        def dfs(path: list[Transaction], visited: set[str]) -> None:
            last = path[-1]
            for nxt in tg.outgoing_between(last.target_account_id, last.timestamp.timestamp(), t0 + window):
                if nxt.target_account_id == origin:
                    if len(path) + 1 >= cfg.min_cycle_length:
                        cycle = path + [nxt]
                        found.setdefault(frozenset(t.id for t in cycle), cycle)
                elif nxt.target_account_id not in visited and len(path) + 1 < cfg.max_cycle_length:
                    dfs(path + [nxt], visited | {nxt.target_account_id})

        dfs([start], {origin, start.target_account_id})

    findings = []
    for cycle in _one_per_route(list(found.values()), _loop_key, window):
        accounts = [t.source_account_id for t in cycle]
        span = (cycle[-1].timestamp - cycle[0].timestamp).total_seconds()
        amounts = [t.amount for t in cycle]
        contributions = [
            ScoreContribution(
                reason=f"Money returned to its starting account after {len(cycle)} transfers", points=45
            )
        ]
        if min(amounts) / max(amounts) >= SIMILAR_AMOUNTS:
            contributions.append(
                ScoreContribution(reason="Amounts around the loop are within 10% of each other", points=15)
            )
        if span <= window / 4:
            contributions.append(
                ScoreContribution(reason="Loop completed in under a quarter of the allowed window", points=10)
            )
        findings.append(
            build_finding(
                "cycle",
                accounts,
                cycle,
                contributions,
                f"Money looped {' -> '.join(accounts + [accounts[0]])} in {_minutes(span)} minutes.",
            )
        )
    return findings


# --------------------------------------------------------------------------
# Rules 3 and 4: bursts and many-counterparty accounts (sliding time window)
# --------------------------------------------------------------------------
def _counterparty(account: str, tx: Transaction) -> str:
    return tx.target_account_id if tx.source_account_id == account else tx.source_account_id


def _greedy_windows(account: str, tg: TransactionGraph, window: float, qualifies) -> list[list[Transaction]]:
    """Slide a time window along the account's history. When a window qualifies,
    record it and jump past it so one episode is reported once."""
    index = tg.touching(account)
    n, i, results = len(index.txs), 0, []
    while i < n:
        j = bisect_right(index.times, index.times[i] + window) - 1
        chunk = index.txs[i : j + 1]
        if qualifies(chunk):
            results.append(chunk)
            i = j + 1
        else:
            i += 1
    return results


def find_bursts(tg: TransactionGraph, cfg: DetectionConfig) -> list[Finding]:
    window = cfg.burst_window_minutes * 60
    findings = []
    for account in tg.accounts:
        for chunk in _greedy_windows(account, tg, window, lambda c: len(c) >= cfg.burst_min_transactions):
            extra = len(chunk) - cfg.burst_min_transactions
            contributions = [
                ScoreContribution(
                    reason=f"{len(chunk)} transactions within {cfg.burst_window_minutes} minutes "
                    f"(threshold {cfg.burst_min_transactions})",
                    points=20,
                )
            ]
            if extra > 0:
                contributions.append(
                    ScoreContribution(reason=f"{extra} transaction(s) above the threshold", points=min(5 * extra, 30))
                )
            others = sorted({_counterparty(account, t) for t in chunk})
            findings.append(
                build_finding(
                    "burst",
                    [account] + others,
                    chunk,
                    contributions,
                    f"{account} was involved in {len(chunk)} transactions within {cfg.burst_window_minutes} minutes.",
                )
            )
    return findings


def find_fans(tg: TransactionGraph, cfg: DetectionConfig) -> list[Finding]:
    window = cfg.burst_window_minutes * 60
    findings = []
    for account in tg.accounts:

        def qualifies(chunk, account=account):
            return len({_counterparty(account, t) for t in chunk}) >= cfg.fan_min_counterparties

        for chunk in _greedy_windows(account, tg, window, qualifies):
            others = sorted({_counterparty(account, t) for t in chunk})
            extra = len(others) - cfg.fan_min_counterparties
            contributions = [
                ScoreContribution(
                    reason=f"{len(others)} different counterparties within {cfg.burst_window_minutes} minutes "
                    f"(threshold {cfg.fan_min_counterparties})",
                    points=20,
                )
            ]
            if extra > 0:
                contributions.append(
                    ScoreContribution(reason=f"{extra} counterparty(ies) above the threshold", points=min(5 * extra, 30))
                )
            findings.append(
                build_finding(
                    "fan",
                    [account] + others,
                    chunk,
                    contributions,
                    f"{account} dealt with {len(others)} different accounts within {cfg.burst_window_minutes} minutes.",
                )
            )
    return findings
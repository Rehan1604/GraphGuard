"""Labelled synthetic datasets. The labels (the "answer key") live in `episodes`,
completely separate from the transactions that detectors are allowed to see."""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from app.schemas import Transaction
from app.simulation.generator import EventGenerator

Role = Literal["positive", "near_miss", "benign_lookalike"]
T0 = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Episode:
    """One labelled stretch of activity."""

    name: str  # e.g. "chain", "slow_chain", "payroll"
    kind: str  # the pattern it is, or resembles
    role: Role  # positive = a planted pattern; the others are NOT patterns to find
    accepts: tuple[str, ...]  # detector rule names that count as "seeing" it
    transaction_ids: frozenset[str]
    start: datetime
    end: datetime


@dataclass(frozen=True)
class LabelledDataset:
    name: str
    seed: int
    transactions: list[Transaction]  # what the detectors get
    episodes: list[Episode]  # the answer key (never given to detectors)

    @property
    def background_count(self) -> int:
        labelled = set().union(*(e.transaction_ids for e in self.episodes)) if self.episodes else set()
        return len(self.transactions) - len(labelled)


@dataclass(frozen=True)
class BenchmarkConfig:
    n_accounts: int = 80
    hours: int = 48
    n_background: int = 700
    n_chain: int = 10
    n_cycle: int = 10
    n_burst: int = 10
    n_fan: int = 10
    n_near_miss_each: int = 4  # six kinds of near-miss
    n_benign_each: int = 4  # three kinds of benign look-alike


Raw = list[tuple[float, str, str, int]]  # (seconds from the episode's start, source, target, cents)


def _chain(rng, accounts, hops=(3, 5), gap=(2, 12), ratio=(0.90, 0.99), amount=(100_000, 9_000_000)) -> Raw:
    n = rng.randint(*hops)
    accs = rng.sample(accounts, n + 1)
    cents, t, out = rng.randint(*amount), 0.0, []
    for i in range(n):
        out.append((t, accs[i], accs[i + 1], cents))
        cents = max(int(cents * rng.uniform(*ratio)), 1)
        t += rng.uniform(*gap) * 60
    return out


def _cycle(rng, accounts, n=(3, 4), gap=(5, 20), amount=(100_000, 9_000_000)) -> Raw:
    k = rng.randint(*n)
    accs = rng.sample(accounts, k)
    base, t, out = rng.randint(*amount), 0.0, []
    for i in range(k):
        out.append((t, accs[i], accs[(i + 1) % k], max(int(base * rng.uniform(0.97, 1.0)), 1)))
        t += rng.uniform(*gap) * 60
    return out


def _burst(rng, accounts, k=(6, 9), span=270, amount=(2_000, 12_000)) -> Raw:
    src, dst = rng.sample(accounts, 2)
    return [(rng.uniform(0, span), src, dst, rng.randint(*amount)) for _ in range(rng.randint(*k))]


def _fan(rng, accounts, n=(5, 7), span=360, amount=(5_000, 40_000), outward=False) -> Raw:
    picks = rng.sample(accounts, rng.randint(*n) + 1)
    hub, others = picks[0], picks[1:]
    return [
        (rng.uniform(0, span), hub, o, rng.randint(*amount)) if outward else (rng.uniform(0, span), o, hub, rng.randint(*amount))
        for o in others
    ]


def build_benchmark(seed: int = 42, cfg: BenchmarkConfig = BenchmarkConfig()) -> LabelledDataset:
    """A designed test: planted patterns, near-misses just outside our own thresholds, and benign
    look-alikes that legitimately resemble a pattern. Everything is generated from the seed."""
    rng = random.Random(seed)
    accounts = [f"EV-A{n:03d}" for n in range(1, cfg.n_accounts + 1)]
    horizon = cfg.hours * 3600
    raw: list[tuple[datetime, str, str, int, int | None]] = []
    meta: list[tuple[str, str, Role, tuple[str, ...]]] = []

    def plant(name: str, kind: str, role: Role, accepts: tuple[str, ...], events: Raw) -> None:
        idx = len(meta)
        meta.append((name, kind, role, accepts))
        start = rng.uniform(0, horizon - 4 * 3600)
        for offset, src, dst, cents in events:
            raw.append((T0 + timedelta(seconds=int(start + offset)), src, dst, cents, idx))

    for _ in range(cfg.n_chain):
        plant("chain", "pass_through_chain", "positive", ("pass_through_chain",), _chain(rng, accounts))
    for _ in range(cfg.n_cycle):
        plant("cycle", "cycle", "positive", ("cycle",), _cycle(rng, accounts))
    for _ in range(cfg.n_burst):
        plant("burst", "burst", "positive", ("burst",), _burst(rng, accounts))
    for _ in range(cfg.n_fan):  # a crowd of 6+ senders is also a burst by definition, so both rules count
        plant("fan", "fan", "positive", ("fan", "burst"), _fan(rng, accounts))

    chain_k, cycle_k, burst_k, fan_k = "pass_through_chain", "cycle", "burst", "fan"
    near_misses = [
        ("slow_chain", chain_k, lambda: _chain(rng, accounts, hops=(3, 3), gap=(90, 150))),
        ("leaky_chain", chain_k, lambda: _chain(rng, accounts, hops=(3, 3), gap=(3, 10), ratio=(0.2, 0.5))),
        ("short_chain", chain_k, lambda: _chain(rng, accounts, hops=(2, 2), gap=(3, 10))),
        ("slow_loop", cycle_k, lambda: _cycle(rng, accounts, n=(3, 3), gap=(90, 120))),
        ("near_burst", burst_k, lambda: _burst(rng, accounts, k=(5, 5), span=240)),
        ("near_fan", fan_k, lambda: _fan(rng, accounts, n=(4, 4), span=300)),
    ]
    for name, kind, make in near_misses:
        for _ in range(cfg.n_near_miss_each):
            plant(name, kind, "near_miss", (kind,), make())

    benign = [
        ("payroll", fan_k, ("fan", "burst"), lambda: _fan(rng, accounts, n=(7, 9), span=240, amount=(100_000, 300_000), outward=True)),
        ("split_bill", cycle_k, (cycle_k,), lambda: _cycle(rng, accounts, n=(3, 3), gap=(8, 15), amount=(2_000, 8_000))),
        ("marketplace_payout", chain_k, (chain_k,), lambda: _chain(rng, accounts, hops=(3, 3), gap=(4, 10), ratio=(0.90, 0.97), amount=(5_000, 50_000))),
    ]
    for name, kind, accepts, make in benign:
        for _ in range(cfg.n_benign_each):
            plant(name, kind, "benign_lookalike", accepts, make())

    for _ in range(cfg.n_background):  # ordinary traffic: random pairs, random amounts
        src, dst = rng.sample(accounts, 2)
        raw.append((T0 + timedelta(seconds=int(rng.uniform(0, horizon))), src, dst, rng.randint(1_000, 500_000), None))

    # Opaque ids, assigned in time order, so an id reveals nothing about which episode a transaction belongs to.
    raw.sort(key=lambda r: (r[0], rng.random()))
    transactions, members = [], {}
    for n, (ts, src, dst, cents, idx) in enumerate(raw, start=1):
        tx_id = f"EV-TX-{n:06d}"
        transactions.append(Transaction(
            id=tx_id, source_account_id=src, target_account_id=dst, amount=Decimal(cents).scaleb(-2),
            currency="USD", timestamp=ts, ingested_at=ts,
        ))
        if idx is not None:
            members.setdefault(idx, []).append((ts, tx_id))

    episodes = [
        Episode(name=name, kind=kind, role=role, accepts=accepts,
                transaction_ids=frozenset(i for _, i in members[idx]),
                start=min(t for t, _ in members[idx]), end=max(t for t, _ in members[idx]))
        for idx, (name, kind, role, accepts) in enumerate(meta)
    ]
    return LabelledDataset(name="benchmark", seed=seed, transactions=transactions, episodes=episodes)


def dataset_from_simulator(seed: int = 42, n_events: int = 240) -> LabelledDataset:
    """The live simulator's own stream, with its recorded ground truth. No near-misses, no look-alikes."""
    gen = EventGenerator(seed=seed, duplicate_rate=0)
    created = [gen.next_event().tx for _ in range(n_events)]
    transactions = [
        Transaction(**t.model_dump(), ingested_at=t.timestamp) for t in created
    ]
    by_id = {t.id: t for t in transactions}
    episodes = []
    for kind, ids in gen.planted:
        if not all(i in by_id for i in ids):
            continue  # the stream stopped before this pattern finished: leave it out
        times = [by_id[i].timestamp for i in ids]
        accepts = ("fan", "burst") if kind == "fan" else ("pass_through_chain",) if kind == "chain" else (kind,)
        episodes.append(Episode(name=kind, kind="pass_through_chain" if kind == "chain" else kind, role="positive",
                                accepts=accepts, transaction_ids=frozenset(ids), start=min(times), end=max(times)))
    return LabelledDataset(name="simulator", seed=seed, transactions=transactions, episodes=episodes)
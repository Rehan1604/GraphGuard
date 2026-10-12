"""Makes fake-but-realistic transaction events, deterministically.
Same seed -> exactly the same stream. No network, no database, no asyncio."""
import heapq
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.schemas import AccountCreate, TransactionCreate

SIM_PREFIX = "SIM-"  # everything the simulator creates starts with this, so reset can find it


@dataclass(frozen=True)
class GeneratedEvent:
    tx: TransactionCreate
    is_replay: bool  # True = the same event delivered a second time


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2)


class EventGenerator:
    def __init__(
        self,
        seed: int = 42,
        n_accounts: int = 40,
        scenario_probability: float = 0.06,
        duplicate_rate: float = 0.05,
        start: datetime | None = None,
    ):
        self.rng = random.Random(seed)
        self.scenario_probability = scenario_probability
        self.duplicate_rate = duplicate_rate
        self.accounts = [f"{SIM_PREFIX}A{n:02d}" for n in range(1, n_accounts + 1)]
        self.sim_time = start or datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
        self._next_background = self.sim_time
        self._heap: list[tuple[datetime, int, TransactionCreate]] = []
        self._counter = 0
        self._last: TransactionCreate | None = None
        self.planted: list[tuple[str, list[str]]] = []

    def account_specs(self) -> list[AccountCreate]:
        return [
            AccountCreate(
                id=acc,
                name=f"Simulated account {i + 1}",
                account_type="business" if (i + 1) % 4 == 0 else "individual",
            )
            for i, acc in enumerate(self.accounts)
        ]

    # ---- scheduling: events wait in a time-ordered queue --------------------
    def _push(self, when: datetime, src: str, dst: str, cents: int) -> None:
        self._counter += 1
        tx = TransactionCreate(
            id=f"{SIM_PREFIX}TX-{self._counter:06d}",
            source_account_id=src,
            target_account_id=dst,
            amount=_money(cents),
            timestamp=when,
        )
        heapq.heappush(self._heap, (when, self._counter, tx))

    def _push_background(self) -> None:
        src, dst = self.rng.sample(self.accounts, 2)
        self._push(self._next_background, src, dst, self.rng.randint(1_000, 500_000))
        self._next_background += timedelta(seconds=self.rng.randint(60, 600))

    def _schedule_scenario(self) -> None:
        kind = self.rng.choice(["chain", "cycle", "burst", "fan"])
        start = self.sim_time + timedelta(seconds=self.rng.randint(1, 30))
        before = self._counter
        getattr(self, f"_scenario_{kind}")(start)
        self.planted.append((kind, [f"{SIM_PREFIX}TX-{n:06d}" for n in range(before + 1, self._counter + 1)]))

    def _scenario_chain(self, start: datetime) -> None:
        hops = self.rng.randint(3, 5)
        accs = self.rng.sample(self.accounts, hops + 1)
        cents, when = self.rng.randint(100_000, 9_000_000), start
        for i in range(hops):
            self._push(when, accs[i], accs[i + 1], cents)
            cents = int(cents * self.rng.uniform(0.90, 0.99))
            when += timedelta(minutes=self.rng.randint(2, 12))

    def _scenario_cycle(self, start: datetime) -> None:
        n = self.rng.randint(3, 4)
        accs = self.rng.sample(self.accounts, n)
        base, when = self.rng.randint(100_000, 9_000_000), start
        for i in range(n):
            self._push(when, accs[i], accs[(i + 1) % n], int(base * self.rng.uniform(0.97, 1.0)))
            when += timedelta(minutes=self.rng.randint(5, 20))

    def _scenario_burst(self, start: datetime) -> None:
        src, dst = self.rng.sample(self.accounts, 2)
        for _ in range(self.rng.randint(6, 9)):
            when = start + timedelta(seconds=self.rng.randint(0, 270))
            self._push(when, src, dst, self.rng.randint(2_000, 12_000))

    def _scenario_fan(self, start: datetime) -> None:
        picks = self.rng.sample(self.accounts, self.rng.randint(6, 8))
        target, sources = picks[0], picks[1:]
        for src in sources:
            when = start + timedelta(seconds=self.rng.randint(0, 360))
            self._push(when, src, target, self.rng.randint(5_000, 40_000))

    # ---- the one method callers use -----------------------------------------
    def next_event(self) -> GeneratedEvent:
        # Sometimes deliver the previous event again (like a network retry).
        if self._last is not None and self.rng.random() < self.duplicate_rate:
            return GeneratedEvent(self._last, True)
        if self.rng.random() < self.scenario_probability:
            self._schedule_scenario()
        # Make sure an ordinary event is queued before anything that happens later.
        while not self._heap or self._next_background <= self._heap[0][0]:
            self._push_background()
        when, _, tx = heapq.heappop(self._heap)  # always the earliest waiting event
        self.sim_time = when
        self._last = tx
        return GeneratedEvent(tx, False)
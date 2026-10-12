import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from app.realtime import EventHub
from app.simulation.generator import EventGenerator
from app.simulation.ingest import ensure_sim_accounts, ingest_event, reset_simulated_data

log = logging.getLogger("graphguard.simulation")
MAX_CONSECUTIVE_FAILURES = 5


class SimulationStateError(Exception):
    pass


class Simulator:
    """Runs the generator in the background and publishes what happens.
    Status flow: stopped -> running <-> paused;  reset -> stopped;  5 failures in a row -> error."""

    def __init__(self, hub: EventHub, db_path_provider: Callable[[], Path]):
        self.hub = hub
        self._db_path = db_path_provider
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._gate = asyncio.Event()  # set = allowed to run, cleared = paused
        self.generator: EventGenerator | None = None
        self._clear_counters()

    def _clear_counters(self) -> None:
        self.status = "stopped"
        self.events_emitted = 0
        self.transactions_created = 0
        self.duplicates_ignored = 0
        self.errors = 0
        self.events_per_second = 0.0
        self.seed: int | None = None
        self.duplicate_rate = 0.0
        self.generator = None

    def state(self) -> dict:
        return {
            "status": self.status,
            "events_emitted": self.events_emitted,
            "transactions_created": self.transactions_created,
            "duplicates_ignored": self.duplicates_ignored,
            "errors": self.errors,
            "events_per_second": self.events_per_second,
            "seed": self.seed,
            "duplicate_rate": self.duplicate_rate,
            "sim_time": self.generator.sim_time.isoformat() if self.generator and self.events_emitted else None,
        }

    async def _announce(self) -> None:
        await self.hub.publish("simulation", self.state())

    # ---- controls ------------------------------------------------------------
    async def start(self, events_per_second: float, seed: int, duplicate_rate: float) -> None:
        if self.status == "error":
            raise SimulationStateError("Simulation failed earlier; reset it first")
        if self.status != "stopped":
            raise SimulationStateError(f"Simulation is already {self.status}")
        self.generator = EventGenerator(seed=seed, duplicate_rate=duplicate_rate)
        self.events_per_second, self.seed, self.duplicate_rate = events_per_second, seed, duplicate_rate
        await asyncio.to_thread(ensure_sim_accounts, self._db_path(), self.generator.account_specs())
        self._stop, self._gate = asyncio.Event(), asyncio.Event()
        self._gate.set()
        self.status = "running"
        self._task = asyncio.create_task(self._run())
        await self._announce()

    async def pause(self) -> None:
        if self.status != "running":
            raise SimulationStateError(f"Cannot pause: simulation is {self.status}")
        self.status = "paused"
        self._gate.clear()
        await self._announce()

    async def resume(self) -> None:
        if self.status != "paused":
            raise SimulationStateError(f"Cannot resume: simulation is {self.status}")
        self.status = "running"
        self._gate.set()
        await self._announce()

    async def reset(self) -> None:
        await self._halt()
        await asyncio.to_thread(reset_simulated_data, self._db_path())
        self._clear_counters()
        await self.hub.publish("reset", {})
        await self._announce()

    async def shutdown(self) -> None:
        await self._halt()

    async def _halt(self) -> None:
        """Ask the background task to finish its current event and exit (never kill it mid-write)."""
        if self._task is not None:
            self._stop.set()
            self._gate.set()  # wake it if it was paused
            await self._task
            self._task = None

    # ---- the background loop -----------------------------------------------
    async def _run(self) -> None:
        failures = 0
        while True:
            await self._gate.wait()  # sleeps here while paused
            if self._stop.is_set():
                return
            try:
                await self._step()
                failures = 0
            except Exception:
                failures += 1
                self.errors += 1
                log.exception("simulation step failed (%d in a row)", failures)
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    self.status = "error"
                    await self._announce()
                    return
            try:  # wait between events, but wake instantly if asked to stop
                await asyncio.wait_for(self._stop.wait(), timeout=1.0 / self.events_per_second)
                return
            except asyncio.TimeoutError:
                pass

    async def _step(self) -> None:
        assert self.generator is not None
        event = self.generator.next_event()
        self.events_emitted += 1
        # The database code blocks, so run it in a worker thread to keep the server responsive.
        result = await asyncio.to_thread(ingest_event, self._db_path(), event.tx)
        if not result.created:
            self.duplicates_ignored += 1  # already seen: no broadcast, no new alerts
            return
        self.transactions_created += 1
        await self.hub.publish("transaction", result.transaction.model_dump(mode="json"))
        for alert, action in result.alerts:
            await self.hub.publish("alert", {"action": action, "alert": alert.model_dump(mode="json")})
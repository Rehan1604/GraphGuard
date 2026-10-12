import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import repository as core
from app.config import get_settings
from app.db import connect, init_db
from app.detection.engine import run_detection
from app.main import app
from app.realtime import EventHub
from app.schemas import AccountCreate, TransactionCreate
from app.simulation.generator import EventGenerator
from app.simulation.ingest import ingest_event, reset_simulated_data, ensure_sim_accounts
from app.alerts import repository as alert_repo


def take(gen, n):
    return [gen.next_event() for _ in range(n)]


# ---- the generator (pure, no network, no database) ---------------------------
def test_same_seed_gives_identical_stream():
    a = [(e.tx.model_dump(), e.is_replay) for e in take(EventGenerator(seed=7), 300)]
    b = [(e.tx.model_dump(), e.is_replay) for e in take(EventGenerator(seed=7), 300)]
    c = [(e.tx.model_dump(), e.is_replay) for e in take(EventGenerator(seed=8), 300)]
    assert a == b and a != c


def test_events_come_out_in_time_order_with_unique_ids():
    fresh = [e.tx for e in take(EventGenerator(seed=1, duplicate_rate=0), 800)]
    times = [t.timestamp for t in fresh]
    assert times == sorted(times)
    assert len({t.id for t in fresh}) == len(fresh)


def test_replays_repeat_the_previous_event_exactly():
    events = take(EventGenerator(seed=3, duplicate_rate=0.3), 300)
    assert any(e.is_replay for e in events)
    for prev, cur in zip(events, events[1:]):
        if cur.is_replay:
            assert cur.tx == prev.tx
    assert not any(e.is_replay for e in take(EventGenerator(seed=3, duplicate_rate=0), 300))


def test_generated_traffic_contains_all_four_patterns():
    txs = [e.tx for e in take(EventGenerator(seed=42, duplicate_rate=0), 1500)]
    from app.schemas import Transaction
    stored = [Transaction(**t.model_dump(), ingested_at=t.timestamp) for t in txs]
    rules = {f.rule for f in run_detection(stored).findings}
    assert rules == {"pass_through_chain", "cycle", "burst", "fan"}


# ---- ingesting one event at a time ------------------------------------------
@pytest.fixture
def sim_db(db_path):
    gen = EventGenerator(seed=42, duplicate_rate=0)
    ensure_sim_accounts(db_path, gen.account_specs())
    return db_path, gen


def feed(db_path, gen, n):
    results = []
    for _ in range(n):
        results.append(ingest_event(db_path, gen.next_event().tx))
    return results


def test_streaming_ingest_raises_alerts(sim_db):
    db_path, gen = sim_db
    results = feed(db_path, gen, 600)
    assert all(r.created for r in results)
    assert sum(len(r.alerts) for r in results) > 0


def test_replayed_event_changes_nothing(sim_db):
    db_path, gen = sim_db
    feed(db_path, gen, 200)
    conn = connect(db_path)
    before = (conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
              conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
    conn.close()
    replay = ingest_event(db_path, EventGenerator(seed=42, duplicate_rate=0).next_event().tx)
    assert replay.created is False and replay.alerts == []
    conn = connect(db_path)
    after = (conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
             conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
    conn.close()
    assert before == after


def test_a_full_scan_finds_nothing_new_after_streaming(sim_db):
    db_path, gen = sim_db
    feed(db_path, gen, 600)
    conn = connect(db_path)
    findings = run_detection(core.all_transactions_chronological(conn)).findings
    summary = alert_repo.save_findings(conn, findings)
    conn.close()
    assert summary.created == 0  # live detection and a full rescan agree


def test_reset_removes_only_simulated_data(sim_db):
    db_path, gen = sim_db
    conn = connect(db_path)
    core.create_account(conn, AccountCreate(id="REAL1", name="Real", account_type="individual"))
    core.create_account(conn, AccountCreate(id="REAL2", name="Real2", account_type="individual"))
    core.create_transaction(conn, TransactionCreate(id="REAL-TX", source_account_id="REAL1",
                            target_account_id="REAL2", amount="5.00", timestamp="2026-03-01T00:00:00Z"))
    conn.close()
    feed(db_path, gen, 400)
    reset_simulated_data(db_path)
    conn = connect(db_path)
    counts = [conn.execute(q).fetchone()[0] for q in (
        "SELECT COUNT(*) FROM transactions", "SELECT COUNT(*) FROM accounts",
        "SELECT COUNT(*) FROM alerts", "SELECT COUNT(*) FROM alert_evidence")]
    conn.close()
    assert counts == [1, 2, 0, 0]


# ---- the hub, tested with fake clients (no network) --------------------------
class FakeWS:
    def __init__(self, broken=False):
        self.sent, self.broken, self.accepted = [], broken, False

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        if self.broken:
            raise RuntimeError("client went away")
        self.sent.append(payload)


def run(coro):
    return asyncio.run(coro)


def test_hub_numbers_events_in_order():
    async def go():
        hub = EventHub()
        a = await hub.publish("x", {})
        b = await hub.publish("x", {})
        return a["seq"], b["seq"]
    assert run(go()) == (1, 2)


def test_reconnect_replays_exactly_what_was_missed():
    async def go():
        hub = EventHub()
        for i in range(5):
            await hub.publish("tick", {"i": i})
        ws = FakeWS()
        await hub.connect(ws, last_seq=2)
        return ws.sent
    sent = run(go())
    assert sent[0] == {"type": "hello", "current_seq": 5, "replayed": 3}
    assert [m["seq"] for m in sent[1:]] == [3, 4, 5]


def test_reconnect_after_too_long_asks_for_full_resync():
    async def go():
        hub = EventHub(buffer_size=3)
        for i in range(10):
            await hub.publish("tick", {})
        ws = FakeWS()
        await hub.connect(ws, last_seq=2)  # events 3..7 already forgotten
        return ws.sent
    assert run(go()) == [{"type": "resync_required", "current_seq": 10}]


def test_client_with_future_seq_means_server_restarted_so_resync():
    async def go():
        hub = EventHub()
        await hub.publish("tick", {})
        ws = FakeWS()
        await hub.connect(ws, last_seq=500)
        return ws.sent
    assert run(go())[0]["type"] == "resync_required"


def test_one_broken_client_does_not_stop_the_others():
    async def go():
        hub = EventHub()
        good, bad = FakeWS(), FakeWS(broken=True)
        await hub.connect(good, None)
        hub._connections.add(bad)
        await hub.publish("tick", {})
        await hub.publish("tick", {})
        return good.sent, hub.connection_count
    sent, count = run(go())
    assert [m["seq"] for m in sent if "seq" in m] == [1, 2]
    assert count == 1  # the broken client was dropped


# ---- the whole thing through the real API and a real WebSocket ---------------
@pytest.fixture
def live(db_path, monkeypatch):
    monkeypatch.setenv("GRAPHGUARD_DATABASE_PATH", str(db_path))
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
        c.post("/api/simulation/reset")
    get_settings.cache_clear()


def wait_for(predicate, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_simulation_controls_and_state_rules(live):
    assert live.get("/api/simulation").json()["status"] == "stopped"
    assert live.post("/api/simulation/pause").status_code == 409
    assert live.post("/api/simulation/resume").status_code == 409
    assert live.post("/api/simulation/start", json={"events_per_second": 20}).json()["status"] == "running"
    assert live.post("/api/simulation/start").status_code == 409  # already running
    assert wait_for(lambda: live.get("/api/simulation").json()["transactions_created"] >= 5)

    assert live.post("/api/simulation/pause").json()["status"] == "paused"
    time.sleep(0.3)  # let any in-flight event finish
    frozen = live.get("/api/simulation").json()["events_emitted"]
    time.sleep(0.4)
    assert live.get("/api/simulation").json()["events_emitted"] == frozen  # truly paused

    assert live.post("/api/simulation/resume").json()["status"] == "running"
    assert wait_for(lambda: live.get("/api/simulation").json()["events_emitted"] > frozen)

    assert live.post("/api/simulation/reset").json()["status"] == "stopped"
    stats = live.get("/api/stats").json()
    assert (stats["accounts"], stats["transactions"], stats["alerts_total"]) == (0, 0, 0)
    assert live.post("/api/simulation/start", json={"events_per_second": 20}).status_code == 200


def test_start_validates_input(live):
    assert live.post("/api/simulation/start", json={"events_per_second": 0}).status_code == 422
    assert live.post("/api/simulation/start", json={"events_per_second": 500}).status_code == 422
    assert live.post("/api/simulation/start", json={"duplicate_rate": 0.9}).status_code == 422


def test_websocket_streams_live_events_and_reconnect_resumes(live):
    with live.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        live.post("/api/simulation/start", json={"events_per_second": 20, "duplicate_rate": 0.3})
        events = []
        while sum(e["type"] == "transaction" for e in events) < 6:
            events.append(ws.receive_json())
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))  # in order, no repeats
    tx_ids = [e["data"]["id"] for e in events if e["type"] == "transaction"]
    assert len(tx_ids) == len(set(tx_ids))  # duplicates were filtered out server-side
    first_tx = next(e for e in events if e["type"] == "transaction")["data"]
    assert first_tx["id"].startswith("SIM-TX-") and first_tx["timestamp"].endswith("Z")

    last = seqs[-1]
    live.post("/api/simulation/pause")
    time.sleep(0.5)
    with live.websocket_connect(f"/ws/events?last_seq={last}") as ws2:  # a "reconnect"
        hello = ws2.receive_json()
        assert hello["type"] == "hello" and hello["replayed"] >= 1  # we get what we missed
        replay = [ws2.receive_json() for _ in range(hello["replayed"])]
    assert [e["seq"] for e in replay] == list(range(last + 1, last + 1 + len(replay)))


def test_websocket_rejects_unknown_origin(live):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with live.websocket_connect("/ws/events", headers={"origin": "http://evil.example"}):
            pass
    with live.websocket_connect("/ws/events", headers={"origin": "http://localhost:5173"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_live_page_is_served(live):
    r = live.get("/live")
    assert r.status_code == 200 and "GraphGuard live console" in r.text
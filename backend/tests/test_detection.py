from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.detection.engine import run_detection
from app.detection.models import DetectionConfig
from app.schemas import Transaction
from tests.conftest import tx as api_tx

T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def mk(tx_id, src, dst, amount, minute):
    """minute = minutes after 10:00 on 1 March 2026."""
    ts = T0 + timedelta(minutes=minute)
    return Transaction(
        id=tx_id, source_account_id=src, target_account_id=dst,
        amount=Decimal(amount), timestamp=ts, ingested_at=ts,
    )


def scenario():
    return [
        # CHAIN: A1 -> A2 -> A3 -> A4, 10 minutes apart, ~98% forwarded each hop
        mk("c1", "A1", "A2", "1000", 0),
        mk("c2", "A2", "A3", "980", 10),
        mk("c3", "A3", "A4", "960", 20),
        # CYCLE: C1 -> C2 -> C3 -> C1 within 40 minutes
        mk("y1", "C1", "C2", "500", 60),
        mk("y2", "C2", "C3", "495", 80),
        mk("y3", "C3", "C1", "490", 100),
        # BURST: B1 sends to B2 six times in five minutes
        *[mk(f"b{i}", "B1", "B2", "50", 180 + i) for i in range(6)],
        # FAN: F1 receives from five different accounts in five minutes
        *[mk(f"f{i}", f"F{i + 2}", "F1", "200", 240 + i) for i in range(5)],
        # LOOKS-SIMILAR-BUT-NORMAL #1: second hop is hours later and far bigger
        mk("n1", "N1", "N2", "100", -60),
        mk("n2", "N2", "N3", "5000", 120),
        # LOOKS-SIMILAR-BUT-NORMAL #2: a chain, but each hop is 2 hours apart
        mk("s1", "S1", "S2", "1000", 0),
        mk("s2", "S2", "S3", "990", 120),
        mk("s3", "S3", "S4", "980", 240),
    ]


def by_rule(result, rule):
    return [f for f in result.findings if f.rule == rule]


def test_expected_findings_per_rule():
    result = run_detection(scenario())
    counts = {r: len(by_rule(result, r)) for r in ("pass_through_chain", "cycle", "burst", "fan")}
    assert counts == {"pass_through_chain": 1, "cycle": 1, "burst": 2, "fan": 1}


def test_chain_finding_and_score_breakdown():
    (chain,) = by_rule(run_detection(scenario()), "pass_through_chain")
    assert chain.accounts == ["A1", "A2", "A3", "A4"]
    assert chain.transaction_ids == ["c1", "c2", "c3"]
    assert [c.points for c in chain.contributions] == [30, 10, 10]  # base, near-full, fast
    assert chain.risk_score == 50 and chain.priority == "medium"


def test_cycle_finding_and_score_breakdown():
    (cycle,) = by_rule(run_detection(scenario()), "cycle")
    assert cycle.accounts == ["C1", "C2", "C3"]
    assert [c.points for c in cycle.contributions] == [45, 15]  # base, similar amounts
    assert cycle.risk_score == 60


def test_burst_and_fan_findings():
    result = run_detection(scenario())
    bursts = by_rule(result, "burst")
    assert {b.accounts[0] for b in bursts} == {"B1", "B2"}  # both ends of the burst
    assert all(b.risk_score == 20 and b.priority == "low" for b in bursts)
    (fan,) = by_rule(result, "fan")
    assert fan.accounts[0] == "F1" and len(fan.accounts) == 6


def test_normal_looking_activity_is_not_flagged():
    flagged = {a for f in run_detection(scenario()).findings for a in f.accounts}
    assert not flagged & {"N1", "N2", "N3", "S1", "S2", "S3", "S4"}


def test_chain_not_flagged_when_forwarded_amount_too_small():
    txs = [mk("a", "X1", "X2", "1000", 0), mk("b", "X2", "X3", "300", 5), mk("c", "X3", "X4", "290", 10)]
    assert by_rule(run_detection(txs), "pass_through_chain") == []


def test_chain_not_flagged_when_second_account_sends_more_than_it_received():
    txs = [mk("a", "X1", "X2", "1000", 0), mk("b", "X2", "X3", "1500", 5), mk("c", "X3", "X4", "1400", 10)]
    assert by_rule(run_detection(txs), "pass_through_chain") == []


def test_changing_the_threshold_changes_the_result():
    tight = DetectionConfig(chain_hop_window_minutes=5)
    assert by_rule(run_detection(scenario(), tight), "pass_through_chain") == []


def test_results_are_deterministic():
    assert run_detection(scenario()) == run_detection(list(reversed(scenario())))


def test_empty_input_gives_no_findings():
    result = run_detection([])
    assert result.findings == [] and result.accounts_in_graph == 0


def test_invalid_config_rejected():
    with pytest.raises(ValidationError):
        DetectionConfig(min_chain_hops=4, max_chain_hops=3)


def test_api_runs_detection_on_stored_transactions(client):
    for acc in ("A", "B", "C", "D"):
        client.post("/api/accounts", json={"id": acc, "name": acc, "account_type": "individual"})
    for i, (s, t, amt, ts) in enumerate(
        [("A", "B", "1000.00", "10:00"), ("B", "C", "980.00", "10:10"), ("C", "D", "960.00", "10:20")]
    ):
        client.post("/api/transactions", json=api_tx(id=f"T{i}", source_account_id=s, target_account_id=t,
                                                     amount=amt, timestamp=f"2026-03-01T{ts}:00Z"))
    body = client.post("/api/detection/run").json()
    assert body["transactions_analyzed"] == 3
    assert [f["rule"] for f in body["findings"]] == ["pass_through_chain"]
    # custom thresholds via the request body
    strict = client.post("/api/detection/run", json={"min_chain_hops": 4}).json()
    assert strict["findings"] == []
    assert client.post("/api/detection/run", json={"min_chain_hops": 1}).status_code == 422
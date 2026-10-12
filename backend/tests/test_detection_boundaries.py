"""Boundary-value tests: for every threshold, test the value just inside and just outside.
Bugs hide at the edges ("at least 6" versus "more than 6"), and demos never touch the edges."""
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.detection.engine import run_detection
from app.detection.models import DetectionConfig, ScoreContribution, build_finding
from app.schemas import Transaction
from tests.test_detection import T0


def mks(tx_id, src, dst, amount, seconds):
    ts = T0 + timedelta(seconds=seconds)
    return Transaction(id=tx_id, source_account_id=src, target_account_id=dst, amount=Decimal(str(amount)),
                       timestamp=ts, ingested_at=ts)


def count(txs, rule, cfg=None):
    return sum(f.rule == rule for f in run_detection(txs, cfg).findings)


MIN = 60


# ---- bursts: "at least 6 transfers inside 10 minutes" ---------------------------------------
def burst(n, last_second):
    times = [round(i * last_second / (n - 1)) for i in range(n)]
    return [mks(f"b{i}", "X", "Y", 10, t) for i, t in enumerate(times)]


def test_burst_threshold_is_inclusive():
    assert count(burst(6, 10 * MIN), "burst") == 2  # exactly 6 in exactly 10 minutes: flagged (each end)
    assert count(burst(5, 2 * MIN), "burst") == 0  # one fewer: not flagged


def test_burst_window_edge():
    assert count(burst(6, 10 * MIN + 1), "burst") == 0  # the same 6 transfers, one second too spread out


# ---- many counterparties: "at least 5 different accounts" -----------------------------------
def crowd(n):
    return [mks(f"f{i}", f"S{i}", "HUB", 10, i * 30) for i in range(n)]


def test_counterparty_threshold_is_inclusive():
    assert count(crowd(5), "fan") == 1
    assert count(crowd(4), "fan") == 0


def test_repeat_transfers_with_one_counterparty_count_once():
    txs = [mks(f"r{i}", "S0", "HUB", 10, i * 30) for i in range(5)] + crowd(3)
    assert count(txs, "fan") == 0  # 5 + 3 transfers but only 4 different accounts


# ---- chains: time gap, forwarding ratio, length ---------------------------------------------
def chain(gap_min, second_amount="800.00", hops=3):
    amounts = ["1000.00", second_amount] + [second_amount] * (hops - 2)
    accounts = ["A", "B", "C", "D", "E"]
    return [mks(f"c{i}", accounts[i], accounts[i + 1], amounts[i], i * gap_min * MIN) for i in range(hops)]


def test_chain_time_gap_is_inclusive_at_30_minutes():
    assert count(chain(30), "pass_through_chain") == 1
    assert count(chain(31), "pass_through_chain") == 0


@pytest.mark.parametrize("amount,expected", [("800.00", 1), ("799.99", 0), ("1000.00", 1), ("1000.01", 0)])
def test_chain_forwarding_ratio_edges(amount, expected):
    # exactly 80% passes, a cent less does not; forwarding more than arrived does not
    assert count(chain(10, second_amount=amount), "pass_through_chain") == expected


def test_chain_minimum_length():
    assert count(chain(10, hops=3), "pass_through_chain") == 1
    assert count(chain(10, hops=2), "pass_through_chain") == 0


# ---- cycles: window and length ----------------------------------------------------------------
def loop(n, total_min):
    accounts = ["A", "B", "C", "D", "E", "F"][:n]
    step = total_min * MIN / (n - 1)
    # alternating amounts so the chain rule stays quiet and only the cycle rule is under test
    return [mks(f"y{i}", accounts[i], accounts[(i + 1) % n], 1000 if i % 2 == 0 else 500, round(i * step)) for i in range(n)]


def test_cycle_window_is_inclusive_at_120_minutes():
    assert count(loop(3, 120), "cycle") == 1
    assert count(loop(3, 121), "cycle") == 0


@pytest.mark.parametrize("n,expected", [(2, 0), (3, 1), (5, 1), (6, 0)])
def test_cycle_length_limits(n, expected):
    assert count(loop(n, 60), "cycle") == expected


# ---- the same route reported many times (found by the evaluation) --------------------------------
def test_parallel_transfers_do_not_multiply_a_loop():
    txs = [mks("p1", "A", "B", 1000, 0), mks("p2", "A", "B", 1000, 20), mks("p3", "A", "B", 1000, 40),
           mks("q", "B", "C", 500, 300), mks("r", "C", "A", 1000, 600)]
    findings = [f for f in run_detection(txs).findings if f.rule == "cycle"]
    assert len(findings) == 1
    assert "p1" in findings[0].transaction_ids  # the earliest combination is the one kept


def test_the_same_loop_hours_later_is_a_new_finding():
    first = [mks("a1", "A", "B", 1000, 0), mks("a2", "B", "C", 500, 300), mks("a3", "C", "A", 1000, 600)]
    later = [mks("b1", "A", "B", 1000, 4 * 3600), mks("b2", "B", "C", 500, 4 * 3600 + 300), mks("b3", "C", "A", 1000, 4 * 3600 + 600)]
    assert count(first + later, "cycle") == 2


def test_parallel_transfers_do_not_multiply_a_chain():
    txs = [mks("p1", "A", "B", 1000, 0), mks("p2", "A", "B", 1000, 10), mks("p3", "A", "B", 1000, 20),
           mks("q", "B", "C", 980, 300), mks("r", "C", "D", 960, 600)]
    assert count(txs, "pass_through_chain") == 1


def test_the_chosen_evidence_does_not_change_when_later_parallel_transfers_arrive():
    base = [mks("p1", "A", "B", 1000, 0), mks("q", "B", "C", 500, 300), mks("r", "C", "A", 1000, 600)]
    before = next(f for f in run_detection(base).findings if f.rule == "cycle")
    after = next(f for f in run_detection(base + [mks("p2", "A", "B", 1000, 700)]).findings if f.rule == "cycle")
    assert before.transaction_ids == after.transaction_ids


# ---- robustness to messy input -------------------------------------------------------------------
def test_the_same_transaction_twice_is_still_one_transaction():
    txs = chain(10)
    assert run_detection(txs + txs).findings == run_detection(txs).findings
    assert run_detection(txs + txs).transactions_analyzed == 3


def test_input_order_does_not_matter():
    txs = burst(8, 5 * MIN) + crowd(6) + chain(10)
    assert run_detection(list(reversed(txs))).findings == run_detection(txs).findings


def test_extreme_amounts_stay_exact():
    def three(first, second):
        return [mks("e1", "A", "B", first, 0), mks("e2", "B", "C", second, 600), mks("e3", "C", "D", second, 1200)]

    assert count(three("100000000000.00", "80000000000.00"), "pass_through_chain") == 1  # exactly 80% at huge scale
    assert count(three("100000000000.00", "79999999999.99"), "pass_through_chain") == 0  # one cent below 80%
    assert count(three("0.10", "0.08"), "pass_through_chain") == 1  # exactly 80% in decimal arithmetic; floats can get this wrong


def test_nothing_or_one_transaction_is_fine():
    assert run_detection([]).findings == []
    assert run_detection([mks("only", "A", "B", 5, 0)]).findings == []


# ---- risk scores: the sum, the cap and the priority edges -------------------------------------------
@pytest.mark.parametrize("points,priority", [(1, "low"), (39, "low"), (40, "medium"), (69, "medium"), (70, "high"), (100, "high")])
def test_priority_edges(points, priority):
    f = build_finding("burst", ["A"], [mks("x", "A", "B", 1, 0)], [ScoreContribution(reason="r", points=points)], "s")
    assert (f.risk_score, f.priority) == (points, priority)


def test_score_is_the_sum_of_contributions_and_capped_at_100():
    f = build_finding("burst", ["A"], [mks("x", "A", "B", 1, 0)],
                      [ScoreContribution(reason="a", points=60), ScoreContribution(reason="b", points=90)], "s")
    assert f.risk_score == 100 and f.priority == "high"


@pytest.mark.parametrize(
    "bad",
    [{"pass_through_ratio": "0"}, {"pass_through_ratio": "1.01"}, {"chain_hop_window_minutes": 0}, {"min_chain_hops": 1},
     {"burst_min_transactions": 1}, {"max_cycle_length": 2, "min_cycle_length": 3}],
)
def test_nonsense_thresholds_are_rejected(bad):
    with pytest.raises(ValidationError):
        DetectionConfig(**bad)
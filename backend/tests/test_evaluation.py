import json
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.detection.engine import run_detection
from app.detection.models import DetectionConfig
from app.evaluation import runner
from app.evaluation.baseline import Detection, counterparties, large_transfers, velocity
from app.evaluation.dataset import Episode, LabelledDataset, build_benchmark, dataset_from_simulator
from app.evaluation.metrics import f1, matches, measure_delay, rate, score_detector
from app.evaluation.runner import run_evaluation, stream_detect, summarize_seeds
from app.main import app
from app.schemas import Transaction
from app.simulation.generator import EventGenerator
from tests.test_detection import T0


@pytest.fixture(scope="module")
def bench():
    return build_benchmark(42)


@pytest.fixture(scope="module")
def report(bench):
    return run_evaluation(bench)


# ---- a tiny hand-built answer key, so every number can be checked by hand ---------------------------
def tx(tx_id, src="a", dst="b", amount="1.00", seconds=0):
    ts = T0 + timedelta(seconds=seconds)
    return Transaction(id=tx_id, source_account_id=src, target_account_id=dst, amount=Decimal(amount), timestamp=ts, ingested_at=ts)


def episode(name, kind, role, ids, accepts=None):
    return Episode(name, kind, role, accepts or (kind,), frozenset(ids), T0, T0 + timedelta(minutes=10))


E_CHAIN = episode("chain", "pass_through_chain", "positive", ["t1", "t2", "t3", "t4"])
E_BURST = episode("burst", "burst", "positive", ["t5", "t6", "t7", "t8"])
E_BENIGN = episode("split_bill", "cycle", "benign_lookalike", ["t9", "t10", "t11"])
E_NEAR = episode("near_fan", "fan", "near_miss", ["t12", "t13", "t14", "t15"])


def mini(episodes=(E_CHAIN, E_BURST, E_BENIGN, E_NEAR), background=("b1", "b2", "b3")):
    ids = sorted(set().union(*(e.transaction_ids for e in episodes)) | set(background))
    return LabelledDataset("mini", 0, [tx(i) for i in ids], list(episodes))


def det(kind, ids):
    return Detection(kind, frozenset(ids))


# ---- matching ---------------------------------------------------------------------------------------
def test_a_match_needs_half_the_pattern_and_a_mostly_pure_finding():
    assert matches(det("pass_through_chain", ["t1", "t2"]), E_CHAIN)  # exactly half of the pattern: counts
    assert not matches(det("pass_through_chain", ["t1"]), E_CHAIN)  # a quarter: does not
    assert matches(det("pass_through_chain", ["t1", "t2", "x1", "x2"]), E_CHAIN)  # half of the finding is the pattern: counts
    assert not matches(det("pass_through_chain", ["t1", "t2", "x1", "x2", "x3"]), E_CHAIN)  # too diluted
    assert not matches(det("cycle", ["t1", "t2", "t3", "t4"]), E_CHAIN)  # right transactions, wrong kind of pattern
    assert matches(det("*", ["t1", "t2"]), E_CHAIN)  # a generic detector may match any kind
    assert not matches(det("pass_through_chain", ["zzz"]), E_CHAIN)


def test_the_fan_pattern_accepts_a_burst_finding():
    e = episode("fan", "fan", "positive", ["f1", "f2", "f3", "f4", "f5", "f6"], accepts=("fan", "burst"))
    assert matches(det("burst", ["f1", "f2", "f3", "f4", "f5", "f6"]), e)


# ---- scoring: every number below was worked out by hand -----------------------------------------------
def test_precision_recall_f1_and_the_confusion_matrix_by_hand():
    detections = [
        det("pass_through_chain", ["t1", "t2", "t3", "t4"]),  # finds the chain
        det("pass_through_chain", ["t1", "t2", "t3"]),  # the same chain found again (duplicate)
        det("burst", ["t5", "t6", "t7"]),  # finds the burst
        det("cycle", ["t9", "t10", "t11"]),  # flags the benign look-alike
        det("fan", ["b1"]),  # touches nothing labelled
        det("*", ["t1"]),  # touches the chain but too little to match
    ]
    r = score_detector("x", detections, mini())
    assert (r.findings, r.precision.numerator, r.precision.denominator) == (6, 3, 6)
    assert (r.recall.numerator, r.recall.denominator) == (2, 2)
    assert r.f1 == pytest.approx(0.6667, abs=1e-4)  # 2 * 0.5 * 1.0 / (0.5 + 1.0)
    assert r.false_positive_findings == 3
    assert (r.false_positives_from_benign_lookalikes, r.false_positives_from_near_misses) == (1, 0)
    assert (r.false_positives_mixed_overlap, r.false_positives_background_only) == (1, 1)
    c = r.confusion
    assert (c.true_positive, c.false_negative, c.false_positive, c.true_negative) == (2, 0, 1, 1)
    assert (r.benign_lookalikes_flagged.numerator, r.benign_lookalikes_flagged.denominator) == (1, 1)
    assert (r.near_misses_flagged.numerator, r.near_misses_flagged.denominator) == (0, 1)
    assert r.recall_lenient.numerator == 2
    assert r.background_only_findings_per_1000_background == pytest.approx(1 / 3 * 1000, abs=0.01)  # 1 finding over 3 background transactions
    assert {k: (v.numerator, v.denominator) for k, v in r.per_kind_recall.items()} == {"burst": (1, 1), "pass_through_chain": (1, 1)}


def test_a_pattern_found_twice_counts_once_for_recall():
    r = score_detector("x", [det("pass_through_chain", ["t1", "t2", "t3", "t4"])] * 3, mini())
    assert (r.recall.numerator, r.precision.numerator, r.precision.denominator) == (1, 3, 3)


def test_finding_nothing_gives_undefined_precision_not_a_crash_or_a_fake_zero():
    r = score_detector("x", [], mini())
    assert r.precision.value is None and r.f1 is None
    assert (r.recall.numerator, r.recall.denominator, r.recall.value) == (0, 2, 0.0)
    assert r.confusion.false_negative == 2


def test_no_planted_patterns_gives_undefined_recall():
    r = score_detector("x", [det("cycle", ["t9"])], mini(episodes=(E_BENIGN, E_NEAR)))
    assert r.recall.value is None and r.f1 is None


def test_f1_and_rate_helpers():
    assert f1(1.0, 1.0) == 1.0 and f1(0.5, 1.0) == 0.6667 and f1(0.0, 0.0) == 0.0 and f1(None, 0.5) is None
    assert rate(1, 3).value == 0.3333 and rate(0, 0).value is None


# ---- the baseline detectors ---------------------------------------------------------------------------
def test_large_transfer_threshold_edge():
    flagged = large_transfers([tx("a", amount="4999.99"), tx("b", amount="5000.00"), tx("c", amount="5000.01")])
    assert sorted(next(iter(d.transaction_ids)) for d in flagged) == ["b", "c"]


def test_velocity_and_counterparty_baselines_have_the_same_edges():
    six = [tx(f"v{i}", "x", "y", seconds=i * 100) for i in range(6)]
    assert len(velocity(six)) == 2 and velocity(six[:5]) == []
    five = [tx(f"c{i}", f"s{i}", "hub", seconds=i * 60) for i in range(5)]
    assert len(counterparties(five)) == 1 and counterparties(five[:4]) == []


# ---- the benchmark data ---------------------------------------------------------------------------------
def test_same_seed_same_data_different_seed_different_data():
    a, b, c = build_benchmark(7), build_benchmark(7), build_benchmark(8)
    assert [t.model_dump() for t in a.transactions] == [t.model_dump() for t in b.transactions]
    assert a.episodes == b.episodes
    assert [t.model_dump() for t in a.transactions] != [t.model_dump() for t in c.transactions]


def test_benchmark_composition(bench):
    roles = [e.role for e in bench.episodes]
    assert (roles.count("positive"), roles.count("near_miss"), roles.count("benign_lookalike")) == (40, 24, 12)
    assert {k: sum(e.kind == k and e.role == "positive" for e in bench.episodes) for k in ("pass_through_chain", "cycle", "burst", "fan")} == \
        {"pass_through_chain": 10, "cycle": 10, "burst": 10, "fan": 10}
    ids = [i for e in bench.episodes for i in e.transaction_ids]
    assert len(ids) == len(set(ids))  # episodes never share a transaction
    assert set(ids) <= {t.id for t in bench.transactions}
    assert bench.background_count == 700 and len(bench.transactions) == 1053
    assert all(t.timestamp.tzinfo is not None and t.amount > 0 for t in bench.transactions)


# ---- no leakage: the detector must not be able to read the answer key ------------------------------------
def test_transaction_ids_reveal_nothing_about_which_episode_they_belong_to(bench):
    ids = [t.id for t in bench.transactions]
    assert all(i.startswith("EV-TX-") and i[6:].isdigit() for i in ids)
    assert ids == sorted(ids) and [t.timestamp for t in bench.transactions] == sorted(t.timestamp for t in bench.transactions)
    words = {e.name for e in bench.episodes} | {"chain", "cycle", "burst", "fan", "decoy", "benign", "planted"}
    assert not any(w in i.lower() for i in ids for w in words)


def test_transactions_carry_no_label_field(bench):
    assert set(bench.transactions[0].model_dump()) == {
        "id", "source_account_id", "target_account_id", "amount", "currency", "timestamp", "ingested_at"}


def test_renaming_every_transaction_id_does_not_change_what_is_detected(bench):
    n = len(bench.transactions)
    renamed = [t.model_copy(update={"id": f"Z{n - i:06d}"}) for i, t in enumerate(bench.transactions)]

    def signature(findings):
        return sorted((f.rule, f.risk_score, tuple(f.accounts), f.window_start, f.window_end) for f in findings)

    assert signature(run_detection(bench.transactions).findings) == signature(run_detection(renamed).findings)


def test_detectors_are_only_ever_given_transactions(bench, monkeypatch):
    seen = []
    real = runner.run_detection

    def spy(txs, cfg=None):
        seen.append(txs)
        return real(txs, cfg)

    monkeypatch.setattr(runner, "run_detection", spy)
    run_evaluation(build_benchmark(3))
    assert seen and all(isinstance(t, Transaction) for batch in seen for t in batch)


def test_negative_control_collapses_recall_when_the_answer_key_is_scrambled(report):
    assert report.graph.recall.value == 1.0
    assert report.negative_control.recall.value == 0.0 and report.negative_control.recall.denominator == 40


# ---- detection delay -------------------------------------------------------------------------------------
def delay_for(txs, kind, accepts):
    e = Episode("e", kind, "positive", accepts, frozenset(t.id for t in txs), min(t.timestamp for t in txs), max(t.timestamp for t in txs))
    ds = LabelledDataset("d", 0, txs, [e])
    return measure_delay(ds, stream_detect(txs, DetectionConfig()))


def test_a_chain_is_flagged_when_its_last_transfer_arrives():
    txs = [tx("c1", "A", "B", "1000", 0), tx("c2", "B", "C", "980", 600), tx("c3", "C", "D", "960", 1200)]
    d = delay_for(txs, "pass_through_chain", ("pass_through_chain",))
    assert d.detected == 1 and d.median_minutes_from_first_transfer == 20.0
    assert d.median_minutes_after_last_transfer == 0.0 and d.flagged_before_pattern_finished.numerator == 0


def test_a_burst_is_flagged_before_it_finishes():
    txs = [tx(f"b{i}", "X", "Y", "10", i * 60) for i in range(9)]  # 9 transfers, one per minute
    d = delay_for(txs, "burst", ("burst",))
    assert d.median_minutes_from_first_transfer == 5.0  # the 6th transfer trips the threshold
    assert d.median_minutes_after_last_transfer == -3.0 and d.flagged_before_pattern_finished.numerator == 1


def test_a_pattern_that_is_never_flagged_has_no_delay():
    txs = [tx("s1", "A", "B", "1000", 0), tx("s2", "B", "C", "980", 7200), tx("s3", "C", "D", "960", 14400)]  # hops 2 hours apart
    d = delay_for(txs, "pass_through_chain", ("pass_through_chain",))
    assert d.detected == 0 and d.median_minutes_from_first_transfer is None


# ---- the full benchmark: a regression snapshot -----------------------------------------------------------------
def test_seed_42_results_are_pinned(report):
    """If a rule changes, these numbers change. Update them ON PURPOSE, after looking at why."""
    g, b = report.graph, report.baseline
    assert (g.findings, g.precision.numerator, g.recall.numerator, g.recall.denominator) == (82, 59, 40, 40)
    assert g.f1 == 0.8369
    assert (g.confusion.true_positive, g.confusion.false_negative, g.confusion.false_positive, g.confusion.true_negative) == (40, 0, 13, 23)
    assert (g.false_positives_from_benign_lookalikes, g.false_positives_from_near_misses,
            g.false_positives_mixed_overlap, g.false_positives_background_only) == (17, 1, 4, 1)
    assert (g.benign_lookalikes_flagged.numerator, g.near_misses_flagged.numerator) == (12, 1)
    assert (b.findings, b.precision.numerator, b.recall.numerator, b.recall_lenient.numerator) == (168, 39, 20, 40)
    assert {k: v.numerator for k, v in b.per_kind_recall.items()} == {"burst": 10, "cycle": 0, "fan": 10, "pass_through_chain": 0}
    d = report.delay
    assert (d.detected, d.median_minutes_from_first_transfer, d.median_minutes_after_last_transfer) == (40, 7.16, -0.44)


def test_false_positive_categories_add_up(report):
    for r in (report.graph, report.baseline):
        assert r.false_positive_findings == (r.false_positives_from_benign_lookalikes + r.false_positives_from_near_misses
                                              + r.false_positives_mixed_overlap + r.false_positives_background_only)
        assert r.precision.numerator + r.false_positive_findings == r.findings


def test_graph_engine_beats_baseline_on_what_baseline_cannot_see(report):
    assert report.baseline.per_kind_recall["cycle"].numerator == 0 and report.graph.per_kind_recall["cycle"].numerator == 10
    assert report.graph.f1 > report.baseline.f1 and report.graph.findings < report.baseline.findings  # fewer alerts to read, too


def test_evaluation_is_reproducible_apart_from_machine_timing(bench):
    a, b = run_evaluation(bench).model_dump(mode="json"), run_evaluation(bench).model_dump(mode="json")
    a.pop("timing"), b.pop("timing")
    assert a == b


def test_threshold_sweeps_show_the_trade_off(report):
    chain = next(s for s in report.sweeps if s.parameter == "chain_hop_window_minutes")
    by = {p.value: p for p in chain.points}
    assert by[5].recall < by[30].recall and chain.default == 30  # too tight a window misses real chains
    burst = next(s for s in report.sweeps if s.parameter == "burst_min_transactions")
    by = {p.value: p for p in burst.points}
    assert by[3].findings > by[10].findings and by[3].precision < by[6].precision  # a low bar floods analysts
    assert by[10].recall < by[6].recall  # a high bar misses real bursts


def test_results_vary_a_little_across_seeds_and_the_summary_says_how_much():
    s = summarize_seeds([1, 2, 3, 4, 5])
    p = s.metrics["graph.precision"]
    assert p["min"] <= p["mean"] <= p["max"] and p["max"] - p["min"] > 0
    assert s.metrics["graph.recall"]["min"] == 1.0


# ---- the simulator as a labelled dataset -----------------------------------------------------------------------
def test_the_simulator_records_which_transactions_it_planted():
    gen = EventGenerator(seed=42, duplicate_rate=0)
    made = {gen.next_event().tx.id for _ in range(300)}
    assert gen.planted and all(kind in ("chain", "cycle", "burst", "fan") for kind, _ in gen.planted)
    assert all(len(ids) >= 3 for _, ids in gen.planted)
    assert len({i for _, ids in gen.planted for i in ids}) == sum(len(ids) for _, ids in gen.planted)  # no overlap
    assert made  # the labels are bookkeeping on the side; the transactions themselves are unchanged


def test_incomplete_patterns_at_the_end_of_the_stream_are_left_out():
    ds = dataset_from_simulator(42, 240)
    ids = {t.id for t in ds.transactions}
    assert all(e.transaction_ids <= ids for e in ds.episodes) and all(e.role == "positive" for e in ds.episodes)
    gen = EventGenerator(seed=42, duplicate_rate=0)
    [gen.next_event() for _ in range(240)]
    assert len(ds.episodes) <= len(gen.planted)


def test_the_simulator_stream_has_one_alert_per_loop(bench):
    ds = dataset_from_simulator(42, 240)
    loops = [f for f in run_detection(ds.transactions).findings if f.rule == "cycle"]
    keys = {tuple(sorted(f.accounts)) for f in loops}
    assert len(loops) == len(keys) == 6  # was 18 alerts for 6 loops before the parallel-transfer fix


# ---- the API -----------------------------------------------------------------------------------------------------
def test_api_returns_the_report_and_is_stable():
    client = TestClient(app)
    a = client.get("/api/evaluation?seed=42")
    assert a.status_code == 200
    body = a.json()
    assert body["graph"]["recall"] == {"numerator": 40, "denominator": 40, "value": 1.0}
    assert body["baseline"]["precision"]["denominator"] == 168 and len(body["caveats"]) >= 5 and "timing" in body
    assert json.dumps(body, sort_keys=True) == json.dumps(client.get("/api/evaluation?seed=42").json(), sort_keys=True)
    sim = client.get("/api/evaluation?dataset=simulator&seed=42&n_events=240").json()
    assert sim["dataset"]["name"] == "simulator" and sim["dataset"]["transactions"] == 240


@pytest.mark.parametrize("query", ["seed=-1", "seed=abc", "dataset=bogus", "n_events=10", "n_events=5000"])
def test_api_rejects_bad_input(query):
    assert TestClient(app).get(f"/api/evaluation?{query}").status_code == 422
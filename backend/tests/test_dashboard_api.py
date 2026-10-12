from tests.test_alerts import chain_client, load  # noqa: F401  (fixture + helper reused)


def test_default_detection_config_endpoint(client):
    body = client.get("/api/detection/config").json()
    assert body["min_chain_hops"] == 3 and body["burst_min_transactions"] == 6


def test_graph_merges_parallel_transfers_and_counts_open_alerts(chain_client):
    chain_client.post("/api/transactions", json={
        "id": "T9", "source_account_id": "A", "target_account_id": "B", "amount": "5.00",
        "timestamp": "2026-03-01T09:00:00Z"})
    chain_client.post("/api/alerts/scan")
    g = chain_client.get("/api/graph").json()
    assert g["transactions_considered"] == 4
    ab = next(e for e in g["edges"] if e["source"] == "A" and e["target"] == "B")
    assert ab["transaction_count"] == 2 and ab["total_amount"] == "1005.00"
    assert {n["id"]: n["open_alerts"] for n in g["nodes"]} == {"A": 1, "B": 1, "C": 1, "D": 1}
    chain_client.post("/api/alerts/1/status", json={"status": "dismissed", "comment": "payroll"})
    assert all(n["open_alerts"] == 0 for n in chain_client.get("/api/graph").json()["nodes"])


def test_graph_limit_keeps_only_most_recent_transactions(chain_client):
    g = chain_client.get("/api/graph?limit=1").json()
    assert g["transactions_considered"] == 1
    assert [(e["source"], e["target"]) for e in g["edges"]] == [("C", "D")]
    assert chain_client.get("/api/graph?limit=0").status_code == 422


def test_alert_metrics_count_by_status_priority_and_rule(chain_client):
    empty = chain_client.get("/api/metrics/alerts").json()
    assert empty["total"] == 0 and empty["by_rule"]["cycle"] == 0
    chain_client.post("/api/alerts/scan")
    chain_client.post("/api/alerts/1/status", json={"status": "in_review"})
    m = chain_client.get("/api/metrics/alerts").json()
    assert m["total"] == 1 and m["by_status"]["in_review"] == 1 and m["by_status"]["new"] == 0
    assert m["by_rule"]["pass_through_chain"] == 1 and m["by_priority"]["medium"] == 1


def test_alert_detail_tells_the_ui_which_moves_are_allowed(chain_client):
    chain_client.post("/api/alerts/scan")
    d = chain_client.get("/api/alerts/1").json()
    assert d["allowed_next_statuses"] == ["in_review", "dismissed"]
    assert d["comment_required_for"] == ["escalated", "dismissed"]
    d = chain_client.post("/api/alerts/1/status", json={"status": "in_review"}).json()
    assert d["allowed_next_statuses"] == ["escalated", "dismissed"]
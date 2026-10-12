import pytest

from app import repository as core
from app.alerts import repository as alert_repo
from app.alerts.models import NoteCreate, StatusChange
from app.alerts.workflow import ALLOWED_TRANSITIONS, CommentRequiredError, InvalidTransitionError, check_transition
from app.db import connect
from tests.conftest import tx as api_tx

CHAIN = [("T0", "A", "B", "1000.00", "10:00"), ("T1", "B", "C", "980.00", "10:10"), ("T2", "C", "D", "960.00", "10:20")]


def load(client, accounts, txs):
    for acc in accounts:
        client.post("/api/accounts", json={"id": acc, "name": acc, "account_type": "individual"})
    for tx_id, s, t, amt, hhmm in txs:
        r = client.post("/api/transactions", json=api_tx(
            id=tx_id, source_account_id=s, target_account_id=t, amount=amt, timestamp=f"2026-03-01T{hhmm}:00Z"))
        assert r.status_code == 201


@pytest.fixture
def chain_client(client):
    load(client, "ABCD", CHAIN)
    return client


def status_of(client, alert_id=1):
    return client.get(f"/api/alerts/{alert_id}").json()["status"]


# ---- creation and deduplication -----------------------------------------
def test_scan_creates_alert_and_rescan_does_not_duplicate(chain_client):
    first = chain_client.post("/api/alerts/scan").json()
    second = chain_client.post("/api/alerts/scan").json()
    assert (first["created"], first["unchanged"]) == (1, 0)
    assert (second["created"], second["unchanged"]) == (0, 1)
    assert len(chain_client.get("/api/alerts").json()) == 1


def test_alert_detail_shows_evidence_and_score_breakdown(chain_client):
    chain_client.post("/api/alerts/scan")
    d = chain_client.get("/api/alerts/1").json()
    assert [t["id"] for t in d["evidence"]] == ["T0", "T1", "T2"]  # in time order
    assert sum(c["points"] for c in d["contributions"]) == d["risk_score"] == 50
    assert d["status"] == "new" and d["evidence_count"] == 3
    assert d["history"][0]["event"] == "created" and d["history"][0]["actor"] == "system"


def test_list_filters(chain_client):
    chain_client.post("/api/alerts/scan")
    assert len(chain_client.get("/api/alerts?status=new").json()) == 1
    assert chain_client.get("/api/alerts?status=dismissed").json() == []
    assert chain_client.get("/api/alerts?rule=cycle").json() == []
    assert len(chain_client.get("/api/alerts?priority=medium").json()) == 1
    assert chain_client.get("/api/alerts?status=bogus").status_code == 422


def test_unknown_alert_is_404(client):
    assert client.get("/api/alerts/99").status_code == 404
    assert client.post("/api/alerts/99/notes", json={"body": "x"}).status_code == 404
    assert client.post("/api/alerts/99/status", json={"status": "in_review"}).status_code == 404


# ---- workflow ------------------------------------------------------------
def test_status_changes_follow_the_rules(chain_client):
    chain_client.post("/api/alerts/scan")
    assert chain_client.post("/api/alerts/1/status", json={"status": "escalated", "comment": "x"}).status_code == 409
    assert chain_client.post("/api/alerts/1/status", json={"status": "in_review"}).status_code == 200
    assert chain_client.post("/api/alerts/1/status", json={"status": "dismissed"}).status_code == 422  # needs a reason
    ok = chain_client.post("/api/alerts/1/status", json={"status": "dismissed", "comment": "Payroll account"})
    assert ok.status_code == 200 and ok.json()["status"] == "dismissed"
    events = [(h["from_status"], h["to_status"]) for h in ok.json()["history"] if h["event"] == "status_changed"]
    assert events == [("new", "in_review"), ("in_review", "dismissed")]


def test_whitespace_comment_does_not_count_as_a_reason(chain_client):
    chain_client.post("/api/alerts/scan")
    chain_client.post("/api/alerts/1/status", json={"status": "in_review"})
    assert chain_client.post("/api/alerts/1/status", json={"status": "escalated", "comment": "   "}).status_code == 422


@pytest.mark.parametrize("current", ["new", "in_review", "escalated", "dismissed"])
@pytest.mark.parametrize("target", ["new", "in_review", "escalated", "dismissed"])
def test_transition_table_is_enforced(current, target):
    if target in ALLOWED_TRANSITIONS[current]:
        check_transition(current, target, "because")
    else:
        with pytest.raises(InvalidTransitionError):
            check_transition(current, target, "because")


def test_conclusions_need_a_comment():
    with pytest.raises(CommentRequiredError):
        check_transition("in_review", "escalated", None)


# ---- notes ---------------------------------------------------------------
def test_notes_are_saved_in_order_and_validated(chain_client):
    chain_client.post("/api/alerts/scan")
    chain_client.post("/api/alerts/1/notes", json={"body": "Checked KYC file", "author": "priya"})
    chain_client.post("/api/alerts/1/notes", json={"body": "  Second note  "})
    notes = chain_client.get("/api/alerts/1").json()["notes"]
    assert [n["body"] for n in notes] == ["Checked KYC file", "Second note"]
    assert notes[0]["author"] == "priya" and notes[1]["author"] == "analyst"
    assert chain_client.post("/api/alerts/1/notes", json={"body": "   "}).status_code == 422


# ---- persistence ---------------------------------------------------------
def test_everything_survives_a_fresh_database_connection(chain_client, db_path):
    chain_client.post("/api/alerts/scan")
    chain_client.post("/api/alerts/1/notes", json={"body": "remember me"})
    chain_client.post("/api/alerts/1/status", json={"status": "in_review"})
    conn = connect(db_path)  # like restarting the app: brand-new connection to the same file
    d = alert_repo.get_alert_detail(conn, 1)
    conn.close()
    assert d.status == "in_review" and [n.body for n in d.notes] == ["remember me"]
    assert len(d.evidence) == 3


# ---- an alert whose pattern keeps growing --------------------------------
def test_growing_pattern_updates_the_same_alert_and_keeps_notes(chain_client):
    chain_client.post("/api/alerts/scan")
    chain_client.post("/api/alerts/1/notes", json={"body": "watching this"})
    chain_client.post("/api/alerts/1/status", json={"status": "in_review"})
    load(chain_client, "E", [("T3", "D", "E", "940.00", "10:30")])
    summary = chain_client.post("/api/alerts/scan").json()
    assert (summary["created"], summary["updated"]) == (0, 1)
    d = chain_client.get("/api/alerts/1").json()
    assert len(chain_client.get("/api/alerts").json()) == 1
    assert d["evidence_count"] == 4 and d["status"] == "in_review"
    assert [n["body"] for n in d["notes"]] == ["watching this"]
    assert "evidence_grew" in [h["event"] for h in d["history"]]


def test_dismissed_alert_reopens_when_new_evidence_arrives(chain_client):
    chain_client.post("/api/alerts/scan")
    chain_client.post("/api/alerts/1/status", json={"status": "dismissed", "comment": "looks normal"})
    load(chain_client, "E", [("T3", "D", "E", "940.00", "10:30")])
    chain_client.post("/api/alerts/scan")
    d = chain_client.get("/api/alerts/1").json()
    assert d["status"] == "new"
    assert d["history"][-1]["actor"] == "system" and d["history"][-1]["to_status"] == "new"


def test_failed_scan_leaves_no_half_saved_alerts(chain_client, db_path, monkeypatch):
    from app.alerts import repository as r
    from app.detection.engine import run_detection
    findings = run_detection(core.all_transactions_chronological(connect(db_path))).findings
    original = r._add_history
    monkeypatch.setattr(r, "_add_history", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    conn = connect(db_path)
    with pytest.raises(RuntimeError):
        r.save_findings(conn, findings)
    monkeypatch.setattr(r, "_add_history", original)
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
    conn.close()
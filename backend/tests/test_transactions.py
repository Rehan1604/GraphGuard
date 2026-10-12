import sqlite3

import pytest

from app.db import connect
from tests.conftest import tx


def test_create_and_retrieve_transaction(two_accounts):
    r = two_accounts.post("/api/transactions", json=tx())
    assert r.status_code == 201
    body = r.json()
    assert body["amount"] == "250.00"
    assert two_accounts.get("/api/transactions/T1").json()["id"] == "T1"


def test_timestamp_normalised_to_utc(two_accounts):
    r = two_accounts.post("/api/transactions", json=tx(timestamp="2026-03-01T15:30:00+05:30"))
    assert r.json()["timestamp"] == "2026-03-01T10:00:00Z"


@pytest.mark.parametrize(
    "override",
    [
        {"amount": "0"},
        {"amount": "-5.00"},
        {"amount": "1.234"},  # more than 2 decimal places
        {"timestamp": "2026-03-01T10:00:00"},  # naive: no timezone
        {"currency": "usd"},
        {"target_account_id": "A"},  # self-transfer
    ],
)
def test_invalid_transactions_rejected(two_accounts, override):
    assert two_accounts.post("/api/transactions", json=tx(**override)).status_code == 422


def test_unknown_account_rejected(two_accounts):
    r = two_accounts.post("/api/transactions", json=tx(target_account_id="GHOST"))
    assert r.status_code == 422


def test_identical_replay_is_idempotent(two_accounts):
    first = two_accounts.post("/api/transactions", json=tx())
    second = two_accounts.post("/api/transactions", json=tx())
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["ingested_at"] == second.json()["ingested_at"]
    assert len(two_accounts.get("/api/transactions").json()) == 1


def test_same_id_different_content_conflicts(two_accounts):
    two_accounts.post("/api/transactions", json=tx())
    r = two_accounts.post("/api/transactions", json=tx(amount="999.00"))
    assert r.status_code == 409


def test_list_orders_newest_first_and_filters_by_account(two_accounts):
    two_accounts.post("/api/accounts", json={"id": "C", "name": "C", "account_type": "business"})
    two_accounts.post("/api/transactions", json=tx(id="T1", timestamp="2026-03-01T10:00:00Z"))
    two_accounts.post("/api/transactions", json=tx(id="T2", timestamp="2026-03-01T11:00:00Z"))
    two_accounts.post(
        "/api/transactions",
        json=tx(id="T3", source_account_id="B", target_account_id="C", timestamp="2026-03-01T12:00:00Z"),
    )
    assert [t["id"] for t in two_accounts.get("/api/transactions").json()] == ["T3", "T2", "T1"]
    assert [t["id"] for t in two_accounts.get("/api/transactions?account_id=C").json()] == ["T3"]
    assert len(two_accounts.get("/api/transactions?account_id=B").json()) == 3  # B is in all three
    assert len(two_accounts.get("/api/transactions?limit=1").json()) == 1
    assert two_accounts.get("/api/transactions?limit=501").status_code == 422


def test_database_enforces_foreign_keys_even_if_code_does_not(db_path):
    conn = connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transactions VALUES ('X','NO1','NO2',100,'USD','t','t')"
        )
    conn.close()
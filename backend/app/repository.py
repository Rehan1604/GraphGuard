"""All SQL lives here. Routes never write SQL; they call these functions."""
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from app.schemas import Account, AccountCreate, Transaction, TransactionCreate


class DuplicateAccountError(Exception):
    pass


class UnknownAccountError(Exception):
    pass


class ConflictingTransactionError(Exception):
    """Same transaction id, different content."""


def _iso(dt: datetime) -> str:
    """Fixed-width UTC string, so lexicographic order == chronological order."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _to_cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_exact())


def _account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        name=row["name"],
        account_type=row["account_type"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _transaction(row: sqlite3.Row) -> Transaction:
    return Transaction(
        id=row["id"],
        source_account_id=row["source_account_id"],
        target_account_id=row["target_account_id"],
        amount=Decimal(row["amount_cents"]).scaleb(-2),
        currency=row["currency"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        ingested_at=datetime.fromisoformat(row["ingested_at"]),
    )


# ---- accounts -------------------------------------------------------------

def create_account(conn: sqlite3.Connection, data: AccountCreate) -> Account:
    try:
        conn.execute(
            "INSERT INTO accounts (id, name, account_type, created_at) VALUES (?, ?, ?, ?)",
            (data.id, data.name, data.account_type, _now_iso()),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise DuplicateAccountError(data.id) from exc
    return get_account(conn, data.id)  # type: ignore[return-value]


def get_account(conn: sqlite3.Connection, account_id: str) -> Account | None:
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return _account(row) if row else None


def list_accounts(conn: sqlite3.Connection) -> list[Account]:
    rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    return [_account(r) for r in rows]


# ---- transactions ---------------------------------------------------------

def get_transaction(conn: sqlite3.Connection, tx_id: str) -> Transaction | None:
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    return _transaction(row) if row else None


def _same_content(existing: Transaction, new: TransactionCreate) -> bool:
    return (
        existing.source_account_id == new.source_account_id
        and existing.target_account_id == new.target_account_id
        and existing.amount == new.amount
        and existing.currency == new.currency
        and existing.timestamp == new.timestamp
    )


def create_transaction(
    conn: sqlite3.Connection, data: TransactionCreate
) -> tuple[Transaction, bool]:
    """Returns (transaction, created). created=False means an identical
    transaction with this id already existed (idempotent replay)."""
    existing = get_transaction(conn, data.id)
    if existing:
        if _same_content(existing, data):
            return existing, False
        raise ConflictingTransactionError(data.id)

    for account_id in (data.source_account_id, data.target_account_id):
        if get_account(conn, account_id) is None:
            raise UnknownAccountError(account_id)

    try:
        conn.execute(
            """INSERT INTO transactions
               (id, source_account_id, target_account_id, amount_cents,
                currency, timestamp, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data.id,
                data.source_account_id,
                data.target_account_id,
                _to_cents(data.amount),
                data.currency,
                _iso(data.timestamp),
                _now_iso(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        # Lost a race with a concurrent insert of the same id: re-check it.
        conn.rollback()
        existing = get_transaction(conn, data.id)
        if existing and _same_content(existing, data):
            return existing, False
        raise ConflictingTransactionError(data.id) from exc
    return get_transaction(conn, data.id), True  # type: ignore[return-value]


def list_transactions(
    conn: sqlite3.Connection,
    account_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Transaction]:
    sql = "SELECT * FROM transactions"
    params: list[object] = []
    if account_id:
        sql += " WHERE source_account_id = ? OR target_account_id = ?"
        params += [account_id, account_id]
    sql += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return [_transaction(r) for r in conn.execute(sql, params).fetchall()]

def all_transactions_chronological(conn: sqlite3.Connection) -> list[Transaction]:
    rows = conn.execute("SELECT * FROM transactions ORDER BY timestamp, id").fetchall()
    return [_transaction(r) for r in rows]


def transactions_since(conn: sqlite3.Connection, since: datetime) -> list[Transaction]:
    rows = conn.execute(
        "SELECT * FROM transactions WHERE timestamp >= ? ORDER BY timestamp, id", (_iso(since),)
    ).fetchall()
    return [_transaction(r) for r in rows]

# Public names used by the alerts package
now_iso = _now_iso
to_iso = _iso
row_to_transaction = _transaction
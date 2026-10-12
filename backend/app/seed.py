"""Load a small, deterministic synthetic dataset: python -m app.seed
Safe to run repeatedly: identical ids replay idempotently."""
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app import repository as repo
from app.config import get_settings
from app.db import connect, init_db
from app.schemas import AccountCreate, TransactionCreate


def seed() -> tuple[int, int]:
    path = get_settings().database_path
    init_db(path)
    rng = random.Random(42)
    base = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
    conn = connect(path)
    try:
        ids = [f"ACC{n:03d}" for n in range(1, 13)]
        for i, acc_id in enumerate(ids):
            try:
                repo.create_account(
                    conn,
                    AccountCreate(
                        id=acc_id,
                        name=f"Synthetic Account {i + 1}",
                        account_type="business" if i % 3 == 0 else "individual",
                    ),
                )
            except repo.DuplicateAccountError:
                pass
        for n in range(1, 41):
            src, dst = rng.sample(ids, 2)
            repo.create_transaction(
                conn,
                TransactionCreate(
                    id=f"TX{n:04d}",
                    source_account_id=src,
                    target_account_id=dst,
                    amount=Decimal(rng.randint(500, 250000)) / 100,
                    timestamp=base + timedelta(minutes=17 * n + rng.randint(0, 9)),
                ),
            )
        return len(ids), 40
    finally:
        conn.close()


if __name__ == "__main__":
    accounts, txs = seed()
    print(f"Seeded {accounts} accounts and {txs} transactions.")
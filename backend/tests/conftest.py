import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import connect, get_db, init_db
from app.main import app
from app.ratelimit import limiter


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def isolated_default_database(tmp_path, monkeypatch):
    """No test may touch the real data/graphguard.db, and none may depend on it already existing
    (a fresh CI machine has no such file, which is how a hidden dependency once slipped through)."""
    monkeypatch.setenv("GRAPHGUARD_DATABASE_PATH", str(tmp_path / "default.db"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def client(db_path):
    """A client wired to a fresh temporary database for each test."""

    def override():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def two_accounts(client):
    for acc_id in ("A", "B"):
        client.post("/api/accounts", json={"id": acc_id, "name": acc_id, "account_type": "individual"})
    return client


def tx(**overrides):
    body = {
        "id": "T1",
        "source_account_id": "A",
        "target_account_id": "B",
        "amount": "250.00",
        "currency": "USD",
        "timestamp": "2026-03-01T10:00:00Z",
    }
    body.update(overrides)
    return body
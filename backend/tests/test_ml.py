"""Tests for the ML triage layer: features, model safety, fallback, migration, and the API fields."""
import shutil
import sqlite3

import pytest

from app.config import get_settings
from app.db import init_db, migrate
from app.ml import features as F
from app.ml.model import DEFAULT_MODEL, get_model, load_model
from app.ml.service import score_findings_if_enabled
from tests.test_alerts import chain_client  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def fresh_model_cache():
    get_model.cache_clear()
    yield
    get_model.cache_clear()


def test_feature_sets_are_consistent():
    assert len(set(F.SHAPE_FEATURES)) == len(F.SHAPE_FEATURES)
    assert not set(F.SHAPE_FEATURES) & set(F.SCALE_FEATURES)
    assert set(F.SHAPE_FEATURES) <= set(F.LABELS)
    assert tuple(F.FEATURE_SETS["shape"]) == tuple(F.SHAPE_FEATURES)


def test_shipped_model_loads_and_scores_in_range():
    model = load_model(DEFAULT_MODEL)
    assert model is not None, "the shipped model must load (fingerprint must match)"
    row = {name: 0.0 for name in F.SHAPE_FEATURES}
    assert 0.0 <= model.probabilities([row])[0] <= 1.0
    assert len(model.explain(row)) <= 4


def test_tampered_model_is_refused(tmp_path):
    copy = tmp_path / "triage.joblib"
    shutil.copy(DEFAULT_MODEL, copy)
    shutil.copy(DEFAULT_MODEL.with_suffix(".json"), copy.with_suffix(".json"))
    assert load_model(copy) is not None
    copy.write_bytes(copy.read_bytes() + b"x")
    assert load_model(copy) is None


def test_missing_or_garbage_model_means_rules_only(tmp_path):
    assert load_model(tmp_path / "nope.joblib") is None
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a model")
    bad.with_suffix(".json").write_text('{"sha256": "0"}')
    assert load_model(bad) is None


def test_switched_off_returns_no_scores(monkeypatch):
    monkeypatch.setenv("GRAPHGUARD_ML_ENABLED", "false")
    get_settings.cache_clear()
    assert score_findings_if_enabled([object()], [], 60) == [None]


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY, rule TEXT)")
    migrate(conn)
    migrate(conn)  # safe to repeat
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
    conn.close()
    assert {"ml_score", "ml_verdict", "ml_model", "ml_drivers_json"} <= cols


def test_init_db_is_idempotent(tmp_path):
    p = tmp_path / "x.db"
    init_db(p)
    init_db(p)


def test_alerts_carry_triage_fields(chain_client):
    chain_client.post("/api/alerts/scan")
    body = chain_client.get("/api/alerts").json()
    items = body["items"] if isinstance(body, dict) else body
    assert items, "the chain scenario should raise an alert"
    first = items[0]
    assert "ml_score" in first and "ml_verdict" in first
    detail = chain_client.get(f"/api/alerts/{first['id']}").json()
    assert "ml_drivers" in detail and "ml_model" in detail
    if first["ml_score"] is not None:
        assert 0.0 <= first["ml_score"] <= 1.0

"""Milestone 9: configuration, logging, errors, headers, limits."""
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.db import init_db
from app.logging_config import JsonFormatter, redact_text, setup_logging, remove_logging_handlers
from app.main import create_app
from app.ratelimit import RateLimiter


def make_app(tmp_path, **overrides):
    values = {"environment": "test", "database_path": tmp_path / "t.db", **overrides}
    settings = Settings(_env_file=None, **values)
    init_db(settings.database_path)
    return create_app(settings), settings


@pytest.fixture
def client(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as c:
        yield c


# ---------- configuration ----------

def test_defaults_are_valid():
    Settings(_env_file=None).validate_for_environment()


def test_wildcard_cors_is_refused():
    with pytest.raises(ConfigError, match="cors_origins"):
        Settings(_env_file=None, cors_origins=["*"]).validate_for_environment()


def test_origin_with_path_is_refused():
    with pytest.raises(ConfigError, match="path"):
        Settings(_env_file=None, cors_origins=["http://localhost:5173/app"]).validate_for_environment()


def test_unknown_provider_is_refused():
    with pytest.raises(ConfigError, match="unknown provider"):
        Settings(_env_file=None, llm_provider="banana").validate_for_environment()


def test_production_with_ai_needs_model_and_key():
    s = Settings(_env_file=None, environment="production", llm_provider="anthropic")
    with pytest.raises(ConfigError) as err:
        s.validate_for_environment()
    assert "llm_model" in str(err.value) and "llm_api_key" in str(err.value)


def test_blank_values_mean_unset():
    s = Settings(_env_file=None, llm_model="", llm_base_url="  ", llm_api_key="", docs_enabled="")
    assert s.llm_model is None and s.llm_base_url is None and s.llm_api_key is None and s.docs_enabled is None


def test_bad_environment_value_is_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="staging")


def test_summary_never_contains_the_key():
    s = Settings(_env_file=None, llm_provider="anthropic", llm_model="m", llm_api_key="sk-supersecretvalue123")
    text = json.dumps(s.summary())
    assert "supersecret" not in text
    assert s.summary()["llm_key_present"] is True
    assert "supersecret" not in repr(s)


def test_app_refuses_to_start_on_bad_config(tmp_path):
    app, _ = make_app(tmp_path, llm_provider="banana")
    with pytest.raises(ConfigError):
        with TestClient(app):
            pass


def test_docs_follow_environment(tmp_path):
    dev, _ = make_app(tmp_path, environment="development")
    prod, _ = make_app(tmp_path, environment="production")
    forced, _ = make_app(tmp_path, environment="production", docs_enabled=True)
    with TestClient(dev) as c:
        assert c.get("/docs").status_code == 200
    with TestClient(prod) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
    with TestClient(forced) as c:
        assert c.get("/docs").status_code == 200


# ---------- logging ----------

def test_redaction():
    assert "sk-abcdef123456" not in redact_text("key sk-abcdef123456 used")
    assert "abc.def.ghi12345" not in redact_text("Authorization: Bearer abc.def.ghi12345")
    assert "hunter2" not in redact_text("password=hunter2")
    assert redact_text("plain message") == "plain message"


def test_json_logs_are_json_and_redacted():
    stream = io.StringIO()
    setup_logging("INFO", "json", stream)
    try:
        logging.getLogger("t").info("calling with api_key=sk-leakleakleak1", extra={"path": "/x"})
    finally:
        remove_logging_handlers()
    line = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert line["level"] == "INFO" and line["path"] == "/x"
    assert "leakleak" not in stream.getvalue()


def test_exception_logs_are_redacted():
    stream = io.StringIO()
    setup_logging("INFO", "json", stream)
    try:
        try:
            raise RuntimeError("bad token=abcdef123456")
        except RuntimeError:
            logging.getLogger("t").exception("failed")
    finally:
        remove_logging_handlers()
    assert "abcdef123456" not in stream.getvalue()


def test_access_log_has_path_but_not_query(tmp_path):
    app, _ = make_app(tmp_path)
    stream = io.StringIO()
    with TestClient(app) as c:
        setup_logging("INFO", "json", stream)  # after startup so our handler is the one in use
        try:
            c.get("/api/accounts?x=ACCOUNT_SECRET_42")
        finally:
            remove_logging_handlers()
    out = stream.getvalue()
    assert "/api/accounts" in out
    assert "ACCOUNT_SECRET_42" not in out


# ---------- request ids, headers, errors ----------

def test_request_id_generated_and_echoed(client):
    r = client.get("/api/health")
    assert len(r.headers["x-request-id"]) >= 16
    r2 = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert r2.headers["x-request-id"] == "abc-123"


def test_bad_request_id_is_replaced(client):
    r = client.get("/api/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert r.headers["x-request-id"] != "bad id\twith spaces"
    assert " " not in r.headers["x-request-id"]


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_live_page_gets_its_own_csp(client):
    r = client.get("/live")
    assert r.status_code == 200
    assert "script-src" in r.headers["content-security-policy"]
    assert "x-frame-options" in r.headers


def test_validation_error_does_not_echo_input(client):
    r = client.post("/api/accounts", json={"id": "A", "name": "SENSITIVE_NAME_VALUE", "account_type": "nonsense"})
    assert r.status_code == 422
    assert "SENSITIVE_NAME_VALUE" not in r.text
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_oversized_body_rejected(tmp_path):
    app, _ = make_app(tmp_path, max_request_body_bytes=2000)
    with TestClient(app) as c:
        r = c.post("/api/accounts", content=b"x" * 5000, headers={"Content-Type": "application/json"})
        assert r.status_code == 413
        assert "x-request-id" in r.headers


def test_unhandled_error_is_generic_and_logged(tmp_path, caplog):
    app, _ = make_app(tmp_path)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail path=C:/private")

    with TestClient(app, raise_server_exceptions=False) as c:
        with caplog.at_level(logging.ERROR):
            r = c.get("/boom")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text
    assert r.json()["detail"] == "Internal server error"
    assert r.headers["x-request-id"] == r.json()["request_id"]
    assert "x-content-type-options" in r.headers
    assert any("secret internal detail" in (rec.exc_text or "") or rec.exc_info for rec in caplog.records)


def test_database_failure_returns_503_without_details(tmp_path):
    import sqlite3
    app, _ = make_app(tmp_path)

    @app.get("/dbfail")
    def dbfail():
        raise sqlite3.OperationalError("unable to open database file /secret/path.db")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/dbfail")
    assert r.status_code == 503
    assert "secret" not in r.text


# ---------- health vs readiness ----------

def test_health_and_ready(client):
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_ready_reports_unavailable_when_db_is_broken(tmp_path):
    app, settings = make_app(tmp_path)
    with TestClient(app) as c:
        settings.database_path = tmp_path  # a folder, not a file: SQLite cannot open it
        r = c.get("/api/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"
    assert str(tmp_path) not in r.text


def test_ready_is_false_when_tables_are_missing(tmp_path):
    app, settings = make_app(tmp_path)
    with TestClient(app) as c:
        settings.database_path = tmp_path / "empty.db"  # exists after connect, but has no tables
        r = c.get("/api/ready")
    assert r.status_code == 503


# ---------- CORS ----------

def test_cors_allows_listed_origin_only(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-credentials" not in ok.headers
    no = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in no.headers


def test_cors_preflight_limits_methods(client):
    r = client.options("/api/accounts", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE"})
    assert r.status_code == 400


def test_cors_headers_present_on_error_responses(client):
    r = client.post("/api/accounts", json={}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 422
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ---------- rate limiting ----------

def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter(clock=lambda: now[0])
    assert all(rl.check("a", 3) is None for _ in range(3))
    wait = rl.check("a", 3)
    assert wait is not None and wait >= 1
    assert rl.check("b", 3) is None  # other clients unaffected
    now[0] = 61
    assert rl.check("a", 3) is None  # window slid


def test_expensive_endpoint_returns_429_with_retry_after(tmp_path):
    app, _ = make_app(tmp_path, rate_limit_per_minute=2)
    with TestClient(app) as c:
        assert c.post("/api/alerts/scan").status_code == 200
        assert c.post("/api/alerts/scan").status_code == 200
        r = c.post("/api/alerts/scan")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1


def test_cheap_endpoints_are_not_limited(tmp_path):
    app, _ = make_app(tmp_path, rate_limit_per_minute=1)
    with TestClient(app) as c:
        assert all(c.get("/api/health").status_code == 200 for _ in range(5))


def test_default_app_follows_environment_settings_at_startup(tmp_path, monkeypatch):
    """Regression: the module-level app must not freeze its settings at import time."""
    from app.config import get_settings
    from app.main import app as default_app

    target = tmp_path / "from_env.db"
    monkeypatch.setenv("GRAPHGUARD_DATABASE_PATH", str(target))
    get_settings.cache_clear()
    try:
        with TestClient(default_app) as c:
            assert target.exists()
            assert c.get("/api/ready").status_code == 200
    finally:
        get_settings.cache_clear()

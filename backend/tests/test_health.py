from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok_payload():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "GraphGuard API"
    assert "server_time" in body


def test_cors_allows_frontend_origin():
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_blocks_unknown_origin():
    response = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
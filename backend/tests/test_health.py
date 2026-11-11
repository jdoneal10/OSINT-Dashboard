from __future__ import annotations

from fastapi.testclient import TestClient

from app.worker import heartbeat


def test_health_reports_db_and_postgis(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["postgis_version"].startswith("3.")
    assert body["worker_last_heartbeat"] is None


def test_health_reports_worker_heartbeat(client: TestClient) -> None:
    heartbeat()
    assert client.get("/health").json()["worker_last_heartbeat"] is not None


def test_cors_allows_only_vite_origin(client: TestClient) -> None:
    ok = client.get("/health", headers={"Origin": "http://localhost:5173"})
    bad = client.get("/health", headers={"Origin": "https://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers

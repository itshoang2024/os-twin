from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.api import app


def test_first_run_login_persists_api_key_and_username(monkeypatch, tmp_path):
    monkeypatch.setenv("OSTWIN_HOME", str(tmp_path / ".ostwin"))
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)
    monkeypatch.delenv("OSTWIN_USERNAME", raising=False)

    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.post(
        "/api/auth/token",
        json={"key": "ostwin_first_run_key", "username": "Ada Lovelace"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "Ada Lovelace"
    assert response.cookies.get("ostwin_auth_key") == "ostwin_first_run_key"
    assert Path(tmp_path / ".ostwin" / ".env").read_text().splitlines() == [
        "OSTWIN_API_KEY=ostwin_first_run_key",
        "OSTWIN_USERNAME='Ada Lovelace'",
    ]

    me = client.get("/api/auth/me", headers={"X-API-Key": "ostwin_first_run_key"})
    assert me.status_code == 200
    assert me.json()["username"] == "Ada Lovelace"


def test_existing_api_key_login_can_update_display_username(monkeypatch, tmp_path):
    monkeypatch.setenv("OSTWIN_HOME", str(tmp_path / ".ostwin"))
    monkeypatch.setenv("OSTWIN_API_KEY", "existing-key")
    monkeypatch.delenv("OSTWIN_USERNAME", raising=False)

    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.post(
        "/api/auth/token",
        json={"key": "existing-key", "username": "Grace Hopper"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "Grace Hopper"
    assert "OSTWIN_USERNAME='Grace Hopper'" in Path(tmp_path / ".ostwin" / ".env").read_text()


def test_first_run_requires_username(monkeypatch, tmp_path):
    monkeypatch.setenv("OSTWIN_HOME", str(tmp_path / ".ostwin"))
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)
    monkeypatch.delenv("OSTWIN_USERNAME", raising=False)

    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.post("/api/auth/token", json={"key": "ostwin_first_run_key"})

    assert response.status_code == 401
    assert response.json()["setup_required"] is True
    assert not (tmp_path / ".ostwin" / ".env").exists()

import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from dashboard.lib.settings import github_copilot_auth as copilot


def test_copilot_session_status_reports_connected_from_current_auth(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "access": "access-secret"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)

    assert copilot.get_github_copilot_session_status().connected is True


def test_copilot_session_status_accepts_legacy_copilot_key(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"copilot": {"type": "oauth", "refresh": "refresh-secret"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)

    assert copilot.get_github_copilot_session_status().connected is True


def test_start_github_oauth_builds_authorization_url(monkeypatch):
    monkeypatch.setattr(copilot, "_CLIENT_ID", "client-123")
    monkeypatch.setattr(copilot, "_REDIRECT_URI", "http://localhost:3366/api/settings/github/oauth/callback")
    copilot._pending_oauth.clear()

    response = copilot.start_github_copilot_oauth()
    parsed = urlparse(response.authorization_url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "github.com"
    assert parsed.path == "/login/oauth/authorize"
    assert params["client_id"] == ["client-123"]
    assert params["redirect_uri"] == ["http://localhost:3366/api/settings/github/oauth/callback"]
    assert params["code_challenge_method"] == ["S256"]
    assert response.state in copilot._pending_oauth

    copilot._pending_oauth.clear()


def test_exchange_oauth_code_writes_opencode_auth(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    state = "state-123"
    verifier = "verifier-abc"

    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    monkeypatch.setattr(copilot, "_CLIENT_ID", "client-123")
    monkeypatch.setattr(copilot, "_CLIENT_SECRET", "secret-123")
    monkeypatch.setattr(copilot, "_REDIRECT_URI", "http://localhost:3366/api/settings/github/oauth/callback")
    monkeypatch.setattr(copilot, "_refresh_models_after_auth", lambda: None)
    monkeypatch.setattr(
        copilot,
        "_post_github_form",
        lambda url, data: {"access_token": "gho-secret", "scope": "read:user", "token_type": "bearer"},
    )

    with copilot._auth_lock:
        copilot._pending_oauth[state] = {"verifier": verifier, "created_at": time.time()}

    copilot.exchange_github_copilot_oauth_code("code-xyz", state)

    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert auth["github-copilot"]["type"] == "oauth"
    assert auth["github-copilot"]["access"] == "gho-secret"
    assert auth["github-copilot"]["token"] == "gho-secret"


def test_start_device_auth_requests_github_device_code(monkeypatch):
    monkeypatch.setattr(copilot, "_CLIENT_ID", "client-123")
    monkeypatch.setattr(
        copilot,
        "_post_github_form",
        lambda url, data: {
            "device_code": "device-secret",
            "user_code": "C73C-CD17",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 900,
        },
    )
    monkeypatch.setattr(copilot.threading.Thread, "start", lambda self: None)
    copilot._device_auth_session = None

    response = copilot.start_github_copilot_device_auth()

    assert response.status == "pending"
    assert response.verification_url == "https://github.com/login/device"
    assert response.user_code == "C73C-CD17"

    copilot._device_auth_session = None

import json

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


def test_opencode_native_github_oauth_token_is_connected(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "access": "gho_secret", "refresh": "gho_secret"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)

    assert copilot.get_github_copilot_session_status().connected is True


def test_start_github_oauth_returns_authorization_url(monkeypatch):
    monkeypatch.setattr(copilot, "GITHUB_OAUTH_CLIENT_ID", "client-id")
    copilot._pending_oauth.clear()

    response = copilot.start_github_copilot_oauth()

    assert response.authorization_url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-id" in response.authorization_url
    assert response.state in copilot._pending_oauth
    copilot._pending_oauth.clear()


def test_exchange_github_oauth_saves_opencode_copilot_shape(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    monkeypatch.setattr(copilot, "GITHUB_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(copilot, "GITHUB_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(copilot, "_refresh_models_after_auth", lambda: None)
    monkeypatch.setattr(copilot, "_validate_github_copilot_token", lambda token: None)
    monkeypatch.setattr(copilot, "sync_github_copilot_opencode_config", lambda **kwargs: None)
    monkeypatch.setattr(copilot, "_post_github_form", lambda url, data: {"access_token": "gho_browser"})
    copilot._pending_oauth["state"] = {"verifier": "verifier", "created_at": copilot.time.time()}

    copilot.exchange_github_copilot_oauth_code("code", "state")

    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert auth["github-copilot"] == {
        "type": "oauth",
        "refresh": "gho_browser",
        "access": "gho_browser",
        "expires": 0,
    }


def test_exchange_github_oauth_rejects_non_copilot_token(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    monkeypatch.setattr(copilot, "GITHUB_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(copilot, "GITHUB_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(copilot, "_post_github_form", lambda url, data: {"access_token": "gho_browser"})

    def reject(token):
        raise RuntimeError("GitHub browser OAuth succeeded, but GitHub Copilot rejected that token.")

    monkeypatch.setattr(copilot, "_validate_github_copilot_token", reject)
    copilot._pending_oauth["state"] = {"verifier": "verifier", "created_at": copilot.time.time()}

    with pytest.raises(RuntimeError, match="Copilot rejected"):
        copilot.exchange_github_copilot_oauth_code("code", "state")

    assert not auth_path.exists()


def test_exchange_copilot_token_returns_token_and_api_url(monkeypatch):
    """_exchange_copilot_token should call the internal token endpoint and parse result."""
    exchange_payload = {
        "token": "tid_abc123",
        "expires_at": 9999999999,
        "endpoints": {"api": "https://api.githubcopilot.com"},
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def read(self):
            return json.dumps(exchange_payload).encode()

    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        return _Resp()

    monkeypatch.setattr(copilot.urllib.request, "urlopen", fake_urlopen)
    # Clear cache so a real exchange is triggered.
    copilot._copilot_token_cache.clear()

    result = copilot._exchange_copilot_token("gho_secret")

    assert captured["url"] == copilot.GITHUB_TOKEN_URL
    assert captured["auth"] == "token gho_secret"
    assert result["token"] == "tid_abc123"
    assert result["api_url"] == "https://api.githubcopilot.com"


def test_exchange_copilot_token_uses_cache(monkeypatch):
    """A cached non-expired entry should be returned without a network call."""
    future_exp = copilot.time.time() + 3600
    copilot._copilot_token_cache["gho_cached"] = {
        "token": "cached_tok",
        "api_url": "https://api.githubcopilot.com",
        "expires_at": future_exp,
    }

    calls = []
    monkeypatch.setattr(
        copilot.urllib.request,
        "urlopen",
        lambda *a, **kw: calls.append(1),
    )

    result = copilot._exchange_copilot_token("gho_cached")

    assert result["token"] == "cached_tok"
    assert calls == []
    copilot._copilot_token_cache.pop("gho_cached", None)


def test_fetch_copilot_model_ids_reads_data_ids(monkeypatch):
    """_fetch_copilot_model_ids should exchange the gho token, then call /models."""
    exchange_payload = {
        "token": "cpilot_tok",
        "expires_at": 9999999999,
        "endpoints": {"api": "https://api.githubcopilot.com"},
    }
    models_payload = {"data": [{"id": "gpt-a"}, {"id": "gpt-b"}, {"name": "fallback-name"}]}

    responses = iter([exchange_payload, models_payload])
    captured_requests = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def read(self):
            return json.dumps(self._payload).encode()

    def fake_urlopen(req, timeout=None):
        captured_requests.append({"url": req.full_url, "auth": req.headers.get("Authorization")})
        return _Resp(next(responses))

    monkeypatch.setattr(copilot.urllib.request, "urlopen", fake_urlopen)
    copilot._copilot_token_cache.clear()

    result = copilot._fetch_copilot_model_ids("gho_secret")

    assert result == ["gpt-a", "gpt-b", "fallback-name"]
    # First call: token exchange
    assert captured_requests[0]["url"] == copilot.GITHUB_TOKEN_URL
    assert captured_requests[0]["auth"] == "token gho_secret"
    # Second call: models list using exchanged copilot token
    assert captured_requests[1]["url"] == "https://api.githubcopilot.com/models"
    assert captured_requests[1]["auth"] == "Bearer cpilot_tok"
    copilot._copilot_token_cache.clear()


def test_sync_github_copilot_opencode_config_strips_legacy_alias(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "refresh": "gho_secret", "access": "gho_secret"}}),
        encoding="utf-8",
    )
    user_config = tmp_path / "user" / "opencode.json"
    managed_config = tmp_path / "managed" / "opencode.json"
    project_dir = tmp_path / "project"
    project_config = project_dir / ".opencode" / "opencode.json"

    legacy_block = {
        "github-copilot-oauth": {
            "npm": "@ai-sdk/openai-compatible",
            "options": {"apiKey": "{env:GITHUB_COPILOT_TOKEN}"},
            "models": {"gpt-old": {"name": "gpt-old (Copilot)"}},
        }
    }
    for path in (user_config, managed_config, project_config):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"provider": dict(legacy_block), "mcp": {"memory": {"type": "local"}}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    monkeypatch.setattr(copilot, "get_user_opencode_config_path", lambda: user_config)
    monkeypatch.setattr(copilot, "get_managed_opencode_config_path", lambda: managed_config)
    monkeypatch.setattr(copilot, "_fetch_copilot_model_ids", lambda token: ["gpt-a", "gpt-b"])
    monkeypatch.setattr(copilot, "_refresh_models_after_auth", lambda: None)

    result = copilot.sync_github_copilot_opencode_config(project_dir=project_dir)

    assert result.synced is True
    assert sorted(result.models) == ["gpt-a", "gpt-b"]
    for path in (user_config, managed_config, project_config):
        data = json.loads(path.read_text(encoding="utf-8"))
        # The deprecated alias is removed.
        assert "github-copilot-oauth" not in data.get("provider", {})
        # Unrelated config is preserved.
        assert data["mcp"] == {"memory": {"type": "local"}}


def test_sync_github_copilot_opencode_config_skips_missing_project_config(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "refresh": "gho_secret"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    monkeypatch.setattr(copilot, "get_user_opencode_config_path", lambda: tmp_path / "user.json")
    monkeypatch.setattr(copilot, "get_managed_opencode_config_path", lambda: tmp_path / "managed.json")
    monkeypatch.setattr(copilot, "_fetch_copilot_model_ids", lambda token: ["gpt-a"])
    monkeypatch.setattr(copilot, "_refresh_models_after_auth", lambda: None)

    result = copilot.sync_github_copilot_opencode_config(project_dir=tmp_path / "missing-project")

    assert result.synced is True
    assert str(tmp_path / "missing-project" / ".opencode" / "opencode.json") in result.skipped


def test_clear_broken_copilot_auth_preserves_opencode_native_token(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "github-copilot": {"type": "oauth", "access": "gho_secret", "refresh": "gho_secret"},
                "openai": {"type": "oauth", "access": "openai-token"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)

    copilot._clear_broken_copilot_auth()

    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert auth["github-copilot"]["access"] == "gho_secret"
    assert auth["openai"]["access"] == "openai-token"


def test_device_status_prefers_saved_auth_over_stale_session(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "access": "gho_secret", "refresh": "gho_secret"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    copilot._device_auth_session = {"status": "error", "message": "old terminal output"}

    response = copilot.get_github_copilot_device_auth_status()

    assert response.connected is True
    assert response.status == "connected"
    assert response.message == "GitHub Copilot connected."
    copilot._device_auth_session = None


def test_start_device_auth_requests_github_device_code(tmp_path, monkeypatch):
    calls = []
    auth_path = tmp_path / "auth.json"

    def fake_post(url, data, **kwargs):
        calls.append((url, data, kwargs))
        return {
            "device_code": "device-secret",
            "user_code": "C73C-CD17",
            "verification_uri": "https://github.com/login/device",
            "interval": 1,
            "expires_in": 900,
        }

    monkeypatch.setattr(copilot, "_clear_broken_copilot_auth", lambda: None)
    monkeypatch.setattr(copilot, "_post_github_form", fake_post)
    monkeypatch.setattr(copilot.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    copilot._device_auth_session = None

    response = copilot.start_github_copilot_device_auth()

    assert calls == [
        (
            "https://github.com/login/device/code",
            {"client_id": copilot.OPENCODE_COPILOT_CLIENT_ID, "scope": "read:user"},
            {},
        )
    ]
    assert response.status == "pending"
    assert response.verification_url == "https://github.com/login/device"
    assert response.user_code == "C73C-CD17"

    copilot._device_auth_session = None


def test_poll_github_device_auth_saves_oauth_token(monkeypatch):
    saved = []
    payloads = iter(
        [
            {"error": "authorization_pending"},
            {"access_token": "gho_secret"},
        ]
    )
    session = {
        "status": "pending",
        "interval": 1,
        "expires_at": copilot.time.time() + 60,
    }

    monkeypatch.setattr(copilot, "_poll_github_device_token", lambda device_code: next(payloads))
    monkeypatch.setattr(copilot, "_save_github_oauth_token", lambda token: saved.append(token))
    monkeypatch.setattr(copilot.time, "sleep", lambda seconds: None)

    copilot._device_auth_session = session
    copilot._poll_github_device_auth(session, "device-secret")

    assert saved == ["gho_secret"]
    assert session["status"] == "connected"
    assert session["connected"] is True
    copilot._device_auth_session = None

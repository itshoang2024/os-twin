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


def test_fetch_copilot_model_ids_reads_data_ids(monkeypatch):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"data": [{"id": "gpt-a"}, {"id": "gpt-b"}, {"name": "fallback-name"}]}).encode()

    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["authorization"] = req.headers.get("Authorization")
        return _Response()

    monkeypatch.setattr(copilot.urllib.request, "urlopen", fake_urlopen)

    assert copilot._fetch_copilot_model_ids("secret-token") == ["gpt-a", "gpt-b", "fallback-name"]
    assert captured["url"] == "https://api.githubcopilot.com/models"
    assert captured["authorization"] == "Bearer secret-token"


def test_sync_github_copilot_opencode_config_writes_global_managed_and_project(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "refresh": "gho_secret", "access": "gho_secret"}}),
        encoding="utf-8",
    )
    user_config = tmp_path / "user" / "opencode.json"
    managed_config = tmp_path / "managed" / "opencode.json"
    project_dir = tmp_path / "project"
    project_config = project_dir / ".opencode" / "opencode.json"
    project_config.parent.mkdir(parents=True)
    project_config.write_text(json.dumps({"mcp": {"memory": {"type": "local"}}}), encoding="utf-8")

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
        provider = data["provider"]["github-copilot-oauth"]
        assert provider["options"]["apiKey"] == "{env:GITHUB_COPILOT_TOKEN}"
        assert "gho_secret" not in path.read_text(encoding="utf-8")
        assert sorted(provider["models"].keys()) == ["gpt-a", "gpt-b"]
    project_data = json.loads(project_config.read_text(encoding="utf-8"))
    assert project_data["mcp"] == {"memory": {"type": "local"}}


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


class _FakeProcess:
    returncode = None

    def poll(self):
        return self.returncode


def test_start_device_auth_runs_opencode_and_selects_github_dot_com(tmp_path, monkeypatch):
    calls = {}
    writes = []
    auth_path = tmp_path / "auth.json"
    output = iter(
        [
            "Select GitHub deployment type\n  GitHub.com\n  GitHub Enterprise\n",
            "Go to: https://github.com/login/device\nEnter code: C73C-CD17\n",
        ]
    )

    def fake_popen(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(copilot, "_clear_broken_copilot_auth", lambda: None)
    monkeypatch.setattr(copilot.pty, "openpty", lambda: (10, 11))
    monkeypatch.setattr(copilot.os, "close", lambda fd: None)
    monkeypatch.setattr(copilot.os, "write", lambda fd, data: writes.append((fd, data)) or len(data))
    monkeypatch.setattr(copilot.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(copilot, "_read_pty", lambda fd, timeout=0.2: next(output, ""))
    monkeypatch.setattr(copilot.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(copilot.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(copilot, "OPENCODE_AUTH_JSON", auth_path)
    copilot._device_auth_session = None

    response = copilot.start_github_copilot_device_auth()

    assert calls["command"] == [
        copilot.OPENCODE_BIN,
        "auth",
        "login",
        "-p",
        "github-copilot",
        "-m",
        "Login with GitHub Copilot",
    ]
    assert writes == [(10, b"\r")]
    assert response.status == "pending"
    assert response.verification_url == "https://github.com/login/device"
    assert response.user_code == "C73C-CD17"

    copilot._device_auth_session = None

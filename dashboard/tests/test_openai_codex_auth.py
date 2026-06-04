import base64
import json
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from dashboard.lib.settings import openai_codex_auth as codex


def _jwt_with_exp(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{payload}.signature"


def test_sanitized_redacts_token_like_values():
    text = 'access_token="abc.def-ghi" refresh_token: "secret.refresh-token" key sk-testsecretvalue'

    redacted = codex._sanitized(text)

    assert "sk-testsecretvalue" not in redacted
    assert "secret.refresh-token" not in redacted
    assert "[REDACTED]" in redacted


def test_save_openai_oauth_writes_native_and_plugin_files(tmp_path, monkeypatch):
    native_auth = tmp_path / "auth.json"
    native_auth.write_text(json.dumps({"anthropic": {"type": "api", "key": "sk-ant"}}), encoding="utf-8")
    plugin_auth = tmp_path / "openai.json"

    monkeypatch.setattr(codex, "OPENCODE_AUTH_JSON", native_auth)
    monkeypatch.setattr(codex, "CODEX_AUTH_JSON", plugin_auth)

    codex._save_openai_oauth(
        {
            "access": "access-secret",
            "refresh": "refresh-secret",
            "expires": 123456789,
        }
    )

    native = json.loads(native_auth.read_text(encoding="utf-8"))
    plugin = json.loads(plugin_auth.read_text(encoding="utf-8"))

    assert native["anthropic"] == {"type": "api", "key": "sk-ant"}
    assert native["openai"] == {
        "type": "oauth",
        "access": "access-secret",
        "refresh": "refresh-secret",
        "expires": 123456789,
    }
    assert plugin == native["openai"]
    assert oct(native_auth.stat().st_mode & 0o777) == "0o600"
    assert oct(plugin_auth.stat().st_mode & 0o777) == "0o600"


def test_import_codex_cli_auth_writes_opencode_oauth(tmp_path, monkeypatch):
    codex_auth = tmp_path / "codex-auth.json"
    native_auth = tmp_path / "auth.json"
    plugin_auth = tmp_path / "openai.json"
    access = _jwt_with_exp(2000000000)
    codex_auth.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": access,
                    "refresh_token": "refresh-secret",
                    "id_token": "id-secret",
                    "account_id": "acct",
                },
                "last_refresh": "2026-06-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(codex, "OPENCODE_AUTH_JSON", native_auth)
    monkeypatch.setattr(codex, "CODEX_AUTH_JSON", plugin_auth)
    monkeypatch.setattr(codex, "_refresh_models_after_auth", lambda: None)

    codex.import_codex_cli_auth_to_opencode(codex_auth)

    native = json.loads(native_auth.read_text(encoding="utf-8"))
    plugin = json.loads(plugin_auth.read_text(encoding="utf-8"))
    assert native["openai"] == {
        "type": "oauth",
        "access": access,
        "refresh": "refresh-secret",
        "expires": 2000000000 * 1000,
    }
    assert plugin == native["openai"]


def test_load_codex_cli_auth_rejects_missing_tokens(tmp_path):
    codex_auth = tmp_path / "codex-auth.json"
    codex_auth.write_text(json.dumps({"tokens": {"access_token": "access"}}), encoding="utf-8")

    try:
        codex._load_codex_cli_oauth_tokens(codex_auth)
    except RuntimeError as exc:
        assert "refresh_token" in str(exc)
    else:
        raise AssertionError("Expected missing refresh_token to fail")


def test_codex_session_status_reports_connected_from_native_auth(tmp_path, monkeypatch):
    native_auth = tmp_path / "auth.json"
    native_auth.write_text(
        json.dumps({"openai": {"type": "oauth", "access": "access-secret"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(codex, "OPENCODE_AUTH_JSON", native_auth)

    assert codex.get_codex_session_status().connected is True


def test_start_codex_device_auth_requires_codex_cli(monkeypatch):
    monkeypatch.setattr(codex, "_ensure_codex_plugin", lambda: None)
    monkeypatch.setattr(codex.shutil, "which", lambda name: None)

    try:
        codex.start_codex_device_auth()
    except RuntimeError as exc:
        assert "Codex CLI is not installed" in str(exc)
    else:
        raise AssertionError("Expected missing Codex CLI to fail")


def test_device_auth_stdout_patterns_parse_url_and_code():
    text = codex._strip_terminal_control(
        "Open https://auth.openai.com/codex/device\x1b[0m and enter ABCD-12345"
    )

    assert codex.DEVICE_URL_RE.search(text).group(0) == "https://auth.openai.com/codex/device"
    assert codex.DEVICE_CODE_RE.search(text).group(0) == "ABCD-12345"


def test_start_codex_oauth_builds_codex_cli_authorize_url(monkeypatch):
    monkeypatch.setattr(codex, "_ensure_codex_plugin", lambda: None)
    monkeypatch.setattr(codex, "_ensure_oauth_server", lambda: None)
    codex._pending_oauth.clear()

    response = codex.start_codex_oauth()
    parsed = urllib.parse.urlparse(response.authorization_url)
    params = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.openai.com"
    assert parsed.path == "/oauth/authorize"
    assert params["client_id"] == [codex.OPENAI_CLIENT_ID]
    assert params["redirect_uri"] == [codex.CODEX_REDIRECT_URI]
    assert params["scope"] == [codex.OPENAI_SCOPE]
    assert params["code_challenge_method"] == ["S256"]
    assert params["id_token_add_organizations"] == ["true"]
    assert params["codex_cli_simplified_flow"] == ["true"]
    assert params["originator"] == ["codex_cli_rs"]
    assert response.state in codex._pending_oauth
    assert codex._pending_oauth[response.state]["verifier"]

    codex._pending_oauth.clear()


def test_start_codex_oauth_prepares_plugin_before_authorize_url(monkeypatch):
    calls = []

    monkeypatch.setattr(codex, "OPENCODE_CONFIG_JSON", object())
    monkeypatch.setattr(codex, "OPENCODE_CONFIG_JSONC", object())
    monkeypatch.setattr(codex, "_read_config_text", lambda: "")
    monkeypatch.setattr(codex.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(codex, "_ensure_oauth_server", lambda: calls.append("server"))

    def fake_run(cmd, *, timeout=20):
        calls.append(cmd)
        return codex.CommandResult(command=cmd, exit_code=0)

    monkeypatch.setattr(codex, "_run", fake_run)
    codex._pending_oauth.clear()

    codex.start_codex_oauth()

    assert calls[0] == ["npx", "-y", codex.PLUGIN_SPEC, "--modern"]
    assert calls[1] == "server"
    codex._pending_oauth.clear()


def test_oauth_callback_writes_native_opencode_auth_json(tmp_path, monkeypatch):
    native_auth = tmp_path / "auth.json"
    plugin_auth = tmp_path / "openai.json"
    state = "state-123"
    verifier = "verifier-abc"

    monkeypatch.setattr(codex, "OPENCODE_AUTH_JSON", native_auth)
    monkeypatch.setattr(codex, "CODEX_AUTH_JSON", plugin_auth)
    monkeypatch.setattr(codex, "_refresh_models_after_auth", lambda: None)

    def fake_exchange(code, received_verifier):
        assert code == "code-xyz"
        assert received_verifier == verifier
        return {
            "access": "access-secret",
            "refresh": "refresh-secret",
            "expires": 999999,
        }

    monkeypatch.setattr(codex, "_exchange_code", fake_exchange)

    with codex._oauth_lock:
        codex._pending_oauth[state] = {
            "verifier": verifier,
            "created_at": time.time(),
        }

    server = ThreadingHTTPServer(("127.0.0.1", 0), codex._CodexOAuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/auth/callback?state={state}&code=code-xyz"
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        codex._pending_oauth.clear()

    assert "success" in body
    native = json.loads(native_auth.read_text(encoding="utf-8"))
    plugin = json.loads(plugin_auth.read_text(encoding="utf-8"))
    assert native["openai"] == {
        "type": "oauth",
        "access": "access-secret",
        "refresh": "refresh-secret",
        "expires": 999999,
    }
    assert plugin == native["openai"]

"""OpenAI Codex OAuth helpers for OpenCode.

The browser flow mirrors the Codex CLI/OpenCode OAuth handshake, writes the
result into OpenCode-owned credential files, and never returns token material
through the dashboard API.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


PLUGIN_PACKAGE = "opencode-openai-codex-auth"
DEFAULT_PLUGIN_VERSION = "4.4.0"
PLUGIN_VERSION = os.environ.get("OSTWIN_CODEX_AUTH_PLUGIN_VERSION", DEFAULT_PLUGIN_VERSION)
PLUGIN_SPEC = f"{PLUGIN_PACKAGE}@{PLUGIN_VERSION}"

OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_SCOPE = "openid profile email offline_access"
CODEX_CALLBACK_PORT = 1455
CODEX_REDIRECT_URI = f"http://localhost:{CODEX_CALLBACK_PORT}/auth/callback"

OPENCODE_CONFIG_JSON = Path.home() / ".config" / "opencode" / "opencode.json"
OPENCODE_CONFIG_JSONC = Path.home() / ".config" / "opencode" / "opencode.jsonc"
OPENCODE_AUTH_JSON = Path.home() / ".local" / "share" / "opencode" / "auth.json"
CODEX_AUTH_JSON = Path.home() / ".opencode" / "auth" / "openai.json"

TOKEN_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]+|"
    r"(access|refresh|id)_token['\"]?\s*[:=]\s*['\"]?[a-z0-9._-]+)"
)
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
DEVICE_URL_RE = re.compile(r"https://auth\.openai\.com/[^\s]+")
DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{5}\b")

CODEX_CLI_AUTH_JSON = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"


class CommandResult(BaseModel):
    command: List[str]
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: Optional[str] = None


class CodexOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str
    callback_port: int = CODEX_CALLBACK_PORT


class CodexSessionStatus(BaseModel):
    connected: bool


class CodexDeviceAuthResponse(BaseModel):
    status: str
    connected: bool = False
    verification_url: Optional[str] = None
    user_code: Optional[str] = None
    message: Optional[str] = None


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


_oauth_lock = threading.Lock()
_oauth_servers: List[ThreadingHTTPServer] = []
_oauth_shutdown_timer: Optional[threading.Timer] = None
_pending_oauth: Dict[str, Dict[str, Any]] = {}
_device_auth_session: Optional[Dict[str, Any]] = None


def _sanitized(text: str, *, limit: int = 6000) -> str:
    redacted = TOKEN_RE.sub("[REDACTED]", _strip_terminal_control(text or ""))
    if len(redacted) > limit:
        return redacted[:limit] + "\n[truncated]"
    return redacted


def _strip_terminal_control(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _create_pkce() -> tuple[str, str]:
    verifier = _base64url(os.urandom(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _env_without_project_config() -> Dict[str, str]:
    env = os.environ.copy()
    # Dashboard checks should use the user's global OpenCode config first.
    # OSTwin room execution sets OPENCODE_CONFIG to project config separately.
    env.pop("OPENCODE_CONFIG", None)
    return env


def _run(cmd: List[str], *, timeout: int = 20) -> CommandResult:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_env_without_project_config(),
        )
        return CommandResult(
            command=cmd,
            exit_code=result.returncode,
            stdout=_sanitized(result.stdout),
            stderr=_sanitized(result.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=cmd,
            timed_out=True,
            stdout=_sanitized(exc.stdout or ""),
            stderr=_sanitized(exc.stderr or ""),
            error=f"Timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return CommandResult(command=cmd, error=str(exc))


def _load_json_object(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_secure(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def _plugin_configured() -> bool:
    return PLUGIN_PACKAGE in _read_config_text()


def _auth_json_has_openai_oauth() -> bool:
    auth = _load_json_object(OPENCODE_AUTH_JSON).get("openai")
    return isinstance(auth, dict) and auth.get("type") == "oauth"


def get_codex_session_status() -> CodexSessionStatus:
    return CodexSessionStatus(connected=_auth_json_has_openai_oauth())


def _device_auth_response_locked() -> CodexDeviceAuthResponse:
    session = _device_auth_session
    if not session:
        connected = _auth_json_has_openai_oauth()
        return CodexDeviceAuthResponse(
            status="connected" if connected else "idle",
            connected=connected,
        )
    connected = session.get("status") == "connected"
    return CodexDeviceAuthResponse(
        status=str(session.get("status") or "idle"),
        connected=connected,
        verification_url=session.get("verification_url"),
        user_code=session.get("user_code"),
        message=session.get("message"),
    )


def get_codex_device_auth_status() -> CodexDeviceAuthResponse:
    with _oauth_lock:
        return _device_auth_response_locked()


def _update_device_session(session: Dict[str, Any], **updates: Any) -> None:
    with _oauth_lock:
        if _device_auth_session is session:
            session.update(updates)


def _complete_device_session_after_oauth_save() -> None:
    process: Optional[subprocess.Popen] = None
    with _oauth_lock:
        session = _device_auth_session
        if not session:
            return
        raw_process = session.get("process")
        if isinstance(raw_process, subprocess.Popen):
            process = raw_process
        session.update(
            status="connected",
            message="OpenAI Codex OAuth credential saved for OpenCode.",
        )

    if process is not None and process.poll() is None:
        process.terminate()


def _capture_device_output(session: Dict[str, Any]) -> None:
    process = session.get("process")
    if not isinstance(process, subprocess.Popen):
        _update_device_session(session, status="error", message="Codex device login process was not available.")
        return

    try:
        if process.stdout is not None:
            for line in process.stdout:
                raw = _strip_terminal_control(line.rstrip())
                url_match = DEVICE_URL_RE.search(raw)
                code_match = DEVICE_CODE_RE.search(raw)
                updates: Dict[str, Any] = {}
                if url_match:
                    updates["verification_url"] = url_match.group(0)
                if code_match:
                    updates["user_code"] = code_match.group(0)
                if updates:
                    _update_device_session(session, **updates)

        exit_code = process.wait()
        if exit_code == 0:
            import_codex_cli_auth_to_opencode()
            _update_device_session(
                session,
                status="connected",
                message="OpenAI Codex OAuth credential saved for OpenCode.",
            )
            return

        _update_device_session(
            session,
            status="error",
            message=f"Codex device login exited with code {exit_code}.",
        )
    except Exception as exc:  # noqa: BLE001
        _update_device_session(session, status="error", message=_sanitized(str(exc)))


def start_codex_device_auth() -> CodexDeviceAuthResponse:
    global _device_auth_session

    _ensure_codex_plugin()
    if shutil.which("codex") is None:
        raise RuntimeError("Cannot start device login because Codex CLI is not installed.")

    with _oauth_lock:
        if _device_auth_session:
            process = _device_auth_session.get("process")
            if isinstance(process, subprocess.Popen) and process.poll() is None:
                return _device_auth_response_locked()

        _device_auth_session = {
            "status": "pending",
            "message": "Starting Codex device login.",
            "created_at": time.time(),
        }
        session = _device_auth_session

    cmd = [
        "codex",
        "login",
        "-c",
        'cli_auth_credentials_store="file"',
        "--device-auth",
    ]
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_env_without_project_config(),
        )
    except OSError as exc:
        _update_device_session(session, status="error", message=str(exc))
        raise RuntimeError(f"Cannot start Codex device login: {exc}") from exc

    _update_device_session(session, process=process, message="Waiting for Codex device code.")
    thread = threading.Thread(target=_capture_device_output, args=(session,), name="codex-device-auth", daemon=True)
    thread.start()

    deadline = time.time() + 8
    while time.time() < deadline:
        with _oauth_lock:
            response = _device_auth_response_locked()
        if response.status in {"connected", "error"} or response.user_code:
            return response
        time.sleep(0.1)

    with _oauth_lock:
        return _device_auth_response_locked()


def _ensure_codex_plugin() -> None:
    if _plugin_configured():
        return
    if shutil.which("npx") is None:
        raise RuntimeError("Cannot prepare Codex login because npx is not installed.")
    result = _run(["npx", "-y", PLUGIN_SPEC, "--modern"], timeout=180)
    if result.exit_code != 0:
        detail = result.stderr or result.error or "Codex login setup failed."
        raise RuntimeError(detail)


def _save_openai_oauth(tokens: Dict[str, Any]) -> None:
    auth = {
        "type": "oauth",
        "access": tokens["access"],
        "refresh": tokens["refresh"],
        "expires": tokens["expires"],
    }

    # Newer OpenCode versions read provider credentials from auth.json.
    native_auth = _load_json_object(OPENCODE_AUTH_JSON)
    native_auth["openai"] = auth
    _write_json_secure(OPENCODE_AUTH_JSON, native_auth)

    # The Codex OAuth plugin install/uninstall script also documents this
    # per-provider artifact. Keep it in sync for plugin/version compatibility.
    _write_json_secure(CODEX_AUTH_JSON, auth)
    _complete_device_session_after_oauth_save()


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _jwt_expires_millis(token: str) -> Optional[int]:
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp > 0:
        return int(exp * 1000)
    return None


def _load_codex_cli_oauth_tokens(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or CODEX_CLI_AUTH_JSON
    data = _load_json_object(path)
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        raise RuntimeError(f"Codex auth file at {path} is missing token data.")

    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not isinstance(access, str) or not access:
        raise RuntimeError(f"Codex auth file at {path} is missing access_token.")
    if not isinstance(refresh, str) or not refresh:
        raise RuntimeError(f"Codex auth file at {path} is missing refresh_token.")

    expires = _jwt_expires_millis(access) or int(time.time() * 1000) + 3600 * 1000
    return {
        "access": access,
        "refresh": refresh,
        "expires": expires,
    }


def import_codex_cli_auth_to_opencode(path: Optional[Path] = None) -> None:
    _save_openai_oauth(_load_codex_cli_oauth_tokens(path))
    _refresh_models_after_auth()


def _refresh_models_after_auth() -> None:
    try:
        from dashboard.lib.settings.models_dev_loader import (
            rebuild_configured_models_from_cache,
        )

        rebuild_configured_models_from_cache()
    except Exception:
        # Auth has succeeded. A stale model cache should not fail the OAuth
        # callback; the user can still reload models manually if this fails.
        pass


def _exchange_code(code: str, verifier: str) -> Dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": OPENAI_CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": CODEX_REDIRECT_URI,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"OpenAI token exchange failed: {exc}") from exc

    if not payload.get("access_token") or not payload.get("refresh_token") or not payload.get("expires_in"):
        raise RuntimeError("OpenAI token response was missing required OAuth fields")

    return {
        "access": payload["access_token"],
        "refresh": payload["refresh_token"],
        "expires": int(time.time() * 1000) + int(payload["expires_in"]) * 1000,
    }


def _oauth_result_page(*, success: bool, message: str) -> bytes:
    status = "success" if success else "error"
    safe_message = html.escape(message)
    return f"""<!doctype html>
<html>
<head>
  <title>OpenAI Codex OAuth</title>
  <meta charset="utf-8" />
  <style>
    body {{ font-family: system-ui, sans-serif; display: grid; place-items: center; min-height: 100vh; margin: 0; background: #f8fafc; color: #0f172a; }}
    .card {{ width: min(420px, calc(100vw - 32px)); border: 1px solid #e2e8f0; border-radius: 8px; background: white; padding: 28px; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08); }}
    .status {{ text-transform: uppercase; font-size: 11px; font-weight: 800; letter-spacing: .08em; color: {"#15803d" if success else "#b91c1c"}; }}
    .msg {{ margin-top: 10px; font-size: 14px; line-height: 1.5; color: #334155; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="status">{status}</div>
    <div class="msg">{safe_message}</div>
  </div>
  <script>
    if (window.opener) {{
      window.opener.postMessage({{
        type: 'openai_codex_oauth_result',
        status: '{status}',
        message: {json.dumps(message)}
      }}, '*');
    }}
    window.setTimeout(() => window.close(), 900);
  </script>
</body>
</html>""".encode("utf-8")


class _CodexOAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404)
            return

        params = urllib.parse.parse_qs(parsed.query)
        state = (params.get("state") or [""])[0]
        code = (params.get("code") or [""])[0]
        error = (params.get("error") or [""])[0]

        success = False
        message = ""
        try:
            if error:
                raise RuntimeError(f"OpenAI returned error: {error}")
            if not state or not code:
                raise RuntimeError("OAuth callback was missing code or state")
            with _oauth_lock:
                session = _pending_oauth.pop(state, None)
            if not session:
                raise RuntimeError("OAuth session expired or state did not match")
            if time.time() - float(session["created_at"]) > 600:
                raise RuntimeError("OAuth session expired")
            tokens = _exchange_code(code, str(session["verifier"]))
            _save_openai_oauth(tokens)
            _refresh_models_after_auth()
            success = True
            message = "OpenAI Codex OAuth credential saved for OpenCode."
        except Exception as exc:  # noqa: BLE001
            message = str(exc)

        page = _oauth_result_page(success=success, message=message)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
        _schedule_oauth_shutdown(0.2)


def _cleanup_pending_oauth() -> None:
    now = time.time()
    stale = [state for state, session in _pending_oauth.items() if now - float(session["created_at"]) > 600]
    for state in stale:
        _pending_oauth.pop(state, None)


def _shutdown_oauth_servers() -> None:
    global _oauth_shutdown_timer
    with _oauth_lock:
        servers = list(_oauth_servers)
        _oauth_servers.clear()
        timer = _oauth_shutdown_timer
        _oauth_shutdown_timer = None

    if timer is not None and timer.is_alive() and threading.current_thread() is not timer:
        timer.cancel()

    for server in servers:
        server.shutdown()
        server.server_close()


def _schedule_oauth_shutdown(delay_seconds: float) -> None:
    global _oauth_shutdown_timer
    with _oauth_lock:
        if _oauth_shutdown_timer is not None:
            _oauth_shutdown_timer.cancel()
        _oauth_shutdown_timer = threading.Timer(delay_seconds, _shutdown_oauth_servers)
        _oauth_shutdown_timer.daemon = True
        _oauth_shutdown_timer.start()


def _ensure_oauth_server() -> None:
    with _oauth_lock:
        if _oauth_servers:
            return
        candidates = [
            (ThreadingHTTPServer, ("127.0.0.1", CODEX_CALLBACK_PORT)),
            (_IPv6ThreadingHTTPServer, ("::1", CODEX_CALLBACK_PORT)),
        ]
        errors: List[str] = []
        for server_cls, address in candidates:
            try:
                server = server_cls(address, _CodexOAuthHandler)
            except OSError as exc:
                errors.append(str(exc))
                continue
            thread = threading.Thread(target=server.serve_forever, name="codex-oauth-callback", daemon=True)
            thread.start()
            _oauth_servers.append(server)
        if not _oauth_servers:
            raise RuntimeError(
                f"Cannot start Codex OAuth callback server on 127.0.0.1:{CODEX_CALLBACK_PORT}. "
                "Close any existing Codex login process and try again."
                f" Errors: {'; '.join(errors)}"
            )


def _read_config_text() -> str:
    chunks: List[str] = []
    for path in (OPENCODE_CONFIG_JSONC, OPENCODE_CONFIG_JSON):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return "\n".join(chunks)


def start_codex_oauth() -> CodexOAuthStartResponse:
    _ensure_codex_plugin()
    _ensure_oauth_server()
    verifier, challenge = _create_pkce()
    state = _base64url(os.urandom(18))
    with _oauth_lock:
        _cleanup_pending_oauth()
        _pending_oauth[state] = {
            "verifier": verifier,
            "created_at": time.time(),
        }
    _schedule_oauth_shutdown(600)

    url = (
        OPENAI_AUTHORIZE_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": OPENAI_CLIENT_ID,
                "redirect_uri": CODEX_REDIRECT_URI,
                "scope": OPENAI_SCOPE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true",
                "originator": "codex_cli_rs",
            }
        )
    )
    return CodexOAuthStartResponse(
        authorization_url=url,
        state=state,
    )

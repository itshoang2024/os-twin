"""GitHub Copilot auth flow for OpenCode.

The dashboard supports both OpenCode's native GitHub Copilot device login and
dashboard-managed browser OAuth. The saved OAuth token is kept in OpenCode's
``auth.json``. For project runs, Ostwin also writes a custom OpenCode provider
alias (``github-copilot-oauth``) that uses ``GITHUB_COPILOT_TOKEN`` at runtime.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import html
import json
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import termios
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel

from dashboard.lib.opencode_paths import (
    get_managed_opencode_config_path,
    get_project_opencode_config_path,
    get_user_opencode_config_path,
)


OPENCODE_AUTH_JSON = Path.home() / ".local" / "share" / "opencode" / "auth.json"
COPILOT_PROVIDER_ID = "github-copilot"
LEGACY_COPILOT_PROVIDER_ID = "copilot"
COPILOT_CUSTOM_PROVIDER_ID = "github-copilot-oauth"
COPILOT_TOKEN_ENV = "GITHUB_COPILOT_TOKEN"
COPILOT_API_BASE_URL = "https://api.githubcopilot.com"
COPILOT_MODELS_URL = f"{COPILOT_API_BASE_URL}/models"
OPENCODE_BIN = os.environ.get("OSTWIN_OPENCODE_BIN") or shutil.which("opencode") or "opencode"
COPILOT_LOGIN_METHOD = "Login with GitHub Copilot"
GITHUB_DEVICE_URL = "https://github.com/login/device"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_OAUTH_CLIENT_ID = os.environ.get("OSTWIN_GITHUB_CLIENT_ID", "Ov23liQTivczXRzkXA1E")
GITHUB_OAUTH_CLIENT_SECRET = os.environ.get("OSTWIN_GITHUB_CLIENT_SECRET", "b98f41f175ae05f2ec527ac8509abd2826afa26b")
GITHUB_OAUTH_REDIRECT_URI = os.environ.get(
    "OSTWIN_GITHUB_REDIRECT_URI",
    "http://localhost:3366/api/settings/github/oauth/callback",
)
# add scope for copilot access
GITHUB_OAUTH_SCOPE = os.environ.get("OSTWIN_GITHUB_SCOPE", "read:user read:repo_hook read:org read:public_key read:gpg_key")
OPENCODE_SCHEMA = "https://opencode.ai/config.json"
FALLBACK_COPILOT_MODELS = [
    "gpt-4o-mini-2024-07-18",
    "gpt-4o-2024-11-20",
    "gpt-4o-2024-08-06",
    "gpt-41-copilot",
    "gpt-3.5-turbo-0613",
    "gpt-5.4",
    "gpt-5.4-fast",
    "gpt-5.4-mini",
]


class GitHubCopilotSessionStatus(BaseModel):
    connected: bool


class GitHubCopilotOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str


class GitHubCopilotDeviceAuthResponse(BaseModel):
    status: str
    connected: bool = False
    verification_url: Optional[str] = None
    user_code: Optional[str] = None
    message: Optional[str] = None


class GitHubCopilotSyncResponse(BaseModel):
    synced: bool
    paths: list[str] = []
    skipped: list[str] = []
    models: list[str] = []
    error: Optional[str] = None


_auth_lock = threading.Lock()
_pending_oauth: Dict[str, Dict[str, Any]] = {}
_device_auth_session: Optional[Dict[str, Any]] = None


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _create_pkce() -> tuple[str, str]:
    verifier = _base64url(os.urandom(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


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


def _auth_entry_connected(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    auth_type = entry.get("type")
    access = entry.get("access") or entry.get("token")
    if auth_type == "oauth":
        return bool(access or entry.get("refresh"))
    if auth_type == "api":
        return bool(entry.get("key"))
    return bool(access or entry.get("refresh") or entry.get("key"))


def _auth_json_has_copilot() -> bool:
    auth = _load_json_object(OPENCODE_AUTH_JSON)
    return _auth_entry_connected(auth.get(COPILOT_PROVIDER_ID)) or _auth_entry_connected(
        auth.get(LEGACY_COPILOT_PROVIDER_ID)
    )


def _refresh_models_after_auth() -> None:
    try:
        from dashboard.lib.settings.models_dev_loader import rebuild_configured_models_from_cache

        rebuild_configured_models_from_cache()
    except Exception:
        pass


def get_saved_github_copilot_token() -> Optional[str]:
    """Return the saved Copilot OAuth token without logging it."""
    auth = _load_json_object(OPENCODE_AUTH_JSON)
    entry = auth.get(COPILOT_PROVIDER_ID)
    if not isinstance(entry, dict):
        entry = auth.get(LEGACY_COPILOT_PROVIDER_ID)
    if not isinstance(entry, dict):
        return None
    token = entry.get("refresh") or entry.get("access") or entry.get("token")
    return token if isinstance(token, str) and token else None


def _fetch_copilot_model_ids(access_token: str) -> list[str]:
    req = urllib.request.Request(
        COPILOT_MODELS_URL,
        method="GET",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "X-GitHub-Api-Version": "2026-06-01",
            "User-Agent": "ostwin-copilot-auth-check",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        return []
    models = payload.get("data")
    if not isinstance(models, list):
        models = payload.get("models")
    if not isinstance(models, list):
        return []
    ids: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id") or model.get("name")
        if isinstance(model_id, str) and model_id and model_id not in ids:
            ids.append(model_id)
    return ids


def _build_copilot_provider_config(models: Optional[list[str]] = None) -> Dict[str, Any]:
    model_ids = models or FALLBACK_COPILOT_MODELS
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "GitHub Copilot OAuth",
        "options": {
            "baseURL": COPILOT_API_BASE_URL,
            "apiKey": f"{{env:{COPILOT_TOKEN_ENV}}}",
            "headers": {
                "X-GitHub-Api-Version": "2026-06-01",
            },
        },
        "models": {
            model_id: {"name": f"{model_id} (Copilot)"}
            for model_id in model_ids
        },
    }


def _merge_opencode_provider(path: Path, provider_config: Dict[str, Any]) -> bool:
    existing = _load_json_object(path)
    original = json.dumps(existing, sort_keys=True)
    existing["$schema"] = existing.get("$schema") or OPENCODE_SCHEMA
    provider_block = existing.get("provider")
    if not isinstance(provider_block, dict):
        provider_block = {}
    provider_block[COPILOT_CUSTOM_PROVIDER_ID] = provider_config
    existing["provider"] = provider_block
    if json.dumps(existing, sort_keys=True) == original:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return True


def sync_github_copilot_opencode_config(
    *,
    project_dir: Optional[Path] = None,
    access_token: Optional[str] = None,
) -> GitHubCopilotSyncResponse:
    """Sync the custom Copilot OAuth provider into OpenCode config files."""
    token = access_token or get_saved_github_copilot_token()
    if not token:
        return GitHubCopilotSyncResponse(
            synced=False,
            error="No GitHub Copilot OAuth token is saved.",
        )

    try:
        models = _fetch_copilot_model_ids(token)
    except Exception:
        models = list(FALLBACK_COPILOT_MODELS)
    if not models:
        models = list(FALLBACK_COPILOT_MODELS)

    provider_config = _build_copilot_provider_config(models)
    targets = [
        get_user_opencode_config_path(),
        get_managed_opencode_config_path(),
    ]
    if project_dir is not None:
        targets.append(get_project_opencode_config_path(project_dir))

    synced_paths: list[str] = []
    skipped_paths: list[str] = []
    errors: list[str] = []
    for target in targets:
        if project_dir is not None and target == get_project_opencode_config_path(project_dir) and not target.exists():
            skipped_paths.append(str(target))
            continue
        try:
            _merge_opencode_provider(target, provider_config)
            synced_paths.append(str(target))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{target}: {exc}")

    _refresh_models_after_auth()
    return GitHubCopilotSyncResponse(
        synced=bool(synced_paths) and not errors,
        paths=synced_paths,
        skipped=skipped_paths,
        models=models,
        error="; ".join(errors) if errors else None,
    )


def _save_github_oauth_token(access_token: str) -> None:
    if not access_token:
        raise RuntimeError("GitHub OAuth response did not include access_token.")

    _validate_github_copilot_token(access_token)
    auth = _load_json_object(OPENCODE_AUTH_JSON)
    auth[COPILOT_PROVIDER_ID] = {
        "type": "oauth",
        "refresh": access_token,
        "access": access_token,
        "expires": 0,
    }
    _write_json_secure(OPENCODE_AUTH_JSON, auth)
    sync_github_copilot_opencode_config(access_token=access_token)
    _refresh_models_after_auth()


def _validate_github_copilot_token(access_token: str) -> None:
    req = urllib.request.Request(
        COPILOT_MODELS_URL,
        method="GET",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "X-GitHub-Api-Version": "2026-06-01",
            "User-Agent": "ostwin-copilot-auth-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "GitHub browser OAuth succeeded, but GitHub Copilot rejected that token. "
            "Use Device code for OpenCode Copilot login."
        ) from exc


def _post_github_form(url: str, data: Dict[str, str]) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"GitHub OAuth request failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("GitHub OAuth response was not a JSON object.")
    if payload.get("error"):
        desc = payload.get("error_description") or payload.get("error")
        raise RuntimeError(f"GitHub OAuth error: {desc}")
    return payload


def _clear_broken_copilot_auth() -> None:
    # OpenCode's native GitHub Copilot device flow stores the GitHub OAuth token
    # in this entry, so token prefixes alone cannot identify a broken credential.
    return


def get_github_copilot_session_status() -> GitHubCopilotSessionStatus:
    return GitHubCopilotSessionStatus(connected=_auth_json_has_copilot())


def start_github_copilot_oauth() -> GitHubCopilotOAuthStartResponse:
    if not GITHUB_OAUTH_CLIENT_ID:
        raise RuntimeError("GitHub OAuth client id is not configured.")

    verifier, challenge = _create_pkce()
    state = _base64url(os.urandom(18))
    with _auth_lock:
        _pending_oauth[state] = {
            "verifier": verifier,
            "created_at": time.time(),
        }

    authorization_url = (
        GITHUB_AUTHORIZE_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": GITHUB_OAUTH_CLIENT_ID,
                "redirect_uri": GITHUB_OAUTH_REDIRECT_URI,
                "scope": GITHUB_OAUTH_SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    return GitHubCopilotOAuthStartResponse(authorization_url=authorization_url, state=state)


def exchange_github_copilot_oauth_code(code: str, state: str) -> None:
    if not GITHUB_OAUTH_CLIENT_SECRET:
        raise RuntimeError("GitHub OAuth client secret is not configured. Set OSTWIN_GITHUB_CLIENT_SECRET.")
    if not code or not state:
        raise RuntimeError("GitHub OAuth callback was missing code or state.")

    with _auth_lock:
        session = _pending_oauth.pop(state, None)
    if not session:
        raise RuntimeError("GitHub OAuth session expired or state did not match.")
    if time.time() - float(session["created_at"]) > 600:
        raise RuntimeError("GitHub OAuth session expired.")

    payload = _post_github_form(
        GITHUB_ACCESS_TOKEN_URL,
        {
            "client_id": GITHUB_OAUTH_CLIENT_ID,
            "client_secret": GITHUB_OAUTH_CLIENT_SECRET,
            "code": code,
            "redirect_uri": GITHUB_OAUTH_REDIRECT_URI,
            "code_verifier": str(session["verifier"]),
        },
    )
    _save_github_oauth_token(str(payload.get("access_token") or ""))


def github_copilot_oauth_result_page(*, success: bool, message: str) -> str:
    status = "success" if success else "error"
    safe_message = html.escape(message)
    return f"""<!doctype html>
<html>
<head>
  <title>GitHub Copilot Login</title>
  <meta charset="utf-8" />
  <style>
    body {{ font-family: system-ui, sans-serif; display: grid; place-items: center; min-height: 100vh; margin: 0; background: #f8fafc; color: #0f172a; }}
    .card {{ width: min(440px, calc(100vw - 32px)); border: 1px solid #e2e8f0; border-radius: 8px; background: white; padding: 28px; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08); }}
    .status {{ text-transform: uppercase; font-size: 11px; font-weight: 800; letter-spacing: .08em; color: {"#15803d" if success else "#b91c1c"}; }}
    .msg {{ margin-top: 10px; font-size: 14px; line-height: 1.5; color: #334155; white-space: pre-wrap; }}
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
        type: 'github_copilot_oauth_result',
        status: '{status}',
        message: {json.dumps(message)}
      }}, '*');
    }}
    window.setTimeout(() => window.close(), 1200);
  </script>
</body>
</html>"""


def _device_auth_response_locked() -> GitHubCopilotDeviceAuthResponse:
    session = _device_auth_session
    auth_connected = _auth_json_has_copilot()
    if not session:
        return GitHubCopilotDeviceAuthResponse(
            status="connected" if auth_connected else "idle",
            connected=auth_connected,
        )
    connected = auth_connected or session.get("status") == "connected"
    return GitHubCopilotDeviceAuthResponse(
        status="connected" if connected else str(session.get("status") or "idle"),
        connected=connected,
        verification_url=session.get("verification_url"),
        user_code=session.get("user_code"),
        message="GitHub Copilot connected." if connected else session.get("message"),
    )


def get_github_copilot_device_auth_status() -> GitHubCopilotDeviceAuthResponse:
    with _auth_lock:
        return _device_auth_response_locked()


def _update_device_session(session: Dict[str, Any], **updates: Any) -> None:
    with _auth_lock:
        if _device_auth_session is session:
            session.update(updates)


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_DEVICE_URL_RE = re.compile(r"https://github\.com/login/device")
_USER_CODE_RE = re.compile(r"(?:Enter code:|code[:\s]+)([A-Z0-9]{4,}-[A-Z0-9-]{4,})", re.IGNORECASE)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _read_pty(master_fd: int, *, timeout: float = 0.2) -> str:
    chunks: list[bytes] = []
    while True:
        readable, _, _ = select.select([master_fd], [], [], timeout)
        if not readable:
            break
        try:
            chunks.append(os.read(master_fd, 4096))
        except OSError:
            break
        timeout = 0
    return _strip_ansi(b"".join(chunks).decode("utf-8", "replace"))


def _set_pty_window_size(fd: int, rows: int = 40, cols: int = 120) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _parse_opencode_device_output(output: str) -> tuple[Optional[str], Optional[str]]:
    verification_url = GITHUB_DEVICE_URL if _DEVICE_URL_RE.search(output) else None
    code_match = _USER_CODE_RE.search(output)
    user_code = code_match.group(1) if code_match else None
    return verification_url, user_code


def _is_process(value: Any) -> bool:
    return hasattr(value, "poll") and hasattr(value, "returncode")


def _handle_opencode_login_output(session: Dict[str, Any], output: str) -> None:
    if not output:
        return
    session["output"] = str(session.get("output") or "") + output
    master_fd = session.get("master_fd")
    if (
        isinstance(master_fd, int)
        and not session.get("deployment_selected")
        and "Select GitHub deployment type" in str(session["output"])
    ):
        try:
            os.write(master_fd, b"\r")
            session["deployment_selected"] = True
            session["message"] = "Selected GitHub.com. Waiting for GitHub device code."
        except OSError:
            pass
    verification_url, user_code = _parse_opencode_device_output(str(session["output"]))
    updates: Dict[str, Any] = {}
    if verification_url:
        updates["verification_url"] = verification_url
    if user_code:
        updates["user_code"] = user_code
        updates["message"] = "Enter the GitHub device code, then authorize GitHub Copilot."
    if updates:
        _update_device_session(session, **updates)


def _drain_initial_login_output(session: Dict[str, Any], *, seconds: float = 20) -> None:
    master_fd = session.get("master_fd")
    process = session.get("process")
    if not isinstance(master_fd, int) or not _is_process(process):
        return
    deadline = time.time() + seconds
    while time.time() < deadline and process.poll() is None:
        _handle_opencode_login_output(session, _read_pty(master_fd))
        if session.get("user_code"):
            return
        time.sleep(0.1)


def _poll_device_auth(session: Dict[str, Any]) -> None:
    process = session.get("process")
    master_fd = session.get("master_fd")
    if not _is_process(process) or not isinstance(master_fd, int):
        _update_device_session(session, status="error", message="OpenCode login process was not started.")
        return

    try:
        while process.poll() is None:
            _handle_opencode_login_output(session, _read_pty(master_fd))
            time.sleep(0.5)

        _handle_opencode_login_output(session, _read_pty(master_fd, timeout=0))
        if process.returncode == 0 and _auth_json_has_copilot():
            sync_github_copilot_opencode_config()
            _update_device_session(
                session,
                status="connected",
                connected=True,
                message="GitHub Copilot credential saved by OpenCode.",
            )
            return

        output = str(session.get("output") or "").strip()
        _update_device_session(
            session,
            status="error",
            message=output[-500:] or f"OpenCode login exited with code {process.returncode}.",
        )
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass


def start_github_copilot_device_auth() -> GitHubCopilotDeviceAuthResponse:
    global _device_auth_session

    with _auth_lock:
        if _device_auth_session and _device_auth_session.get("status") == "pending":
            return _device_auth_response_locked()

    _clear_broken_copilot_auth()
    master_fd, slave_fd = pty.openpty()
    _set_pty_window_size(slave_fd)
    command = [OPENCODE_BIN, "auth", "login", "-p", COPILOT_PROVIDER_ID, "-m", COPILOT_LOGIN_METHOD]
    try:
        process = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        os.close(slave_fd)

    session: Dict[str, Any] = {
        "status": "pending",
        "connected": False,
        "user_code": None,
        "verification_url": GITHUB_DEVICE_URL,
        "message": "Starting OpenCode GitHub Copilot login.",
        "process": process,
        "master_fd": master_fd,
        "output": "",
        "deployment_selected": False,
    }
    with _auth_lock:
        _device_auth_session = session

    _drain_initial_login_output(session)
    thread = threading.Thread(target=_poll_device_auth, args=(session,), name="github-copilot-device-auth", daemon=True)
    thread.start()

    if not session.get("user_code") and process.poll() is not None:
        _update_device_session(
            session,
            status="error",
            message=str(session.get("output") or "").strip()[-500:] or "OpenCode did not produce a GitHub device code.",
        )

    return _device_auth_response_locked()

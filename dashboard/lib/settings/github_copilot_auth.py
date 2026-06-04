"""GitHub Copilot auth flow for OpenCode.

This mirrors the dashboard's Google OAuth helper: the browser flow uses PKCE,
state validation, and a local dashboard callback before writing the credential
that OpenCode reads from its native auth.json.

Unlike Google's well-known desktop OAuth credentials, a GitHub OAuth app client
secret is private. Keep the secret in local env/config, not in tracked source.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel


OPENCODE_AUTH_JSON = Path.home() / ".local" / "share" / "opencode" / "auth.json"
COPILOT_PROVIDER_ID = "github-copilot"
LEGACY_COPILOT_PROVIDER_ID = "copilot"

# Public GitHub OAuth app client id for the OSTwin local dashboard.
_CLIENT_ID = os.environ.get("OSTWIN_GITHUB_CLIENT_ID", "Ov23liQTivczXRzkXA1E")
_CLIENT_SECRET = os.environ.get("OSTWIN_GITHUB_CLIENT_SECRET", "")
_REDIRECT_URI = os.environ.get(
    "OSTWIN_GITHUB_REDIRECT_URI",
    "http://localhost:3366/api/settings/github/oauth/callback",
)
_SCOPE = os.environ.get("OSTWIN_GITHUB_SCOPE", "read:user")

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


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
    if auth_type == "oauth":
        return bool(entry.get("access") or entry.get("token") or entry.get("refresh"))
    if auth_type == "api":
        return bool(entry.get("key"))
    return bool(entry.get("access") or entry.get("token") or entry.get("refresh") or entry.get("key"))


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


def _save_github_oauth_token(access_token: str, *, scope: str = "", token_type: str = "bearer") -> None:
    if not access_token:
        raise RuntimeError("GitHub token response did not include access_token.")

    auth = _load_json_object(OPENCODE_AUTH_JSON)
    # Keep both ``access`` and ``token`` for compatibility with OpenCode auth
    # schema changes across versions.
    auth[COPILOT_PROVIDER_ID] = {
        "type": "oauth",
        "access": access_token,
        "token": access_token,
        "refresh": "",
        "expires": int(time.time() * 1000) + 365 * 24 * 3600 * 1000,
        "scope": scope,
        "token_type": token_type,
    }
    _write_json_secure(OPENCODE_AUTH_JSON, auth)
    _refresh_models_after_auth()


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


def get_github_copilot_session_status() -> GitHubCopilotSessionStatus:
    return GitHubCopilotSessionStatus(connected=_auth_json_has_copilot())


def start_github_copilot_oauth() -> GitHubCopilotOAuthStartResponse:
    if not _CLIENT_ID:
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
                "client_id": _CLIENT_ID,
                "redirect_uri": _REDIRECT_URI,
                "scope": _SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    return GitHubCopilotOAuthStartResponse(authorization_url=authorization_url, state=state)


def exchange_github_copilot_oauth_code(code: str, state: str) -> None:
    if not _CLIENT_SECRET:
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
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "code_verifier": str(session["verifier"]),
        },
    )
    _save_github_oauth_token(
        str(payload.get("access_token") or ""),
        scope=str(payload.get("scope") or ""),
        token_type=str(payload.get("token_type") or "bearer"),
    )


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
    if not session:
        connected = _auth_json_has_copilot()
        return GitHubCopilotDeviceAuthResponse(
            status="connected" if connected else "idle",
            connected=connected,
        )
    connected = session.get("status") == "connected"
    return GitHubCopilotDeviceAuthResponse(
        status=str(session.get("status") or "idle"),
        connected=connected,
        verification_url=session.get("verification_url"),
        user_code=session.get("user_code"),
        message=session.get("message"),
    )


def get_github_copilot_device_auth_status() -> GitHubCopilotDeviceAuthResponse:
    with _auth_lock:
        return _device_auth_response_locked()


def _update_device_session(session: Dict[str, Any], **updates: Any) -> None:
    with _auth_lock:
        if _device_auth_session is session:
            session.update(updates)


def _poll_device_auth(session: Dict[str, Any]) -> None:
    interval = int(session.get("interval") or 5)
    expires_at = float(session.get("expires_at") or 0)
    device_code = str(session.get("device_code") or "")

    while time.time() < expires_at:
        time.sleep(max(interval, 1))
        try:
            payload = _post_github_form(
                GITHUB_ACCESS_TOKEN_URL,
                {
                    "client_id": _CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": GITHUB_DEVICE_GRANT_TYPE,
                },
            )
            access_token = str(payload.get("access_token") or "")
            if access_token:
                _save_github_oauth_token(
                    access_token,
                    scope=str(payload.get("scope") or ""),
                    token_type=str(payload.get("token_type") or "bearer"),
                )
                _update_device_session(
                    session,
                    status="connected",
                    connected=True,
                    message="GitHub Copilot credential saved for OpenCode.",
                )
                return
        except RuntimeError as exc:
            msg = str(exc)
            if "authorization_pending" in msg:
                continue
            if "slow_down" in msg:
                interval += 5
                continue
            _update_device_session(session, status="error", message=msg)
            return

    _update_device_session(session, status="error", message="GitHub device code expired. Try again.")


def start_github_copilot_device_auth() -> GitHubCopilotDeviceAuthResponse:
    global _device_auth_session

    if not _CLIENT_ID:
        raise RuntimeError("GitHub OAuth client id is not configured.")

    with _auth_lock:
        if _device_auth_session and _device_auth_session.get("status") == "pending":
            return _device_auth_response_locked()

    payload = _post_github_form(
        GITHUB_DEVICE_CODE_URL,
        {
            "client_id": _CLIENT_ID,
            "scope": _SCOPE,
        },
    )

    device_code = str(payload.get("device_code") or "")
    user_code = str(payload.get("user_code") or "")
    verification_url = str(payload.get("verification_uri") or "https://github.com/login/device")
    if not device_code or not user_code:
        raise RuntimeError("GitHub device response was missing device_code or user_code.")

    session: Dict[str, Any] = {
        "status": "pending",
        "connected": False,
        "device_code": device_code,
        "user_code": user_code,
        "verification_url": verification_url,
        "interval": int(payload.get("interval") or 5),
        "expires_at": time.time() + int(payload.get("expires_in") or 900),
        "message": "Waiting for GitHub device authorization.",
    }
    with _auth_lock:
        _device_auth_session = session

    thread = threading.Thread(target=_poll_device_auth, args=(session,), name="github-copilot-device-auth", daemon=True)
    thread.start()
    return _device_auth_response_locked()

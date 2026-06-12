"""GitHub Copilot auth flow for OpenCode.

The dashboard supports both OpenCode's native GitHub Copilot device login and
dashboard-managed browser OAuth. The saved OAuth token is kept in OpenCode's
``auth.json``, which OpenCode's native ``github-copilot`` provider reads
directly at runtime. ``GITHUB_COPILOT_TOKEN`` is injected for project runs.
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

from dashboard.lib.opencode_paths import (
    get_managed_opencode_config_path,
    get_project_opencode_config_path,
    get_user_opencode_config_path,
)


OPENCODE_AUTH_JSON = Path.home() / ".local" / "share" / "opencode" / "auth.json"
COPILOT_PROVIDER_ID = "github-copilot"
LEGACY_COPILOT_PROVIDER_ID = "copilot"
# Deprecated custom provider alias. Retained only to clean up configs written
# by older versions; the native ``github-copilot`` provider is used now.
LEGACY_COPILOT_CUSTOM_PROVIDER_ID = "github-copilot-oauth"
COPILOT_API_BASE_URL = "https://api.githubcopilot.com"
GITHUB_DEVICE_URL = "https://github.com/login/device"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
OPENCODE_COPILOT_CLIENT_ID = os.environ.get("OSTWIN_OPENCODE_COPILOT_CLIENT_ID", "Ov23li8tweQw6odWQebz")
GITHUB_OAUTH_CLIENT_ID = os.environ.get("OSTWIN_GITHUB_CLIENT_ID", "Ov23liQTivczXRzkXA1E")
GITHUB_OAUTH_CLIENT_SECRET = os.environ.get("OSTWIN_GITHUB_CLIENT_SECRET", "b98f41f175ae05f2ec527ac8509abd2826afa26b")
GITHUB_OAUTH_REDIRECT_URI = os.environ.get(
    "OSTWIN_GITHUB_REDIRECT_URI",
    "http://localhost:3366/api/settings/github/oauth/callback",
)
# add scope for copilot access
GITHUB_OAUTH_SCOPE = os.environ.get("OSTWIN_GITHUB_SCOPE", "read:user read:repo_hook read:org read:public_key read:gpg_key")
GITHUB_DEVICE_SCOPE = os.environ.get("OSTWIN_GITHUB_DEVICE_SCOPE", "read:user")
GITHUB_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_EDITOR_VERSION = "vscode/1.98.0"
COPILOT_EDITOR_PLUGIN_VERSION = "copilot/1.254.0"
# Reuse a exchanged copilot token until this many seconds before it expires.
_COPILOT_TOKEN_EXPIRY_BUFFER_SECS = 60

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
# Cache of exchanged Copilot tokens keyed by GitHub OAuth token.
# Value: {"token": str, "api_url": str, "expires_at": float}
_copilot_token_cache: Dict[str, Dict[str, Any]] = {}


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


def _exchange_copilot_token(gho_token: str) -> Dict[str, Any]:
    """Exchange a GitHub OAuth token for a short-lived Copilot API token.

    Calls ``https://api.github.com/copilot_internal/v2/token`` and returns
    a dict with ``token``, ``api_url`` and ``expires_at`` (Unix timestamp).
    Results are cached in-process and reused until ``_COPILOT_TOKEN_EXPIRY_BUFFER_SECS``
    before expiry.
    """
    now = time.time()
    cached = _copilot_token_cache.get(gho_token)
    if cached and cached["expires_at"] - now > _COPILOT_TOKEN_EXPIRY_BUFFER_SECS:
        return cached

    req = urllib.request.Request(
        GITHUB_TOKEN_URL,
        method="GET",
        headers={
            "Authorization": f"token {gho_token}",
            "Accept": "application/json",
            "Editor-Version": COPILOT_EDITOR_VERSION,
            "Editor-Plugin-Version": COPILOT_EDITOR_PLUGIN_VERSION,
            "User-Agent": f"ostwin/{COPILOT_EDITOR_PLUGIN_VERSION}",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected response from GitHub Copilot token endpoint.")

    copilot_token = payload.get("token")
    if not isinstance(copilot_token, str) or not copilot_token:
        raise RuntimeError("GitHub Copilot token endpoint did not return a token.")

    # expires_at is an ISO-8601 string or a Unix timestamp integer.
    raw_exp = payload.get("expires_at")
    if isinstance(raw_exp, (int, float)):
        expires_at = float(raw_exp)
    elif isinstance(raw_exp, str):
        import datetime
        try:
            expires_at = datetime.datetime.fromisoformat(
                raw_exp.replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            expires_at = now + 1800
    else:
        expires_at = now + 1800

    endpoints = payload.get("endpoints") or {}
    api_url = (
        endpoints.get("api")
        if isinstance(endpoints, dict)
        else None
    ) or COPILOT_API_BASE_URL

    entry: Dict[str, Any] = {
        "token": copilot_token,
        "api_url": api_url.rstrip("/"),
        "expires_at": expires_at,
    }
    _copilot_token_cache[gho_token] = entry
    return entry


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
    """Fetch the list of model IDs available to the connected Copilot user.

    ``access_token`` is the GitHub OAuth token (``gho_*``) stored in auth.json.
    It is exchanged for a short-lived Copilot API token before the /models call.
    """
    exchange = _exchange_copilot_token(access_token)
    copilot_token = exchange["token"]
    models_url = exchange["api_url"] + "/models"

    req = urllib.request.Request(
        models_url,
        method="GET",
        headers={
            "Authorization": f"Bearer {copilot_token}",
            "Accept": "application/json",
            "Copilot-Integration-Id": "vscode-chat",
            "Editor-Version": COPILOT_EDITOR_VERSION,
            "Editor-Plugin-Version": COPILOT_EDITOR_PLUGIN_VERSION,
            "User-Agent": f"ostwin/{COPILOT_EDITOR_PLUGIN_VERSION}",
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


def _strip_legacy_copilot_alias(path: Path) -> bool:
    """Remove the deprecated ``github-copilot-oauth`` provider alias.

    Older dashboard versions wrote a custom OpenCode provider alias so project
    runs could inject ``GITHUB_COPILOT_TOKEN``.  The native ``github-copilot``
    provider now authenticates from ``auth.json`` directly, so the alias is
    removed when present.  Returns ``True`` when ``path`` was modified.
    """
    if not path.exists():
        return False
    existing = _load_json_object(path)
    provider_block = existing.get("provider")
    if not isinstance(provider_block, dict) or LEGACY_COPILOT_CUSTOM_PROVIDER_ID not in provider_block:
        return False
    provider_block.pop(LEGACY_COPILOT_CUSTOM_PROVIDER_ID, None)
    if provider_block:
        existing["provider"] = provider_block
    else:
        existing.pop("provider", None)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return True


def sync_github_copilot_opencode_config(
    *,
    project_dir: Optional[Path] = None,
    access_token: Optional[str] = None,
) -> GitHubCopilotSyncResponse:
    """Refresh Copilot models and remove any deprecated provider alias.

    OpenCode's native ``github-copilot`` provider authenticates from
    ``auth.json``, so Ostwin no longer writes a custom provider alias.  This
    fetches the live model list for the dashboard catalog and strips any
    ``github-copilot-oauth`` alias left behind by older versions.
    """
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

    targets = [
        get_user_opencode_config_path(),
        get_managed_opencode_config_path(),
    ]
    if project_dir is not None:
        targets.append(get_project_opencode_config_path(project_dir))

    cleaned_paths: list[str] = []
    skipped_paths: list[str] = []
    errors: list[str] = []
    for target in targets:
        if not target.exists():
            skipped_paths.append(str(target))
            continue
        try:
            _strip_legacy_copilot_alias(target)
            cleaned_paths.append(str(target))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{target}: {exc}")

    _refresh_models_after_auth()
    return GitHubCopilotSyncResponse(
        synced=not errors,
        paths=cleaned_paths,
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
    """Validate that ``access_token`` is accepted by the Copilot API.

    Performs the same two-step exchange as ``_fetch_copilot_model_ids`` so that
    browser-OAuth tokens are checked against real Copilot entitlement rather than
    against the GitHub API directly (which would always succeed).
    """
    try:
        _fetch_copilot_model_ids(access_token)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "GitHub browser OAuth succeeded, but GitHub Copilot rejected that token. "
            "Use Device code for OpenCode Copilot login."
        ) from exc


def _post_github_form(url: str, data: Dict[str, str], *, raise_on_error: bool = True) -> Dict[str, Any]:
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
    if raise_on_error and payload.get("error"):
        desc = payload.get("error_description") or payload.get("error")
        raise RuntimeError(f"GitHub OAuth error: {desc}")
    return payload


def _poll_github_device_token(device_code: str) -> Dict[str, Any]:
    return _post_github_form(
        GITHUB_ACCESS_TOKEN_URL,
        {
            "client_id": OPENCODE_COPILOT_CLIENT_ID,
            "device_code": device_code,
            "grant_type": GITHUB_DEVICE_GRANT_TYPE,
        },
        raise_on_error=False,
    )


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


def _poll_device_auth(session: Dict[str, Any]) -> None:
    device_code = session.get("device_code")
    if isinstance(device_code, str) and device_code:
        _poll_github_device_auth(session, device_code)
        return
    _update_device_session(session, status="error", message="GitHub device code was not provided.")


def _poll_github_device_auth(session: Dict[str, Any], device_code: str) -> None:
    interval = max(1, int(session.get("interval") or 5))
    expires_at = float(session.get("expires_at") or (time.time() + 900))

    while time.time() < expires_at:
        try:
            payload = _poll_github_device_token(device_code)
        except Exception as exc:  # noqa: BLE001
            _update_device_session(
                session,
                status="error",
                message=f"GitHub device authorization failed: {exc}",
            )
            return

        access_token = payload.get("access_token")
        if isinstance(access_token, str) and access_token:
            try:
                _save_github_oauth_token(access_token)
            except Exception as exc:  # noqa: BLE001
                _update_device_session(
                    session,
                    status="error",
                    message=str(exc),
                )
                return
            _update_device_session(
                session,
                status="connected",
                connected=True,
                message="GitHub Copilot credential saved for OpenCode.",
            )
            return

        error = str(payload.get("error") or "")
        if error == "authorization_pending":
            _update_device_session(session, message="Waiting for GitHub authorization.")
            time.sleep(interval)
            continue
        if error == "slow_down":
            interval += 5
            _update_device_session(session, message="Waiting for GitHub authorization.")
            time.sleep(interval)
            continue

        description = payload.get("error_description") or error or "GitHub did not return an access token."
        _update_device_session(
            session,
            status="error",
            message=f"GitHub device authorization failed: {description}",
        )
        return

    _update_device_session(
        session,
        status="error",
        message="GitHub device authorization expired. Start login again.",
    )


def start_github_copilot_device_auth() -> GitHubCopilotDeviceAuthResponse:
    global _device_auth_session

    with _auth_lock:
        if _device_auth_session and _device_auth_session.get("status") == "pending":
            return _device_auth_response_locked()

    _clear_broken_copilot_auth()

    payload = _post_github_form(
        GITHUB_DEVICE_CODE_URL,
        {
            "client_id": OPENCODE_COPILOT_CLIENT_ID,
            "scope": GITHUB_DEVICE_SCOPE,
        },
    )
    device_code = str(payload.get("device_code") or "")
    user_code = str(payload.get("user_code") or "")
    verification_url = str(payload.get("verification_uri") or payload.get("verification_url") or GITHUB_DEVICE_URL)
    if not device_code or not user_code:
        raise RuntimeError("GitHub did not return a device code.")

    interval = int(payload.get("interval") or 5)
    expires_in = int(payload.get("expires_in") or 900)
    session: Dict[str, Any] = {
        "status": "pending",
        "connected": False,
        "user_code": user_code,
        "verification_url": verification_url,
        "message": "Enter the GitHub device code, then authorize GitHub Copilot.",
        "device_code": device_code,
        "interval": interval,
        "expires_at": time.time() + expires_in,
        "output": "",
    }
    with _auth_lock:
        _device_auth_session = session

    thread = threading.Thread(target=_poll_device_auth, args=(session,), name="github-copilot-device-auth", daemon=True)
    thread.start()
    return _device_auth_response_locked()


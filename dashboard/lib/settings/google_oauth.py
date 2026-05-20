"""
Google OAuth2 flow for Vertex AI authentication.

Implements the OAuth2 Authorization Code flow using Google's well-known
desktop-app client credentials (the same ones ``gcloud auth`` uses).
The result is an Application Default Credentials (ADC) JSON file that
litellm and other Google SDKs pick up automatically.

Flow
----
1. ``start_oauth()`` → returns an authorization URL for the browser.
2. User authenticates in the browser, Google redirects to our callback.
3. ``exchange_code()`` → exchanges the auth code for tokens.
4. Tokens are saved as ADC at ``~/.config/gcloud/application_default_credentials.json``.

Security
--------
* PKCE (``code_verifier`` / ``code_challenge``) prevents auth-code interception.
* A random ``state`` parameter prevents CSRF.
* Tokens are stored with 0600 permissions (owner read/write only).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# ── Google's well-known desktop-app OAuth2 credentials ────────────────
# These are the same credentials ``gcloud auth application-default login``
# uses.  They are intentionally public (not secret) for installed/desktop
# apps per Google's OAuth2 documentation.
_CLIENT_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com"
_CLIENT_SECRET = "d-FL95Q19q7MQmFpd7hHD0Ty"

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

_ADC_DIR = Path.home() / ".config" / "gcloud"
_ADC_FILE = _ADC_DIR / "application_default_credentials.json"


# ── OAuth Session Data Structure ──────────────────────────────────────

@dataclass
class OAuthSession:
    state: str
    code_verifier: str
    redirect_uri: str
    project_id: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "code_verifier": self.code_verifier,
            "redirect_uri": self.redirect_uri,
            "project_id": self.project_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OAuthSession:
        return cls(**data)



# ── Public API ────────────────────────────────────────────────────────

def start_oauth(
    redirect_uri: str,
    project_id: str = "",
) -> Dict[str, Any]:
    """Generate an OAuth2 authorization URL and session data.

    Parameters
    ----------
    redirect_uri : str
        The callback URL on this dashboard server, e.g.
        ``http://localhost:3366/api/settings/google/oauth/callback``
    project_id : str
        GCP project ID (stored in the session for later use).

    Returns
    -------
    dict with ``authorization_url``, ``state``, and ``session`` (OAuthSession).
    """
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _s256(code_verifier)

    params = {
        "client_id": _CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }

    authorization_url = f"{_AUTH_URL}?{urlencode(params)}"

    session = OAuthSession(
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        project_id=project_id,
    )

    logger.info("[GOOGLE_OAUTH] OAuth flow generated (state=%s…)", state[:8])
    return {
        "authorization_url": authorization_url,
        "state": state,
        "session": session,
    }



def exchange_code(
    code: str, 
    state: str, 
    session: OAuthSession
) -> Dict[str, Any]:
    """Exchange an authorization code for tokens and save as ADC.

    Parameters
    ----------
    code : str
        The authorization code from Google's redirect.
    state : str
        Must match the ``state`` from the provided session.
    session : OAuthSession
        The session data recovered from external storage (e.g., cookie).

    Returns
    -------
    dict with ``status``, ``email`` (if available), and ``adc_path``.

    Raises
    ------
    ValueError
        If state doesn't match or session expired.
    RuntimeError
        If token exchange fails.
    """
    if session.state != state:
        raise ValueError("State mismatch — possible CSRF attack.")

    # Session expires after 10 minutes
    if time.time() - session.created_at > 600:
        raise ValueError("OAuth session expired. Please start again.")


    # Exchange code for tokens
    token_data = {
        "client_id": _CLIENT_ID,
        "client_secret": _CLIENT_SECRET,
        "code": code,
        "code_verifier": session.code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": session.redirect_uri,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(_TOKEN_URL, data=token_data)

    if resp.status_code != 200:
        error_detail = resp.text
        logger.error("[GOOGLE_OAUTH] Token exchange failed: %s", error_detail)
        raise RuntimeError(f"Token exchange failed: {error_detail}")

    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "No refresh_token returned. Ensure 'access_type=offline' and "
            "'prompt=consent' were used."
        )

    # Extract email from id_token (if present) for display purposes
    email = _extract_email(tokens.get("id_token", ""))

    # Detect project_id from the session or from the token info
    project_id = session.project_id

    # Save as Application Default Credentials
    adc = {
        "client_id": _CLIENT_ID,
        "client_secret": _CLIENT_SECRET,
        "refresh_token": refresh_token,
        "type": "authorized_user",
    }

    # If we got a quota_project_id, include it
    if project_id:
        adc["quota_project_id"] = project_id

    _save_adc(adc)

    logger.info(
        "[GOOGLE_OAUTH] ADC saved to %s (email=%s, project=%s)",
        _ADC_FILE, email or "unknown", project_id or "unset",
    )

    return {
        "status": "ok",
        "email": email,
        "adc_path": str(_ADC_FILE),
        "project_id": project_id,
    }


def get_oauth_status() -> Dict[str, Any]:
    """Check whether ADC exists and is valid.

    Returns
    -------
    dict with ``authenticated``, ``email``, ``adc_path``, ``type``.
    """
    if not _ADC_FILE.exists():
        return {"authenticated": False, "adc_path": str(_ADC_FILE)}

    try:
        adc = json.loads(_ADC_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"authenticated": False, "adc_path": str(_ADC_FILE), "error": "corrupt"}

    result: Dict[str, Any] = {
        "authenticated": False,
        "adc_path": str(_ADC_FILE),
        "type": adc.get("type", "unknown"),
    }

    if adc.get("quota_project_id"):
        result["project_id"] = adc["quota_project_id"]

    adc_type = adc.get("type", "unknown")
    if adc_type == "service_account":
        result["authenticated"] = True
        return result

    if adc_type == "authorized_user":
        authenticated, email, error = _refresh_adc(adc)
        result["authenticated"] = authenticated
        if email:
            result["email"] = email
        if error:
            result["error"] = error

    return result


# has_pending_session() removed as it relied on global state



# ── Internal helpers ──────────────────────────────────────────────────

def _s256(verifier: str) -> str:
    """Compute S256 code_challenge from a code_verifier."""
    import base64
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _save_adc(adc: Dict[str, Any]) -> None:
    """Save ADC JSON with restrictive permissions."""
    _ADC_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _ADC_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(adc, indent=2) + "\n")
        os.chmod(str(tmp), 0o600)
        os.replace(str(tmp), str(_ADC_FILE))
        os.chmod(str(_ADC_FILE), 0o600)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _extract_email(id_token: str) -> Optional[str]:
    """Extract email from a JWT id_token without verifying signature."""
    if not id_token:
        return None
    try:
        import base64
        parts = id_token.split(".")
        if len(parts) < 2:
            return None
        # Add padding
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("email")
    except Exception:
        return None


def _refresh_adc(adc: Dict[str, Any]) -> tuple[bool, Optional[str], Optional[str]]:
    """Refresh authorized-user ADC and return validity plus display metadata."""
    refresh_token = adc.get("refresh_token")
    if not refresh_token:
        return False, None, "missing_refresh_token"

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(_TOKEN_URL, data={
                "client_id": adc.get("client_id", _CLIENT_ID),
                "client_secret": adc.get("client_secret", _CLIENT_SECRET),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            })
    except Exception as exc:
        logger.warning("[GOOGLE_OAUTH] ADC refresh failed: %s", exc)
        return False, None, "refresh_failed"

    if resp.status_code != 200:
        error = _token_refresh_error(resp)
        logger.warning(
            "[GOOGLE_OAUTH] ADC refresh rejected (status=%s, error=%s)",
            resp.status_code,
            error,
        )
        return False, None, error

    try:
        tokens = resp.json()
    except Exception:
        return False, None, "invalid_token_response"

    if not tokens.get("access_token"):
        return False, None, "missing_access_token"

    return True, _extract_email(tokens.get("id_token", "")), None


def _token_refresh_error(resp: httpx.Response) -> str:
    """Return a stable, non-secret error code for a failed token refresh."""
    try:
        payload = resp.json()
    except Exception:
        return "refresh_failed"

    error = str(payload.get("error") or "").strip()
    if error == "invalid_grant":
        return "reauth_required"
    return error or "refresh_failed"

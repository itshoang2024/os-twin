"""
Auth module — ENV-based API-key authentication.

OSTWIN_API_KEY must be set. All API requests must include the key via:
  - Header: X-API-Key: <key>
  - Header: Authorization: Bearer <key>
  - Cookie: ostwin_auth_key=<key> (SameSite=Strict)

Local development can opt into a narrow frontend bypass with
OSTWIN_DEV_MODE=1. The bypass is limited to loopback requests associated
with localhost on the configured dev frontend port (default: 3000) or
127.0.0.1 on any explicit port.

Unauthenticated requests receive 401.
"""

import os
import secrets
from datetime import timedelta
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

# Kept for API compatibility with existing imports
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Read API key from environment at request time (not cached at import)
# so env_watcher and load_dotenv(override=True) changes take effect.
def _get_api_key() -> str:
    return os.environ.get("OSTWIN_API_KEY", "")

# Cookie name used by the frontend
AUTH_COOKIE_NAME = "ostwin_auth_key"
DEFAULT_DEV_FRONTEND_PORT = "3000"


def _is_dev_mode_enabled() -> bool:
    return os.environ.get("OSTWIN_DEV_MODE", "").lower() in {"1", "true", "yes"}


def _dev_frontend_port() -> str:
    return os.environ.get("OSTWIN_DEV_FRONTEND_PORT", DEFAULT_DEV_FRONTEND_PORT)


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_loopback_client(request: Request) -> bool:
    client_host = request.client.host if request.client else None
    return _is_loopback_host(client_host)


def _is_dev_frontend_location(value: str | None) -> bool:
    if not value:
        return False

    raw = value.strip()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    try:
        port = parsed.port
    except ValueError:
        return False

    hostname = parsed.hostname.strip().lower() if parsed.hostname else None
    if hostname == "127.0.0.1" and port is not None:
        return True

    return (
        hostname == "localhost"
        and port is not None
        and str(port) == _dev_frontend_port()
    )


def _is_local_dev_frontend_request(request: Request) -> bool:
    """Allow anonymous dev access only from explicit local frontend origins."""
    if not _is_dev_mode_enabled() or not _is_loopback_client(request):
        return False

    return any(
        _is_dev_frontend_location(value)
        for value in (
            request.headers.get("origin"),
            request.headers.get("referer"),
            request.headers.get("host"),
            request.headers.get("x-forwarded-host"),
        )
    )


# DEPRECATED: These stubs are retained for import compatibility only.
# Do NOT use them for actual authentication logic.
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """DEPRECATED — retained for import compatibility only. Always returns True."""
    return True


def get_password_hash(password: str) -> str:
    """DEPRECATED — retained for import compatibility only."""
    return "disabled"


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """DEPRECATED — retained for import compatibility only."""
    return "disabled"


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"ostwin_{secrets.token_urlsafe(32)}"


def _extract_api_key(request: Request) -> str | None:
    """Extract API key from request headers or cookies.

    Checks (in order):
      1. X-API-Key header
      2. Authorization: Bearer <key>
      3. Cookie: ostwin_auth_key (SameSite=Strict)
    """
    # Check X-API-Key header
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key

    # Check Authorization: Bearer <key>
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    # Check cookie
    cookie_key = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_key:
        return cookie_key

    return None


async def get_current_user(request: Request) -> dict:
    """Validate API key — always required.

    The key can be provided via header or cookie.
    Returns 401 if missing or invalid.
    
    SECURITY: User identity is derived from the API key, not from
    client-supplied headers. The X-User header is no longer trusted.
    """
    if _is_local_dev_frontend_request(request):
        return {"username": "dev-mode-user", "auth_mode": "dev"}

    provided_key = _extract_api_key(request)
    if not provided_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide via X-API-Key header, Authorization: Bearer <key>, or cookie.",
        )

    if not _get_api_key() or not secrets.compare_digest(provided_key, _get_api_key()):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )

    # SECURITY: Do not trust X-User header for identity — derive from API key only
    return {"username": "api-key-user"}

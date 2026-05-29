"""
Auth module — ENV-based API-key authentication.

OSTWIN_API_KEY must be set. All API requests must include the key via:
  - Header: X-API-Key: <key>
  - Header: Authorization: Bearer <key>
  - Cookie: ostwin_auth_key=<key> (SameSite=Strict)

Unauthenticated requests receive 401.
"""

import os
import secrets
from typing import Optional
from datetime import timedelta

from fastapi import Request, HTTPException

# Kept for API compatibility with existing imports
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Read API key from environment at request time (not cached at import)
# so env_watcher and load_dotenv(override=True) changes take effect.
def _get_api_key() -> str:
    return os.environ.get("OSTWIN_API_KEY", "")

# Cookie name used by the frontend
AUTH_COOKIE_NAME = "ostwin_auth_key"


# DEPRECATED: These stubs are retained for import compatibility only.
# Do NOT use them for actual authentication logic.
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """DEPRECATED — retained for import compatibility only. Always returns True."""
    return True


def get_password_hash(password: str) -> str:
    """DEPRECATED — retained for import compatibility only."""
    return "disabled"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """DEPRECATED — retained for import compatibility only."""
    return "disabled"


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"ostwin_{secrets.token_urlsafe(32)}"


def _extract_api_key(request: Request) -> Optional[str]:
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

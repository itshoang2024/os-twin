import os
import re
import shlex
from ipaddress import ip_address
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from dashboard.auth import _is_local_dev_frontend_request, get_configured_username, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Read API key at request time (not cached at import) so
# env_watcher and load_dotenv(override=True) changes take effect.
def _get_api_key() -> str:
    return os.environ.get("OSTWIN_API_KEY", "")
AUTH_COOKIE_NAME = "ostwin_auth_key"
_ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")


def _ostwin_env_file() -> Path:
    return Path(os.environ.get("OSTWIN_HOME", str(Path.home() / ".ostwin"))).expanduser() / ".env"


def _clean_username(value: object) -> str:
    username = str(value or "").strip()
    # Keep the local display name compact and header/log safe.
    username = re.sub(r"[\r\n\t]+", " ", username)
    username = re.sub(r"\s{2,}", " ", username)
    return username[:80]


def _is_loopback_request(request: Request) -> bool:
    host = request.client.host if request.client else None
    if not host:
        return False
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _upsert_env_values(path: Path, values: dict[str, str]) -> None:
    """Create/update ~/.ostwin/.env values while preserving unrelated lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    updated: list[str] = []

    for line in lines:
        match = _ENV_KEY_RE.match(line)
        key = match.group(1) if match else None
        if key in values:
            updated.append(f"{key}={shlex.quote(values[key])}")
            remaining.pop(key, None)
        else:
            updated.append(line)

    if remaining and updated and updated[-1].strip():
        updated.append("")
    for key, value in remaining.items():
        updated.append(f"{key}={shlex.quote(value)}")

    path.write_text("\n".join(updated).rstrip() + "\n")


def _persist_first_run_credentials(api_key: str, username: str) -> None:
    """Persist first-run auth credentials and update this process immediately."""
    _upsert_env_values(_ostwin_env_file(), {
        "OSTWIN_API_KEY": api_key,
        "OSTWIN_USERNAME": username,
    })
    os.environ["OSTWIN_API_KEY"] = api_key
    os.environ["OSTWIN_USERNAME"] = username


def _persist_username(username: str) -> None:
    _upsert_env_values(_ostwin_env_file(), {"OSTWIN_USERNAME": username})
    os.environ["OSTWIN_USERNAME"] = username


def _dev_auth_response() -> JSONResponse:
    return JSONResponse(content={
        "access_token": "dev-mode",
        "token_type": "dev",
        "username": "dev-mode-user",
        "auth_mode": "dev",
    })


@router.post("/token")
async def login_for_access_token(request: Request):
    """Authenticate with API key and set cookie.

    Accepts JSON body: {"key": "ostwin_..."} or form data.
    Sets the auth cookie on success.
    """
    if _is_local_dev_frontend_request(request):
        return _dev_auth_response()

    # Try JSON body
    key = None
    username = None
    try:
        body = await request.json()
        key = body.get("key", "")
        username = body.get("username", "")
    except Exception:
        # Try form data
        form = await request.form()
        key = form.get("key", "") or form.get("password", "")
        username = form.get("username", "")

    key = str(key or "").strip()
    username = _clean_username(username)

    # First-run setup: when no OSTWIN_API_KEY exists yet, the first local
    # dashboard login establishes both the API key and display username.
    if not _get_api_key():
        if not _is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "First-time setup is only available from localhost"},
            )
        if not key or not username:
            return JSONResponse(
                status_code=401,
                content={"detail": "First-time setup requires an OSTWIN API key and username", "setup_required": True},
            )
        _persist_first_run_credentials(key, username)

    if not key or not _get_api_key():
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid API key"},
        )

    import secrets
    if not secrets.compare_digest(str(key), _get_api_key()):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid API key"},
        )

    if username:
        _persist_username(username)

    # Set cookie and return token
    # SECURITY: Don't return the actual API key in the response body.
    # The cookie is set below and will be sent automatically.
    response = JSONResponse(content={
        "access_token": "authenticated",
        "token_type": "bearer",
        "username": get_configured_username(),
    })
    # P3-20: Use SameSite=Strict to prevent CSRF via cross-site requests.
    # HttpOnly prevents JavaScript access. Secure flag set when not localhost.
    is_localhost = request.url.hostname in ("localhost", "127.0.0.1")
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=_get_api_key(),
        httponly=True,
        secure=not is_localhost,
        samesite="strict",
        max_age=60 * 60 * 24 * 30,  # 30 days
        path="/",
    )
    return response


@router.get("/me")
async def read_users_me(request: Request):
    """Return current user info — validates the API key from header or cookie."""
    user = await get_current_user(request)
    return user


@router.post("/logout")
async def logout():
    """Clear the auth cookie."""
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return response

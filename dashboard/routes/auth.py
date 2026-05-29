import os
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Read API key at request time (not cached at import) so
# env_watcher and load_dotenv(override=True) changes take effect.
def _get_api_key() -> str:
    return os.environ.get("OSTWIN_API_KEY", "")
AUTH_COOKIE_NAME = "ostwin_auth_key"


@router.post("/token")
async def login_for_access_token(request: Request):
    """Authenticate with API key and set cookie.

    Accepts JSON body: {"key": "ostwin_..."} or form data.
    Sets the auth cookie on success.
    """
    # Try JSON body
    key = None
    try:
        body = await request.json()
        key = body.get("key", "")
    except Exception:
        # Try form data
        form = await request.form()
        key = form.get("key", "") or form.get("password", "")

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

    # Set cookie and return token
    # SECURITY: Don't return the actual API key in the response body.
    # The cookie is set below and will be sent automatically.
    response = JSONResponse(content={
        "access_token": "authenticated",
        "token_type": "bearer",
        "username": "api-key-user",
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
    from dashboard.auth import get_current_user as _get_user
    user = await _get_user(request)
    return user


@router.post("/logout")
async def logout():
    """Clear the auth cookie."""
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return response

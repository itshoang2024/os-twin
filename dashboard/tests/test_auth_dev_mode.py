import json

import pytest
from dashboard.auth import get_current_user
from dashboard.routes.auth import login_for_access_token, read_users_me
from fastapi import HTTPException
from starlette.requests import Request


def _request(headers: dict[str, str] | None = None, client_host: str = "127.0.0.1") -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/auth/me",
            "scheme": "http",
            "client": (client_host, 51234),
            "server": ("127.0.0.1", 3366),
            "headers": raw_headers,
        }
    )


@pytest.mark.asyncio
async def test_localhost_3000_allows_without_dev_mode_or_api_key(monkeypatch):
    monkeypatch.delenv("OSTWIN_DEV_MODE", raising=False)
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    user = await get_current_user(
        _request({"origin": "http://localhost:3000"})
    )

    assert user == {"username": "dev-mode-user", "auth_mode": "dev"}


@pytest.mark.asyncio
async def test_127_0_0_1_3000_allows_without_dev_mode_or_api_key(monkeypatch):
    monkeypatch.delenv("OSTWIN_DEV_MODE", raising=False)
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    user = await get_current_user(
        _request({"origin": "http://127.0.0.1:3000"})
    )

    assert user == {"username": "dev-mode-user", "auth_mode": "dev"}


@pytest.mark.asyncio
async def test_dev_mode_allows_loopback_frontend_3000_without_api_key(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    user = await get_current_user(
        _request({"referer": "http://localhost:3000/plans/new"})
    )

    assert user == {"username": "dev-mode-user", "auth_mode": "dev"}


@pytest.mark.asyncio
async def test_dev_mode_accepts_host_header_from_next_proxy(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    user = await get_current_user(_request({"host": "localhost:3000"}))

    assert user["auth_mode"] == "dev"


@pytest.mark.asyncio
async def test_dev_mode_accepts_forwarded_host_from_next_proxy(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    user = await get_current_user(
        _request({"host": "localhost:3366", "x-forwarded-host": "localhost:3000"})
    )

    assert user["auth_mode"] == "dev"


@pytest.mark.asyncio
async def test_dev_mode_accepts_127_0_0_1_on_any_frontend_port(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    user = await get_current_user(_request({"referer": "http://127.0.0.1:5173/"}))

    assert user["auth_mode"] == "dev"


@pytest.mark.asyncio
async def test_dev_mode_rejects_wrong_frontend_port(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_request({"referer": "http://localhost:3001"}))

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_dev_mode_rejects_remote_client_spoofing_frontend_header(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            _request({"origin": "http://localhost:3000"}, client_host="203.0.113.10")
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_dev_mode_rejects_remote_client_spoofing_127_header(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            _request({"origin": "http://127.0.0.1:5173"}, client_host="203.0.113.10")
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_normal_mode_still_requires_api_key_for_non_default_frontend(monkeypatch):
    monkeypatch.delenv("OSTWIN_DEV_MODE", raising=False)
    monkeypatch.setenv("OSTWIN_API_KEY", "test-key")

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_request({"referer": "http://localhost:3001"}))

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_normal_mode_rejects_127_0_0_1_frontend_without_dev_mode(monkeypatch):
    monkeypatch.delenv("OSTWIN_DEV_MODE", raising=False)
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_request({"origin": "http://127.0.0.1:5173"}))

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_default_localhost_3000_rejects_remote_client_spoofing_header(monkeypatch):
    monkeypatch.delenv("OSTWIN_DEV_MODE", raising=False)
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            _request({"origin": "http://localhost:3000"}, client_host="203.0.113.10")
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_default_127_0_0_1_3000_rejects_remote_client_spoofing_header(monkeypatch):
    monkeypatch.delenv("OSTWIN_DEV_MODE", raising=False)
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(
            _request({"origin": "http://127.0.0.1:3000"}, client_host="203.0.113.10")
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_api_key_auth_still_works(monkeypatch):
    monkeypatch.delenv("OSTWIN_DEV_MODE", raising=False)
    monkeypatch.setenv("OSTWIN_API_KEY", "test-key")

    user = await get_current_user(_request({"x-api-key": "test-key"}))

    assert user == {"username": "api-key-user"}


@pytest.mark.asyncio
async def test_auth_me_route_uses_dev_mode_for_localhost_3000(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    user = await read_users_me(_request({"referer": "http://localhost:3000/"}))

    assert user == {"username": "dev-mode-user", "auth_mode": "dev"}


@pytest.mark.asyncio
async def test_auth_token_route_uses_dev_mode_for_localhost_3000(monkeypatch):
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)

    response = await login_for_access_token(
        _request({"referer": "http://localhost:3000/"})
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "access_token": "dev-mode",
        "token_type": "dev",
        "username": "dev-mode-user",
        "auth_mode": "dev",
    }

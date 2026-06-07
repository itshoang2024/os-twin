"""Tests for dashboard/tunnel.py and dashboard/routes/tunnel.py."""

import os

os.environ["OSTWIN_API_KEY"] = "DEBUG"

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import dashboard.tunnel as tunnel_mod


# ── tunnel.py module tests (mock pyngrok) ──────────────────────────


class TestTunnelModule:
    """Tests for dashboard/tunnel.py — start/stop/status functions."""

    @pytest.fixture(autouse=True)
    def reset_module_state(self):
        """Reset tunnel module state before each test."""
        tunnel_mod._tunnel = None
        tunnel_mod._tunnel_url = None
        tunnel_mod._started_at = None
        tunnel_mod._error = None
        yield
        tunnel_mod._tunnel = None
        tunnel_mod._tunnel_url = None
        tunnel_mod._started_at = None
        tunnel_mod._error = None

    @pytest.mark.asyncio
    async def test_start_tunnel_sets_state_and_returns_url(self):
        mock_tunnel = MagicMock()
        mock_tunnel.public_url = "https://abc123.ngrok.io"

        mock_ngrok = MagicMock()
        mock_ngrok.connect.return_value = mock_tunnel
        mock_ngrok.kill = MagicMock()
        mock_ngrok.disconnect = MagicMock()

        mock_conf = MagicMock()
        mock_conf.get_default.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "pyngrok": MagicMock(),
            "pyngrok.ngrok": mock_ngrok,
            "pyngrok.conf": mock_conf,
        }):
            with patch("dashboard.tunnel.ngrok", mock_ngrok, create=True):
                # We need to patch the import inside the function
                with patch("builtins.__import__", side_effect=lambda name, *args, **kwargs: (
                    MagicMock(ngrok=mock_ngrok, conf=mock_conf) if name == "pyngrok" else __builtins__.__import__(name, *args, **kwargs)
                )):
                    # Simpler approach: directly mock the import inside start_tunnel
                    pass

        # Use a more straightforward patching approach
        mock_tunnel_obj = MagicMock()
        mock_tunnel_obj.public_url = "https://abc123.ngrok.io"

        mock_ngrok_module = MagicMock()
        mock_ngrok_module.connect.return_value = mock_tunnel_obj
        mock_conf_module = MagicMock()
        mock_conf_module.get_default.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "pyngrok": MagicMock(ngrok=mock_ngrok_module, conf=mock_conf_module),
            "pyngrok.ngrok": mock_ngrok_module,
            "pyngrok.conf": mock_conf_module,
        }):
            url = await tunnel_mod.start_tunnel(3366, "test-token")
            assert url == "https://abc123.ngrok.io"
            assert tunnel_mod._tunnel_url == "https://abc123.ngrok.io"
            assert tunnel_mod._started_at is not None
            assert tunnel_mod._error is None

    @pytest.mark.asyncio
    async def test_start_tunnel_failure_sets_error(self):
        mock_ngrok_module = MagicMock()
        mock_ngrok_module.connect.side_effect = RuntimeError("ngrok failed")
        mock_conf_module = MagicMock()
        mock_conf_module.get_default.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "pyngrok": MagicMock(ngrok=mock_ngrok_module, conf=mock_conf_module),
            "pyngrok.ngrok": mock_ngrok_module,
            "pyngrok.conf": mock_conf_module,
        }):
            with pytest.raises(RuntimeError, match="ngrok failed"):
                await tunnel_mod.start_tunnel(3366, "test-token")

        assert tunnel_mod._tunnel is None
        assert tunnel_mod._tunnel_url is None
        assert tunnel_mod._error == "ngrok failed"

    def test_stop_tunnel_clears_state(self):
        # Set up fake state
        tunnel_mod._tunnel = MagicMock()
        tunnel_mod._tunnel.public_url = "https://xyz.ngrok.io"
        tunnel_mod._tunnel_url = "https://xyz.ngrok.io"
        tunnel_mod._started_at = "2026-01-01T00:00:00Z"
        tunnel_mod._error = None

        mock_ngrok = MagicMock()
        with patch.dict("sys.modules", {
            "pyngrok": MagicMock(ngrok=mock_ngrok),
            "pyngrok.ngrok": mock_ngrok,
        }):
            tunnel_mod.stop_tunnel()

        assert tunnel_mod._tunnel is None
        assert tunnel_mod._tunnel_url is None
        assert tunnel_mod._started_at is None
        assert tunnel_mod._error is None

    def test_stop_tunnel_when_no_tunnel(self):
        """stop_tunnel() should not raise when there's no active tunnel."""
        tunnel_mod.stop_tunnel()
        assert tunnel_mod._tunnel is None

    def test_get_tunnel_url_returns_current_url(self):
        tunnel_mod._tunnel_url = "https://my-tunnel.ngrok.io"
        assert tunnel_mod.get_tunnel_url() == "https://my-tunnel.ngrok.io"

    def test_get_tunnel_url_returns_none_when_inactive(self):
        assert tunnel_mod.get_tunnel_url() is None

    def test_get_tunnel_status_active(self):
        tunnel_mod._tunnel_url = "https://active.ngrok.io"
        tunnel_mod._started_at = "2026-04-01T12:00:00Z"
        tunnel_mod._error = None

        status = tunnel_mod.get_tunnel_status()
        assert status["active"] is True
        assert status["url"] == "https://active.ngrok.io"
        assert status["started_at"] == "2026-04-01T12:00:00Z"
        assert status["error"] is None

    def test_get_tunnel_status_inactive(self):
        status = tunnel_mod.get_tunnel_status()
        assert status["active"] is False
        assert status["url"] is None
        assert status["started_at"] is None
        assert status["error"] is None

    def test_get_tunnel_status_with_error(self):
        tunnel_mod._error = "Connection refused"
        status = tunnel_mod.get_tunnel_status()
        assert status["active"] is False
        assert status["error"] == "Connection refused"

    @pytest.mark.asyncio
    async def test_start_tunnel_with_existing_disconnects_first(self):
        """If a tunnel is already active, start_tunnel should disconnect it first."""
        old_tunnel = MagicMock()
        old_tunnel.public_url = "https://old.ngrok.io"
        tunnel_mod._tunnel = old_tunnel

        new_tunnel = MagicMock()
        new_tunnel.public_url = "https://new.ngrok.io"

        mock_ngrok_module = MagicMock()
        mock_ngrok_module.connect.return_value = new_tunnel
        mock_conf_module = MagicMock()
        mock_conf_module.get_default.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "pyngrok": MagicMock(ngrok=mock_ngrok_module, conf=mock_conf_module),
            "pyngrok.ngrok": mock_ngrok_module,
            "pyngrok.conf": mock_conf_module,
        }):
            url = await tunnel_mod.start_tunnel(3366, "test-token")

        assert url == "https://new.ngrok.io"
        # Old tunnel should have been disconnected
        mock_ngrok_module.disconnect.assert_called_with("https://old.ngrok.io")

    @pytest.mark.asyncio
    async def test_start_tunnel_with_domain_passes_hostname(self):
        mock_tunnel_obj = MagicMock()
        mock_tunnel_obj.public_url = "https://custom.example.com"

        mock_ngrok_module = MagicMock()
        mock_ngrok_module.connect.return_value = mock_tunnel_obj
        mock_conf_module = MagicMock()
        mock_conf_module.get_default.return_value = MagicMock()

        with patch.dict("sys.modules", {
            "pyngrok": MagicMock(ngrok=mock_ngrok_module, conf=mock_conf_module),
            "pyngrok.ngrok": mock_ngrok_module,
            "pyngrok.conf": mock_conf_module,
        }):
            await tunnel_mod.start_tunnel(3366, "test-token", domain="custom.example.com")

        # Verify hostname was passed in connect kwargs
        call_kwargs = mock_ngrok_module.connect.call_args[1]
        assert call_kwargs["hostname"] == "custom.example.com"


# ── routes/tunnel.py endpoint tests ────────────────────────────────


class TestTunnelRoutes:
    """Tests for dashboard/routes/tunnel.py endpoints."""

    @pytest.fixture
    def test_client(self):
        from fastapi.testclient import TestClient
        from dashboard.api import app
        return TestClient(app)

    def test_get_tunnel_status(self, test_client):
        with patch.object(tunnel_mod, "get_tunnel_status", return_value={
            "active": False, "url": None, "started_at": None, "error": None,
        }):
            resp = test_client.get("/api/tunnel/status", headers={"X-API-Key": "DEBUG"})
            assert resp.status_code == 200
            data = resp.json()
            assert "active" in data
            assert data["active"] is False

    def test_restart_without_ngrok_authtoken(self, test_client, monkeypatch):
        monkeypatch.delenv("NGROK_AUTHTOKEN", raising=False)
        resp = test_client.post("/api/tunnel/restart", headers={"X-API-Key": "DEBUG"})
        assert resp.status_code == 400
        assert "NGROK_AUTHTOKEN" in resp.json()["detail"]

    def test_restart_with_token_success(self, test_client, monkeypatch):
        monkeypatch.setenv("NGROK_AUTHTOKEN", "fake-token")
        monkeypatch.setenv("DASHBOARD_PORT", "3366")
        monkeypatch.delenv("NGROK_DOMAIN", raising=False)

        with patch.object(tunnel_mod, "stop_tunnel") as mock_stop, \
             patch.object(tunnel_mod, "start_tunnel", new_callable=AsyncMock,
                          return_value="https://restarted.ngrok.io") as mock_start:
            resp = test_client.post("/api/tunnel/restart", headers={"X-API-Key": "DEBUG"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["url"] == "https://restarted.ngrok.io"
            assert "restarted" in data["message"].lower()
            mock_stop.assert_called_once()
            mock_start.assert_awaited_once()

    def test_restart_failure_returns_500(self, test_client, monkeypatch):
        monkeypatch.setenv("NGROK_AUTHTOKEN", "fake-token")
        monkeypatch.setenv("DASHBOARD_PORT", "3366")
        monkeypatch.delenv("NGROK_DOMAIN", raising=False)

        with patch.object(tunnel_mod, "stop_tunnel"), \
             patch.object(tunnel_mod, "start_tunnel", new_callable=AsyncMock,
                          side_effect=RuntimeError("ngrok boom")):
            resp = test_client.post("/api/tunnel/restart", headers={"X-API-Key": "DEBUG"})
            assert resp.status_code == 500
            assert "ngrok boom" in resp.json()["detail"]

    def test_share_without_active_tunnel(self, test_client):
        with patch.object(tunnel_mod, "get_tunnel_url", return_value=None):
            resp = test_client.post("/api/tunnel/share", headers={"X-API-Key": "DEBUG"})
            assert resp.status_code == 400
            assert "No active tunnel" in resp.json()["detail"]

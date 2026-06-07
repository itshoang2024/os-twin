"""Tests for dashboard/ws_router.py — ConnectionManager and WS endpoint."""

import os

os.environ["OSTWIN_API_KEY"] = "DEBUG"

import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dashboard.ws_router import ConnectionManager, handle_client_message


# ── ConnectionManager unit tests ───────────────────────────────────


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    @pytest.fixture
    def mgr(self):
        """Fresh ConnectionManager for each test."""
        return ConnectionManager()

    @pytest.fixture
    def mock_ws(self):
        """Create a mock WebSocket."""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect_adds_websocket(self, mgr, mock_ws):
        await mgr.connect(mock_ws)
        assert mock_ws in mgr.active_connections
        assert mgr.client_count == 1
        mock_ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_websocket(self, mgr, mock_ws):
        await mgr.connect(mock_ws)
        assert mgr.client_count == 1
        mgr.disconnect(mock_ws)
        assert mock_ws not in mgr.active_connections
        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_no_error(self, mgr, mock_ws):
        # Should not raise even if ws was never added
        mgr.disconnect(mock_ws)
        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self, mgr):
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()

        await mgr.connect(ws1)
        await mgr.connect(ws2)
        assert mgr.client_count == 2

        message = {"type": "test", "data": "hello"}
        await mgr.broadcast(message)

        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_removes_disconnected_clients(self, mgr):
        ws_good = AsyncMock()
        ws_good.accept = AsyncMock()
        ws_good.send_json = AsyncMock()

        ws_bad = AsyncMock()
        ws_bad.accept = AsyncMock()
        ws_bad.send_json = AsyncMock(side_effect=RuntimeError("connection closed"))

        await mgr.connect(ws_good)
        await mgr.connect(ws_bad)
        assert mgr.client_count == 2

        await mgr.broadcast({"type": "test"})

        # The bad connection should have been removed
        assert mgr.client_count == 1
        assert ws_good in mgr.active_connections
        assert ws_bad not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_epic_progress(self, mgr, mock_ws):
        await mgr.connect(mock_ws)
        await mgr.broadcast_epic_progress("plan-1", "EPIC-001", "running", 50)

        mock_ws.send_json.assert_awaited_once()
        call_arg = mock_ws.send_json.call_args[0][0]
        assert call_arg["type"] == "epic_progress"
        assert call_arg["plan_id"] == "plan-1"
        assert call_arg["epic_ref"] == "EPIC-001"
        assert call_arg["status"] == "running"
        assert call_arg["progress"] == 50

    @pytest.mark.asyncio
    async def test_broadcast_connection_health(self, mgr, mock_ws):
        await mgr.connect(mock_ws)
        await mgr.broadcast_connection_health("ngrok", "healthy", latency=42.5)

        mock_ws.send_json.assert_awaited_once()
        call_arg = mock_ws.send_json.call_args[0][0]
        assert call_arg["type"] == "connection_health"
        assert call_arg["service"] == "ngrok"
        assert call_arg["status"] == "healthy"
        assert call_arg["latency"] == 42.5

    @pytest.mark.asyncio
    async def test_client_count_property(self, mgr):
        assert mgr.client_count == 0

        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        await mgr.connect(ws1)
        assert mgr.client_count == 1

        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        await mgr.connect(ws2)
        assert mgr.client_count == 2

        mgr.disconnect(ws1)
        assert mgr.client_count == 1


# ── handle_client_message tests ────────────────────────────────────


class TestHandleClientMessage:
    """Tests for handle_client_message()."""

    @pytest.mark.asyncio
    async def test_ping_sends_pong(self):
        ws = AsyncMock()
        await handle_client_message(ws, {"type": "ping"})
        ws.send_json.assert_awaited_once()
        call_arg = ws.send_json.call_args[0][0]
        assert call_arg["type"] == "pong"
        assert "ts" in call_arg

    @pytest.mark.asyncio
    async def test_unknown_type_no_response(self):
        ws = AsyncMock()
        await handle_client_message(ws, {"type": "unknown_event"})
        ws.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_message_no_response(self):
        ws = AsyncMock()
        await handle_client_message(ws, {})
        ws.send_json.assert_not_awaited()


# ── WebSocket endpoint integration tests ───────────────────────────


class TestWebSocketEndpoint:
    """Integration tests using TestClient WebSocket support."""

    def test_connect_receives_connected_event(self):
        from fastapi.testclient import TestClient
        from dashboard.api import app

        with TestClient(app).websocket_connect("/api/ws") as ws:
            data = ws.receive_json()
            assert data["event"] == "connected"
            assert "timestamp" in data

    def test_ping_pong_works(self):
        from fastapi.testclient import TestClient
        from dashboard.api import app

        with TestClient(app).websocket_connect("/api/ws") as ws:
            # Consume the initial "connected" event
            ws.receive_json()

            ws.send_text(json.dumps({"type": "ping"}))
            response = ws.receive_json()
            assert response["type"] == "pong"
            assert "ts" in response

    def test_invalid_json_ignored(self):
        from fastapi.testclient import TestClient
        from dashboard.api import app

        with TestClient(app).websocket_connect("/api/ws") as ws:
            # Consume the initial "connected" event
            ws.receive_json()

            # Send invalid JSON — should not crash the connection
            ws.send_text("not valid json {{{")

            # Send a valid ping to verify still connected
            ws.send_text(json.dumps({"type": "ping"}))
            response = ws.receive_json()
            assert response["type"] == "pong"

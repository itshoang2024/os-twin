"""Tests for dashboard/routes/command.py — in-memory command & conversation API."""

import os
import sys
from unittest.mock import MagicMock

os.environ["OSTWIN_API_KEY"] = "DEBUG"

import pytest
from fastapi.testclient import TestClient

from dashboard.api import app
from dashboard.routes.command import _generate_reply, _conversations

client = TestClient(app)
HEADERS = {"X-API-Key": "DEBUG"}


@pytest.fixture(autouse=True)
def clear_conversations():
    """Clear in-memory conversation store between tests."""
    _conversations.clear()
    yield
    _conversations.clear()


# ── _generate_reply unit tests ─────────────────────────────────────


class TestGenerateReply:
    """Tests for _generate_reply() helper."""

    def test_status_keyword(self):
        reply = _generate_reply("What's the status?")
        assert "current status" in reply.lower()
        assert "War rooms" in reply

    def test_whats_running_keyword(self):
        reply = _generate_reply("what's running right now?")
        assert "current status" in reply.lower()
        assert "Plans tab" in reply

    def test_active_keyword(self):
        reply = _generate_reply("show me active tasks")
        assert "War rooms" in reply
        assert "Plans tab" in reply

    def test_create_plan_keyword(self):
        reply = _generate_reply("create plan for my app")
        assert "Plans" in reply or "plan" in reply.lower()
        assert "create plan for my app" in reply

    def test_build_keyword(self):
        reply = _generate_reply("build a chatbot")
        assert "build a chatbot" in reply

    def test_deploy_keyword(self):
        reply = _generate_reply("deploy to production")
        assert "deploy to production" in reply

    def test_make_keyword(self):
        reply = _generate_reply("make a landing page")
        assert "make a landing page" in reply

    def test_hello_no_keyword_match(self):
        reply = _generate_reply("hello")
        assert "hello" in reply
        # Generic response mentions available features
        assert "Plans" in reply or "MCP" in reply or "Channels" in reply

    def test_message_text_included_in_response(self):
        reply = _generate_reply("my unique message 12345")
        assert "my unique message 12345" in reply


# ── POST /api/command ──────────────────────────────────────────────


class TestPostCommand:
    """Tests for POST /api/command endpoint."""

    def test_new_conversation_created(self):
        resp = client.post(
            "/api/command",
            json={"message": "Hello world"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "command_response"
        assert "content" in data
        assert data["conversation_id"].startswith("conv-")

    def test_existing_conversation_continued(self):
        # Create a conversation first
        resp1 = client.post(
            "/api/command",
            json={"message": "First message"},
            headers=HEADERS,
        )
        conv_id = resp1.json()["conversation_id"]

        # Continue with the same conversation_id
        resp2 = client.post(
            "/api/command",
            json={"message": "Second message", "conversation_id": conv_id},
            headers=HEADERS,
        )
        assert resp2.status_code == 200
        assert resp2.json()["conversation_id"] == conv_id

    def test_returns_correct_shape(self):
        resp = client.post(
            "/api/command",
            json={"message": "test"},
            headers=HEADERS,
        )
        data = resp.json()
        assert "type" in data
        assert "content" in data
        assert "conversation_id" in data

    def test_user_and_assistant_messages_added(self):
        resp = client.post(
            "/api/command",
            json={"message": "Add me"},
            headers=HEADERS,
        )
        conv_id = resp.json()["conversation_id"]

        # Fetch the conversation to verify messages
        conv_resp = client.get(f"/api/conversations/{conv_id}", headers=HEADERS)
        assert conv_resp.status_code == 200
        messages = conv_resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Add me"
        assert messages[1]["role"] == "assistant"

    def test_multiple_messages_in_conversation(self):
        resp1 = client.post(
            "/api/command",
            json={"message": "First"},
            headers=HEADERS,
        )
        conv_id = resp1.json()["conversation_id"]
        client.post(
            "/api/command",
            json={"message": "Second", "conversation_id": conv_id},
            headers=HEADERS,
        )

        conv_resp = client.get(f"/api/conversations/{conv_id}", headers=HEADERS)
        messages = conv_resp.json()["messages"]
        # 2 user messages + 2 assistant replies = 4
        assert len(messages) == 4


# ── GET /api/conversations/{conv_id} ───────────────────────────────


class TestGetConversation:
    """Tests for GET /api/conversations/{conv_id} endpoint."""

    def test_existing_conversation_returned(self):
        resp = client.post(
            "/api/command",
            json={"message": "Create me"},
            headers=HEADERS,
        )
        conv_id = resp.json()["conversation_id"]

        conv_resp = client.get(f"/api/conversations/{conv_id}", headers=HEADERS)
        assert conv_resp.status_code == 200
        data = conv_resp.json()
        assert data["id"] == conv_id
        assert "title" in data
        assert "messages" in data
        assert len(data["messages"]) >= 2

    def test_nonexistent_conversation_404(self):
        resp = client.get("/api/conversations/conv-nonexistent", headers=HEADERS)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

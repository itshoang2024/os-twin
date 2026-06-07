"""
Tests for template-based brainstorm flow.

Covers:
- build_messages preserves <template> content in HumanMessage
- Template annotation format: @Name + user brief + <template> block
- Thread creation with template_meta
- Streaming endpoint passes full template content to brainstorm_stream
- build_messages with chat history + template message
- BRAINSTORM_SYSTEM_PROMPT contains template-aware instructions
"""

import pytest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from dashboard.api import app
from dashboard.plan_agent import build_messages, BRAINSTORM_SYSTEM_PROMPT
from dashboard.planning_thread_store import PlanningThreadStore
import dashboard.global_state as global_state


# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_TEMPLATE = """\
# Launch plan for {{product name}}

## What it is, in one sentence
{{ }}

## Who it's for
{{ }}

## Launch surfaces (pick any)
- [ ] Landing page
- [ ] Waitlist signup
- [ ] Email announcement

## Tone
{{e.g. confident, technical, playful}}

---

Turn the details I've filled in above into an Ostwin plan."""

SAMPLE_USER_BRIEF = "developing new plan for ostwin to launch opensource"

SAMPLE_TEMPLATE_NAME = "Product launch (landing + email + waitlist)"


def _compose_template_message(
    template_name: str = SAMPLE_TEMPLATE_NAME,
    user_brief: str = SAMPLE_USER_BRIEF,
    template_content: str = SAMPLE_TEMPLATE,
) -> str:
    """Compose a message in the same format the frontend produces."""
    return f"@{template_name}\n\n{user_brief}\n\n---\n\n<template>\n{template_content}\n</template>"


@pytest.fixture
def client(tmp_path):
    store = PlanningThreadStore(base_dir=tmp_path)
    global_state.planning_store = store

    from dashboard.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user"}

    with patch("dashboard.api.startup_all", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


# ── build_messages unit tests ─────────────────────────────────────────

class TestBuildMessagesWithTemplate:
    """Verify build_messages preserves the full template content."""

    def test_template_in_human_message(self):
        """The <template> block must appear verbatim in the HumanMessage."""
        msg = _compose_template_message()
        messages = build_messages(user_message=msg)

        assert len(messages) == 1
        human = messages[0]
        assert isinstance(human, HumanMessage)

        content = human.content if isinstance(human.content, str) else human.content[0]["text"]
        assert "<template>" in content
        assert "</template>" in content
        assert "{{product name}}" in content
        assert "## Launch surfaces" in content

    def test_template_annotation_preserved(self):
        """The @TemplateName annotation is in the message."""
        msg = _compose_template_message()
        messages = build_messages(user_message=msg)

        content = messages[0].content if isinstance(messages[0].content, str) else messages[0].content[0]["text"]
        assert f"@{SAMPLE_TEMPLATE_NAME}" in content

    def test_user_brief_preserved(self):
        """The user's own brief text is in the message."""
        msg = _compose_template_message()
        messages = build_messages(user_message=msg)

        content = messages[0].content if isinstance(messages[0].content, str) else messages[0].content[0]["text"]
        assert SAMPLE_USER_BRIEF in content

    def test_no_plan_content_means_no_system_message(self):
        """When plan_content is empty, no SystemMessage is injected."""
        messages = build_messages(user_message="test", plan_content="")
        assert not any(isinstance(m, SystemMessage) for m in messages)

    def test_plan_content_injects_system_message(self):
        """When plan_content is provided, a SystemMessage appears first."""
        messages = build_messages(
            user_message="update the plan",
            plan_content="# My Plan\n\n## Goal\nBuild a thing",
        )
        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert "My Plan" in messages[0].content

    def test_chat_history_plus_template_message(self):
        """Chat history is followed by the current template message."""
        history = [
            {"role": "user", "content": "I want to build something"},
            {"role": "assistant", "content": "Tell me more about your idea."},
        ]
        msg = _compose_template_message()
        messages = build_messages(user_message=msg, chat_history=history)

        assert len(messages) == 3
        assert isinstance(messages[0], HumanMessage)
        assert isinstance(messages[1], AIMessage)
        assert isinstance(messages[2], HumanMessage)

        # The last message is the template message
        last_content = messages[2].content if isinstance(messages[2].content, str) else messages[2].content[0]["text"]
        assert "<template>" in last_content

    def test_message_without_template(self):
        """A plain message (no template) works normally."""
        messages = build_messages(user_message="Build me a todo app")
        assert len(messages) == 1
        content = messages[0].content if isinstance(messages[0].content, str) else messages[0].content[0]["text"]
        assert content == "Build me a todo app"
        assert "<template>" not in content

    def test_template_with_all_placeholders_unfilled(self):
        """A template where user filled nothing should still pass through."""
        msg = _compose_template_message(user_brief="")
        messages = build_messages(user_message=msg)

        content = messages[0].content if isinstance(messages[0].content, str) else messages[0].content[0]["text"]
        assert "{{ }}" in content
        assert "{{product name}}" in content


# ── BRAINSTORM_SYSTEM_PROMPT ──────────────────────────────────────────

class TestBrainstormSystemPrompt:
    """Verify the system prompt contains template-aware instructions."""

    def test_mentions_template_format(self):
        assert "<template>" in BRAINSTORM_SYSTEM_PROMPT
        assert "</template>" in BRAINSTORM_SYSTEM_PROMPT

    def test_mentions_annotation_format(self):
        assert "@Template Name" in BRAINSTORM_SYSTEM_PROMPT

    def test_mentions_placeholder_markers(self):
        assert "{{ }}" in BRAINSTORM_SYSTEM_PROMPT

    def test_instructs_not_to_show_raw_template(self):
        assert "do NOT repeat" in BRAINSTORM_SYSTEM_PROMPT or "Never show the raw template" in BRAINSTORM_SYSTEM_PROMPT

    def test_instructs_conversational_exploration(self):
        assert "2-3 at a time" in BRAINSTORM_SYSTEM_PROMPT


# ── Thread creation with template ────────────────────────────────────

class TestThreadCreationWithTemplate:
    """Verify thread creation stores template metadata and full content."""

    def test_create_thread_with_template_message(self, client):
        msg = _compose_template_message()
        response = client.post("/api/plans/threads", json={
            "message": msg,
            "template_name": SAMPLE_TEMPLATE_NAME,
        })
        assert response.status_code == 201
        data = response.json()
        thread_id = data["thread_id"]

        # Retrieve and verify the stored message
        t_res = client.get(f"/api/plans/threads/{thread_id}")
        messages = t_res.json()["messages"]
        assert len(messages) == 1
        stored = messages[0]["content"]
        assert "<template>" in stored
        assert "</template>" in stored
        assert "{{product name}}" in stored
        assert SAMPLE_USER_BRIEF in stored

    def test_create_thread_stores_template_meta(self, client):
        msg = _compose_template_message()
        response = client.post("/api/plans/threads", json={
            "message": msg,
            "template_name": SAMPLE_TEMPLATE_NAME,
            "template_id": "product-launch",
        })
        thread_id = response.json()["thread_id"]

        t_res = client.get(f"/api/plans/threads/{thread_id}")
        thread = t_res.json()["thread"]
        assert thread.get("template_meta") is not None
        assert thread["template_meta"]["template_name"] == SAMPLE_TEMPLATE_NAME

    def test_create_thread_without_template(self, client):
        response = client.post("/api/plans/threads", json={"message": "Build a todo app"})
        assert response.status_code == 201
        thread_id = response.json()["thread_id"]

        t_res = client.get(f"/api/plans/threads/{thread_id}")
        messages = t_res.json()["messages"]
        assert messages[0]["content"] == "Build a todo app"
        assert "<template>" not in messages[0]["content"]


# ── Streaming endpoint with template ─────────────────────────────────

class TestStreamWithTemplate:
    """Verify the stream endpoint passes the full template message to brainstorm_stream."""

    @patch("dashboard.routes.threads.brainstorm_stream")
    def test_stream_receives_full_template_content(self, mock_stream, client):
        """brainstorm_stream must receive the full message including <template>."""
        captured_args = {}

        async def capture_and_yield(*args, **kwargs):
            captured_args.update(kwargs)
            yield "Got it!"

        mock_stream.side_effect = capture_and_yield

        msg = _compose_template_message()
        res = client.post("/api/plans/threads", json={"message": msg})
        thread_id = res.json()["thread_id"]

        # The auto-trigger sends the stored message to /stream
        client.post(
            f"/api/plans/threads/{thread_id}/messages/stream",
            json={"message": msg},
        )

        # Verify brainstorm_stream was called with the full template content
        assert "user_message" in captured_args
        received = captured_args["user_message"]
        assert "<template>" in received
        assert "</template>" in received
        assert "{{product name}}" in received
        assert SAMPLE_USER_BRIEF in received

    @patch("dashboard.routes.threads.brainstorm_stream")
    def test_stream_dedup_does_not_lose_content(self, mock_stream, client):
        """When auto-trigger re-sends the same message, dedup should keep the full content."""
        async def mock_gen(*args, **kwargs):
            yield "Response"

        mock_stream.side_effect = mock_gen

        msg = _compose_template_message()
        res = client.post("/api/plans/threads", json={"message": msg})
        thread_id = res.json()["thread_id"]

        # Send the same message (simulates IdeaChat auto-trigger)
        client.post(
            f"/api/plans/threads/{thread_id}/messages/stream",
            json={"message": msg},
        )

        # Verify messages: should be 1 user (deduped) + 1 assistant
        t_res = client.get(f"/api/plans/threads/{thread_id}")
        messages = t_res.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert "<template>" in messages[0]["content"]
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Response"


# ── Template format composition ──────────────────────────────────────

class TestTemplateMessageFormat:
    """Verify the message format matches what the frontend produces."""

    def test_format_with_brief(self):
        msg = _compose_template_message(
            template_name="Web app",
            user_brief="A todo app with auth",
            template_content="# {{name}}\n## Goal\n{{ }}",
        )
        assert msg.startswith("@Web app\n\n")
        assert "A todo app with auth" in msg
        assert "---" in msg
        assert "<template>\n# {{name}}\n## Goal\n{{ }}\n</template>" in msg

    def test_format_without_brief(self):
        msg = f"@{SAMPLE_TEMPLATE_NAME}\n\n---\n\n<template>\n{SAMPLE_TEMPLATE}\n</template>"
        assert msg.startswith(f"@{SAMPLE_TEMPLATE_NAME}\n\n---")
        assert "<template>" in msg

    def test_full_roundtrip_through_build_messages(self):
        """Compose a template message, pass through build_messages, verify integrity."""
        original_template = "# Plan for {{name}}\n\n## Features\n- {{ }}\n- {{ }}\n\n## Timeline\n{{ }}"
        msg = _compose_template_message(
            template_name="Feature plan",
            user_brief="Build a CRM",
            template_content=original_template,
        )
        messages = build_messages(user_message=msg)

        content = messages[0].content if isinstance(messages[0].content, str) else messages[0].content[0]["text"]

        # Every part of the original template must survive
        assert "{{name}}" in content
        assert "## Features" in content
        assert "## Timeline" in content
        assert "Build a CRM" in content
        assert "@Feature plan" in content

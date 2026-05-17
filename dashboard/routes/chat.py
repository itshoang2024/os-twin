"""
OpenCode-backed chat endpoint for connectors.

Flow:
  1. Connector sends POST /api/chat with user message + conversation_id
  2. Backend gets/creates an OpenCode session for that conversation
  3. Sends user message to the session (with ostwin system prompt)
  4. OpenCode executes ostwin_* native tools internally
  5. Backend reads back assistant text + tool call results
  6. Extracts ToolAction entries from completed tool calls
  7. Returns clean text + actions

OpenCode handles tool execution natively — no text-based parsing loop needed.
Custom tools are defined in .opencode/tools/ and auto-discovered by OpenCode.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

SYSTEM_PROMPT = """\
You are OS Twin, an autonomous AI assistant that manages software projects \
through the Ostwin multi-agent war-room orchestrator.

You have native tools under the ostwin_* namespace. Use them to take actions:

- ostwin_list_plans — List all plans with status and completion %
- ostwin_get_plan_status — Get detailed plan status (args: plan_id)
- ostwin_create_plan — Create a new plan from an idea (args: idea, working_dir?)
- ostwin_refine_plan — Refine an existing plan (args: plan_id, instruction)
- ostwin_launch_plan — Launch a plan into war-rooms (args: plan_id)
- ostwin_resume_plan — Resume a failed/stopped plan (args: plan_id)
- ostwin_get_war_room_status — Get status of all war-rooms
- ostwin_get_logs — Read war-room channel messages (args: room_id, limit?)
- ostwin_get_health — Check system health
- ostwin_search_skills — Search ClawHub marketplace (args: query)
- ostwin_get_plan_assets — List plan assets (args: plan_id)
- ostwin_get_memories — List plan memories (args: plan_id)

ROUTING (read-only / safe — call freely when the user asks):
- STATUS/PROGRESS queries → ostwin_list_plans or ostwin_get_war_room_status
- LOGS/MESSAGES from agents → ostwin_get_logs
- SYSTEM HEALTH → ostwin_get_health
- FIND/SEARCH skills → ostwin_search_skills
- ASSETS/ARTIFACTS/FILES → ostwin_get_plan_assets
- MEMORIES/KNOWLEDGE → ostwin_get_memories
- MODIFY/REFINE an existing plan → ostwin_refine_plan
- RESUME a failed plan the user explicitly names → ostwin_resume_plan

WRITE TOOLS (ostwin_create_plan, ostwin_launch_plan) — STRICT INTENT GATES:

ostwin_create_plan — ONLY call when the user EXPLICITLY asks to create/start a plan.
Explicit triggers (verbatim or very close): "create a plan", "make me a plan",
"start a plan for…", "/plan", "build this for me", "go ahead and plan it",
"yes, create the plan".
- A product idea, brainstorm, or feature description on its own is NOT a trigger.
  Example: "I want to make an interactive blog about X, here are some assets" is
  a discussion opener — reply conversationally, ask clarifying questions, and
  WAIT for the user to say "create the plan" before calling the tool.
- Attached files / images are NOT a trigger by themselves.
- If intent is ambiguous, ASK: "Want me to turn this into a plan, or keep
  discussing first?"  Do not call the tool to "be helpful."

ostwin_launch_plan — ONLY call when the user EXPLICITLY asks to launch.
Explicit triggers: "launch the plan", "launch plan <id>", "start it", "kick it
off", "/launch", "yes, launch it".
- NEVER chain create→launch in the same turn. After ostwin_create_plan succeeds,
  STOP, summarise the plan, and ask "Want me to launch it?" — wait for the user.
- NEVER call ostwin_launch_plan because the user's earlier message described
  something they want built; description ≠ launch permission.

GENERAL:
- Be concise (1-3 paragraphs). Present tool results clearly.
- For status questions, ALWAYS use tools — don't guess from context.
- One write-tool call per turn maximum. Never chain write tools.

HARD CONSTRAINTS:
- You have ONLY the ostwin_* tools listed above, plus bash for `!` command injections in slash command templates.
- You have NO file read, write, edit, or scaffolding tools.
- NEVER write files, NEVER create folders, NEVER run arbitrary shell commands. The dashboard does all persistence.
- bash is ONLY for executing `!` injections from command templates — do NOT use it to write files or scaffold projects.
- If an ostwin_* tool errors, surface the error to the user verbatim and stop — DO NOT try to "create the plan another way" by writing PLAN.md locally or invoking npx/create-next-app. There is no fallback path.
"""


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    user_id: str = "unknown"
    platform: str = "unknown"
    working_dir: str | None = None
    attachments: list[dict] | None = None
    images: list[dict] | None = None
    referenced_message_content: str | None = None


class CommandRequest(BaseModel):
    command: str
    arguments: str = ""
    conversation_id: str | None = None
    user_id: str = "unknown"
    platform: str = "unknown"
    agent: str | None = "ostwin"


class ToolAction(BaseModel):
    type: str
    plan_id: str | None = None
    room_id: str | None = None


class ChatResponse(BaseModel):
    text: str
    conversation_id: str
    actions: list[ToolAction] | None = None


# ── Tool-call → action mapping ────────────────────────────────────────────

# Maps ostwin tool names to the ToolAction.type they produce
_TOOL_ACTION_MAP: dict[str, str] = {
    "ostwin_create_plan": "plan_created",
    "ostwin_launch_plan": "plan_launched",
    "ostwin_resume_plan": "plan_resumed",
}


def _extract_actions_from_tool_parts(tool_parts: list[dict]) -> list[ToolAction]:
    """Convert completed ostwin tool calls into ToolAction entries.

    Looks for tools in _TOOL_ACTION_MAP that finished successfully
    and extracts plan_id from their output.
    """
    actions: list[ToolAction] = []
    for part in tool_parts:
        tool_name = part.get("tool", "")
        action_type = _TOOL_ACTION_MAP.get(tool_name)
        if not action_type:
            continue
        if part.get("status") != "completed":
            continue
        output = part.get("output", "")
        plan_id = _extract_plan_id(tool_name, output)
        if plan_id:
            actions.append(ToolAction(type=action_type, plan_id=plan_id))
    return actions


def _extract_plan_id(tool_name: str, output: str) -> str | None:
    """Extract plan_id from a tool's output string.

    Output may be plain JSON or a JSON string nested inside text.
    """
    if not output:
        return None
    # Try direct JSON parse
    try:
        data = json.loads(output)
        pid = data.get("plan_id")
        if pid:
            return str(pid)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try finding JSON blob in text
    import re
    match = re.search(r'\{[^{}]*"plan_id"\s*:\s*"([^"]+)"[^{}]*\}', output)
    if match:
        return match.group(1)
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, user: dict = Depends(get_current_user)):
    from dashboard.master_agent import (
        _opencode_chat,
        _session_registry,
        read_session_tool_parts,
    )

    conv_id = request.conversation_id or f"{request.platform}:{request.user_id}"
    session_id = await _session_registry.get_or_create(conv_id)

    # Build user message with context
    user_text = request.message
    if request.referenced_message_content:
        user_text = f'[User is replying to: "{request.referenced_message_content}"]\n\n{user_text}'
    if request.attachments:
        file_list = "\n".join(
            f"  - {a.get('name', 'file')} ({a.get('contentType', 'unknown')})"
            for a in request.attachments
        )
        user_text += f"\n\nAttached files:\n{file_list}"

    # Build parts: image file parts first, then text.
    # OpenCode's FilePartInputParam requires {type, mime, url} at the top level.
    parts: list[dict] = []
    if request.images:
        for img in request.images:
            url = img.get("url", "")
            if not url:
                continue
            part: dict = {
                "type": "file",
                "mime": img.get("contentType") or img.get("mime") or "image/png",
                "url": url,
            }
            name = img.get("name") or img.get("filename")
            if name:
                part["filename"] = name
            parts.append(part)
    parts.append({"type": "text", "text": user_text})

    try:
        raw_text = await _opencode_chat(
            session_id,
            parts,
            system=SYSTEM_PROMPT,
            conversation_id=conv_id,
        )
    except Exception as e:
        logger.error("[CHAT] OpenCode chat failed: %s", e)
        raise HTTPException(status_code=502, detail=f"OpenCode error: {e}")

    # Extract ToolAction entries from completed ostwin tool calls
    actions: list[ToolAction] = []
    try:
        tool_parts = await read_session_tool_parts(session_id)
        actions = _extract_actions_from_tool_parts(tool_parts)
    except Exception as e:
        logger.warning("[CHAT] Failed to read tool parts for actions: %s", e)

    return ChatResponse(
        text=raw_text or "No response from AI.",
        conversation_id=conv_id,
        actions=actions or None,
    )


@router.post("/api/chat/command", response_model=ChatResponse)
async def chat_command_endpoint(request: CommandRequest, user: dict = Depends(get_current_user)):
    """Run a connector slash command through the OpenCode session.

    The OpenCode server resolves the command name against
    ``.opencode/commands/<name>.md``, substitutes ``$ARGUMENTS``, and runs
    the rendered prompt through the configured agent — so the conversation
    history reflects a real command invocation rather than a fabricated
    user message.
    """
    from dashboard.master_agent import (
        _opencode_command,
        _session_registry,
        read_session_tool_parts,
    )

    conv_id = request.conversation_id or f"{request.platform}:{request.user_id}"
    session_id = await _session_registry.get_or_create(conv_id)

    try:
        raw_text = await _opencode_command(
            session_id,
            request.command,
            request.arguments,
            conversation_id=conv_id,
            agent=request.agent,
        )
    except Exception as e:
        logger.error("[CHAT] OpenCode command failed: %s", e)
        raise HTTPException(status_code=502, detail=f"OpenCode error: {e}")

    actions: list[ToolAction] = []
    try:
        tool_parts = await read_session_tool_parts(session_id)
        actions = _extract_actions_from_tool_parts(tool_parts)
    except Exception as e:
        logger.warning("[CHAT] Failed to read tool parts for actions: %s", e)

    return ChatResponse(
        text=raw_text or "No response from AI.",
        conversation_id=conv_id,
        actions=actions or None,
    )


@router.delete("/api/chat/{conversation_id}")
async def delete_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    from dashboard.master_agent import end_conversation

    await end_conversation(conversation_id)
    return {"status": "deleted", "conversation_id": conversation_id}

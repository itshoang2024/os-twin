#!/usr/bin/env python3
"""
ostwin-server.py — MCP server for OS Twin slash commands.

Exposes the same actions the bot's slash commands used to invoke directly
(/draft, /startplan, /edit, /viewplan, /launch, /resume, /logs, ...) as
native MCP tools so OpenCode can call them deterministically instead of
hoping the model emits a ```tool``` JSON block.

All tools proxy to the dashboard REST API (http://127.0.0.1:3366/api/...)
so the same handler logic in dashboard/routes/chat.py is reused — plans
end up in the correct folder, saved to the database, etc.

Transport: stdio (invoked via opencode.json)

Env:
    OSTWIN_API_KEY        Required. Sent as X-API-Key.
    OSTWIN_DASHBOARD_URL  Optional. Defaults to http://127.0.0.1:3366
"""

import json
import os
import pathlib
from typing import Annotated, Optional

original_is_file = pathlib.Path.is_file
def safe_is_file(self):
    try:
        return original_is_file(self)
    except PermissionError:
        return False
pathlib.Path.is_file = safe_is_file

import httpx
from pydantic import Field
from mcp.server.fastmcp import FastMCP


def _api_base() -> str:
    base = os.environ.get("OSTWIN_DASHBOARD_URL", "").rstrip("/")
    if base:
        return base
    port = os.environ.get("DASHBOARD_PORT", "3366")
    return f"http://127.0.0.1:{port}"


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    key = os.environ.get("OSTWIN_API_KEY", "")
    if key:
        h["X-API-Key"] = key
    return h


_http_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            base_url=_api_base(),
            headers=_headers(),
            timeout=30,
        )
    return _http_client


def _get(path: str, params: Optional[dict] = None) -> dict:
    try:
        r = _get_client().get(path, params=params)
        if r.status_code >= 400:
            return {"error": f"API {r.status_code}: {r.text[:300]}"}
        return r.json()
    except Exception as e:
        return {"error": f"Request failed: {e}"}


def _post(path: str, body: Optional[dict] = None) -> dict:
    try:
        r = _get_client().post(path, json=body or {}, timeout=90)
        if r.status_code >= 400:
            return {"error": f"API {r.status_code}: {r.text[:300]}"}
        return r.json()
    except Exception as e:
        return {"error": f"Request failed: {e}"}


mcp = FastMCP("ostwin", log_level="CRITICAL")


@mcp.tool()
def list_plans() -> str:
    """List every plan with id, title and status. No arguments."""
    data = _get("/api/plans")
    if "error" in data:
        return json.dumps(data)
    plans = data.get("plans", [])
    summary = [
        {"plan_id": p.get("plan_id"), "title": p.get("title"), "status": p.get("status")}
        for p in plans
    ]
    return json.dumps({"plans": summary, "count": data.get("count", len(summary))})


@mcp.tool()
def get_plan_status(
    plan_id: Annotated[str, Field(description="Plan identifier, e.g. pt-879068143dba")],
) -> str:
    """Get detailed status of a single plan including its epics."""
    if not plan_id:
        return json.dumps({"error": "plan_id is required"})
    data = _get(f"/api/plans/{plan_id}")
    if "error" in data:
        return json.dumps(data)
    plan = data.get("plan", {})
    epics = data.get("epics", [])
    return json.dumps({
        "plan_id": plan_id,
        "title": plan.get("title"),
        "status": plan.get("status"),
        "epic_count": len(epics),
        "epics": [
            {"epic_ref": e.get("epic_ref"), "title": e.get("title"), "status": e.get("status")}
            for e in epics
        ],
    })


@mcp.tool()
def create_plan(
    idea: Annotated[str, Field(description="Plain-language description of what to build")],
    working_dir: Annotated[
        Optional[str],
        Field(description="Optional absolute path the plan will operate on"),
    ] = None,
) -> str:
    """Create a new plan from an idea, draft it via the AI, and save it.

    Wraps the three-step /draft flow:
      1. POST /api/plans/create  → reserves plan_id, folder, db row
      2. POST /api/plans/refine  → AI drafts the plan content
      3. POST /api/plans/{id}/save → persists the drafted content

    Returns {"plan_id", "title", "status"} on success.
    """
    if not idea:
        return json.dumps({"error": "idea is required"})

    body: dict = {"title": idea, "content": ""}
    if working_dir:
        body["working_dir"] = working_dir
    created = _post("/api/plans/create", body)
    if "error" in created:
        return json.dumps(created)

    plan_id = created.get("plan_id", "")
    if not plan_id:
        return json.dumps({"error": "Dashboard did not return a plan_id", "raw": created})

    refined = _post("/api/plans/refine", {
        "plan_id": plan_id,
        "message": f"Draft a new plan for: {idea}",
    })
    plan_text = refined.get("plan", refined.get("full_response", "")) if isinstance(refined, dict) else ""

    if plan_text:
        _post(f"/api/plans/{plan_id}/save", {
            "content": plan_text,
            "change_source": "ai_create",
        })

    return json.dumps({
        "plan_id": plan_id,
        "title": idea,
        "status": "created",
        "drafted": bool(plan_text),
    })


@mcp.tool()
def refine_plan(
    plan_id: Annotated[str, Field(description="Plan identifier to modify")],
    instruction: Annotated[str, Field(description="Instruction describing the edit, e.g. 'Add acceptance criteria'")],
) -> str:
    """Refine an existing plan with an instruction; saves the new content."""
    if not plan_id:
        return json.dumps({"error": "plan_id is required"})
    if not instruction:
        return json.dumps({"error": "instruction is required"})

    data = _post("/api/plans/refine", {"plan_id": plan_id, "message": instruction})
    if "error" in data:
        return json.dumps(data)

    refined = data.get("plan", data.get("full_response", ""))
    if refined:
        _post(f"/api/plans/{plan_id}/save", {
            "content": refined,
            "change_source": "ai_refine",
        })

    return json.dumps({
        "plan_id": plan_id,
        "status": "refined",
        "explanation": data.get("explanation", ""),
    })


@mcp.tool()
def launch_plan(
    plan_id: Annotated[str, Field(description="Plan identifier to launch into war-rooms")],
) -> str:
    """Launch a saved plan into the war-room orchestrator.

    Fetches the plan content, then POSTs to /api/run to spin up rooms.
    """
    if not plan_id:
        return json.dumps({"error": "plan_id is required"})

    plan_data = _get(f"/api/plans/{plan_id}")
    if "error" in plan_data:
        return json.dumps(plan_data)
    plan_content = plan_data.get("plan", {}).get("content", "")
    if not plan_content:
        return json.dumps({"error": f"Plan '{plan_id}' has no content"})

    result = _post("/api/run", {"plan_id": plan_id, "plan": plan_content})
    if "error" in result:
        return json.dumps(result)
    return json.dumps({
        "plan_id": plan_id,
        "status": "launched",
        "rooms": result.get("rooms", []),
    })


@mcp.tool()
def resume_plan(
    plan_id: Annotated[str, Field(description="Plan identifier to resume")],
) -> str:
    """Resume a stopped/failed plan by flipping its status to 'running'."""
    if not plan_id:
        return json.dumps({"error": "plan_id is required"})
    result = _post(f"/api/plans/{plan_id}/status", {"status": "running"})
    if "error" in result:
        return json.dumps(result)
    return json.dumps({"plan_id": plan_id, "status": "resuming"})


@mcp.tool()
def get_war_room_status() -> str:
    """Get aggregate stats for all war-rooms. No arguments."""
    data = _get("/api/stats")
    return json.dumps(data)


@mcp.tool()
def get_logs(
    plan_id: Annotated[str, Field(description="Plan identifier")],
    room_id: Annotated[str, Field(description="War-room identifier inside the plan")],
    limit: Annotated[Optional[int], Field(description="Max messages to return (default 10)", ge=1)] = 10,
) -> str:
    """Read the most recent messages from a war-room channel."""
    if not plan_id:
        return json.dumps({"error": "plan_id is required"})
    if not room_id:
        return json.dumps({"error": "room_id is required"})

    data = _get(f"/api/plans/{plan_id}/rooms/{room_id}/channel")
    if "error" in data:
        return json.dumps(data)
    messages = data.get("messages", data)
    if isinstance(messages, list) and limit:
        messages = messages[-limit:]
    return json.dumps({"room_id": room_id, "messages": messages})


@mcp.tool()
def get_health() -> str:
    """Check overall dashboard health. No arguments."""
    data = _get("/api/status")
    healthy = "error" not in data
    return json.dumps({
        "status": "healthy" if healthy else "unhealthy",
        "service": "os-twin-dashboard",
        "manager": data,
    })


@mcp.tool()
def search_skills(
    query: Annotated[str, Field(description="Search term for the ClawHub skill marketplace")],
) -> str:
    """Search the ClawHub marketplace for skills matching `query`."""
    if not query:
        return json.dumps({"error": "query is required"})
    data = _get("/api/skills/search", {"q": query})
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data)
    skills = data if isinstance(data, list) else []
    return json.dumps({"skills": skills[:10], "total": len(skills)})


@mcp.tool()
def get_plan_assets(
    plan_id: Annotated[str, Field(description="Plan identifier")],
) -> str:
    """List assets/artifacts attached to a plan."""
    if not plan_id:
        return json.dumps({"error": "plan_id is required"})
    data = _get(f"/api/plans/{plan_id}/assets")
    if "error" in data:
        return json.dumps(data)
    return json.dumps({"plan_id": plan_id, "assets": data.get("assets", [])})


@mcp.tool()
def get_memories(
    plan_id: Annotated[str, Field(description="Plan identifier")],
) -> str:
    """List memories / knowledge notes attached to a plan (currently a stub)."""
    if not plan_id:
        return json.dumps({"error": "plan_id is required"})
    return json.dumps({"plan_id": plan_id, "memories": []})


if __name__ == "__main__":
    mcp.run(transport="stdio")

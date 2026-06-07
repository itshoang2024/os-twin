#!/usr/bin/env python3
"""
warroom-server.py — MCP server for OS Twin war-room operations.

Provides tools for agents to:
  - Update war-room status
  - List artifacts
  - Report progress

Transport: stdio (invoked via deepagents --mcp-config)
"""

import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone
from typing import Annotated, get_args, Literal

# Monkey patch pathlib to bypass macOS SIP PermissionError on .env files
original_is_file = pathlib.Path.is_file
def safe_is_file(self):
    try:
        return original_is_file(self)
    except PermissionError:
        return False
pathlib.Path.is_file = safe_is_file

from pydantic import Field
from mcp.server.fastmcp import FastMCP

StatusType = Literal[
    "pending",
    "developing",
    "review",
    "optimize",
    "triage",
    "done",
    "failed",
]


def _find_project_root() -> str:
    """Find project root from env vars, falling back to CWD."""
    for var in ("AGENT_OS_ROOT", "AGENT_OS_PROJECT_DIR"):
        val = os.environ.get(var, "")
        if val and os.path.isabs(val) and os.path.isdir(val):
            return val
    return os.getcwd()

AGENT_OS_ROOT: str = _find_project_root()


def _resolve_room_dir(room_dir: str) -> str:
    """Resolve room_dir relative to AGENT_OS_ROOT if not absolute."""
    if os.path.isabs(room_dir):
        return room_dir
    return os.path.join(AGENT_OS_ROOT, room_dir)


mcp = FastMCP("agent-os-warroom", log_level="CRITICAL")


def _atomic_write_text(path: str, text: str) -> None:
    """Atomically replace a small war-room state file."""
    directory = os.path.dirname(path) or "."
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=directory, delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _get_lifecycle(room_dir: str) -> dict | None:
    """Read lifecycle.json and return the parsed JSON dictionary, or None."""
    lc_path = os.path.join(room_dir, "lifecycle.json")
    if not os.path.exists(lc_path):
        return None
    try:
        with open(lc_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


@mcp.tool()
def update_status(
    room_dir: Annotated[str, Field(description="Absolute or relative path to the war-room directory")],
    status: Annotated[StatusType, Field(description="New status matching a canonical state from the room's lifecycle.json (e.g. developing, review, optimize, triage, done, failed).")],
) -> str:
    """Update the war-room status file.

    Validates status against the room's lifecycle.json if present.
    Returns a confirmation string "status:{status}".
    """
    room_dir = _resolve_room_dir(room_dir)
    os.makedirs(room_dir, exist_ok=True)

    # Validate status against lifecycle.json if present
    lc = _get_lifecycle(room_dir)
    if lc is not None:
        valid_states = lc.get("states", {})
        if status not in valid_states:
            error_msg = f"Error: Invalid status '{status}'.\n\nValid statuses in lifecycle.json are:\n"
            for s_name, s_info in valid_states.items():
                role = s_info.get("role", "none")
                s_type = s_info.get("type", "unknown")
                error_msg += f"- {s_name} (assigned role: {role}, type: {s_type})\n"
            raise ValueError(error_msg)

    status_file = os.path.join(room_dir, "status")

    # Read old status for audit
    old_status = "unknown"
    if os.path.exists(status_file):
        with open(status_file) as f:
            old_status = f.read().strip()

    # Write new status
    _atomic_write_text(status_file, status)

    # Write state_changed_at (epoch seconds)
    epoch = int(datetime.now(timezone.utc).timestamp())
    _atomic_write_text(os.path.join(room_dir, "state_changed_at"), str(epoch))

    # Append audit log
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(os.path.join(room_dir, "audit.log"), "a") as f:
        f.write(f"{ts} STATUS {old_status} -> {status}\n")

    return f"status:{status}"


@mcp.tool()
def list_artifacts(
    room_dir: Annotated[str, Field(description="Absolute or relative path to the war-room directory")],
) -> str:
    """List all artifacts produced in this war-room.

    Walks {room_dir}/artifacts/ and returns a JSON array of
    {path, size_bytes, modified} objects sorted by path.
    Returns an empty JSON array ("[]") if the artifacts directory
    does not exist.
    """
    room_dir = _resolve_room_dir(room_dir)
    artifacts_dir = os.path.join(room_dir, "artifacts")
    if not os.path.exists(artifacts_dir):
        return "[]"

    files = []
    for root, _dirs, fnames in os.walk(artifacts_dir):
        for fname in fnames:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, artifacts_dir)
            stat = os.stat(full_path)
            files.append({
                "path": rel_path,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    return json.dumps(sorted(files, key=lambda x: x["path"]))


@mcp.tool()
def report_progress(
    room_dir: Annotated[str, Field(description="Absolute or relative path to the war-room directory")],
    percent: Annotated[int, Field(description="Completion percentage (0–100)", ge=0, le=100)],
    message: Annotated[str, Field(description="Human-readable progress message")],
) -> str:
    """Write a progress snapshot to {room_dir}/progress.json.

    Clamps percent to [0, 100] even if the schema constraint is bypassed.
    Returns the written progress object as a JSON string.
    """
    room_dir = _resolve_room_dir(room_dir)
    os.makedirs(room_dir, exist_ok=True)
    progress_file = os.path.join(room_dir, "progress.json")

    progress = {
        "percent": max(0, min(100, percent)),
        "message": message,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(progress_file, "w") as f:
        json.dump(progress, f, indent=2)

    return json.dumps(progress)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")

"""Tests for ``dashboard.api_utils.read_room``.

Covers the basic shape plus two recently-added fields the bot/OpenCode
slash-command clients rely on:

* ``plan_id``  — surfaced from the room's ``config.json``.
* ``epic_ref`` — alias of ``task_ref`` so callers spelling it either way
  pick up the same value.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_dashboard_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_dashboard_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)
if _dashboard_dir not in sys.path:
    sys.path.insert(0, _dashboard_dir)

from dashboard.api_utils import read_room


def _make_room(tmp: Path, *, room_id: str = "room-007", plan_id: str | None = "plan-abc",
               task_ref: str = "EPIC-007", status: str = "developing") -> Path:
    room = tmp / room_id
    room.mkdir(parents=True)
    (room / "status").write_text(status)
    (room / "task-ref").write_text(task_ref)
    if plan_id is not None:
        (room / "config.json").write_text(json.dumps({"plan_id": plan_id}))
    return room


def test_read_room_returns_plan_id_and_epic_ref_alias(tmp_path):
    """OpenCode `/logs` and `/status` need both fields exposed."""
    room = _make_room(tmp_path)
    data = read_room(room)

    assert data["room_id"] == "room-007"
    assert data["task_ref"] == "EPIC-007"
    assert data["epic_ref"] == "EPIC-007", "epic_ref must alias task_ref"
    assert data["plan_id"] == "plan-abc"
    assert data["status"] == "developing"


def test_read_room_plan_id_is_none_when_no_config(tmp_path):
    room = _make_room(tmp_path, plan_id=None)
    data = read_room(room)
    assert data["plan_id"] is None
    assert data["epic_ref"] == "EPIC-007"


def test_read_room_plan_id_is_none_for_malformed_config(tmp_path):
    room = _make_room(tmp_path, plan_id=None)
    (room / "config.json").write_text("{not json")
    data = read_room(room)
    assert data["plan_id"] is None


def test_read_room_extended_metadata(tmp_path):
    """``include_metadata=True`` should still surface lifecycle/roles/etc.

    Regression guard: the new ``plan_id`` plumbing must coexist with the
    existing extended-metadata block.
    """
    room = _make_room(tmp_path)
    (room / "lifecycle.json").write_text(json.dumps({
        "initial_state": "pending",
        "states": {"developing": {}, "review": {}},
    }))
    (room / "engineer_001.json").write_text(json.dumps({
        "role": "engineer", "instance_id": "001",
    }))
    artifacts = room / "artifacts"
    artifacts.mkdir()
    (artifacts / "out.txt").write_text("hello")

    data = read_room(room, include_metadata=True)

    assert data["plan_id"] == "plan-abc"
    assert data["epic_ref"] == "EPIC-007"
    assert data["lifecycle"]["initial_state"] == "pending"
    assert "developing" in data["lifecycle"]["states"]
    assert len(data["roles"]) == 1
    assert data["roles"][0]["role"] == "engineer"
    assert "out.txt" in data["artifact_files"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))

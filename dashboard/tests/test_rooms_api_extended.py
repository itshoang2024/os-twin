"""Integration smoke test for GET /api/rooms/{room_id}/state.

Skips automatically when the developer hasn't seeded a ``room-003``
fixture on disk — the unit-level coverage for the underlying ``read_room``
function lives in ``test_room_state_backend.py``.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

_dashboard_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_dashboard_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)
if _dashboard_dir not in sys.path:
    sys.path.insert(0, _dashboard_dir)

from dashboard.api import app
from dashboard.api_utils import WARROOMS_DIR

client = TestClient(app)


def test_get_room_state_extended():
    if not (WARROOMS_DIR / "room-003").exists():
        pytest.skip(f"fixture room-003 missing under {WARROOMS_DIR}")

    response = client.get("/api/rooms/room-003/state")
    assert response.status_code == 200
    data = response.json()

    assert data["room_id"] == "room-003"
    # read_room now surfaces these fields for slash-command consumers.
    assert "plan_id" in data
    assert "epic_ref" in data
    # Extended metadata (opt-in inside the endpoint)
    assert "lifecycle" in data
    assert "roles" in data
    assert "artifact_files" in data
    assert "audit_tail" in data
    assert "initial_state" in data["lifecycle"]
    assert "states" in data["lifecycle"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

"""
Tests for DELETE /api/plans/{plan_id} — full plan deletion.

Covers:
  - Successful delete removes .md, .meta.json, .roles.json, assets dir
  - Working dir .agents/ and .war-rooms/ are cleaned up
  - 404 when plan doesn't exist
  - 400 for invalid plan_id format
  - zvec index is cleaned via store.delete_plan()
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from dashboard.api import app


@pytest.fixture
def client(monkeypatch):
    """TestClient with auth overridden.

    ``dashboard.auth`` now reads ``OSTWIN_API_KEY`` from ``os.environ`` at
    request time (see ``_get_api_key``), so we override the env var rather
    than a module-level constant.
    """
    monkeypatch.setenv("OSTWIN_API_KEY", "test-key")
    return TestClient(app)


AUTH = {"X-API-Key": "test-key"}


@pytest.fixture
def plan_dirs(tmp_path, monkeypatch):
    """Set up isolated plan directories for testing."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    monkeypatch.setattr("dashboard.routes.plans.PLANS_DIR", plans_dir)
    monkeypatch.setattr("dashboard.routes.plans.GLOBAL_PLANS_DIR", plans_dir)
    return plans_dir, tmp_path


def _create_test_plan(plans_dir: Path, plan_id: str, working_dir: str | None = None):
    """Helper to create a full test plan on disk."""
    (plans_dir / f"{plan_id}.md").write_text(f"# Plan: Test Plan\n\nGoal\n")
    meta = {
        "plan_id": plan_id,
        "title": "Test Plan",
        "status": "draft",
        "created_at": "2025-01-01T00:00:00Z",
        "assets": [],
        "epic_assets": {},
    }
    if working_dir:
        meta["working_dir"] = working_dir
    (plans_dir / f"{plan_id}.meta.json").write_text(json.dumps(meta, indent=2))
    (plans_dir / f"{plan_id}.roles.json").write_text(json.dumps({}, indent=2))
    assets_dir = plans_dir / "assets" / plan_id
    assets_dir.mkdir(parents=True)
    (assets_dir / "test-asset.txt").write_text("test")
    return meta


def test_delete_plan_removes_all_global_files(client, plan_dirs):
    """DELETE should remove .md, .meta.json, .roles.json, and assets dir."""
    plans_dir, tmp_path = plan_dirs
    plan_id = "abcdef012345"
    _create_test_plan(plans_dir, plan_id)

    mock_store = MagicMock()
    mock_store.delete_plan.return_value = True

    with patch("dashboard.routes.plans.global_state") as mock_gs:
        mock_gs.store = mock_store
        resp = client.delete(f"/api/plans/{plan_id}", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deleted"
    assert data["plan_id"] == plan_id

    # All global files should be gone
    assert not (plans_dir / f"{plan_id}.md").exists()
    assert not (plans_dir / f"{plan_id}.meta.json").exists()
    assert not (plans_dir / f"{plan_id}.roles.json").exists()
    assert not (plans_dir / "assets" / plan_id).exists()

    # zvec delete should have been called
    mock_store.delete_plan.assert_called_once_with(plan_id)


def test_delete_plan_cleans_working_dir(client, plan_dirs):
    """DELETE should remove .agents/ and .war-rooms/ from the working directory."""
    plans_dir, tmp_path = plan_dirs
    plan_id = "abcdef012345"

    # Create a working directory with .agents and .war-rooms
    working_dir = tmp_path / "projects" / "my-project"
    working_dir.mkdir(parents=True)
    agents_dir = working_dir / ".agents"
    agents_dir.mkdir()
    (agents_dir / "config.json").write_text("{}")
    warrooms_dir = working_dir / ".war-rooms"
    warrooms_dir.mkdir()
    (warrooms_dir / "room-01").mkdir()

    _create_test_plan(plans_dir, plan_id, working_dir=str(working_dir))

    with patch("dashboard.routes.plans.global_state") as mock_gs:
        mock_gs.store = None
        resp = client.delete(f"/api/plans/{plan_id}", headers=AUTH)

    assert resp.status_code == 200
    data = resp.json()

    # Working dir itself should still exist
    assert working_dir.exists()
    # But .agents and .war-rooms should be gone
    assert not agents_dir.exists()
    assert not warrooms_dir.exists()
    # cleaned_paths should include these dirs
    assert str(agents_dir) in data["cleaned_paths"]
    assert str(warrooms_dir) in data["cleaned_paths"]


def test_delete_plan_404_when_not_found(client, plan_dirs):
    """DELETE should return 404 when the plan doesn't exist."""
    resp = client.delete("/api/plans/abcdef012345", headers=AUTH)
    assert resp.status_code == 404


def test_delete_plan_400_for_invalid_id(client, plan_dirs):
    """DELETE should reject plan IDs that don't match the expected hex format."""
    # Too short
    resp = client.delete("/api/plans/abcdef", headers=AUTH)
    assert resp.status_code == 400

    # Too long
    resp = client.delete("/api/plans/abcdef0123456789", headers=AUTH)
    assert resp.status_code == 400

    # Non-hex
    resp = client.delete("/api/plans/xxxxxxxxxxxx", headers=AUTH)
    assert resp.status_code == 400


def test_delete_plan_no_working_dir_in_meta(client, plan_dirs):
    """DELETE should succeed even when meta.json has no working_dir."""
    plans_dir, tmp_path = plan_dirs
    plan_id = "abcdef012345"
    _create_test_plan(plans_dir, plan_id)  # no working_dir

    with patch("dashboard.routes.plans.global_state") as mock_gs:
        mock_gs.store = None
        resp = client.delete(f"/api/plans/{plan_id}", headers=AUTH)

    assert resp.status_code == 200
    assert not (plans_dir / f"{plan_id}.md").exists()

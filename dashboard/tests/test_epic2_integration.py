import pytest
from fastapi.testclient import TestClient
from dashboard.api import app
from dashboard.auth import get_current_user
from pathlib import Path
import json

def mock_get_current_user():
    return {"sub": "test-user"}

app.dependency_overrides[get_current_user] = mock_get_current_user

client = TestClient(app)

@pytest.fixture
def plan_setup(tmp_path, monkeypatch):
    # Mock PLANS_DIR to use tmp_path
    monkeypatch.setattr("dashboard.routes.plans.PLANS_DIR", tmp_path)
    monkeypatch.setattr("dashboard.routes.plans.GLOBAL_PLANS_DIR", tmp_path)
    plan_id = "test-plan"
    plan_file = tmp_path / f"{plan_id}.md"
    plan_file.write_text(
        "# Plan: Test Plan\n\n"
        "### EPIC-001 — First Epic\n\n"
        "### EPIC-002 — Second Epic\n\n"
        "## Assets\n"
    )
    assets_dir = tmp_path / "assets" / plan_id
    assets_dir.mkdir(parents=True)
    return plan_id, tmp_path, assets_dir

def test_upload_and_bind(plan_setup):
    plan_id, tmp_path, assets_dir = plan_setup
    
    # 1. Upload with epic_ref
    files = [("files", ("test.txt", b"hello world", "text/plain"))]
    data = {"epic_ref": "EPIC-001", "asset_type": "reference-doc", "tags": "test,initial"}
    
    response = client.post(f"/api/plans/{plan_id}/assets", files=files, data=data)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["count"] == 1
    asset = res_data["assets"][0]
    assert "EPIC-001" in asset["bound_epics"]
    assert asset["asset_type"] == "reference-doc"
    assert "test" in asset["tags"]
    
    filename = asset["filename"]
    
    # 2. Bind existing asset to another epic
    response = client.post(f"/api/plans/{plan_id}/assets/{filename}/bind", json={"epic_ref": "EPIC-002"})
    assert response.status_code == 200
    assert "EPIC-002" in response.json()["asset"]["bound_epics"]
    
    # 3. List assets for EPIC-001
    response = client.get(f"/api/plans/{plan_id}/epics/EPIC-001/assets")
    assert response.status_code == 200
    res_data = response.json()
    found = any(a["filename"] == filename for a in res_data["assets"])
    assert found
    
    # 4. Update metadata
    response = client.patch(f"/api/plans/{plan_id}/assets/{filename}", json={
        "asset_type": "api-spec",
        "description": "New description"
    })
    assert response.status_code == 200
    assert response.json()["asset"]["asset_type"] == "api-spec"
    assert response.json()["asset"]["description"] == "New description"

    # 5. Path traversal protection
    # Test plan_id invalid chars (should match route but fail validation)
    response = client.get(f"/api/plans/invalid!id/assets")
    assert response.status_code == 400
    assert "Invalid plan_id" in response.json()["detail"]

    # Test filename invalid chars
    response = client.get(f"/api/plans/{plan_id}/assets/invalid!file/download")
    assert response.status_code == 400
    assert "Invalid filename" in response.json()["detail"]

def test_unbind(plan_setup):
    plan_id, tmp_path, assets_dir = plan_setup
    files = [("files", ("test.txt", b"hello world", "text/plain"))]
    data = {"epic_ref": "EPIC-001"}
    response = client.post(f"/api/plans/{plan_id}/assets", files=files, data=data)
    filename = response.json()["assets"][0]["filename"]
    
    response = client.delete(f"/api/plans/{plan_id}/assets/{filename}/bind/EPIC-001")
    assert response.status_code == 200
    assert "EPIC-001" not in response.json()["asset"]["bound_epics"]

def test_list_epic_combined(plan_setup):
    plan_id, tmp_path, assets_dir = plan_setup
    client.post(f"/api/plans/{plan_id}/assets", files=[("files", ("plan.txt", b"plan", "text/plain"))])
    client.post(f"/api/plans/{plan_id}/assets", files=[("files", ("epic.txt", b"epic", "text/plain"))], data={"epic_ref": "EPIC-001"})
    client.post(f"/api/plans/{plan_id}/assets", files=[("files", ("other.txt", b"other", "text/plain"))], data={"epic_ref": "EPIC-002"})
                
    response = client.get(f"/api/plans/{plan_id}/epics/EPIC-001/assets")
    assert response.status_code == 200
    assets = response.json()["assets"]
    filenames = [a["original_name"] for a in assets]
    assert "plan.txt" in filenames
    assert "epic.txt" in filenames
    assert "other.txt" not in filenames

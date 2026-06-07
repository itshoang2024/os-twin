import pytest
from fastapi.testclient import TestClient
import os
import json
from pathlib import Path

# Set up environment for testing
os.environ["OSTWIN_API_KEY"] = "test-key"
# We'll use a temporary directory for roles config
import tempfile
tmp_dir = tempfile.mkdtemp()
os.environ["OSTWIN_PROJECT_DIR"] = tmp_dir
os.environ["OSTWIN_HOME"] = str(Path(tmp_dir) / ".ostwin")

from dashboard.api import app

client = TestClient(app)
headers = {"X-API-Key": "test-key"}

def test_roles_crud():
    # 1. List roles (initially empty or default)
    response = client.get("/api/roles", headers=headers)
    assert response.status_code == 200
    roles = response.json()
    # It might have defaults if registry exists, but in our tmp_dir it should be empty
    
    # 2. Create a role
    new_role_data = {
        "name": "test-engineer",
        "provider": "Claude",
        "version": "claude-3-5-sonnet-20241022",
        "temperature": 0.5,
        "budget_tokens_max": 1000000,
        "max_retries": 3,
        "timeout_seconds": 600,
        "skill_refs": ["web-research"],
        "system_prompt_override": "You are a test engineer."
    }
    response = client.post("/api/roles", json=new_role_data, headers=headers)
    assert response.status_code == 201
    created_role = response.json()
    assert created_role["name"] == "test-engineer"
    assert "id" in created_role
    role_id = created_role["id"]

    # 3. Get roles again
    response = client.get("/api/roles", headers=headers)
    assert response.status_code == 200
    roles = response.json()
    assert any(r["id"] == role_id for r in roles)

    # 4. Update the role
    updated_role_data = new_role_data.copy()
    updated_role_data["temperature"] = 0.8
    response = client.put(f"/api/roles/{role_id}", json=updated_role_data, headers=headers)
    assert response.status_code == 200
    updated_role = response.json()
    assert updated_role["temperature"] == 0.8



    # 6. Delete the role
    response = client.delete(f"/api/roles/{role_id}?force=true", headers=headers)
    assert response.status_code == 204

    # 7. Verify deletion
    response = client.get("/api/roles", headers=headers)
    assert response.status_code == 200
    roles = response.json()
    assert not any(r["id"] == role_id for r in roles)

def test_role_name_uniqueness():
    role_data = {
        "name": "unique-role",
        "provider": "GPT",
        "version": "gpt-4o",
    }
    # Create first time
    client.post("/api/roles", json=role_data, headers=headers)
    
    # Create second time with same name
    response = client.post("/api/roles", json=role_data, headers=headers)
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]

def test_role_dependencies(tmp_path):
    # Setup a synthetic war-room role. Keep this distinct from seeded roles so
    # the test does not imply that "active-role" is an available built-in.
    role_name = "dependency-test-role"
    role_data = {
        "name": role_name,
        "provider": "Gemini",
        "version": "google-vertex/gemini-1.5-pro",
    }
    res = client.post("/api/roles", json=role_data, headers=headers)
    assert res.status_code == 201
    role_id = res.json()["id"]
    
    # Create a mock war-room in our project dir
    warrooms_dir = Path(tmp_dir) / ".war-rooms"
    room_dir = warrooms_dir / "room-dependency-test"
    room_dir.mkdir(parents=True)
    
    config = {
        "assignment": {
            "candidate_roles": [role_name]
        }
    }
    with open(room_dir / "config.json", "w") as f:
        json.dump(config, f)
    
    with open(room_dir / "status", "w") as f:
        f.write("in_progress")
        
    # Check dependencies
    response = client.get(f"/api/roles/{role_id}/dependencies", headers=headers)
    assert response.status_code == 200
    deps = response.json()
    assert len(deps["active_warrooms"]) == 1
    assert deps["active_warrooms"][0]["id"] == "room-dependency-test"
    
    # Try to delete - should fail
    response = client.delete(f"/api/roles/{role_id}", headers=headers)
    assert response.status_code == 409
    assert "actively used" in response.json()["detail"]

if __name__ == "__main__":
    pytest.main([__file__])

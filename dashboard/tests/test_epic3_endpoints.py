import sys
from pathlib import Path
import json

# Add project root to sys.path
sys.path.insert(0, "/Users/paulaan/PycharmProjects/agent-os")

import pytest
from fastapi.testclient import TestClient
from dashboard.api import app
from unittest.mock import patch, MagicMock

client = TestClient(app)

# Mock the get_current_user dependency
def mock_get_current_user():
    return {"user_id": "test-user"}

app.dependency_overrides[MagicMock] = mock_get_current_user # Not exactly right, need to find where get_current_user is from

from dashboard.auth import get_current_user
app.dependency_overrides[get_current_user] = mock_get_current_user

@pytest.fixture
def mock_room_data(tmp_path):
    _plan_id = "test-plan"
    task_ref = "EPIC-003"
    room_dir = tmp_path / ".war-rooms" / "room-003"
    room_dir.mkdir(parents=True)
    (room_dir / "config.json").write_text(json.dumps({
        "roles": {
            "engineer": {
                "default_model": "gpt-4-test",
                "temperature": 0.5
            }
        }
    }))
    (room_dir / "task-ref").write_text(task_ref)
    return room_dir

def test_get_epic_roles():
    plan_id = "plan-001"
    task_ref = "EPIC-003"
    
    with patch("dashboard.routes.plans._resolve_room_dir", return_value=Path("/tmp/room-003")), \
         patch("dashboard.routes.plans.get_plan_roles_config", return_value={"engineer": {}}), \
         patch("dashboard.routes.plans.Path.exists", return_value=True), \
         patch("dashboard.routes.plans.Path.read_text", return_value=json.dumps({"roles": {"engineer": {"temperature": 0.9}}})), \
         patch("dashboard.routes.plans.build_roles_list", return_value=[{"name": "engineer", "temperature": 0.9}]):
        
        response = client.get(f"/api/plans/{plan_id}/epics/{task_ref}/roles")
        assert response.status_code == 200
        data = response.json()
        assert "roles" in data
        assert data["roles"][0]["name"] == "engineer"
        assert data["roles"][0]["temperature"] == 0.9

def test_update_epic_role_config():
    plan_id = "plan-001"
    task_ref = "EPIC-003"
    role_name = "engineer"
    
    with patch("dashboard.routes.plans._resolve_room_dir", return_value=Path("/tmp/room-003")), \
         patch("dashboard.routes.plans.Path.exists", return_value=True), \
         patch("dashboard.routes.plans.Path.read_text", return_value=json.dumps({"roles": {}})), \
         patch("dashboard.routes.plans.Path.write_text") as mock_write:
        
        payload = {
            "default_model": "claude-3-opus",
            "temperature": 0.2,
            "skill_refs": ["new-skill"]
        }
        response = client.put(f"/api/plans/{plan_id}/epics/{task_ref}/roles/{role_name}/config", json=payload)
        
        assert response.status_code == 200
        assert mock_write.called
        written_data = json.loads(mock_write.call_args[0][0])
        assert written_data["roles"][role_name]["default_model"] == "claude-3-opus"
        assert written_data["roles"][role_name]["temperature"] == 0.2
        assert written_data["roles"][role_name]["skill_refs"] == ["new-skill"]

def test_preview_epic_role_prompt():
    plan_id = "plan-001"
    task_ref = "EPIC-003"
    role_name = "engineer"
    
    with patch("dashboard.epic_manager.EpicSkillsManager.generate_system_prompt", return_value="System Prompt Content"):
        response = client.get(f"/api/plans/{plan_id}/epics/{task_ref}/roles/{role_name}/preview")
        assert response.status_code == 200
        assert response.json()["prompt"] == "System Prompt Content"

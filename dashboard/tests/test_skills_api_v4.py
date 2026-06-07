import pytest
from pathlib import Path
import os
import tempfile

# Set API key BEFORE importing the app
TEST_API_KEY = "test-key"
os.environ["OSTWIN_API_KEY"] = TEST_API_KEY

from fastapi.testclient import TestClient
from dashboard.api import app
from dashboard.api_utils import SKILLS_DIRS, save_skill_md

client = TestClient(app)

HEADERS = {"X-API-Key": TEST_API_KEY, "X-User": "testuser"}

@pytest.fixture
def temp_skills_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        
        # Patch SKILLS_DIRS for testing
        old_skills_dirs = SKILLS_DIRS.copy()
        SKILLS_DIRS.clear()
        SKILLS_DIRS.append(skills_dir)
        
        yield skills_dir
        
        SKILLS_DIRS.clear()
        SKILLS_DIRS.extend(old_skills_dirs)

def test_create_skill(temp_skills_dir):
    payload = {
        "name": "Test Skill",
        "description": "A test skill for API testing.",
        "category": "implementation",
        "applicable_roles": ["engineer"],
        "tags": ["test"],
        "content": "This is the skill content with at least fifty characters to pass validation.",
        "is_draft": False
    }
    response = client.post("/api/skills", json=payload, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Skill"
    assert data["version"] == "1.0.0"
    
    # Verify file exists
    skill_dir = temp_skills_dir / "test-skill"
    assert skill_dir.exists()
    assert (skill_dir / "SKILL.md").exists()

def test_update_skill_with_versioning(temp_skills_dir):
    # 1. Create initial skill
    payload = {
        "name": "Versioned Skill",
        "description": "Initial description.",
        "category": "implementation",
        "applicable_roles": ["engineer"],
        "content": "Initial content with at least fifty characters to pass validation.",
        "is_draft": False
    }
    client.post("/api/skills", json=payload, headers=HEADERS)
    
    # 2. Update skill
    update_payload = {
        "description": "Updated description.",
        "content": "Updated content with at least fifty characters to pass validation.",
        "change_description": "First update"
    }
    response = client.put("/api/skills/Versioned Skill", json=update_payload, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "1.1.0"
    
    # 3. Verify snapshot exists
    skill_dir = temp_skills_dir / "versioned-skill"
    assert (skill_dir / ".versions" / "v1.0.0.md").exists()
    
    # 4. Get historical version
    response = client.get("/api/skills/Versioned Skill/versions/1.0.0", headers=HEADERS)
    assert response.status_code == 200
    assert "Initial content" in response.json()["content"]

def test_draft_visibility(temp_skills_dir):
    # 1. Create draft as the API-key user. X-User is intentionally ignored by auth.
    payload = {
        "name": "User1 Draft",
        "description": "A draft skill.",
        "category": "implementation",
        "content": "Draft content with at least fifty characters to pass validation.",
        "is_draft": True
    }
    create_response = client.post("/api/skills", json=payload, headers=HEADERS)
    assert create_response.status_code == 200
    assert create_response.json()["author"] == "api-key-user"
    
    # 2. List skills as the same authenticated user (should see the draft)
    response = client.get("/api/skills", headers=HEADERS)
    assert response.status_code == 200
    assert any(s["name"] == "User1 Draft" for s in response.json())

def test_validate_skill(temp_skills_dir):
    # Valid template
    payload = {"content": "This is a valid template with {{task_description}} and {{working_dir}}."}
    response = client.post("/api/skills/validate", json=payload, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["valid"] is True
    
    # Invalid template (short)
    payload = {"content": "Short"}
    response = client.post("/api/skills/validate", json=payload, headers=HEADERS)
    assert response.json()["valid"] is False
    assert any("too short" in err for err in response.json()["errors"])
    
    # Malformed brackets
    payload = {"content": "Mismatched {{ brackets and more than fifty chars to pass length check."}
    response = client.post("/api/skills/validate", json=payload, headers=HEADERS)
    assert response.json()["valid"] is False
    assert len(response.json()["markers"]) > 0
    assert response.json()["markers"][0]["message"] == "Unclosed bracket '{{'"

def test_duplicate_check(temp_skills_dir):
    # 1. Create skill
    save_skill_md({"name": "Existing Skill", "description": "desc", "content": "content"}, path=temp_skills_dir / "existing-skill")
    
    # 2. Check for duplicate with similar name
    payload = {"name": "Existing Skil"}
    response = client.post("/api/skills/check-duplicate", json=payload, headers=HEADERS)
    assert response.status_code == 200
    assert "Existing Skill" in response.json()["similar_skills"]

def test_fork_skill(temp_skills_dir):
    # 1. Create original
    save_skill_md({"name": "original", "description": "desc", "content": "original content"}, path=temp_skills_dir / "original")
    
    # 2. Fork
    payload = {"name": "forked-skill"}
    response = client.post("/api/skills/original/fork", json=payload, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "forked-skill"
    assert data["forked_from"] == "original"
    assert data["version"] == "1.0.0"

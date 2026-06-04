import os
from pathlib import Path

import pytest

TEST_API_KEY = "test_key_123"
os.environ["OSTWIN_API_KEY"] = TEST_API_KEY

from fastapi.testclient import TestClient

from dashboard.api import app
from dashboard.api_utils import SKILLS_DIRS
from dashboard.routes import skills as skills_routes

os.environ["OSTWIN_API_KEY"] = TEST_API_KEY
client = TestClient(app)
HEADERS = {"X-API-Key": TEST_API_KEY, "X-User": "testuser"}


@pytest.fixture(autouse=True)
def auth_override():
    async def _current_user():
        return {"username": "testuser"}

    app.dependency_overrides[skills_routes.get_current_user] = _current_user
    yield
    app.dependency_overrides.pop(skills_routes.get_current_user, None)


def _write_skill(skill_dir: Path, name: str = "Migrated Skill") -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: A migratable skill used by tests.
tags:
  - migration
---
This skill has enough body content to be parsed and copied during migration.
""",
        encoding="utf-8",
    )
    return skill_dir


def _patch_migration(monkeypatch, tmp_path):
    source_root = tmp_path / "project" / ".agents" / "skills"
    target_root = tmp_path / "home" / ".ostwin" / ".agents" / "skills"
    monkeypatch.setattr(skills_routes, "_GLOBAL_SKILLS_DIR", target_root)
    monkeypatch.setattr(skills_routes, "_MIGRATION_SOURCE_ROOTS", [source_root, target_root])
    old_dirs = SKILLS_DIRS.copy()
    SKILLS_DIRS.clear()
    SKILLS_DIRS.extend([target_root, source_root])
    return source_root, target_root, old_dirs


def _restore_skill_dirs(old_dirs):
    SKILLS_DIRS.clear()
    SKILLS_DIRS.extend(old_dirs)


def test_migration_preview_finds_source_skill_and_targets_global_store(monkeypatch, tmp_path):
    source_root, target_root, old_dirs = _patch_migration(monkeypatch, tmp_path)
    try:
        _write_skill(source_root / "global" / "foo", "Foo Skill")
        _write_skill(source_root / "references" / "copy", "Reference Copy")

        response = client.post("/api/skills/migration/preview", headers=HEADERS, json={})

        assert response.status_code == 200
        data = response.json()
        assert data["target_path"] == str(target_root.resolve())
        assert data["total_skills"] == 1
        assert data["conflicts"] == 0
        assert data["source_summaries"][0]["skill_count"] == 1
        assert data["items"][0]["name"] == "Foo Skill"
        assert data["items"][0]["relative_path"] == "global/foo"
        assert data["items"][0]["target_path"] == str((target_root / "global" / "foo").resolve())
    finally:
        _restore_skill_dirs(old_dirs)


def test_migration_apply_requires_confirmation(monkeypatch, tmp_path):
    source_root, _, old_dirs = _patch_migration(monkeypatch, tmp_path)
    try:
        _write_skill(source_root / "global" / "foo")

        response = client.post(
            "/api/skills/migration/apply",
            headers=HEADERS,
            json={"delete_source": True},
        )

        assert response.status_code == 403
    finally:
        _restore_skill_dirs(old_dirs)


def test_migration_apply_copies_to_target_and_deletes_source(monkeypatch, tmp_path):
    source_root, target_root, old_dirs = _patch_migration(monkeypatch, tmp_path)
    try:
        source_skill = _write_skill(source_root / "roles" / "engineer" / "bar", "Bar Skill")

        response = client.post(
            "/api/skills/migration/apply",
            headers={**HEADERS, "X-Confirm-Migrate": "true"},
            json={"delete_source": True, "conflict_strategy": "skip"},
        )

        assert response.status_code == 200
        data = response.json()
        target_skill = target_root / "roles" / "engineer" / "bar"
        assert (target_skill / "SKILL.md").exists()
        assert not source_skill.exists()
        assert len(data["copied"]) == 1
        assert len(data["deleted"]) == 1
        assert data["target_path"] == str(target_root.resolve())
    finally:
        _restore_skill_dirs(old_dirs)


def test_migration_conflict_strategy_skip_and_fail(monkeypatch, tmp_path):
    source_root, target_root, old_dirs = _patch_migration(monkeypatch, tmp_path)
    try:
        source_skill = _write_skill(source_root / "global" / "foo", "Foo Skill")
        _write_skill(target_root / "global" / "foo", "Existing Foo Skill")

        fail_response = client.post(
            "/api/skills/migration/apply",
            headers={**HEADERS, "X-Confirm-Migrate": "true"},
            json={"conflict_strategy": "fail"},
        )
        assert fail_response.status_code == 409

        skip_response = client.post(
            "/api/skills/migration/apply",
            headers={**HEADERS, "X-Confirm-Migrate": "true"},
            json={"conflict_strategy": "skip", "delete_source": True},
        )
        assert skip_response.status_code == 200
        data = skip_response.json()
        assert len(data["skipped"]) == 1
        assert len(data["copied"]) == 0
        assert source_skill.exists()
    finally:
        _restore_skill_dirs(old_dirs)


def test_migration_duplicate_destination_conflicts_fail_before_copy(monkeypatch, tmp_path):
    source_root, target_root, old_dirs = _patch_migration(monkeypatch, tmp_path)
    second_source_root = tmp_path / "legacy" / ".agents" / "skills"
    monkeypatch.setattr(
        skills_routes,
        "_MIGRATION_SOURCE_ROOTS",
        [source_root, second_source_root, target_root],
    )
    try:
        first_skill = _write_skill(source_root / "global" / "foo", "Foo Skill")
        second_skill = _write_skill(second_source_root / "global" / "foo", "Foo Skill Copy")

        preview_response = client.post(
            "/api/skills/migration/preview", headers=HEADERS, json={}
        )

        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["total_skills"] == 2
        assert preview["conflicts"] == 1
        conflict_items = [item for item in preview["items"] if item["conflict"]]
        assert len(conflict_items) == 1
        assert conflict_items[0]["relative_path"] == "global/foo"

        fail_response = client.post(
            "/api/skills/migration/apply",
            headers={**HEADERS, "X-Confirm-Migrate": "true"},
            json={"conflict_strategy": "fail"},
        )

        assert fail_response.status_code == 409
        assert not (target_root / "global" / "foo").exists()
        assert first_skill.exists()
        assert second_skill.exists()
    finally:
        _restore_skill_dirs(old_dirs)

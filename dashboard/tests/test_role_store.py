import json

from dashboard.lib.roles.store import RoleRepository
from dashboard.models import Role


def _repo(tmp_path):
    return RoleRepository(
        global_roles_dir=tmp_path / "home" / ".agents" / "roles",
        project_roles_dir=tmp_path / "project" / ".agents" / "roles",
        roles_config_file=tmp_path / "home" / ".agents" / "roles" / "config.json",
        engine_config_file=tmp_path / "project" / ".agents" / "config.json",
    )


def _write_role(root, name, data=None, instructions=None):
    role_dir = root / name
    role_dir.mkdir(parents=True)
    if data is not None:
        (role_dir / "role.json").write_text(json.dumps(data))
    if instructions is not None:
        (role_dir / "ROLE.md").write_text(instructions)
    return role_dir


def test_list_roles_reads_folders_without_writing_config(tmp_path):
    repo = _repo(tmp_path)
    _write_role(
        repo.project_roles_dir,
        "engineer",
        {"name": "engineer", "model": "openai/gpt-5"},
        "Engineer instructions",
    )

    roles = repo.list_roles()

    assert [role.name for role in roles] == ["engineer"]
    assert roles[0].version == "openai/gpt-5"
    assert roles[0].instructions == "Engineer instructions"
    assert not repo.roles_config_file.exists()
    assert not repo.engine_config_file.exists()


def test_global_role_folder_overrides_project_role_folder(tmp_path):
    repo = _repo(tmp_path)
    _write_role(
        repo.project_roles_dir,
        "engineer",
        {"name": "engineer", "model": "openai/gpt-5"},
        "Project instructions",
    )
    _write_role(
        repo.global_roles_dir,
        "engineer",
        {"name": "engineer", "model": "anthropic/claude-sonnet-4"},
        "Global instructions",
    )

    role = repo.list_roles()[0]

    assert role.name == "engineer"
    assert role.version == "anthropic/claude-sonnet-4"
    assert role.instructions == "Global instructions"


def test_sync_migrates_legacy_config_values_into_role_folder(tmp_path):
    repo = _repo(tmp_path)
    _write_role(
        repo.global_roles_dir,
        "engineer",
        {"name": "engineer", "model": "openai/gpt-5"},
        "Folder instructions",
    )
    legacy = Role(
        id="legacy-engineer",
        name="engineer",
        description="Legacy description",
        instructions="Legacy instructions",
        provider="gpt",
        version="openai/gpt-5.5",
        temperature=0.7,
        budget_tokens_max=500000,
        max_retries=5,
        timeout_seconds=1200,
        skill_refs=["implement-epic"],
        mcp_refs=["github"],
        instance_type="worker",
        system_prompt_override=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-02T00:00:00+00:00",
    )
    repo.roles_config_file.parent.mkdir(parents=True, exist_ok=True)
    repo.roles_config_file.write_text(json.dumps([legacy.model_dump()]))

    result = repo.sync_from_disk()
    role_json = json.loads((repo.global_roles_dir / "engineer" / "role.json").read_text())

    assert result == {"synced": ["engineer"], "total": 1}
    assert role_json["id"] == "legacy-engineer"
    assert role_json["model"] == "openai/gpt-5.5"
    assert role_json["max_retries"] == 5
    assert role_json["timeout_seconds"] == 1200
    assert (repo.global_roles_dir / "engineer" / "ROLE.md").read_text() == "Legacy instructions"


def test_delete_role_removes_global_role_folder(tmp_path):
    repo = _repo(tmp_path)
    role_dir = _write_role(
        repo.global_roles_dir,
        "temporary-role",
        {"name": "temporary-role", "model": "openai/gpt-5"},
        "Temporary instructions",
    )
    role = repo.list_roles()[0]

    repo.delete_role(role)
    repo.save_projections([])

    assert not role_dir.exists()
    assert repo.list_roles() == []


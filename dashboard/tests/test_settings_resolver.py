"""
Tests for dashboard.lib.settings.resolver.SettingsResolver.

Covers: default-only resolution, layered overrides, provenance,
skill_refs union, vault deref (success + not-found), atomic writes.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from pydantic import ValidationError

from dashboard.lib.settings.resolver import SettingsResolver
from dashboard.models import MasterSettings


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def temp_project(tmp_path):
    """Create a complete mock project tree."""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()

    engine_config = {
        "engineer": {
            "default_model": "engine-model",
            "temperature": 0.8,
            "timeout_seconds": 500,
            "skill_refs": ["engine-skill"],
        },
        "runtime": {
            "poll_interval_seconds": 10,
            "max_concurrent_rooms": 5,
        },
    }
    (agents_dir / "config.json").write_text(json.dumps(engine_config))

    warrooms = tmp_path / ".war-rooms"
    warrooms.mkdir()

    # Plan-level role config in PLANS_DIR/{plan_id}.roles.json (flat structure)
    plans_dir = agents_dir / "plans"
    plans_dir.mkdir()
    plan_roles_config = {
        "engineer": {
            "default_model": "plan-model",
            "temperature": 0.5,
            "skill_refs": ["plan-skill"],
        },
        "attached_skills": ["attached-skill"],
    }
    (plans_dir / "plan-001.roles.json").write_text(json.dumps(plan_roles_config))

    # Room-level config (still in war-rooms)
    plan_dir = warrooms / "plan-001"
    plan_dir.mkdir()
    room_dir = plan_dir / "EPIC-001"
    room_dir.mkdir()
    room_config = {
        "role_config": {
            "engineer": {
                "default_model": "room-model",
                "temperature": 0.3,
                "skill_refs": ["room-skill"],
            }
        }
    }
    (room_dir / "config.json").write_text(json.dumps(room_config))
    (room_dir / "brief.md").write_text("Test brief content")

    return tmp_path


@pytest.fixture
def resolver(temp_project):
    """Build a resolver pointing at the temp project."""
    config_path = temp_project / ".agents" / "config.json"
    with patch("dashboard.lib.settings.resolver.AGENTS_DIR", temp_project / ".agents"), \
         patch("dashboard.lib.settings.resolver.PROJECT_ROOT", temp_project):
        r = SettingsResolver(config_path=config_path)
        # Replace vault with a mock so we don't touch the real keychain
        r.vault = MagicMock()
        r.vault.get.return_value = None
        yield r


def _skill_mock(name: str) -> Mock:
    m = Mock()
    m.name = name
    return m


# ── load / save ───────────────────────────────────────────────────────────

def test_load_config(resolver, temp_project):
    cfg = resolver.load_config()
    assert cfg["engineer"]["default_model"] == "engine-model"


def test_save_config_atomic(resolver, temp_project):
    cfg = resolver.load_config()
    cfg["new_key"] = "new_value"
    resolver.save_config(cfg)

    raw = json.loads((temp_project / ".agents" / "config.json").read_text())
    assert raw["new_key"] == "new_value"
    assert not (temp_project / ".agents" / "config.tmp").exists()


# ── get_master_settings ───────────────────────────────────────────────────

def test_get_master_settings(resolver):
    ms = resolver.get_master_settings()
    assert isinstance(ms, MasterSettings)
    assert ms.runtime.poll_interval_seconds == 10
    assert ms.runtime.max_concurrent_rooms == 5


# ── resolve_role ──────────────────────────────────────────────────────────

def test_resolve_role_default_only(resolver):
    # Wipe the engine config so only defaults apply
    resolver.save_config({})

    defaults = {"engineer": {"default_model": "default-model", "timeout_seconds": 300}}
    with patch("dashboard.constants.ROLE_DEFAULTS", defaults):
        res = resolver.resolve_role("engineer")

    assert res.effective["default_model"] == "default-model"
    assert res.provenance["default_model"] == "default"


def test_resolve_role_layered_overrides(resolver, temp_project):
    defaults = {"engineer": {"default_model": "default-model", "timeout_seconds": 300}}

    with patch("dashboard.constants.ROLE_DEFAULTS", defaults), \
         patch("dashboard.api_utils.PLANS_DIR", temp_project / ".agents" / "plans"), \
         patch("dashboard.api_utils.WARROOMS_DIR", temp_project / ".war-rooms"), \
         patch("dashboard.api_utils.build_skills_list", return_value=[]):
        res = resolver.resolve_role("engineer", plan_id="plan-001", task_ref="EPIC-001")

    assert res.effective["default_model"] == "room-model"
    assert res.provenance["default_model"] == "room:EPIC-001"
    assert res.effective["temperature"] == 0.3
    assert res.provenance["temperature"] == "room:EPIC-001"


def test_provenance_default(resolver):
    resolver.save_config({})
    defaults = {"engineer": {"default_model": "d"}}
    with patch("dashboard.constants.ROLE_DEFAULTS", defaults):
        res = resolver.resolve_role("engineer")

    assert res.provenance["default_model"] == "default"


def test_provenance_global(resolver):
    defaults = {"engineer": {"timeout_seconds": 300}}
    with patch("dashboard.constants.ROLE_DEFAULTS", defaults):
        res = resolver.resolve_role("engineer")

    # engine config sets default_model for engineer -> provenance=global
    assert res.provenance["default_model"] == "global"


# ── skill_refs union ─────────────────────────────────────────────────────

def test_skill_refs_union_across_layers(resolver, temp_project):
    defaults = {"engineer": {"skill_refs": ["default-skill"]}}
    enabled = [
        _skill_mock("default-skill"),
        _skill_mock("engine-skill"),
        _skill_mock("plan-skill"),
        _skill_mock("attached-skill"),
        _skill_mock("room-skill"),
    ]

    with patch("dashboard.constants.ROLE_DEFAULTS", defaults), \
         patch("dashboard.api_utils.PLANS_DIR", temp_project / ".agents" / "plans"), \
         patch("dashboard.api_utils.WARROOMS_DIR", temp_project / ".war-rooms"), \
         patch("dashboard.api_utils.build_skills_list", return_value=enabled):
        res = resolver.resolve_role("engineer", plan_id="plan-001", task_ref="EPIC-001")

    refs = set(res.effective.get("skill_refs", []))
    assert {"default-skill", "engine-skill", "plan-skill", "attached-skill", "room-skill"} == refs


def test_skill_refs_disabled_subtracted(resolver, temp_project):
    # Add disabled_skills at plan level in the roles.json file
    plans_dir = temp_project / ".agents" / "plans"
    plan_cfg = json.loads(
        (plans_dir / "plan-001.roles.json").read_text()
    )
    plan_cfg["engineer"]["disabled_skills"] = ["engine-skill"]
    (plans_dir / "plan-001.roles.json").write_text(
        json.dumps(plan_cfg)
    )
    resolver._cache = None  # invalidate

    defaults = {"engineer": {"skill_refs": ["default-skill"]}}
    enabled = [_skill_mock("default-skill"), _skill_mock("engine-skill"),
               _skill_mock("plan-skill"), _skill_mock("attached-skill")]

    with patch("dashboard.constants.ROLE_DEFAULTS", defaults), \
         patch("dashboard.api_utils.PLANS_DIR", plans_dir), \
         patch("dashboard.api_utils.build_skills_list", return_value=enabled):
        res = resolver.resolve_role("engineer", plan_id="plan-001")

    assert "engine-skill" not in res.effective["skill_refs"]


# ── vault deref ───────────────────────────────────────────────────────────

def test_vault_deref_success(resolver):
    resolver.vault.get.return_value = "secret-value"
    result = resolver._resolve_vault_refs("${vault:providers/claude}")
    assert result == "secret-value"


def test_vault_deref_not_found_returns_none(resolver):
    resolver.vault.get.return_value = None
    result = resolver._resolve_vault_refs("${vault:providers/missing}")
    assert result is None


def test_vault_deref_plain_passthrough(resolver):
    result = resolver._resolve_vault_refs("plain-value")
    assert result == "plain-value"


def test_vault_deref_masked(resolver):
    resolver.vault.get.return_value = "sk-ant-secret-value"
    result = resolver._resolve_vault_refs("${vault:providers/claude}", mask=True)
    assert result.startswith("***")
    assert "sk-ant" not in result


def test_vault_deref_exception_graceful(resolver):
    resolver.vault.get.side_effect = RuntimeError("keychain locked")
    result = resolver._resolve_vault_refs("${vault:providers/claude}")
    assert result is None


# ── atomic write ──────────────────────────────────────────────────────────

def test_atomic_write_json(tmp_path):
    path = tmp_path / "test.json"
    SettingsResolver._atomic_write_json(path, {"key": "value"})
    assert json.loads(path.read_text()) == {"key": "value"}
    assert not path.with_suffix(".tmp").exists()


def test_atomic_write_cleanup_on_error(tmp_path):
    path = tmp_path / "test.json"
    with patch("pathlib.Path.write_text", side_effect=PermissionError("denied")):
        with pytest.raises(PermissionError):
            SettingsResolver._atomic_write_json(path, {"key": "value"})
    assert not path.with_suffix(".tmp").exists()


# ── patch helpers ─────────────────────────────────────────────────────────

def test_patch_namespace(resolver, temp_project):
    resolver.patch_namespace("runtime", {"max_concurrent_rooms": 100})
    cfg = json.loads((temp_project / ".agents" / "config.json").read_text())
    assert cfg["manager"]["max_concurrent_rooms"] == 100
    assert "max_concurrent_rooms" not in cfg.get("runtime", {})


def test_default_config_path_honors_ostwin_project_dir(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    monkeypatch.setenv("OSTWIN_PROJECT_DIR", str(project_dir))

    resolver = SettingsResolver()

    assert resolver.config_path == project_dir / ".agents" / "config.json"


def test_patch_namespace_rejects_legacy_poll_interval(resolver):
    with pytest.raises(ValidationError):
        resolver.patch_namespace("runtime", {"poll_interval": 42})


def test_reset_namespace(resolver, temp_project):
    resolver.reset_namespace("runtime")
    cfg = json.loads((temp_project / ".agents" / "config.json").read_text())
    assert "runtime" not in cfg
    assert "manager" not in cfg


def test_patch_plan_role(resolver, temp_project):
    plans_dir = temp_project / ".agents" / "plans"
    with patch("dashboard.api_utils.PLANS_DIR", plans_dir):
        resolver.patch_plan_role("plan-001", "engineer", {"temperature": 1.5})

    plan_cfg = json.loads(
        (plans_dir / "plan-001.roles.json").read_text()
    )
    assert plan_cfg["engineer"]["temperature"] == 1.5


def test_patch_room_role(resolver, temp_project):
    with patch("dashboard.api_utils.WARROOMS_DIR", temp_project / ".war-rooms"):
        resolver.patch_room_role("plan-001", "EPIC-001", "engineer", {"temperature": 1.9})

    room_cfg = json.loads(
        (temp_project / ".war-rooms" / "plan-001" / "EPIC-001" / "config.json").read_text()
    )
    assert room_cfg["role_config"]["engineer"]["temperature"] == 1.9

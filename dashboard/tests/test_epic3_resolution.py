"""
Regression tests for EpicSkillsManager.resolve_config and
generate_system_prompt.  These must pass unchanged after the
resolver consolidation (settings_manager.py -> lib/settings/).
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from dashboard.epic_manager import EpicSkillsManager


@pytest.fixture
def mock_project(tmp_path):
    """Complete mock project tree for epic resolution."""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    (agents_dir / "config.json").write_text(json.dumps({
        "engineer": {
            "default_model": "global-model",
            "temperature": 0.7,
        }
    }))

    warrooms = tmp_path / ".war-rooms"
    warrooms.mkdir()

    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()

    plan_dir = warrooms / "plan-001"
    plan_dir.mkdir()
    (plan_dir / "config.json").write_text(json.dumps({
        "roles": {
            "engineer": {
                "default_model": "plan-model",
                "temperature": 0.5,
                "skill_refs": ["plan-skill"],
            }
        },
        "attached_skills": ["attached-skill"],
    }))

    (plans_dir / "plan-001.md").write_text("# Plan 001\n\nTest plan content.")

    room_dir = plan_dir / "EPIC-003"
    room_dir.mkdir()
    (room_dir / "config.json").write_text(json.dumps({
        "role_config": {
            "engineer": {
                "default_model": "gpt-4-override",
                "temperature": 0.1,
                "skill_refs": ["room-skill"],
            }
        }
    }))
    (room_dir / "brief.md").write_text("This is a test epic brief.")

    roles_dir = agents_dir / "roles" / "engineer"
    roles_dir.mkdir(parents=True)
    (roles_dir / "ROLE.md").write_text(
        "---\nname: engineer\n---\n# Responsibilities\nDo engineering things."
    )

    skills_dir = tmp_path / "skills" / "room-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: room-skill\n---\n# Usage\nUse this for testing."
    )

    return tmp_path


@pytest.fixture
def resolver_patches(mock_project):
    """Context manager that patches resolver to use mock project."""
    from dashboard.lib.settings.resolver import SettingsResolver, reset_settings_resolver

    reset_settings_resolver()
    config_path = mock_project / ".agents" / "config.json"
    mock_vault = MagicMock()
    mock_vault.get.return_value = None

    def _fake_resolver():
        r = SettingsResolver(config_path=config_path)
        r.vault = mock_vault
        return r

    patches = patch.multiple(
        "dashboard.api_utils",
        AGENTS_DIR=mock_project / ".agents",
        PROJECT_ROOT=mock_project,
        WARROOMS_DIR=mock_project / ".war-rooms",
        PLANS_DIR=mock_project / "plans",
        GLOBAL_PLANS_DIR=mock_project / "plans",
    )
    return patches, _fake_resolver, mock_vault


def test_resolve_config(mock_project, resolver_patches):
    """resolve_config should return room-level overrides + brief."""
    patches, factory, _ = resolver_patches
    room_dir = mock_project / ".war-rooms" / "plan-001" / "EPIC-003"

    with patches, \
         patch("dashboard.lib.settings.resolver.get_settings_resolver", factory), \
         patch("dashboard.epic_manager._resolve_room_dir", return_value=room_dir), \
         patch("dashboard.constants.ROLE_DEFAULTS", {"engineer": {"skill_refs": ["default-skill"]}}), \
         patch("dashboard.api_utils.build_skills_list", return_value=[]):

        config = EpicSkillsManager.resolve_config("plan-001", "EPIC-003", "engineer")

    assert config["model"] == "gpt-4-override"
    assert config["temperature"] == 0.1
    assert config["brief"] == "This is a test epic brief."


def test_generate_system_prompt(mock_project, resolver_patches):
    """generate_system_prompt should contain role heading + instructions + brief."""
    patches, factory, _ = resolver_patches
    room_dir = mock_project / ".war-rooms" / "plan-001" / "EPIC-003"

    with patches, \
         patch("dashboard.lib.settings.resolver.get_settings_resolver", factory), \
         patch("dashboard.epic_manager._resolve_room_dir", return_value=room_dir), \
         patch("dashboard.epic_manager.AGENTS_DIR", mock_project / ".agents"), \
         patch("dashboard.epic_manager.SKILLS_DIRS", [mock_project / "skills"]), \
         patch("dashboard.routes.plans.PLANS_DIR", mock_project / "plans"), \
         patch("dashboard.routes.plans.GLOBAL_PLANS_DIR", mock_project / "plans"), \
         patch("dashboard.constants.ROLE_DEFAULTS", {}), \
         patch("dashboard.api_utils.build_skills_list", return_value=[]):

        prompt = EpicSkillsManager.generate_system_prompt("plan-001", "EPIC-003", "engineer")

    assert "# Role: engineer" in prompt
    assert "Do engineering things." in prompt
    assert "# Current Epic Context" in prompt
    assert "This is a test epic brief." in prompt


def test_generate_system_prompt_appends_plan_system_prompt_override(mock_project, resolver_patches):
    """Preview generation should mirror runtime prompt override append behavior."""
    (mock_project / "plans" / "plan-001.roles.json").write_text(json.dumps({
        "engineer": {
            "system_prompt_override": "Final dashboard preview override."
        }
    }))
    patches, factory, _ = resolver_patches
    room_dir = mock_project / ".war-rooms" / "plan-001" / "EPIC-003"

    with patches, \
         patch("dashboard.lib.settings.resolver.get_settings_resolver", factory), \
         patch("dashboard.epic_manager._resolve_room_dir", return_value=room_dir), \
         patch("dashboard.epic_manager.AGENTS_DIR", mock_project / ".agents"), \
         patch("dashboard.epic_manager.SKILLS_DIRS", [mock_project / "skills"]), \
         patch.object(EpicSkillsManager, "build_asset_context", return_value=""), \
         patch("dashboard.constants.ROLE_DEFAULTS", {}), \
         patch("dashboard.api_utils.build_skills_list", return_value=[]):

        prompt = EpicSkillsManager.generate_system_prompt("plan-001", "EPIC-003", "engineer")

    assert "# System Prompt Override" in prompt
    assert prompt.strip().endswith("Final dashboard preview override.")

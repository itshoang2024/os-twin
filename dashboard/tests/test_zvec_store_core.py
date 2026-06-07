"""Tests for dashboard/zvec_store.py — pure/static methods that don't need zvec runtime."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dashboard.zvec_store import PLANS_COLLECTION, OSTwinStore


# ── OSTwinStore._sanitize_text ─────────────────────────────────────


class TestSanitizeText:
    """Tests for OSTwinStore._sanitize_text() static method."""

    def test_ascii_text_unchanged(self):
        text = "Hello world! This is plain ASCII."
        assert OSTwinStore._sanitize_text(text) == text

    def test_em_dash_replaced(self):
        assert OSTwinStore._sanitize_text("word\u2014word") == "word--word"

    def test_en_dash_replaced(self):
        assert OSTwinStore._sanitize_text("1\u20132") == "1-2"

    def test_smart_single_quotes_replaced(self):
        result = OSTwinStore._sanitize_text("\u2018hello\u2019")
        assert result == "'hello'"

    def test_smart_double_quotes_replaced(self):
        result = OSTwinStore._sanitize_text("\u201CHello\u201D")
        assert result == '"Hello"'

    def test_ellipsis_replaced(self):
        assert OSTwinStore._sanitize_text("wait\u2026") == "wait..."

    def test_non_breaking_space_replaced(self):
        result = OSTwinStore._sanitize_text("hello\u00A0world")
        assert result == "hello world"

    def test_bullet_replaced(self):
        result = OSTwinStore._sanitize_text("\u2022 item")
        assert result == "* item"

    def test_emoji_stripped(self):
        result = OSTwinStore._sanitize_text("Hello 🎉 World 🚀")
        # Emoji should be stripped; rest should remain
        assert "Hello" in result
        assert "World" in result
        assert "🎉" not in result
        assert "🚀" not in result

    def test_none_text_handled(self):
        # _sanitize_text returns the falsy value as-is
        assert OSTwinStore._sanitize_text("") == ""
        assert OSTwinStore._sanitize_text(None) is None

    def test_mixed_unicode(self):
        text = "EPIC-001 \u2014 Setup \u201Cproject\u201D with \u2026"
        result = OSTwinStore._sanitize_text(text)
        assert "EPIC-001" in result
        assert "--" in result
        assert '"project"' in result
        assert "..." in result

    def test_horizontal_bar_replaced(self):
        assert "--" in OSTwinStore._sanitize_text("\u2015")

    def test_non_breaking_hyphen_replaced(self):
        assert "-" in OSTwinStore._sanitize_text("\u2011")

    def test_minus_sign_replaced(self):
        assert "-" in OSTwinStore._sanitize_text("\u2212")

    def test_guillemets_replaced(self):
        assert OSTwinStore._sanitize_text("\u00AB") == "<<"
        assert OSTwinStore._sanitize_text("\u00BB") == ">>"
        assert OSTwinStore._sanitize_text("\u2039") == "<"
        assert OSTwinStore._sanitize_text("\u203A") == ">"

    def test_nfkd_decomposition(self):
        # Accented characters should decompose to ASCII base
        result = OSTwinStore._sanitize_text("caf\u00E9")
        assert result == "cafe"


# ── OSTwinStore.migrate_collections ─────────────────────────────────


class TestMigrateCollections:
    """Tests for schema migration checks."""

    def test_rebuilds_collection_when_embedding_is_not_vector(self, tmp_path):
        store = OSTwinStore.__new__(OSTwinStore)
        store.zvec_dir = tmp_path / ".zvec"
        stale_collection = store.zvec_dir / PLANS_COLLECTION
        stale_collection.mkdir(parents=True)

        stale_schema = SimpleNamespace(
            fields=[
                SimpleNamespace(name="time_id"),
                SimpleNamespace(name="embedding"),
            ],
            vectors=[],
        )
        stale_collection_handle = SimpleNamespace(schema=stale_schema)

        with patch("zvec.open", return_value=stale_collection_handle):
            stats = store.migrate_collections()

        assert PLANS_COLLECTION in stats["migrated"]
        assert not stale_collection.exists()


# ── OSTwinStore._parse_plan_epics ──────────────────────────────────


class TestParsePlanEpics:
    """Tests for OSTwinStore._parse_plan_epics() static method."""

    def test_epic_colon_format(self):
        content = (
            "# Plan: Test\n\n"
            "working_dir: /projects/test\n\n"
            "## Epic: EPIC-001 \u2014 Setup Project\n"
            "Bootstrap the repository and CI.\n\n"
            "## Epic: EPIC-002 \u2014 Build API\n"
            "Implement REST endpoints.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "test-plan")
        assert len(epics) == 2
        assert epics[0]["task_ref"] == "EPIC-001"
        assert epics[0]["title"] == "Setup Project"
        assert epics[0]["room_id"] == "room-001"
        assert epics[0]["working_dir"] == "/projects/test"
        assert epics[1]["task_ref"] == "EPIC-002"
        assert epics[1]["title"] == "Build API"
        assert epics[1]["room_id"] == "room-002"

    def test_epic_bare_format(self):
        content = (
            "# Plan: Bare\n\n"
            "### EPIC-001 - First Epic\n"
            "Body of first epic.\n\n"
            "### EPIC-002 - Second Epic\n"
            "Body of second epic.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "bare-plan")
        assert len(epics) == 2
        assert epics[0]["task_ref"] == "EPIC-001"
        assert epics[0]["title"] == "First Epic"
        assert epics[1]["task_ref"] == "EPIC-002"

    def test_task_format(self):
        content = (
            "# Plan: Tasks\n\n"
            "## Task: TASK-001 \u2014 Write Tests\n"
            "Cover all modules.\n\n"
            "## Task: TASK-002 \u2014 Deploy\n"
            "Push to staging.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "task-plan")
        assert len(epics) == 2
        assert epics[0]["task_ref"] == "TASK-001"
        assert epics[0]["title"] == "Write Tests"
        assert epics[1]["task_ref"] == "TASK-002"

    def test_no_epics_returns_empty(self):
        content = "# Plan: Empty\n\nJust some text without epics."
        epics = OSTwinStore._parse_plan_epics(content, "empty-plan")
        assert epics == []

    def test_working_dir_extracted(self):
        content = (
            "working_dir: /my/project/path\n\n"
            "## Epic: EPIC-001 \u2014 Something\n"
            "Body.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "wd-plan")
        assert len(epics) == 1
        assert epics[0]["working_dir"] == "/my/project/path"

    def test_working_dir_default_when_missing(self):
        content = (
            "## Epic: EPIC-001 \u2014 No WD\n"
            "Body.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "no-wd-plan")
        assert len(epics) == 1
        assert epics[0]["working_dir"] == "."

    def test_multiple_epics_have_sequential_room_ids(self):
        content = (
            "## Epic: EPIC-001 \u2014 A\nBody A.\n\n"
            "## Epic: EPIC-002 \u2014 B\nBody B.\n\n"
            "## Epic: EPIC-003 \u2014 C\nBody C.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "multi-plan")
        assert len(epics) == 3
        assert epics[0]["room_id"] == "room-001"
        assert epics[1]["room_id"] == "room-002"
        assert epics[2]["room_id"] == "room-003"

    def test_epic_body_is_content_below_header(self):
        content = (
            "## Epic: EPIC-001 \u2014 Title\n"
            "Line one.\n"
            "Line two.\n"
            "Line three.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "body-plan")
        assert len(epics) == 1
        assert "Line one." in epics[0]["body"]
        assert "Line two." in epics[0]["body"]
        assert "Line three." in epics[0]["body"]

    def test_h3_epic_colon_format(self):
        """### Epic: ... format should also be parsed."""
        content = (
            "### Epic: EPIC-001 \u2014 Title\n"
            "Body.\n"
        )
        epics = OSTwinStore._parse_plan_epics(content, "h3-plan")
        assert len(epics) == 1
        assert epics[0]["task_ref"] == "EPIC-001"


# ── OSTwinStore._skill_doc_id ─────────────────────────────────────


class TestSkillDocId:
    """Tests for OSTwinStore._skill_doc_id() static method."""

    def test_normal_name(self):
        result = OSTwinStore._skill_doc_id("my-skill")
        assert result == "my-skill"

    def test_uppercase_lowered(self):
        result = OSTwinStore._skill_doc_id("My Skill")
        assert result == "my-skill"

    def test_special_characters_removed(self):
        result = OSTwinStore._skill_doc_id("skill@v1.0!")
        # regex replaces non-alnum to "-", strip("-") removes trailing
        assert result == "skill-v1-0"
        result2 = OSTwinStore._skill_doc_id("!skill!")
        assert not result2.startswith("-")
        assert not result2.endswith("-")

    def test_leading_trailing_hyphens_stripped(self):
        result = OSTwinStore._skill_doc_id("  --my-skill--  ")
        assert not result.startswith("-")
        assert not result.endswith("-")
        assert "my-skill" in result

    def test_spaces_become_hyphens(self):
        result = OSTwinStore._skill_doc_id("Add UGUI View")
        assert result == "add-ugui-view"

    def test_empty_after_sanitize(self):
        result = OSTwinStore._skill_doc_id("!!!")
        assert result == ""

    def test_alphanumeric_only(self):
        result = OSTwinStore._skill_doc_id("abc123")
        assert result == "abc123"

    def test_mixed_casing_and_symbols(self):
        result = OSTwinStore._skill_doc_id("Game Architecture Design")
        assert result == "game-architecture-design"

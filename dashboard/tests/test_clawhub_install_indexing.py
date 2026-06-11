"""Unit tests for ClawHub install → zvec indexing (post-install searchability fix)."""
import os
import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

TEST_API_KEY = "test_key_clawhub"
os.environ["OSTWIN_API_KEY"] = TEST_API_KEY
os.environ.setdefault("OSTWIN_AUTH_KEY", TEST_API_KEY)

from dashboard.api_utils import parse_skill_md
from dashboard.routes import skills as skills_routes
from dashboard.routes.skills import _index_skill_from_disk


def _make_skill_on_disk(base_dir: Path, slug: str, name: str = "", description: str = "A test skill") -> Path:
    """Create a minimal SKILL.md inside base_dir/slug/ and return the skill directory."""
    skill_dir = base_dir / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name or slug}\ndescription: {description}\ntags:\n  - clawhub\n---\nSkill content body here for testing purposes, needs enough characters."
    )
    return skill_dir


class _FakeLock:
    """A fake asyncio.Lock that is always unlocked and does nothing."""
    def locked(self):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ── _index_skill_from_disk unit tests ────────────────────────────────

class TestIndexSkillFromDisk:
    """Verify the helper that the clawhub_install endpoint now calls."""

    def test_calls_store_with_correct_name_and_description(self, tmp_path):
        skill_dir = _make_skill_on_disk(tmp_path, "my-clawhub-skill")
        skill_data = parse_skill_md(skill_dir)
        assert skill_data is not None

        store = MagicMock()
        store.index_skill.return_value = True

        _index_skill_from_disk(store, skill_data)

        store.index_skill.assert_called_once()
        kwargs = store.index_skill.call_args.kwargs
        assert kwargs["name"] == "my-clawhub-skill"
        assert kwargs["description"] == "A test skill"
        assert "clawhub" in kwargs["tags"]

    def test_passes_all_required_fields(self, tmp_path):
        skill_dir = _make_skill_on_disk(tmp_path, "full-field-skill", name="Full Field Skill")
        skill_data = parse_skill_md(skill_dir)

        store = MagicMock()
        _index_skill_from_disk(store, skill_data)

        kwargs = store.index_skill.call_args.kwargs
        for key in ("name", "description", "tags", "path", "trust_level", "source", "content"):
            assert key in kwargs, f"Missing required field: {key}"


# ── clawhub_install endpoint integration tests ──────────────────────

class TestClawhubInstallIndexing:
    """Test that the clawhub_install endpoint indexes the skill into zvec after install."""

    @pytest.fixture
    def mock_globals(self, tmp_path):
        """Patch global dirs for isolated testing.

        Upstream uses --workdir and --dir so clawhub writes directly into
        _GLOBAL_SKILLS_DIR/<slug> (no separate "global" subdirectory).
        """
        fake_skills_dir = tmp_path / "skills"
        fake_skills_dir.mkdir(parents=True)
        fake_workdir = tmp_path / "workdir"
        fake_workdir.mkdir(parents=True)

        patches = [
            patch.object(skills_routes, "_GLOBAL_SKILLS_DIR", fake_skills_dir),
            patch.object(skills_routes, "_CLAWHUB_WORKDIR", fake_workdir),
            patch.object(skills_routes, "_install_lock", _FakeLock()),
        ]
        for p in patches:
            p.start()

        yield {"skills_dir": fake_skills_dir, "workdir": fake_workdir}

        for p in patches:
            p.stop()

    def _make_mocks(self):
        """Create common mocks for subprocess and request."""
        fake_proc = AsyncMock()
        fake_proc.communicate = AsyncMock(return_value=(b"installed ok", b""))
        fake_proc.returncode = 0

        mock_request = MagicMock()
        mock_request.headers.get = lambda k: "true" if k == "x-confirm-install" else ""

        return fake_proc, mock_request

    @pytest.mark.asyncio
    async def test_indexes_skill_after_successful_install(self, mock_globals):
        """After a successful clawhub install, the skill must be indexed into zvec."""
        skills_dir = mock_globals["skills_dir"]

        # Simulate what `bun x clawhub install --workdir --dir skills` produces:
        # the skill lands directly in _GLOBAL_SKILLS_DIR/<slug>/SKILL.md
        _make_skill_on_disk(skills_dir, "test-clawhub-skill", description="From ClawHub")

        store = MagicMock()
        store.index_skill.return_value = True
        fake_proc, mock_request = self._make_mocks()

        with patch("dashboard.routes.skills._verify_clawhub_skill_exists", new_callable=AsyncMock, return_value=True), \
             patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc) as create_proc, \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"installed ok", b"")), \
             patch("dashboard.routes.skills.shutil.which", return_value=None), \
             patch("dashboard.global_state.store", store):

            req = skills_routes.ClawhubInstallRequest(skill_name="test-clawhub-skill")
            result = await skills_routes.clawhub_install(req, mock_request, {"username": "testuser"})

        assert result["status"] == "installed"
        assert create_proc.call_args.args[:3] == ("bun", "x", "clawhub")

        # Skill should exist at _GLOBAL_SKILLS_DIR/<slug>
        dest = skills_dir / "test-clawhub-skill"
        assert dest.exists()
        assert (dest / "SKILL.md").exists()

        # Critical assertion: index_skill must have been called
        store.index_skill.assert_called_once()
        kwargs = store.index_skill.call_args.kwargs
        assert kwargs["name"] == "test-clawhub-skill"
        assert kwargs["description"] == "From ClawHub"

    @pytest.mark.asyncio
    async def test_succeeds_without_crash_when_store_is_none(self, mock_globals):
        """If the zvec store is None, install should still succeed (just skip indexing)."""
        skills_dir = mock_globals["skills_dir"]
        _make_skill_on_disk(skills_dir, "no-store-skill")

        fake_proc, mock_request = self._make_mocks()

        with patch("dashboard.routes.skills._verify_clawhub_skill_exists", new_callable=AsyncMock, return_value=True), \
             patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"ok", b"")), \
             patch("dashboard.routes.skills.shutil.which", return_value=None), \
             patch("dashboard.global_state.store", None):

            req = skills_routes.ClawhubInstallRequest(skill_name="no-store-skill")
            result = await skills_routes.clawhub_install(req, mock_request, {"username": "test"})

        assert result["status"] == "installed"

    @pytest.mark.asyncio
    async def test_skips_indexing_when_skill_md_missing(self, mock_globals):
        """If clawhub CLI produces a dir without SKILL.md, indexing should be skipped."""
        skills_dir = mock_globals["skills_dir"]

        # Create dir WITHOUT SKILL.md
        (skills_dir / "broken-skill").mkdir(parents=True)

        store = MagicMock()
        fake_proc, mock_request = self._make_mocks()

        with patch("dashboard.routes.skills._verify_clawhub_skill_exists", new_callable=AsyncMock, return_value=True), \
             patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"ok", b"")), \
             patch("dashboard.routes.skills.shutil.which", return_value=None), \
             patch("dashboard.global_state.store", store):

            req = skills_routes.ClawhubInstallRequest(skill_name="broken-skill")
            result = await skills_routes.clawhub_install(req, mock_request, {"username": "test"})

        assert result["status"] == "installed"
        store.index_skill.assert_not_called()


# ── Regression: local install_skill already indexes ──────────────────

class TestLocalInstallAlreadyIndexes:
    """Confirm the local install endpoint indexes — regression guard."""

    @pytest.mark.asyncio
    async def test_local_install_calls_index_skill(self, tmp_path):
        skill_dir = _make_skill_on_disk(tmp_path, "local-skill")

        store = MagicMock()
        store.index_skill.return_value = True

        with patch("dashboard.global_state.store", store):
            from dashboard.routes.skills import install_skill
            from dashboard.models import SkillInstallRequest

            req = SkillInstallRequest(path=str(skill_dir))
            result = await install_skill(req, {"username": "test"})

        assert result["status"] == "installed"
        store.index_skill.assert_called_once()

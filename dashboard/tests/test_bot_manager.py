"""Tests for dashboard/bot_manager.py"""
import sys
from pathlib import Path
from unittest.mock import MagicMock


class TestBotDirResolution:
    """Test BOT_DIR resolution logic."""

    def test_bot_dir_prefers_ostwin_home(self, tmp_path, monkeypatch):
        """BOT_DIR should prefer ~/.ostwin/bot/ when it exists."""
        bot_dir = tmp_path / ".ostwin" / "bot"
        bot_dir.mkdir(parents=True)
        (bot_dir / "package.json").write_text("{}")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        if "dashboard.bot_manager" in sys.modules:
            del sys.modules["dashboard.bot_manager"]

        import dashboard.bot_manager as bm

        assert bm.BOT_DIR == tmp_path / ".ostwin" / "bot"

    def test_bot_dir_fallback_to_relative(self, tmp_path, monkeypatch):
        """BOT_DIR should fallback to relative path when ~/.ostwin/bot/ doesn't exist."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        if "dashboard.bot_manager" in sys.modules:
            del sys.modules["dashboard.bot_manager"]

        import dashboard.bot_manager as bm

        assert bm.BOT_DIR == bm._DASHBOARD_DIR.parent / "bot"


class TestBotProcessManager:
    """Test BotProcessManager class."""

    def test_init_with_default_dir(self):
        """BotProcessManager should use BOT_DIR by default."""
        from dashboard.bot_manager import BotProcessManager, BOT_DIR

        manager = BotProcessManager()
        assert manager.bot_dir == BOT_DIR

    def test_init_with_custom_dir(self, tmp_path):
        """BotProcessManager should accept custom bot_dir."""
        from dashboard.bot_manager import BotProcessManager

        custom_dir = tmp_path / "custom-bot"
        manager = BotProcessManager(bot_dir=custom_dir)

        assert manager.bot_dir == custom_dir

    def test_status_when_not_running(self):
        """Status should return correct info when bot is not running."""
        from dashboard.bot_manager import BotProcessManager

        manager = BotProcessManager()
        status = manager.status()

        assert status["running"] is False
        assert status["pid"] is None
        assert status["started_at"] is None

    def test_is_running_false_when_no_process(self):
        """is_running should be False when no process exists."""
        from dashboard.bot_manager import BotProcessManager

        manager = BotProcessManager()
        assert manager.is_running is False

    def test_find_bun_from_path(self, tmp_path, monkeypatch):
        """_find_bun should return Bun path when available."""
        from dashboard.bot_manager import BotProcessManager
        import shutil

        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/bun" if x == "bun" else None)

        manager = BotProcessManager(bot_dir=tmp_path)
        assert manager._find_bun() == "/usr/bin/bun"

    def test_find_bun_returns_none_when_not_found(self, tmp_path, monkeypatch):
        """_find_bun should return None when Bun is unavailable."""
        from dashboard.bot_manager import BotProcessManager
        import shutil

        monkeypatch.setattr(shutil, "which", lambda x: None)

        manager = BotProcessManager(bot_dir=tmp_path)
        assert manager._find_bun() is None


class TestEnsureBotDependencies:
    """Test ensure_bot_dependencies function."""

    def test_returns_true_when_node_modules_exists(self, tmp_path, monkeypatch):
        """Should return True if node_modules already exists."""
        (tmp_path / "node_modules").mkdir()

        import dashboard.bot_manager as bm
        monkeypatch.setattr(bm, "BOT_DIR", tmp_path)

        result = bm.ensure_bot_dependencies()
        assert result is True

    def test_returns_false_when_no_package_json(self, tmp_path, monkeypatch):
        """Should return False if package.json doesn't exist."""
        import dashboard.bot_manager as bm
        monkeypatch.setattr(bm, "BOT_DIR", tmp_path)

        result = bm.ensure_bot_dependencies()
        assert result is False

    def test_returns_false_when_bun_missing(self, tmp_path, monkeypatch):
        """Should return False if Bun is not installed."""
        import dashboard.bot_manager as bm
        import shutil

        (tmp_path / "package.json").write_text('{"name": "test"}')
        monkeypatch.setattr(bm, "BOT_DIR", tmp_path)
        monkeypatch.setattr(shutil, "which", lambda x: None)

        result = bm.ensure_bot_dependencies()
        assert result is False

    def test_installs_dependencies_when_missing(self, tmp_path, monkeypatch):
        """Should install dependencies with Bun when node_modules is missing."""
        import dashboard.bot_manager as bm
        import shutil
        import subprocess

        (tmp_path / "package.json").write_text('{"name": "test"}')
        monkeypatch.setattr(bm, "BOT_DIR", tmp_path)
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/bun" if x == "bun" else None)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = bm.ensure_bot_dependencies()

        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == ["/usr/bin/bun", "install"]

    def test_uses_frozen_bun_lockfile_when_present(self, tmp_path, monkeypatch):
        """Should use --frozen-lockfile when a Bun lockfile exists."""
        import dashboard.bot_manager as bm
        import shutil
        import subprocess

        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "bun.lock").write_text("")
        monkeypatch.setattr(bm, "BOT_DIR", tmp_path)
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/bun" if x == "bun" else None)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = MagicMock(return_value=mock_result)
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = bm.ensure_bot_dependencies()

        assert result is True
        assert mock_run.call_args.args[0] == ["/usr/bin/bun", "install", "--frozen-lockfile"]

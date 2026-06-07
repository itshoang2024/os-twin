"""Tests for dashboard/tasks.py — startup_all initialization."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import dashboard.global_state as global_state
import dashboard.tasks as tasks_module


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset global_state between tests."""
    old_store = global_state.store
    old_planning = getattr(global_state, "planning_store", None)
    old_tunnel = getattr(global_state, "tunnel_url", None)
    global_state.store = None
    global_state.planning_store = None
    global_state.tunnel_url = None
    yield
    global_state.store = old_store
    global_state.planning_store = old_planning
    global_state.tunnel_url = old_tunnel


@pytest.fixture
def mock_dirs(tmp_path):
    """Set up isolated directories for tasks module."""
    warrooms = tmp_path / ".war-rooms"
    warrooms.mkdir()
    agents = tmp_path / ".agents"
    agents.mkdir()
    plans = agents / "plans"
    plans.mkdir()
    roles = agents / "roles"
    roles.mkdir()

    orig_warrooms = tasks_module.WARROOMS_DIR
    orig_agents = tasks_module.AGENTS_DIR
    orig_plans = tasks_module.PLANS_DIR

    tasks_module.WARROOMS_DIR = warrooms
    tasks_module.AGENTS_DIR = agents
    tasks_module.PLANS_DIR = plans

    yield tmp_path

    tasks_module.WARROOMS_DIR = orig_warrooms
    tasks_module.AGENTS_DIR = orig_agents
    tasks_module.PLANS_DIR = orig_plans


class TestStartupAll:
    """Tests for startup_all() initialization logic."""

    @pytest.mark.asyncio
    async def test_initializes_planning_store(self, mock_dirs):
        """startup_all should initialize global_state.planning_store."""
        mock_planning_cls = MagicMock()
        mock_planning_instance = MagicMock()
        mock_planning_cls.return_value = mock_planning_instance

        with patch("dashboard.tasks.poll_war_rooms", new_callable=AsyncMock), \
             patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", side_effect=RuntimeError("skip store")):
            await tasks_module.startup_all()

        assert global_state.planning_store is mock_planning_instance

    @pytest.mark.asyncio
    async def test_initializes_ostwin_store(self, mock_dirs):
        """startup_all should initialize global_state.store."""
        mock_store = MagicMock()
        mock_store.zvec_dir = mock_dirs / ".zvec"
        mock_store.zvec_dir.mkdir(exist_ok=True)

        mock_planning_cls = MagicMock(return_value=MagicMock())

        with patch("dashboard.tasks.poll_war_rooms", new_callable=AsyncMock), \
             patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", return_value=mock_store), \
             patch("dashboard.routes.roles.sync_roles_from_disk", return_value={"synced": []}):
            await tasks_module.startup_all()

        assert global_state.store is mock_store
        mock_store.ensure_collections.assert_called_once()
        mock_store.sync_from_disk.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_ostwin_store_init_failure(self, mock_dirs):
        """If OSTwinStore fails, store should be set to None."""
        mock_planning_cls = MagicMock(return_value=MagicMock())

        with patch("dashboard.tasks.poll_war_rooms", new_callable=AsyncMock), \
             patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", side_effect=RuntimeError("store init failed")):
            await tasks_module.startup_all()

        assert global_state.store is None

    @pytest.mark.asyncio
    async def test_starts_ngrok_tunnel_when_token_set(self, mock_dirs, monkeypatch):
        """startup_all should start ngrok when NGROK_AUTHTOKEN is set."""
        monkeypatch.setenv("NGROK_AUTHTOKEN", "fake-token")
        monkeypatch.setenv("DASHBOARD_PORT", "3366")
        monkeypatch.delenv("NGROK_DOMAIN", raising=False)

        mock_start = AsyncMock(return_value="https://tunnel.ngrok.io")
        mock_planning_cls = MagicMock(return_value=MagicMock())

        with patch("dashboard.tasks.poll_war_rooms", new_callable=AsyncMock), \
             patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", side_effect=RuntimeError("skip")), \
             patch("dashboard.tunnel.start_tunnel", mock_start), \
             patch("dashboard.notify.send_message", new_callable=AsyncMock):
            await tasks_module.startup_all()

        mock_start.assert_awaited_once_with(3366, "fake-token", None)
        assert global_state.tunnel_url == "https://tunnel.ngrok.io"

    @pytest.mark.asyncio
    async def test_skips_ngrok_when_no_token(self, mock_dirs, monkeypatch):
        """startup_all should skip ngrok when NGROK_AUTHTOKEN is not set."""
        monkeypatch.delenv("NGROK_AUTHTOKEN", raising=False)
        mock_planning_cls = MagicMock(return_value=MagicMock())

        with patch("dashboard.tasks.poll_war_rooms", new_callable=AsyncMock), \
             patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", side_effect=RuntimeError("skip")):
            await tasks_module.startup_all()

        assert global_state.tunnel_url is None

    @pytest.mark.asyncio
    async def test_skips_ngrok_when_disabled(self, mock_dirs, monkeypatch):
        """startup_all should skip ngrok when OSTWIN_NGROK_ENABLED=false."""
        monkeypatch.setenv("NGROK_AUTHTOKEN", "fake-token")
        monkeypatch.setenv("OSTWIN_NGROK_ENABLED", "false")
        mock_start = AsyncMock(return_value="https://tunnel.ngrok.io")
        mock_planning_cls = MagicMock(return_value=MagicMock())

        with patch("dashboard.tasks.poll_war_rooms", new_callable=AsyncMock), \
             patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", side_effect=RuntimeError("skip")), \
             patch("dashboard.tunnel.start_tunnel", mock_start):
            await tasks_module.startup_all()

        mock_start.assert_not_awaited()
        assert global_state.tunnel_url is None

    @pytest.mark.asyncio
    async def test_creates_poll_war_rooms_task(self, mock_dirs):
        """startup_all should create the poll_war_rooms background task."""
        created_tasks = []
        original_create_task = asyncio.create_task

        def capture_create_task(coro, **kwargs):
            task = original_create_task(coro, **kwargs)
            created_tasks.append(task)
            return task

        mock_planning_cls = MagicMock(return_value=MagicMock())

        with patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", side_effect=RuntimeError("skip")), \
             patch("asyncio.create_task", side_effect=capture_create_task):
            await tasks_module.startup_all()

        # At least one task should have been created (poll_war_rooms)
        assert len(created_tasks) >= 1

        # Clean up
        for t in created_tasks:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_ngrok_failure_handled_gracefully(self, mock_dirs, monkeypatch):
        """If ngrok tunnel fails, startup_all should not crash."""
        monkeypatch.setenv("NGROK_AUTHTOKEN", "fake-token")
        monkeypatch.setenv("DASHBOARD_PORT", "3366")
        mock_planning_cls = MagicMock(return_value=MagicMock())

        with patch("dashboard.tasks.poll_war_rooms", new_callable=AsyncMock), \
             patch("dashboard.planning_thread_store.PlanningThreadStore", mock_planning_cls), \
             patch("dashboard.tasks.OSTwinStore", side_effect=RuntimeError("skip")), \
             patch("dashboard.tunnel.start_tunnel", new_callable=AsyncMock,
                   side_effect=RuntimeError("ngrok error")):
            # Should NOT raise
            await tasks_module.startup_all()

        assert global_state.tunnel_url is None

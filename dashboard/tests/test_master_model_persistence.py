"""
TDD tests for master-model PERSISTENCE.

The current implementation only mutates the in-memory ``_master_config``
singleton in ``dashboard.master_agent``.  That means whatever the user
picks in the settings panel is **lost** the moment the dashboard
process restarts.

These tests describe the desired behaviour:

1. ``PUT /api/settings/master-model`` writes the chosen model into
   ``.agents/config.json`` under ``runtime.master_agent_model`` (the
   field already declared on :class:`RuntimeSettings`) using the
   ``provider/model`` combined format that ``set_master_model`` already
   knows how to parse.
2. After the in-memory singleton is wiped (simulating a dashboard
   restart), ``GET /api/settings/master-model`` must still return the
   persisted value -- but **only** if a startup hook re-hydrates the
   singleton from disk.  We expose that hook as
   ``master_agent.load_persisted_master_model()`` and assert it loads
   the value back.
3. Round-trip: what is stored on disk == what
   :func:`master_agent.get_master_config` reports after re-hydration.

The tests are intentionally hermetic: each test points the global
:class:`SettingsResolver` at a temporary directory so we never touch
the developer's real ``~/.ostwin/.agents/config.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dashboard.api import app
from dashboard.auth import get_current_user


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_config_resolver(tmp_path, monkeypatch):
    """Point the global SettingsResolver at a tmp .agents/config.json.

    Yields the Path to the config file so tests can read/write it
    directly and assert on the on-disk state.
    """
    from dashboard.lib.settings import resolver as resolver_mod

    config_path = tmp_path / ".agents" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a fresh resolver bound to the tmp path and install it as the
    # singleton.  reset_settings_resolver() afterwards restores normal
    # behaviour for subsequent tests.
    fresh = resolver_mod.SettingsResolver(config_path=config_path)
    monkeypatch.setattr(resolver_mod, "_resolver_instance", fresh)

    yield config_path

    resolver_mod.reset_settings_resolver()


@pytest.fixture(autouse=True)
def reset_master_state():
    """Reset _master_config singleton before/after each test."""
    from dashboard import master_agent as ma

    saved = (
        ma._master_config.model,
        ma._master_config.provider,
        ma._master_config.temperature,
        ma._master_config.max_tokens,
        ma._master_config.is_explicit,
    )
    yield
    (
        ma._master_config.model,
        ma._master_config.provider,
        ma._master_config.temperature,
        ma._master_config.max_tokens,
        ma._master_config.is_explicit,
    ) = saved


@pytest.fixture
def client():
    """Authenticated test client (auth bypassed)."""
    app.dependency_overrides[get_current_user] = lambda: {"username": "test-user"}
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# ── 1. PUT persists to disk ─────────────────────────────────────────────────


class TestPutPersistsToConfigJson:
    """PUT /api/settings/master-model must write to .agents/config.json."""

    def test_put_writes_combined_provider_model_to_runtime_namespace(
        self, client, tmp_config_resolver
    ):
        resp = client.put(
            "/api/settings/master-model",
            json={"model": "gpt-4o", "provider": "openai"},
        )
        assert resp.status_code == 200

        # The file MUST exist after a successful PUT.
        assert tmp_config_resolver.exists(), (
            "PUT /api/settings/master-model did not create .agents/config.json"
        )
        on_disk = json.loads(tmp_config_resolver.read_text())

        # Stored under runtime.master_agent_model in the combined "provider/model" format
        # which is exactly what set_master_model() already parses.
        runtime = on_disk.get("runtime") or {}
        assert runtime.get("master_agent_model") == "openai/gpt-4o", (
            f"expected runtime.master_agent_model='openai/gpt-4o', got: {runtime}"
        )

    def test_put_writes_plain_model_when_no_provider(
        self, client, tmp_config_resolver
    ):
        resp = client.put(
            "/api/settings/master-model",
            json={"model": "custom-model"},
        )
        assert resp.status_code == 200

        on_disk = json.loads(tmp_config_resolver.read_text())
        runtime = on_disk.get("runtime") or {}
        # No provider -> store the bare model id (set_master_model accepts this).
        assert runtime.get("master_agent_model") == "custom-model"

    def test_put_infers_google_provider_for_bare_gemini_model(
        self, client, tmp_config_resolver
    ):
        resp = client.put(
            "/api/settings/master-model",
            json={"model": "gemini-3.1-pro"},
        )
        assert resp.status_code == 200

        on_disk = json.loads(tmp_config_resolver.read_text())
        runtime = on_disk.get("runtime") or {}
        assert runtime.get("master_agent_model") == "google/gemini-3.1-pro"

    def test_put_with_slash_prefix_normalises_to_provider_slash_model(
        self, client, tmp_config_resolver
    ):
        """When the model string itself carries a provider prefix, the
        stored value should be the same canonical ``provider/model`` form
        so that loading it back yields the same parsed components."""
        resp = client.put(
            "/api/settings/master-model",
            json={"model": "openai/gpt-4-turbo"},
        )
        assert resp.status_code == 200

        on_disk = json.loads(tmp_config_resolver.read_text())
        runtime = on_disk.get("runtime") or {}
        assert runtime.get("master_agent_model") == "openai/gpt-4-turbo"

    def test_put_overwrites_previous_value(self, client, tmp_config_resolver):
        client.put(
            "/api/settings/master-model",
            json={"model": "gpt-4o", "provider": "openai"},
        )
        client.put(
            "/api/settings/master-model",
            json={"model": "claude-3-opus", "provider": "anthropic"},
        )

        on_disk = json.loads(tmp_config_resolver.read_text())
        runtime = on_disk.get("runtime") or {}
        assert runtime.get("master_agent_model") == "anthropic/claude-3-opus"

    def test_put_does_not_clobber_unrelated_runtime_keys(
        self, client, tmp_config_resolver
    ):
        # Seed the file with another runtime-related setting so we can
        # prove the PUT doesn't blow it away.
        tmp_config_resolver.write_text(
            json.dumps(
                {
                    "manager": {
                        "poll_interval_seconds": 17,
                        "max_concurrent_rooms": 5,
                    }
                }
            )
        )

        resp = client.put(
            "/api/settings/master-model",
            json={"model": "gpt-4o", "provider": "openai"},
        )
        assert resp.status_code == 200

        on_disk = json.loads(tmp_config_resolver.read_text())
        manager = on_disk.get("manager") or {}
        assert manager.get("poll_interval_seconds") == 17
        assert manager.get("max_concurrent_rooms") == 5


# ── 2. Startup hook reloads the persisted value ─────────────────────────────


class TestStartupReloadsPersistedModel:
    """A startup hook reloads runtime.master_agent_model into the singleton."""

    def test_load_persisted_master_model_helper_exists(self):
        """master_agent must expose a callable that re-hydrates from disk."""
        from dashboard import master_agent as ma

        assert hasattr(ma, "load_persisted_master_model"), (
            "master_agent must expose load_persisted_master_model() so "
            "dashboard.tasks.startup_all can rehydrate the singleton "
            "after a process restart"
        )
        assert callable(ma.load_persisted_master_model)

    def test_load_applies_persisted_value_to_singleton(self, tmp_config_resolver):
        from dashboard import master_agent as ma

        # Simulate a previously persisted setting.
        tmp_config_resolver.write_text(
            json.dumps({"runtime": {"master_agent_model": "anthropic/claude-3-opus"}})
        )

        # Force defaults so we can prove the load mutated the singleton.
        ma._master_config.model = ma.DEFAULT_MODEL
        ma._master_config.provider = ma.DEFAULT_PROVIDER
        ma._master_config.is_explicit = False

        ma.load_persisted_master_model()

        cfg = ma.get_master_config()
        assert cfg.model == "claude-3-opus"
        assert cfg.provider == "anthropic"

    def test_load_with_no_persisted_value_keeps_defaults(self, tmp_config_resolver):
        from dashboard import master_agent as ma

        tmp_config_resolver.write_text(json.dumps({}))  # empty config
        ma._master_config.model = ma.DEFAULT_MODEL
        ma._master_config.provider = ma.DEFAULT_PROVIDER
        ma._master_config.is_explicit = False

        ma.load_persisted_master_model()

        cfg = ma.get_master_config()
        assert cfg.model == ma.DEFAULT_MODEL
        assert cfg.provider == ma.DEFAULT_PROVIDER

    def test_load_handles_missing_config_file_gracefully(
        self, tmp_config_resolver
    ):
        """If config.json doesn't exist yet, load must NOT crash."""
        from dashboard import master_agent as ma

        if tmp_config_resolver.exists():
            tmp_config_resolver.unlink()

        # Must not raise.
        ma.load_persisted_master_model()


# ── 3. End-to-end: PUT → restart → GET round-trip ───────────────────────────


class TestRoundTripAcrossRestart:
    """The model returned to clients matches what's persisted on disk."""

    def test_get_returns_persisted_value_after_singleton_reset(
        self, client, tmp_config_resolver
    ):
        """Simulates: user picks a model → dashboard restarts → user opens
        settings page again → must see the same model."""
        from dashboard import master_agent as ma

        # 1. User saves a model via the API.
        resp = client.put(
            "/api/settings/master-model",
            json={"model": "claude-3-opus", "provider": "anthropic"},
        )
        assert resp.status_code == 200

        # 2. Dashboard "restarts" — singleton resets to defaults.
        ma._master_config.model = ma.DEFAULT_MODEL
        ma._master_config.provider = ma.DEFAULT_PROVIDER
        ma._master_config.is_explicit = False
        ma._session_registry.clear()

        # 3. Startup hook re-hydrates from disk.
        ma.load_persisted_master_model()

        # 4. GET must reflect the originally-saved value.
        resp = client.get("/api/settings/master-model")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "claude-3-opus"
        assert data["provider"] == "anthropic"

    def test_master_agent_uses_same_model_as_persisted_settings(
        self, client, tmp_config_resolver
    ):
        """The model the master agent will actually use must equal the one
        the settings API reports as persisted."""
        from dashboard import master_agent as ma

        client.put(
            "/api/settings/master-model",
            json={"model": "gpt-4o", "provider": "openai"},
        )

        # Restart-and-reload cycle.
        ma._master_config.model = ma.DEFAULT_MODEL
        ma._master_config.provider = ma.DEFAULT_PROVIDER
        ma._master_config.is_explicit = False
        ma.load_persisted_master_model()

        # What the master agent will send to OpenCode:
        resolved_model, resolved_provider = ma.get_model_and_provider()

        # What the API exposes to the FE:
        api_resp = client.get("/api/settings/master-model").json()

        assert resolved_model == api_resp["model"] == "gpt-4o"
        assert resolved_provider == api_resp["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_master_chat_sends_persisted_model_to_opencode(
        self, tmp_config_resolver
    ):
        """The persisted setting must reach the actual OpenCode chat payload."""
        from dashboard import master_agent as ma
        from dashboard.llm_client import ChatMessage

        tmp_config_resolver.write_text(
            json.dumps({"runtime": {"master_agent_model": "google/gemini-3.1-pro"}})
        )
        ma._master_config.model = ma.DEFAULT_MODEL
        ma._master_config.provider = ma.DEFAULT_PROVIDER
        ma._master_config.is_explicit = False

        ma.load_persisted_master_model()

        mock_client = MagicMock()
        mock_client.session.create = AsyncMock(return_value=MagicMock(id="sess-model"))
        mock_client.post = AsyncMock()

        with (
            patch("dashboard.master_agent.get_opencode_client", return_value=mock_client),
            patch(
                "dashboard.master_agent.read_session_text",
                new_callable=AsyncMock,
                return_value="ok",
            ),
        ):
            await ma.master_chat(
                [ChatMessage(role="user", content="hello")],
                conversation_id="persisted-model-chat",
            )

        post_kwargs = mock_client.post.call_args.kwargs
        body = post_kwargs["body"]
        assert body["model"]["modelID"] == "gemini-3.1-pro"
        assert body["model"]["providerID"] == "google"

    @pytest.mark.asyncio
    async def test_fresh_install_sends_opencode_style_provider_to_chat(
        self, tmp_config_resolver
    ):
        """Regression: on a fresh install (no persisted runtime model), the
        provider sent to OpenCode must be the OpenCode-style ``google`` —
        not the legacy direct-LLM ``google-vertex``. Without this, every
        connector ``/api/chat`` call on a brand-new dashboard targets a
        provider OpenCode doesn't know about until the user opens settings
        and explicitly saves a model."""
        from dashboard import master_agent as ma
        from dashboard.llm_client import ChatMessage

        # Empty config — nothing persisted.
        tmp_config_resolver.write_text(json.dumps({}))
        ma._master_config.model = ma.DEFAULT_MODEL
        ma._master_config.provider = ma.DEFAULT_PROVIDER
        ma._master_config.is_explicit = False

        ma.load_persisted_master_model()  # no-op, but mirrors the startup path

        mock_client = MagicMock()
        mock_client.session.create = AsyncMock(return_value=MagicMock(id="sess-fresh"))
        mock_client.post = AsyncMock()

        with (
            patch("dashboard.master_agent.get_opencode_client", return_value=mock_client),
            patch(
                "dashboard.master_agent.read_session_text",
                new_callable=AsyncMock,
                return_value="ok",
            ),
        ):
            await ma.master_chat(
                [ChatMessage(role="user", content="hello")],
                conversation_id="fresh-install-chat",
            )

        body = mock_client.post.call_args.kwargs["body"]
        assert body["model"]["providerID"] == "google"
        assert body["model"]["providerID"] != "google-vertex"

    @pytest.mark.asyncio
    async def test_stale_google_vertex_runtime_is_normalised_for_chat(
        self, tmp_config_resolver
    ):
        """Regression: if a previously persisted value still has the legacy
        ``google-vertex`` prefix (e.g. from before this fix), the chat body
        sent to OpenCode must still use ``google``."""
        from dashboard import master_agent as ma
        from dashboard.llm_client import ChatMessage

        ma._master_config.model = "gemini-3.1-pro-preview"
        ma._master_config.provider = "google-vertex"  # stale legacy value
        ma._master_config.is_explicit = True

        mock_client = MagicMock()
        mock_client.session.create = AsyncMock(return_value=MagicMock(id="sess-legacy"))
        mock_client.post = AsyncMock()

        with (
            patch("dashboard.master_agent.get_opencode_client", return_value=mock_client),
            patch(
                "dashboard.master_agent.read_session_text",
                new_callable=AsyncMock,
                return_value="ok",
            ),
        ):
            await ma.master_chat(
                [ChatMessage(role="user", content="hello")],
                conversation_id="legacy-vertex-chat",
            )

        body = mock_client.post.call_args.kwargs["body"]
        assert body["model"]["providerID"] == "google"


# ── 4. Lifespan startup hydrates before background tasks ───────────────────


class TestStartupHydration:
    @pytest.mark.asyncio
    async def test_lifespan_hydrates_persisted_model_before_background_startup(
        self, tmp_config_resolver, monkeypatch
    ):
        """Early requests after startup must not see the hardcoded default.

        ``startup_all`` intentionally runs as a background task, so the
        persisted master model must be loaded in the lifespan path before
        request handling can begin.
        """
        from dashboard import api as api_mod
        from dashboard import master_agent as ma

        tmp_config_resolver.write_text(
            json.dumps({"runtime": {"master_agent_model": "openai/gpt-4o"}})
        )

        ma._master_config.model = ma.DEFAULT_MODEL
        ma._master_config.provider = ma.DEFAULT_PROVIDER
        ma._master_config.is_explicit = False

        async def fake_startup_all():
            return None

        class DummyKnowledgeService:
            def start_background(self):
                return None

        async def fake_memory_pool_startup():
            return None

        monkeypatch.setattr(api_mod, "startup_all", fake_startup_all)
        monkeypatch.setattr(api_mod, "_mcp_lifespan_app", None)
        monkeypatch.setattr(api_mod, "_shutdown_app", AsyncMock())

        import dashboard.routes.knowledge as knowledge_routes
        import dashboard.routes.memory_mcp as memory_mcp_routes

        monkeypatch.setattr(
            knowledge_routes,
            "_get_service",
            lambda: DummyKnowledgeService(),
        )
        monkeypatch.setattr(
            memory_mcp_routes,
            "startup_knowledge",
            fake_memory_pool_startup,
        )

        async with api_mod.app_lifespan(api_mod.app):
            model, provider = ma.get_model_and_provider()

        assert model == "gpt-4o"
        assert provider == "openai"

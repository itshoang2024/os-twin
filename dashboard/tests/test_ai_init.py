"""Unit tests for the public helpers exposed by ``dashboard.ai`` (``__init__.py``).

Focus: the embedder-label helper that powers monitor records.  The contract is
explicitly simple after the SentenceTransformers removal — the label is the
bare model name (no ``ollama/`` or ``google/`` prefix), because the *provider*
is tracked separately and the model name itself is what humans search for.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


# Mock google.genai before dashboard.ai imports (matches other test files).
sys.modules.setdefault("google.genai", MagicMock())
sys.modules.setdefault("google.genai.types", MagicMock())


class TestEmbedderModel:
    """``dashboard.ai._embedder_model`` resolves the label written to AI Monitor
    records.  It must return the *bare* model name with no provider prefix —
    that was the explicit ask after the initial fix used ``ollama/<model>``."""

    def test_returns_model_name_attribute(self):
        from dashboard.ai import _embedder_model

        embedder = MagicMock(spec=["model_name"])
        embedder.model_name = "qwen3-embedding:0.6b"

        assert _embedder_model(embedder) == "qwen3-embedding:0.6b"

    def test_falls_back_to_model_attribute(self):
        from dashboard.ai import _embedder_model

        # No ``model_name`` attribute — the EmbeddingClient base uses ``.model``.
        embedder = MagicMock(spec=["model"])
        embedder.model = "gemini-embedding-001"

        assert _embedder_model(embedder) == "gemini-embedding-001"

    def test_model_name_takes_precedence_over_model(self):
        from dashboard.ai import _embedder_model

        embedder = MagicMock(spec=["model_name", "model"])
        embedder.model_name = "wrapper-label"
        embedder.model = "underlying-model"

        assert _embedder_model(embedder) == "wrapper-label"

    def test_empty_model_name_falls_through_to_model(self):
        from dashboard.ai import _embedder_model

        embedder = MagicMock(spec=["model_name", "model"])
        embedder.model_name = ""  # falsy
        embedder.model = "underlying-model"

        # The implementation uses ``or`` — empty string falls through to ``.model``.
        assert _embedder_model(embedder) == "underlying-model"

    def test_returns_unknown_when_no_attributes(self):
        from dashboard.ai import _embedder_model

        class Bare:
            pass

        assert _embedder_model(Bare()) == "unknown"

    def test_label_has_no_provider_prefix(self):
        """Regression guard: an earlier fix prepended ``ollama/`` — the user
        explicitly asked for the bare model name (the provider is tracked
        elsewhere, and the prefix would have to be re-stripped by every
        consumer).
        """
        from dashboard.ai import _embedder_model

        embedder = MagicMock(spec=["model_name"])
        embedder.model_name = "qwen3-embedding:0.6b"

        label = _embedder_model(embedder)
        assert "/" not in label
        assert not label.startswith("ollama")
        assert not label.startswith("google")


class TestDetectEmbedDefaults:
    """``_detect_embed_model`` / ``_detect_embed_provider`` should fall back
    to the qwen3 / ollama defaults when settings + env vars are absent.
    """

    def test_detect_embed_model_defaults_to_qwen3(self, monkeypatch):
        # Stub the settings resolver to short-circuit through except: pass.
        import dashboard.ai as ai_mod

        monkeypatch.delenv("OSTWIN_KNOWLEDGE_EMBED_MODEL", raising=False)

        def boom_resolver():
            raise RuntimeError("no settings")

        monkeypatch.setattr(
            "dashboard.lib.settings.resolver.get_settings_resolver",
            boom_resolver,
        )

        assert ai_mod._detect_embed_model() == "qwen3-embedding:0.6b"

    def test_detect_embed_provider_defaults_to_ollama(self, monkeypatch):
        import dashboard.ai as ai_mod

        monkeypatch.delenv("OSTWIN_KNOWLEDGE_EMBED_PROVIDER", raising=False)

        def boom_resolver():
            raise RuntimeError("no settings")

        monkeypatch.setattr(
            "dashboard.lib.settings.resolver.get_settings_resolver",
            boom_resolver,
        )

        assert ai_mod._detect_embed_provider() == "ollama"

    def test_detect_embed_model_honors_env_var(self, monkeypatch):
        import dashboard.ai as ai_mod

        monkeypatch.setenv("OSTWIN_KNOWLEDGE_EMBED_MODEL", "custom-embed")

        def boom_resolver():
            raise RuntimeError("no settings")

        monkeypatch.setattr(
            "dashboard.lib.settings.resolver.get_settings_resolver",
            boom_resolver,
        )

        assert ai_mod._detect_embed_model() == "custom-embed"

    def test_detect_embed_provider_honors_env_var(self, monkeypatch):
        import dashboard.ai as ai_mod

        monkeypatch.setenv("OSTWIN_KNOWLEDGE_EMBED_PROVIDER", "google")

        def boom_resolver():
            raise RuntimeError("no settings")

        monkeypatch.setattr(
            "dashboard.lib.settings.resolver.get_settings_resolver",
            boom_resolver,
        )

        assert ai_mod._detect_embed_provider() == "google"

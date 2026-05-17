"""AI Gateway configuration.

Reads from the dashboard settings system (``MasterSettings``) when
available. Falls back to environment variables when running standalone
(e.g. the memory MCP server without the dashboard).

Config is cached after first load.  Call ``reset_config()`` to force
a re-read (done automatically when ``PUT /api/settings/providers``
or ``PUT /api/settings/ai`` is called on the dashboard).

Provider names follow ``llm_client.py`` conventions:
  - ``"google"``       — Gemini AI Studio (consumer API key)
  - ``"google-vertex"``— Vertex AI (ADC / service account)
  - ``"openai"``       — OpenAI
  - ``"anthropic"``    — Anthropic (via OpenAI-compatible endpoint)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AIConfig:
    """Resolved AI gateway configuration.

    Provider values follow ``llm_client.py`` naming (``"google"``,
    ``"google-vertex"``, ``"openai"``, etc.) — NOT litellm prefixes.
    """

    # Provider for llm_client.create_client()
    provider: str = "google"

    # Completion models (bare names — no provider prefix)
    completion_model: str = "gemini-3-flash-preview"
    knowledge_model: Optional[str] = None  # for knowledge graph (e.g. Claude)
    memory_model: Optional[str] = None  # for memory analysis

    # Embedding models
    cloud_embedding_model: str = "text-embedding-005"
    local_embedding_model: str = "qwen3-embedding:0.6b"

    # Runtime
    timeout: int = 60
    max_retries: int = 2

    def full_model(self, purpose: Optional[str] = None) -> str:
        """Return the bare model name for the given purpose.

        Args:
            purpose: Optional purpose hint (``"knowledge"``, ``"memory"``).
                Selects a per-purpose model override if configured.

        Returns:
            Bare model name (e.g. ``"gemini-3-flash-preview"``).
            Passed directly to ``llm_client.create_client(model=...)``.
        """
        if purpose == "knowledge" and self.knowledge_model:
            return self.knowledge_model
        elif purpose == "memory" and self.memory_model:
            return self.memory_model
        return self.completion_model

    def display_model(self, purpose: Optional[str] = None) -> str:
        """Return ``"provider/model"`` for display in API responses."""
        model = self.full_model(purpose)
        return f"{self.provider}/{model}"

    def full_cloud_embedding_model(self) -> str:
        """Return the cloud embedding model name (bare, no prefix)."""
        return self.cloud_embedding_model


# ---------------------------------------------------------------------------
# Singleton cache
# ---------------------------------------------------------------------------

_config: Optional[AIConfig] = None


def get_config() -> AIConfig:
    """Load config from settings system (or env fallback).  Cached."""
    global _config
    if _config is not None:
        return _config

    try:
        _config = _load_from_settings()
        logger.info("AI config loaded from settings system")
    except Exception as exc:
        logger.info("Settings system unavailable (%s), falling back to env vars", exc)
        _config = _load_from_env()

    return _config


def reset_config() -> None:
    """Invalidate cached config.  Next ``get_config()`` re-reads."""
    global _config
    _config = None


# ---------------------------------------------------------------------------
# Provider mapping helpers
# ---------------------------------------------------------------------------

# Maps MasterSettings deployment_mode / legacy names → llm_client provider keys
_PROVIDER_MAP = {
    "vertex_ai": "google-vertex",
    "vertex": "google-vertex",
    "google-vertex": "google-vertex",
    "gemini": "google",
    "google": "google",
    "google-genai": "google",
    "openai": "openai",
    "anthropic": "anthropic",
}


def _map_provider(raw: str) -> str:
    """Normalise a provider string to a ``llm_client.py`` key."""
    return _PROVIDER_MAP.get(raw.lower(), raw.lower())


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_from_settings() -> AIConfig:
    """Read from ``MasterSettings.providers`` + ``MasterSettings.ai``."""
    from dashboard.lib.settings import SettingsResolver

    resolver = SettingsResolver()
    settings = resolver.get_master_settings()

    # --- providers.google ---
    google = settings.providers.google if settings.providers else None
    if not google or not google.enabled:
        raise ValueError("Google provider not configured or disabled in settings")

    is_vertex = (google.deployment_mode or "").lower() == "vertex"
    provider = "google-vertex" if is_vertex else "google"

    # --- ai namespace ---
    ai_ns = getattr(settings, "ai", None)

    completion_model = (
        (ai_ns.completion_model if ai_ns and ai_ns.completion_model else None)
        or google.default_model
        or "gemini-3.1-flash-lite"
    )
    knowledge_model = ai_ns.knowledge_model if ai_ns else None
    memory_model = ai_ns.memory_model if ai_ns else None
    cloud_embedding = (
        (ai_ns.cloud_embedding_model if ai_ns and ai_ns.cloud_embedding_model else None)
        or (google.embedding_model if hasattr(google, "embedding_model") else None)
        or "text-embedding-005"
    )
    local_embedding = (
        ai_ns.local_embedding_model if ai_ns else None
    ) or "qwen3-embedding:0.6b"
    timeout = (
        ai_ns.timeout_seconds if ai_ns and hasattr(ai_ns, "timeout_seconds") else 60
    )
    max_retries = ai_ns.max_retries if ai_ns and hasattr(ai_ns, "max_retries") else 2

    return AIConfig(
        provider=provider,
        completion_model=completion_model,
        knowledge_model=knowledge_model,
        memory_model=memory_model,
        cloud_embedding_model=cloud_embedding,
        local_embedding_model=local_embedding,
        timeout=timeout,
        max_retries=max_retries,
    )


def _load_from_env() -> AIConfig:
    """Fallback: read from environment variables.

    These are typically set by ``_sync_vertex_env()`` in the settings route,
    so even without the dashboard the values are correct.
    """
    is_vertex = bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    provider = "google-vertex" if is_vertex else "google"

    return AIConfig(
        provider=provider,
        completion_model=os.environ.get("LLM_MODEL", "gemini-3-flash-preview"),
        cloud_embedding_model=os.environ.get(
            "LLM_CLOUD_EMBEDDING_MODEL", "text-embedding-005"
        ),
        local_embedding_model=os.environ.get(
            "LLM_LOCAL_EMBEDDING_MODEL", "qwen3-embedding:0.6b"
        ),
        timeout=int(os.environ.get("LLM_TIMEOUT", "60")),
        max_retries=int(os.environ.get("LLM_MAX_RETRIES", "2")),
    )

"""Unified AI gateway for the dashboard.

Provides completion via :mod:`dashboard.llm_client` (multi-provider native
SDK abstraction), and embedding via the centralized
:func:`dashboard.llm_client.create_embedding_client`.

Usage::

    from dashboard.ai import get_completion, get_embedding

    # Completion (prompt → text)
    text = get_completion("Extract keywords from this text...")

    # Completion with purpose-specific model
    text = get_completion(prompt, purpose="knowledge")

    # Completion with function calling
    result = complete(messages=msgs, tools=tool_defs)
    if result.tool_calls:
        ...  # handle tool calls

    # Embedding (text → vector)
    vectors = get_embedding(["some text"])
"""

from .completion import complete, CompletionResult
from .config import get_config, reset_config, AIConfig
from .errors import AIError, AIAuthError, AITimeoutError, AIQuotaError


# Lazy singleton — delegates to the centralized EmbeddingClient
_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from dashboard.llm_client import create_embedding_client

        _embedder = create_embedding_client(
            model=_detect_embed_model(),
            provider=_detect_embed_provider(),
        )
    return _embedder


def _detect_embed_model(purpose: str = "knowledge") -> str:
    """Resolve embedding model from settings or env var.

    When ``purpose="memory"``, checks ``MemorySettings.embedding_model`` first.
    Falls through to knowledge config if not set (backward compat).
    """
    try:
        from dashboard.lib.settings.resolver import get_settings_resolver

        resolver = get_settings_resolver()
        master = resolver.get_master_settings()
        # Memory-specific override
        if purpose == "memory" and hasattr(master, "memory") and master.memory:
            mem_model = getattr(master.memory, "embedding_model", "")
            if mem_model:
                return mem_model
        # Knowledge config (shared default)
        if hasattr(master, "knowledge") and master.knowledge:
            know_cfg = master.knowledge
            if hasattr(know_cfg, "knowledge_embedding_model") and know_cfg.knowledge_embedding_model:
                return know_cfg.knowledge_embedding_model
    except Exception:
        pass
    return os.environ.get("OSTWIN_KNOWLEDGE_EMBED_MODEL", "qwen3-embedding:0.6b")


def _detect_embed_provider(purpose: str = "knowledge") -> str:
    """Resolve embedding provider from settings or env var.

    When ``purpose="memory"``, checks ``MemorySettings.embedding_provider`` first.
    Falls through to knowledge config if not set (backward compat).
    """
    try:
        from dashboard.lib.settings.resolver import get_settings_resolver

        resolver = get_settings_resolver()
        master = resolver.get_master_settings()
        # Memory-specific override
        if purpose == "memory" and hasattr(master, "memory") and master.memory:
            mem_provider = getattr(master.memory, "embedding_backend", "") or getattr(master.memory, "embedding_provider", "")
            if mem_provider:
                return mem_provider
        # Knowledge config (shared default)
        if hasattr(master, "knowledge") and master.knowledge:
            know_cfg = master.knowledge
            if hasattr(know_cfg, "knowledge_embedding_backend") and know_cfg.knowledge_embedding_backend:
                return know_cfg.knowledge_embedding_backend
    except Exception:
        pass
    return os.environ.get("OSTWIN_KNOWLEDGE_EMBED_PROVIDER", "ollama")


def _detect_embed_compatible_url(purpose: str = "knowledge") -> str | None:
    """Resolve openai-compatible base URL from settings.

    When ``purpose="memory"``, checks ``MemorySettings.embedding_compatible_url``
    then ``MemorySettings.llm_compatible_url``.  For knowledge, checks
    ``KnowledgeSettings.knowledge_embedding_compatible_url``.
    """
    try:
        from dashboard.lib.settings.resolver import get_settings_resolver

        resolver = get_settings_resolver()
        master = resolver.get_master_settings()
        if purpose == "memory" and hasattr(master, "memory") and master.memory:
            url = getattr(master.memory, "embedding_compatible_url", "") or getattr(master.memory, "llm_compatible_url", "")
            if url:
                return url
        if hasattr(master, "knowledge") and master.knowledge:
            url = getattr(master.knowledge, "knowledge_embedding_compatible_url", "") or getattr(master.knowledge, "knowledge_llm_compatible_url", "")
            if url:
                return url
    except Exception:
        pass
    return None


def _detect_embed_compatible_key(purpose: str = "knowledge") -> str | None:
    """Resolve openai-compatible API key from settings.

    When ``purpose="memory"``, checks ``MemorySettings.embedding_compatible_key``
    then ``MemorySettings.llm_compatible_key``.  For knowledge, checks
    ``KnowledgeSettings.knowledge_embedding_compatible_key``.
    """
    try:
        from dashboard.lib.settings.resolver import get_settings_resolver

        resolver = get_settings_resolver()
        master = resolver.get_master_settings()
        if purpose == "memory" and hasattr(master, "memory") and master.memory:
            key = getattr(master.memory, "embedding_compatible_key", "") or getattr(master.memory, "llm_compatible_key", "")
            if key:
                return key
        if hasattr(master, "knowledge") and master.knowledge:
            key = getattr(master.knowledge, "knowledge_embedding_compatible_key", "") or getattr(master.knowledge, "knowledge_llm_compatible_key", "")
            if key:
                return key
    except Exception:
        pass
    return None


import os


def get_completion(
    prompt: str,
    **kwargs,
) -> str:
    """Simple prompt → text.  For callers that don't need tool_calls.

    Accepts the same keyword arguments as :func:`complete`.
    """
    result = complete(prompt, **kwargs)
    return result.text or ""


# Cache embedders by (provider, model) so different purposes get different clients
_embedder_cache: dict = {}


def _get_embedder_for(purpose: str = "knowledge"):
    """Get or create an embedder for the given purpose."""
    model = _detect_embed_model(purpose)
    provider = _detect_embed_provider(purpose)
    compatible_url = _detect_embed_compatible_url(purpose)
    compatible_key = _detect_embed_compatible_key(purpose)
    cache_key = (provider, model, compatible_url)
    if cache_key not in _embedder_cache:
        from dashboard.llm_client import create_embedding_client

        kwargs: dict = dict(model=model, provider=provider)
        if compatible_url:
            kwargs["base_url"] = compatible_url
        if compatible_key:
            kwargs["api_key"] = compatible_key

        _embedder_cache[cache_key] = create_embedding_client(**kwargs)
    return _embedder_cache[cache_key], provider, model


def get_embedding(
    texts: list[str],
    purpose: str = "knowledge",
    **kwargs,
) -> list[list[float]]:
    """Texts → vectors via the AI gateway.

    Args:
        texts: List of strings to embed.
        purpose: ``"memory"`` or ``"knowledge"``. Determines which embedding
            model is used (configured separately in Settings).

    Every call is recorded in the AI Monitor for observability.
    """
    import time as _time
    from .monitor import record_embedding

    embedder, _provider, _model = _get_embedder_for(purpose)
    _model_label = f"{_provider}/{_model}"

    t0 = _time.time()
    try:
        result = embedder.embed(texts)
        latency_ms = (_time.time() - t0) * 1000
        record_embedding(
            model=_model_label,
            text_count=len(texts),
            latency_ms=latency_ms,
        )
        return result
    except Exception as exc:
        latency_ms = (_time.time() - t0) * 1000
        record_embedding(
            model=_model_label,
            text_count=len(texts),
            latency_ms=latency_ms,
            success=False,
            error=str(exc),
        )
        raise


def _embedder_model(embedder) -> str:
    return getattr(embedder, "model_name", None) or getattr(embedder, "model", "unknown")


def embed(
    texts: list[str],
    **kwargs,
) -> list[list[float]]:
    """Alias for ``get_embedding`` — backward compatibility."""
    return get_embedding(texts, **kwargs)


def get_stats():
    """Return AI usage statistics."""
    from .monitor import get_stats as _get_stats

    return _get_stats()


def reset_stats():
    """Reset AI usage statistics."""
    from .monitor import reset_stats as _reset_stats

    return _reset_stats()


__all__ = [
    "get_completion",
    "get_embedding",
    "complete",
    "CompletionResult",
    "embed",
    "get_config",
    "reset_config",
    "AIConfig",
    "AIError",
    "AIAuthError",
    "AITimeoutError",
    "AIQuotaError",
    "get_stats",
    "reset_stats",
]

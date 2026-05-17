"""Multi-provider embedding wrapper with lazy model load.

Delegates to the centralized :func:`dashboard.llm_client.create_embedding_client`
factory, which supports ``ollama``, ``google`` (Gemini), and ``openai-compatible``
backends with class-level singleton caching and configurable output dimensions.

The provider is controlled by ``OSTWIN_KNOWLEDGE_EMBED_PROVIDER`` env var
or ``MasterSettings.knowledge.embedding_backend`` (via ``KnowledgeService``).

Importing this module is essentially free — no heavy deps at module load.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from dashboard.knowledge.config import EMBEDDING_DIMENSION, EMBEDDING_MODEL, EMBEDDING_PROVIDER

logger = logging.getLogger(__name__)


class KnowledgeEmbedder:
    """Multi-provider embedding helper.

    Thin wrapper around :func:`dashboard.llm_client.create_embedding_client`.
    Instances share the underlying model via the centralized class-level cache
    keyed on ``(provider, model_name, dimension)``, so spinning up many
    ``KnowledgeEmbedder()``s is cheap.

    Parameters
    ----------
    model_name:
        The embedding model name. For ``ollama`` this is the Ollama model ID.
        For ``openai-compatible`` this is the model ID expected by your server.
        For ``google`` this is a Gemini embedding model (e.g. ``gemini-embedding-001``).
    provider:
        Embedding backend: ``"ollama"`` (default), ``"google"``, or ``openai-compatible``.
    """

    def __init__(
        self,
        model_name: str | None = None,
        provider: str | None = None,
    ) -> None:
        from dashboard.lib.settings.resolver import get_settings_resolver
        try:
            resolver = get_settings_resolver()
            master = resolver.get_master_settings()
            know_cfg = master.knowledge
            master_model = know_cfg.knowledge_embedding_model if know_cfg and know_cfg.knowledge_embedding_model else ""
            master_provider = know_cfg.knowledge_embedding_backend if know_cfg and know_cfg.knowledge_embedding_backend else ""
        except Exception:
            master_model = ""
            master_provider = ""

        self.model_name: str = model_name or master_model or EMBEDDING_MODEL or "qwen3-embedding:0.6b"
        self.provider: str = (provider or master_provider or EMBEDDING_PROVIDER or "ollama").lower()
        # Dimension is fixed system-wide from OSTWIN_EMBEDDING_DIM env var.
        # Not configurable via MasterSettings to prevent dimension conflicts.
        self._dimension: int = EMBEDDING_DIMENSION

        # The centralized client is lazy-created on first embed/dimension call.
        self._client: Any = None

    def _get_client(self) -> Any:
        """Create (or retrieve cached) the centralized EmbeddingClient."""
        if self._client is not None:
            return self._client

        from dashboard.llm_client import create_embedding_client

        self._client = create_embedding_client(
            model=self.model_name,
            provider=self.provider,
            dimension=self._dimension,
        )
        return self._client

    # -- Public API -----------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns a list of float lists."""
        if not texts:
            return []
        return self._get_client().embed(texts)

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text. Returns a list of floats."""
        if text is None:
            return []
        return self._get_client().embed_one(text)

    def dimension(self) -> int:
        """Return the embedding dimension (cached after first load)."""
        if self._dimension is not None:
            return self._dimension
        self._dimension = self._get_client().dimension
        return self._dimension

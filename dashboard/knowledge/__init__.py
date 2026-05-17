"""Knowledge — Graph-RAG over imported folders.

Public surface (post EPIC-003 v2):

- :class:`KnowledgeService` — sync façade. Namespace lifecycle wired here;
  ingestion (``import_folder``) lands in EPIC-003 and query (``query``) in EPIC-004.
- :class:`NamespaceManager`, :class:`NamespaceMeta`, :class:`NamespaceStats`,
  :class:`ImportRecord` — namespace lifecycle primitives.
- Namespace exceptions: :class:`NamespaceError`, :class:`NamespaceNotFoundError`,
  :class:`NamespaceExistsError`, :class:`InvalidNamespaceIdError`.
- :class:`KnowledgeLLM` — multi-provider LLM wrapper (via ``llm_client.py``)
  for entity extraction, query planning, and answer aggregation.
- :class:`KnowledgeEmbedder` — embedding helper supporting Ollama, Google, Vertex,
  and OpenAI-compatible backends.
- :class:`NamespaceVectorStore`, :class:`VectorHit` — per-namespace zvec
  vector wrapper used by ingestion and (in EPIC-004) query.
- Graph internals: :class:`KuzuLabelledPropertyGraph`, :class:`GraphRAGExtractor`,
  :class:`GraphRAGQueryEngine`, :class:`GraphRAGStore`,
  :class:`TrackVectorRetriever`.

Importing this module is intentionally cheap — heavy deps (kuzu, zvec,
markitdown) are imported lazily inside the
methods that need them.
"""

from __future__ import annotations

import os
import multiprocessing

# macOS fork safety — redundancy guard in case this module is imported
# before api.py (e.g. in tests or standalone scripts). The canonical
# guard lives in dashboard/api.py at import-line 1.
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
try:
    multiprocessing.set_start_method("spawn", force=True)
except RuntimeError:
    pass

from dashboard.knowledge.config import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    KNOWLEDGE_DIR,
    LLM_MODEL,
    LLM_PROVIDER,
)
from dashboard.knowledge.embeddings import KnowledgeEmbedder
from dashboard.knowledge.graph.core import (
    GraphRAGExtractor,
    GraphRAGQueryEngine,
    GraphRAGStore,
    TrackVectorRetriever,
)
from dashboard.knowledge.graph.index import KuzuLabelledPropertyGraph
from dashboard.knowledge.ingestion import (
    FileEntry,
    IngestOptions,
    Ingestor,
)
from dashboard.knowledge.jobs import (
    JobEvent,
    JobManager,
    JobState,
    JobStatus,
)
from dashboard.knowledge.llm import KnowledgeLLM
from dashboard.knowledge.query import (
    ChunkHit,
    Citation,
    EntityHit,
    KnowledgeQueryEngine,
    QueryResult,
)
from dashboard.knowledge.namespace import (
    ImportRecord,
    InvalidNamespaceIdError,
    NamespaceError,
    NamespaceExistsError,
    NamespaceManager,
    NamespaceMeta,
    NamespaceNotFoundError,
    NamespaceStats,
    RetentionPolicy,  # EPIC-004
)
from dashboard.knowledge.service import KnowledgeService
from dashboard.knowledge.vector_store import NamespaceVectorStore, VectorHit
__all__ = [
    "KNOWLEDGE_DIR",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
    "EMBEDDING_PROVIDER",
    "LLM_MODEL",
    "LLM_PROVIDER",
    "KnowledgeService",
    "KnowledgeLLM",
    "KnowledgeEmbedder",
    "KuzuLabelledPropertyGraph",
    "GraphRAGExtractor",
    "GraphRAGQueryEngine",
    "GraphRAGStore",
    "TrackVectorRetriever",
    # Namespace primitives (EPIC-002)
    "NamespaceManager",
    "NamespaceMeta",
    "NamespaceStats",
    "ImportRecord",
    "NamespaceError",
    "NamespaceNotFoundError",
    "NamespaceExistsError",
    "InvalidNamespaceIdError",
    "RetentionPolicy",  # EPIC-004
    # Ingestion + jobs (EPIC-003)
    "Ingestor",
    "IngestOptions",
    "FileEntry",
    "JobManager",
    "JobStatus",
    "JobEvent",
    "JobState",
    # Vector store (EPIC-003 v2 — zvec migration)
    "NamespaceVectorStore",
    "VectorHit",
    # Query engine (EPIC-004)
    "KnowledgeQueryEngine",
    "QueryResult",
    "ChunkHit",
    "EntityHit",
    "Citation",
]

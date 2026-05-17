"""Top-level :class:`KnowledgeService` facade.

EPIC-002: namespace lifecycle is fully wired (delegates to
:class:`NamespaceManager`).
EPIC-003: ``import_folder``, ``get_job``, ``list_jobs`` are wired through a
:class:`JobManager` + :class:`Ingestor`.
EPIC-004: ``query`` and a centralized ``_vector_stores`` /
``_kuzu_graphs`` / ``_query_engines`` cache (architect's ZVEC-LIVE-1 fix).
Both the ingestor and the query engine pull their per-namespace handles from
this single service-level cache, so a single zvec collection / Kuzu DB is
shared across ingestion + retrieval (no duplicate handles).
EPIC-003 Hardening: concurrent import protection, namespace quotas, and
audit logging integration.
EPIC-004 Lifecycle: backup/restore, retention sweeper, refresh.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from dashboard.knowledge.namespace import (
    ImportRecord,  # noqa: F401 — re-exported convenience
    InvalidNamespaceIdError,  # noqa: F401
    NamespaceExistsError,  # noqa: F401
    NamespaceManager,
    NamespaceMeta,
    NamespaceNotFoundError,
    RetentionPolicy,  # noqa: F401 — EPIC-004
)
from dashboard.knowledge.audit import (  # noqa: WPS433 — EPIC-003 policies
    ImportInProgressError,
    MaxNamespacesReachedError,
    MAX_NAMESPACES,
    register_import,
    unregister_import,
    is_import_in_progress,
    _log_call,
    count_namespaces,
)
from dashboard.knowledge.stats import get_stats_computer  # noqa: WPS433 — EPIC-005
from dashboard.knowledge.metrics import get_metrics_registry  # noqa: WPS433 — EPIC-005
from dashboard.knowledge.config import LLM_MODEL as _DEFAULT_LLM  # noqa: WPS433
from dashboard.knowledge.config import LLM_PROVIDER as _DEFAULT_LLM_PROV  # noqa: WPS433
from dashboard.knowledge.llm import KnowledgeLLM  # noqa: WPS433
from dashboard.knowledge.config import EMBEDDING_MODEL as _DEFAULT_EMBED  # noqa: WPS433
from dashboard.knowledge.config import EMBEDDING_PROVIDER as _DEFAULT_EMBED_PROV  # noqa: WPS433
from dashboard.knowledge.embeddings import KnowledgeEmbedder  # noqa: WPS433
from dashboard.knowledge.query import KnowledgeQueryEngine  # noqa: WPS433
if TYPE_CHECKING:  # pragma: no cover
    from dashboard.knowledge.query import KnowledgeQueryEngine, QueryResult
    from dashboard.knowledge.vector_store import NamespaceVectorStore

logger = logging.getLogger(__name__)

# Default sweep interval for retention (hours)
DEFAULT_SWEEP_INTERVAL_HOURS = 6


class RetentionSweeper(threading.Thread):
    """Background thread that purges expired imports based on TTL policy.

    Started by :meth:`KnowledgeService.start_background` on dashboard startup.
    Runs every ``OSTWIN_KNOWLEDGE_SWEEP_INTERVAL_HOURS`` (default 6 hours).

    For each namespace with ``retention.policy == "ttl_days"``:
        1. Delete import records older than ``ttl_days``
        2. If all imports purged and ``auto_delete_when_empty == True``,
           delete the namespace itself
    """

    def __init__(
        self,
        service: "KnowledgeService",
        interval_hours: Optional[float] = None,
    ) -> None:
        super().__init__(daemon=True, name="RetentionSweeper")
        self._service = service
        self._interval_hours = interval_hours or float(
            os.environ.get("OSTWIN_KNOWLEDGE_SWEEP_INTERVAL_HOURS", DEFAULT_SWEEP_INTERVAL_HOURS)
        )
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Main sweep loop."""
        logger.info("RetentionSweeper started (interval: %.1f hours)", self._interval_hours)
        while not self._stop_event.wait(timeout=self._interval_hours * 3600):
            try:
                self._sweep_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("RetentionSweeper error: %s", exc)

    def stop(self) -> None:
        """Signal the sweeper to stop."""
        self._stop_event.set()

    def _sweep_once(self) -> None:
        """Run a single sweep pass."""
        now = datetime.now(timezone.utc)
        namespaces = self._service.list_namespaces()
        
        for meta in namespaces:
            if meta.retention.policy != "ttl_days":
                continue
            if meta.retention.ttl_days is None:
                continue
            
            ttl_days = meta.retention.ttl_days
            cutoff = now - timedelta(days=ttl_days)
            
            # Find expired imports
            expired = [
                imp for imp in meta.imports
                if imp.finished_at and imp.finished_at < cutoff
            ]
            
            # Update last_swept_at regardless of whether we have expired imports
            meta.retention.last_swept_at = now
            meta.updated_at = now
            
            if not expired:
                # Just save the updated timestamp
                self._service._nm.write_manifest(meta.name, meta)  # noqa: SLF001
                continue
            
            logger.info(
                "Sweeping %d expired imports from namespace %r (TTL: %d days)",
                len(expired), meta.name, ttl_days
            )
            
            # Remove expired imports from manifest
            remaining = [imp for imp in meta.imports if imp not in expired]
            meta.imports = remaining
            
            # Check if namespace should be deleted
            if not remaining and meta.retention.auto_delete_when_empty:
                logger.info("Deleting empty namespace %r (auto_delete_when_empty=True)", meta.name)
                self._service.delete_namespace(meta.name, actor="retention_sweeper")
            else:
                # Save updated manifest
                self._service._nm.write_manifest(meta.name, meta)  # noqa: SLF001


class KnowledgeService:
    """Sync façade composing :class:`NamespaceManager` + ingestion + query.

    All methods are sync; route handlers should wrap calls in
    ``asyncio.to_thread(...)`` per the cross-cutting concern in the plan.

    The ``namespace_manager``, ``job_manager`` and ``ingestor`` ctor args are
    optional injection points used by tests. When omitted they're constructed
    on-demand against ``KNOWLEDGE_DIR`` and shared across all calls.

    EPIC-004 architecture: this service owns the canonical per-namespace
    caches for vector stores, Kuzu graphs and query engines. Both the
    Ingestor and the query path resolve handles through
    :meth:`get_vector_store` / :meth:`get_kuzu_graph`, so there is exactly
    one live zvec handle and one Kuzu connection per namespace per process.
    Call :meth:`shutdown` before process exit (or in test teardown) to
    release them cleanly.
    """

    def __init__(
        self,
        namespace_manager: Optional[NamespaceManager] = None,
        job_manager: Optional[Any] = None,
        ingestor: Optional[Any] = None,
        embedder: Optional[Any] = None,
        llm: Optional[Any] = None,
    ) -> None:
        self._nm = namespace_manager or NamespaceManager()
        # Lazy: only construct JobManager / Ingestor on first use, so that
        # `KnowledgeService()` itself stays cheap.
        self._jm_override = job_manager
        self._ingestor_override = ingestor
        # Pass-throughs to the Ingestor when it's constructed lazily; tests
        # use these to inject fake embedder / LLM without having to also
        # build their own Ingestor.
        self._embedder_override = embedder
        self._llm_override = llm
        self._jm: Any = None
        self._ingestor: Any = None
        # Lazy-instantiated long-lived embedder / llm shared between the
        # ingestor and the query engine. Constructed on first use through
        # the relevant getter so a fresh `KnowledgeService()` stays cheap.
        self._embedder: Any = None
        self._llm: Any = None
        # Centralised caches — survive across ingestion + query and are the
        # ONLY source of truth for per-namespace handles. Architect's
        # ZVEC-LIVE-1 fix from the EPIC-003 review.
        self._vector_stores: dict[str, "NamespaceVectorStore"] = {}
        self._vs_lock = threading.Lock()  # guards _vector_stores creation

        self._kuzu_graphs: dict[str, Any] = {}
        self._query_engines: dict[str, "KnowledgeQueryEngine"] = {}
        self._graph_rag_engines: dict[str, Any] = {}  # per-namespace GraphRAGQueryEngine cache
        # Background retention sweeper (EPIC-004)
        self._sweeper: Optional[RetentionSweeper] = None

    # ---- Shared embedder / LLM (lazy) -----------------------------------

    @staticmethod
    def _resolve_settings_overrides() -> tuple[str, str]:
        """Resolve model overrides from MasterSettings.

        Returns:
            tuple[str, str]: (knowledge_llm_model, knowledge_embedding_model)
        """
        try:
            from dashboard.lib.settings import get_settings_resolver  # noqa: WPS433

            ms = get_settings_resolver().get_master_settings()
            ks = getattr(ms, "knowledge", None)
            if ks is None:
                return "", ""
            return (
                ks.knowledge_llm_model or "",
                ks.knowledge_embedding_model or "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("settings resolver unavailable: %s; using env defaults", exc)
            return "", ""

    def _get_embedder(self) -> Any:
        """Lazily construct (or return the injected) embedder, shared service-wide.

        The Ingestor and the query engine both go through this so a single
        model load is amortised across ingestion + every subsequent query.

        Effective model resolution (ADR-15): ``MasterSettings.knowledge.embedding_model``
        > ``OSTWIN_KNOWLEDGE_EMBED_MODEL`` env var > hardcoded ``EMBEDDING_MODEL``.

        Provider resolution: ``MasterSettings.knowledge.embedding_backend``
        > ``OSTWIN_KNOWLEDGE_EMBED_PROVIDER`` env var > ``EMBEDDING_PROVIDER``
        (default: ``ollama``). Supported providers: ``ollama`` and
        ``openai-compatible`` (plus Gemini for cloud).

        When the chosen backend is unreachable, the embedder will return
        empty vectors and log errors.
        """
        # Test/programmatic injection takes priority — mirrors the pattern used
        # for _jm_override and _ingestor_override.
        if self._embedder_override is not None:
            return self._embedder_override
        if self._embedder is not None:
            return self._embedder
        settings_llm, settings_embed = self._resolve_settings_overrides()
        effective_model = settings_embed or _DEFAULT_EMBED or None
        # Let KnowledgeEmbedder resolve the provider from MasterSettings /
        # env vars / config defaults — don't hardcode it here. Passing
        # None lets the embedder fall through its own resolution chain.
        effective_provider = None
        self._embedder = KnowledgeEmbedder(
            model_name=effective_model,
            provider=effective_provider,
        )
        return self._embedder

    def _get_llm(self) -> Any:
        """Lazily construct (or return the injected) LLM, shared service-wide.

        Effective model resolution (ADR-15): ``MasterSettings.knowledge.llm_model``
        > ``OSTWIN_KNOWLEDGE_LLM_MODEL`` env var > config ``LLM_MODEL``.
        User must configure a model; there is no hardcoded default.
        """
        if self._llm_override is not None:
            return self._llm_override
        if self._llm is not None:
            return self._llm
        settings_llm, _ = self._resolve_settings_overrides()
        effective_model = settings_llm or _DEFAULT_LLM
        self._llm = KnowledgeLLM(
            model=effective_model,
        )
        return self._llm

    # ---- Centralised per-namespace handle cache (EPIC-004) --------------

    def get_vector_store(self, namespace: str) -> "NamespaceVectorStore":
        """Get-or-create the cached vector store for ``namespace``.

        BOTH the ingestor AND the query engine MUST go through this method
        — the architect's ZVEC-LIVE-1 fix from the EPIC-003 review. zvec
        rejects opening the same collection from two live handles in the
        same process; centralising the cache here is the only correct
        solution.

        Thread-safe: a lock guards the check-and-create so concurrent
        callers (ingestion thread + query thread) never construct two
        ``NamespaceVectorStore`` instances for the same namespace — which
        would cause ``"Can't lock read-write collection"`` from zvec.

        Raises :class:`DimensionMismatchError` if the on-disk collection
        was created with a different embedding dimension than the current
        embedder produces.
        """
        existing = self._vector_stores.get(namespace)
        if existing is not None:
            return existing
        with self._vs_lock:
            # Double-check after acquiring lock — another thread may have
            # populated the cache while we waited.
            existing = self._vector_stores.get(namespace)
            if existing is not None:
                return existing
            from dashboard.knowledge.vector_store import NamespaceVectorStore  # noqa: WPS433

            vs = NamespaceVectorStore(
                vector_path=self._nm.vector_dir(namespace),
                dimension=int(self._get_embedder().dimension()),
                schema_name=f"knowledge_{namespace}",
            )
            self._vector_stores[namespace] = vs
            return vs



    def get_kuzu_graph(self, namespace: str) -> Any:
        """Get-or-create the cached Kuzu graph for ``namespace``.

        Uses :meth:`NamespaceManager.kuzu_db_path` so a custom ``base_dir``
        is honoured — never falls back to the module-level
        ``config.kuzu_db_path`` helper.
        """
        existing = self._kuzu_graphs.get(namespace)
        if existing is not None:
            return existing
        from dashboard.knowledge.graph.index.kuzudb import (  # noqa: WPS433
            KuzuLabelledPropertyGraph,
        )

        db_path = str(self._nm.kuzu_db_path(namespace))
        kg = KuzuLabelledPropertyGraph(
            index=namespace,
            ws_id=namespace,
            database_path=db_path,
        )
        self._kuzu_graphs[namespace] = kg
        return kg

    def get_graph(self, namespace: str, limit: int = 200, actor: str = "anonymous") -> dict:
        """Alias for the graph visualisation route (EPIC-004).
        
        Delegates to the cached per-namespace query engine's visualization method.
        """
        engine = self._get_query_engine(namespace)
        return engine.get_graph(limit=limit)

    # ---- Supernova Explorer APIs ----------------------------------------

    def _get_explorer(self, namespace: str):
        """Lazy-construct a :class:`KnowledgeExplorer` for *namespace*.

        Uses the same cached Kuzu graph handle as the rest of the service.
        """
        from dashboard.knowledge.graph.explorer import KnowledgeExplorer  # noqa: WPS433
        kg = self.get_kuzu_graph(namespace)
        return KnowledgeExplorer(kg)

    def explorer_summary(self, namespace: str) -> dict:
        """Return lightweight topology stats for the namespace graph."""
        explorer = self._get_explorer(namespace)
        return explorer.summary()

    def explorer_seed(self, namespace: str, top_k: int = 50) -> dict:
        """Return the initial "sky" — top PageRank nodes + 1-hop neighborhood."""
        explorer = self._get_explorer(namespace)
        return explorer.seed(top_k=top_k)

    def explorer_expand(self, namespace: str, node_ids: list[str], depth: int = 1) -> dict:
        """Expand from a set of node IDs outward by N hops."""
        explorer = self._get_explorer(namespace)
        return explorer.expand(node_ids=node_ids, depth=depth)

    def explorer_search(self, namespace: str, query: str, limit: int = 20) -> dict:
        """Vector-similarity search over node embeddings + 1-hop context."""
        explorer = self._get_explorer(namespace)
        return explorer.search(query=query, limit=limit)

    def explorer_path(self, namespace: str, source_id: str, target_id: str) -> dict:
        """Find the shortest weighted path between two nodes."""
        explorer = self._get_explorer(namespace)
        return explorer.path(source_id=source_id, target_id=target_id)

    def explorer_node_detail(self, namespace: str, node_id: str) -> dict:
        """Full detail for a single node including incident edges and scores."""
        explorer = self._get_explorer(namespace)
        return explorer.node_detail(node_id=node_id)

    def explorer_communities(self, namespace: str) -> dict:
        """Return Louvain community mapping for the namespace graph."""
        explorer = self._get_explorer(namespace)
        return explorer.communities()

    def _get_graph_rag_engine(self, namespace: str) -> Any:
        """Cached per-namespace :class:`GraphRAGQueryEngine`.

        Constructs the full llama-index graph-RAG query pipeline using the
        same shared Kuzu graph and vector store handles that the lightweight
        ``KnowledgeQueryEngine`` uses.

        The ``PropertyGraphIndex.from_existing`` call is cheap — it doesn't
        reload data; it just wraps the existing stores with the llama-index
        index interface.

        Returns ``None`` when construction fails (missing deps, bad graph
        state, etc.) so the caller can fall back to the simple path.
        """
        existing = self._graph_rag_engines.get(namespace)
        if existing is not None:
            return existing

        try:
            from llama_index.core import PropertyGraphIndex, StorageContext  # noqa: WPS433
            from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore  # noqa: WPS433
            from dashboard.knowledge.graph.core.graph_rag_extractor import GraphRAGExtractor  # noqa: WPS433
            from dashboard.knowledge.graph.core.graph_rag_query_engine import (
                GraphRAGQueryEngine,
            )  # noqa: WPS433
            from dashboard.knowledge.graph.core.llama_adapters import (
                ZvecVectorStoreAdapter,
                EmbedderAdapter,
            )  # noqa: WPS433

            kuzu_graph = self.get_kuzu_graph(namespace)
            graph_store = GraphRAGStore(graph=kuzu_graph)

            vs_adapter = ZvecVectorStoreAdapter(
                zvec_store=self.get_vector_store(namespace),
            )
            embed_adapter = EmbedderAdapter(
                knowledge_embedder=self._get_embedder(),
            )

            # Resolve namespace language for prompt selection.
            meta = self._nm.get(namespace)
            ns_language = meta.language if meta else "English"

            llm = self._get_llm()
            extractor = GraphRAGExtractor(
                llm=llm,
                embedder=self._get_embedder(),
                language=ns_language,
            )

            # kg_extractors=[extractor] prevents llama-index from
            # constructing a default SimpleLLMPathExtractor that requires
            # the llama-index-llms-openai package / OPENAI_API_KEY.
            index = PropertyGraphIndex.from_existing(
                property_graph_store=graph_store,
                vector_store=vs_adapter,
                embed_model=embed_adapter,
                embed_kg_nodes=False,
                kg_extractors=[extractor],
            )

            storage_ctx = StorageContext.from_defaults(
                property_graph_store=graph_store,
            )

            engine = GraphRAGQueryEngine(
                graph_store=graph_store,
                index=index,
                vector_store=vs_adapter,
                storage_context=storage_ctx,
                kg_extractor=extractor,
                llm=llm,
                plan_llm=llm,
                node_id=namespace,
                embed_model=embed_adapter,
                include_graph=True,
                max_queries=3,
                language=ns_language,
            )
            self._graph_rag_engines[namespace] = engine
            return engine

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to construct GraphRAGQueryEngine for %r; "
                "graph/summarized queries will use the simple path: %s",
                namespace,
                exc,
            )
            return None

    def _get_query_engine(self, namespace: str) -> "KnowledgeQueryEngine":
        """Cached per-namespace query engine.

        The engine holds references to the cached Kuzu graph, embedder and
        LLM — building one is cheap (sub-ms) so this cache primarily exists
        so repeated queries against the same namespace don't reconstruct
        the wrapper.

        All query modes use KuzuDB's ``QUERY_VECTOR_INDEX`` for vector
        search and graph expansion. The zvec vector store is NOT used for
        queries (only for ingestion-time idempotency tracking).

        When a ``GraphRAGQueryEngine`` is available (llama-index graph-RAG
        pipeline with hit-aware PageRank scoring), it is injected so that
        ``graph`` and ``summarized`` modes benefit from the richer scoring.
        """
        existing = self._query_engines.get(namespace)
        if existing is not None:
            return existing

        # Resolve namespace language for prompt selection.
        meta = self._nm.get(namespace)
        ns_language = meta.language if meta else "English"

        graph_rag_engine = self._get_graph_rag_engine(namespace)

        engine = KnowledgeQueryEngine(
            namespace=namespace,
            kuzu_graph=self.get_kuzu_graph(namespace),
            embedder=self._get_embedder(),
            llm=self._get_llm(),
            graph_rag_engine=graph_rag_engine,
            language=ns_language,
        )
        self._query_engines[namespace] = engine
        return engine

    def invalidate_model_cache(self) -> None:
        """Drop cached LLM + embedder so next access picks up new settings.

        Called by the settings route when ``knowledge`` config changes.
        Query engines hold refs to the old LLM/embedder — they must be
        rebuilt too.  Vector stores and Kuzu graphs are model-independent
        and survive the invalidation.
        """
        self._llm = None
        self._embedder = None
        self._query_engines.clear()
        self._graph_rag_engines.clear()
        logger.info("Knowledge model cache invalidated — next call will re-resolve settings")

    def shutdown(self) -> None:
        """Release every cached handle. Call before process exit / test teardown.

        Order matters: query engines (which hold refs to the others) are
        cleared first, then vector stores, then Kuzu graphs, then the job
        manager. Each ``close`` is best-effort; a single failure is logged
        but does not abort the rest of the shutdown.
        """
        # Drop query engine refs first (they only hold weak-ish refs to
        # the underlying handles, but clearing them ensures a future
        # call doesn't accidentally hold an old handle alive).
        self._query_engines.clear()
        self._graph_rag_engines.clear()

        for ns, vs in list(self._vector_stores.items()):
            try:
                vs.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing vector store for %r: %s", ns, exc)
        self._vector_stores.clear()


        for ns, kg in list(self._kuzu_graphs.items()):
            try:
                kg.close_connection()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing kuzu graph for %r: %s", ns, exc)
        self._kuzu_graphs.clear()

        # Tell the JobManager to stop accepting new work and tear down its
        # ThreadPoolExecutor. ``wait=False`` so callers (especially test
        # teardown) don't block on a long-running ingest.
        if self._jm is not None:
            try:
                self._jm.shutdown(wait=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error shutting down job manager: %s", exc)
        
        # Stop the retention sweeper (EPIC-004)
        if self._sweeper is not None:
            try:
                self._sweeper.stop()
                self._sweeper.join(timeout=5.0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping retention sweeper: %s", exc)

    def start_background(self) -> None:
        """Start background services (retention sweeper).

        Called by the FastAPI lifespan in ``api.py`` on startup.
        """
        if self._sweeper is None:
            self._sweeper = RetentionSweeper(self)
            self._sweeper.start()
            logger.info("Started retention sweeper background thread")


    def _evict_namespace_caches(self, namespace: str) -> None:
        """Drop all cached handles for ``namespace`` (used by delete_namespace)."""
        self._query_engines.pop(namespace, None)
        self._graph_rag_engines.pop(namespace, None)
        vs = self._vector_stores.pop(namespace, None)
        if vs is not None:
            try:
                vs.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Error closing vector store for %r during eviction: %s",
                    namespace,
                    exc,
                )

        kg = self._kuzu_graphs.pop(namespace, None)
        if kg is not None:
            try:
                kg.close_connection()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Error closing kuzu graph for %r during eviction: %s",
                    namespace,
                    exc,
                )

    # ---- Lazy job manager / ingestor ------------------------------------

    def _get_job_manager(self) -> Any:
        if self._jm is not None:
            return self._jm
        if self._jm_override is not None:
            self._jm = self._jm_override
            return self._jm
        from dashboard.knowledge.jobs import JobManager  # noqa: WPS433

        self._jm = JobManager(base_dir=self._nm._base)  # noqa: SLF001
        return self._jm

    def _get_ingestor(self) -> Any:
        if self._ingestor is not None:
            return self._ingestor
        if self._ingestor_override is not None:
            self._ingestor = self._ingestor_override
            return self._ingestor
        from dashboard.knowledge.ingestion import Ingestor  # noqa: WPS433

        # Pass the cache-aware factories so the ingestor pulls from the
        # service's centralised caches instead of constructing its own
        # per-namespace handles. This is the architect's ZVEC-LIVE-1 fix.
        #
        # graph_index_factory: builds a PropertyGraphIndex per namespace
        # so ingestion writes entities/relations through the same llama-index
        # pipeline that the query engine reads — guaranteeing schema compat.
        self._ingestor = Ingestor(
            namespace_manager=self._nm,
            embedder=self._get_embedder(),
            llm=self._get_llm(),
            vector_store_factory=self.get_vector_store,
            kuzu_factory=self.get_kuzu_graph,
            graph_index_factory=self._build_graph_index,
        )
        return self._ingestor

    def _build_graph_index(self, namespace: str, *, llm_model: str = "") -> Any:
        """Construct a ``PropertyGraphIndex`` for ingestion into ``namespace``.

        Uses the same shared stores/adapters as ``_get_graph_rag_engine`` so
        ingested data is immediately visible to the query engine.  Unlike the
        query-engine constructor, ``embed_kg_nodes=True`` here so entity
        embeddings are computed and persisted during ingestion.

        The ``kg_extractors`` list is populated with a ``GraphRAGExtractor`` so
        ``insert_nodes()`` automatically runs entity extraction.

        When ``llm_model`` is provided, creates a fresh ``KnowledgeLLM`` with
        that model instead of using the service-level default. This supports
        per-import model overrides from ``IngestOptions.llm_model``.
        """
        try:
            from llama_index.core import PropertyGraphIndex, StorageContext  # noqa: WPS433
            from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore  # noqa: WPS433
            from dashboard.knowledge.graph.core.graph_rag_extractor import GraphRAGExtractor  # noqa: WPS433
            from dashboard.knowledge.graph.core.llama_adapters import (  # noqa: WPS433
                ZvecVectorStoreAdapter,
                EmbedderAdapter,
            )

            kuzu_graph = self.get_kuzu_graph(namespace)
            graph_store = GraphRAGStore(graph=kuzu_graph)

            vs_adapter = ZvecVectorStoreAdapter(
                zvec_store=self.get_vector_store(namespace),
            )
            embed_adapter = EmbedderAdapter(
                knowledge_embedder=self._get_embedder(),
            )

            if llm_model:
                from dashboard.knowledge.llm import KnowledgeLLM  # noqa: WPS433
                llm = KnowledgeLLM(model=llm_model)
            else:
                llm = self._get_llm()

            # Resolve namespace language for prompt selection.
            meta = self._nm.get(namespace)
            ns_language = meta.language if meta else "English"

            extractor = GraphRAGExtractor(
                llm=llm,
                embedder=self._get_embedder(),
                language=ns_language,
            )

            index = PropertyGraphIndex.from_existing(
                property_graph_store=graph_store,
                vector_store=vs_adapter,
                embed_model=embed_adapter,
                kg_extractors=[extractor],
                embed_kg_nodes=True,
            )
            return index

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to build PropertyGraphIndex for ingestion into %r: %s",
                namespace,
                exc,
            )
            raise

    # ---- Namespace lifecycle (EPIC-002 — wired) --------------------------

    def list_namespaces(self) -> list[NamespaceMeta]:
        """Return manifests for every existing namespace (possibly empty)."""
        return self._nm.list()

    def get_namespace(self, namespace: str) -> Optional[NamespaceMeta]:
        """Return the manifest for ``namespace``, or None if missing/invalid."""
        return self._nm.get(namespace)

    def get_namespace_stats(self, namespace: str) -> Optional[dict[str, Any]]:
        """Return enriched stats for a namespace (EPIC-005).

        Computes and caches:
        - disk_bytes: Actual disk usage
        - query_count_24h: Queries in last 24 hours
        - ingest_count_24h: Ingestions in last 24 hours

        Returns None if the namespace doesn't exist.
        """
        meta = self._nm.get(namespace)
        if meta is None:
            return None

        # Get computed stats from stats computer
        stats_computer = get_stats_computer()
        namespace_dir = self._nm.namespace_dir(namespace)
        computed = stats_computer.get_stats(namespace, namespace_dir)

        # Merge with manifest stats
        base_stats = meta.stats.model_dump()
        base_stats.update(computed)
        return base_stats

    def _update_namespace_gauges(self) -> None:
        """Update Prometheus gauges for namespace counts (EPIC-005).

        Called after namespace create/delete operations and periodically.
        """
        metrics = get_metrics_registry()
        namespaces = self._nm.list()
        
        # Total namespace count
        metrics.gauge("namespaces_total").set(len(namespaces))
        
        # Per-namespace gauges
        for meta in namespaces:
            ns = meta.name
            labels = {"namespace": ns}
            
            # Vector count
            metrics.gauge("vector_count_per_namespace").set(meta.stats.vectors, labels=labels)
            
            # Entity count
            metrics.gauge("entity_count_per_namespace").set(meta.stats.entities, labels=labels)
            
            # Disk bytes (use computed value if available)
            stats_computer = get_stats_computer()
            namespace_dir = self._nm.namespace_dir(ns)
            computed = stats_computer.get_stats(ns, namespace_dir)
            metrics.gauge("disk_bytes_per_namespace").set(computed.get("disk_bytes", 0), labels=labels)

    def create_namespace(
        self,
        namespace: str,
        language: str = "English",
        description: Optional[str] = None,
        actor: str = "anonymous",
    ) -> NamespaceMeta:
        """Create a fresh namespace.

        Raises :class:`InvalidNamespaceIdError` for bad ids,
        :class:`NamespaceExistsError` for duplicates, and
        :class:`MaxNamespacesReachedError` when the quota is exceeded.
        """
        start_time = time.perf_counter()
        try:
            # Check namespace quota before attempting creation
            current_count = count_namespaces(self._nm._base)  # noqa: SLF001
            if current_count >= MAX_NAMESPACES:
                raise MaxNamespacesReachedError(MAX_NAMESPACES)

            # Resolve the effective embedding model so the manifest records
            # the ACTUAL model/dimension that will be used for ingestion,
            # not the hardcoded config.py default.
            embedder = self._get_embedder()
            meta = self._nm.create(
                namespace,
                language=language,
                description=description,
                embedding_model=embedder.model_name,
                embedding_dimension=embedder.dimension(),
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "create_namespace", "success", latency_ms, {"actor": actor})
            # EPIC-005: Update namespace gauges
            self._update_namespace_gauges()
            return meta
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            result = "error"
            if isinstance(exc, (InvalidNamespaceIdError, NamespaceExistsError, MaxNamespacesReachedError)):
                result = type(exc).__name__
            _log_call(namespace, "create_namespace", result, latency_ms, {"actor": actor, "error": str(exc)})
            raise

    def delete_namespace(self, namespace: str, actor: str = "anonymous") -> bool:
        """Delete a namespace; returns True if it existed, False otherwise.

        EPIC-004: evicts the namespace's entries from all centralised
        caches BEFORE the directory is removed. Without this, the cached
        zvec handle would keep a file lock on the now-deleted directory
        and a subsequent re-create would fail.
        """
        start_time = time.perf_counter()
        try:
            # Evict cached handles FIRST so files can be removed cleanly.
            self._evict_namespace_caches(namespace)
            deleted = self._nm.delete(namespace)
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "delete_namespace", "success", latency_ms, {"actor": actor, "deleted": deleted})
            # EPIC-005: Update namespace gauges
            self._update_namespace_gauges()
            return deleted
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "delete_namespace", "error", latency_ms, {"actor": actor, "error": str(exc)})
            raise

    # ---- Ingestion (EPIC-003 — wired) -----------------------------------

    def import_folder(
        self,
        namespace: str,
        folder_path: str,
        options: Optional[dict[str, Any]] = None,
        actor: str = "anonymous",
    ) -> str:
        """Submit a folder for background ingestion; return the ``job_id``.

        - **Auto-creates the namespace** when it doesn't already exist
          (decision recorded in EPIC-003 done report — chosen over 404
          because the alternative forces a clumsy two-step API for
          first-time imports).
        - Validates that ``folder_path`` exists and is a directory; raises
          :class:`FileNotFoundError` / :class:`NotADirectoryError` otherwise.
        - Returns within milliseconds — actual work runs on the JobManager's
          ThreadPoolExecutor.
        - **Concurrent import protection**: raises :class:`ImportInProgressError`
          if another import is already running for the same namespace.

        Raises:
            ImportInProgressError: When an import is already in progress for
                the same namespace.
        """
        from dashboard.knowledge.ingestion import IngestOptions  # noqa: WPS433

        start_time = time.perf_counter()

        try:
            # Auto-create namespace if missing.  Resolve the effective
            # embedder so the manifest records the correct model/dimension.
            if self._nm.get(namespace) is None:
                embedder = self._get_embedder()
                self._nm.create(
                    namespace,
                    embedding_model=embedder.model_name,
                    embedding_dimension=embedder.dimension(),
                )

            # Early validation: check that the namespace's recorded dimension
            # matches the current embedder. A mismatch means the embedding
            # model was changed after the namespace was created — every
            # chunk upsert would fail with "dimension mismatch".
            ns_meta = self._nm.get(namespace)
            if ns_meta is not None:
                embedder = self._get_embedder()
                actual_dim = embedder.dimension()
                if ns_meta.embedding_dimension != actual_dim:
                    raise RuntimeError(
                        f"Namespace {namespace!r} was created with "
                        f"embedding model {ns_meta.embedding_model!r} "
                        f"(dim={ns_meta.embedding_dimension}), but the "
                        f"current embedder is {embedder.model_name!r} "
                        f"(dim={actual_dim}). Delete the namespace and "
                        f"re-create it, or switch back to the original "
                        f"embedding model."
                    )

            # Validate folder path BEFORE submitting — surface the error to the caller.
            p = Path(folder_path)
            if not p.exists():
                raise FileNotFoundError(folder_path)
            if not p.is_dir():
                raise NotADirectoryError(folder_path)

            opts = IngestOptions(**(options or {}))
            ingestor = self._get_ingestor()
            jm = self._get_job_manager()

            # Register the import as in-progress BEFORE submitting the job.
            # This closes the TOCTOU window: register_import() is atomic
            # (holds _active_imports_lock) and will raise ImportInProgressError
            # if another import is already running for this namespace.
            # We use a placeholder job_id and update it after submit.
            register_import(namespace, "__pending__")

            # The JobManager calls runner(emit) in a worker thread.
            def runner(emit):
                try:
                    return ingestor.run(namespace, folder_path, opts, emit=emit)
                finally:
                    # Always unregister the import when done (success or failure)
                    unregister_import(namespace)

            try:
                job_id = jm.submit(
                    namespace=namespace,
                    operation="import_folder",
                    fn=runner,
                    message=f"Importing {folder_path}",
                )
            except Exception:
                # Submit failed — rollback the registration
                unregister_import(namespace)
                raise

            # Update the registration with the real job_id
            from dashboard.knowledge.audit import _active_imports, _active_imports_lock  # noqa: WPS433
            with _active_imports_lock:
                _active_imports[namespace] = job_id

            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "import_folder", "success", latency_ms, {"actor": actor, "job_id": job_id})
            return job_id

        except ImportInProgressError:
            # Re-raise as-is (don't log as regular error)
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "import_folder", "import_in_progress", latency_ms, {"actor": actor})
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "import_folder", "error", latency_ms, {"actor": actor, "error": str(exc)})
            raise

    def import_text(
        self,
        namespace: str,
        text: str,
        source_label: str = "inline",
        options: Optional[dict[str, Any]] = None,
        actor: str = "anonymous",
    ) -> dict:
        """Synchronously ingest plain text into ``namespace``.

        Unlike :meth:`import_folder` (which submits a background job), this
        returns the result dict directly. However, the actual ingestion
        runs in a **dedicated thread** because ``PropertyGraphIndex.insert_nodes()``
        internally calls ``asyncio.run()``, which fails when called from
        within a running event loop (e.g. FastMCP / uvicorn).

        - Auto-creates the namespace when it doesn't exist.
        - Uses concurrent-import protection (same as ``import_folder``).
        - Returns a result dict with ``chunks_added``, ``entities_added``,
          ``relations_added``, ``elapsed_seconds``.
        """
        from concurrent.futures import ThreadPoolExecutor
        from dashboard.knowledge.ingestion import IngestOptions

        start_time = time.perf_counter()

        try:
            if self._nm.get(namespace) is None:
                embedder = self._get_embedder()
                self._nm.create(
                    namespace,
                    embedding_model=embedder.model_name,
                    embedding_dimension=embedder.dimension(),
                )

            ns_meta = self._nm.get(namespace)
            if ns_meta is not None:
                embedder = self._get_embedder()
                actual_dim = embedder.dimension()
                if ns_meta.embedding_dimension != actual_dim:
                    raise RuntimeError(
                        f"Namespace {namespace!r} was created with "
                        f"embedding model {ns_meta.embedding_model!r} "
                        f"(dim={ns_meta.embedding_dimension}), but the "
                        f"current embedder is {embedder.model_name!r} "
                        f"(dim={actual_dim}). Delete the namespace and "
                        f"re-create it, or switch back to the original "
                        f"embedding model."
                    )

            opts = IngestOptions(**(options or {}))
            ingestor = self._get_ingestor()

            register_import(namespace, "__pending_text__")

            def _run_ingest():
                return ingestor.ingest_text(
                    namespace,
                    text,
                    source_label=source_label,
                    options=opts,
                )

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(_run_ingest).result()
            finally:
                unregister_import(namespace)

            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "import_text", "success", latency_ms, {"actor": actor})
            return result

        except ImportInProgressError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "import_text", "import_in_progress", latency_ms, {"actor": actor})
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "import_text", "error", latency_ms, {"actor": actor, "error": str(exc)})
            raise

    def get_job(self, job_id: str) -> Any:
        """Return the :class:`JobStatus` for ``job_id`` (or None if unknown)."""
        return self._get_job_manager().get(job_id)

    def list_jobs(self, namespace: str) -> Any:
        """List jobs for ``namespace`` (newest first)."""
        return self._get_job_manager().list_for_namespace(namespace)

    def count_graph_stats(self, namespace: str) -> dict[str, int]:
        """Return live entity/chunk/relation counts from KuzuDB.

        Uses lightweight Cypher COUNT queries — no full node materialisation.
        Returns ``{"entities": 0, "chunks": 0, "relations": 0}`` if the
        graph DB doesn't exist or the schema hasn't been set up yet.
        """
        try:
            kg = self.get_kuzu_graph(namespace)
            return {
                "entities": kg.count_entities(),
                "chunks": kg.count_chunks(),
                "relations": kg.count_relations(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("count_graph_stats failed for %r: %s", namespace, exc)
            return {"entities": 0, "chunks": 0, "relations": 0}

    # ---- Retrieval (EPIC-004) -------------------------------------------

    def query(
        self,
        namespace: str,
        query: str,
        *,
        mode: str = "raw",
        top_k: int = 10,
        threshold: float = 0.5,
        category: Optional[str] = None,
        parameter: str = "",
        actor: str = "anonymous",
    ) -> "QueryResult":
        """Run a retrieval against ``namespace``.

        Modes:

        - ``raw``        — vector search only. Fast (< 500ms p95 on small
          corpora). No graph, no LLM.
        - ``graph``      — vector search + graph expansion + PageRank
          rerank. Returns chunks AND entities. No LLM aggregation.
        - ``summarized`` — graph mode + LLM-aggregated answer. Requires
          an LLM model and API key; without it, returns chunks + a warning
          (no crash, no answer).

        Raises :class:`NamespaceNotFoundError` if the namespace doesn't
        exist, and :class:`ValueError` for an unknown mode.
        """
        start_time = time.perf_counter()
        try:
            if self._nm.get(namespace) is None:
                raise NamespaceNotFoundError(namespace)
            if mode not in ("raw", "graph", "summarized"):
                raise ValueError(f"unknown mode: {mode!r}")
            engine = self._get_query_engine(namespace)
            result = engine.query(
                query,
                mode=mode,
                top_k=top_k,
                threshold=threshold,
                category=category,
                parameter=parameter,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "query", "success", latency_ms, {"actor": actor, "mode": mode})
            # EPIC-005: Update last_query_at in stats
            try:
                from datetime import datetime, timezone  # noqa: WPS433

                self._nm.update_stats(namespace, last_query_at=datetime.now(timezone.utc))
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to update last_query_at: %s", exc)
            return result
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "query", "error", latency_ms, {"actor": actor, "error": str(exc)})
            raise

    def refresh_namespace(self, namespace: str, actor: str = "anonymous") -> list[str]:
        """Re-ingest all folders previously imported into this namespace (EPIC-004).

        Triggers a new background job for each unique folder path found in the
        namespace's import history.  Uses ``force=True`` to ensure that files
        are re-processed even if they haven't changed (e.g. to pickup new
        extraction logic or model improvements).

        Returns:
            A list of ``job_id`` strings for the triggered refresh jobs.
        """
        meta = self.get_namespace(namespace)
        if meta is None:
            raise NamespaceNotFoundError(namespace)

        # Extract unique folder paths that were successfully imported
        folders = {
            imp.folder_path for imp in meta.imports
            if imp.status == "completed"
        }
        
        job_ids = []
        for folder in sorted(folders):
            try:
                jid = self.import_folder(
                    namespace,
                    folder,
                    options={"force": True},
                    actor=actor
                )
                job_ids.append(jid)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to trigger refresh for %r in %r: %s", folder, namespace, exc)

        return job_ids

    def backup_namespace(self, namespace: str, dest_path: Optional[Path] = None) -> Path:
        """Create a backup archive for the namespace (EPIC-004)."""
        # Ensure all handles are closed and flushed before backup
        self._evict_namespace_caches(namespace)
        from dashboard.knowledge.backup import backup_namespace  # noqa: WPS433
        return backup_namespace(namespace, dest_path=dest_path, namespace_manager=self._nm)

    def restore_namespace(
        self,
        archive_path: str,
        name: Optional[str] = None,
        overwrite: bool = False
    ) -> NamespaceMeta:
        """Restore a namespace from a backup archive (EPIC-004)."""
        from dashboard.knowledge.backup import restore_namespace  # noqa: WPS433
        return restore_namespace(
            Path(archive_path),
            name=name,
            namespace_manager=self._nm,
            knowledge_service=self,
            overwrite=overwrite
        )



__all__ = ["KnowledgeService"]

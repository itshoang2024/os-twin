"""Per-namespace query engine — three retrieval modes (EPIC-004).

The :class:`KnowledgeQueryEngine` is the heart of EPIC-004. One engine
instance per namespace, constructed by :meth:`KnowledgeService._get_query_engine`
and cached for the lifetime of the service. The engine holds **references**
(not copies) to the centralised Kuzu graph, embedder and LLM that live on
the :class:`KnowledgeService` — which is why the service-level cache is the
single source of truth for those handles (architect's ZVEC-LIVE-1 fix from
the EPIC-003 review).

Three modes:

- ``raw``        — KG graph engine retrieval via ``get_all_nodes``. Returns
                   both ChunkNode and EntityNode hits. The KG layer owns
                   vector search logic entirely.
- ``graph``      — Graph expansion (entities related to the query, ranked
                   by personalised PageRank via :class:`GraphRAGQueryEngine`
                   when available, otherwise uniform PageRank).
- ``summarized`` — graph mode + LLM-aggregated answer. Requires an LLM model
                   and API key to be configured; without it the engine returns
                   chunks + entities + a ``warning`` field on the result and
                   ``answer=None``. Never crashes for missing-key reasons.

All three modes record ``latency_ms`` on the result. Per-step failures are
caught and accumulated as ``warnings`` on the result so a single bad
component (e.g. a Kuzu read error during graph expansion) doesn't kill the
entire query — the caller still gets the chunks that *did* come back.

Citations are populated from the vector hits' metadata. ``page`` is left
None because not every parser provides page numbers; future EPIC-007 work
can fill that in for PDF / DOCX once MarkItDown propagates page metadata
through the chunker.

TODO(EPIC-007): Wire ``enrich_memory_links`` + citation enrichment once
the memory-knowledge bridge is stable.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from dashboard.knowledge.metrics import get_metrics_registry

logger = logging.getLogger(__name__)


# Import bridge lazily to avoid circular imports
_bridge_index = None
_bridge_warned_unavailable = False  # Track if we've logged the "unavailable" warning


def _get_bridge_index():
    """Lazily import and get the bridge index singleton.
    
    Returns None if:
    - Bridge is disabled (OSTWIN_KNOWLEDGE_MEMORY_BRIDGE != "1")
    - Bridge module import fails
    - Memory server is unavailable
    
    Logs a warning ONCE when the bridge is unavailable.
    """
    global _bridge_index, _bridge_warned_unavailable
    
    if _bridge_index is None:
        try:
            from dashboard.knowledge.bridge import get_bridge_index, is_bridge_enabled
            if is_bridge_enabled():
                _bridge_index = get_bridge_index()
                if _bridge_index is None:
                    # Bridge enabled but not available
                    if not _bridge_warned_unavailable:
                        logger.warning(
                            "Memory-Knowledge bridge enabled but unavailable; "
                            "memory_links will be empty for all queries. "
                            "This warning will not repeat."
                        )
                        _bridge_warned_unavailable = True
            # If bridge is disabled, we silently return None (no warning needed)
        except ImportError:
            if not _bridge_warned_unavailable:
                logger.warning(
                    "Bridge module not available; memory_links will be empty. "
                    "This warning will not repeat."
                )
                _bridge_warned_unavailable = True
    return _bridge_index


# Hard ceiling on PageRank result count — even the most graph-heavy
# namespace shouldn't surface more than a handful of entities for a single
# query. EPIC-007 may make this configurable.
_MAX_ENTITIES_PER_QUERY = 20


# ---------------------------------------------------------------------------
# Result models (Pydantic — JSON-serialisable for EPIC-005 REST API)
# ---------------------------------------------------------------------------


class ChunkHit(BaseModel):
    """A single chunk returned from vector retrieval."""

    text: str
    score: float
    file_path: str = ""
    filename: str = ""
    chunk_index: int = 0
    total_chunks: int = 1
    file_hash: str = ""
    mime_type: Optional[str] = None
    category_id: Optional[str] = None
    memory_links: list[str] = Field(default_factory=list)


class EntityHit(BaseModel):
    """A single entity returned from graph expansion."""

    id: str
    name: str
    label: str = "entity"
    score: float = 0.0
    description: Optional[str] = None
    category_id: Optional[str] = None


class Citation(BaseModel):
    """A pointer back to the source document for a chunk hit.

    ``snippet_id`` is the zvec doc id. ``page`` is None for parsers that
    don't propagate page numbers (most of MarkItDown's path right now);
    EPIC-007 may extend this for PDF / DOCX.
    """

    file: str
    page: Optional[int] = None
    chunk_index: int = 0
    snippet_id: str = ""


class QueryResult(BaseModel):
    """Top-level result for a single query.

    Wired to the REST surface in EPIC-005 — keep this shape stable. Use
    ``model_dump(mode="json")`` when serialising via FastAPI to ensure the
    enum-like ``mode`` string and any future datetime fields render
    correctly.
    """

    query: str
    mode: str
    namespace: str
    chunks: list[ChunkHit] = Field(default_factory=list)
    entities: list[EntityHit] = Field(default_factory=list)
    answer: Optional[str] = None
    citations: list[Citation] = Field(default_factory=list)
    latency_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# KnowledgeQueryEngine
# ---------------------------------------------------------------------------


class KnowledgeQueryEngine:
    """Per-namespace query engine.

    Constructed once by :meth:`KnowledgeService._get_query_engine` and
    cached for the namespace's lifetime in the service. The engine itself
    is stateless beyond the references it holds; safe to call concurrently
    from multiple threads provided the underlying handles are thread-safe
    (Kuzu reads are).

    Parameters
    ----------
    namespace:
        The namespace this engine queries against — informational only,
        used to populate :class:`QueryResult.namespace`.
    kuzu_graph:
        A :class:`KuzuLabelledPropertyGraph` instance. Reused across
        queries; never closed by the engine.
    embedder:
        A :class:`KnowledgeEmbedder` (or duck-typed equivalent). The query
        text is embedded once per query via :meth:`embed_one`.
    llm:
        A :class:`KnowledgeLLM` (or duck-typed equivalent). Only invoked
        when ``mode="summarized"``; always checked via :meth:`is_available`
        first so a missing LLM API key can't crash a query.
    """

    def __init__(
        self,
        namespace: str,
        kuzu_graph: Any,
        embedder: Any,
        llm: Any,
        graph_rag_engine: Any = None,
        language: str = "English",
        **kwargs: Any,
    ) -> None:
        self.namespace = namespace
        self.kg = kuzu_graph
        self.embedder = embedder
        self.llm = llm
        self.graph_rag_engine = graph_rag_engine
        vector_store = kwargs.get("vector_store")
        self.vector_store = vector_store
        if vector_store is not None:
            self.vs = vector_store
        self.language = language

    # ---- Public entrypoint -----------------------------------------------

    def query(
        self,
        query: str,
        *,
        mode: str = "graph",
        top_k: int = 10,
        threshold: float = 0.5,
        category: Optional[str] = None,
        parameter: str = "",
    ) -> QueryResult:
        """Run a single query against this engine's namespace.

        See module docstring for ``mode`` semantics. ``threshold`` filters
        out vector hits with score < threshold (KuzuDB returns COSINE
        distance — lower is better, converted to similarity). ``category``
        scopes both the vector search and the graph expansion when set.

        ``parameter`` is reserved for future use (e.g. a domain hint for
        the LLM); it's accepted on the API surface so EPIC-005 doesn't
        need a follow-up signature change.
        """
        t0 = time.perf_counter()
        result = QueryResult(query=query, mode=mode, namespace=self.namespace)

        # Get metrics registry
        metrics = get_metrics_registry()
        metrics.counter("query_total").inc()

        # --- 1) Raw mode — delegate to KG graph engine ------------------
        #
        # The KG graph engine owns all vector retrieval now. For "raw"
        # mode we fetch chunks + entities directly via the graph layer
        # and return immediately. "graph" and "summarized" modes fall
        # through to steps 2–3 below.
        #
        # TODO(EPIC-007): enrich_memory_links + citation enrichment
        # should be wired here once the bridge is stable.
        if mode == "raw":
            try:
                kg_nodes = self.kg.get_all_nodes(
                    context=query,
                    category_id=category,
                    limit=top_k,
                )
                chunks, entities = self._split_kg_nodes(kg_nodes)
                # Apply threshold filter — chunks from KuzuDB have
                # score=1.0 (placeholder) by default; a threshold > 1.0
                # filters everything.  Future: propagate real cosine
                # similarity from the vector index.
                if threshold > 0:
                    chunks = [c for c in chunks if c.score >= threshold]
                result.chunks = chunks
                result.entities = entities
                result.citations = [self._chunk_to_citation(c) for c in chunks]
            except Exception as exc:  # noqa: BLE001
                logger.error("KG raw search failed for %r: %s", query, exc)
                result.warnings.append(f"vector_search_failed: {exc}")
                metrics.counter("query_errors_total").inc()

            result.latency_ms = int((time.perf_counter() - t0) * 1000)
            return result

        # Optional legacy vector-store retrieval for callers/tests that still
        # inject a separate vector_store. The graph layer is authoritative for
        # raw mode above; graph/summarized modes use these chunks only as LLM
        # fallback context.
        if getattr(self, "vs", None) is not None:
            try:
                vector_hits = self.vs.search(query, top_k=top_k)
                result.chunks = self._vector_hits_to_chunks(vector_hits, threshold=threshold)
                result.citations = [self._chunk_to_citation(c) for c in result.chunks]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Legacy vector_store search failed: %s", exc)

        # --- 2) Graph expansion (graph + summarized modes) -----------
        if self.graph_rag_engine is not None:
            # Delegate to GraphRAGQueryEngine for hit-aware PageRank scoring.
            try:
                entity_hits = self._graph_expand_via_rag_engine(query, category=category)
                # Merge with vector-search entities (deduplicate by id)
                existing_ids = {e.id for e in result.entities}
                for eh in entity_hits:
                    if eh.id not in existing_ids:
                        result.entities.append(eh)
                        existing_ids.add(eh.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("GraphRAGQueryEngine expansion failed, falling back: %s", exc)
                try:
                    entity_hits = self._graph_expand(query, category=category)
                    existing_ids = {e.id for e in result.entities}
                    for eh in entity_hits:
                        if eh.id not in existing_ids:
                            result.entities.append(eh)
                            existing_ids.add(eh.id)
                except Exception as fallback_exc:  # noqa: BLE001
                    logger.warning("Fallback graph expansion also failed: %s", fallback_exc)
                    result.warnings.append(f"graph_expansion_failed: {exc}")
        else:
            try:
                entity_hits = self._graph_expand(query, category=category)
                existing_ids = {e.id for e in result.entities}
                for eh in entity_hits:
                    if eh.id not in existing_ids:
                        result.entities.append(eh)
                        existing_ids.add(eh.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Graph expansion failed: %s", exc)
                result.warnings.append(f"graph_expansion_failed: {exc}")

        if mode == "graph":
            result.latency_ms = int((time.perf_counter() - t0) * 1000)
            return result

        # --- 3) LLM aggregation (summarized only) --------------------
        if mode == "summarized":
            if self.graph_rag_engine is not None:
                # Use GraphRAGQueryEngine multi-step plan + execute pipeline.
                try:
                    answer = self.graph_rag_engine.custom_query(
                        query, parameter=parameter, category_id=category,
                    )
                    if answer:  # non-empty string — real answer
                        result.answer = answer
                    else:
                        # custom_query returned None/empty — fall back
                        fallback = self._fallback_summarize(result.chunks, query)
                        result.answer = fallback if fallback else None
                        if not result.answer:
                            result.warnings.append("llm_unavailable")
                except Exception as exc:  # noqa: BLE001
                    logger.error("GraphRAGQueryEngine summarization failed: %s", exc)
                    result.warnings.append(f"graph_rag_summarization_failed: {exc}")
                    # Fall back to simple LLM aggregation.
                    fallback = self._fallback_summarize(result.chunks, query)
                    result.answer = fallback if fallback else None
                    if not result.answer:
                        result.warnings.append("llm_unavailable")
            else:
                fallback = self._fallback_summarize(result.chunks, query)
                result.answer = fallback if fallback else None
                if not result.answer:
                    result.warnings.append("llm_unavailable")

        result.latency_ms = int((time.perf_counter() - t0) * 1000)
        # Record query latency histogram (convert ms to seconds)
        metrics.histogram("query_latency_seconds").observe(result.latency_ms / 1000.0)
        return result

    # ---- Graph visualisation ---------------------------------------------

    def get_graph(self, *, limit: int = 200) -> dict:
        """Return ``{nodes, edges, stats}`` for visualization.

        ``limit`` caps the number of entity nodes returned (and therefore
        the maximum number of edges, since edges are filtered to those
        connecting two surviving nodes). Failures are caught and an
        ``error`` field is added to the response — never raises so the
        REST handler can return a 200 with an empty graph + diagnostic.
        """
        try:
            entities = self.kg.get_all_nodes(label_type="entity")
        except Exception as exc:  # noqa: BLE001
            logger.error("get_graph: get_all_nodes failed: %s", exc)
            return {
                "nodes": [],
                "edges": [],
                "stats": {"node_count": 0, "edge_count": 0},
                "error": str(exc),
            }

        # Bound the result before doing anything else expensive.
        if limit is not None and limit >= 0:
            entities = list(entities)[:limit]

        nodes = [
            {
                "id": getattr(e, "id", ""),
                "label": getattr(e, "label", "") or getattr(e, "id", ""),
                "name": getattr(e, "name", "") or getattr(e, "id", ""),
                "score": 1.0,
                "properties": getattr(e, "properties", {}) or {},
            }
            for e in entities
        ]
        entity_ids = {n["id"] for n in nodes if n["id"]}

        try:
            relations = self.kg.get_all_relations()
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_graph: get_all_relations failed: %s", exc)
            relations = []

        edges = [
            {
                "source": getattr(r, "source_id", ""),
                "target": getattr(r, "target_id", ""),
                "label": getattr(r, "label", "") or "RELATES",
            }
            for r in relations
            if getattr(r, "source_id", None) in entity_ids
            and getattr(r, "target_id", None) in entity_ids
        ]

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {"node_count": len(nodes), "edge_count": len(edges)},
        }

    # ---- Internals --------------------------------------------------------

    def _split_kg_nodes(self, kg_nodes: list) -> tuple[list[ChunkHit], list[EntityHit]]:
        """Split KuzuDB results into ChunkHit and EntityHit lists.

        KuzuDB's ``get_all_nodes(context=...)`` returns a mix of
        :class:`ChunkNode` and :class:`EntityNode`. We separate them
        and convert to the API-facing Pydantic models.
        """
        from llama_index.core.graph_stores.types import EntityNode, ChunkNode  # noqa: WPS433

        chunks: list[ChunkHit] = []
        entities: list[EntityHit] = []

        for node in (kg_nodes or []):
            props = getattr(node, "properties", {}) or {}
            if isinstance(node, ChunkNode) or getattr(node, "label", "") == "text_chunk":
                chunks.append(ChunkHit(
                    text=getattr(node, "text", "") or "",
                    score=1.0,  # KuzuDB vector search returns by distance order
                    file_path=str(props.get("file_path", "")),
                    filename=str(props.get("filename", "")),
                    chunk_index=int(props.get("chunk_index", 0)),
                    total_chunks=int(props.get("total_chunks", 1)),
                    file_hash=str(props.get("file_hash", "")),
                    mime_type=props.get("mime_type"),
                    category_id=props.get("category_id"),
                ))
            else:
                # EntityNode
                entities.append(EntityHit(
                    id=str(getattr(node, "id", "")),
                    name=str(getattr(node, "name", "")) or str(getattr(node, "id", "")),
                    label=str(getattr(node, "label", "entity")),
                    score=1.0,
                    description=str(props.get("entity_description", "")) or None,
                    category_id=str(props.get("category_id", "")) or None,
                ))

        return chunks, entities

    def _vector_hits_to_chunks(self, hits: list, threshold: float = 0.0) -> list[ChunkHit]:
        chunks: list[ChunkHit] = []
        for hit in hits or []:
            score = float(getattr(hit, "score", 0.0) or 0.0)
            if score < threshold:
                continue
            meta = getattr(hit, "metadata", {}) or {}
            chunks.append(ChunkHit(
                text=str(getattr(hit, "text", "") or ""),
                score=score,
                file_path=str(meta.get("file_path", "")),
                filename=str(meta.get("filename", "")),
                chunk_index=int(meta.get("chunk_index", 0)),
                total_chunks=int(meta.get("total_chunks", 1)),
                file_hash=str(meta.get("file_hash", "")),
                mime_type=meta.get("mime_type"),
                category_id=meta.get("category_id"),
            ))
        return chunks

    def _chunk_to_citation(self, chunk: ChunkHit) -> Citation:
        """Convert a ChunkHit to a Citation."""
        return Citation(
            file=chunk.file_path or chunk.filename,
            page=None,
            chunk_index=chunk.chunk_index,
            snippet_id="",
        )

    def _enrich_memory_links(self, chunks: list[ChunkHit]) -> None:
        """Enrich chunks with memory_links from the bridge index.
        
        This is a no-op if the bridge is disabled or unavailable.
        Modifies chunks in-place.
        """
        bridge = _get_bridge_index()
        if bridge is None:
            return
        
        for chunk in chunks:
            if not chunk.file_hash:
                continue
            try:
                note_ids = bridge.lookup(
                    namespace=self.namespace,
                    file_hash=chunk.file_hash,
                    chunk_idx=chunk.chunk_index,
                )
                chunk.memory_links = note_ids
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Bridge lookup failed for %s/%s#%d: %s",
                    self.namespace,
                    chunk.file_hash,
                    chunk.chunk_index,
                    exc,
                )

    def _graph_expand_via_rag_engine(
        self,
        query: str,
        *,
        category: Optional[str] = None,
    ) -> list[EntityHit]:
        """Expand entities using :class:`GraphRAGQueryEngine`'s pipeline.

        Uses the full vector-retrieval → triplet scoring → PageRank pipeline
        for hit-aware personalisation.  Converts the engine's ``graph_result``
        output (networkx nodes with scores) into :class:`EntityHit` objects.
        """
        engine = self.graph_rag_engine
        # Run vector retrieval + PageRank through the engine.
        engine.get_nodes(query, category_id=category)
        # graph_result() returns a YAML string of ranked nodes/edges from
        # the TrackVectorRetriever's networkx DiGraph.
        import yaml  # noqa: WPS433

        raw_yaml = engine.graph_result()
        parsed = yaml.safe_load(raw_yaml) or {}
        knowledge_str = parsed.get("knowledge", "")
        knowledge_nodes = yaml.safe_load(knowledge_str) if knowledge_str else []

        out: list[EntityHit] = []
        for node_data in (knowledge_nodes or [])[:_MAX_ENTITIES_PER_QUERY]:
            if not isinstance(node_data, dict):
                continue
            node_id = node_data.get("id", "")
            out.append(
                EntityHit(
                    id=str(node_id),
                    name=str(node_data.get("label", node_id)),
                    label="entity",
                    score=float(node_data.get("score", 0.0)),
                    description=str(node_data.get("citation", "")),
                )
            )
        return out

    def _fallback_summarize(self, chunks: list[ChunkHit], query: str) -> Optional[str]:
        """Simple LLM aggregation fallback (no GraphRAGQueryEngine).

        Used when :attr:`graph_rag_engine` is ``None`` or when the full
        graph-RAG summarization fails.

        The LLM instance is constructed by :class:`KnowledgeService._get_llm`
        which reads the ``knowledge_llm_model`` setting from MasterSettings.
        """
        llm_available = False
        try:
            llm_available = bool(self.llm.is_available())
        except Exception:  # noqa: BLE001
            llm_available = False

        if not llm_available:
            logger.debug(
                "LLM unavailable for summarize (model=%s) — returning None",
                getattr(self.llm, "model", "?"),
            )
            return None

        summaries = [c.text for c in chunks if c.text]
        if not summaries:
            return ""

        try:
            logger.debug(
                "Summarizing %d chunks with knowledge_llm_model=%s",
                len(summaries),
                getattr(self.llm, "model", "?"),
            )
            return self.llm.aggregate_answers(summaries, query, language=self.language)
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM aggregation fallback failed: %s", exc)
            return None

    def _graph_expand(
        self,
        query: str,
        *,
        category: Optional[str] = None,
    ) -> list[EntityHit]:
        """Use Kuzu PageRank to find entities related to the vector hits.

        Pulls all entities for the namespace, runs PageRank with a
        uniform personalisation vector. Returns at most
        :data:`_MAX_ENTITIES_PER_QUERY` entities, sorted by PageRank
        score descending.

        Returns ``[]`` (not raise) when:

        - The Kuzu graph has no entities (e.g. ingest ran without a
          configured LLM, so no entities were extracted).
        - PageRank fails for any reason — the warning is captured by the
          caller via the surrounding try/except in :meth:`query`.
        """
        try:
            entities = self.kg.get_all_nodes(label_type="entity", category_id=category)
        except Exception as exc:  # noqa: BLE001
            logger.warning("_graph_expand: get_all_nodes failed: %s", exc)
            return []

        entities = list(entities or [])
        if not entities:
            return []

        # Uniform personalisation — every entity gets equal weight. Good
        # enough for MVP; EPIC-007 can swap in a hit-aware vector.
        weight = 1.0 / float(len(entities))
        personalize = {
            getattr(e, "id", str(i)): weight
            for i, e in enumerate(entities)
            if getattr(e, "id", None)
        }
        if not personalize:
            return []

        try:
            ranked = self.kg.pagerank(personalize, category_id=category)
        except Exception as exc:  # noqa: BLE001
            logger.warning("_graph_expand: pagerank failed: %s", exc)
            return []

        # ``ranked`` is List[(node_id, score)] sorted by score DESC.
        # Build an id → entity lookup so we can pull name / label / props.
        ent_by_id = {getattr(e, "id", None): e for e in entities}
        out: list[EntityHit] = []
        for item in (ranked or [])[:_MAX_ENTITIES_PER_QUERY]:
            try:
                ent_id, score = item[0], float(item[1])
            except (TypeError, IndexError, ValueError):
                continue
            ent = ent_by_id.get(ent_id)
            name = getattr(ent, "name", None) if ent is not None else None
            label = getattr(ent, "label", None) if ent is not None else None
            props = getattr(ent, "properties", None) if ent is not None else None
            description = None
            cat_id = None
            if isinstance(props, dict):
                description = props.get("description")
                cat_id = props.get("category_id")
            out.append(
                EntityHit(
                    id=str(ent_id),
                    name=str(name) if name else str(ent_id),
                    label=str(label) if label else "entity",
                    score=score,
                    description=str(description) if description else None,
                    category_id=str(cat_id) if cat_id else None,
                )
            )
        return out


__all__ = [
    "ChunkHit",
    "Citation",
    "EntityHit",
    "KnowledgeQueryEngine",
    "QueryResult",
]

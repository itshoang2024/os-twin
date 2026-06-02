"""Knowledge-graph extractor — wraps a :class:`KnowledgeLLM` to extract
entities and relationships from text chunks.

Refactor notes (EPIC-001):
- Removed DSPy + DspyLlamaIndexAdapter (not available in dashboard).
- Now takes a :class:`KnowledgeLLM` instance directly. The LLM call goes
  through ``KnowledgeLLM.extract_entities``.
- Removed the `_create_extraction_prompt` machinery — prompts are baked into
  ``KnowledgeLLM`` so callers only need to pass language + domain.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from llama_index.core.async_utils import run_jobs  # noqa: F401 — kept for back-compat
from llama_index.core.graph_stores.types import (
    KG_NODES_KEY,
    KG_RELATIONS_KEY,
    EntityNode,
    Relation,
)
from llama_index.core.schema import BaseNode, TransformComponent

from dashboard.knowledge.embeddings import KnowledgeEmbedder
from dashboard.knowledge.llm import KnowledgeLLM

logger = logging.getLogger(__name__)


class ExtractionStatus(Enum):
    """Status of graph extraction process."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class ExtractionConfig:
    """Configuration for graph extraction."""

    max_retries: int = 3
    retry_delay: float = 1.0
    timeout_seconds: float = 240.0
    min_entity_length: int = 2
    max_entity_length: int = 100
    min_entities_per_chunk: int = 0
    max_entities_per_chunk: int = 50
    enable_validation: bool = True
    enable_performance_monitoring: bool = True
    batch_size: int = 10


@dataclass
class ExtractionMetrics:
    """Aggregate metrics for an extraction batch."""

    total_nodes: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    candidate_count: int = 0
    average_processing_time: float = 0.0
    errors: List[str] = field(default_factory=list)


class GraphRAGExtractor(TransformComponent):
    """Knowledge-graph extractor backed by ``KnowledgeLLM``.

    Implements the LlamaIndex ``TransformComponent`` interface so it can be
    plugged into ``PropertyGraphIndex.from_existing(...)``.
    """

    # Pydantic-friendly field declarations
    llm: Optional[Any] = None
    embedder: Optional[Any] = None
    config: Optional[ExtractionConfig] = None
    metrics: Optional[Any] = None
    domain_prompt: str = ""
    language: str = "English"
    max_paths_per_chunk: int = 10
    num_workers: int = 1
    ontology_profile: Optional[Any] = None
    candidate_store: Optional[Any] = None
    namespace: str = ""

    def __init__(
        self,
        llm: KnowledgeLLM,
        domain_prompt: str = "",
        language: str = "English",
        max_paths_per_chunk: int = 10,
        num_workers: int = 1,
        config: Optional[ExtractionConfig] = None,
        embedder: Optional[KnowledgeEmbedder] = None,
        ontology_profile: Optional[Any] = None,
        candidate_store: Optional[Any] = None,
        namespace: str = "",
        # Legacy kwargs accepted for back-compat; ignored.
        extract_prompt: Any = None,
        sys_prompt: Any = None,
        parse_fn: Any = None,
        **_: Any,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.embedder = embedder or KnowledgeEmbedder()
        self.config = config or ExtractionConfig()
        self.metrics = ExtractionMetrics()
        self.domain_prompt = domain_prompt or ""
        self.language = language or "English"
        self.max_paths_per_chunk = max_paths_per_chunk
        self.num_workers = num_workers
        self.ontology_profile = ontology_profile
        self.candidate_store = candidate_store
        self.namespace = namespace or getattr(ontology_profile, "namespace", "") or ""

    # -- Sync entrypoint ------------------------------------------------

    def __call__(self, nodes: List[BaseNode], show_progress: bool = False, **kwargs: Any) -> List[BaseNode]:
        """Run extraction synchronously — one node at a time.

        Previous implementation nested ThreadPoolExecutor → event loop →
        asyncio.to_thread → _run_sync → asyncio.run(), which caused
        "cannot schedule new futures after shutdown" because asyncio.run()
        shuts down the default executor on exit, poisoning subsequent
        asyncio.to_thread calls in the same loop.

        The fix: call ``extract_entities`` directly (it is already sync —
        it handles async→sync bridging internally via ``_run_sync``).
        No nested executors, no event-loop conflicts.
        """
        import time as _time

        if not nodes:
            return []
        logger.info("Starting graph extraction for %d nodes", len(nodes))
        self.metrics = ExtractionMetrics()

        batch_t0 = _time.monotonic()
        results: List[BaseNode] = []
        for node in nodes:
            try:
                node_t0 = _time.monotonic()
                result = self._extract_single_sync(node)
                node_dt = _time.monotonic() - node_t0
                n_entities = len(result.metadata.get(KG_NODES_KEY, []))
                n_rels = len(result.metadata.get(KG_RELATIONS_KEY, []))
                logger.info(
                    "[TRACE] extractor/node: %.3fs, %s, %d entities, %d relations",
                    node_dt, node.id_, n_entities, n_rels,
                )
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                logger.error("GraphRAGExtractor failed for node %s: %s", node.id_, exc)
                results.append(self._create_empty_extraction_result(node, str(exc)))

        batch_dt = _time.monotonic() - batch_t0
        logger.info(
            "[TRACE] extractor/batch: %.3fs, %d nodes, %d entities, %d relations",
            batch_dt, len(nodes),
            self.metrics.total_entities, self.metrics.total_relationships,
        )
        return results

    # -- Sync extraction (no nested executors) --------------------------

    def _extract_single_sync(self, node: BaseNode) -> BaseNode:
        """Extract entities from a single node with retry — fully synchronous.

        Calls ``self.llm.extract_entities`` directly (it handles its own
        async→sync bridging internally).  Retries up to ``config.max_retries``
        times with linear back-off.
        """
        import time as _time

        if not hasattr(node, "text"):
            return self._create_empty_extraction_result(node, "node missing .text")

        text = node.get_content(metadata_mode="llm")
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                if attempt > 0:
                    _time.sleep(self.config.retry_delay * attempt)
                t_llm_start = _time.monotonic()
                entities, relations = self.llm.extract_entities(
                    text,
                    self.language,
                    self.domain_prompt,
                    ontology_profile_hint=self.ontology_profile,
                )
                t_llm = _time.monotonic() - t_llm_start
                logger.info(
                    "[TRACE] extractor/llm_call: %.3fs, attempt=%d, node=%s, %d entities, %d relations",
                    t_llm, attempt + 1, node.id_, len(entities), len(relations),
                )
                entities, relations = self._normalize_extraction_payload(node, text, entities, relations)
                return self._create_extraction_result(node, entities, relations)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                t_llm = _time.monotonic() - t_llm_start
                logger.error(
                    "Extraction attempt %d failed for %s (%.3fs): %s",
                    attempt + 1, node.id_, t_llm, exc,
                )

        return self._create_empty_extraction_result(node, str(last_error))

    # -- Async pipeline (kept for callers that prefer async) ------------

    async def acall(self, nodes: List[BaseNode], show_progress: bool = False, **kwargs: Any) -> List[BaseNode]:
        """Async extraction — runs ``_extract_single_sync`` concurrently.

        Uses ``asyncio.to_thread`` to offload the blocking sync work and
        ``run_jobs`` to bound concurrency to ``self.num_workers``. Each
        ``_extract_single_sync`` call already has its own retry logic with
        linear back-off, so no extra retry layer is needed here.

        NOTE: We deliberately do NOT wrap this in a ThreadPoolExecutor.
        ``run_jobs`` already manages its own internal pool sized by
        ``workers``. A second ThreadPoolExecutor + ``run_in_executor``
        creates double-scheduling: the ``with`` block can close the pool
        while ``run_jobs`` still holds pending futures, causing
        ``CancelledError`` or "cannot schedule new futures after shutdown".
        """
        if not nodes:
            return []
        logger.info("Starting async graph extraction for %d nodes", len(nodes))
        self.metrics = ExtractionMetrics()

        async def _process_node(node: BaseNode) -> BaseNode:
            try:
                return await asyncio.to_thread(self._extract_single_sync, node)
            except Exception as exc:  # noqa: BLE001
                logger.error("Async extraction failed for node %s: %s", node.id_, exc)
                return self._create_empty_extraction_result(node, str(exc))

        jobs = [_process_node(node) for node in nodes]
        try:
            results = await run_jobs(
                jobs,
                show_progress=show_progress,
                workers=self.num_workers,
            )
            return list(results)
        except Exception as exc:
            logger.error("acall batch extraction failed: %s", exc)
            return [self._create_empty_extraction_result(node, str(exc)) for node in nodes]

    def _normalize_extraction_payload(
        self,
        node: BaseNode,
        text: str,
        entities: list,
        relations: list,
    ) -> tuple[list, list]:
        """Normalize extracted labels and persist ontology review candidates."""

        profile = self.ontology_profile
        if profile is None:
            # Legacy namespaces must behave exactly as before.
            return entities, relations

        from dashboard.knowledge.ontology.normalizer import normalize_concept, normalize_relation

        source_hash = str(node.metadata.get("file_hash") or node.metadata.get("chunk_hash") or "")
        source = str(node.metadata.get("file_path") or node.metadata.get("filename") or node.id_)
        sample_text = text[:500]
        candidate_count = 0

        normalized_entities: list = []
        entity_type_by_name: dict[str, str] = {}
        for entity in entities:
            if isinstance(entity, dict):
                item = dict(entity)
                raw_type = str(item.get("type", ""))
                normalized = normalize_concept(raw_type, profile)
                item["type"] = normalized.normalized
                if normalized.classification != "canonical":
                    item.setdefault("metadata", {})
                    item["original_type"] = normalized.original
                    item["ontology_normalization"] = normalized.classification
                if normalized.classification == "candidate":
                    candidate = self._record_candidate(
                        candidate_type="concept_type",
                        original_label=normalized.original,
                        source=source,
                        source_hash=source_hash,
                        sample_text=sample_text,
                        suggested_canonical=normalized.normalized,
                        confidence=float(item.get("confidence") or 0.5),
                        metadata={"node_id": str(node.id_), "entity_name": item.get("name", "")},
                    )
                    if candidate is not None and candidate.status == "pending":
                        candidate_count += 1
                    item["ontology_candidate_id"] = getattr(candidate, "id", None)
                entity_type_by_name[str(item.get("name", ""))] = str(item.get("type", ""))
                normalized_entities.append(item)
            else:
                normalized_entities.append(entity)

        normalized_relations: list = []
        for rel in relations:
            if isinstance(rel, dict):
                item = dict(rel)
                raw_label = str(item.get("relation", ""))
                normalized = normalize_relation(raw_label, profile)
                item["original_relation"] = raw_label
                item["relation"] = normalized.normalized if normalized.classification != "candidate" else raw_label
                item["ontology_normalization"] = normalized.classification
                if normalized.classification == "candidate":
                    candidate = self._record_candidate(
                        candidate_type="relationship_type",
                        original_label=normalized.original,
                        source=source,
                        source_hash=source_hash,
                        sample_text=sample_text,
                        suggested_canonical=normalized.normalized,
                        confidence=float(item.get("confidence") or 0.5),
                        metadata={
                            "node_id": str(node.id_),
                            "source_entity": item.get("source", ""),
                            "target_entity": item.get("target", ""),
                            "source_type": entity_type_by_name.get(str(item.get("source", "")), ""),
                            "target_type": entity_type_by_name.get(str(item.get("target", "")), ""),
                        },
                    )
                    if candidate is not None and candidate.status == "pending":
                        candidate_count += 1
                    item["ontology_candidate_id"] = getattr(candidate, "id", None)
                normalized_relations.append(item)
            else:
                normalized_relations.append(rel)

        if candidate_count and self.metrics is not None:
            self.metrics.candidate_count += candidate_count
        node.metadata["ontology_candidate_count"] = candidate_count
        return normalized_entities, normalized_relations

    def _record_candidate(self, **kwargs: Any) -> Any | None:
        """Persist a candidate if candidate storage is configured."""

        if self.candidate_store is None or not self.namespace:
            return None
        try:
            return self.candidate_store.upsert_pending(self.namespace, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist ontology candidate: %s", exc)
            return None

    # -- Result builders ------------------------------------------------

    def _create_extraction_result(
        self,
        node: BaseNode,
        entities: list,
        entities_relationship: list,
    ) -> BaseNode:
        existing_nodes = node.metadata.pop(KG_NODES_KEY, [])
        existing_relations = node.metadata.pop(KG_RELATIONS_KEY, [])
        entity_metadata = node.metadata.copy()

        if entities:
            entity_texts: list[str] = []
            for entity in entities:
                if isinstance(entity, dict):
                    name = entity.get("name", "")
                    etype = entity.get("type", "")
                    desc = entity.get("description", "")
                else:
                    name, etype, desc = entity
                entity_texts.append(".".join([str(name), str(etype), str(desc)]))
            try:
                embeddings = self.embedder.embed(entity_texts)
                logger.info("Batch embedding completed for %s entities", len(entities))
            except Exception as exc:  # noqa: BLE001
                logger.error("Batch embedding failed (%s); falling back to per-text", exc)
                embeddings = [self.embedder.embed_one(t) for t in entity_texts]
        else:
            embeddings = []

        for entity, embedding in zip(entities, embeddings):
            if isinstance(entity, dict):
                name = entity.get("name", "")
                etype = entity.get("type", "")
                desc = entity.get("description", "")
            else:
                name, etype, desc = entity
            entity_metadata["entity_description"] = desc
            entity_metadata["node_id"] = str(node.id_)
            existing_nodes.append(
                EntityNode(
                    name=name,
                    label=etype,
                    properties=dict(entity_metadata),
                    embedding=embedding,
                )
            )

        relation_metadata = node.metadata.copy()
        for rel in entities_relationship:
            if isinstance(rel, dict):
                subj = rel.get("source", "")
                obj = rel.get("target", "")
                rlabel = rel.get("relation", "")
                desc = rel.get("description", "")
            else:
                subj, obj, rlabel, desc = rel
            relation_metadata["relationship_description"] = desc
            relation_metadata["node_id"] = str(node.id_)
            if isinstance(rel, dict):
                for key in ("original_relation", "ontology_normalization", "ontology_candidate_id"):
                    if rel.get(key) is not None:
                        relation_metadata[key] = rel.get(key)
            existing_relations.append(
                Relation(
                    label=rlabel,
                    source_id=subj,
                    target_id=obj,
                    properties=dict(relation_metadata),
                )
            )

        node.metadata[KG_NODES_KEY] = existing_nodes
        node.metadata[KG_RELATIONS_KEY] = existing_relations

        if self.metrics is not None:
            self.metrics.successful_extractions += 1
            self.metrics.total_nodes += 1
            self.metrics.total_entities += len(existing_nodes)
            self.metrics.total_relationships += len(existing_relations)

        # Ensure the source node (ChunkNode) also carries an embedding so it
        # can be found via KuzuDB's QUERY_VECTOR_INDEX. If the node already
        # has an embedding (e.g. from the PropertyGraphIndex embed_model) we
        # leave it alone; otherwise we generate one from its text content.
        if not getattr(node, "embedding", None):
            try:
                text_for_embed = node.get_content(metadata_mode="none")
                if text_for_embed and text_for_embed.strip():
                    node.embedding = self.embedder.embed_one(text_for_embed)
                    logger.debug("Embedded source ChunkNode %s (%d chars)", node.id_, len(text_for_embed))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to embed source ChunkNode %s: %s", node.id_, exc)

        logger.info(
            "Extraction: %d entities, %d relations",
            len(existing_nodes),
            len(existing_relations),
        )
        return node

    def _create_empty_extraction_result(self, node: BaseNode, error_msg: str) -> BaseNode:
        node.metadata[KG_NODES_KEY] = []
        node.metadata[KG_RELATIONS_KEY] = []
        node.metadata["extraction_error"] = error_msg
        node.metadata["extraction_status"] = ExtractionStatus.FAILED.value

        if self.metrics is not None:
            self.metrics.failed_extractions += 1
            self.metrics.total_nodes += 1

        # Ensure the ChunkNode still gets an embedding even when extraction
        # fails. Without this the node is invisible to KuzuDB's
        # QUERY_VECTOR_INDEX and unreachable via vector search.
        if not getattr(node, "embedding", None):
            try:
                text_for_embed = node.get_content(metadata_mode="none")
                if text_for_embed and text_for_embed.strip():
                    node.embedding = self.embedder.embed_one(text_for_embed)
                    logger.debug(
                        "Embedded failed-extraction ChunkNode %s (%d chars)",
                        node.id_,
                        len(text_for_embed),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to embed ChunkNode %s after extraction error: %s",
                    node.id_,
                    exc,
                )

        return node

    def get_metrics(self) -> ExtractionMetrics:
        return self.metrics

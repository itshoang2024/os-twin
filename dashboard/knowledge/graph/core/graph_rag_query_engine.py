"""Graph-RAG query engine — combines vector search with graph reasoning.

Refactor notes (EPIC-001):
- Removed dependency on llama-index ``LLM`` and DSPy adapters.
- ``llm`` and ``plan_llm`` attributes are now :class:`KnowledgeLLM` instances.
- Aggregation uses :meth:`KnowledgeLLM.aggregate_answers` directly.
- Removed ``run_async_in_thread`` (was an `app.utils` helper); use a small
  inline event-loop runner.

Shared citation utilities and the async runner are now imported from
:mod:`dashboard.knowledge.graph.core.citation` — the old names
(``_run_async``, ``_is_uuid_node``, ``_resolve_chunk_metadata``,
``FILE_METADATA_FIELDS``) are re-exported here for backward compatibility.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from pydantic import PrivateAttr

import yaml
from llama_index.core import PropertyGraphIndex, StorageContext
from llama_index.core.graph_stores.types import KG_SOURCE_REL
from llama_index.core.query_engine import CustomQueryEngine
from llama_index.core.query_engine.custom import STR_OR_RESPONSE_TYPE
from llama_index.core.vector_stores.types import BasePydanticVectorStore

from dashboard.knowledge.config import PAGERANK_SCORE_THRESHOLD
from dashboard.knowledge.graph.core.citation import (
    FILE_METADATA_FIELDS,  # backward-compat re-export
    build_citation_dict,
    format_citation,
    is_uuid,
    resolve_chunk_metadata,
    run_async,
)
from dashboard.knowledge.graph.core.graph_rag_extractor import GraphRAGExtractor
from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore
from dashboard.knowledge.graph.core.query_executioner import QueryExecutor
from dashboard.knowledge.graph.core.track_vector_retriever import TrackVectorRetriever
from dashboard.knowledge.llm import KnowledgeLLM

logger = logging.getLogger(__name__)

# Backward-compat aliases — existing imports still work.
_run_async = run_async


class GraphRAGQueryEngine(CustomQueryEngine):
    """Query engine combining vector search and graph-based reasoning."""

    graph_store: GraphRAGStore
    index: PropertyGraphIndex
    vector_store: BasePydanticVectorStore
    storage_context: StorageContext
    kg_extractor: GraphRAGExtractor
    llm: Any  # KnowledgeLLM
    plan_llm: Any  # KnowledgeLLM
    similarity_top_k: int = 20
    similarity_score: float = 0.2
    data_instruction: str = ""
    language: str = "English"
    node_id: str
    embed_model: Any = None  # EmbedderAdapter (BaseEmbedding)
    include_graph: bool = False
    stream_handler: Optional[Callable] = None
    max_queries: int = 3
    _tracking: Any = PrivateAttr(default=None)

    @property
    def tracking(self):
        if self._tracking is None:
            _embed = self.embed_model or getattr(self.index, "_embed_model", None)
            self._tracking = TrackVectorRetriever(
                engine=self,
                graph_store=self.index.property_graph_store,
                vector_store=self.index.vector_store,
                include_text=False,
                embed_model=_embed,
            )
        return self._tracking

    # -- Citation helpers -----------------------------------------------

    def create_citation(self, metadata: dict) -> dict | None:
        """Build a citation dict for a graph node that carries UUID references.

        Delegates to :func:`build_citation_dict` from the shared citation
        module.  Returns ``None`` when no resolvable UUID is found or
        metadata is empty.
        """
        return build_citation_dict(metadata, self.index)

    def _create_citation(self, metadata: dict, uuid_fallback: str = "") -> str:
        """Backward-compatible citation string builder used by older tests.

        ``create_citation`` returns the newer structured citation dictionary;
        older call sites expected a human-readable string containing file/page
        information plus a uuid trace. Keep that private helper as a thin
        wrapper around the shared formatter.
        """
        metadata = metadata or {}
        citation = format_citation(metadata, uuid_fallback=uuid_fallback)
        has_file_identifier = bool(metadata.get("filename") or metadata.get("file_path"))
        if has_file_identifier and uuid_fallback and "uuid:" not in citation:
            return f"{citation}{{uuid:{uuid_fallback}}}"
        return citation

    @staticmethod
    def _is_uuid_node(value: str) -> bool:
        """Backward-compat wrapper around :func:`is_uuid`."""
        return is_uuid(value)

    def _resolve_chunk_metadata(self, uuid_key: str) -> dict | None:
        """Backward-compat wrapper around :func:`resolve_chunk_metadata`."""
        return resolve_chunk_metadata(self.index, uuid_key)

    # -- Graph snapshot -------------------------------------------------

    def graph_result(self):
        graph = self.tracking.graph
        nodes: list[dict] = []
        for node_id, node_data in graph.nodes(data=True):
            try:
                score = node_data.get("score", 0.0)
                properties = node_data.get("properties", {})
                citation = self._create_citation(properties, node_id)
                nodes.append(
                    {
                        "id": node_id,
                        "citation": citation,
                        "label": node_data.get("label", node_id),
                        "score": score,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Error processing node %s: %s", node_id, exc)
                nodes.append(
                    {
                        "id": node_id,
                        "citation": f"`{node_id}`",
                        "label": node_data.get("label", node_id),
                        "score": node_data.get("score", 0.0),
                    }
                )
        nodes.sort(key=lambda x: x["score"], reverse=True)

        edges: list[dict] = []
        for source_id, target_id, edge_data in graph.edges(data=True):
            relationship_label = edge_data.get("label", "RELATED")
            relationship_desc = edge_data.get("relationship_description", "")
            edges.append(
                {"source": source_id, "target": target_id, "**": f"{relationship_label}: {relationship_desc}"}
            )
        return yaml.dump(
            {
                "knowledge": yaml.dump(nodes, allow_unicode=True),
                "context": yaml.dump(edges, allow_unicode=True),
            },
            allow_unicode=True,
        )

    # -- CustomQueryEngine surface --------------------------------------

    async def acustom_query(self, query_str: str, **kwargs) -> STR_OR_RESPONSE_TYPE:
        return await self._acustom_query(query_str, **kwargs)

    def custom_query(self, query_str: str, **kwargs) -> str:
        return run_async(self._acustom_query(query_str, **kwargs))

    async def _acustom_query(self, query_str: str, **kwargs) -> str:
        context_query = kwargs.get("parameter", None)
        answer, _ = await self._query_plan(
            query_str, context=context_query, include_graph=self.include_graph, **kwargs
        )
        return answer

    async def _query_plan(self, query, context=None, include_graph=True, **kwargs):
        knowledge: list[dict] = []
        if include_graph:
            for node in self.graph_store.graph.get_all_nodes(
                label_type="entity",
                context=f"{context or ''}. {query}. {self.data_instruction}",
                category_id=kwargs.get("category_id"),
            ):
                if node.label == "text_chunk":
                    continue
                if len(node.name) < 100:
                    knowledge.append(
                        {
                            node.label: node.id,
                            "name": node.properties.get("entity_description"),
                            "category_id": node.properties.get("category_id"),
                        }
                    )
        logger.info("Query: %s with knowledge: %s", query, knowledge)

        executor = QueryExecutor(self, llm=self.plan_llm, language=self.language)
        if self.max_queries == 1:
            plans = [{"is_query": True, "term": query}]
        else:
            plans, _ = executor.generate_plans(
                query,
                max_queries=self.max_queries,
                instruction=self.data_instruction,
                knowledge=yaml.dump(knowledge, allow_unicode=True),
                context=context if context is not None else "",
            )
        if plans is None:
            return "", []

        is_memory = self.max_queries == 1
        return await executor.execute_plans(
            plans,
            yaml.dump(knowledge, allow_unicode=True),
            query=query,
            llm=self.llm,
            stream_handler=self.stream_handler,
            is_memory=is_memory,
            **kwargs,
        )

    def get_nodes(self, query_str, similarity_top_k=40, similarity_score=0.5, **kwargs):
        sub_retrievers = [self.tracking]
        return self.index.as_retriever(
            similarity_top_k=similarity_top_k,
            similarity_score=similarity_score,
            sub_retrievers=sub_retrievers,
        ).retrieve(query_str)

    def compute_page_rank(self, personalize_matrix, **kwargs):
        score = self.graph_store.pagerank(personalize_matrix, **kwargs)
        if score is not None:
            return [(_id, s) for _id, s in score if s > PAGERANK_SCORE_THRESHOLD]
        return [(v, _i) for _i, v in enumerate(personalize_matrix)]

    def get_community_relations(self, ids):
        kg_ids = self.index.property_graph_store.get(ids=ids)
        return self.index.property_graph_store.get_rel_map(kg_ids, depth=3, ignore_rels=[KG_SOURCE_REL])

    async def aggregate_answers(self, community_answers, query, llm=None, citation=None):
        """Aggregate community answers via :meth:`KnowledgeLLM.aggregate_answers`.

        The ``citation`` parameter is preserved in the API for back-compat;
        post-processing of UUID -> file citations is left to the caller in v1.
        """
        active_llm: KnowledgeLLM = llm if llm is not None else self.llm

        if isinstance(community_answers, str):
            snippets = [community_answers]
        elif isinstance(community_answers, (list, tuple)):
            snippets = [str(s) for s in community_answers]
        else:
            snippets = [str(community_answers)]

        try:
            return await asyncio.to_thread(
                active_llm.aggregate_answers, snippets, query, self.language
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("aggregate_answers failed: %s", exc)
            return f"Error: {exc}"

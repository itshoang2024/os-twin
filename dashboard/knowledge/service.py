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
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.models import OntologyProfile, OntologyUnit
from dashboard.knowledge.ontology.store import OntologyProfileStore
from dashboard.knowledge.ontology.audit import (
    OntologyAuditStore,
    add_rename_aliases,
    diff_profiles,
    validate_migration_safety,
)
from dashboard.knowledge.ontology.candidates import OntologyCandidateStore, normalize_candidate_label
from dashboard.knowledge.ontology.evidence import EvidenceStore
from dashboard.knowledge.ontology.facts import FactSubjectRef, OntologyFactPromotionService, OntologyFactStore, SuggestedRelationshipMapping
from dashboard.knowledge.ontology.approval import KuzuGraphInstanceStore, ObservationEventStore, OntologyApprovalService
from dashboard.knowledge.ontology.analysis import AnalysisStore, FlowDefinition, SimulationScenario, StateMachine, validate_state_transition
from dashboard.knowledge.ontology.observation import TimeSeriesStore
from dashboard.knowledge.ontology.packs import DomainPackStore
from dashboard.knowledge.ontology.validator import (
    validate_node as validate_ontology_node,
    validate_pack as validate_ontology_pack,
    validate_profile as validate_ontology_profile,
    validate_relationship as validate_ontology_relationship,
)
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
        self._ontology_store = OntologyProfileStore(self._nm)
        self._ontology_audit_store = OntologyAuditStore(self._nm)
        self._candidate_store = OntologyCandidateStore(self._nm)
        self._evidence_store = EvidenceStore(self._nm)
        self._fact_store = OntologyFactStore(self._nm)
        self._observation_store = ObservationEventStore(self._nm)
        self._series_store = TimeSeriesStore(self._nm)
        self._analysis_store = AnalysisStore(self._nm)
        self._domain_pack_store = DomainPackStore(self._nm, self._ontology_store)

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
            ontology_profile=self.get_ontology_profile(namespace),
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

    def explorer_expand(self, namespace: str, node_ids: list[str], depth: int = 1, filters: dict[str, Any] | None = None) -> dict:
        """Expand from a set of node IDs outward by N hops."""
        explorer = self._get_explorer(namespace)
        return explorer.expand(node_ids=node_ids, depth=depth, filters=filters)

    def explorer_search(self, namespace: str, query: str, limit: int = 20, filters: dict[str, Any] | None = None) -> dict:
        """Vector-similarity search over node embeddings + 1-hop context."""
        explorer = self._get_explorer(namespace)
        return explorer.search(query=query, limit=limit, filters=filters)

    def ontology_enterprise_map(self, namespace: str, limit: int = 200, filters: dict[str, Any] | None = None) -> dict:
        """Return a graph-backed ontology projection for map and builder surfaces."""
        self._require_namespace(namespace)
        explorer = self._get_explorer(namespace)
        result = explorer.enterprise_map(limit=limit, filters=filters)
        candidate_count = self._candidate_store.pending_count(namespace)
        self._attach_observation_projection(namespace, result, filters=filters)
        self._attach_analysis_projection(namespace, result)
        result.setdefault("stats", {})["ontology_candidate_count"] = candidate_count
        result.setdefault("meta", {})["ontology_candidate_count"] = candidate_count
        return result

    def _attach_observation_projection(self, namespace: str, result: dict[str, Any], *, filters: dict[str, Any] | None = None) -> None:
        """Attach observation counts and series refs without fabricating metrics."""

        window = self._resolve_observation_window(namespace, filters or {})
        subject_ids = [str(item.get("id")) for item in result.get("nodes", []) if item.get("id")]
        subject_ids.extend(str(item.get("id") or f"{item.get('source')}:{item.get('relationship_type') or item.get('label')}:{item.get('target')}") for item in result.get("edges", []) if item.get("source") and item.get("target"))
        summary = self._observation_store.summary_for_subjects(namespace, subject_ids, start=window.get("start"), end=window.get("end"))
        series_refs = self._series_store.refs_for_subjects(namespace, subject_ids)
        for item in [*(result.get("nodes") or []), *(result.get("edges") or [])]:
            subject_id = str(item.get("id") or f"{item.get('source')}:{item.get('relationship_type') or item.get('label')}:{item.get('target')}")
            rec = summary.get(subject_id, {})
            item["event_count"] = int(rec.get("event_count") or 0)
            item["active_event_count"] = int(rec.get("active_event_count") or 0)
            if rec.get("time_range"):
                item["time_range"] = rec["time_range"]
            refs = series_refs.get(subject_id) or []
            if refs:
                item["series_refs"] = refs
        total_events = sum(int(rec.get("event_count") or 0) for rec in summary.values())
        active_events = sum(int(rec.get("active_event_count") or 0) for rec in summary.values())
        result.setdefault("stats", {})["event_count"] = total_events
        result.setdefault("stats", {})["active_event_count"] = active_events
        result.setdefault("meta", {})["time_window"] = window
        result.setdefault("meta", {})["observation_series_backend"] = "inline-json-mvp"


    def _attach_analysis_projection(self, namespace: str, result: dict[str, Any]) -> None:
        """Attach saved Analysis-plane overlays without inventing workflows or metrics."""

        nodes = result.get("nodes") or []
        edges = result.get("edges") or []
        node_by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
        flows = self._analysis_store.list_flows(namespace)
        machines = self._analysis_store.list_state_machines(namespace)
        scenarios = self._analysis_store.list_simulation_scenarios(namespace)

        for flow in flows:
            for step in flow.steps:
                matched = []
                if step.node_id and step.node_id in node_by_id:
                    matched.append(node_by_id[step.node_id])
                if step.concept_type:
                    matched.extend(node for node in nodes if str(node.get("concept_type") or node.get("label") or "") == step.concept_type)
                for node in matched:
                    refs = list(node.get("flow_refs") or [])
                    if flow.id not in refs:
                        refs.append(flow.id)
                    node["flow_refs"] = refs

        state_overlay_count = 0
        for machine in machines:
            state_colors = {state.id: state.color for state in machine.states if state.color}
            for node in nodes:
                if str(node.get("concept_type") or node.get("label") or "") != machine.subject_concept_type:
                    continue
                metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
                properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
                state = str(metadata.get("state") or properties.get("state") or metadata.get("current_state") or machine.initial_state or "")
                node["state"] = state
                node["state_machine_ref"] = machine.id
                if state_colors.get(state):
                    node["state_color"] = state_colors[state]
                state_overlay_count += 1

        for scenario in scenarios:
            for node_id in scenario.input_node_ids:
                node = node_by_id.get(node_id)
                if not node:
                    continue
                node["simulation_state"] = scenario.simulation_state
                refs = list(node.get("simulation_refs") or [])
                if scenario.id not in refs:
                    refs.append(scenario.id)
                node["simulation_refs"] = refs

        result.setdefault("meta", {})["analysis"] = {
            "flow_count": len(flows),
            "state_machine_count": len(machines),
            "simulation_scenario_count": len(scenarios),
            "state_overlay_count": state_overlay_count,
            "simulation_provider_required": any(s.simulation_state == "provider_required" for s in scenarios),
            "provider_contract": "Simulation outputs require provider_id or result_ref; no predictive metrics are generated by the core product.",
        }
        result.setdefault("stats", {})["flow_count"] = len(flows)
        result.setdefault("stats", {})["state_machine_count"] = len(machines)
        result.setdefault("stats", {})["simulation_scenario_count"] = len(scenarios)

    def list_analysis_definitions(self, namespace: str) -> dict[str, Any]:
        self._require_namespace(namespace)
        scenarios = self._analysis_store.list_simulation_scenarios(namespace)
        return {
            "namespace": namespace,
            "flows": [item.model_dump(mode="json", by_alias=True) for item in self._analysis_store.list_flows(namespace)],
            "state_machines": [item.model_dump(mode="json", by_alias=True) for item in self._analysis_store.list_state_machines(namespace)],
            "simulation_scenarios": [item.model_dump(mode="json", by_alias=True) for item in scenarios],
            "provider_contract": {
                "required_for_outputs": True,
                "message": "Simulation outputs require a registered provider or saved result reference.",
                "scenario_states": {item.id: item.simulation_state for item in scenarios},
            },
        }

    def upsert_flow_definition(self, namespace: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_namespace(namespace)
        payload = {**payload, "namespace": namespace}
        flow = self._analysis_store.upsert_flow(namespace, FlowDefinition.model_validate(payload))
        return flow.model_dump(mode="json", by_alias=True)

    def upsert_state_machine(self, namespace: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_namespace(namespace)
        payload = {**payload, "namespace": namespace}
        machine = self._analysis_store.upsert_state_machine(namespace, StateMachine.model_validate(payload))
        return machine.model_dump(mode="json", by_alias=True)

    def upsert_simulation_scenario(self, namespace: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_namespace(namespace)
        payload = {**payload, "namespace": namespace}
        scenario = self._analysis_store.upsert_simulation_scenario(namespace, SimulationScenario.model_validate(payload))
        return scenario.model_dump(mode="json", by_alias=True)

    def validate_state_machine_transition(self, namespace: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_namespace(namespace)
        machine_id = str(payload.get("state_machine_id") or "")
        machine = next((item for item in self._analysis_store.list_state_machines(namespace) if item.id == machine_id), None)
        if machine is None:
            raise ValueError("state_machine_id is required and must reference a saved state machine")
        issues = validate_state_transition(
            machine,
            current_state=str(payload.get("current_state") or ""),
            event_type=str(payload.get("event_type") or ""),
            evidence_refs=list(payload.get("evidence_refs") or []),
            metadata=dict(payload.get("metadata") or {}),
        )
        return {"namespace": namespace, "valid": not any(issue.severity == "error" for issue in issues), "issues": [issue.model_dump() for issue in issues]}

    def _resolve_observation_window(self, namespace: str, filters: dict[str, Any]) -> dict[str, Any]:
        mode = str(filters.get("time_mode") or filters.get("timeMode") or "none")
        if mode == "fixed_range":
            return {"mode": mode, "start": filters.get("start") or filters.get("start_at"), "end": filters.get("end") or filters.get("end_at")}
        if mode == "latest_import":
            event = self._observation_store.latest_by_type(namespace, "ImportCompleted") or self._observation_store.latest_by_type(namespace, "ImportSubmitted")
            return {"mode": mode, "start": event.occurred_at.isoformat() if event else None, "end": None, "empty_reason": None if event else "No import observation events recorded."}
        if mode == "current_profile_version":
            profile = self.get_ontology_profile(namespace)
            history = self._ontology_audit_store.list_history(namespace)
            matching = next((record for record in history if profile is not None and record.new_version == profile.version), None)
            return {"mode": mode, "start": matching.timestamp.isoformat() if matching else None, "end": None, "profile_version": profile.version if profile else None, "empty_reason": None if matching else "No profile-history timestamp found for current version."}
        return {"mode": "none", "start": None, "end": None}

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
                ontology_profile=self.get_ontology_profile(namespace),
                candidate_store=self._candidate_store,
                evidence_store=self._evidence_store,
                fact_store=self._fact_store,
                namespace=namespace,
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
        The ingestor also caches embedder/LLM refs and must be rebuilt.
        """
        self._llm = None
        self._embedder = None
        self._ingestor = None
        self._query_engines.clear()
        self._graph_rag_engines.clear()
        # Also clear the global embedding client cache so stale singleton
        # clients (keyed on old model name) are not reused.
        from dashboard.llm_client import _embedding_cache, _embedding_cache_lock
        with _embedding_cache_lock:
            _embedding_cache.clear()
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
            evidence_store=self._evidence_store,
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
                ontology_profile=self.get_ontology_profile(namespace),
                candidate_store=self._candidate_store,
                evidence_store=self._evidence_store,
                fact_store=self._fact_store,
                namespace=namespace,
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


    def _require_namespace(self, namespace: str) -> NamespaceMeta:
        """Return namespace metadata or raise the canonical not-found exception."""
        meta = self._nm.get(namespace)
        if meta is None:
            raise NamespaceNotFoundError(namespace)
        return meta


    def get_ontology_unit(self, namespace: str) -> OntologyUnit | None:
        """Return the namespace ontology unit identity/governance record, if any."""
        self._require_namespace(namespace)
        return self._ontology_store.get_unit(namespace)

    def get_ontology_unit_response(self, namespace: str) -> dict[str, Any]:
        """Return transport-ready ontology unit metadata."""
        unit = self.get_ontology_unit(namespace)
        return {
            "namespace": namespace,
            "unit": unit.model_dump(mode="json") if unit is not None else None,
            "unit_exists": unit is not None,
        }

    def save_ontology_unit_payload(self, namespace: str, payload: dict[str, Any]) -> OntologyUnit:
        """Validate and persist ontology unit metadata without publishing a profile.

        Unit updates are metadata edits by default. If an active unit already
        points at a profile, a partial PUT that omits ``active_profile_id`` must
        not silently deactivate that profile. Deactivation is intentionally not
        exposed through this metadata endpoint.
        """
        self._require_namespace(namespace)
        payload_namespace = payload.get("namespace")
        if payload_namespace is None:
            payload = {**payload, "namespace": namespace}
        elif payload_namespace != namespace:
            raise ValueError("Ontology unit namespace must match path namespace")
        if payload.get("id") not in (None, namespace):
            raise ValueError("Ontology unit id must match path namespace")

        existing_unit = self._ontology_store.get_unit(namespace)
        existing_payload = existing_unit.model_dump(mode="json") if existing_unit is not None else {}
        merged_payload = {**existing_payload, **payload, "id": namespace, "namespace": namespace}
        if (
            existing_unit is not None
            and existing_unit.active_profile_id is not None
            and merged_payload.get("active_profile_id") is None
        ):
            merged_payload["active_profile_id"] = existing_unit.active_profile_id

        return self._ontology_store.write_unit(OntologyUnit.model_validate(merged_payload))

    def get_ontology_profile(self, namespace: str) -> Optional[OntologyProfile]:
        """Return the namespace's active ontology profile, or None for legacy namespaces."""
        return self._ontology_store.get(namespace)

    def get_ontology_profile_with_default(self, namespace: str) -> dict[str, Any]:
        """Return active ontology profile metadata or a deterministic default suggestion."""
        self._require_namespace(namespace)
        profile = self.get_ontology_profile(namespace)
        issues = validate_ontology_profile(profile) if profile is not None else []
        return {
            "namespace": namespace,
            "profile": profile.model_dump(mode="json") if profile is not None else None,
            "profile_exists": profile is not None,
            "default_suggested": profile is None,
            "default_profile": (
                None
                if profile is not None
                else create_default_ontology_profile(namespace).model_dump(mode="json")
            ),
            "validation_issues": [issue.model_dump() for issue in issues],
        }

    def save_ontology_profile(
        self,
        profile: OntologyProfile,
        *,
        actor: str = "anonymous",
        reason: str = "Profile saved",
        validation_override: dict[str, Any] | None = None,
        operation: str = "profile_save",
        migration_entries: list[dict[str, Any]] | None = None,
    ) -> OntologyProfile:
        """Persist an ontology profile, history record, migration warnings, and audit event."""
        previous = self.get_ontology_profile(profile.namespace)
        profile, rename_entries = add_rename_aliases(previous, profile)
        issues = validate_ontology_profile(profile)
        if any(issue.severity == "error" for issue in issues):
            messages = "; ".join(issue.message for issue in issues)
            raise ValueError(f"Ontology profile has validation errors: {messages}")
        cached_graph = self._kuzu_graphs.get(profile.namespace)
        migration_issues = validate_migration_safety(
            profile.namespace,
            previous,
            profile,
            graph=cached_graph,
        )
        dangerous = [issue for issue in migration_issues if issue.severity == "error"]
        if dangerous:
            override = validation_override or {}
            approver = override.get("approved_by") or override.get("approver")
            ticket = override.get("ticket")
            if not str(ticket or "").strip() or not str(approver or "").strip():
                messages = "; ".join(issue.message for issue in dangerous)
                raise ValueError(
                    "Dangerous ontology migration requires validation_override metadata "
                    f"with ticket and approved_by: {messages}"
                )

        diff = diff_profiles(previous, profile)
        written = self._ontology_store.write(profile, set_active=True)
        self._ontology_audit_store.append_profile_record(
            profile.namespace,
            actor=actor,
            reason=reason,
            previous=previous,
            current=written,
            diff=diff,
            migration_issues=migration_issues,
            validation_override=validation_override,
            migration_entries=[*rename_entries, *(migration_entries or [])],
            op=operation,
        )
        if cached_graph is not None:
            cached_graph.ontology_profile = written
        return written

    def save_ontology_profile_payload(
        self,
        namespace: str,
        payload: dict[str, Any],
        *,
        actor: str = "anonymous",
        reason: str = "Profile saved through API",
        validation_override: dict[str, Any] | None = None,
    ) -> OntologyProfile:
        """Validate and persist an ontology profile payload for the path namespace."""
        self._require_namespace(namespace)
        payload_namespace = payload.get("namespace")
        if payload_namespace is None:
            payload = {**payload, "namespace": namespace}
        elif payload_namespace != namespace:
            raise ValueError("Ontology profile namespace must match path namespace")
        return self.save_ontology_profile(
            OntologyProfile.model_validate(payload),
            actor=actor,
            reason=reason,
            validation_override=validation_override,
        )

    def create_default_ontology_profile(self, namespace: str) -> OntologyProfile:
        """Create and persist the deterministic default ontology profile for a namespace."""
        self._require_namespace(namespace)
        profile = create_default_ontology_profile(namespace)
        return self.save_ontology_profile(profile, actor="system", reason="Create default ontology profile", operation="profile_reset")

    def reset_default_ontology_profile(self, namespace: str) -> tuple[OntologyProfile, bool]:
        """Replace any active profile with the deterministic default profile."""
        self._require_namespace(namespace)
        replaced_existing = self.get_ontology_profile(namespace) is not None
        return self.create_default_ontology_profile(namespace), replaced_existing

    def validate_ontology_payload(self, namespace: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate ontology profile, node, edge, or pack data without saving it."""
        self._require_namespace(namespace)
        subject = payload.get("subject")
        profile_payload = payload.get("profile")
        profile = (
            OntologyProfile.model_validate(
                {**profile_payload, "namespace": profile_payload.get("namespace", namespace)}
            )
            if isinstance(profile_payload, dict)
            else self.get_ontology_profile(namespace) or create_default_ontology_profile(namespace)
        )
        issues: list[Any] = []
        if subject == "profile":
            issues.extend(validate_ontology_profile(profile))
        elif subject == "node":
            node = payload.get("node") or {}
            concept_type = node.get("concept_type", node.get("type", ""))
            issues.extend(validate_ontology_node(str(concept_type), profile))
        elif subject == "edge":
            edge = payload.get("edge") or {}
            relation_type = edge.get("relation_type", edge.get("label", edge.get("type", "")))
            source_type = edge.get(
                "source_type",
                edge.get("source_concept_type", edge.get("source", {}).get("type", "")),
            )
            target_type = edge.get(
                "target_type",
                edge.get("target_concept_type", edge.get("target", {}).get("type", "")),
            )
            issues.extend(
                validate_ontology_relationship(str(relation_type), str(source_type), str(target_type), profile)
            )
        elif subject == "pack":
            for idx, node in enumerate(payload.get("nodes") or []):
                concept_type = node.get("concept_type", node.get("type", ""))
                issues.extend(validate_ontology_node(str(concept_type), profile, path=f"nodes[{idx}].type"))
            issues.extend(validate_ontology_pack(list(payload.get("edges") or []), profile))
        else:
            raise ValueError("Validation subject must be one of: profile, node, edge, pack")
        return {
            "namespace": namespace,
            "subject": str(subject),
            "valid": not any(issue.severity == "error" for issue in issues),
            "issues": [issue.model_dump() for issue in issues],
        }

    def list_ontology_profile_history(self, namespace: str) -> list[dict[str, Any]]:
        """List profile version history records newest-first."""
        self._require_namespace(namespace)
        return [record.model_dump(mode="json", exclude={"profile"}) for record in self._ontology_audit_store.list_history(namespace)]

    def get_ontology_profile_history(self, namespace: str, version_or_id: str) -> dict[str, Any]:
        """Read one profile history record including its immutable profile snapshot."""
        self._require_namespace(namespace)
        return self._ontology_audit_store.get_history(namespace, version_or_id).model_dump(mode="json")

    def diff_ontology_profiles(
        self,
        namespace: str,
        *,
        base_profile: dict[str, Any] | None = None,
        target_profile: dict[str, Any] | None = None,
        base_version: str | None = None,
        target_version: str | None = None,
    ) -> dict[str, Any]:
        """Return a side-effect-free diff between two profile payloads or history versions."""
        self._require_namespace(namespace)

        def resolve(payload: dict[str, Any] | None, version: str | None, fallback_current: bool) -> OntologyProfile | None:
            if payload is not None:
                return OntologyProfile.model_validate({**payload, "namespace": payload.get("namespace", namespace)})
            if version:
                record = self._ontology_audit_store.get_history(namespace, version)
                return OntologyProfile.model_validate(record.profile)
            if fallback_current:
                return self.get_ontology_profile(namespace)
            return None

        previous = resolve(base_profile, base_version, True)
        current = resolve(target_profile, target_version, False)
        if current is None:
            raise ValueError("target_profile or target_version is required")
        diff = diff_profiles(previous, current)
        migration_issues = validate_migration_safety(
            namespace, previous, current, graph=self._kuzu_graphs.get(namespace)
        )
        return {
            "namespace": namespace,
            "base_version": previous.version if previous else None,
            "target_version": current.version,
            "diff": diff.model_dump(mode="json"),
            "migration_issues": [issue.model_dump() for issue in migration_issues],
            "would_mutate": False,
        }

    def preview_ontology_profile_rollback(self, namespace: str, version_or_id: str) -> dict[str, Any]:
        """Preview rollback diff to a historical profile without mutating current storage."""
        record = self._ontology_audit_store.get_history(namespace, version_or_id)
        current = self.get_ontology_profile(namespace)
        target = OntologyProfile.model_validate(record.profile)
        diff = diff_profiles(current, target)
        migration_issues = validate_migration_safety(namespace, current, target, graph=self._kuzu_graphs.get(namespace))
        return {
            "namespace": namespace,
            "base_version": current.version if current else None,
            "target_version": target.version,
            "history_id": record.id,
            "diff": diff.model_dump(mode="json"),
            "migration_issues": [issue.model_dump() for issue in migration_issues],
            "would_mutate": False,
        }

    def get_ontology_summary(self, namespace: str) -> dict[str, Any]:
        """Return summary counters for the active ontology profile or default suggestion."""
        self._require_namespace(namespace)
        profile = self.get_ontology_profile(namespace)
        profile_exists = profile is not None
        if profile is None:
            profile = create_default_ontology_profile(namespace)
        issues = validate_ontology_profile(profile)
        candidate_count = self._candidate_store.pending_count(namespace)
        return {
            "namespace": namespace,
            "profile_exists": profile_exists,
            "profile_id": profile.profile_id,
            "version": profile.version,
            "concept_type_count": len(profile.concept_types),
            "relation_type_count": len(profile.relationship_types),
            "alias_count": len(profile.aliases),
            "candidate_count": candidate_count,
            "validation_issue_count": len(issues),
            "validation_issues": [issue.model_dump() for issue in issues],
        }


    def get_ontology_release_observability(self, namespace: str) -> dict[str, Any]:
        """Return release-gate ontology health signals for PO/QA signoff.

        The report intentionally reads existing stores and validation results; it
        does not mutate profile history, facts, candidates, graph instances, or
        observation events.  Counts are grouped so release failures can be traced
        to source processing, ontology schema, assistant advisory output,
        governance review, projection, or pack compatibility.
        """

        self._require_namespace(namespace)
        profile = self.get_ontology_profile(namespace)
        effective_profile = profile or create_default_ontology_profile(namespace)
        validation_issues = validate_ontology_profile(effective_profile)
        candidates = self._candidate_store.list(namespace)
        facts = self._fact_store.list(namespace)
        artifacts = self._evidence_store.list_artifacts(namespace)
        anchors = self._evidence_store.list_anchors(namespace)
        provenance_links = self._evidence_store.list_provenance(namespace)
        events = self._observation_store.list(namespace)
        installed_state = self._domain_pack_store.get_state(namespace)

        def count_by(records: list[Any], attr: str) -> dict[str, int]:
            counts: dict[str, int] = {}
            for record in records:
                value = str(getattr(record, attr, None) or "unknown")
                counts[value] = counts.get(value, 0) + 1
            return dict(sorted(counts.items()))

        extraction_warning_count = sum(len(artifact.limitations) for artifact in artifacts)
        warning_source_states = {
            "partial",
            "sampled",
            "ocr_needed",
            "conversion_needed",
            "failed",
        }
        partial_source_count = sum(
            1
            for artifact in artifacts
            if artifact.read_coverage != "full" or artifact.source_state in warning_source_states
        )
        assistant_error_count = sum(
            1
            for fact in facts
            if fact.source == "assistant"
            and any(key in fact.metadata for key in ("parse_error", "assistant_error", "error"))
        )
        assistant_error_count += sum(
            1
            for event in events
            if "Assistant" in event.event_type
            and any(key in event.metadata for key in ("parse_error", "assistant_error", "error"))
        )

        pack_results: list[dict[str, Any]] = []
        release_blockers: list[dict[str, Any]] = []
        pack_compatibility_profile = create_default_ontology_profile(namespace)
        for manifest in self._domain_pack_store.list_available():
            # Pack compatibility is tested against the shipped base profile so one
            # installed pack's aliases do not create false conflicts for another
            # independently shippable pack. Installed state is reported separately.
            result = self._domain_pack_store.validate(manifest, pack_compatibility_profile)
            active_record = installed_state.installed_packs.get(manifest.pack_id)
            active = active_record is not None and active_record.status == "installed"
            relationship_families = sorted({rel.family for rel in manifest.relationship_types.values()})
            pack_payload = {
                "pack_id": manifest.pack_id,
                "name": manifest.name,
                "version": manifest.version,
                "valid": result.valid,
                "installed": active,
                "compatible_profile_versions": list(manifest.compatible_profile_versions),
                "relationship_families": relationship_families,
                "issue_count": len(result.issues),
                "issues": [issue.model_dump() for issue in result.issues],
                "fixture_count": len(manifest.fixtures),
                "migration_note_count": len(manifest.migration_notes),
            }
            pack_results.append(pack_payload)
            if not result.valid:
                release_blockers.append({
                    "plane": "packs",
                    "code": "PACK_COMPATIBILITY_FAILED",
                    "message": (
                        f"Domain pack {manifest.pack_id} is not compatible with "
                        f"profile {effective_profile.version}."
                    ),
                    "metadata": {"pack_id": manifest.pack_id, "issues": pack_payload["issues"]},
                })
            if manifest.pack_id in {"audit-risk", "audit-risk-management", "esg"} and not relationship_families:
                release_blockers.append({
                    "plane": "packs",
                    "code": "RELATIONSHIP_FAMILY_MISSING",
                    "message": f"Release-blocking pack {manifest.pack_id} has no relationship families.",
                    "metadata": {"pack_id": manifest.pack_id},
                })

        if any(issue.severity == "error" for issue in validation_issues):
            release_blockers.append({
                "plane": "spec",
                "code": "PROFILE_VALIDATION_ERRORS",
                "message": "Active ontology profile has error-severity validation issues.",
                "metadata": {
                    "issue_count": len([issue for issue in validation_issues if issue.severity == "error"])
                },
            })
        has_unreviewed_generated_facts = any(
            fact.source in {"assistant", "extraction"} and fact.review_state in {"assistive", "draft"}
            for fact in facts
        )
        if has_unreviewed_generated_facts:
            release_blockers.append({
                "plane": "facts",
                "code": "UNREVIEWED_FACTS",
                "message": "Assistant/extraction facts remain advisory or draft and need human review before release.",
                "metadata": {"fact_states": count_by(facts, "review_state")},
            })
        if assistant_error_count:
            release_blockers.append({
                "plane": "assistant",
                "code": "ASSISTANT_ERRORS",
                "message": "Assistant parse/runtime errors were observed in release evidence.",
                "metadata": {"assistant_error_count": assistant_error_count},
            })

        active_unit = self._ontology_store.get_unit(namespace)
        installed_pack_ids = sorted(
            pid for pid, record in installed_state.installed_packs.items() if record.status == "installed"
        )

        return {
            "namespace": namespace,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile": {
                "exists": profile is not None,
                "profile_id": effective_profile.profile_id,
                "version": effective_profile.version,
                "active_unit": active_unit.model_dump(mode="json") if active_unit else None,
                "concept_type_count": len(effective_profile.concept_types),
                "relationship_type_count": len(effective_profile.relationship_types),
                "validation_issue_count": len(validation_issues),
                "validation_issues_by_severity": count_by(validation_issues, "severity"),
            },
            "candidates": {
                "total": len(candidates),
                "by_status": count_by(candidates, "status"),
                "by_type": count_by(candidates, "candidate_type"),
                "pending": sum(1 for candidate in candidates if candidate.status == "pending"),
            },
            "facts": {
                "total": len(facts),
                "by_review_state": count_by(facts, "review_state"),
                "by_source": count_by(facts, "source"),
                "approved": sum(1 for fact in facts if fact.review_state == "approved"),
            },
            "evidence": {
                "artifact_count": len(artifacts),
                "anchor_count": len(anchors),
                "provenance_link_count": len(provenance_links),
                "extraction_warning_count": extraction_warning_count,
                "partial_source_count": partial_source_count,
                "source_types": count_by(artifacts, "source_type"),
                "read_coverage": count_by(artifacts, "read_coverage"),
            },
            "observations": {
                "event_count": len(events),
                "by_event_type": count_by(events, "event_type"),
                "by_subject_type": count_by(events, "subject_type"),
            },
            "assistant": {
                "advisory_only": True,
                "error_count": assistant_error_count,
                "fact_count": sum(1 for fact in facts if fact.source == "assistant"),
            },
            "packs": {
                "installed_pack_ids": installed_pack_ids,
                "available_pack_count": len(pack_results),
                "compatible_pack_count": sum(1 for result in pack_results if result["valid"]),
                "load_results": pack_results,
            },
            "release_blockers": release_blockers,
            "release_ready": not release_blockers,
        }


    def list_available_domain_packs(self) -> list[dict[str, Any]]:
        """Return built-in domain pack manifests available for installation."""

        return [manifest.model_dump(mode="json") for manifest in self._domain_pack_store.list_available()]

    def list_installed_domain_packs(self, namespace: str) -> dict[str, Any]:
        """Return namespace-local domain pack lifecycle state."""

        self._require_namespace(namespace)
        return self._domain_pack_store.get_state(namespace).model_dump(mode="json")

    def validate_domain_pack_install(self, namespace: str, pack_id: str) -> dict[str, Any]:
        """Preview pack compatibility, conflicts, and merged profile without saving."""

        self._require_namespace(namespace)
        manifest = self._domain_pack_store.load_manifest(pack_id)
        profile = self.get_ontology_profile(namespace) or create_default_ontology_profile(namespace)
        result = self._domain_pack_store.validate(manifest, profile)
        data = result.model_dump()
        data.update({"namespace": namespace, "pack_id": pack_id, "manifest": manifest.model_dump(mode="json")})
        return data

    def install_domain_pack(self, namespace: str, pack_id: str, *, actor: str = "anonymous", reason: str = "Domain pack install") -> dict[str, Any]:
        """Install or upgrade a domain pack into the namespace active ontology profile."""

        self._require_namespace(namespace)
        manifest = self._domain_pack_store.load_manifest(pack_id)
        profile = self.get_ontology_profile(namespace) or create_default_ontology_profile(namespace)
        result = self._domain_pack_store.install(namespace, manifest, profile, persist_profile=False)
        saved = self.save_ontology_profile(
            result.profile,
            actor=actor,
            reason=reason or f"Install domain pack {pack_id}",
            operation="pack_install",
            migration_entries=[{"kind": "domain_pack_install", "pack_id": pack_id, "action": result.action}],
        )
        self._domain_pack_store.write_state(result.state)
        unit = self._ontology_store.get_unit(namespace)
        if unit is not None:
            unit.installed_packs = sorted(pid for pid, rec in result.state.installed_packs.items() if rec.status == "installed")
            self._ontology_store.write_unit(unit)
        self._observation_store.create(namespace, event_type="DomainPackInstalled", subject_type="pack", subject_id=pack_id, actor=actor, metadata={"profile_version": saved.version})
        data = result.model_dump()
        data["profile"] = saved.model_dump(mode="json")
        return data

    def uninstall_domain_pack(self, namespace: str, pack_id: str, *, actor: str = "anonymous", reason: str = "Domain pack uninstall") -> dict[str, Any]:
        """Disable a domain pack and remove pack-owned profile additions when safe."""

        self._require_namespace(namespace)
        profile = self.get_ontology_profile(namespace)
        if profile is None:
            raise ValueError("Cannot uninstall a domain pack before an ontology profile exists")
        result = self._domain_pack_store.uninstall(namespace, pack_id, profile, persist_profile=False)
        saved = self.save_ontology_profile(
            result.profile,
            actor=actor,
            reason=reason or f"Uninstall domain pack {pack_id}",
            operation="pack_uninstall",
            migration_entries=[{"kind": "domain_pack_uninstall", "pack_id": pack_id, "action": result.action}],
        )
        self._domain_pack_store.write_state(result.state)
        unit = self._ontology_store.get_unit(namespace)
        if unit is not None:
            unit.installed_packs = sorted(pid for pid, rec in result.state.installed_packs.items() if rec.status == "installed")
            self._ontology_store.write_unit(unit)
        data = result.model_dump()
        data["profile"] = saved.model_dump(mode="json")
        return data


    def list_observation_events(
        self,
        namespace: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        event_type: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """List operational observation events separately from profile history."""

        self._require_namespace(namespace)
        return [event.model_dump(mode="json") for event in self._observation_store.list(namespace, subject_type=subject_type, subject_id=subject_id, event_type=event_type, start=start, end=end)]

    def list_time_series(self, namespace: str, *, subject_id: str | None = None, metric_id: str | None = None) -> list[dict[str, Any]]:
        """List inline MVP time-series records for selected object metrics."""

        self._require_namespace(namespace)
        return [series.model_dump(mode="json") for series in self._series_store.list(namespace, subject_id=subject_id, metric_id=metric_id)]

    def upsert_time_series(
        self,
        namespace: str,
        *,
        subject_id: str,
        metric_id: str,
        unit: str = "count",
        points: list[dict[str, Any]] | None = None,
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist an MVP inline series without pretending it is production analytics."""

        self._require_namespace(namespace)
        series = self._series_store.upsert(namespace, subject_id=subject_id, metric_id=metric_id, unit=unit, points=points or [], evidence_refs=evidence_refs or [], metadata=metadata or {})
        self._observation_store.create(namespace, event_type="TimeSeriesUpdated", subject_type="instance", subject_id=subject_id, actor=str((metadata or {}).get("created_by") or "system"), metadata={"metric_id": metric_id, "series_id": series.id, "storage": "inline-json-mvp"}, evidence_refs=evidence_refs or [])
        return series.model_dump(mode="json")


    def list_ontology_facts(
        self,
        namespace: str,
        *,
        review_state: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """List namespace Facts-plane reviewed claims."""

        self._require_namespace(namespace)
        return [fact.model_dump(mode="json") for fact in self._fact_store.list(namespace, review_state=review_state, source=source)]

    def create_ontology_fact(
        self,
        namespace: str,
        *,
        statement: str,
        subjects: list[dict[str, Any]] | None = None,
        confidence: float = 0.5,
        source: str = "assistant",
        evidence_refs: list[str] | None = None,
        provenance_refs: list[str] | None = None,
        suggested_mapping: dict[str, Any] | None = None,
        source_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an advisory fact proposal without mutating canonical graph data."""

        self._require_namespace(namespace)
        fact = self._fact_store.create_assistive(
            namespace,
            statement=statement,
            subjects=[FactSubjectRef.model_validate(item) for item in (subjects or [])],
            confidence=confidence,
            source=source if source in {"extraction", "assistant", "manual"} else "assistant",
            evidence_refs=evidence_refs or [],
            provenance_refs=provenance_refs or [],
            suggested_mapping=SuggestedRelationshipMapping.model_validate(suggested_mapping) if suggested_mapping else None,
            source_hash=source_hash,
            metadata=metadata or {},
        )
        self._observation_store.create(
            namespace,
            event_type="OntologyFactCreated",
            subject_type="fact",
            subject_id=fact.id,
            created_by=str((metadata or {}).get("created_by") or "assistant"),
            provenance_refs=fact.provenance_refs or fact.evidence_refs,
            metadata={"source": fact.source, "review_state": fact.review_state},
        )
        return fact.model_dump(mode="json")

    def review_ontology_fact(
        self,
        namespace: str,
        fact_id: str,
        review_state: str,
        *,
        reviewed_by: str = "anonymous",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a fact review state while keeping it non-canonical."""

        self._require_namespace(namespace)
        if review_state not in {"draft", "assistive", "reviewed", "approved", "rejected"}:
            raise ValueError(f"Unsupported fact review state: {review_state}")
        fact = self._fact_store.update_review_state(namespace, fact_id, review_state, reviewed_by=reviewed_by, metadata=metadata or {})
        self._observation_store.create(
            namespace,
            event_type="OntologyFactReviewed" if review_state != "rejected" else "OntologyFactRejected",
            subject_type="fact",
            subject_id=fact.id,
            created_by=reviewed_by,
            provenance_refs=fact.provenance_refs or fact.evidence_refs,
            metadata={"review_state": fact.review_state, **(metadata or {})},
        )
        return fact.model_dump(mode="json")

    def promote_ontology_fact_to_edge(
        self,
        namespace: str,
        fact_id: str,
        *,
        relationship_type: str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        reviewed_by: str = "anonymous",
    ) -> dict[str, Any]:
        """Promote an approved fact into a typed graph edge with provenance."""

        self._require_namespace(namespace)
        promoter = OntologyFactPromotionService(
            self._nm,
            KuzuGraphInstanceStore(self.get_kuzu_graph(namespace)),
            fact_store=self._fact_store,
            candidate_store=self._candidate_store,
            profile_store=self._ontology_store,
            evidence_store=self._evidence_store,
            observation_store=self._observation_store,
        )
        edge = promoter.promote_to_edge(namespace, fact_id, relationship_type=relationship_type, source_id=source_id, target_id=target_id, reviewed_by=reviewed_by)
        return edge.model_dump(mode="json", exclude_none=True)

    def raise_fact_relationship_candidate(
        self,
        namespace: str,
        fact_id: str,
        *,
        relationship_label: str,
        reviewed_by: str = "anonymous",
    ) -> dict[str, Any]:
        """Raise a relationship-type candidate when a fact cannot map to an active type."""

        self._require_namespace(namespace)
        promoter = OntologyFactPromotionService(
            self._nm,
            KuzuGraphInstanceStore(self.get_kuzu_graph(namespace)),
            fact_store=self._fact_store,
            candidate_store=self._candidate_store,
            profile_store=self._ontology_store,
            evidence_store=self._evidence_store,
            observation_store=self._observation_store,
        )
        candidate = promoter.raise_relationship_candidate(namespace, fact_id, relationship_label=relationship_label, reviewed_by=reviewed_by)
        return candidate.model_dump(mode="json")


    def list_ontology_candidates(
        self,
        namespace: str,
        *,
        status: str | None = None,
        candidate_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List namespace ontology review candidates."""

        self._require_namespace(namespace)
        return [c.model_dump(mode="json") for c in self._candidate_store.list(namespace, status=status, candidate_type=candidate_type)]

    def approve_ontology_candidate(
        self,
        namespace: str,
        candidate_id: str,
        *,
        reviewed_by: str = "anonymous",
        canonical_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Approve a candidate by creating a canonical concept or relationship enum."""

        self._require_namespace(namespace)
        payload = payload or {}
        candidate = next((c for c in self._candidate_store.list(namespace) if c.id == candidate_id), None)
        if candidate is None:
            raise KeyError(f"Candidate not found: {candidate_id}")
        canonical = normalize_candidate_label(canonical_id or candidate.suggested_canonical or candidate.original_label)
        profile = self.get_ontology_profile(namespace) or create_default_ontology_profile(namespace)

        if candidate.candidate_type in {"node", "edge"}:
            # EPIC-004 instance candidates are not schema enum changes. Mark the
            # reviewed candidate approved, then route the write through the typed
            # approve-write service so Kuzu/graph remains the source of record and
            # provenance + observation events are emitted exactly once.
            updated_candidate = self._candidate_store.update_status(
                namespace,
                candidate_id,
                "approved",
                reviewed_by=reviewed_by,
                suggested_canonical=canonical,
                metadata={"approval_kind": "graph_instance"},
            )
            approval_service = OntologyApprovalService(
                self._nm,
                KuzuGraphInstanceStore(self.get_kuzu_graph(namespace)),
                candidate_store=self._candidate_store,
                profile_store=self._ontology_store,
                evidence_store=self._evidence_store,
            )
            instance = approval_service.approve_candidate(namespace, candidate_id, reviewed_by=reviewed_by)
            self._ontology_audit_store.audit_operation(
                namespace,
                actor=reviewed_by,
                op="candidate_instance_approve",
                reason="Ontology graph instance candidate approved",
                metadata={
                    "candidate_id": candidate_id,
                    "candidate_type": candidate.candidate_type,
                    "instance_id": instance.id,
                    "approval_kind": "graph_instance",
                },
            )
            self._record_candidate_observation(
                namespace,
                event_type="OntologyCandidateApproved",
                candidate=updated_candidate,
                reviewed_by=reviewed_by,
                metadata={"instance_id": instance.id, "approval_kind": "graph_instance"},
            )
            result = updated_candidate.model_dump(mode="json")
            result["confirmed_instance"] = instance.model_dump(mode="json", exclude_none=True)
            return result

        if candidate.candidate_type == "concept_type":
            from dashboard.knowledge.ontology.models import ConceptType  # noqa: WPS433
            level = payload.get("abstraction_level") or (next(iter(profile.abstraction_levels), "implementation"))
            profile.concept_types[canonical] = ConceptType(
                id=canonical,
                label=payload.get("label") or candidate.original_label.strip().title(),
                abstraction_level=level,
                description=payload.get("description") or f"Approved from extraction candidate {candidate.original_label!r}.",
                color=payload.get("color", "#64748b"),
                shape=payload.get("shape", "rounded_rectangle"),
            )
        elif candidate.candidate_type in {"relationship_type", "alias"}:
            from dashboard.knowledge.ontology.models import RelationshipType  # noqa: WPS433
            profile.relationship_types[canonical] = RelationshipType(
                id=canonical,
                label=payload.get("label") or candidate.original_label.strip().title(),
                family=payload.get("family", "semantic"),
                description=payload.get("description") or f"Approved from extraction candidate {candidate.original_label!r}.",
                allowed_source_types=list(payload.get("allowed_source_types") or []),
                allowed_target_types=list(payload.get("allowed_target_types") or []),
                weight=float(payload.get("weight", 0.5)),
                style=payload.get("style", "solid"),
                is_directed=bool(payload.get("is_directed", True)),
            )
        elif candidate.candidate_type == "metadata_field":
            from dashboard.knowledge.ontology.models import MetadataField  # noqa: WPS433
            proposed = {**candidate.proposed_payload, **payload}
            profile.metadata_fields[canonical] = MetadataField(
                id=canonical,
                label=proposed.get("label") or candidate.original_label.strip().title(),
                field_type=proposed.get("field_type", "string"),
                description=proposed.get("description") or f"Approved metadata field from candidate {candidate.original_label!r}.",
                required=bool(proposed.get("required", False)),
                default=proposed.get("default"),
                allowed_values=list(proposed.get("allowed_values") or []),
            )
        elif candidate.candidate_type == "validation_rule":
            from dashboard.knowledge.ontology.models import ValidationRule  # noqa: WPS433
            proposed = {**candidate.proposed_payload, **payload}
            profile.validation_rules.append(
                ValidationRule(
                    id=canonical,
                    label=proposed.get("label") or candidate.original_label.strip().title(),
                    rule_type=proposed.get("rule_type", "required_metadata"),
                    severity=proposed.get("severity", "error"),
                    message=proposed.get("message") or f"Validate {candidate.original_label.strip() or canonical}",
                    enabled=bool(proposed.get("enabled", True)),
                    params=dict(proposed.get("params") or {}),
                )
            )
        else:
            raise ValueError(f"Unsupported candidate type: {candidate.candidate_type}")

        saved = self.save_ontology_profile(profile, actor=reviewed_by, reason=f"Approve ontology candidate {candidate_id}")
        updated = self._candidate_store.update_status(
            namespace,
            candidate_id,
            "approved",
            reviewed_by=reviewed_by,
            suggested_canonical=canonical,
            metadata={"profile_version": saved.version},
        )
        self._ontology_audit_store.audit_operation(
            namespace,
            actor=reviewed_by,
            op="candidate_approve",
            reason="Ontology candidate approved",
            metadata={"candidate_id": candidate_id, "canonical_id": canonical, "profile_version": saved.version},
        )
        self._record_candidate_observation(
            namespace,
            event_type="OntologyCandidateApproved",
            candidate=updated,
            reviewed_by=reviewed_by,
            metadata={"canonical_id": canonical, "profile_version": saved.version, "approval_kind": "profile_change"},
        )
        return updated.model_dump(mode="json")

    def map_ontology_candidate(
        self,
        namespace: str,
        candidate_id: str,
        canonical_id: str,
        *,
        reviewed_by: str = "anonymous",
    ) -> dict[str, Any]:
        """Map a candidate label as an alias to an existing canonical enum."""

        self._require_namespace(namespace)
        candidate = next((c for c in self._candidate_store.list(namespace) if c.id == candidate_id), None)
        if candidate is None:
            raise KeyError(f"Candidate not found: {candidate_id}")
        canonical = normalize_candidate_label(canonical_id)
        alias = normalize_candidate_label(candidate.original_label)
        profile = self.get_ontology_profile(namespace) or create_default_ontology_profile(namespace)

        if candidate.candidate_type == "concept_type":
            if canonical not in profile.concept_types:
                raise ValueError(f"Unknown concept type: {canonical}")
            profile.concept_aliases[alias] = canonical
        else:
            if canonical not in profile.relationship_types:
                raise ValueError(f"Unknown relationship type: {canonical}")
            profile.aliases[alias] = canonical

        saved = self.save_ontology_profile(profile, actor=reviewed_by, reason=f"Map ontology candidate {candidate_id}")
        updated = self._candidate_store.update_status(
            namespace,
            candidate_id,
            "mapped",
            reviewed_by=reviewed_by,
            suggested_canonical=canonical,
            metadata={"profile_version": saved.version},
        )
        self._ontology_audit_store.audit_operation(
            namespace,
            actor=reviewed_by,
            op="candidate_map",
            reason="Ontology candidate mapped",
            metadata={"candidate_id": candidate_id, "canonical_id": canonical, "profile_version": saved.version},
        )
        self._record_candidate_observation(
            namespace,
            event_type="OntologyCandidateMapped",
            candidate=updated,
            reviewed_by=reviewed_by,
            metadata={"canonical_id": canonical, "profile_version": saved.version},
        )
        return updated.model_dump(mode="json")

    def reject_ontology_candidate(
        self,
        namespace: str,
        candidate_id: str,
        *,
        reviewed_by: str = "anonymous",
        reason: str = "",
    ) -> dict[str, Any]:
        """Reject a candidate; same source hash will not emit it again."""

        self._require_namespace(namespace)
        updated = self._candidate_store.update_status(
            namespace,
            candidate_id,
            "rejected",
            reviewed_by=reviewed_by,
            metadata={"reason": reason} if reason else None,
        )
        self._ontology_audit_store.audit_operation(
            namespace,
            actor=reviewed_by,
            op="candidate_reject",
            reason=reason or "Ontology candidate rejected",
            metadata={"candidate_id": candidate_id},
        )
        self._record_candidate_observation(
            namespace,
            event_type="OntologyCandidateRejected",
            candidate=updated,
            reviewed_by=reviewed_by,
            metadata={"reason": reason} if reason else {},
        )
        return updated.model_dump(mode="json")

    def bulk_update_ontology_candidates(
        self,
        namespace: str,
        actions: list[dict[str, Any]],
        *,
        reviewed_by: str = "anonymous",
    ) -> list[dict[str, Any]]:
        """Apply approve/map/reject actions to multiple candidates."""

        results: list[dict[str, Any]] = []
        for action in actions:
            op = action.get("action")
            cid = action.get("candidate_id") or action.get("id")
            if not cid:
                raise ValueError("candidate_id is required for bulk actions")
            if op == "approve":
                results.append(self.approve_ontology_candidate(namespace, cid, reviewed_by=reviewed_by, canonical_id=action.get("canonical_id"), payload=action.get("payload") or {}))
            elif op == "map":
                results.append(self.map_ontology_candidate(namespace, cid, action.get("canonical_id", ""), reviewed_by=reviewed_by))
            elif op == "reject":
                results.append(self.reject_ontology_candidate(namespace, cid, reviewed_by=reviewed_by, reason=action.get("reason", "")))
            else:
                raise ValueError(f"Unsupported candidate action: {op}")
        return results


    def _record_candidate_observation(
        self,
        namespace: str,
        *,
        event_type: str,
        candidate: Any,
        reviewed_by: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append candidate review events without weakening the review gate."""

        provenance_refs = [candidate.source_evidence_ref] if getattr(candidate, "source_evidence_ref", None) else []
        self._observation_store.create(
            namespace,
            event_type=event_type,
            subject_type="candidate",
            subject_id=candidate.id,
            created_by=reviewed_by,
            provenance_refs=provenance_refs,
            metadata={
                "candidate_type": candidate.candidate_type,
                "status": candidate.status,
                "source_hash": candidate.source_hash,
                **(metadata or {}),
            },
        )

    def normalize_relation(self, relation_type: str, namespace: str) -> Any:
        """Normalize a relationship label for a namespace ontology profile."""
        from dashboard.knowledge.ontology.normalizer import normalize_relation  # noqa: WPS433

        return normalize_relation(relation_type, self.get_ontology_profile(namespace))

    def validate_relationship(
        self,
        namespace: str,
        relation_type: str,
        source_concept_type: str,
        target_concept_type: str,
    ) -> list[Any]:
        """Validate relationship semantics for a namespace ontology profile."""
        from dashboard.knowledge.ontology.validator import validate_relationship  # noqa: WPS433

        profile = self.get_ontology_profile(namespace)
        if profile is None:
            return []
        return validate_relationship(relation_type, source_concept_type, target_concept_type, profile)

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
            self._observation_store.create(namespace, event_type="ImportSubmitted", subject_type="import", subject_id=job_id, actor=actor, metadata={"folder_path": folder_path})
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
            self._observation_store.create(namespace, event_type="ImportCompleted", subject_type="import", subject_id=f"inline:{source_label}", actor=actor, value=result.get("chunks_added", 0), metadata={"source_label": source_label, "chunks_added": result.get("chunks_added", 0), "entities_added": result.get("entities_added", 0), "relations_added": result.get("relations_added", 0)})
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

    # ---- Web Research (SearXNG) -----------------------------------------

    def research(
        self,
        namespace: str,
        query: str,
        *,
        engines: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
        max_results: int = 0,
        summarize: bool = True,
        language: str = "en",
        actor: str = "anonymous",
    ) -> dict:
        """Execute a web research cycle using SearXNG and ingest into namespace.

        Searches the web → fetches top pages → ingests content into the
        knowledge namespace → optionally generates an LLM summary.

        - Auto-creates the namespace when it doesn't exist.
        - Uses concurrent-import protection.
        - Runs in a dedicated thread (same pattern as import_text).

        Returns a :class:`ResearchResult` serialized as a dict.
        """
        from concurrent.futures import ThreadPoolExecutor
        from dashboard.knowledge.research.researcher import WebResearcher

        start_time = time.perf_counter()

        try:
            # Auto-create namespace if needed
            if self._nm.get(namespace) is None:
                embedder = self._get_embedder()
                self._nm.create(
                    namespace,
                    embedding_model=embedder.model_name,
                    embedding_dimension=embedder.dimension(),
                )

            ingestor = self._get_ingestor()

            # Build the researcher with all dependencies
            researcher = WebResearcher(
                ingestor=ingestor,
                llm=self._get_llm(),
            )

            register_import(namespace, "__pending_research__")

            def _run_research():
                return researcher.run(
                    query=query,
                    namespace=namespace,
                    engines=engines,
                    categories=categories,
                    max_results=max_results,
                    summarize=summarize,
                    language=language,
                )

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(_run_research).result()
            finally:
                unregister_import(namespace)

            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "research", "success", latency_ms, {"actor": actor, "query": query})
            return result.model_dump() if hasattr(result, "model_dump") else result

        except ImportInProgressError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "research", "import_in_progress", latency_ms, {"actor": actor})
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _log_call(namespace, "research", "error", latency_ms, {"actor": actor, "error": str(exc)})
            raise

    def search_web(
        self,
        query: str,
        *,
        engines: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
        max_results: int = 10,
        language: str = "en",
    ) -> dict:
        """Search the web via SearXNG and return preview results (no ingestion).

        This is the fast first step of the two-step research flow.
        Returns search results with titles, URLs, snippets, engines, and scores
        so the user can pick which ones to ingest.
        """
        from dashboard.knowledge.research.searxng_client import SearXNGClient

        start_time = time.perf_counter()
        warnings: list[str] = []

        client = SearXNGClient()
        results = client.search(
            query,
            engines=engines,
            categories=categories,
            language=language,
            max_results=max_results,
        )

        elapsed = time.perf_counter() - start_time
        return {
            "query": query,
            "engines_used": engines or [],
            "categories_used": categories or [],
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "engine": r.engine,
                    "score": r.score,
                    "thumbnail_url": r.thumbnail_url,
                    "metadata": r.metadata,
                }
                for r in results
            ],
            "elapsed_seconds": round(elapsed, 3),
            "warnings": warnings,
        }

    def research_ingest(
        self,
        namespace: str,
        query: str,
        items: list[dict],
        *,
        summarize: bool = True,
        language: str = "en",
        actor: str = "anonymous",
    ) -> str:
        """Submit a background job to fetch and ingest selected research URLs.

        This is the async second step of the two-step research flow.
        Returns the job_id immediately; the caller polls via get_job().

        Parameters
        ----------
        namespace : str
            Target namespace. Auto-created if it doesn't exist.
        query : str
            Original search query (used for provenance metadata).
        items : list[dict]
            Selected items, each with keys: url, title, engine, snippet.
        summarize : bool
            Whether to generate an LLM summary after ingestion.
        language : str
            Content language code.
        actor : str
            Who initiated the operation.

        Returns
        -------
        str
            The job_id for tracking progress.
        """
        # Auto-create namespace if needed
        if self._nm.get(namespace) is None:
            embedder = self._get_embedder()
            self._nm.create(
                namespace,
                embedding_model=embedder.model_name,
                embedding_dimension=embedder.dimension(),
            )

        jm = self._get_job_manager()

        # Register the import as in-progress BEFORE submitting the job.
        # This closes the TOCTOU window: register_import() is atomic and
        # will raise ImportInProgressError if another import is already
        # running for this namespace.
        register_import(namespace, "__pending__")

        def _job_fn(emit):
            try:
                from dashboard.knowledge.research.page_fetcher import PageFetcher
                from dashboard.knowledge.research.models import ResearchSourceResult
                from dashboard.knowledge.jobs import JobEvent, JobState

                fetcher = PageFetcher()
                ingestor = self._get_ingestor()
                total = len(items)
                sources: list[dict] = []
                batch_items: list[dict] = []

                # Fetch each selected URL
                for idx, item in enumerate(items):
                    url = item["url"]
                    title = item.get("title", "")
                    engine = item.get("engine", "")
                    snippet = item.get("snippet", "")

                    emit(JobEvent(
                        timestamp=datetime.now(timezone.utc),
                        state=JobState.RUNNING,
                        message=f"Fetching {idx + 1}/{total}: {title or url}",
                        progress_current=idx,
                        progress_total=total,
                        detail={},
                    ))

                    fetch_result = fetcher.fetch(url)

                    if not fetch_result.ok:
                        sources.append({
                            "url": url,
                            "title": title,
                            "engine": engine,
                            "status": "error",
                            "chunks_added": 0,
                            "error": fetch_result.error or f"HTTP {fetch_result.status_code}",
                        })
                        continue

                    if not fetch_result.markdown.strip():
                        sources.append({
                            "url": url,
                            "title": title,
                            "engine": engine,
                            "status": "skipped",
                            "chunks_added": 0,
                            "error": "Empty content after conversion",
                        })
                        continue

                    batch_items.append({
                        "text": fetch_result.markdown,
                        "source_url": url,
                        "source_title": title,
                        "metadata": {
                            "source_engine": engine,
                            "source_query": query,
                            "source_snippet": snippet[:200] if snippet else "",
                            "research_timestamp": time.time(),
                            "engines_used": [engine] if engine else [],
                        },
                    })
                    sources.append({
                        "url": url,
                        "title": title,
                        "engine": engine,
                        "status": "fetched",
                        "chunks_added": 0,
                        "error": None,
                    })

                # Ingest the batch
                totals = {"chunks_added": 0, "entities_added": 0, "relations_added": 0}
                if batch_items:
                    emit(JobEvent(
                        timestamp=datetime.now(timezone.utc),
                        state=JobState.RUNNING,
                        message=f"Ingesting {len(batch_items)} sources into {namespace}...",
                        progress_current=total,
                        progress_total=total,
                        detail={},
                    ))

                    try:
                        ingest_result = ingestor.ingest_research_batch(namespace, batch_items)
                        totals["chunks_added"] = ingest_result.get("chunks_added", 0)
                        totals["entities_added"] = ingest_result.get("entities_added", 0)
                        totals["relations_added"] = ingest_result.get("relations_added", 0)

                        # Update per-source status from ingest result
                        per_source = ingest_result.get("per_source", {})
                        for src in sources:
                            if src["status"] == "fetched":
                                chunks = per_source.get(src["url"], 0)
                                src["chunks_added"] = chunks
                                src["status"] = "ingested" if chunks > 0 else "skipped"
                    except Exception as exc:
                        logger.exception("research_ingest batch failed")
                        for src in sources:
                            if src["status"] == "fetched":
                                src["status"] = "error"
                                src["error"] = f"Ingestion failed: {exc}"

                # Optional LLM summary
                summary = None
                if summarize:
                    try:
                        llm = self._get_llm()
                        if llm and hasattr(llm, "is_available") and llm.is_available():
                            ingested_sources = [s for s in sources if s["status"] == "ingested"]
                            if ingested_sources:
                                summary_prompt = (
                                    f"Summarize the key findings from researching: '{query}'\n\n"
                                    f"Sources ingested ({len(ingested_sources)}):\n"
                                )
                                for s in ingested_sources[:10]:
                                    summary_prompt += f"- {s['title'] or s['url']}\n"
                                summary = llm.complete(summary_prompt)
                    except Exception as exc:
                        logger.warning("Research summary generation failed: %s", exc)

                return {
                    "query": query,
                    "namespace": namespace,
                    "engines_used": list({s["engine"] for s in sources if s.get("engine")}),
                    "categories_used": [],
                    "sources": sources,
                    "total_chunks_added": totals["chunks_added"],
                    "total_entities_added": totals["entities_added"],
                    "total_relations_added": totals["relations_added"],
                    "summary": summary,
                    "warnings": [],
                }
            finally:
                unregister_import(namespace)

        try:
            job_id = jm.submit(
                namespace,
                "research_ingest",
                _job_fn,
                message=f"Research ingest: {query} ({len(items)} sources)",
            )
        except Exception:
            # Submit failed — rollback the registration
            unregister_import(namespace)
            raise

        # Update the registration with the real job_id
        from dashboard.knowledge.audit import _active_imports, _active_imports_lock  # noqa: WPS433
        with _active_imports_lock:
            _active_imports[namespace] = job_id

        _log_call(namespace, "research_ingest", "submitted", 0, {"actor": actor, "query": query, "count": len(items)})
        return job_id

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

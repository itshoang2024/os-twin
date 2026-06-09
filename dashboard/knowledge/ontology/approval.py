"""Approve-write service for Graph-plane ontology instances.

All confirmed node/edge instances are written through a graph-store abstraction so
Kuzu remains the source of record.  The service refuses unreviewed direct
mutation, attaches EPIC-003 provenance when an evidence anchor is available, and
records observation events for confirmations and lifecycle transitions.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError
from dashboard.knowledge.ontology.candidates import OntologyCandidate, OntologyCandidateStore
from dashboard.knowledge.ontology.evidence import EvidenceStore
from dashboard.knowledge.ontology.instances import InstanceValidationIssue, OntologyEdge, OntologyNode
from dashboard.knowledge.ontology.models import OntologyProfile
from dashboard.knowledge.ontology.store import OntologyProfileStore


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OntologyMutationError(ValueError):
    """Raised when graph instance mutation bypasses review/validation gates."""


class GraphInstanceStore(Protocol):
    """Minimal Kuzu-source-of-record abstraction used by the approval service."""

    def upsert_node(self, node: OntologyNode) -> OntologyNode: ...
    def upsert_edge(self, edge: OntologyEdge) -> OntologyEdge: ...
    def get_node(self, node_id: str) -> OntologyNode | None: ...


from dashboard.knowledge.ontology.observation import ObservationEvent, ObservationEventStore


class InMemoryGraphInstanceStore:
    """Deterministic graph-store fake used by tests and service callers."""

    def __init__(self) -> None:
        self.nodes: dict[str, OntologyNode] = {}
        self.edges: dict[str, OntologyEdge] = {}

    def upsert_node(self, node: OntologyNode) -> OntologyNode:
        self.nodes[node.id] = node
        return node

    def upsert_edge(self, edge: OntologyEdge) -> OntologyEdge:
        self.edges[edge.id] = edge
        return edge

    def get_node(self, node_id: str) -> OntologyNode | None:
        return self.nodes.get(node_id)


class KuzuGraphInstanceStore:
    """Adapter that writes approved typed instances into Kuzu/LlamaIndex stores."""

    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def upsert_node(self, node: OntologyNode) -> OntologyNode:
        if hasattr(self.graph, "upsert_node"):
            self.graph.upsert_node(node)
            return node
        from llama_index.core.graph_stores.types import EntityNode

        self.graph.add_node(
            EntityNode(
                name=node.name,
                label=node.concept_type,
                properties=node.to_projection_dict().get("properties", {}) | {
                    "concept_type": node.concept_type,
                    "ontology_node": node.model_dump(mode="json", exclude_none=True),
                    "lifecycle_state": node.lifecycle_state,
                    "provenance_refs": node.provenance_refs,
                    "external_ref": node.external_ref.model_dump(mode="json") if node.external_ref else None,
                    "confidence": node.confidence,
                },
            )
        )
        return node

    def upsert_edge(self, edge: OntologyEdge) -> OntologyEdge:
        if hasattr(self.graph, "upsert_edge"):
            self.graph.upsert_edge(edge)
            return edge
        from llama_index.core.graph_stores.types import Relation

        self.graph.add_relation(
            Relation(
                source_id=edge.source_id,
                target_id=edge.target_id,
                label=edge.relationship_type,
                properties=edge.model_dump(mode="json", exclude_none=True),
            )
        )
        return edge

    def get_node(self, node_id: str) -> OntologyNode | None:
        if hasattr(self.graph, "get_node"):
            raw = self.graph.get_node(node_id)
            if raw is None:
                return None
            if isinstance(raw, OntologyNode):
                return raw
            return OntologyNode.from_kuzu_row(raw)
        return None


class OntologyApprovalService:
    """Reviewed candidate -> Kuzu instance + provenance + observation events."""

    def __init__(self, namespace_manager: NamespaceManager, graph_store: GraphInstanceStore, *, candidate_store: OntologyCandidateStore | None = None, profile_store: OntologyProfileStore | None = None, evidence_store: EvidenceStore | None = None, observation_store: ObservationEventStore | None = None) -> None:
        self._nm = namespace_manager
        self.graph_store = graph_store
        self.candidate_store = candidate_store or OntologyCandidateStore(namespace_manager)
        self.profile_store = profile_store or OntologyProfileStore(namespace_manager)
        self.evidence_store = evidence_store or EvidenceStore(namespace_manager)
        self.observation_store = observation_store or ObservationEventStore(namespace_manager)

    def approve_candidate(self, namespace: str, candidate_id: str, *, reviewed_by: str | None = None) -> OntologyNode | OntologyEdge:
        candidate = next((item for item in self.candidate_store.list(namespace) if item.id == candidate_id), None)
        if candidate is None:
            raise KeyError(f"Candidate not found: {candidate_id}")
        if candidate.status != "approved":
            raise OntologyMutationError("candidate must be reviewed/approved before graph mutation")
        if candidate.candidate_type == "node":
            return self.confirm_node(namespace, candidate, reviewed_by=reviewed_by)
        if candidate.candidate_type == "edge":
            return self.confirm_edge(namespace, candidate, reviewed_by=reviewed_by)
        raise OntologyMutationError("only node/edge candidates can be written as graph instances")

    def direct_upsert_node(self, node: OntologyNode) -> None:
        raise OntologyMutationError("direct graph instance mutation is blocked; use approve_candidate/confirm_node")

    def direct_upsert_edge(self, edge: OntologyEdge) -> None:
        raise OntologyMutationError("direct graph instance mutation is blocked; use approve_candidate/confirm_edge")

    def confirm_node(self, namespace: str, candidate: OntologyCandidate, *, reviewed_by: str | None = None) -> OntologyNode:
        self._require_reviewed(candidate, "node")
        profile = self.profile_store.get(namespace)
        payload = dict(candidate.proposed_payload or {})
        provenance_refs = self._provenance_refs(namespace, "node", payload.get("id") or candidate.suggested_canonical or candidate.id, candidate, reviewed_by)
        node = OntologyNode.from_kuzu_row(
            {
                **payload,
                "id": payload.get("id") or candidate.suggested_canonical or candidate.id,
                "name": payload.get("name") or candidate.original_label,
                "concept_type": payload.get("concept_type") or payload.get("type") or "entity",
                "lifecycle_state": payload.get("lifecycle_state") or "active",
                "confidence": payload.get("confidence", candidate.confidence),
                "provenance_refs": [*payload.get("provenance_refs", []), *provenance_refs],
            },
            namespace=namespace,
        )
        issues = self._validate_node(node, profile)
        if any(issue["severity"] == "error" for issue in issues):
            raise OntologyMutationError("node candidate does not validate against active profile: " + "; ".join(i["message"] for i in issues))
        if issues:
            node.validation_issues.extend(InstanceValidationIssue.model_validate(issue) for issue in issues)
        stored = self.graph_store.upsert_node(node)
        self._event(namespace, "ObjectConfirmed", "node", stored.id, reviewed_by, stored.provenance_refs, {"candidate_id": candidate.id})
        if stored.lifecycle_state == "active":
            self._event(namespace, "ObjectLifecycleActivated", "node", stored.id, reviewed_by, stored.provenance_refs, {"from": "approved_candidate", "to": "active"})
        return stored

    def confirm_edge(self, namespace: str, candidate: OntologyCandidate, *, reviewed_by: str | None = None) -> OntologyEdge:
        self._require_reviewed(candidate, "edge")
        profile = self.profile_store.get(namespace)
        payload = dict(candidate.proposed_payload or {})
        source = payload.get("source_id") or payload.get("source")
        target = payload.get("target_id") or payload.get("target")
        rel_type = payload.get("relationship_type") or payload.get("label") or "relates"
        edge_id = payload.get("id") or f"{source}:{rel_type}:{target}"
        provenance_refs = self._provenance_refs(namespace, "edge", edge_id, candidate, reviewed_by)
        edge = OntologyEdge.from_kuzu_row(
            {
                **payload,
                "id": edge_id,
                "source_id": source,
                "target_id": target,
                "relationship_type": rel_type,
                "review_state": payload.get("review_state") or "approved",
                "confidence": payload.get("confidence", candidate.confidence),
                "provenance_refs": [*payload.get("provenance_refs", []), *provenance_refs],
            },
            namespace=namespace,
        )
        issues = self._validate_edge(edge, profile)
        if any(issue["severity"] == "error" for issue in issues):
            raise OntologyMutationError("edge candidate does not validate against active profile: " + "; ".join(i["message"] for i in issues))
        if issues:
            edge.validation_issues.extend(InstanceValidationIssue.model_validate(issue) for issue in issues)
        stored = self.graph_store.upsert_edge(edge)
        self._event(namespace, "RelationshipConfirmed", "edge", stored.id, reviewed_by, stored.provenance_refs, {"candidate_id": candidate.id})
        if stored.review_state == "approved":
            self._event(namespace, "RelationshipApproved", "edge", stored.id, reviewed_by, stored.provenance_refs, {"from": "approved_candidate", "to": "approved"})
        return stored

    def _require_reviewed(self, candidate: OntologyCandidate, expected: str) -> None:
        if candidate.status != "approved" or candidate.candidate_type != expected:
            raise OntologyMutationError(f"{expected} candidates must be approved before mutation")

    def _validate_node(self, node: OntologyNode, profile: OntologyProfile | None) -> list[dict[str, Any]]:
        if profile is None:
            return []
        concept = profile.concept_types.get(node.concept_type)
        if concept is None or concept.lifecycle_state != "active":
            return [{"field": "concept_type", "severity": "error", "message": f"Concept type {node.concept_type!r} is not active in profile"}]
        issues = []
        for field_id, schema in concept.metadata_schema.items():
            if schema.required and field_id not in node.metadata and field_id not in node.properties:
                issues.append({"field": field_id, "severity": "error", "message": f"Required metadata {field_id!r} is missing"})
        return issues

    def _validate_edge(self, edge: OntologyEdge, profile: OntologyProfile | None) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        source_node = self.graph_store.get_node(edge.source_id)
        target_node = self.graph_store.get_node(edge.target_id)
        if source_node is None:
            issues.append({"field": "source_id", "severity": "error", "message": f"Source node {edge.source_id!r} does not exist"})
        if target_node is None:
            issues.append({"field": "target_id", "severity": "error", "message": f"Target node {edge.target_id!r} does not exist"})
        if profile is None:
            return issues
        rel = profile.relationship_types.get(edge.relationship_type)
        if rel is None or rel.lifecycle_state != "active":
            issues.append({"field": "relationship_type", "severity": "error", "message": f"Relationship type {edge.relationship_type!r} is not active in profile"})
            return issues
        if (
            source_node is not None
            and rel.allowed_source_types
            and source_node.concept_type not in rel.allowed_source_types
        ):
            issues.append({
                "field": "source_id",
                "severity": "error",
                "message": (
                    f"Source node {edge.source_id!r} has concept type {source_node.concept_type!r}, "
                    f"but relationship type {edge.relationship_type!r} allows sources {rel.allowed_source_types!r}"
                ),
            })
        if (
            target_node is not None
            and rel.allowed_target_types
            and target_node.concept_type not in rel.allowed_target_types
        ):
            issues.append({
                "field": "target_id",
                "severity": "error",
                "message": (
                    f"Target node {edge.target_id!r} has concept type {target_node.concept_type!r}, "
                    f"but relationship type {edge.relationship_type!r} allows targets {rel.allowed_target_types!r}"
                ),
            })
        return issues

    def _provenance_refs(self, namespace: str, subject_type: str, subject_id: str, candidate: OntologyCandidate, reviewed_by: str | None) -> list[str]:
        refs = []
        if candidate.source_evidence_ref:
            if candidate.source_evidence_ref.startswith("anchor:"):
                link = self.evidence_store.create_provenance_link(namespace, subject_type=subject_type, subject_id=subject_id, evidence_anchor_id=candidate.source_evidence_ref, relation="approved_by", created_by=reviewed_by, metadata={"candidate_id": candidate.id})
                refs.append(link.id)
            else:
                refs.append(candidate.source_evidence_ref)
        return refs

    def _event(self, namespace: str, event_type: str, subject_type: str, subject_id: str, created_by: str | None, provenance_refs: list[str], metadata: dict[str, Any]) -> None:
        self.observation_store.create(namespace, event_type=event_type, subject_type=subject_type, subject_id=subject_id, created_by=created_by, provenance_refs=provenance_refs, metadata=metadata)

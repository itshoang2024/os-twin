"""EPIC-004 typed instance graph adapter and approve-write tests."""

from __future__ import annotations

import pytest

from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology import (
    InMemoryGraphInstanceStore,
    OntologyApprovalService,
    OntologyMutationError,
    OntologyNode,
    OntologyEdge,
    create_default_ontology_profile,
)
from dashboard.knowledge.service import KnowledgeService


class CapturingGraph:
    def __init__(self) -> None:
        self.nodes = {}
        self.edges = {}

    def upsert_node(self, node):  # noqa: ANN001
        self.nodes[node.id] = node

    def upsert_edge(self, edge):  # noqa: ANN001
        self.edges[edge.id] = edge

    def get_node(self, node_id: str):
        return self.nodes.get(node_id)


def test_ontology_node_adapter_projects_full_and_legacy_rows_without_layout_fields() -> None:
    full = OntologyNode.from_kuzu_row(
        {
            "id": "svc-billing",
            "name": "Billing Service",
            "concept_type": "service",
            "lifecycle_state": "candidate",
            "confidence": "0.82",
            "external_ref": {"system": "crm", "id": "CRM-42", "uri": "https://crm/42"},
            "provenance_refs": ["prov-1", "prov-1", "prov-2"],
            "metadata": {"owner": "Finance", "layout_x": 20},
            "properties": {"layout": {"x": 1}, "description": "Handles billing"},
            "validation_issues": [{"message": "Needs owner review", "severity": "warning"}],
        },
        namespace="demo",
    )

    assert full.lifecycle_state == "candidate"
    assert full.confidence == 0.82
    assert full.external_ref is not None and full.external_ref.system == "crm"
    assert full.provenance_refs == ["prov-1", "prov-2"]
    assert "layout_x" not in full.metadata
    assert "layout" not in full.properties

    legacy = OntologyNode.from_kuzu_row({"id": "legacy-api", "label": "Screen"}, namespace="legacy")
    assert legacy.lifecycle_state == "active"
    assert legacy.ontology_unit_id == "legacy"
    assert legacy.concept_type == "Screen"


def test_ontology_edge_adapter_projects_review_metadata_and_legacy_defaults() -> None:
    edge = OntologyEdge.from_kuzu_row(
        {
            "source": {"id": "a"},
            "target": {"id": "b"},
            "label": "depends_on",
            "metadata": {"review_state": "candidate", "confidence": 0.5},
            "properties": {"external_ref": {"system": "jira", "id": "PROJ-1"}, "layout_y": 9},
            "provenance_refs": ["prov-edge"],
        },
        namespace="demo",
    )

    assert edge.source_id == "a"
    assert edge.target_id == "b"
    assert edge.relationship_type == "depends_on"
    assert edge.review_state == "candidate"
    assert edge.confidence == 0.5
    assert edge.external_ref is not None and edge.external_ref.id == "PROJ-1"
    assert edge.provenance_refs == ["prov-edge"]
    assert "layout_y" not in edge.properties


def test_approval_service_writes_reviewed_node_and_edge_and_emits_observations(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)
    service.save_ontology_profile(create_default_ontology_profile("demo"))
    graph = CapturingGraph()
    service._kuzu_graphs["demo"] = graph  # noqa: SLF001 - inject graph source-of-record fake

    node_candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="node",
        original_label="Billing API",
        source="inline://demo",
        source_hash="node-hash",
        proposed_payload={
            "id": "billing-api",
            "name": "Billing API",
            "concept_type": "service",
            "lifecycle_state": "active",
            "confidence": 0.91,
            "external_ref": {"system": "catalog", "id": "svc-1"},
            "properties": {"layout_x": 100},
        },
        source_evidence_ref="prov-node",
    )

    node_result = service.approve_ontology_candidate("demo", node_candidate.id, reviewed_by="po")
    assert node_result["status"] == "approved"
    assert node_result["confirmed_instance"]["id"] == "billing-api"
    assert "billing-api" in graph.nodes
    assert graph.nodes["billing-api"].provenance_refs == ["prov-node"]
    assert "layout_x" not in graph.nodes["billing-api"].properties

    # Add a target node through the same reviewed path so edge approval validates endpoints.
    target_candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="node",
        original_label="Payments API",
        source="inline://demo",
        source_hash="target-hash",
        proposed_payload={"id": "payments-api", "name": "Payments API", "concept_type": "service"},
    )
    service.approve_ontology_candidate("demo", target_candidate.id, reviewed_by="po")

    edge_candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="edge",
        original_label="Billing depends on Payments",
        source="inline://demo",
        source_hash="edge-hash",
        proposed_payload={
            "source_id": "billing-api",
            "target_id": "payments-api",
            "relationship_type": "depends_on",
            "review_state": "approved",
            "confidence": 0.77,
            "provenance_refs": ["prov-edge-extra"],
        },
        source_evidence_ref="prov-edge",
    )
    edge_result = service.approve_ontology_candidate("demo", edge_candidate.id, reviewed_by="po")

    assert edge_result["confirmed_instance"]["review_state"] == "approved"
    assert "billing-api:depends_on:payments-api" in graph.edges
    assert graph.edges["billing-api:depends_on:payments-api"].provenance_refs == ["prov-edge-extra", "prov-edge"]

    events = service._candidate_store  # noqa: F841, SLF001 - keep candidate store visible for debugging
    from dashboard.knowledge.ontology.approval import ObservationEventStore

    event_types = [event.event_type for event in ObservationEventStore(nm).list("demo")]
    assert "ObjectConfirmed" in event_types
    assert "RelationshipConfirmed" in event_types


def test_approval_service_blocks_unreviewed_direct_mutation(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    approval = OntologyApprovalService(nm, InMemoryGraphInstanceStore())
    with pytest.raises(OntologyMutationError):
        approval.direct_upsert_node(OntologyNode.from_kuzu_row({"id": "x", "name": "X", "concept_type": "service"}, namespace="demo"))

from __future__ import annotations

from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.graph_instruction import GraphInstruction
from dashboard.knowledge.ontology.packs import DomainPackStore
from dashboard.knowledge.ontology.projection import project_enterprise_map
from dashboard.knowledge.ontology.store import OntologyProfileStore
from dashboard.knowledge.ontology.validator import validate_node, validate_relationship


def _pack_store(tmp_path):
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    return DomainPackStore(nm, OntologyProfileStore(nm))


def test_default_profile_declares_graph_instruction_layers_and_map_direction():
    profile = create_default_ontology_profile("demo")

    assert isinstance(profile.graph_instruction, GraphInstruction)
    assert profile.concept_types["feature"].default_layer == "product"
    assert profile.concept_types["service"].default_layer == "delivery"
    assert profile.relationship_types["depends_on"].map_direction == "reversed"
    assert profile.graph_instruction.relationship_type_defaults["depends_on"].map_direction == "reversed"


def test_projection_uses_profile_declared_direction_not_hardcoded_set():
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    payload["relationship_types"]["depends_on"]["map_direction"] = "forward"
    payload["graph_instruction"]["relationship_type_defaults"]["depends_on"]["map_direction"] = "forward"
    profile = profile.__class__.model_validate(payload)

    result = project_enterprise_map(
        nodes=[
            {"id": "feature-1", "label": "feature", "concept_type": "feature"},
            {"id": "service-1", "label": "service", "concept_type": "service"},
        ],
        edges=[{"source": "feature-1", "target": "service-1", "relationship_type": "depends_on"}],
        profile=profile,
    )

    assert result["nodes"][0]["layer_id"] == "product"
    assert result["nodes"][1]["layer_id"] == "delivery"
    assert result["edges"][0]["map_direction"] == "forward"
    assert result["edges"][0]["map_source"] == "feature-1"


def test_audit_risk_and_ecommerce_packs_declare_required_concepts_and_fixtures(tmp_path):
    store = _pack_store(tmp_path)
    audit = store.load_manifest("audit-risk-management")
    ecommerce = store.load_manifest("ecommerce-logistics")

    audit_preview = store.validate(audit, create_default_ontology_profile("demo")).profile
    assert audit_preview is not None
    assert set(audit_preview.concept_types) >= {"risk", "control", "obligation", "evidence", "finding", "remediation"}
    assert set(ecommerce.concept_types) >= {
        "order",
        "shipment",
        "carrier",
        "inventory",
        "crm_touchpoint",
        "sla",
        "integration",
    }
    assert audit.graph_instruction.default_views
    assert ecommerce.graph_instruction.examples
    assert audit.fixtures and ecommerce.fixtures


def test_domain_pack_install_merges_layers_graph_instruction_and_validates_candidates(tmp_path):
    store = _pack_store(tmp_path)
    base = create_default_ontology_profile("demo")
    audit = store.load_manifest("audit-risk-management")
    result = store.validate(audit, base)

    assert result.valid is True
    assert result.profile is not None
    merged = result.profile
    assert "governance" in merged.layers
    assert merged.concept_types["risk"].default_layer == "governance"
    assert merged.relationship_types["mitigates"].map_direction == "forward"
    assert merged.relationship_types["mitigates"].family == "validation"
    assert validate_relationship("mitigates", "control", "risk", merged) == []
    assert validate_node("unknown_audit_thing", merged)[0].code == "UNKNOWN_CONCEPT_TYPE"
    assert validate_relationship("mystery_link", "control", "risk", merged)[0].code == "CANDIDATE_RELATION_TYPE"

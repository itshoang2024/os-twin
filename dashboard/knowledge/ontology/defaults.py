"""Deterministic bootstrap ontology profiles."""

from __future__ import annotations

from dashboard.knowledge.ontology.graph_instruction import (
    ConceptGraphInstruction,
    GraphDefaultView,
    GraphInstruction,
    GraphLayoutHint,
    RelationshipGraphInstruction,
)
from dashboard.knowledge.ontology.models import (
    AbstractionLevel,
    ConceptType,
    Layer,
    MetadataField,
    OntologyProfile,
    RelationshipType,
    ValidationRule,
)

DEFAULT_PROFILE_ID = "enterprise_feature_map"
DEFAULT_PROFILE_VERSION = "1.0.0"


def create_default_ontology_profile(namespace: str, *, version: str = DEFAULT_PROFILE_VERSION) -> OntologyProfile:
    """Create the deterministic enterprise feature map ontology profile."""

    metadata_fields = {
        "owner": MetadataField(id="owner", label="Owner", field_type="string", description="Accountable team or role"),
        "status": MetadataField(
            id="status",
            label="Delivery status",
            field_type="enum",
            allowed_values=["planned", "in_progress", "released", "deprecated"],
            description="Lifecycle state of the mapped item",
        ),
        "source": MetadataField(
            id="source",
            label="Source",
            field_type="string",
            description="Source document or system",
        ),
    }
    abstraction_levels = {
        "portfolio": AbstractionLevel(id="portfolio", label="Portfolio", order=0),
        "capability": AbstractionLevel(id="capability", label="Capability", order=1),
        "feature": AbstractionLevel(id="feature", label="Feature", order=2),
        "implementation": AbstractionLevel(id="implementation", label="Implementation", order=3),
    }
    layers = {
        "strategy": Layer(id="strategy", label="Strategy", order=0, description="Business outcomes and value streams"),
        "product": Layer(id="product", label="Product", order=1, description="Capabilities and features"),
        "delivery": Layer(
            id="delivery",
            label="Delivery",
            order=2,
            description="Implementation and operational assets",
        ),
    }
    concept_types = {
        "business_domain": ConceptType(
            id="business_domain",
            label="Business Domain",
            abstraction_level="portfolio",
            default_layer="strategy",
            description="Top-level enterprise or product domain",
            metadata_schema={"owner": metadata_fields["owner"]},
            color="#1d4ed8",
            shape="hexagon",
        ),
        "capability": ConceptType(
            id="capability",
            label="Capability",
            abstraction_level="capability",
            default_layer="product",
            description="Stable business or platform capability",
            metadata_schema={"owner": metadata_fields["owner"], "status": metadata_fields["status"]},
            color="#047857",
            shape="rounded_rectangle",
        ),
        "feature": ConceptType(
            id="feature",
            label="Feature",
            abstraction_level="feature",
            default_layer="product",
            description="User-visible or API-visible feature",
            metadata_schema={"owner": metadata_fields["owner"], "status": metadata_fields["status"]},
            color="#7c3aed",
            shape="rectangle",
        ),
        "service": ConceptType(
            id="service",
            label="Service",
            abstraction_level="implementation",
            default_layer="delivery",
            description="Runtime service, module, or backend component",
            metadata_schema={"owner": metadata_fields["owner"], "source": metadata_fields["source"]},
            color="#b45309",
            shape="cylinder",
        ),
        "data_entity": ConceptType(
            id="data_entity",
            label="Data Entity",
            abstraction_level="implementation",
            default_layer="delivery",
            description="Persisted entity, event, or document shape",
            metadata_schema={"source": metadata_fields["source"]},
            color="#0f766e",
            shape="diamond",
        ),
        "data_object": ConceptType(
            id="data_object",
            label="Data Object",
            abstraction_level="implementation",
            default_layer="delivery",
            description="Artifact-like data object produced or consumed by services and features",
            metadata_schema={"source": metadata_fields["source"]},
            color="#0e7490",
            shape="diamond",
        ),
        "event": ConceptType(
            id="event",
            label="Event",
            abstraction_level="implementation",
            default_layer="delivery",
            description="Runtime or domain event emitted as an artifact",
            metadata_schema={"source": metadata_fields["source"]},
            color="#0891b2",
            shape="diamond",
        ),
        "evidence": ConceptType(
            id="evidence",
            label="Evidence",
            abstraction_level="implementation",
            default_layer="delivery",
            description="Traceability evidence, decision support, or validation artifact",
            metadata_schema={"source": metadata_fields["source"]},
            color="#0369a1",
            shape="document",
        ),
    }
    relationship_types = {
        "contains": RelationshipType(
            id="contains",
            label="Contains",
            family="composition",
            inverse="part_of",
            allowed_source_types=["business_domain", "capability"],
            allowed_target_types=["capability", "feature"],
            weight=0.9,
        ),
        "part_of": RelationshipType(
            id="part_of",
            label="Part of",
            family="composition",
            inverse="contains",
            allowed_source_types=["capability", "feature"],
            allowed_target_types=["business_domain", "capability"],
            weight=0.9,
            map_direction="reversed",
        ),
        "depends_on": RelationshipType(
            id="depends_on",
            label="Depends on",
            family="dependency",
            inverse="enables",
            allowed_source_types=["feature", "service"],
            allowed_target_types=["feature", "service", "data_entity", "data_object", "event", "evidence"],
            weight=0.7,
            style="dashed",
            map_direction="reversed",
        ),
        "enables": RelationshipType(
            id="enables",
            label="Enables",
            family="dependency",
            inverse="depends_on",
            allowed_source_types=["feature", "service", "data_entity", "data_object", "event", "evidence"],
            allowed_target_types=["feature", "service"],
            weight=0.7,
            style="dashed",
            is_system=True,
        ),
        "consumes": RelationshipType(
            id="consumes",
            label="Consumes",
            family="flow",
            allowed_source_types=["feature", "service"],
            allowed_target_types=["data_entity", "data_object", "event", "evidence"],
            weight=0.6,
            map_direction="reversed",
        ),
        "produces": RelationshipType(
            id="produces",
            label="Produces",
            family="flow",
            allowed_source_types=["feature", "service"],
            allowed_target_types=["data_object", "event", "evidence"],
            weight=0.6,
        ),
        "implemented_by": RelationshipType(
            id="implemented_by",
            label="Implemented by",
            family="traceability",
            inverse="implements",
            allowed_source_types=["feature"],
            allowed_target_types=["service"],
            weight=0.8,
            map_direction="reversed",
        ),
        "implements": RelationshipType(
            id="implements",
            label="Implements",
            family="traceability",
            inverse="implemented_by",
            allowed_source_types=["service"],
            allowed_target_types=["feature"],
            weight=0.8,
        ),
        "reads_writes": RelationshipType(
            id="reads_writes",
            label="Reads/Writes",
            family="flow",
            allowed_source_types=["service"],
            allowed_target_types=["data_entity"],
            weight=0.6,
        ),
        "evidences": RelationshipType(
            id="evidences",
            label="Evidences",
            family="assurance",
            allowed_source_types=["evidence", "data_object", "event"],
            allowed_target_types=["feature", "service", "capability"],
            weight=0.7,
            style="dotted",
        ),
        "mitigates": RelationshipType(
            id="mitigates",
            label="Mitigates",
            family="validation",
            allowed_source_types=["feature", "service"],
            allowed_target_types=["feature", "service"],
            weight=0.8,
            style="bold",
        ),
        "syncs_with": RelationshipType(
            id="syncs_with",
            label="Syncs with",
            family="synchronization",
            allowed_source_types=["feature", "service", "data_object", "event"],
            allowed_target_types=["feature", "service", "data_object", "event"],
            weight=0.5,
            style="dashed",
        ),
    }
    validation_rules = [
        ValidationRule(
            id="alias_targets_canonical_relationship",
            label="Alias targets canonical relationship",
            rule_type="alias_resolution",
            severity="error",
            message="Relationship aliases must resolve to canonical relationship type ids.",
        ),
        ValidationRule(
            id="relationship_endpoints_known",
            label="Relationship endpoints known",
            rule_type="allowed_relationship",
            severity="error",
            message="Relationship source and target concept types must exist in the profile.",
        ),
        ValidationRule(
            id="produces_target_artifact_like",
            label="Produces targets artifact-like concepts",
            rule_type="allowed_relationship",
            severity="warning",
            message="Produces should target data_object, event, evidence, or configured artifact-like concepts.",
        ),
    ]
    graph_instruction = GraphInstruction(
        default_lane_dimension="default_layer",
        layout_hints=GraphLayoutHint(
            lane_dimension="default_layer",
            orientation="horizontal",
            group_by=["default_layer", "concept_type"],
            sort_by=["layer_order", "label"],
        ),
        default_views=[
            GraphDefaultView(
                id="enterprise_map",
                label="Enterprise Map",
                lane_dimension="default_layer",
                description="Default lane view for profile-aware enterprise maps.",
            )
        ],
        concept_type_defaults={
            cid: ConceptGraphInstruction(
                concept_type=cid,
                default_layer=concept.default_layer,
                color=concept.color,
                shape=concept.shape,
            )
            for cid, concept in concept_types.items()
        },
        relationship_type_defaults={
            rid: RelationshipGraphInstruction(
                relationship_type=rid,
                map_direction=relationship.map_direction,
                color="#64748b",
                dash="6 4" if relationship.style == "dashed" else None,
                weight=relationship.weight,
            )
            for rid, relationship in relationship_types.items()
        },
        validation_rules=[rule.id for rule in validation_rules],
    )
    return OntologyProfile(
        profile_id=DEFAULT_PROFILE_ID,
        namespace=namespace,
        version=version,
        status="active",
        concept_types=concept_types,
        relationship_types=relationship_types,
        layers=layers,
        abstraction_levels=abstraction_levels,
        metadata_fields=metadata_fields,
        aliases={
            "owns": "contains",
            "requires": "depends_on",
            "prerequisite": "depends_on",
            "backed_by": "implemented_by",
        },
        validation_rules=validation_rules,
        graph_instruction=graph_instruction,
    )

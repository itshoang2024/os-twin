"""Typed ontology profile schema for namespace-specific knowledge graphs."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dashboard.knowledge.ontology.graph_instruction import GraphInstruction, MapDirection

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

LifecycleState = Literal["draft", "active", "deprecated", "retired"]


class OntologyUnitLifecycle(str, Enum):
    """Lifecycle states for the namespace-scoped ontology aggregate root."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


ONTOLOGY_LIFECYCLE_STATES = frozenset(item.value for item in OntologyUnitLifecycle)


def is_ontology_lifecycle_state(value: str) -> bool:
    """Return whether ``value`` is a schema/unit lifecycle state, not review status."""

    return value in ONTOLOGY_LIFECYCLE_STATES


OntologyProfileStatus = Literal["draft", "active", "deprecated", "archived"]
RelationshipFamily = Literal[
    "composition",
    "dependency",
    "flow",
    "semantic",
    "ownership",
    "classification",
    "causality",
    "temporal",
    "validation",
    "traceability",
    "assurance",
    "synchronization",
]
RelationshipStyle = Literal["solid", "dashed", "dotted", "bold"]
RelationshipCardinality = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
SourceMappingKind = Literal["document", "database", "api", "file", "event", "manual", "derived", "other"]
MetadataFieldType = Literal["string", "number", "integer", "boolean", "array", "object", "date", "datetime", "enum"]
ValidationRuleType = Literal[
    "required_metadata",
    "allowed_relationship",
    "alias_resolution",
    "acyclic_relationship",
    "cardinality",
]
ValidationSeverity = Literal["info", "warning", "error"]


def _validate_identifier(value: str, field_name: str) -> str:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"{field_name} must match {_IDENTIFIER_RE.pattern}")
    return value


class StrictOntologyModel(BaseModel):
    """Base model that rejects unknown fields to keep profiles canonical."""

    model_config = {"extra": "forbid"}


class OntologyUnit(StrictOntologyModel):
    """Namespace-scoped ontology unit persisted as ``ontology/unit.json``.

    The unit is the durable lifecycle/configuration wrapper for a namespace's
    ontology profile. Its ``id`` is intentionally derived from the namespace so
    existing namespace-keyed APIs do not need to be re-keyed. Entity candidate
    review status remains separate from profile/unit lifecycle state.
    """

    id: str | None = None
    namespace: str
    active_profile_id: str | None = None
    name: str = ""
    purpose: str = ""
    domain: str = ""
    expected_users: list[str] = Field(default_factory=list)
    source_material: list[str] = Field(default_factory=list)
    governance_mode: str = "manual"
    lifecycle: OntologyUnitLifecycle = OntologyUnitLifecycle.ACTIVE
    installed_packs: list[str] = Field(default_factory=list)
    auto_confirm_threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("namespace")
    @classmethod
    def _namespace_has_value(cls, value: str) -> str:
        if not value:
            raise ValueError("OntologyUnit.namespace is required")
        return value

    @field_validator("active_profile_id")
    @classmethod
    def _active_profile_id_is_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_identifier(value, "OntologyUnit.active_profile_id")

    @field_validator("name", "purpose", "domain", "governance_mode")
    @classmethod
    def _unit_text_fields_are_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("expected_users", "source_material")
    @classmethod
    def _unit_lists_are_strings(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("installed_packs")
    @classmethod
    def _installed_packs_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("OntologyUnit.installed_packs must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _derive_and_validate_id(self) -> OntologyUnit:
        derived_id = self.namespace
        if self.id is None:
            self.id = derived_id
        elif self.id != derived_id:
            raise ValueError("OntologyUnit.id must be derived from namespace")
        if self.active_profile_id is not None and ":" in self.active_profile_id and not self.active_profile_id.startswith(f"{self.namespace}:"):
            raise ValueError("OntologyUnit.active_profile_id cannot point outside namespace")
        return self


class SourceMapping(StrictOntologyModel):
    """Traceability from an ontology schema element to an upstream data source.

    Source mappings are intentionally declarative metadata. They let domains
    such as audit, ingestion, and evidence review map a concept, relationship,
    or property definition to source systems without mutating graph instances.
    """

    source_id: str
    source_type: SourceMappingKind = "other"
    source_label: str = ""
    field_path: str = ""
    transform: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str = ""

    @field_validator("source_id")
    @classmethod
    def _source_id_has_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("SourceMapping.source_id is required")
        return value

    @field_validator("source_label", "field_path", "transform", "notes")
    @classmethod
    def _source_text_fields_are_strings(cls, value: str) -> str:
        return value.strip()


class MetadataField(StrictOntologyModel):
    """Field definition used inside concept metadata schemas."""

    id: str
    label: str
    field_type: MetadataFieldType
    description: str = ""
    required: bool = False
    default: Any = None
    allowed_values: list[str] = Field(default_factory=list)
    lifecycle_state: LifecycleState = "active"
    source_mappings: list[SourceMapping] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "MetadataField.id")

    @model_validator(mode="after")
    def _enum_has_values(self) -> MetadataField:
        if self.field_type == "enum" and not self.allowed_values:
            raise ValueError("enum metadata fields must define allowed_values")
        return self


class AbstractionLevel(StrictOntologyModel):
    """Named abstraction tier for concepts, ordered from concrete to abstract."""

    id: str
    label: str
    order: int = Field(ge=0)
    description: str = ""

    @field_validator("id")
    @classmethod
    def _id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "AbstractionLevel.id")


class Layer(StrictOntologyModel):
    """Ontology layer used to group concepts in maps and validation rules."""

    id: str
    label: str
    order: int = Field(ge=0)
    description: str = ""
    lifecycle_state: LifecycleState = "active"
    source_mappings: list[SourceMapping] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "Layer.id")


class ConceptType(StrictOntologyModel):
    """Canonical node type available in an ontology profile."""

    id: str
    label: str
    abstraction_level: str
    default_layer: str | None = None
    description: str = ""
    metadata_schema: dict[str, MetadataField] = Field(default_factory=dict)
    color: str = "#64748b"
    shape: str = "rounded_rectangle"
    lifecycle_state: LifecycleState = "active"
    source_mappings: list[SourceMapping] = Field(default_factory=list)

    @field_validator("id", "abstraction_level")
    @classmethod
    def _ids_are_identifiers(cls, value: str) -> str:
        return _validate_identifier(value, "ConceptType identifier")

    @field_validator("default_layer")
    @classmethod
    def _default_layer_is_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_identifier(value, "ConceptType.default_layer")

    @field_validator("color")
    @classmethod
    def _color_is_hex(cls, value: str) -> str:
        if not _HEX_COLOR_RE.match(value):
            raise ValueError("ConceptType.color must be a #RRGGBB hex color")
        return value


class RelationshipType(StrictOntologyModel):
    """Canonical edge type available in an ontology profile."""

    id: str
    label: str
    family: RelationshipFamily
    inverse: str | None = None
    description: str = ""
    allowed_source_types: list[str] = Field(default_factory=list)
    allowed_target_types: list[str] = Field(default_factory=list)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    style: RelationshipStyle = "solid"
    map_direction: MapDirection = "forward"
    is_directed: bool = True
    is_system: bool = False
    cardinality: RelationshipCardinality | None = None
    lifecycle_state: LifecycleState = "active"
    source_mappings: list[SourceMapping] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "RelationshipType.id")

    @field_validator("inverse")
    @classmethod
    def _inverse_is_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_identifier(value, "RelationshipType.inverse")

    @field_validator("allowed_source_types", "allowed_target_types")
    @classmethod
    def _allowed_types_are_identifiers(cls, value: list[str]) -> list[str]:
        return [_validate_identifier(item, "RelationshipType.allowed_*_types") for item in value]


class ValidationRule(StrictOntologyModel):
    """Validation rule metadata stored with a profile."""

    id: str
    label: str
    rule_type: ValidationRuleType
    severity: ValidationSeverity = "error"
    message: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "ValidationRule.id")


class OntologyProfile(StrictOntologyModel):
    """Namespace-scoped ontology profile persisted as ``ontology/profile.json``."""

    profile_id: str
    namespace: str
    version: str
    status: OntologyProfileStatus = "active"
    concept_types: dict[str, ConceptType] = Field(default_factory=dict)
    relationship_types: dict[str, RelationshipType] = Field(default_factory=dict)
    layers: dict[str, Layer] = Field(default_factory=dict)
    abstraction_levels: dict[str, AbstractionLevel] = Field(default_factory=dict)
    metadata_fields: dict[str, MetadataField] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    concept_aliases: dict[str, str] = Field(default_factory=dict)
    validation_rules: list[ValidationRule] = Field(default_factory=list)
    graph_instruction: GraphInstruction = Field(default_factory=GraphInstruction)

    @field_validator("profile_id")
    @classmethod
    def _profile_id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "OntologyProfile.profile_id")

    @field_validator("namespace")
    @classmethod
    def _namespace_has_value(cls, value: str) -> str:
        if not value:
            raise ValueError("OntologyProfile.namespace is required")
        return value

    @model_validator(mode="after")
    def _validate_cross_references(self) -> OntologyProfile:
        concept_ids = set(self.concept_types)
        relationship_ids = set(self.relationship_types)
        level_ids = set(self.abstraction_levels)
        layer_ids = set(self.layers)

        for key, concept in self.concept_types.items():
            if key != concept.id:
                raise ValueError(f"concept_types key {key!r} must match ConceptType.id {concept.id!r}")
            if concept.abstraction_level not in level_ids:
                raise ValueError(
                    f"ConceptType {concept.id!r} references unknown abstraction_level {concept.abstraction_level!r}"
                )
            if concept.default_layer is not None and concept.default_layer not in layer_ids:
                raise ValueError(
                    f"ConceptType {concept.id!r} references unknown default_layer {concept.default_layer!r}"
                )

        for key, relationship in self.relationship_types.items():
            if key != relationship.id:
                raise ValueError(
                    f"relationship_types key {key!r} must match RelationshipType.id {relationship.id!r}"
                )
            missing_sources = set(relationship.allowed_source_types) - concept_ids
            missing_targets = set(relationship.allowed_target_types) - concept_ids
            if missing_sources:
                raise ValueError(
                    f"RelationshipType {relationship.id!r} has unknown source types {sorted(missing_sources)}"
                )
            if missing_targets:
                raise ValueError(
                    f"RelationshipType {relationship.id!r} has unknown target types {sorted(missing_targets)}"
                )
            if relationship.inverse and relationship.inverse not in relationship_ids:
                raise ValueError(f"RelationshipType {relationship.id!r} inverse {relationship.inverse!r} is unknown")

        for key, level in self.abstraction_levels.items():
            if key != level.id:
                raise ValueError(f"abstraction_levels key {key!r} must match AbstractionLevel.id {level.id!r}")
        for key, layer in self.layers.items():
            if key != layer.id:
                raise ValueError(f"layers key {key!r} must match Layer.id {layer.id!r}")
        for key, field in self.metadata_fields.items():
            if key != field.id:
                raise ValueError(f"metadata_fields key {key!r} must match MetadataField.id {field.id!r}")

        for alias, canonical_id in self.aliases.items():
            _validate_identifier(alias, "OntologyProfile.aliases key")
            if alias in relationship_ids:
                raise ValueError(f"relationship alias {alias!r} cannot shadow a canonical relationship id")
            if canonical_id not in relationship_ids:
                raise ValueError(f"relationship alias {alias!r} targets unknown relationship id {canonical_id!r}")

        for alias, canonical_id in self.concept_aliases.items():
            _validate_identifier(alias, "OntologyProfile.concept_aliases key")
            if alias in concept_ids:
                raise ValueError(f"concept alias {alias!r} cannot shadow a canonical concept id")
            if canonical_id not in concept_ids:
                raise ValueError(f"concept alias {alias!r} targets unknown concept id {canonical_id!r}")
        return self

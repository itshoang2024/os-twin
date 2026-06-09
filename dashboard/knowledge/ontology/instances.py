"""Typed Graph-plane instance adapters over Kuzu-like rows.

EPIC-004 keeps Kuzu as the source of record for confirmed instances.  These
models are strict read adapters: they normalize the loose row shapes returned by
Kuzu/LlamaIndex/fakes into explicit OntologyNode and OntologyEdge contracts while
remaining tolerant of legacy rows that predate review metadata.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from dashboard.knowledge.ontology.models import StrictOntologyModel, _validate_identifier

NodeLifecycleState = Literal["candidate", "active", "deprecated", "retired"]
EdgeReviewState = Literal["candidate", "approved", "rejected"]

_VISUAL_INSTANCE_FIELDS = frozenset(
    {
        "x",
        "y",
        "fx",
        "fy",
        "position",
        "layout",
        "layout_hint",
        "layout_x",
        "layout_y",
        "color",
        "shape",
        "concept_color",
        "concept_shape",
        "style",
        "dash",
        "map_source",
        "map_target",
        "map_direction",
        "map_group",
    }
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class ExternalRef(StrictOntologyModel):
    """Pointer to a source-of-record object outside the knowledge graph."""

    system: str
    id: str
    uri: str | None = None

    @field_validator("system", "id")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("ExternalRef.system and ExternalRef.id are required")
        return str(value)


class InstanceValidationIssue(StrictOntologyModel):
    """Validation issue attached to a projected graph instance."""

    field: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    code: str | None = None

    @field_validator("message")
    @classmethod
    def _message_required(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("validation issue message is required")
        return str(value)


class OntologyNode(StrictOntologyModel):
    """Strict typed adapter for a confirmed/candidate node row stored in Kuzu."""

    id: str
    ontology_unit_id: str
    concept_type: str
    name: str
    description: str = ""
    lifecycle_state: NodeLifecycleState = "active"
    external_ref: ExternalRef | None = None
    layer_id: str | None = None
    abstraction_level: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)
    validation_issues: list[InstanceValidationIssue] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("id", "ontology_unit_id", "concept_type")
    @classmethod
    def _ids_have_value(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("node identifiers are required")
        return str(value)

    @field_validator("layer_id", "abstraction_level")
    @classmethod
    def _optional_identifiers(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        return _validate_identifier(str(value), "OntologyNode optional identifier")

    @field_validator("provenance_refs")
    @classmethod
    def _dedupe_refs(cls, value: list[str]) -> list[str]:
        return _dedupe_strings(value)

    @model_validator(mode="after")
    def _strip_visual_payload(self) -> "OntologyNode":
        self.metadata = strip_visual_fields(self.metadata)
        self.properties = strip_visual_fields(self.properties)
        return self

    @classmethod
    def from_kuzu_row(cls, row: Any, *, namespace: str | None = None, ontology_unit_id: str | None = None) -> "OntologyNode":
        data = normalize_kuzu_node_row(row)
        props = coerce_mapping(data.get("properties"))
        metadata = coerce_mapping(data.get("metadata") or props.get("metadata"))
        node_id = str(data.get("id") or props.get("id") or data.get("name") or props.get("name") or "").strip()
        name = str(data.get("name") or props.get("name") or data.get("label") or node_id).strip()
        concept_type = str(data.get("concept_type") or props.get("concept_type") or props.get("type") or data.get("label") or "entity").strip()
        lifecycle_state = str(data.get("lifecycle_state") or metadata.get("lifecycle_state") or props.get("lifecycle_state") or "active")
        return cls(
            id=node_id,
            ontology_unit_id=str(ontology_unit_id or data.get("ontology_unit_id") or props.get("ontology_unit_id") or namespace or "legacy"),
            concept_type=concept_type,
            name=name,
            description=str(data.get("description") or metadata.get("description") or props.get("description") or props.get("entity_description") or ""),
            lifecycle_state=lifecycle_state,
            external_ref=coerce_external_ref(data.get("external_ref") or metadata.get("external_ref") or props.get("external_ref")),
            layer_id=optional_str(data.get("layer_id") or metadata.get("layer_id") or props.get("layer_id") or props.get("layer")),
            abstraction_level=optional_str(data.get("abstraction_level") or metadata.get("abstraction_level") or props.get("abstraction_level")),
            confidence=coerce_confidence(data.get("confidence") or metadata.get("confidence") or props.get("confidence")),
            provenance_refs=coerce_str_list(data.get("provenance_refs") or metadata.get("provenance_refs") or props.get("provenance_refs")),
            metadata=metadata,
            properties=props,
            validation_issues=coerce_validation_issues(data.get("validation_issues") or metadata.get("validation_issues") or props.get("validation_issues")),
            created_at=coerce_datetime(data.get("created_at") or metadata.get("created_at") or props.get("created_at")),
            updated_at=coerce_datetime(data.get("updated_at") or metadata.get("updated_at") or props.get("updated_at")),
        )

    def to_projection_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=True)
        payload["label"] = self.name
        payload["properties"] = strip_visual_fields(payload.get("properties") or {})
        payload["metadata"] = strip_visual_fields(payload.get("metadata") or {})
        return payload


class OntologyEdge(StrictOntologyModel):
    """Strict typed adapter for a relationship row stored in Kuzu."""

    id: str
    ontology_unit_id: str
    relationship_type: str
    source_id: str
    target_id: str
    review_state: EdgeReviewState = "approved"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance_refs: list[str] = Field(default_factory=list)
    external_ref: ExternalRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)
    validation_issues: list[InstanceValidationIssue] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("id", "ontology_unit_id", "relationship_type", "source_id", "target_id")
    @classmethod
    def _required_values(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("edge identifiers are required")
        return str(value)

    @field_validator("relationship_type")
    @classmethod
    def _relationship_type_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "OntologyEdge.relationship_type")

    @field_validator("provenance_refs")
    @classmethod
    def _dedupe_refs(cls, value: list[str]) -> list[str]:
        return _dedupe_strings(value)

    @model_validator(mode="after")
    def _strip_visual_payload(self) -> "OntologyEdge":
        self.metadata = strip_visual_fields(self.metadata)
        self.properties = strip_visual_fields(self.properties)
        return self

    @classmethod
    def from_kuzu_row(cls, row: Any, *, namespace: str | None = None, ontology_unit_id: str | None = None) -> "OntologyEdge":
        data = normalize_kuzu_edge_row(row)
        props = coerce_mapping(data.get("properties") or data.get("relation_properties"))
        metadata = coerce_mapping(data.get("metadata") or props.get("metadata"))
        source = str(data.get("source_id") or data.get("source") or props.get("source_id") or "").strip()
        target = str(data.get("target_id") or data.get("target") or props.get("target_id") or "").strip()
        rel_type = str(data.get("relationship_type") or data.get("relation_label") or data.get("label") or props.get("relationship_type") or props.get("relation_label") or "relates").strip()
        edge_id = str(data.get("id") or props.get("id") or f"{source}:{rel_type}:{target}").strip()
        return cls(
            id=edge_id,
            ontology_unit_id=str(ontology_unit_id or data.get("ontology_unit_id") or props.get("ontology_unit_id") or namespace or "legacy"),
            relationship_type=rel_type,
            source_id=source,
            target_id=target,
            review_state=str(data.get("review_state") or metadata.get("review_state") or props.get("review_state") or "approved"),
            confidence=coerce_confidence(data.get("confidence") or metadata.get("confidence") or props.get("confidence")),
            provenance_refs=coerce_str_list(data.get("provenance_refs") or metadata.get("provenance_refs") or props.get("provenance_refs")),
            external_ref=coerce_external_ref(data.get("external_ref") or metadata.get("external_ref") or props.get("external_ref")),
            metadata=metadata,
            properties=props,
            validation_issues=coerce_validation_issues(data.get("validation_issues") or metadata.get("validation_issues") or props.get("validation_issues")),
            created_at=coerce_datetime(data.get("created_at") or metadata.get("created_at") or props.get("created_at")),
            updated_at=coerce_datetime(data.get("updated_at") or metadata.get("updated_at") or props.get("updated_at")),
        )

    def to_projection_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=True)
        payload["source"] = self.source_id
        payload["target"] = self.target_id
        payload["label"] = self.relationship_type
        payload["properties"] = strip_visual_fields(payload.get("properties") or {})
        return payload


def strip_visual_fields(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in coerce_mapping(value).items() if k not in _VISUAL_INSTANCE_FIELDS}


def normalize_kuzu_node_row(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return coerce_mapping(row.model_dump())
    data = coerce_mapping(row)
    if not data and hasattr(row, "__dict__"):
        data = dict(row.__dict__)
    if "n" in data and isinstance(data["n"], dict):
        data = {**data["n"], **{k: v for k, v in data.items() if k != "n"}}
    return data


def normalize_kuzu_edge_row(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return coerce_mapping(row.model_dump())
    data = coerce_mapping(row)
    if not data and hasattr(row, "__dict__"):
        data = dict(row.__dict__)
    if "r" in data and isinstance(data["r"], dict):
        data = {**data["r"], **{k: v for k, v in data.items() if k != "r"}}
    if "source" in data and not isinstance(data.get("source"), str):
        source_data = normalize_kuzu_node_row(data["source"])
        data["source"] = source_data.get("id")
    if "target" in data and not isinstance(data.get("target"), str):
        target_data = normalize_kuzu_node_row(data["target"])
        data["target"] = target_data.get("id")
    return data


def coerce_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def coerce_external_ref(value: Any) -> ExternalRef | None:
    data = coerce_mapping(value)
    if not data:
        return None
    return ExternalRef.model_validate(data)


def coerce_validation_issues(value: Any) -> list[InstanceValidationIssue]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    issues: list[InstanceValidationIssue] = []
    for item in raw:
        if isinstance(item, str):
            issues.append(InstanceValidationIssue(message=item))
        elif isinstance(item, dict):
            issues.append(InstanceValidationIssue.model_validate(item))
    return issues


def coerce_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
            else:
                value = [value]
        except Exception:
            value = [value]
    if not isinstance(value, list):
        value = [value]
    return _dedupe_strings(str(item) for item in value if str(item or "").strip())


def _dedupe_strings(value: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def optional_str(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def coerce_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return utcnow()

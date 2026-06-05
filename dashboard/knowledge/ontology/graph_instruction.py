"""Typed Graph Instruction schema for ontology-driven map rendering.

Graph Instruction captures display semantics that profiles and domain packs own:
lane defaults, style hints, relationship direction, validation surfaces, and
examples. Projections and frontend contracts consume this typed schema instead
of hardcoding relationship or layer behavior.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

LaneDimension = Literal["layer", "default_layer", "abstraction_level", "concept_type", "pack"]
MapDirection = Literal["forward", "reversed", "bidirectional", "none"]
LayoutOrientation = Literal["horizontal", "vertical"]


def _validate_identifier(value: str, field_name: str) -> str:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"{field_name} must match {_IDENTIFIER_RE.pattern}")
    return value


class StrictGraphInstructionModel(BaseModel):
    """Base class that keeps Graph Instruction payloads canonical."""

    model_config = {"extra": "forbid"}


class GraphLayoutHint(StrictGraphInstructionModel):
    """Layout metadata used by projections and UI renderers."""

    lane_dimension: LaneDimension = "default_layer"
    orientation: LayoutOrientation = "horizontal"
    group_by: list[str] = Field(default_factory=lambda: ["default_layer", "concept_type"])
    sort_by: list[str] = Field(default_factory=lambda: ["layer_order", "label"])
    density: Literal["compact", "comfortable", "spacious"] = "comfortable"
    # EPIC-015 View-plane draft controls. These fields keep visual changes
    # governed inside the profile diff/history flow instead of becoming
    # untyped frontend-only state.
    mode: str = "layered"
    color_by: str = "type"
    fallback_color: str | None = None


class GraphDefaultView(StrictGraphInstructionModel):
    """Named map view exposed by a profile or domain pack."""

    id: str
    label: str
    lane_dimension: LaneDimension = "default_layer"
    filters: dict[str, list[str]] = Field(default_factory=dict)
    excluded_filters: dict[str, list[str]] = Field(default_factory=dict)
    color_by: str | None = None
    style_property: str = ""
    selected_node_ids: list[str] = Field(default_factory=list)
    search_around: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    description: str = ""

    @field_validator("id")
    @classmethod
    def _id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "GraphDefaultView.id")


class ConceptGraphInstruction(StrictGraphInstructionModel):
    """Rendering and grouping defaults for a concept type."""

    concept_type: str
    default_layer: str | None = None
    label_template: str = "{label}"
    color: str | None = None
    shape: str | None = None
    group: str | None = None

    @field_validator("concept_type", "default_layer")
    @classmethod
    def _ids_are_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_identifier(value, "ConceptGraphInstruction identifier")

    @field_validator("color")
    @classmethod
    def _color_is_hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError("ConceptGraphInstruction.color must be a #RRGGBB hex color")
        return value


class RelationshipGraphInstruction(StrictGraphInstructionModel):
    """Rendering semantics for a canonical relationship type."""

    relationship_type: str
    map_direction: MapDirection = "forward"
    label_template: str = "{label}"
    inverse_label_template: str | None = None
    color: str | None = None
    dash: str | None = None
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    group: str | None = None

    @field_validator("relationship_type", "group")
    @classmethod
    def _id_is_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_identifier(value, "RelationshipGraphInstruction identifier")

    @field_validator("color")
    @classmethod
    def _color_is_hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError("RelationshipGraphInstruction.color must be a #RRGGBB hex color")
        return value


class GraphInstructionExample(StrictGraphInstructionModel):
    """Small fixture example proving a domain can express itself through the schema."""

    id: str
    description: str = ""
    nodes: list[dict[str, object]] = Field(default_factory=list)
    edges: list[dict[str, object]] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "GraphInstructionExample.id")


class GraphInstruction(StrictGraphInstructionModel):
    """Top-level Graph Instruction contract shared by profiles and packs."""

    schema_version: int = 1
    default_lane_dimension: LaneDimension = "default_layer"
    layout_hints: GraphLayoutHint = Field(default_factory=GraphLayoutHint)
    default_views: list[GraphDefaultView] = Field(default_factory=list)
    concept_type_defaults: dict[str, ConceptGraphInstruction] = Field(default_factory=dict)
    relationship_type_defaults: dict[str, RelationshipGraphInstruction] = Field(default_factory=dict)
    validation_rules: list[str] = Field(default_factory=list)
    examples: list[GraphInstructionExample] = Field(default_factory=list)

    @model_validator(mode="after")
    def _keys_match_nested_ids(self) -> GraphInstruction:
        for key, value in self.concept_type_defaults.items():
            _validate_identifier(key, "GraphInstruction.concept_type_defaults key")
            if key != value.concept_type:
                raise ValueError(
                    f"concept_type_defaults key {key!r} must match concept_type {value.concept_type!r}"
                )
        for key, value in self.relationship_type_defaults.items():
            _validate_identifier(key, "GraphInstruction.relationship_type_defaults key")
            if key != value.relationship_type:
                raise ValueError(
                    "relationship_type_defaults key "
                    f"{key!r} must match relationship_type {value.relationship_type!r}"
                )
        return self


def merge_graph_instruction(base: GraphInstruction, overlay: GraphInstruction | None) -> GraphInstruction:
    """Merge pack-level instructions onto a profile instruction deterministically."""

    if overlay is None:
        return base
    data = base.model_dump(mode="json")
    overlay_data = overlay.model_dump(mode="json")
    data["default_lane_dimension"] = overlay_data.get("default_lane_dimension") or data["default_lane_dimension"]
    data["layout_hints"].update(overlay_data.get("layout_hints") or {})
    data["concept_type_defaults"].update(overlay_data.get("concept_type_defaults") or {})
    data["relationship_type_defaults"].update(overlay_data.get("relationship_type_defaults") or {})

    view_by_id = {view["id"]: view for view in data.get("default_views", [])}
    for view in overlay_data.get("default_views", []):
        view_by_id[view["id"]] = view
    data["default_views"] = list(view_by_id.values())

    example_by_id = {example["id"]: example for example in data.get("examples", [])}
    for example in overlay_data.get("examples", []):
        example_by_id[example["id"]] = example
    data["examples"] = list(example_by_id.values())

    data["validation_rules"] = sorted(
        set(data.get("validation_rules", [])) | set(overlay_data.get("validation_rules", []))
    )
    return GraphInstruction.model_validate(data)

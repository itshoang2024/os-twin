"""Ontology-owned graph projections for map and builder surfaces."""

from __future__ import annotations

from collections import Counter
from typing import Any


def project_enterprise_map(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    profile: Any = None,
    group_by: list[str] | None = None,
    color_by: str | None = None,
) -> dict[str, Any]:
    """Compose serialized graph data into an ontology-ready map projection.

    The graph remains the source of node/edge facts. This projection attaches
    canonical ontology labels, stable layer definitions, and dependency-map
    direction so builder surfaces do not have to reinterpret raw relationship
    semantics independently.
    """
    layer_defs = _profile_layers(profile)
    applied_group_by = _resolve_group_by(profile, group_by)
    applied_color_by = color_by or _resolve_color_by(profile)
    projected_nodes = [_project_node(node, profile, layer_defs, applied_group_by) for node in nodes]
    node_ids = {node["id"] for node in projected_nodes}

    projected_edges = []
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target or source not in node_ids or target not in node_ids:
            continue
        projected_edges.append(_project_edge(edge, profile))

    layer_defs = _include_observed_layers(layer_defs, projected_nodes)
    layer_counts = Counter(node.get("layer_id") or "unassigned" for node in projected_nodes)
    concept_counts = Counter(node.get("concept_type") or "untyped" for node in projected_nodes)
    relation_counts = Counter(
        edge.get("relationship_type") or edge.get("label") or "relates" for edge in projected_edges
    )
    family_counts = Counter(edge.get("family") or "semantic" for edge in projected_edges)
    validation_issue_count = sum(len(node.get("validation_issues") or []) for node in projected_nodes)
    validation_issue_count += sum(len(edge.get("validation_issues") or []) for edge in projected_edges)

    layers = [
        {
            **layer,
            "count": layer_counts.get(layer["id"], 0),
        }
        for layer in sorted(layer_defs.values(), key=lambda item: (item.get("order", 999), item.get("label", "")))
    ]

    return {
        "nodes": projected_nodes,
        "edges": projected_edges,
        "layers": layers,
        "abstraction_levels": _profile_abstraction_levels(profile),
        "concept_type_counts": dict(concept_counts),
        "relationship_type_counts": dict(relation_counts),
        "relationship_family_counts": dict(family_counts),
        "stats": {
            "node_count": len(projected_nodes),
            "edge_count": len(projected_edges),
            "layer_count": len(layers),
            "concept_type_count": len(concept_counts),
            "relationship_type_count": len(relation_counts),
            "candidate_edge_count": sum(1 for edge in projected_edges if edge.get("is_candidate")),
            "validation_issue_count": validation_issue_count,
        },
        "applied_group_by": applied_group_by,
        "applied_color_by": applied_color_by,
    }


def _project_node(node: dict[str, Any], profile: Any, layer_defs: dict[str, dict[str, Any]], group_by: list[str]) -> dict[str, Any]:
    props = _as_dict(node.get("properties"))
    metadata = _as_dict(node.get("metadata"))
    instance_metadata = _as_dict(node.get("instance_metadata"))
    concept_id = _string(
        node.get("concept_type") or props.get("concept_type") or props.get("type") or node.get("label")
    )
    concept = (getattr(profile, "concept_types", {}) or {}).get(concept_id) if profile and concept_id else None
    instruction = (
        (getattr(getattr(profile, "graph_instruction", None), "concept_type_defaults", {}) or {}).get(concept_id)
        if profile and concept_id
        else None
    )
    abstraction_id = _string(node.get("abstraction_level") or getattr(concept, "abstraction_level", None))
    layer_id = _resolve_layer_id(node, metadata, props, concept_id, abstraction_id, profile, layer_defs)
    layer = layer_defs.get(layer_id) or _layer_from_observed(layer_id)
    owner = _string(metadata.get("owner") or props.get("owner") or "Unassigned")
    description = _string(
        metadata.get("purpose")
        or metadata.get("description")
        or props.get("purpose")
        or props.get("description")
        or props.get("entity_description")
        or getattr(concept, "description", "")
        or "No purpose metadata available."
    )

    projected = {
        **node,
        "concept_type": concept_id or None,
        "concept_label": _format_label(
            getattr(instruction, "label_template", None),
            getattr(concept, "label", None) or concept_id or node.get("label"),
        ),
        "concept_color": getattr(instruction, "color", None) or getattr(concept, "color", None),
        "concept_shape": getattr(instruction, "shape", None) or getattr(concept, "shape", None),
        "abstraction_level": abstraction_id or None,
        "abstraction_label": _abstraction_label(profile, abstraction_id),
        "layer_id": layer_id,
        "layer_label": layer["label"],
        "layer_order": layer["order"],
        "owner": owner,
        "description": description,
        "map_group": _map_group(
            group_by,
            node=node,
            metadata=metadata,
            props=props,
            concept_id=concept_id,
            layer_id=layer_id,
            abstraction_id=abstraction_id,
            instruction_group=getattr(instruction, "group", None),
        ),
        "data_store": _string(
            metadata.get("data_store") or props.get("data_store") or node.get("pack_id") or "knowledge_graph"
        ),
        "sync_mode": _string(metadata.get("sync_mode") or props.get("sync_mode") or "sync"),
        "lifecycle_state": _string(node.get("lifecycle_state") or instance_metadata.get("lifecycle_state") or metadata.get("lifecycle_state") or props.get("lifecycle_state") or "active"),
        "review_state": _optional_string(node.get("review_state") or instance_metadata.get("review_state") or metadata.get("review_state") or props.get("review_state")),
        "confidence": _optional_float(node.get("confidence") or instance_metadata.get("confidence") or metadata.get("confidence") or props.get("confidence")),
        "provenance_refs": _as_list(node.get("provenance_refs") or instance_metadata.get("provenance_refs") or metadata.get("provenance_refs") or props.get("provenance_refs")),
        "external_ref": _optional_dict(node.get("external_ref") or instance_metadata.get("external_ref") or metadata.get("external_ref") or props.get("external_ref")),
        "quality_state": _node_quality_state(node, metadata, props),
        "candidate_state": _optional_string(node.get("candidate_state") or metadata.get("candidate_state") or props.get("candidate_state")),
        "metadata": metadata,
        "properties": props,
        "validation_issues": _as_list(node.get("validation_issues") or metadata.get("validation_issues") or props.get("validation_issues")),
        "ontology_path": {
            "layer": layer_id,
            "abstraction_level": abstraction_id or None,
            "concept_type": concept_id or None,
            "pack_id": node.get("pack_id"),
            "lifecycle_state": node.get("lifecycle_state"),
        },
    }
    _copy_optional_fields(
        projected,
        node,
        metadata,
        props,
        (
            "event_count",
            "active_event_count",
            "time_range",
            "series_refs",
            "flow_refs",
            "state",
            "simulation_state",
            "simulation_refs",
            "state_machine_ref",
            "state_color",
            "phase",
            "track",
            "priority",
            "effort",
            "prerequisites",
            "acceptance",
        ),
    )
    return projected


def _project_edge(edge: dict[str, Any], profile: Any) -> dict[str, Any]:
    props = _as_dict(edge.get("properties"))
    metadata = _as_dict(edge.get("metadata"))
    rel_type = _string(edge.get("relationship_type") or props.get("relationship_type") or edge.get("label") or "relates")
    source = _string(edge.get("source"))
    target = _string(edge.get("target"))
    relationship = (getattr(profile, "relationship_types", {}) or {}).get(rel_type) if profile else None
    instruction = (
        (getattr(getattr(profile, "graph_instruction", None), "relationship_type_defaults", {}) or {}).get(rel_type)
        if profile
        else None
    )
    direction = _string(
        edge.get("map_direction")
        or getattr(instruction, "map_direction", None)
        or getattr(relationship, "map_direction", None)
        or "forward"
    )
    if direction == "reversed":
        map_source, map_target = target, source
    else:
        map_source, map_target = source, target
    display_label = _format_label(
        getattr(instruction, "label_template", None),
        edge.get("display_label") or getattr(relationship, "label", None) or rel_type,
    )
    inverse_label = _format_label(
        getattr(instruction, "inverse_label_template", None),
        edge.get("inverse_label") or getattr(relationship, "inverse", None) or "",
    )
    projected = {
        **edge,
        "id": _string(edge.get("id") or f"{source}:{rel_type}:{target}"),
        "relationship_type": rel_type,
        "display_label": display_label,
        "inverse_label": inverse_label or None,
        "family": _string(edge.get("family") or getattr(relationship, "family", None) or getattr(instruction, "group", None) or "semantic"),
        "style": _style_from_instruction(edge, relationship, instruction),
        "color": getattr(instruction, "color", None) or edge.get("color"),
        "weight": float(getattr(instruction, "weight", None) or edge.get("weight") or getattr(relationship, "weight", None) or 1.0),
        "map_source": map_source,
        "map_target": map_target,
        "map_direction": direction,
        "map_group": _string(getattr(instruction, "group", None) or getattr(relationship, "family", None) or "semantic"),
        "review_state": _optional_string(edge.get("review_state") or metadata.get("review_state") or props.get("review_state") or edge.get("status")),
        "confidence": _optional_float(edge.get("confidence") or metadata.get("confidence") or props.get("confidence")),
        "provenance_refs": _as_list(edge.get("provenance_refs") or metadata.get("provenance_refs") or props.get("provenance_refs")),
        "external_ref": _optional_dict(edge.get("external_ref") or metadata.get("external_ref") or props.get("external_ref")),
        "candidate_state": _optional_string(edge.get("candidate_state") or ("pending" if edge.get("is_candidate") else None)),
        "validation_issues": _as_list(edge.get("validation_issues") or metadata.get("validation_issues") or props.get("validation_issues")),
    }
    _copy_optional_fields(
        projected,
        edge,
        metadata,
        props,
        (
            "event_count",
            "active_event_count",
            "time_range",
            "series_refs",
            "flow_refs",
            "state",
            "simulation_state",
            "simulation_refs",
            "state_machine_ref",
            "state_color",
            "phase",
            "track",
            "priority",
            "effort",
            "prerequisites",
            "acceptance",
        ),
    )
    return projected


def _resolve_group_by(profile: Any, requested: list[str] | None) -> list[str]:
    if requested:
        return [str(item) for item in requested if str(item).strip()]
    hints = getattr(getattr(profile, "graph_instruction", None), "layout_hints", None)
    configured = getattr(hints, "group_by", None) if hints is not None else None
    return [str(item) for item in (configured or ["default_layer", "concept_type"])]


def _resolve_color_by(profile: Any) -> str:
    hints = getattr(getattr(profile, "graph_instruction", None), "layout_hints", None)
    return str(getattr(hints, "color_by", None) or "type")


def _map_group(
    group_by: list[str],
    *,
    node: dict[str, Any],
    metadata: dict[str, Any],
    props: dict[str, Any],
    concept_id: str,
    layer_id: str,
    abstraction_id: str,
    instruction_group: Any,
) -> str:
    values: list[str] = []
    for key in group_by:
        if key in {"default_layer", "layer", "layer_id"}:
            value = layer_id
        elif key == "concept_type":
            value = concept_id
        elif key == "abstraction_level":
            value = abstraction_id
        elif key == "pack":
            value = node.get("pack_id")
        elif key == "instruction_group":
            value = instruction_group
        else:
            value = node.get(key) or metadata.get(key) or props.get(key)
        text = _string(value)
        if text:
            values.append(text)
    if values:
        return " / ".join(values)
    return _string(instruction_group or node.get("pack_id") or metadata.get("group") or props.get("group") or concept_id or layer_id)


def _profile_layers(profile: Any) -> dict[str, dict[str, Any]]:
    layers = getattr(profile, "layers", {}) or {}
    result: dict[str, dict[str, Any]] = {}
    for fallback_order, (layer_id, layer) in enumerate(layers.items()):
        result[str(layer_id)] = {
            "id": str(layer_id),
            "label": getattr(layer, "label", None) or _title(layer_id),
            "order": getattr(layer, "order", fallback_order),
            "description": getattr(layer, "description", ""),
            "lifecycle_state": getattr(layer, "lifecycle_state", "active"),
        }
    return result


def _profile_abstraction_levels(profile: Any) -> list[dict[str, Any]]:
    levels = getattr(profile, "abstraction_levels", {}) or {}
    result = []
    for fallback_order, (level_id, level) in enumerate(levels.items()):
        result.append(
            {
                "id": str(level_id),
                "label": getattr(level, "label", None) or _title(level_id),
                "order": getattr(level, "order", fallback_order),
                "description": getattr(level, "description", ""),
            }
        )
    return sorted(result, key=lambda item: (item.get("order", 999), item.get("label", "")))


def _include_observed_layers(
    layer_defs: dict[str, dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result = dict(layer_defs)
    next_order = max([layer.get("order", 0) for layer in result.values()] or [-1]) + 1
    for node in nodes:
        layer_id = _string(node.get("layer_id") or "unassigned")
        if layer_id in result:
            continue
        result[layer_id] = {
            "id": layer_id,
            "label": _string(node.get("layer_label") or _title(layer_id)),
            "order": next_order,
            "description": "",
            "lifecycle_state": "active",
        }
        next_order += 1
    return result


def _resolve_layer_id(
    node: dict[str, Any],
    metadata: dict[str, Any],
    props: dict[str, Any],
    concept_id: str,
    abstraction_id: str,
    profile: Any,
    layer_defs: dict[str, dict[str, Any]],
) -> str:
    raw_layer = _string(node.get("layer") or metadata.get("layer") or props.get("layer"))
    if raw_layer:
        return _match_layer_id(raw_layer, layer_defs)

    if profile is not None and layer_defs:
        concept = (getattr(profile, "concept_types", {}) or {}).get(concept_id)
        instruction = (
            (getattr(getattr(profile, "graph_instruction", None), "concept_type_defaults", {}) or {}).get(concept_id)
            if concept_id
            else None
        )
        declared_layer = _string(
            getattr(instruction, "default_layer", None) or getattr(concept, "default_layer", None)
        )
        if declared_layer:
            return _match_layer_id(declared_layer, layer_defs)
        return _first_layer(layer_defs)

    # Legacy namespaces without profiles still render safely, but the fallback is
    # intentionally generic: domain-specific layer rules must come from Graph
    # Instruction/profile defaults rather than frontend or projection constants.
    return _first_layer(layer_defs) if layer_defs else "unassigned"


def _match_layer_id(raw_layer: str, layer_defs: dict[str, dict[str, Any]]) -> str:
    normalized = raw_layer.strip().lower()
    for layer_id, layer in layer_defs.items():
        if normalized in {layer_id.lower(), str(layer.get("label", "")).lower()}:
            return layer_id
    return _safe_id(raw_layer)


def _first_existing(layer_defs: dict[str, dict[str, Any]], ids: list[str]) -> str | None:
    for layer_id in ids:
        if layer_id in layer_defs:
            return layer_id
    return None


def _first_layer(layer_defs: dict[str, dict[str, Any]]) -> str:
    return min(layer_defs.values(), key=lambda item: (item.get("order", 999), item.get("label", "")))["id"]


def _layer_from_observed(layer_id: str) -> dict[str, Any]:
    return {
        "id": layer_id,
        "label": _title(layer_id),
        "order": 999,
        "description": "",
        "lifecycle_state": "active",
    }


def _abstraction_label(profile: Any, abstraction_id: str) -> str | None:
    if not abstraction_id:
        return None
    level = (getattr(profile, "abstraction_levels", {}) or {}).get(abstraction_id) if profile else None
    return getattr(level, "label", None) or _title(abstraction_id)


def _format_label(template: Any, fallback: Any) -> str:
    label = _string(fallback) or "relates"
    template_text = _string(template)
    if not template_text:
        return _title(label)
    try:
        return template_text.format(label=_title(label), raw_label=label)
    except (KeyError, IndexError, ValueError):
        return _title(label)


def _style_from_instruction(edge: dict[str, Any], relationship: Any, instruction: Any) -> str:
    dash = _string(getattr(instruction, "dash", None))
    if dash:
        return "dotted" if dash.startswith("2") else "dashed"
    explicit = _string(edge.get("style"))
    if explicit:
        return explicit
    relationship_style = _string(getattr(relationship, "style", None) or getattr(relationship, "display_style", None))
    if relationship_style:
        return relationship_style
    return "solid"


def _node_quality_state(node: dict[str, Any], metadata: dict[str, Any], props: dict[str, Any]) -> str:
    explicit = _optional_string(node.get("quality_state") or metadata.get("quality_state") or props.get("quality_state"))
    if explicit:
        return explicit
    if _as_list(node.get("validation_issues") or metadata.get("validation_issues") or props.get("validation_issues")):
        return "needs_review"
    lifecycle = _string(node.get("lifecycle_state") or metadata.get("lifecycle_state") or props.get("lifecycle_state"))
    if lifecycle in {"draft", "deprecated", "retired"}:
        return lifecycle
    return "healthy"


def _copy_optional_fields(
    projected: dict[str, Any],
    primary: dict[str, Any],
    metadata: dict[str, Any],
    props: dict[str, Any],
    field_names: tuple[str, ...],
) -> None:
    for field_name in field_names:
        for source in (primary, metadata, props):
            if field_name in source and source[field_name] is not None:
                projected[field_name] = source[field_name]
                break


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_dict(value: Any) -> dict[str, Any] | None:
    data = _as_dict(value)
    return data or None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: str) -> str:
    safe = "_".join(_string(value).lower().replace("-", "_").split())
    return safe or "unassigned"


def _title(value: Any) -> str:
    return _string(value).replace("_", " ").replace("-", " ").title() or "Unassigned"

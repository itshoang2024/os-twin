"""Ontology-owned graph projections for map and builder surfaces."""

from __future__ import annotations

from collections import Counter
from typing import Any


def project_enterprise_map(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    profile: Any = None,
) -> dict[str, Any]:
    """Compose serialized graph data into an ontology-ready map projection.

    The graph remains the source of node/edge facts. This projection attaches
    canonical ontology labels, stable layer definitions, and dependency-map
    direction so builder surfaces do not have to reinterpret raw relationship
    semantics independently.
    """
    layer_defs = _profile_layers(profile)
    projected_nodes = [_project_node(node, profile, layer_defs) for node in nodes]
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
    }


def _project_node(node: dict[str, Any], profile: Any, layer_defs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    props = _as_dict(node.get("properties"))
    metadata = _as_dict(node.get("metadata"))
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

    return {
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
        "map_group": _string(
            getattr(instruction, "group", None)
            or node.get("pack_id")
            or metadata.get("group")
            or props.get("group")
            or concept_id
            or layer_id
        ),
        "data_store": _string(
            metadata.get("data_store") or props.get("data_store") or node.get("pack_id") or "knowledge_graph"
        ),
        "sync_mode": _string(metadata.get("sync_mode") or props.get("sync_mode") or "sync"),
        "ontology_path": {
            "layer": layer_id,
            "abstraction_level": abstraction_id or None,
            "concept_type": concept_id or None,
            "pack_id": node.get("pack_id"),
            "lifecycle_state": node.get("lifecycle_state"),
        },
    }


def _project_edge(edge: dict[str, Any], profile: Any) -> dict[str, Any]:
    rel_type = _string(edge.get("relationship_type") or edge.get("label") or "relates")
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
    return {
        **edge,
        "relationship_type": rel_type,
        "display_label": display_label,
        "inverse_label": inverse_label or None,
        "family": _string(edge.get("family") or getattr(relationship, "family", None) or getattr(instruction, "group", None) or "semantic"),
        "style": _style_from_instruction(edge, relationship, instruction),
        "color": edge.get("color") or getattr(instruction, "color", None),
        "weight": float(edge.get("weight") or getattr(instruction, "weight", None) or getattr(relationship, "weight", None) or 1.0),
        "map_source": map_source,
        "map_target": map_target,
        "map_direction": direction,
        "map_group": _string(getattr(instruction, "group", None) or getattr(relationship, "family", None) or "semantic"),
    }


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
    explicit = _string(edge.get("style") or getattr(relationship, "style", None) or getattr(relationship, "display_style", None))
    if explicit:
        return explicit
    dash = _string(getattr(instruction, "dash", None))
    if dash:
        return "dotted" if dash.startswith("2") else "dashed"
    return "solid"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: str) -> str:
    safe = "_".join(_string(value).lower().replace("-", "_").split())
    return safe or "unassigned"


def _title(value: Any) -> str:
    return _string(value).replace("_", " ").replace("-", " ").title() or "Unassigned"

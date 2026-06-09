"""Ontology governance audit, history, diff, and migration safety helpers."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from dashboard.knowledge.audit import audit_event
from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError
from dashboard.knowledge.ontology.models import OntologyProfile

OntologyAuditOperation = Literal[
    "profile_save",
    "profile_reset",
    "candidate_approve",
    "candidate_map",
    "candidate_reject",
    "pack_install",
    "pack_uninstall",
]


class OntologyDiff(BaseModel):
    """Structured diff between two ontology profile versions."""

    added: dict[str, list[str]] = Field(default_factory=dict)
    removed: dict[str, list[str]] = Field(default_factory=dict)
    changed: dict[str, list[str]] = Field(default_factory=dict)
    changed_paths: list[str] = Field(default_factory=list)


class MigrationIssue(BaseModel):
    """Safety issue detected when a profile enum change may affect graph data."""

    severity: Literal["warning", "error"] = "warning"
    code: str
    path: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileHistoryRecord(BaseModel):
    """Append-only profile version history entry."""

    id: str
    namespace: str
    actor: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str
    previous_version: str | None = None
    new_version: str
    changed_paths: list[str] = Field(default_factory=list)
    diff: OntologyDiff = Field(default_factory=OntologyDiff)
    migration_issues: list[MigrationIssue] = Field(default_factory=list)
    validation_override: dict[str, Any] | None = None
    migration_entries: list[dict[str, Any]] = Field(default_factory=list)
    profile: dict[str, Any]


def diff_profiles(previous: OntologyProfile | None, current: OntologyProfile) -> OntologyDiff:
    """Return added/removed/changed top-level ontology definition ids and paths."""

    if previous is None:
        added = {
            "concept_types": sorted(current.concept_types),
            "relationship_types": sorted(current.relationship_types),
            "aliases": sorted(current.aliases),
            "concept_aliases": sorted(current.concept_aliases),
            "metadata_fields": sorted(current.metadata_fields),
            "layers": sorted(current.layers),
            "abstraction_levels": sorted(current.abstraction_levels),
            "validation_rules": sorted(rule.id for rule in current.validation_rules),
        }
        changed_paths = [f"{section}.{item}" for section, items in added.items() for item in items]
        changed_paths.extend(["profile_id", "namespace", "version", "status"])
        return OntologyDiff(added=added, removed={}, changed={}, changed_paths=sorted(changed_paths))

    prev_data = previous.model_dump(mode="json")
    curr_data = current.model_dump(mode="json")
    sections = [
        "concept_types",
        "relationship_types",
        "aliases",
        "concept_aliases",
        "metadata_fields",
        "layers",
        "abstraction_levels",
        "graph_instruction",
    ]
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    changed: dict[str, list[str]] = {}
    changed_paths: list[str] = []

    for section in sections:
        prev_section = prev_data.get(section) or {}
        curr_section = curr_data.get(section) or {}
        if not isinstance(prev_section, dict):
            prev_section = {}
        if not isinstance(curr_section, dict):
            curr_section = {}
        prev_keys = set(prev_section)
        curr_keys = set(curr_section)
        added[section] = sorted(curr_keys - prev_keys)
        removed[section] = sorted(prev_keys - curr_keys)
        changed_ids = sorted(key for key in (prev_keys & curr_keys) if prev_section.get(key) != curr_section.get(key))
        changed[section] = changed_ids
        changed_paths.extend(f"{section}.{key}" for key in added[section] + removed[section] + changed_ids)

    prev_rules = {rule.get("id"): rule for rule in prev_data.get("validation_rules", [])}
    curr_rules = {rule.get("id"): rule for rule in curr_data.get("validation_rules", [])}
    prev_rule_ids = {str(k) for k in prev_rules if k}
    curr_rule_ids = {str(k) for k in curr_rules if k}
    added["validation_rules"] = sorted(curr_rule_ids - prev_rule_ids)
    removed["validation_rules"] = sorted(prev_rule_ids - curr_rule_ids)
    changed["validation_rules"] = sorted(
        key for key in (prev_rule_ids & curr_rule_ids) if prev_rules.get(key) != curr_rules.get(key)
    )
    changed_paths.extend(
        f"validation_rules.{key}"
        for key in added["validation_rules"] + removed["validation_rules"] + changed["validation_rules"]
    )

    for field in ("profile_id", "namespace", "version", "status"):
        if prev_data.get(field) != curr_data.get(field):
            changed.setdefault("profile", []).append(field)
            changed_paths.append(field)

    return OntologyDiff(added=added, removed=removed, changed=changed, changed_paths=sorted(set(changed_paths)))


def _relation_usage(namespace: str, relation_id: str, graph: Any | None) -> int:
    if graph is None or not hasattr(graph, "get_all_relations"):
        return 0
    try:
        return sum(1 for relation in graph.get_all_relations() if getattr(relation, "label", None) == relation_id)
    except Exception:
        return 0


def add_rename_aliases(previous: OntologyProfile | None, current: OntologyProfile) -> tuple[OntologyProfile, list[dict[str, Any]]]:
    """Create aliases for likely canonical enum renames instead of orphaning graph labels."""

    if previous is None:
        return current, []
    data = current.model_dump(mode="json")
    entries: list[dict[str, Any]] = []

    def normalized_label(value: Any) -> str:
        return str(getattr(value, "label", "") or "").strip().lower()

    removed_rel = set(previous.relationship_types) - set(current.relationship_types)
    added_rel = set(current.relationship_types) - set(previous.relationship_types)
    for old_id in sorted(removed_rel):
        old_label = normalized_label(previous.relationship_types[old_id])
        match = next((new_id for new_id in sorted(added_rel) if normalized_label(current.relationship_types[new_id]) == old_label), None)
        if match:
            for alias, target in list(data["aliases"].items()):
                if alias == match:
                    data["aliases"].pop(alias, None)
                elif target == old_id:
                    data["aliases"][alias] = match
            if old_id not in data["relationship_types"] and old_id not in data["aliases"] and old_id != match:
                data["aliases"][old_id] = match
            for relationship in data["relationship_types"].values():
                if relationship.get("inverse") == old_id:
                    relationship["inverse"] = match
            entries.append({"kind": "relationship_rename_alias", "from": old_id, "to": match})
        else:
            for alias, target in list(data["aliases"].items()):
                if target == old_id:
                    data["aliases"].pop(alias, None)

    removed_concepts = set(previous.concept_types) - set(current.concept_types)
    added_concepts = set(current.concept_types) - set(previous.concept_types)
    for old_id in sorted(removed_concepts):
        old_label = normalized_label(previous.concept_types[old_id])
        match = next((new_id for new_id in sorted(added_concepts) if normalized_label(current.concept_types[new_id]) == old_label), None)
        if match:
            for alias, target in list(data["concept_aliases"].items()):
                if alias == match:
                    data["concept_aliases"].pop(alias, None)
                elif target == old_id:
                    data["concept_aliases"][alias] = match
            if old_id not in data["concept_types"] and old_id not in data["concept_aliases"] and old_id != match:
                data["concept_aliases"][old_id] = match
            entries.append({"kind": "concept_rename_alias", "from": old_id, "to": match})
        else:
            for alias, target in list(data["concept_aliases"].items()):
                if target == old_id:
                    data["concept_aliases"].pop(alias, None)

    return OntologyProfile.model_validate(data), entries


def validate_migration_safety(
    namespace: str,
    previous: OntologyProfile | None,
    current: OntologyProfile,
    *,
    graph: Any | None = None,
) -> list[MigrationIssue]:
    """Detect dangerous enum evolution before saving a profile."""

    if previous is None:
        return []
    issues: list[MigrationIssue] = []
    removed_relationships = set(previous.relationship_types) - set(current.relationship_types)
    for relation_id in sorted(removed_relationships):
        if relation_id in current.aliases:
            continue
        usage_count = _relation_usage(namespace, relation_id, graph)
        severity: Literal["warning", "error"] = "error" if usage_count else "warning"
        issues.append(
            MigrationIssue(
                severity=severity,
                code="RELATION_TYPE_REMOVED",
                path=f"relationship_types.{relation_id}",
                message=(
                    f"Relationship type {relation_id!r} was removed"
                    + (f" while {usage_count} graph edge(s) still use it." if usage_count else ".")
                ),
                metadata={"relation_type": relation_id, "edge_count": usage_count},
            )
        )

    for relation_id, previous_relation in previous.relationship_types.items():
        current_relation = current.relationship_types.get(relation_id)
        if current_relation and previous_relation.lifecycle_state != "deprecated" and current_relation.lifecycle_state == "deprecated":
            usage_count = _relation_usage(namespace, relation_id, graph)
            if usage_count:
                issues.append(
                    MigrationIssue(
                        severity="warning",
                        code="RELATION_TYPE_DEPRECATED_IN_USE",
                        path=f"relationship_types.{relation_id}.lifecycle_state",
                        message=f"Relationship type {relation_id!r} is deprecated while {usage_count} graph edge(s) still use it.",
                        metadata={"relation_type": relation_id, "edge_count": usage_count},
                    )
                )
    return issues


class OntologyAuditStore:
    """Namespace-local append-only profile history and audit store."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def ontology_dir(self, namespace: str) -> Path:
        return self._nm.namespace_dir(namespace) / "ontology"

    def history_path(self, namespace: str) -> Path:
        return self.ontology_dir(namespace) / "profile_history.json"

    def _require_namespace(self, namespace: str) -> None:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)

    def list_history(self, namespace: str) -> list[ProfileHistoryRecord]:
        self._require_namespace(namespace)
        path = self.history_path(namespace)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        records = [ProfileHistoryRecord.model_validate(item) for item in (data if isinstance(data, list) else [])]
        return sorted(records, key=lambda r: r.timestamp, reverse=True)

    def get_history(self, namespace: str, version_or_id: str) -> ProfileHistoryRecord:
        for record in self.list_history(namespace):
            if record.new_version == version_or_id or record.id == version_or_id:
                return record
        raise KeyError(f"Profile history record not found: {version_or_id}")

    def append_profile_record(
        self,
        namespace: str,
        *,
        actor: str,
        reason: str,
        previous: OntologyProfile | None,
        current: OntologyProfile,
        diff: OntologyDiff,
        migration_issues: list[MigrationIssue] | None = None,
        validation_override: dict[str, Any] | None = None,
        migration_entries: list[dict[str, Any]] | None = None,
        op: OntologyAuditOperation = "profile_save",
    ) -> ProfileHistoryRecord:
        self._require_namespace(namespace)
        timestamp = datetime.now(UTC)
        record = ProfileHistoryRecord(
            id=f"{current.version}-{int(timestamp.timestamp() * 1000)}",
            namespace=namespace,
            actor=actor or "anonymous",
            timestamp=timestamp,
            reason=reason or "No reason supplied",
            previous_version=previous.version if previous else None,
            new_version=current.version,
            changed_paths=diff.changed_paths,
            diff=diff,
            migration_issues=migration_issues or [],
            validation_override=validation_override,
            migration_entries=migration_entries or [],
            profile=current.model_dump(mode="json"),
        )
        with self._lock:
            records = self.list_history(namespace)
            records.append(record)
            self._write(namespace, records)
        audit_event(
            actor=record.actor,
            namespace=namespace,
            op=op,
            args={
                "reason": record.reason,
                "previous_version": record.previous_version,
                "new_version": record.new_version,
                "changed_paths": record.changed_paths,
                "migration_issues": [issue.model_dump(mode="json") for issue in record.migration_issues],
                "validation_override": validation_override,
                "migration_entries": record.migration_entries,
            },
            result_status="success",
            latency_ms=0.0,
        )
        return record

    def audit_operation(
        self,
        namespace: str,
        *,
        actor: str,
        op: OntologyAuditOperation,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._require_namespace(namespace)
        audit_event(
            actor=actor or "anonymous",
            namespace=namespace,
            op=op,
            args={"reason": reason, **(metadata or {})},
            result_status="success",
            latency_ms=0.0,
        )

    def _write(self, namespace: str, records: list[ProfileHistoryRecord]) -> None:
        target = self.history_path(namespace)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".profile_history.", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump([r.model_dump(mode="json") for r in records], fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

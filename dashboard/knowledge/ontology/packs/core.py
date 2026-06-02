"""Domain pack manifest schema, validation, merge, and lifecycle state.

Domain packs are versioned, installable ontology extensions. They are stored
separately from the active profile so install/upgrade/uninstall can be previewed
and rolled back without silently corrupting namespace graph semantics.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError
from dashboard.knowledge.ontology.graph_instruction import GraphInstruction, merge_graph_instruction
from dashboard.knowledge.ontology.models import (
    AbstractionLevel,
    ConceptType,
    Layer,
    MetadataField,
    OntologyProfile,
    RelationshipType,
    ValidationRule,
    _validate_identifier,
)
from dashboard.knowledge.ontology.store import OntologyProfileStore
from dashboard.knowledge.ontology.validator import ValidationIssue, validate_profile

PackLifecycleState = Literal["installed", "disabled"]
ENTERPRISE_EXTENSION_RELATIONSHIP_TYPES = {"evidences", "mitigates", "syncs_with"}


class DomainPackManifest(BaseModel):
    """Typed manifest for a vertical ontology extension pack."""

    model_config = {"extra": "forbid"}

    pack_id: str
    name: str
    version: str
    compatible_profile_versions: list[str] = Field(default_factory=list)
    concept_types: dict[str, ConceptType] = Field(default_factory=dict)
    layers: dict[str, Layer] = Field(default_factory=dict)
    abstraction_levels: dict[str, AbstractionLevel] = Field(default_factory=dict)
    relationship_types: dict[str, RelationshipType] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    metadata_fields: dict[str, MetadataField] = Field(default_factory=dict)
    validation_rules: list[ValidationRule] = Field(default_factory=list)
    graph_instruction: GraphInstruction = Field(default_factory=GraphInstruction)
    fixtures: list[dict[str, Any]] = Field(default_factory=list)
    migration_notes: list[str] = Field(default_factory=list)

    @field_validator("pack_id")
    @classmethod
    def _pack_id_is_identifier(cls, value: str) -> str:
        return _validate_identifier(value, "DomainPackManifest.pack_id")

    @field_validator("version")
    @classmethod
    def _version_has_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DomainPackManifest.version is required")
        return value

    @model_validator(mode="after")
    def _validate_manifest_references(self) -> DomainPackManifest:
        for key, concept in self.concept_types.items():
            if key != concept.id:
                raise ValueError(f"concept_types key {key!r} must match ConceptType.id {concept.id!r}")
        for key, relationship in self.relationship_types.items():
            if key != relationship.id:
                raise ValueError(
                    f"relationship_types key {key!r} must match RelationshipType.id {relationship.id!r}"
                )
        for key, layer in self.layers.items():
            if key != layer.id:
                raise ValueError(f"layers key {key!r} must match Layer.id {layer.id!r}")
        for key, level in self.abstraction_levels.items():
            if key != level.id:
                raise ValueError(f"abstraction_levels key {key!r} must match AbstractionLevel.id {level.id!r}")
        for key, field_def in self.metadata_fields.items():
            if key != field_def.id:
                raise ValueError(f"metadata_fields key {key!r} must match MetadataField.id {field_def.id!r}")
        pack_relationship_ids = set(self.relationship_types)
        for alias, target in self.aliases.items():
            _validate_identifier(alias, "DomainPackManifest.aliases key")
            if alias in pack_relationship_ids:
                raise ValueError(f"pack alias {alias!r} cannot shadow a pack relationship id")
            _validate_identifier(target, "DomainPackManifest.aliases value")
        return self


class InstalledDomainPack(BaseModel):
    """Persisted record of a pack installed into a namespace."""

    model_config = {"extra": "forbid"}

    pack_id: str
    name: str
    version: str
    status: PackLifecycleState = "installed"
    installed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    disabled_at: datetime | None = None
    additions: dict[str, list[str]] = Field(default_factory=dict)


class DomainPackInstallState(BaseModel):
    """Namespace-local pack lifecycle state stored under ontology/packs_state.json."""

    model_config = {"extra": "forbid"}

    schema_version: int = 1
    namespace: str
    installed_packs: dict[str, InstalledDomainPack] = Field(default_factory=dict)


@dataclass(frozen=True)
class PackValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    profile: OntologyProfile | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.model_dump() for issue in self.issues],
            "profile": self.profile.model_dump(mode="json") if self.profile is not None else None,
        }


@dataclass(frozen=True)
class DomainPackOperationResult:
    namespace: str
    pack_id: str
    action: str
    installed: bool
    profile: OntologyProfile
    state: DomainPackInstallState
    issues: list[ValidationIssue] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "pack_id": self.pack_id,
            "action": self.action,
            "installed": self.installed,
            "profile": self.profile.model_dump(mode="json"),
            "state": self.state.model_dump(mode="json"),
            "issues": [issue.model_dump() for issue in self.issues],
        }


class DomainPackConflictError(ValueError):
    """Raised when a pack cannot be safely installed or upgraded."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        message = "; ".join(f"{issue.code}: {issue.message}" for issue in issues) or "Domain pack conflict"
        super().__init__(message)


def _issue(
    code: str,
    path: str,
    message: str,
    suggested_fix: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        path=path,
        message=message,
        suggested_fix=suggested_fix,
        subject="pack",
        metadata=metadata or {},
    )


def _matches_version(profile_version: str, compatible: list[str]) -> bool:
    if not compatible:
        return True
    for pattern in compatible:
        if pattern in {"*", profile_version}:
            return True
        if pattern.endswith(".x") and profile_version.startswith(pattern[:-1]):
            return True
        if pattern.endswith(".*") and profile_version.startswith(pattern[:-1]):
            return True
    return False


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _same_definition(left: Any, right: Any) -> bool:
    return _dump(left) == _dump(right)


def validate_domain_pack(manifest: DomainPackManifest, profile: OntologyProfile) -> PackValidationResult:
    """Return compatibility/conflict issues and merged preview for ``manifest``."""

    issues: list[ValidationIssue] = []
    if not _matches_version(profile.version, manifest.compatible_profile_versions):
        issues.append(
            _issue(
                "INCOMPATIBLE_PROFILE_VERSION",
                "compatible_profile_versions",
                f"Pack {manifest.pack_id!r} is not compatible with profile version {profile.version!r}.",
                "Install a compatible pack version or migrate the ontology profile first.",
                metadata={"profile_version": profile.version, "compatible": manifest.compatible_profile_versions},
            )
        )

    for layer_id, layer in manifest.layers.items():
        existing = profile.layers.get(layer_id)
        if existing is not None and not _same_definition(existing, layer):
            issues.append(
                _issue(
                    "LAYER_CONFLICT",
                    f"layers.{layer_id}",
                    f"Pack layer {layer_id!r} conflicts with the active profile definition.",
                    "Rename the pack layer or align its definition with the active profile.",
                )
            )

    for level_id, level in manifest.abstraction_levels.items():
        existing = profile.abstraction_levels.get(level_id)
        if existing is not None and not _same_definition(existing, level):
            issues.append(
                _issue(
                    "ABSTRACTION_LEVEL_CONFLICT",
                    f"abstraction_levels.{level_id}",
                    f"Pack abstraction level {level_id!r} conflicts with the active profile definition.",
                    "Rename the pack abstraction level or align its definition with the active profile.",
                )
            )

    for concept_id, concept in manifest.concept_types.items():
        existing = profile.concept_types.get(concept_id)
        if existing is not None and not _same_definition(existing, concept):
            issues.append(
                _issue(
                    "CONCEPT_TYPE_CONFLICT",
                    f"concept_types.{concept_id}",
                    f"Pack concept type {concept_id!r} conflicts with the active profile definition.",
                    "Rename the pack concept or align its definition with the active profile before install.",
                )
            )

    for relationship_id, relationship in manifest.relationship_types.items():
        existing = profile.relationship_types.get(relationship_id)
        if existing is not None and not _same_definition(existing, relationship):
            if relationship_id in ENTERPRISE_EXTENSION_RELATIONSHIP_TYPES and not existing.is_system:
                # Default enterprise-map relationships are intentionally generic placeholders.
                # Domain packs may refine their labels, endpoint constraints, and Graph Instruction styling.
                continue
            code = "CORE_RELATIONSHIP_CONFLICT" if existing.is_system else "RELATIONSHIP_TYPE_CONFLICT"
            issues.append(
                _issue(
                    code,
                    f"relationship_types.{relationship_id}",
                    f"Pack relationship type {relationship_id!r} conflicts with the active profile definition.",
                    (
                        "Domain packs cannot mutate existing/core relationship types; "
                        "use aliases or a new relationship id."
                    ),
                    metadata={"is_system": existing.is_system},
                )
            )

    relationship_ids = set(profile.relationship_types) | set(manifest.relationship_types)
    for alias, target in manifest.aliases.items():
        if alias in relationship_ids:
            issues.append(
                _issue(
                    "ALIAS_SHADOWS_RELATIONSHIP",
                    f"aliases.{alias}",
                    f"Pack alias {alias!r} shadows a canonical relationship type.",
                    "Choose an alias that does not match any canonical relationship id.",
                )
            )
        existing_target = profile.aliases.get(alias)
        if existing_target is not None and existing_target != target:
            issues.append(
                _issue(
                    "ALIAS_CONFLICT",
                    f"aliases.{alias}",
                    f"Pack alias {alias!r} targets {target!r} but the profile already maps it to {existing_target!r}.",
                    "Rename the alias or make both packs target the same canonical relationship.",
                    metadata={"existing_target": existing_target, "pack_target": target},
                )
            )
        if target not in relationship_ids:
            issues.append(
                _issue(
                    "ALIAS_TARGET_MISSING",
                    f"aliases.{alias}",
                    f"Pack alias {alias!r} targets unknown relationship {target!r}.",
                    "Add the target relationship type to the pack or active profile.",
                )
            )

    for field_id, field_def in manifest.metadata_fields.items():
        existing = profile.metadata_fields.get(field_id)
        if existing is not None and not _same_definition(existing, field_def):
            issues.append(
                _issue(
                    "METADATA_FIELD_CONFLICT",
                    f"metadata_fields.{field_id}",
                    f"Pack metadata field {field_id!r} conflicts with the active profile definition.",
                    "Rename the field or align its type/options with the active profile.",
                )
            )

    existing_rules = {rule.id: rule for rule in profile.validation_rules}
    for rule in manifest.validation_rules:
        existing = existing_rules.get(rule.id)
        if existing is not None and not _same_definition(existing, rule):
            issues.append(
                _issue(
                    "VALIDATION_RULE_CONFLICT",
                    f"validation_rules.{rule.id}",
                    f"Pack validation rule {rule.id!r} conflicts with the active profile definition.",
                    "Rename the rule or align its definition with the active profile.",
                )
            )

    if issues:
        return PackValidationResult(valid=False, issues=issues, profile=None)

    try:
        merged = merge_domain_pack(profile, manifest)
    except ValueError as exc:
        return PackValidationResult(
            valid=False,
            issues=[
                _issue(
                    "MERGED_PROFILE_INVALID",
                    "profile",
                    str(exc),
                    "Fix pack references so the merged profile validates.",
                )
            ],
            profile=None,
        )
    profile_issues = validate_profile(merged)
    return PackValidationResult(
        valid=not any(issue.severity == "error" for issue in profile_issues),
        issues=profile_issues,
        profile=merged,
    )


def merge_domain_pack(profile: OntologyProfile, manifest: DomainPackManifest) -> OntologyProfile:
    """Return a validated profile with pack additions merged in."""

    data = profile.model_dump(mode="json")
    data["layers"].update({key: layer.model_dump(mode="json") for key, layer in manifest.layers.items()})
    data["abstraction_levels"].update(
        {key: level.model_dump(mode="json") for key, level in manifest.abstraction_levels.items()}
    )
    data["metadata_fields"].update(
        {key: field_def.model_dump(mode="json") for key, field_def in manifest.metadata_fields.items()}
    )
    data["concept_types"].update(
        {key: concept.model_dump(mode="json") for key, concept in manifest.concept_types.items()}
    )
    data["relationship_types"].update(
        {key: relationship.model_dump(mode="json") for key, relationship in manifest.relationship_types.items()}
    )
    data["aliases"].update(manifest.aliases)
    rule_by_id = {rule["id"]: rule for rule in data["validation_rules"]}
    for rule in manifest.validation_rules:
        rule_by_id[rule.id] = rule.model_dump(mode="json")
    data["validation_rules"] = list(rule_by_id.values())
    data["graph_instruction"] = merge_graph_instruction(
        profile.graph_instruction, manifest.graph_instruction
    ).model_dump(mode="json")
    return OntologyProfile.model_validate(data)


def _manifest_additions(manifest: DomainPackManifest) -> dict[str, list[str]]:
    return {
        "concept_types": sorted(manifest.concept_types),
        "relationship_types": sorted(manifest.relationship_types),
        "aliases": sorted(manifest.aliases),
        "metadata_fields": sorted(manifest.metadata_fields),
        "layers": sorted(manifest.layers),
        "abstraction_levels": sorted(manifest.abstraction_levels),
        "validation_rules": sorted(rule.id for rule in manifest.validation_rules),
        "graph_instruction": sorted(
            set(manifest.graph_instruction.concept_type_defaults)
            | set(manifest.graph_instruction.relationship_type_defaults)
        ),
        "fixtures": [str(item.get("id", idx)) for idx, item in enumerate(manifest.fixtures)],
    }


class DomainPackStore:
    """Load built-in pack manifests and persist namespace pack install state."""

    def __init__(self, namespace_manager: NamespaceManager, profile_store: OntologyProfileStore) -> None:
        self._nm = namespace_manager
        self._profile_store = profile_store
        self._defaults_dir = Path(__file__).parent / "defaults"

    def state_path(self, namespace: str) -> Path:
        return self._profile_store.ontology_dir(namespace) / "packs_state.json"

    def load_manifest(self, pack_id: str) -> DomainPackManifest:
        path = self._defaults_dir / f"{pack_id}.json"
        if not path.exists():
            raise ValueError(f"Unknown domain pack {pack_id!r}")
        with path.open("r", encoding="utf-8") as fh:
            return DomainPackManifest.model_validate(json.load(fh))

    def list_available(self) -> list[DomainPackManifest]:
        manifests: list[DomainPackManifest] = []
        for path in sorted(self._defaults_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                manifests.append(DomainPackManifest.model_validate(json.load(fh)))
        return manifests

    def get_state(self, namespace: str) -> DomainPackInstallState:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)
        path = self.state_path(namespace)
        if not path.exists():
            return DomainPackInstallState(namespace=namespace)
        with path.open("r", encoding="utf-8") as fh:
            return DomainPackInstallState.model_validate(json.load(fh))

    def write_state(self, state: DomainPackInstallState) -> DomainPackInstallState:
        if self._nm.get(state.namespace) is None:
            raise NamespaceNotFoundError(state.namespace)
        target = self.state_path(state.namespace)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".packs_state.", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state.model_dump(mode="json"), fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return state

    def validate(self, manifest: DomainPackManifest, profile: OntologyProfile) -> PackValidationResult:
        return validate_domain_pack(manifest, profile)

    def install(
        self, namespace: str, manifest: DomainPackManifest, profile: OntologyProfile
    ) -> DomainPackOperationResult:
        state = self.get_state(namespace)
        previous_state = state.model_copy(deep=True)
        previous_profile = profile.model_copy(deep=True)
        validation = validate_domain_pack(manifest, profile)
        if not validation.valid or validation.profile is None:
            raise DomainPackConflictError(validation.issues)
        state.installed_packs[manifest.pack_id] = InstalledDomainPack(
            pack_id=manifest.pack_id,
            name=manifest.name,
            version=manifest.version,
            status="installed",
            additions=_manifest_additions(manifest),
        )
        try:
            self._profile_store.write(validation.profile, set_active=True)
            self.write_state(state)
        except Exception:
            self._profile_store.write(previous_profile, set_active=True)
            self.write_state(previous_state)
            raise
        return DomainPackOperationResult(
            namespace, manifest.pack_id, "install", True, validation.profile, state, validation.issues
        )

    def uninstall(self, namespace: str, pack_id: str, profile: OntologyProfile) -> DomainPackOperationResult:
        state = self.get_state(namespace)
        previous_state = state.model_copy(deep=True)
        previous_profile = profile.model_copy(deep=True)
        installed = state.installed_packs.get(pack_id)
        if installed is None or installed.status != "installed":
            raise ValueError(f"Domain pack {pack_id!r} is not installed in namespace {namespace!r}")
        manifest = self.load_manifest(pack_id)
        remaining_manifests = [
            self.load_manifest(pid)
            for pid, rec in state.installed_packs.items()
            if pid != pack_id and rec.status == "installed"
        ]
        next_profile = uninstall_domain_pack(profile, manifest, remaining_manifests)
        installed.status = "disabled"
        installed.disabled_at = datetime.now(UTC)
        try:
            self._profile_store.write(next_profile, set_active=True)
            self.write_state(state)
        except Exception:
            self._profile_store.write(previous_profile, set_active=True)
            self.write_state(previous_state)
            raise
        return DomainPackOperationResult(namespace, pack_id, "uninstall", False, next_profile, state, [])


def uninstall_domain_pack(
    profile: OntologyProfile,
    manifest: DomainPackManifest,
    remaining_manifests: list[DomainPackManifest],
) -> OntologyProfile:
    """Return profile with pack-owned additions disabled unless needed by remaining packs."""

    data = profile.model_dump(mode="json")
    keep_concepts = (
        set().union(*(set(pack.concept_types) for pack in remaining_manifests)) if remaining_manifests else set()
    )
    keep_relationships = (
        set().union(*(set(pack.relationship_types) for pack in remaining_manifests))
        if remaining_manifests
        else set()
    )
    keep_layers = (
        set().union(*(set(pack.layers) for pack in remaining_manifests)) if remaining_manifests else set()
    )
    keep_abstraction_levels = (
        set().union(*(set(pack.abstraction_levels) for pack in remaining_manifests))
        if remaining_manifests
        else set()
    )
    keep_metadata = (
        set().union(*(set(pack.metadata_fields) for pack in remaining_manifests)) if remaining_manifests else set()
    )
    keep_aliases = set().union(*(set(pack.aliases) for pack in remaining_manifests)) if remaining_manifests else set()
    keep_rules = (
        set().union(*(set(rule.id for rule in pack.validation_rules) for pack in remaining_manifests))
        if remaining_manifests
        else set()
    )

    for pack in remaining_manifests:
        for relationship in pack.relationship_types.values():
            keep_concepts.update(relationship.allowed_source_types)
            keep_concepts.update(relationship.allowed_target_types)
            if relationship.inverse:
                keep_relationships.add(relationship.inverse)
        keep_relationships.update(pack.aliases.values())
        for concept in pack.concept_types.values():
            keep_metadata.update(concept.metadata_schema)
            if concept.default_layer:
                keep_layers.add(concept.default_layer)
            keep_abstraction_levels.add(concept.abstraction_level)

    for alias in manifest.aliases:
        if alias not in keep_aliases:
            data["aliases"].pop(alias, None)
    for rule in manifest.validation_rules:
        if rule.id not in keep_rules:
            data["validation_rules"] = [item for item in data["validation_rules"] if item.get("id") != rule.id]
    for relationship_id in manifest.relationship_types:
        if relationship_id not in keep_relationships:
            data["relationship_types"].pop(relationship_id, None)
    for concept_id in manifest.concept_types:
        if concept_id not in keep_concepts:
            data["concept_types"].pop(concept_id, None)
    for layer_id in manifest.layers:
        if layer_id not in keep_layers:
            data["layers"].pop(layer_id, None)
    for level_id in manifest.abstraction_levels:
        if level_id not in keep_abstraction_levels:
            data["abstraction_levels"].pop(level_id, None)
    for field_id in manifest.metadata_fields:
        if field_id not in keep_metadata:
            data["metadata_fields"].pop(field_id, None)
            for concept in data["concept_types"].values():
                concept.get("metadata_schema", {}).pop(field_id, None)
    return OntologyProfile.model_validate(data)

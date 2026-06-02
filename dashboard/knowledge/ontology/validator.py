"""Ontology relationship validation with structured issue output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from dashboard.knowledge.ontology.models import OntologyProfile, ValidationSeverity
from dashboard.knowledge.ontology.normalizer import normalize_concept_type, normalize_relation

ValidationSubject = Literal["node", "edge", "profile", "pack"]


@dataclass(frozen=True)
class ValidationIssue:
    """Structured validation issue suitable for API responses and QA assertions."""

    severity: ValidationSeverity
    code: str
    path: str
    message: str
    suggested_fix: str
    subject: ValidationSubject = "edge"
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        """Pydantic-like dump helper for callers that serialize issues."""

        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "subject": self.subject,
            "metadata": self.metadata,
        }


def _rule_severity(profile: OntologyProfile, rule_id: str, default: ValidationSeverity) -> ValidationSeverity:
    for rule in profile.validation_rules:
        if rule.id == rule_id and rule.enabled:
            return rule.severity
    return default


def validate_node(concept_type: str, profile: OntologyProfile, *, path: str = "node.type") -> list[ValidationIssue]:
    """Validate that a node concept type is known to the ontology profile."""

    normalized = normalize_concept_type(concept_type, profile)
    if normalized in profile.concept_types:
        return []
    return [
        ValidationIssue(
            severity="warning",
            code="UNKNOWN_CONCEPT_TYPE",
            path=path,
            message=f"Concept type '{concept_type}' is not defined in ontology profile '{profile.profile_id}'.",
            suggested_fix="Add the concept type to the profile or map it to an existing canonical concept type.",
            subject="node",
            metadata={"candidate": normalized},
        )
    ]


def validate_relationship(
    relation_type: str,
    source_concept_type: str,
    target_concept_type: str,
    profile: OntologyProfile,
    *,
    path: str = "edge.relation_type",
) -> list[ValidationIssue]:
    """Validate relationship semantics and source/target compatibility."""

    issues: list[ValidationIssue] = []
    normalized_relation = normalize_relation(relation_type, profile)
    source_type = normalize_concept_type(source_concept_type, profile)
    target_type = normalize_concept_type(target_concept_type, profile)

    if normalized_relation.classification == "candidate":
        issues.append(
            ValidationIssue(
                severity="warning",
                code="CANDIDATE_RELATION_TYPE",
                path=path,
                message=f"Relationship label '{relation_type}' is not canonical or aliased for this profile.",
                suggested_fix=normalized_relation.suggested_fix or "Add an alias or canonical relationship type.",
                metadata={"candidate": normalized_relation.normalized},
            )
        )
        return issues

    relationship = normalized_relation.canonical or profile.relationship_types.get(normalized_relation.normalized)
    if relationship is None:
        issues.append(
            ValidationIssue(
                severity="error",
                code="ALIAS_TARGET_MISSING",
                path=path,
                message=(
                    f"Relationship label '{relation_type}' resolves to missing canonical type "
                    f"'{normalized_relation.normalized}'."
                ),
                suggested_fix="Fix the profile alias target or add the missing canonical relationship type.",
                metadata={"normalized": normalized_relation.normalized},
            )
        )
        return issues

    if source_type not in profile.concept_types:
        issues.extend(validate_node(source_concept_type, profile, path="edge.source.type"))
    if target_type not in profile.concept_types:
        issues.extend(validate_node(target_concept_type, profile, path="edge.target.type"))

    if relationship.allowed_source_types and source_type not in relationship.allowed_source_types:
        severity = _rule_severity(profile, "relationship_endpoints_known", "error")
        issues.append(
            ValidationIssue(
                severity=severity,
                code="INVALID_RELATION_SOURCE_TYPE",
                path="edge.source.type",
                message=f"'{relationship.id}' does not allow source concept type '{source_type}'.",
                suggested_fix=f"Use one of: {', '.join(relationship.allowed_source_types)}.",
                metadata={"relation_type": relationship.id, "allowed": relationship.allowed_source_types},
            )
        )

    if relationship.allowed_target_types and target_type not in relationship.allowed_target_types:
        rule_id = f"{relationship.id}_target_artifact_like"
        default_severity: ValidationSeverity = "warning" if relationship.id == "produces" else "error"
        severity = _rule_severity(
            profile,
            rule_id,
            _rule_severity(profile, "relationship_endpoints_known", default_severity),
        )
        issues.append(
            ValidationIssue(
                severity=severity,
                code="INVALID_RELATION_TARGET_TYPE",
                path="edge.target.type",
                message=f"'{relationship.id}' does not allow target concept type '{target_type}'.",
                suggested_fix=f"Use one of: {', '.join(relationship.allowed_target_types)}.",
                metadata={"relation_type": relationship.id, "allowed": relationship.allowed_target_types},
            )
        )

    return issues


def validate_profile(profile: OntologyProfile) -> list[ValidationIssue]:
    """Return non-fatal profile validation hints not covered by strict Pydantic checks."""

    issues: list[ValidationIssue] = []
    for rel_id, relationship in profile.relationship_types.items():
        if relationship.inverse and relationship.inverse not in profile.relationship_types:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="UNKNOWN_INVERSE_RELATIONSHIP",
                    path=f"relationship_types.{rel_id}.inverse",
                    message=f"Relationship '{rel_id}' references unknown inverse '{relationship.inverse}'.",
                    suggested_fix="Add the inverse relationship type or remove the inverse reference.",
                    subject="profile",
                )
            )
    return issues


def validate_pack(edges: list[dict[str, Any]], profile: OntologyProfile) -> list[ValidationIssue]:
    """Validate a small imported/mock edge pack."""

    issues: list[ValidationIssue] = []
    for idx, edge in enumerate(edges):
        issues.extend(
            validate_relationship(
                str(edge.get("relation_type", edge.get("label", ""))),
                str(edge.get("source_type", "")),
                str(edge.get("target_type", "")),
                profile,
                path=f"edges[{idx}].relation_type",
            )
        )
    return issues

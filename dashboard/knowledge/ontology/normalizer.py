"""Relationship and concept normalization helpers for ontology profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dashboard.knowledge.ontology.models import ConceptType, OntologyProfile, RelationshipType

RelationClassification = Literal["canonical", "alias", "candidate"]
ConceptClassification = Literal["canonical", "alias", "candidate"]

# Global aliases that preserve canonical semantics across all namespace profiles.
GLOBAL_RELATION_ALIASES: dict[str, str] = {
    "prerequisite": "depends_on",
}


@dataclass(frozen=True)
class NormalizedConcept:
    """Result of normalizing a concept type label against a profile."""

    original: str
    normalized: str
    classification: ConceptClassification
    canonical: ConceptType | None = None
    source: Literal["canonical", "profile_alias", "candidate"] = "candidate"
    suggested_fix: str | None = None


@dataclass(frozen=True)
class NormalizedRelation:
    """Result of normalizing a user/mock/LLM relationship label."""

    original: str
    normalized: str
    classification: RelationClassification
    canonical: RelationshipType | None = None
    source: Literal["canonical", "profile_alias", "global_alias", "candidate"] = "candidate"
    suggested_fix: str | None = None


@dataclass(frozen=True)
class RenderedRelation:
    """Relation representation for UI rendering without requiring storage duplication."""

    source_id: str
    target_id: str
    relation_type: str
    is_inverse: bool = False
    stored_relation_type: str | None = None
    should_persist: bool = False


def _normalize_label(label: str) -> str:
    """Convert free-form relation/concept labels into ontology-safe ids."""

    return "_".join(label.strip().lower().replace("-", "_").split())


def normalize_concept(label: str, profile: OntologyProfile | None = None) -> NormalizedConcept:
    """Normalize a concept label against canonical concept ids and concept aliases."""

    candidate = _normalize_label(label)
    concept_types = profile.concept_types if profile else {}
    if candidate in concept_types:
        return NormalizedConcept(
            original=label,
            normalized=candidate,
            classification="canonical",
            canonical=concept_types[candidate],
            source="canonical",
        )

    concept_aliases = getattr(profile, "concept_aliases", {}) if profile else {}
    if candidate in concept_aliases:
        canonical_id = concept_aliases[candidate]
        return NormalizedConcept(
            original=label,
            normalized=canonical_id,
            classification="alias",
            canonical=concept_types.get(canonical_id),
            source="profile_alias",
            suggested_fix=f"Use canonical concept type '{canonical_id}'.",
        )

    return NormalizedConcept(
        original=label,
        normalized=candidate,
        classification="candidate",
        canonical=None,
        source="candidate",
        suggested_fix="Add this label as a concept type or map it to an existing concept type.",
    )


def normalize_concept_type(label: str, profile: OntologyProfile | None = None) -> str:
    """Normalize a concept label to a canonical concept id when known."""

    return normalize_concept(label, profile).normalized


def normalize_relation(label: str, profile: OntologyProfile | None = None) -> NormalizedRelation:
    """Normalize a relationship label against profile aliases and canonical ids.

    Unknown labels intentionally remain queryable as ``candidate`` relations;
    they are not silently coerced to broad fallback labels such as
    ``related_to``.
    """

    candidate = _normalize_label(label)
    relationship_types = profile.relationship_types if profile else {}

    if candidate in relationship_types:
        return NormalizedRelation(
            original=label,
            normalized=candidate,
            classification="canonical",
            canonical=relationship_types[candidate],
            source="canonical",
        )

    if profile and candidate in profile.aliases:
        canonical_id = profile.aliases[candidate]
        return NormalizedRelation(
            original=label,
            normalized=canonical_id,
            classification="alias",
            canonical=relationship_types.get(canonical_id),
            source="profile_alias",
            suggested_fix=f"Use canonical relationship type '{canonical_id}'.",
        )

    if candidate in GLOBAL_RELATION_ALIASES:
        canonical_id = GLOBAL_RELATION_ALIASES[candidate]
        return NormalizedRelation(
            original=label,
            normalized=canonical_id,
            classification="alias",
            canonical=relationship_types.get(canonical_id),
            source="global_alias",
            suggested_fix=f"Use canonical relationship type '{canonical_id}'.",
        )

    return NormalizedRelation(
        original=label,
        normalized=candidate,
        classification="candidate",
        canonical=None,
        source="candidate",
        suggested_fix="Add this label as a profile alias or canonical relationship type if it is intentional.",
    )


def render_relation_for_ui(
    source_id: str,
    target_id: str,
    relation_type: str,
    profile: OntologyProfile | None = None,
    *,
    inverse: bool = False,
    persist_inverse: bool = False,
) -> RenderedRelation:
    """Render a relation or derived inverse without duplicating stored edges by default."""

    normalized = normalize_relation(relation_type, profile)
    canonical_id = normalized.normalized
    relationship = normalized.canonical or (profile.relationship_types.get(canonical_id) if profile else None)

    if inverse and relationship and relationship.inverse:
        return RenderedRelation(
            source_id=target_id,
            target_id=source_id,
            relation_type=relationship.inverse,
            is_inverse=True,
            stored_relation_type=canonical_id,
            should_persist=persist_inverse,
        )

    return RenderedRelation(
        source_id=source_id,
        target_id=target_id,
        relation_type=canonical_id,
        is_inverse=False,
        stored_relation_type=canonical_id,
        should_persist=True,
    )

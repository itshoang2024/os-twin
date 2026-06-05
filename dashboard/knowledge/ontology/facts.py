"""Namespace-scoped Facts plane models, store, and promotion helpers.

Facts are reviewed claims. They are intentionally not canonical graph edges until
an approved fact is promoted through the same graph approve-write primitive used
for reviewed edge candidates.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError
from dashboard.knowledge.ontology.approval import GraphInstanceStore, ObservationEventStore, OntologyApprovalService, OntologyMutationError
from dashboard.knowledge.ontology.candidates import OntologyCandidate, OntologyCandidateStore, normalize_candidate_label
from dashboard.knowledge.ontology.evidence import EvidenceStore
from dashboard.knowledge.ontology.instances import OntologyEdge
from dashboard.knowledge.ontology.models import StrictOntologyModel
from dashboard.knowledge.ontology.store import OntologyProfileStore

FactReviewState = Literal["draft", "assistive", "reviewed", "approved", "rejected"]
FactSource = Literal["extraction", "assistant", "manual"]
FactSubjectKind = Literal["node", "candidate", "label"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def fact_id(namespace: str, statement: str, source_hash: str = "") -> str:
    digest = hashlib.sha256(f"{namespace}:{statement.strip()}:{source_hash}".encode("utf-8")).hexdigest()[:24]
    return f"fact:{digest}"


class FactSubjectRef(StrictOntologyModel):
    """Reference to a fact subject before or after graph confirmation."""

    kind: FactSubjectKind
    id: str
    label: str = ""
    concept_type: str | None = None

    @field_validator("id")
    @classmethod
    def _id_required(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("subject id is required")
        return str(value).strip()


class SuggestedRelationshipMapping(StrictOntologyModel):
    """Optional edge mapping proposed for a fact."""

    relationship_type: str | None = None
    source_id: str | None = None
    target_id: str | None = None
    source_kind: FactSubjectKind = "node"
    target_kind: FactSubjectKind = "node"
    direction: Literal["forward", "reversed"] = "forward"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class OntologyFact(StrictOntologyModel):
    """A cited, reviewable claim staged before canonical graph mutation."""

    id: str
    namespace: str
    statement: str
    subjects: list[FactSubjectRef] = Field(default_factory=list)
    subject_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    review_state: FactReviewState = "assistive"
    source: FactSource = "extraction"
    evidence_refs: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    suggested_mapping: SuggestedRelationshipMapping | None = None
    source_hash: str = ""
    promoted_edge_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("statement")
    @classmethod
    def _statement_required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("fact statement is required")
        if len(text) > 2000:
            raise ValueError("fact statement must be <= 2000 characters")
        return text

    @field_validator("subject_ids", "evidence_refs", "provenance_refs")
    @classmethod
    def _dedupe_strings(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in value or []:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    @model_validator(mode="after")
    def _sync_subject_ids(self) -> "OntologyFact":
        subject_ids = list(self.subject_ids)
        for subject in self.subjects:
            if subject.id not in subject_ids:
                subject_ids.append(subject.id)
        self.subject_ids = self._dedupe_strings(subject_ids)
        return self


class OntologyFactStore:
    """Atomic JSON store for facts under ``ontology/facts/facts.json``."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def facts_dir(self, namespace: str) -> Path:
        return self._nm.namespace_dir(namespace) / "ontology" / "facts"

    def facts_path(self, namespace: str) -> Path:
        return self.facts_dir(namespace) / "facts.json"

    def list(self, namespace: str, *, review_state: str | None = None, source: str | None = None) -> list[OntologyFact]:
        self._require_namespace(namespace)
        records = self._read(namespace)
        if review_state:
            records = [r for r in records if r.review_state == review_state]
        if source:
            records = [r for r in records if r.source == source]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def get(self, namespace: str, fact_id_: str) -> OntologyFact | None:
        self._require_namespace(namespace)
        return next((fact for fact in self._read(namespace) if fact.id == fact_id_), None)

    def upsert(self, namespace: str, fact: OntologyFact) -> OntologyFact:
        self._require_namespace(namespace)
        if fact.namespace != namespace:
            raise ValueError("fact namespace does not match store namespace")
        with self._lock:
            records = self._read(namespace)
            for idx, existing in enumerate(records):
                if existing.id == fact.id:
                    records[idx] = fact
                    self._write(namespace, records)
                    return fact
            records.append(fact)
            self._write(namespace, records)
            return fact

    def create_assistive(
        self,
        namespace: str,
        *,
        statement: str,
        subjects: list[FactSubjectRef] | None = None,
        confidence: float = 0.5,
        source: FactSource = "extraction",
        evidence_refs: list[str] | None = None,
        provenance_refs: list[str] | None = None,
        suggested_mapping: SuggestedRelationshipMapping | None = None,
        source_hash: str = "",
        metadata: dict[str, Any] | None = None,
        review_state: FactReviewState | None = None,
    ) -> OntologyFact:
        self._require_namespace(namespace)
        fid = fact_id(namespace, statement, source_hash)
        with self._lock:
            records = self._read(namespace)
            for idx, existing in enumerate(records):
                if existing.id == fid:
                    existing.confidence = max(existing.confidence, confidence)
                    existing.evidence_refs = OntologyFact._dedupe_strings([*existing.evidence_refs, *(evidence_refs or [])])
                    existing.provenance_refs = OntologyFact._dedupe_strings([*existing.provenance_refs, *(provenance_refs or [])])
                    existing.metadata.update(metadata or {})
                    if suggested_mapping and existing.suggested_mapping is None:
                        existing.suggested_mapping = suggested_mapping
                    records[idx] = existing
                    self._write(namespace, records)
                    return existing
            fact = OntologyFact(
                id=fid,
                namespace=namespace,
                statement=statement,
                subjects=subjects or [],
                confidence=confidence,
                review_state=review_state or ("assistive" if source in {"extraction", "assistant"} else "draft"),
                source=source,
                evidence_refs=evidence_refs or [],
                provenance_refs=provenance_refs or [],
                suggested_mapping=suggested_mapping,
                source_hash=source_hash,
                metadata=metadata or {},
            )
            records.append(fact)
            self._write(namespace, records)
            return fact

    def update_review_state(self, namespace: str, fact_id_: str, review_state: FactReviewState, *, reviewed_by: str | None = None, metadata: dict[str, Any] | None = None, promoted_edge_id: str | None = None) -> OntologyFact:
        self._require_namespace(namespace)
        with self._lock:
            records = self._read(namespace)
            for idx, fact in enumerate(records):
                if fact.id == fact_id_:
                    fact.review_state = review_state
                    fact.reviewed_by = reviewed_by
                    fact.reviewed_at = _utcnow()
                    if promoted_edge_id:
                        fact.promoted_edge_id = promoted_edge_id
                    if metadata:
                        fact.metadata.update(metadata)
                    records[idx] = fact
                    self._write(namespace, records)
                    return fact
        raise KeyError(f"Fact not found: {fact_id_}")

    def _require_namespace(self, namespace: str) -> None:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)

    def _read(self, namespace: str) -> list[OntologyFact]:
        path = self.facts_path(namespace)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [OntologyFact.model_validate(item) for item in (data if isinstance(data, list) else [])]

    def _write(self, namespace: str, records: list[OntologyFact]) -> None:
        target = self.facts_path(namespace)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".facts.", suffix=".tmp", dir=str(target.parent))
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


class OntologyFactPromotionService:
    """Review-gated bridge from approved fact to canonical graph edge."""

    def __init__(self, namespace_manager: NamespaceManager, graph_store: GraphInstanceStore, *, fact_store: OntologyFactStore | None = None, candidate_store: OntologyCandidateStore | None = None, profile_store: OntologyProfileStore | None = None, evidence_store: EvidenceStore | None = None, observation_store: ObservationEventStore | None = None) -> None:
        self._nm = namespace_manager
        self.graph_store = graph_store
        self.fact_store = fact_store or OntologyFactStore(namespace_manager)
        self.candidate_store = candidate_store or OntologyCandidateStore(namespace_manager)
        self.profile_store = profile_store or OntologyProfileStore(namespace_manager)
        self.evidence_store = evidence_store or EvidenceStore(namespace_manager)
        self.observation_store = observation_store or ObservationEventStore(namespace_manager)

    def promote_to_edge(self, namespace: str, fact_id_: str, *, relationship_type: str | None = None, source_id: str | None = None, target_id: str | None = None, reviewed_by: str | None = None) -> OntologyEdge:
        fact = self.fact_store.get(namespace, fact_id_)
        if fact is None:
            raise KeyError(f"Fact not found: {fact_id_}")
        if fact.review_state != "approved":
            raise OntologyMutationError("fact must be approved before promotion to a canonical edge")
        mapping = fact.suggested_mapping
        rel_type = normalize_candidate_label(relationship_type or (mapping.relationship_type if mapping else ""))
        src = source_id or (mapping.source_id if mapping else None)
        tgt = target_id or (mapping.target_id if mapping else None)
        if not rel_type or not src or not tgt:
            raise OntologyMutationError("relationship_type, source_id, and target_id are required for fact promotion")
        profile = self.profile_store.get(namespace)
        if profile is not None:
            rel = profile.relationship_types.get(rel_type)
            if rel is None or rel.lifecycle_state != "active":
                raise OntologyMutationError(f"Relationship type {rel_type!r} is not active in profile")
        edge_id = f"{src}:{rel_type}:{tgt}"
        candidate = OntologyCandidate(
            id=f"fact-edge:{hashlib.sha256(f'{namespace}:{fact.id}:{edge_id}'.encode()).hexdigest()[:20]}",
            namespace=namespace,
            candidate_type="edge",
            source=f"fact:{fact.source}",
            original_label=fact.statement,
            normalized_label=rel_type,
            suggested_canonical=rel_type,
            confidence=fact.confidence,
            sample_text=fact.statement[:500],
            status="approved",
            source_hash=fact.source_hash,
            proposed_payload={
                "id": edge_id,
                "source_id": src,
                "target_id": tgt,
                "relationship_type": rel_type,
                "review_state": "approved",
                "confidence": fact.confidence,
                "provenance_refs": [*fact.provenance_refs, fact.id],
                "metadata": {"promoted_from_fact_id": fact.id, "fact_statement": fact.statement},
            },
            source_evidence_ref=(fact.provenance_refs or fact.evidence_refs or [None])[0],
            reviewed_by=reviewed_by,
            reviewed_at=_utcnow(),
            metadata={"promoted_from_fact_id": fact.id},
        )
        approval = OntologyApprovalService(
            self._nm,
            self.graph_store,
            candidate_store=self.candidate_store,
            profile_store=self.profile_store,
            evidence_store=self.evidence_store,
            observation_store=self.observation_store,
        )
        edge = approval.confirm_edge(namespace, candidate, reviewed_by=reviewed_by)
        self.fact_store.update_review_state(namespace, fact.id, "reviewed", reviewed_by=reviewed_by, promoted_edge_id=edge.id, metadata={"promoted_edge_id": edge.id})
        self.observation_store.create(namespace, event_type="OntologyFactPromoted", subject_type="fact", subject_id=fact.id, created_by=reviewed_by, provenance_refs=edge.provenance_refs, metadata={"edge_id": edge.id, "relationship_type": rel_type})
        return edge

    def raise_relationship_candidate(self, namespace: str, fact_id_: str, *, relationship_label: str, reviewed_by: str | None = None) -> OntologyCandidate:
        fact = self.fact_store.get(namespace, fact_id_)
        if fact is None:
            raise KeyError(f"Fact not found: {fact_id_}")
        mapping = fact.suggested_mapping
        candidate = self.candidate_store.upsert_pending(
            namespace,
            candidate_type="relationship_type",
            original_label=relationship_label,
            source=f"fact:{fact.source}",
            suggested_canonical=normalize_candidate_label(relationship_label),
            confidence=fact.confidence,
            sample_text=fact.statement,
            source_hash=fact.source_hash or fact.id,
            source_evidence_ref=(fact.provenance_refs or fact.evidence_refs or [None])[0],
            proposed_payload={
                "label": relationship_label.strip().title(),
                "allowed_source_types": [],
                "allowed_target_types": [],
                "description": f"Raised from fact {fact.id}: {fact.statement}",
                **({"source_id": mapping.source_id, "target_id": mapping.target_id} if mapping else {}),
            },
            metadata={"fact_id": fact.id, "raised_by": reviewed_by or "anonymous"},
        )
        self.fact_store.update_review_state(namespace, fact.id, "reviewed", reviewed_by=reviewed_by, metadata={"relationship_candidate_id": candidate.id})
        self.observation_store.create(namespace, event_type="OntologyFactRelationshipCandidateRaised", subject_type="fact", subject_id=fact.id, created_by=reviewed_by, provenance_refs=fact.provenance_refs or fact.evidence_refs, metadata={"candidate_id": candidate.id})
        return candidate

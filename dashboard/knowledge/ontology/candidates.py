"""Namespace-scoped ontology candidate review storage and models."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError

CandidateType = Literal["concept_type", "relationship_type", "alias"]
CandidateStatus = Literal["pending", "approved", "mapped", "rejected"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_candidate_label(label: str) -> str:
    return "_".join(str(label or "").strip().lower().replace("-", "_").split())


def candidate_id(namespace: str, candidate_type: str, original_label: str, source_hash: str = "") -> str:
    base = f"{namespace}:{candidate_type}:{normalize_candidate_label(original_label)}:{source_hash or ''}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


class OntologyCandidate(BaseModel):
    """Reviewable ontology candidate emitted during extraction."""

    id: str
    namespace: str
    candidate_type: CandidateType
    source: str = "extraction"
    original_label: str
    normalized_label: str = ""
    suggested_canonical: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sample_text: str = ""
    status: CandidateStatus = "pending"
    source_hash: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyCandidateStore:
    """Atomic JSON store for ontology candidates under ``ontology/candidates.json``."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def ontology_dir(self, namespace: str) -> Path:
        return self._nm.namespace_dir(namespace) / "ontology"

    def candidates_path(self, namespace: str) -> Path:
        return self.ontology_dir(namespace) / "candidates.json"

    def list(
        self,
        namespace: str,
        *,
        status: str | None = None,
        candidate_type: str | None = None,
    ) -> list[OntologyCandidate]:
        self._require_namespace(namespace)
        records = self._read(namespace)
        if status:
            records = [r for r in records if r.status == status]
        if candidate_type:
            records = [r for r in records if r.candidate_type == candidate_type]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def pending_count(self, namespace: str) -> int:
        if self._nm.get(namespace) is None:
            return 0
        return sum(1 for r in self._read(namespace) if r.status == "pending")

    def upsert_pending(
        self,
        namespace: str,
        *,
        candidate_type: CandidateType,
        original_label: str,
        source: str,
        suggested_canonical: str | None = None,
        confidence: float = 0.5,
        sample_text: str = "",
        source_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> OntologyCandidate:
        self._require_namespace(namespace)
        normalized = normalize_candidate_label(original_label)
        cid = candidate_id(namespace, candidate_type, original_label, source_hash)
        with self._lock:
            records = self._read(namespace)
            for idx, existing in enumerate(records):
                if existing.id == cid:
                    # Rejected candidates for the same source hash intentionally do not reappear.
                    if existing.status == "pending":
                        existing.sample_text = existing.sample_text or sample_text[:500]
                        existing.confidence = max(existing.confidence, confidence)
                        existing.metadata.update(metadata or {})
                        records[idx] = existing
                        self._write(namespace, records)
                    return existing
            candidate = OntologyCandidate(
                id=cid,
                namespace=namespace,
                candidate_type=candidate_type,
                source=source,
                original_label=original_label,
                normalized_label=normalized,
                suggested_canonical=suggested_canonical or normalized,
                confidence=confidence,
                sample_text=sample_text[:500],
                status="pending",
                source_hash=source_hash or "",
                metadata=metadata or {},
            )
            records.append(candidate)
            self._write(namespace, records)
            return candidate

    def update_status(
        self,
        namespace: str,
        candidate_id_: str,
        status: CandidateStatus,
        *,
        reviewed_by: str | None = None,
        suggested_canonical: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OntologyCandidate:
        self._require_namespace(namespace)
        with self._lock:
            records = self._read(namespace)
            for idx, record in enumerate(records):
                if record.id == candidate_id_:
                    record.status = status
                    record.reviewed_by = reviewed_by
                    record.reviewed_at = _utcnow()
                    if suggested_canonical:
                        record.suggested_canonical = normalize_candidate_label(suggested_canonical)
                    if metadata:
                        record.metadata.update(metadata)
                    records[idx] = record
                    self._write(namespace, records)
                    return record
        raise KeyError(f"Candidate not found: {candidate_id_}")

    def _require_namespace(self, namespace: str) -> None:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)

    def _read(self, namespace: str) -> list[OntologyCandidate]:
        path = self.candidates_path(namespace)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [OntologyCandidate.model_validate(item) for item in (data if isinstance(data, list) else [])]

    def _write(self, namespace: str, records: list[OntologyCandidate]) -> None:
        target = self.candidates_path(namespace)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".candidates.", suffix=".tmp", dir=str(target.parent))
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

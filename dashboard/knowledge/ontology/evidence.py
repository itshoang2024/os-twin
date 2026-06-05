"""Namespace-scoped Evidence plane models and stores.

EPIC-003 makes source artifacts, readable anchors, and provenance links first
class ontology records.  The store is deliberately JSON based to match the
existing ontology profile/candidate stores and stays namespace-scoped under
``{namespace}/ontology/evidence``.
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

from pydantic import BaseModel, Field, field_validator, model_validator

from dashboard.knowledge.namespace import NamespaceManager, NamespaceNotFoundError

EvidenceSourceType = Literal[
    "document",
    "spreadsheet",
    "database_row",
    "api_payload",
    "ticket",
    "commit",
    "log",
    "message",
    "image",
    "manual_entry",
    "external_system",
]
ExtractionMethod = Literal["manual", "parser", "api", "ocr", "llm"]
ReadCoverage = Literal["unread", "partial", "sampled", "full", "failed"]
SourceState = Literal["read", "partial", "sampled", "ocr_needed", "conversion_needed", "failed", "manual"]
EvidenceLimitation = Literal[
    "partial",
    "sampled",
    "ocr_needed",
    "conversion_needed",
    "failed",
    "unsupported",
    "empty",
]
ProvenanceSubject = Literal["node", "edge", "fact", "event", "candidate"]
ProvenanceRelation = Literal["supports", "contradicts", "derived_from", "approved_by"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _short_hash(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


class EvidenceLocator(BaseModel):
    """Fine-grained pointer back into a source artifact."""

    model_config = {"extra": "forbid"}

    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    heading: str | None = None
    row: int | None = Field(default=None, ge=1)
    column: str | int | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    chunk_id: str | None = None
    timestamp: str | None = None

    @model_validator(mode="after")
    def _line_range_is_ordered(self) -> "EvidenceLocator":
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class EvidenceArtifact(BaseModel):
    """A source object imported into an ontology namespace."""

    model_config = {"extra": "forbid"}

    id: str
    ontology_unit_id: str
    source_type: EvidenceSourceType
    source_uri: str | None = None
    title: str | None = None
    checksum: str = ""
    ingested_at: datetime = Field(default_factory=_utcnow)
    ingested_by: str | None = None
    read_coverage: ReadCoverage = "unread"
    source_state: SourceState = "partial"
    limitations: list[EvidenceLimitation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "ontology_unit_id")
    @classmethod
    def _id_not_empty(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("identifier must not be empty")
        return value

    @model_validator(mode="after")
    def _unread_sources_have_limitations(self) -> "EvidenceArtifact":
        if self.read_coverage in {"unread", "failed"} and not self.limitations:
            raise ValueError("unread/failed artifacts must record at least one limitation")
        return self


class EvidenceAnchor(BaseModel):
    """A readable excerpt/locator inside an EvidenceArtifact."""

    model_config = {"extra": "forbid"}

    id: str
    artifact_id: str
    locator: EvidenceLocator = Field(default_factory=EvidenceLocator)
    excerpt: str = ""
    extraction_method: ExtractionMethod
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("excerpt")
    @classmethod
    def _bound_excerpt(cls, value: str) -> str:
        return (value or "")[:1000]


class ProvenanceLink(BaseModel):
    """Append-only support/derivation relationship from an anchor to a subject."""

    model_config = {"extra": "forbid"}

    id: str
    subject_type: ProvenanceSubject
    subject_id: str
    evidence_anchor_id: str
    relation: ProvenanceRelation = "supports"
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceStore:
    """Atomic namespace store for evidence artifacts/anchors and append-only provenance links."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def evidence_dir(self, namespace: str) -> Path:
        return self._nm.namespace_dir(namespace) / "ontology" / "evidence"

    def artifacts_path(self, namespace: str) -> Path:
        return self.evidence_dir(namespace) / "artifacts.json"

    def anchors_path(self, namespace: str) -> Path:
        return self.evidence_dir(namespace) / "anchors.json"

    def provenance_path(self, namespace: str) -> Path:
        return self.evidence_dir(namespace) / "provenance.jsonl"

    @staticmethod
    def artifact_id(namespace: str, source_uri: str, checksum: str = "") -> str:
        return f"artifact:{_short_hash(f'{namespace}:{source_uri}:{checksum}')}"

    @staticmethod
    def anchor_id(artifact_id: str, chunk_id: str | int | None = None, locator: EvidenceLocator | None = None) -> str:
        locator_json = json.dumps((locator or EvidenceLocator()).model_dump(mode="json", exclude_none=True), sort_keys=True)
        return f"anchor:{_short_hash(f'{artifact_id}:{chunk_id or locator_json}')}"

    @staticmethod
    def provenance_id(subject_type: str, subject_id: str, evidence_anchor_id: str, relation: str = "supports") -> str:
        return f"prov:{_short_hash(f'{subject_type}:{subject_id}:{evidence_anchor_id}:{relation}')}"

    def upsert_artifact(self, namespace: str, artifact: EvidenceArtifact) -> EvidenceArtifact:
        self._require_namespace(namespace)
        with self._lock:
            records = self._read_artifacts(namespace)
            for idx, existing in enumerate(records):
                if existing.id == artifact.id:
                    records[idx] = artifact
                    self._write_json(namespace, self.artifacts_path(namespace), [r.model_dump(mode="json") for r in records])
                    return artifact
            records.append(artifact)
            self._write_json(namespace, self.artifacts_path(namespace), [r.model_dump(mode="json") for r in records])
            return artifact

    def upsert_anchor(self, namespace: str, anchor: EvidenceAnchor) -> EvidenceAnchor:
        self._require_namespace(namespace)
        artifact_ids = {a.id for a in self._read_artifacts(namespace)}
        if anchor.artifact_id not in artifact_ids:
            raise ValueError(f"Evidence artifact not found: {anchor.artifact_id}")
        with self._lock:
            records = self._read_anchors(namespace)
            for idx, existing in enumerate(records):
                if existing.id == anchor.id:
                    records[idx] = anchor
                    self._write_json(namespace, self.anchors_path(namespace), [r.model_dump(mode="json") for r in records])
                    return anchor
            records.append(anchor)
            self._write_json(namespace, self.anchors_path(namespace), [r.model_dump(mode="json") for r in records])
            return anchor

    def append_provenance_link(self, namespace: str, link: ProvenanceLink) -> ProvenanceLink:
        self._require_namespace(namespace)
        anchor_ids = {a.id for a in self._read_anchors(namespace)}
        if link.evidence_anchor_id not in anchor_ids:
            raise ValueError(f"Evidence anchor not found: {link.evidence_anchor_id}")
        with self._lock:
            existing = {p.id for p in self._read_provenance(namespace)}
            if link.id in existing:
                return next(p for p in self._read_provenance(namespace) if p.id == link.id)
            target = self.provenance_path(namespace)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(link.model_dump(mode="json"), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return link

    def create_provenance_link(
        self,
        namespace: str,
        *,
        subject_type: ProvenanceSubject,
        subject_id: str,
        evidence_anchor_id: str,
        relation: ProvenanceRelation = "supports",
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProvenanceLink:
        link = ProvenanceLink(
            id=self.provenance_id(subject_type, subject_id, evidence_anchor_id, relation),
            subject_type=subject_type,
            subject_id=subject_id,
            evidence_anchor_id=evidence_anchor_id,
            relation=relation,
            created_by=created_by,
            metadata=metadata or {},
        )
        return self.append_provenance_link(namespace, link)

    def list_artifacts(self, namespace: str) -> list[EvidenceArtifact]:
        self._require_namespace(namespace)
        return sorted(self._read_artifacts(namespace), key=lambda a: a.ingested_at, reverse=True)

    def list_anchors(self, namespace: str, artifact_id: str | None = None) -> list[EvidenceAnchor]:
        self._require_namespace(namespace)
        records = self._read_anchors(namespace)
        if artifact_id:
            records = [r for r in records if r.artifact_id == artifact_id]
        return sorted(records, key=lambda a: a.created_at)

    def list_provenance(self, namespace: str, subject_type: str | None = None, subject_id: str | None = None) -> list[ProvenanceLink]:
        self._require_namespace(namespace)
        records = self._read_provenance(namespace)
        if subject_type:
            records = [r for r in records if r.subject_type == subject_type]
        if subject_id:
            records = [r for r in records if r.subject_id == subject_id]
        return sorted(records, key=lambda p: p.created_at)

    def resolve_provenance(self, namespace: str, provenance_id: str) -> dict[str, Any] | None:
        self._require_namespace(namespace)
        links = {p.id: p for p in self._read_provenance(namespace)}
        link = links.get(provenance_id)
        if link is None:
            return None
        anchors = {a.id: a for a in self._read_anchors(namespace)}
        artifacts = {a.id: a for a in self._read_artifacts(namespace)}
        anchor = anchors.get(link.evidence_anchor_id)
        artifact = artifacts.get(anchor.artifact_id) if anchor else None
        return {
            "provenance_link": link.model_dump(mode="json"),
            "anchor": anchor.model_dump(mode="json") if anchor else None,
            "artifact": artifact.model_dump(mode="json") if artifact else None,
        }

    def _require_namespace(self, namespace: str) -> None:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)

    def _read_artifacts(self, namespace: str) -> list[EvidenceArtifact]:
        return [EvidenceArtifact.model_validate(item) for item in self._read_json(self.artifacts_path(namespace))]

    def _read_anchors(self, namespace: str) -> list[EvidenceAnchor]:
        return [EvidenceAnchor.model_validate(item) for item in self._read_json(self.anchors_path(namespace))]

    def _read_provenance(self, namespace: str) -> list[ProvenanceLink]:
        path = self.provenance_path(namespace)
        if not path.exists():
            return []
        records: list[ProvenanceLink] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    records.append(ProvenanceLink.model_validate(json.loads(line)))
        return records

    @staticmethod
    def _read_json(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []

    @staticmethod
    def _write_json(namespace: str, target: Path, payload: list[dict[str, Any]]) -> None:  # noqa: ARG004
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def source_type_for_extension(extension: str) -> EvidenceSourceType:
    ext = (extension or "").lower()
    if ext in {".xls", ".xlsx", ".csv"}:
        return "spreadsheet"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}:
        return "image"
    if ext in {".log"}:
        return "log"
    return "document"

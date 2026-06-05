"""Observation-plane events and MVP time-series storage.

Observation history is operational telemetry for ontology activity. It is kept
separate from ``profile_history`` governance audit records: profile history tells
which schema version changed and why, while these records explain runtime events
for candidates, facts, imports, validations, and graph instances over time.
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

ObservationSubjectType = (
    Literal["instance", "node", "edge", "candidate", "fact", "import", "validation", "profile", "pack", "namespace"]
    | str
)
TimeSelectionMode = Literal["none", "fixed_range", "latest_import", "current_profile_version"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


class ObservationEvent(BaseModel):
    """Append-only operational event for ontology subjects.

    ``occurred_at`` is the event time used for filtering. ``actor`` identifies the
    producer when known. ``value`` stores a small numeric/string value for counts
    or state changes, while ``evidence_refs`` preserves provenance links. The
    compatibility properties keep EPIC-004/006 callers that used
    ``created_at``/``created_by``/``provenance_refs`` working while the canonical
    EPIC-007 contract uses occurred_at/actor/evidence_refs.
    """

    model_config = {"extra": "forbid"}

    id: str
    namespace: str
    event_type: str
    subject_type: ObservationSubjectType
    subject_id: str
    occurred_at: datetime = Field(default_factory=_utcnow)
    actor: str | None = None
    value: float | int | str | bool | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        mapped = dict(data)
        if "occurred_at" not in mapped and "created_at" in mapped:
            mapped["occurred_at"] = mapped.pop("created_at")
        if "actor" not in mapped and "created_by" in mapped:
            mapped["actor"] = mapped.pop("created_by")
        if "evidence_refs" not in mapped and "provenance_refs" in mapped:
            mapped["evidence_refs"] = mapped.pop("provenance_refs")
        return mapped

    @field_validator("event_type", "subject_type", "subject_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("observation event fields cannot be empty")
        return text

    @field_validator("evidence_refs")
    @classmethod
    def _dedupe_refs(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        refs: list[str] = []
        for item in value or []:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                refs.append(text)
        return refs

    @property
    def created_at(self) -> datetime:
        return self.occurred_at

    @property
    def created_by(self) -> str | None:
        return self.actor

    @property
    def provenance_refs(self) -> list[str]:
        return self.evidence_refs


class TimeSeriesPoint(BaseModel):
    """Single MVP time-series data point."""

    timestamp: datetime
    value: float
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimeSeries(BaseModel):
    """Inline MVP series for selected-object metrics.

    This is intentionally small JSON storage for PO-demo metrics and must not be
    treated as a production columnar/append-only analytics backend.
    """

    model_config = {"extra": "forbid"}

    id: str
    namespace: str
    subject_id: str
    metric_id: str
    unit: str = "count"
    points: list[TimeSeriesPoint] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("subject_id", "metric_id")
    @classmethod
    def _required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("time series subject_id and metric_id are required")
        return text


def observation_event_id(
    namespace: str,
    subject_type: str,
    subject_id: str,
    event_type: str,
    occurred_at: datetime,
) -> str:
    stamp = occurred_at.isoformat()
    raw = f"{namespace}:{subject_type}:{subject_id}:{event_type}:{stamp}"
    return "evt:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def time_series_id(namespace: str, subject_id: str, metric_id: str) -> str:
    return "series:" + hashlib.sha256(f"{namespace}:{subject_id}:{metric_id}".encode()).hexdigest()[:24]


class ObservationEventStore:
    """Namespace-scoped append-only JSONL event store."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def events_path(self, namespace: str) -> Path:
        return self._nm.namespace_dir(namespace) / "ontology" / "observation" / "events.jsonl"

    @staticmethod
    def event_id(namespace: str, subject_type: str, subject_id: str, event_type: str, occurred_at: datetime) -> str:
        return observation_event_id(namespace, subject_type, subject_id, event_type, occurred_at)

    def append(self, namespace: str, event: ObservationEvent) -> ObservationEvent:
        self._require_namespace(namespace)
        if event.namespace != namespace:
            raise ValueError("event namespace does not match store namespace")
        target = self.events_path(namespace)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return event

    def create(
        self,
        namespace: str,
        *,
        event_type: str,
        subject_type: str,
        subject_id: str,
        actor: str | None = None,
        created_by: str | None = None,
        value: float | int | str | bool | None = None,
        metadata: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
        provenance_refs: list[str] | None = None,
        occurred_at: datetime | None = None,
    ) -> ObservationEvent:
        happened = occurred_at or _utcnow()
        return self.append(
            namespace,
            ObservationEvent(
                id=self.event_id(namespace, subject_type, subject_id, event_type, happened),
                namespace=namespace,
                event_type=event_type,
                subject_type=subject_type,
                subject_id=subject_id,
                occurred_at=happened,
                actor=actor or created_by,
                value=value,
                evidence_refs=evidence_refs if evidence_refs is not None else (provenance_refs or []),
                metadata=metadata or {},
            ),
        )

    def list(
        self,
        namespace: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        event_type: str | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> list[ObservationEvent]:
        self._require_namespace(namespace)
        path = self.events_path(namespace)
        if not path.exists():
            return []
        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end)
        events: list[ObservationEvent] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                event = ObservationEvent.model_validate(json.loads(line))
                if subject_type and event.subject_type != subject_type:
                    continue
                if subject_id and event.subject_id != subject_id:
                    continue
                if event_type and event.event_type != event_type:
                    continue
                if start_dt and event.occurred_at < start_dt:
                    continue
                if end_dt and event.occurred_at > end_dt:
                    continue
                events.append(event)
        return sorted(events, key=lambda item: item.occurred_at, reverse=True)

    def latest_by_type(self, namespace: str, event_type: str) -> ObservationEvent | None:
        events = self.list(namespace, event_type=event_type)
        return events[0] if events else None

    def summary_for_subjects(
        self,
        namespace: str,
        subject_ids: list[str],
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> dict[str, dict[str, Any]]:
        ids = {str(item) for item in subject_ids if str(item)}
        result = {subject_id: {"event_count": 0, "active_event_count": 0, "time_range": None} for subject_id in ids}
        if not ids:
            return result
        for event in self.list(namespace, start=start, end=end):
            if event.subject_id not in ids:
                continue
            rec = result[event.subject_id]
            rec["event_count"] += 1
            if _is_active_event(event):
                rec["active_event_count"] += 1
            existing = rec.get("time_range") or {}
            iso = event.occurred_at.isoformat()
            rec["time_range"] = {
                "start": min(existing.get("start", iso), iso),
                "end": max(existing.get("end", iso), iso),
            }
        return result

    def _require_namespace(self, namespace: str) -> None:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)


class TimeSeriesStore:
    """Atomic JSON store for MVP time-series records."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def series_path(self, namespace: str) -> Path:
        return self._nm.namespace_dir(namespace) / "ontology" / "observation" / "series.json"

    def list(self, namespace: str, *, subject_id: str | None = None, metric_id: str | None = None) -> list[TimeSeries]:
        self._require_namespace(namespace)
        records = self._read(namespace)
        if subject_id:
            records = [record for record in records if record.subject_id == subject_id]
        if metric_id:
            records = [record for record in records if record.metric_id == metric_id]
        return sorted(records, key=lambda item: (item.subject_id, item.metric_id))

    def upsert(
        self,
        namespace: str,
        *,
        subject_id: str,
        metric_id: str,
        unit: str = "count",
        points: list[dict[str, Any] | TimeSeriesPoint] | None = None,
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TimeSeries:
        self._require_namespace(namespace)
        now = _utcnow()
        sid = time_series_id(namespace, subject_id, metric_id)
        parsed_points = [
            point if isinstance(point, TimeSeriesPoint) else TimeSeriesPoint.model_validate(point)
            for point in (points or [])
        ]
        with self._lock:
            records = self._read(namespace)
            for idx, existing in enumerate(records):
                if existing.id == sid:
                    existing.unit = unit or existing.unit
                    existing.points = parsed_points
                    existing.evidence_refs = evidence_refs or existing.evidence_refs
                    existing.metadata.update(metadata or {})
                    existing.updated_at = now
                    records[idx] = existing
                    self._write(namespace, records)
                    return existing
            series = TimeSeries(
                id=sid,
                namespace=namespace,
                subject_id=subject_id,
                metric_id=metric_id,
                unit=unit,
                points=parsed_points,
                evidence_refs=evidence_refs or [],
                metadata=metadata or {},
                created_at=now,
                updated_at=now,
            )
            records.append(series)
            self._write(namespace, records)
            return series

    def refs_for_subjects(self, namespace: str, subject_ids: list[str]) -> dict[str, list[str]]:
        ids = {str(item) for item in subject_ids if str(item)}
        result = {subject_id: [] for subject_id in ids}
        for series in self.list(namespace):
            if series.subject_id in result:
                result[series.subject_id].append(series.id)
        return result

    def _read(self, namespace: str) -> list[TimeSeries]:
        path = self.series_path(namespace)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [TimeSeries.model_validate(item) for item in (data if isinstance(data, list) else [])]

    def _write(self, namespace: str, records: list[TimeSeries]) -> None:
        target = self.series_path(namespace)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".series.", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump([record.model_dump(mode="json") for record in records], fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _require_namespace(self, namespace: str) -> None:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)


def _is_active_event(event: ObservationEvent) -> bool:
    if str(event.metadata.get("active", "")).lower() == "true":
        return True
    text = event.event_type.lower()
    return any(marker in text for marker in ("confirmed", "approved", "activated", "promoted", "issue"))

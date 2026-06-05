from datetime import UTC, datetime, timedelta

from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.observation import ObservationEvent, ObservationEventStore, TimeSeriesStore
from dashboard.knowledge.service import KnowledgeService


def test_observation_event_validation_persistence_and_time_filter(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = ObservationEventStore(nm)
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = older + timedelta(days=1)

    store.create(
        "demo",
        event_type="CandidateCreated",
        subject_type="candidate",
        subject_id="cand-1",
        actor="extractor",
        evidence_refs=["anchor:1", "anchor:1"],
        occurred_at=older,
    )
    store.create(
        "demo",
        event_type="ValidationIssueRaised",
        subject_type="node",
        subject_id="node-1",
        value=1,
        occurred_at=newer,
    )

    candidate_events = store.list("demo", subject_type="candidate")
    assert len(candidate_events) == 1
    assert candidate_events[0].evidence_refs == ["anchor:1"]
    assert candidate_events[0].provenance_refs == ["anchor:1"]
    assert store.list("demo", start=(older + timedelta(hours=1)).isoformat())[0].event_type == "ValidationIssueRaised"
    assert ObservationEvent.model_validate(candidate_events[0].model_dump(mode="json")).occurred_at == older


def test_time_series_store_and_projection_counts_do_not_touch_profile_history(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)
    event_store = ObservationEventStore(nm)
    series_store = TimeSeriesStore(nm)
    event_store.create("demo", event_type="ObjectConfirmed", subject_type="node", subject_id="node-1", actor="po")
    event_store.create(
        "demo",
        event_type="OntologyCandidateApproved",
        subject_type="candidate",
        subject_id="cand-1",
        actor="po",
    )
    series = series_store.upsert(
        "demo",
        subject_id="node-1",
        metric_id="event_count",
        points=[{"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "value": 1}],
    )

    result = {"nodes": [{"id": "node-1"}], "edges": [], "stats": {}, "meta": {}}
    service._attach_observation_projection("demo", result, filters={})  # noqa: SLF001

    assert result["nodes"][0]["event_count"] == 1
    assert result["nodes"][0]["active_event_count"] == 1
    assert result["nodes"][0]["series_refs"] == [series.id]
    assert service.list_ontology_profile_history("demo") == []


def test_service_observation_api_shapes_and_inline_series_event(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)

    saved = service.upsert_time_series(
        "demo",
        subject_id="node-1",
        metric_id="validation_count",
        unit="count",
        points=[{"timestamp": datetime(2026, 1, 2, tzinfo=UTC), "value": 2}],
        evidence_refs=["prov:series"],
        metadata={"created_by": "qa"},
    )

    assert saved["metric_id"] == "validation_count"
    assert service.list_time_series("demo", subject_id="node-1")[0]["id"] == saved["id"]
    events = service.list_observation_events("demo", subject_id="node-1")
    assert events[0]["event_type"] == "TimeSeriesUpdated"
    assert events[0]["evidence_refs"] == ["prov:series"]

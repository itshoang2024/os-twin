from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.analysis import (
    AnalysisStore,
    FlowDefinition,
    FlowStep,
    SimulationMetricDefinition,
    SimulationScenario,
    StateDefinition,
    StateMachine,
    StateTransition,
    validate_state_transition,
)
from dashboard.knowledge.service import KnowledgeService


def test_analysis_models_store_and_validation_guards(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = AnalysisStore(nm)

    flow = store.upsert_flow(
        "demo",
        FlowDefinition(
            namespace="demo",
            name="Evidence to finding",
            steps=[FlowStep(order=1, node_id="evidence-1", action_label="Attach evidence", required_event_type="EvidenceAttached")],
        ),
    )
    machine = store.upsert_state_machine(
        "demo",
        StateMachine(
            namespace="demo",
            name="Evidence lifecycle",
            subject_concept_type="evidence",
            states=[StateDefinition(id="draft", label="Draft"), StateDefinition(id="ready", label="Ready", color="#16a34a")],
            transitions=[StateTransition(from_state="draft", to="ready", event_type="EvidenceApproved", evidence_required=True, enforcement="enforced", guard_rule={"required_metadata": ["owner"]})],
            enforcement_enabled=True,
        ),
    )
    scenario = store.upsert_simulation_scenario(
        "demo",
        SimulationScenario(
            namespace="demo",
            name="Closure what-if",
            assumptions={"cycle_days": 10},
            input_node_ids=["evidence-1", "evidence-1"],
            input_series_ids=["series:events"],
            output_metrics=[SimulationMetricDefinition(id="closure_rate", label="Closure rate")],
        ),
    )

    assert store.list_flows("demo")[0].id == flow.id
    assert store.list_state_machines("demo")[0].id == machine.id
    assert store.list_simulation_scenarios("demo")[0].simulation_state == "provider_required"
    assert scenario.input_node_ids == ["evidence-1"]

    issues = validate_state_transition(machine, current_state="draft", event_type="EvidenceApproved", evidence_refs=[], metadata={})
    assert {issue.code for issue in issues} == {"STATE_TRANSITION_EVIDENCE_REQUIRED", "STATE_TRANSITION_GUARD_FAILED"}
    assert all(issue.severity == "error" for issue in issues)


def test_analysis_projection_attaches_only_saved_definitions(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)
    service.upsert_flow_definition("demo", {"name": "Evidence path", "steps": [{"order": 0, "node_id": "evidence-1", "action_label": "Review", "required_event_type": "ReviewCompleted"}]})
    service.upsert_state_machine("demo", {"name": "Evidence lifecycle", "subject_concept_type": "evidence", "states": [{"id": "draft", "label": "Draft"}, {"id": "ready", "label": "Ready", "color": "#16a34a"}], "transitions": [{"from": "draft", "to": "ready", "event_type": "EvidenceApproved", "evidence_required": True}]})
    service.upsert_simulation_scenario("demo", {"name": "Provider missing scenario", "input_node_ids": ["evidence-1"], "output_metrics": [{"id": "readiness", "label": "Readiness"}]})

    result = {"nodes": [{"id": "evidence-1", "concept_type": "evidence", "metadata": {"state": "draft"}}], "edges": [], "stats": {}, "meta": {}}
    service._attach_analysis_projection("demo", result)  # noqa: SLF001

    node = result["nodes"][0]
    assert node["flow_refs"]
    assert node["state"] == "draft"
    assert node["simulation_state"] == "provider_required"
    assert result["meta"]["analysis"]["simulation_provider_required"] is True


def test_simulation_outputs_require_provider_or_saved_result(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = AnalysisStore(nm)
    try:
        store.upsert_simulation_scenario("demo", SimulationScenario(namespace="demo", name="Bad outputs", saved_outputs={"metric": 1}))
    except ValueError as exc:
        assert "provider_id or result_ref" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("saved outputs without provider/result should fail")

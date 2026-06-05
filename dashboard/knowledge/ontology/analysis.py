"""Analysis-plane flow, state-machine, and simulation scenario models.

The Analysis plane explains workflows and lifecycle transitions from saved
ontology definitions. It deliberately does not execute predictions: simulation
outputs are only persisted when a provider/result reference exists.
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
from dashboard.knowledge.ontology.models import StrictOntologyModel, _validate_identifier
from dashboard.knowledge.ontology.validator import ValidationIssue


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _dedupe_strings(value: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in value or []:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def analysis_id(namespace: str, kind: str, name: str) -> str:
    digest = hashlib.sha256(f"{namespace}:{kind}:{name.strip()}".encode("utf-8")).hexdigest()[:24]
    return f"{kind}:{digest}"


class FlowStep(StrictOntologyModel):
    """A single explainable workflow step tied to graph nodes or concepts."""

    order: int = Field(ge=0)
    node_id: str | None = None
    concept_type: str | None = None
    action_label: str
    required_event_type: str | None = None
    description: str = ""

    @field_validator("node_id", "concept_type", "required_event_type")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("action_label")
    @classmethod
    def _action_required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("flow step action_label is required")
        return text

    @model_validator(mode="after")
    def _must_reference_graph_or_concept(self) -> "FlowStep":
        if not self.node_id and not self.concept_type:
            raise ValueError("flow step must reference node_id or concept_type")
        return self


class FlowDefinition(StrictOntologyModel):
    """Namespace-local workflow overlay for ontology objects."""

    id: str | None = None
    namespace: str
    name: str
    purpose: str = ""
    steps: list[FlowStep] = Field(default_factory=list, min_length=1)
    pack_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("flow name is required")
        return text

    @model_validator(mode="after")
    def _derive_id_and_unique_order(self) -> "FlowDefinition":
        self.id = self.id or analysis_id(self.namespace, "flow", self.name)
        orders = [step.order for step in self.steps]
        if len(orders) != len(set(orders)):
            raise ValueError("flow step order values must be unique")
        self.steps = sorted(self.steps, key=lambda step: step.order)
        return self


class StateDefinition(StrictOntologyModel):
    id: str
    label: str
    color: str | None = None
    description: str = ""

    @field_validator("id")
    @classmethod
    def _id_valid(cls, value: str) -> str:
        return _validate_identifier(value, "StateDefinition.id")


class StateTransition(StrictOntologyModel):
    """Inspectable lifecycle transition. Serialized field is `from`."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    from_state: str = Field(alias="from")
    to: str
    event_type: str
    guard_rule: dict[str, Any] | None = None
    evidence_required: bool = False
    enforcement: Literal["advisory", "enforced"] = "advisory"
    description: str = ""

    @field_validator("from_state", "to", "event_type")
    @classmethod
    def _required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("state transition from/to/event_type are required")
        return text


class StateMachine(StrictOntologyModel):
    id: str | None = None
    namespace: str
    name: str
    subject_concept_type: str
    states: list[StateDefinition] = Field(default_factory=list, min_length=1)
    initial_state: str | None = None
    transitions: list[StateTransition] = Field(default_factory=list)
    enforcement_enabled: bool = False
    pack_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "subject_concept_type")
    @classmethod
    def _required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("state machine name and subject_concept_type are required")
        return text

    @model_validator(mode="after")
    def _validate_states_and_transitions(self) -> "StateMachine":
        self.id = self.id or analysis_id(self.namespace, "state_machine", self.name)
        state_ids = [state.id for state in self.states]
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("state ids must be unique")
        known = set(state_ids)
        if self.initial_state is None:
            self.initial_state = state_ids[0]
        if self.initial_state not in known:
            raise ValueError("initial_state must reference a defined state")
        for transition in self.transitions:
            if transition.from_state not in known or transition.to not in known:
                raise ValueError("state transition endpoints must reference defined states")
        return self


class SimulationMetricDefinition(StrictOntologyModel):
    id: str
    label: str
    unit: str = "count"
    description: str = ""

    @field_validator("id")
    @classmethod
    def _id_valid(cls, value: str) -> str:
        return _validate_identifier(value, "SimulationMetricDefinition.id")


class SimulationScenario(StrictOntologyModel):
    """Provider-pluggable scenario capture without an embedded engine."""

    id: str | None = None
    namespace: str
    name: str
    description: str = ""
    assumptions: dict[str, Any] = Field(default_factory=dict)
    input_node_ids: list[str] = Field(default_factory=list)
    input_series_ids: list[str] = Field(default_factory=list)
    output_metrics: list[SimulationMetricDefinition] = Field(default_factory=list)
    provider_id: str | None = None
    provider_requirements: list[str] = Field(default_factory=lambda: ["registered_analysis_provider"])
    result_ref: str | None = None
    saved_outputs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("simulation scenario name is required")
        return text

    @field_validator("input_node_ids", "input_series_ids", "provider_requirements")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return _dedupe_strings(value)

    @model_validator(mode="after")
    def _honest_outputs(self) -> "SimulationScenario":
        self.id = self.id or analysis_id(self.namespace, "simulation", self.name)
        if self.saved_outputs and not (self.provider_id or self.result_ref):
            raise ValueError("simulation saved_outputs require provider_id or result_ref")
        return self

    @property
    def simulation_state(self) -> str:
        if self.saved_outputs or self.result_ref:
            return "result_saved"
        if self.provider_id:
            return "provider_ready"
        return "provider_required"


class SimulationProviderContract(StrictOntologyModel):
    """Placeholder contract for future analytics packs/providers."""

    provider_id: str
    supported_scenario_kinds: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    governance_notes: list[str] = Field(default_factory=list)


class AnalysisStore:
    """Atomic namespace-scoped JSON store under ``ontology/analysis``."""

    def __init__(self, namespace_manager: NamespaceManager) -> None:
        self._nm = namespace_manager
        self._lock = threading.Lock()

    def analysis_dir(self, namespace: str) -> Path:
        return self._nm.namespace_dir(namespace) / "ontology" / "analysis"

    def flows_path(self, namespace: str) -> Path:
        return self.analysis_dir(namespace) / "flows.json"

    def state_machines_path(self, namespace: str) -> Path:
        return self.analysis_dir(namespace) / "state_machines.json"

    def scenarios_path(self, namespace: str) -> Path:
        return self.analysis_dir(namespace) / "simulation_scenarios.json"

    def list_flows(self, namespace: str) -> list[FlowDefinition]:
        return self._read(namespace, self.flows_path(namespace), FlowDefinition)

    def list_state_machines(self, namespace: str) -> list[StateMachine]:
        return self._read(namespace, self.state_machines_path(namespace), StateMachine)

    def list_simulation_scenarios(self, namespace: str) -> list[SimulationScenario]:
        return self._read(namespace, self.scenarios_path(namespace), SimulationScenario)

    def upsert_flow(self, namespace: str, flow: FlowDefinition) -> FlowDefinition:
        return self._upsert(namespace, self.flows_path(namespace), FlowDefinition, flow)

    def upsert_state_machine(self, namespace: str, machine: StateMachine) -> StateMachine:
        return self._upsert(namespace, self.state_machines_path(namespace), StateMachine, machine)

    def upsert_simulation_scenario(self, namespace: str, scenario: SimulationScenario) -> SimulationScenario:
        return self._upsert(namespace, self.scenarios_path(namespace), SimulationScenario, scenario)

    def _upsert(self, namespace: str, path: Path, model: type, record: Any) -> Any:
        self._require_namespace(namespace)
        if record.namespace != namespace:
            raise ValueError("analysis record namespace does not match store namespace")
        record.updated_at = _utcnow()
        with self._lock:
            records = self._read(namespace, path, model)
            for idx, existing in enumerate(records):
                if existing.id == record.id:
                    records[idx] = record
                    self._write(path, records)
                    return record
            records.append(record)
            self._write(path, records)
            return record

    def _read(self, namespace: str, path: Path, model: type) -> list[Any]:
        self._require_namespace(namespace)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
        return [model.model_validate(item) for item in data]

    def _write(self, path: Path, records: list[Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump([r.model_dump(mode="json", by_alias=True) for r in records], fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _require_namespace(self, namespace: str) -> None:
        if self._nm.get(namespace) is None:
            raise NamespaceNotFoundError(namespace)


def validate_state_transition(
    machine: StateMachine,
    *,
    current_state: str,
    event_type: str,
    evidence_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[ValidationIssue]:
    """Evaluate configured state-machine guards before enforcement.

    The helper is intentionally small and inspectable. It reports issues that can
    feed normal validation responses; callers decide whether advisory issues block
    mutation based on ``machine.enforcement_enabled`` and transition enforcement.
    """

    metadata = metadata or {}
    evidence_refs = evidence_refs or []
    transition = next(
        (item for item in machine.transitions if item.from_state == current_state and item.event_type == event_type),
        None,
    )
    if transition is None:
        return [ValidationIssue(severity="warning", code="STATE_TRANSITION_UNCONFIGURED", path="state.event_type", message=f"No transition from '{current_state}' for event '{event_type}'.", suggested_fix="Configure a state-machine transition or keep validation advisory.", subject="node", metadata={"state_machine_id": machine.id})]

    issues: list[ValidationIssue] = []
    blocking = machine.enforcement_enabled or transition.enforcement == "enforced"
    severity = "error" if blocking else "warning"
    if transition.evidence_required and not evidence_refs:
        issues.append(ValidationIssue(severity=severity, code="STATE_TRANSITION_EVIDENCE_REQUIRED", path="state.evidence_refs", message=f"Transition '{current_state}' → '{transition.to}' requires supporting evidence.", suggested_fix="Attach evidence_refs/provenance before completing this transition.", subject="node", metadata={"state_machine_id": machine.id, "event_type": event_type}))
    guard = transition.guard_rule or {}
    required_metadata = guard.get("required_metadata") if isinstance(guard, dict) else None
    if isinstance(required_metadata, list):
        missing = [str(key) for key in required_metadata if not metadata.get(str(key))]
        if missing:
            issues.append(ValidationIssue(severity=severity, code="STATE_TRANSITION_GUARD_FAILED", path="state.guard_rule.required_metadata", message=f"Transition guard missing metadata: {', '.join(missing)}.", suggested_fix="Populate required metadata or relax the guard rule.", subject="node", metadata={"state_machine_id": machine.id, "missing": missing}))
    return issues

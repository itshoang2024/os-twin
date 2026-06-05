import EnterpriseMapPanel from '@/components/knowledge/EnterpriseMapPanel';
import type { EnterpriseMapProjectionData } from '@/hooks/use-knowledge-explorer';
import type { ObservationEvent, OntologyProfile, TimeSeries } from '@/hooks/use-ontology';

const fixtureProfile: OntologyProfile = {
  profile_id: 'enterprise_feature_map',
  namespace: 'qa-enterprise-map-fixture',
  version: '1.0.0',
  status: 'active',
  concept_types: {
    risk: { id: 'risk', label: 'Risk', color: '#be123c', default_layer: 'governance', abstraction_level: 'control' },
    control: { id: 'control', label: 'Control', color: '#2563eb', default_layer: 'governance', abstraction_level: 'control' },
    evidence: { id: 'evidence', label: 'Evidence', color: '#d97706', default_layer: 'evidence', abstraction_level: 'record' },
  },
  relationship_types: {
    evidences: { id: 'evidences', label: 'Evidences', family: 'evidence', style: 'dotted' },
    mitigates: { id: 'mitigates', label: 'Mitigates', family: 'validation', style: 'bold' },
  },
  aliases: {},
  concept_aliases: {},
  layers: {
    governance: { id: 'governance', label: 'Governance', order: 1 },
    evidence: { id: 'evidence', label: 'Evidence', order: 2 },
  },
  abstraction_levels: {
    control: { id: 'control', label: 'Control', order: 1 },
    record: { id: 'record', label: 'Record', order: 2 },
  },
  metadata_fields: {},
  validation_rules: [],
};

const fixtureMap: EnterpriseMapProjectionData = {
  nodes: [
    {
      id: 'risk-1', label: 'Risk', name: 'Vendor outage risk', score: 1,
      concept_type: 'risk', concept_label: 'Risk', concept_color: '#be123c',
      layer_id: 'governance', layer_label: 'Governance', layer_order: 1,
      abstraction_level: 'control', abstraction_label: 'Control', pack_id: 'audit-risk-management',
      lifecycle_state: 'active', review_state: 'approved', confidence: 0.92,
      provenance_refs: ['prov-risk'], external_ref: { system: 'jira', id: 'RISK-1' },
      owner: 'Risk', description: 'Third-party outage exposure confirmed from reviewed source evidence.',
      quality_state: 'watch', metadata: { owner: 'Risk', purpose: 'Track outage exposure' }, properties: {},
      event_count: 3, active_event_count: 2,
      time_range: { start: '2026-06-01T09:00:00Z', end: '2026-06-03T11:30:00Z' },
      series_refs: ['risk-1:event_count', 'risk-1:validation_count'],
      flow_refs: ['flow:evidence_to_finding'], state: 'ready_for_finding', state_machine_ref: 'state_machine:risk_closure',
      state_color: '#16a34a', simulation_state: 'provider_required', simulation_refs: ['simulation:closure_what_if'],
    },
    {
      id: 'control-1', label: 'Control', name: 'Failover control', score: 1,
      concept_type: 'control', concept_label: 'Control', concept_color: '#2563eb',
      layer_id: 'governance', layer_label: 'Governance', layer_order: 1,
      abstraction_level: 'control', abstraction_label: 'Control', pack_id: 'audit-risk-management',
      lifecycle_state: 'active', review_state: 'approved', confidence: 0.88,
      provenance_refs: ['prov-control'], external_ref: { system: 'gRC', id: 'CTRL-1' },
      owner: 'Risk', description: 'Reviewed failover procedure that mitigates the vendor outage risk.',
      metadata: { owner: 'Risk', purpose: 'Mitigate outage' }, properties: {},
    },
    {
      id: 'evidence-1', label: 'Evidence', name: 'DR test evidence', score: 1,
      concept_type: 'evidence', concept_label: 'Evidence', concept_color: '#d97706',
      layer_id: 'evidence', layer_label: 'Evidence', layer_order: 2,
      abstraction_level: 'record', abstraction_label: 'Record', pack_id: 'audit-risk-management',
      lifecycle_state: 'candidate', review_state: 'pending', confidence: 0.64,
      provenance_refs: ['prov-evidence'], external_ref: { system: 'docs', id: 'DR-TEST-2026' },
      owner: 'Audit', description: 'Unverified discovered instance awaiting reviewer confirmation.',
      metadata: { owner: 'Audit', purpose: 'Evidence control' }, properties: {},
      validation_issues: [{ message: 'Needs reviewer before relying on this evidence instance.' }],
      event_count: 4, active_event_count: 1,
      time_range: { start: '2026-06-02T10:00:00Z', end: '2026-06-03T12:00:00Z' },
      series_refs: ['evidence-1:event_count', 'evidence-1:candidate_count', 'evidence-1:validation_count'],
    },
  ],
  edges: [
    {
      source: 'evidence-1', target: 'control-1', map_source: 'evidence-1', map_target: 'control-1',
      label: 'evidences', relationship_type: 'evidences', family: 'evidence', weight: 0.7, style: 'dotted',
      review_state: 'candidate', confidence: 0.61, provenance_refs: ['prov-candidate-edge'],
    },
    {
      source: 'control-1', target: 'risk-1', map_source: 'control-1', map_target: 'risk-1',
      label: 'mitigates', relationship_type: 'mitigates', family: 'validation', weight: 0.8, style: 'bold',
      review_state: 'approved', confidence: 0.88, provenance_refs: ['prov-edge'], external_ref: { system: 'gRC', id: 'CTRL-1' },
    },
  ],
  layers: [
    { id: 'governance', label: 'Governance', order: 1, count: 2 },
    { id: 'evidence', label: 'Evidence', order: 2, count: 1 },
  ],
  abstraction_levels: [
    { id: 'control', label: 'Control', order: 1 },
    { id: 'record', label: 'Record', order: 2 },
  ],
  concept_type_counts: { risk: 1, control: 1, evidence: 1 },
  relationship_type_counts: { evidences: 1, mitigates: 1 },
  relationship_family_counts: { evidence: 1, validation: 1 },
  stats: {
    node_count: 3, edge_count: 2, layer_count: 2, concept_type_count: 3,
    relationship_type_count: 2, candidate_edge_count: 1, validation_issue_count: 1,
    ontology_candidate_count: 1, flow_count: 1, state_machine_count: 1, simulation_scenario_count: 1, limit: 200,
  },
  meta: {
    analysis: {
      flow_count: 1,
      state_machine_count: 1,
      simulation_scenario_count: 1,
      simulation_provider_required: true,
      provider_contract: 'Simulation outputs require provider_id or result_ref; no predictive metrics are generated by the core product.',
    },
  },
};

const fixtureObservationEvents: ObservationEvent[] = [
  {
    id: 'obs-import-1', namespace: 'qa-enterprise-map-fixture', event_type: 'ImportCompleted',
    subject_type: 'node', subject_id: 'evidence-1', occurred_at: '2026-06-02T10:00:00Z',
    actor: 'fixture-importer', value: true, evidence_refs: ['prov-evidence'], metadata: { import_id: 'fixture-import-1', profile_version: '1.0.0' },
  },
  {
    id: 'obs-candidate-1', namespace: 'qa-enterprise-map-fixture', event_type: 'OntologyCandidateCreated',
    subject_type: 'candidate', subject_id: 'evidence-1', occurred_at: '2026-06-02T10:15:00Z',
    actor: 'assistant', value: 'pending', evidence_refs: ['prov-evidence'], metadata: { profile_version: '1.0.0' },
  },
  {
    id: 'obs-validation-1', namespace: 'qa-enterprise-map-fixture', event_type: 'ValidationIssueRaised',
    subject_type: 'validation', subject_id: 'evidence-1', occurred_at: '2026-06-03T12:00:00Z',
    actor: 'validator', value: 'warning', evidence_refs: ['prov-evidence'], metadata: { profile_version: '1.0.0', code: 'needs_reviewer' },
  },
  {
    id: 'obs-risk-1', namespace: 'qa-enterprise-map-fixture', event_type: 'NodeApproved',
    subject_type: 'node', subject_id: 'risk-1', occurred_at: '2026-06-03T11:30:00Z',
    actor: 'risk-owner', value: 'approved', evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' },
  },
];

const fixtureTimeSeries: TimeSeries[] = [
  {
    id: 'series-evidence-events', namespace: 'qa-enterprise-map-fixture', subject_id: 'evidence-1',
    metric_id: 'event_count', unit: 'count', evidence_refs: ['prov-evidence'],
    points: [
      { timestamp: '2026-06-02T10:00:00Z', value: 1, metadata: { profile_version: '1.0.0' } },
      { timestamp: '2026-06-02T10:15:00Z', value: 2, metadata: { profile_version: '1.0.0' } },
      { timestamp: '2026-06-03T12:00:00Z', value: 3, metadata: { profile_version: '1.0.0' } },
    ],
    metadata: { storage_note: 'MVP inline fixture series, not production analytics.' },
    created_at: '2026-06-02T10:00:00Z', updated_at: '2026-06-03T12:00:00Z',
  },
  {
    id: 'series-evidence-validation', namespace: 'qa-enterprise-map-fixture', subject_id: 'evidence-1',
    metric_id: 'validation_count', unit: 'count', evidence_refs: ['prov-evidence'],
    points: [{ timestamp: '2026-06-03T12:00:00Z', value: 1, metadata: { profile_version: '1.0.0' } }],
    metadata: { storage_note: 'MVP inline fixture series, not production analytics.' },
    created_at: '2026-06-03T12:00:00Z', updated_at: '2026-06-03T12:00:00Z',
  },
];

export default function EnterpriseMapFixturePanel() {
  return (
    <main className="h-full overflow-auto bg-[var(--color-background)] p-6" data-testid="enterprise-map-fixture-panel">
      <div className="mx-auto max-w-7xl">
        <div className="mb-4 rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: 'var(--color-text-muted)' }}>EPIC-004 QA Fixture</p>
          <h1 className="mt-2 text-2xl font-black" style={{ color: 'var(--color-text-main)' }}>Enterprise Map trust metadata fixture</h1>
          <p className="mt-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Deterministic browser-test fixture for reviewed instances, candidate lifecycle styling, review-state filters, provenance refs, and external system links. This route does not call backend APIs.
          </p>
        </div>
        <EnterpriseMapPanel selectedNamespace="qa-enterprise-map-fixture" fixtureMap={fixtureMap} fixtureProfile={fixtureProfile} fixtureInitialSelectedId="evidence-1" fixtureObservationEvents={fixtureObservationEvents} fixtureTimeSeries={fixtureTimeSeries} />
      </div>
    </main>
  );
}

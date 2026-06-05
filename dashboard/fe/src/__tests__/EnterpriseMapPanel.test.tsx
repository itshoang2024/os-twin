import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import EnterpriseMapPanel from '@/components/knowledge/EnterpriseMapPanel';
import EnterpriseMapFixturePanel from '@/components/knowledge/ontology/EnterpriseMapFixturePanel';

const getNodeDetail = vi.fn();
const seedMock = vi.fn();

const observationState = vi.hoisted(() => ({
  events: [
    { id: 'event-import', namespace: 'demo', event_type: 'ImportCompleted', subject_type: 'node', subject_id: 'risk-1', occurred_at: '2026-06-01T00:00:00Z', actor: 'importer', value: true, evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
    { id: 'event-candidate', namespace: 'demo', event_type: 'OntologyCandidateCreated', subject_type: 'candidate', subject_id: 'risk-1', occurred_at: '2026-06-02T00:00:00Z', actor: 'assistant', value: 'pending', evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
    { id: 'event-validation', namespace: 'demo', event_type: 'ValidationIssueRaised', subject_type: 'validation', subject_id: 'risk-1', occurred_at: '2026-06-03T00:00:00Z', actor: 'validator', value: 'warning', evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
  ],
  series: [
    { id: 'series-risk-events', namespace: 'demo', subject_id: 'risk-1', metric_id: 'event_count', unit: 'count', evidence_refs: ['prov-risk'], points: [
      { timestamp: '2026-06-01T00:00:00Z', value: 1, metadata: { profile_version: '1.0.0' } },
      { timestamp: '2026-06-03T00:00:00Z', value: 3, metadata: { profile_version: '1.0.0' } },
    ], created_at: '2026-06-01T00:00:00Z', updated_at: '2026-06-03T00:00:00Z' },
  ],
  isLoading: false,
  error: null as string | null,
}));

const nodes = [
  { id: 'risk-1', label: 'Risk', name: 'Vendor outage risk', score: 1, concept_type: 'risk', concept_label: 'Risk', concept_color: '#123456', quality_state: 'watch', flow_refs: ['flow:evidence'], state: 'ready', state_machine_ref: 'state_machine:evidence', state_color: '#16a34a', simulation_state: 'provider_required', simulation_refs: ['simulation:closure'], event_count: 2, active_event_count: 1, time_range: { start: '2026-06-01T00:00:00Z', end: '2026-06-03T00:00:00Z' }, series_refs: ['risk-1:event_count'], layer_id: 'governance', layer_label: 'Governance', abstraction_level: 'control', abstraction_label: 'Control', pack_id: 'audit-risk-management', lifecycle_state: 'active', review_state: 'approved', confidence: 0.92, provenance_refs: ['prov-risk'], external_ref: { system: 'jira', id: 'RISK-1' }, owner: 'Risk', description: 'Third party outage', map_group: 'audit-risk-management', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Risk', purpose: 'Track outage exposure' }, properties: {} },
  { id: 'control-1', label: 'Control', name: 'Failover control', score: 1, concept_type: 'control', concept_label: 'Control', layer_id: 'governance', layer_label: 'Governance', abstraction_level: 'control', abstraction_label: 'Control', pack_id: 'audit-risk-management', lifecycle_state: 'active', owner: 'Risk', description: 'Failover procedure', map_group: 'audit-risk-management', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Risk', purpose: 'Mitigate outage' }, properties: {} },
  { id: 'evidence-1', label: 'Evidence', name: 'DR test evidence', score: 1, concept_type: 'evidence', concept_label: 'Evidence', layer_id: 'evidence', layer_label: 'Evidence', abstraction_level: 'record', abstraction_label: 'Record', pack_id: 'audit-risk-management', lifecycle_state: 'candidate', review_state: 'pending', owner: 'Audit', description: 'Last DR test', map_group: 'audit-risk-management', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Audit', purpose: 'Evidence control' }, properties: {}, validation_issues: [{ message: 'Needs reviewer' }] },
  { id: 'order-1', label: 'Order', name: 'Order 1001', score: 1, concept_type: 'order', concept_label: 'Order', layer_id: 'commerce', layer_label: 'Commerce', abstraction_level: 'transaction', abstraction_label: 'Transaction', pack_id: 'ecommerce-logistics', lifecycle_state: 'active', owner: 'Ops', description: 'Customer order', map_group: 'ecommerce-logistics', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Ops', purpose: 'Fulfill order' }, properties: {} },
  { id: 'shipment-1', label: 'Shipment', name: 'Shipment 1001', score: 1, concept_type: 'shipment', concept_label: 'Shipment', layer_id: 'fulfillment', layer_label: 'Fulfillment', abstraction_level: 'transaction', abstraction_label: 'Transaction', pack_id: 'ecommerce-logistics', lifecycle_state: 'active', owner: 'Ops', description: 'Carrier movement', map_group: 'ecommerce-logistics', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Ops', purpose: 'Ship order' }, properties: {} },
  { id: 'integration-1', label: 'Integration', name: 'Carrier API', score: 1, concept_type: 'integration', concept_label: 'Integration', layer_id: 'platform', layer_label: 'Platform', abstraction_level: 'system', abstraction_label: 'System', pack_id: 'ecommerce-logistics', lifecycle_state: 'active', owner: 'Platform', description: 'Carrier sync', map_group: 'ecommerce-logistics', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Platform', purpose: 'Sync carriers' }, properties: {} },
];

const edges = [
  { source: 'order-1', target: 'shipment-1', map_source: 'shipment-1', map_target: 'order-1', label: 'depends_on', relationship_type: 'depends_on', family: 'dependency', weight: .9, inverse_label: 'Enables', style: 'dashed' },
  { source: 'shipment-1', target: 'integration-1', map_source: 'shipment-1', map_target: 'integration-1', label: 'consumes', relationship_type: 'consumes', family: 'flow', weight: .8, style: 'bold' },
  { source: 'evidence-1', target: 'control-1', map_source: 'evidence-1', map_target: 'control-1', label: 'evidences', relationship_type: 'evidences', family: 'evidence', weight: .7, style: 'dotted' },
  { source: 'control-1', target: 'risk-1', map_source: 'control-1', map_target: 'risk-1', label: 'mitigates', relationship_type: 'mitigates', family: 'validation', weight: .7, style: 'bold', review_state: 'approved', confidence: 0.88, provenance_refs: ['prov-edge'], external_ref: { system: 'gRC', id: 'CTRL-1' } },
  { source: 'integration-1', target: 'shipment-1', map_source: 'integration-1', map_target: 'shipment-1', label: 'implements', relationship_type: 'implements', family: 'traceability', weight: .7, style: 'solid' },
  { source: 'integration-1', target: 'shipment-1', map_source: 'integration-1', map_target: 'shipment-1', label: 'syncs_with', relationship_type: 'syncs_with', family: 'integration', weight: .7, style: 'dashed' },
];

vi.mock('@/hooks/use-knowledge-explorer', () => ({
  useEnterpriseMap: () => ({
    map: {
      nodes,
      edges,
      layers: [
        { id: 'governance', label: 'Governance', order: 1, count: 2 },
        { id: 'evidence', label: 'Evidence', order: 2, count: 1 },
        { id: 'commerce', label: 'Commerce', order: 3, count: 1 },
        { id: 'fulfillment', label: 'Fulfillment', order: 4, count: 1 },
        { id: 'platform', label: 'Platform', order: 5, count: 1 },
      ],
      abstraction_levels: [{ id: 'control', label: 'Control', order: 1 }, { id: 'transaction', label: 'Transaction', order: 2 }, { id: 'system', label: 'System', order: 3 }],
      concept_type_counts: { risk: 1, control: 1, evidence: 1, order: 1, shipment: 1, integration: 1 },
      relationship_type_counts: { depends_on: 1, consumes: 1, evidences: 1, mitigates: 1, implements: 1, syncs_with: 1 },
      relationship_family_counts: { dependency: 1, flow: 1, evidence: 1, validation: 1, traceability: 1, integration: 1 },
      stats: { node_count: 6, edge_count: 6, layer_count: 5, concept_type_count: 6, relationship_type_count: 6, candidate_edge_count: 0, validation_issue_count: 1, ontology_candidate_count: 1, flow_count: 1, state_machine_count: 1, simulation_scenario_count: 1, limit: 200 },
      meta: { analysis: { flow_count: 1, state_machine_count: 1, simulation_scenario_count: 1, simulation_provider_required: true, provider_contract: 'Simulation outputs require provider_id or result_ref; no predictive metrics are generated by the core product.' } },
    },
    isLoading: false,
    error: null,
  }),
  useKnowledgeExplorer: () => ({ nodes, edges, isSeeded: false, seed: seedMock, getNodeDetail }),
}));

vi.mock('@/hooks/use-ontology', () => ({
  useOntologyProfile: () => ({ profile: {
    profile_id: 'enterprise_feature_map', namespace: 'demo', version: '1.0.0', status: 'active',
    concept_types: { risk: { id: 'risk', label: 'Risk', color: '#be123c' }, control: { id: 'control', label: 'Control', color: '#2563eb' }, evidence: { id: 'evidence', label: 'Evidence', color: '#d97706' }, order: { id: 'order', label: 'Order', color: '#059669' }, shipment: { id: 'shipment', label: 'Shipment', color: '#0f766e' }, integration: { id: 'integration', label: 'Integration', color: '#7c3aed' } },
    relationship_types: { depends_on: { id: 'depends_on', label: 'Depends on', family: 'dependency', map_direction: 'reversed' }, consumes: { id: 'consumes', label: 'Consumes', family: 'flow' }, evidences: { id: 'evidences', label: 'Evidences', family: 'evidence' }, mitigates: { id: 'mitigates', label: 'Mitigates', family: 'validation' }, implements: { id: 'implements', label: 'Implements', family: 'traceability' }, syncs_with: { id: 'syncs_with', label: 'Syncs with', family: 'integration' } },
    aliases: {}, concept_aliases: {}, layers: {}, abstraction_levels: {}, metadata_fields: {}, validation_rules: [],
  } }),
  useOntologyPacks: () => ({ installed: { installed_packs: { 'audit-risk-management': {}, 'ecommerce-logistics': {} } } }),
  useOntologyCandidates: () => ({ candidates: [{ id: 'cand', status: 'pending' }] }),
  useOntologyObservation: (_namespace: string | null, subjectId?: string | null) => ({
    events: observationState.events.filter((event) => !subjectId || event.subject_id === subjectId),
    series: observationState.series.filter((item) => !subjectId || item.subject_id === subjectId),
    isLoading: observationState.isLoading,
    error: observationState.error,
    refresh: vi.fn(),
  }),
}));

describe('EnterpriseMapPanel', () => {
  beforeEach(() => {
    getNodeDetail.mockResolvedValue({ node: null, edges: [], stats: {} });
    seedMock.mockClear();
    observationState.events = [
      { id: 'event-import', namespace: 'demo', event_type: 'ImportCompleted', subject_type: 'node', subject_id: 'risk-1', occurred_at: '2026-06-01T00:00:00Z', actor: 'importer', value: true, evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
      { id: 'event-candidate', namespace: 'demo', event_type: 'OntologyCandidateCreated', subject_type: 'candidate', subject_id: 'risk-1', occurred_at: '2026-06-02T00:00:00Z', actor: 'assistant', value: 'pending', evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
      { id: 'event-validation', namespace: 'demo', event_type: 'ValidationIssueRaised', subject_type: 'validation', subject_id: 'risk-1', occurred_at: '2026-06-03T00:00:00Z', actor: 'validator', value: 'warning', evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
    ];
    observationState.series = [
      { id: 'series-risk-events', namespace: 'demo', subject_id: 'risk-1', metric_id: 'event_count', unit: 'count', evidence_refs: ['prov-risk'], points: [
        { timestamp: '2026-06-01T00:00:00Z', value: 1, metadata: { profile_version: '1.0.0' } },
        { timestamp: '2026-06-03T00:00:00Z', value: 3, metadata: { profile_version: '1.0.0' } },
      ], created_at: '2026-06-01T00:00:00Z', updated_at: '2026-06-03T00:00:00Z' },
    ];
    observationState.isLoading = false;
    observationState.error = null;
  });


  it('renders the empty map truth state without auto-seeding demo data', () => {
    const emptyMap = {
      nodes: [],
      edges: [],
      layers: [],
      abstraction_levels: [],
      concept_type_counts: {},
      relationship_type_counts: {},
      relationship_family_counts: {},
      stats: { node_count: 0, edge_count: 0, layer_count: 0, concept_type_count: 0, relationship_type_count: 0, candidate_edge_count: 0, validation_issue_count: 0, ontology_candidate_count: 2 },
    };
    const onImportData = vi.fn();
    const onApproveCandidates = vi.fn();
    const onCreateSampleData = vi.fn();

    render(<EnterpriseMapPanel selectedNamespace="empty-ns" fixtureMap={emptyMap} onImportData={onImportData} onApproveCandidates={onApproveCandidates} onCreateSampleData={onCreateSampleData} />);

    expect(screen.getByTestId('enterprise-map-empty-state')).toBeInTheDocument();
    expect(screen.getByText(/No graph objects yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('enterprise-map-example-banner')).not.toBeInTheDocument();
    expect(screen.queryByTestId('enterprise-map-graph')).not.toBeInTheDocument();
    expect(seedMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('enterprise-map-empty-import'));
    fireEvent.click(screen.getByTestId('enterprise-map-empty-approve'));
    fireEvent.click(screen.getByTestId('enterprise-map-empty-sample'));
    expect(onImportData).toHaveBeenCalledTimes(1);
    expect(onApproveCandidates).toHaveBeenCalledTimes(1);
    expect(onCreateSampleData).toHaveBeenCalledTimes(1);
  });

  it('renders labeled example data when only fallback examples exist', () => {
    const emptyLiveMap = {
      nodes: [],
      edges: [],
      layers: [],
      abstraction_levels: [],
      concept_type_counts: {},
      relationship_type_counts: {},
      relationship_family_counts: {},
      stats: { node_count: 0, edge_count: 0, layer_count: 0, concept_type_count: 0, relationship_type_count: 0, candidate_edge_count: 0, validation_issue_count: 0, ontology_candidate_count: 0 },
    };
    const exampleMap = {
      ...emptyLiveMap,
      nodes: [{ ...nodes[0], id: 'example-risk', name: 'Example vendor risk', review_state: 'example', provenance_refs: [] }],
      layers: [{ id: 'governance', label: 'Governance', order: 1, count: 1 }],
      concept_type_counts: { risk: 1 },
      stats: { ...emptyLiveMap.stats, node_count: 1, layer_count: 1, concept_type_count: 1 },
    };

    render(<EnterpriseMapPanel selectedNamespace="example-ns" fixtureMap={emptyLiveMap} fallbackMap={exampleMap} />);

    expect(screen.getByTestId('enterprise-map-example-banner')).toHaveTextContent('[Example Data]');
    expect(screen.queryByTestId('enterprise-map-empty-state')).not.toBeInTheDocument();
    expect(screen.getByTestId('enterprise-node-example-risk')).toBeInTheDocument();
  });

  it('syncs externally selected map instances for lens switch preservation', async () => {
    const { rerender } = render(<EnterpriseMapPanel selectedNamespace="demo" selectedInstanceId="risk-1" />);
    const detail = await waitFor(() => screen.getByRole('dialog', { name: /detail drawer/i }));
    expect(within(detail).getByText(/Vendor outage risk/i)).toBeInTheDocument();

    rerender(<EnterpriseMapPanel selectedNamespace="demo" selectedInstanceId="control-1" />);
    const updatedDetail = await waitFor(() => screen.getByRole('dialog', { name: /detail drawer/i }));
    expect(within(updatedDetail).getByText(/Failover control/i)).toBeInTheDocument();
  });

  it('renders audit-risk and ecommerce fixtures with all required relationship families', () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    expect(screen.getByText('Enterprise Ontology Map')).toBeInTheDocument();
    expect(screen.getByTestId('edge-depends_on')).toBeInTheDocument();
    expect(screen.getByTestId('edge-consumes')).toBeInTheDocument();
    expect(screen.getByTestId('edge-evidences')).toBeInTheDocument();
    expect(screen.getByTestId('edge-mitigates')).toBeInTheDocument();
    expect(screen.getByTestId('edge-implements')).toBeInTheDocument();
    expect(screen.getByTestId('edge-syncs_with')).toBeInTheDocument();
    expect(screen.getByLabelText(/audit risk management/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/ecommerce logistics/i)).toBeInTheDocument();
  });


  it('renders saved flow and state overlays plus honest simulation rail', async () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    expect(screen.getByTestId('analysis-overlay')).toBeInTheDocument();
    expect(screen.getByText(/Flow \/ state overlays/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Simulation/i }));
    expect(screen.getByTestId('simulation-rail')).toBeInTheDocument();
    expect(screen.getAllByText(/Provider required/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/does not generate predictions or fake metrics/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Inspect graph object/i }));
    const detail = await waitFor(() => screen.getByRole('dialog', { name: /detail drawer/i }));
    expect(within(detail).getByText(/flow refs/i)).toBeInTheDocument();
    expect(within(detail).getByText(/state: ready/i)).toBeInTheDocument();
    expect(within(detail).getByText(/simulation: provider required/i)).toBeInTheDocument();
  });

  it('supports accessible graph node selection and relationship chips', async () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /Select Vendor outage risk/i }));
    const detail = await waitFor(() => screen.getByRole('dialog', { name: /detail drawer/i }));
    expect(within(detail).getByText(/Vendor outage risk/i)).toBeInTheDocument();
    expect(within(detail).getByRole('button', { name: /Mitigates: Failover control/i })).toBeInTheDocument();
    expect(within(detail).getByText(/approved · source-backed · gRC:CTRL-1/i)).toBeInTheDocument();
    expect(within(detail).getAllByText(/source-backed/i).length).toBeGreaterThan(0);
  });

  it('focuses the evidence candidate detail when its graph hit target is selected', async () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /Select DR test evidence/i }));
    const detail = await waitFor(() => screen.getByRole('dialog', { name: /detail drawer/i }));
    expect(within(detail).getByRole('heading', { name: /evidence-1 - DR test evidence/i })).toBeInTheDocument();
    expect(within(detail).getByText(/unverified candidate instance/i)).toBeInTheDocument();
    expect(within(detail).getByText(/review: pending/i)).toBeInTheDocument();
    expect(within(detail).getByText(/Needs reviewer/i)).toBeInTheDocument();
  });

  it('exposes large graph safeguards and quality state filtering', () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    expect(screen.getByTestId('enterprise-map-safeguards')).toBeInTheDocument();
    expect(screen.getByLabelText(/Density/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Page size/i)).toBeInTheDocument();
    expect(screen.getByText(/Quality state/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Review state/i).length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/Pending/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Needs Review/i)).toBeInTheDocument();
  });


  it('prefers projected visual fields and degrades when optional fields are absent', () => {
    const { container } = render(<EnterpriseMapPanel selectedNamespace="demo" />);
    const riskNode = screen.getByTestId('enterprise-node-risk-1');
    expect(riskNode.querySelector('rect')).toHaveAttribute('stroke', '#123456');
    expect(screen.getByLabelText(/Watch/i)).toBeInTheDocument();
    expect(screen.getByTestId('enterprise-node-evidence-1').querySelector('rect')).toHaveAttribute('stroke-dasharray', '2 3');
    expect(screen.getByTestId('enterprise-node-evidence-1')).toHaveClass('candidate-instance');
    expect(screen.getAllByText('Vendor outage risk').length).toBeGreaterThan(0);
    expect(container.querySelector('[data-testid="edge-depends_on"]')).toBeInTheDocument();
  });

  it('updates visible time selection mode and filters real observation data', () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /Select Vendor outage risk/i }));

    fireEvent.click(screen.getByTestId('time-mode-latest_import'));
    expect(screen.getByTestId('time-mode-latest_import')).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByTestId('series-time-panel')).getByText('latest import')).toBeInTheDocument();
    expect(within(screen.getByTestId('series-time-panel')).getByText(/Import Completed/i)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('time-mode-current_profile_version'));
    expect(screen.getByTestId('time-mode-current_profile_version')).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByTestId('series-time-panel')).getByText('current profile version')).toBeInTheDocument();
  });


  it('shows selected-window metric counts instead of all-time projection counts', () => {
    observationState.events = [
      { id: 'event-approved', namespace: 'demo', event_type: 'NodeApproved', subject_type: 'node', subject_id: 'risk-1', occurred_at: '2026-06-03T00:00:00Z', actor: 'reviewer', value: 'approved', evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
    ];
    observationState.series = [];
    const { container } = render(<EnterpriseMapPanel selectedNamespace="demo" />);

    fireEvent.click(screen.getByRole('button', { name: /Select Vendor outage risk/i }));
    fireEvent.click(screen.getByTestId('time-mode-latest_import'));

    const panel = screen.getByTestId('series-time-panel');
    expect(within(panel).getByText('latest import')).toBeInTheDocument();
    expect(within(panel).getByText(/No observation events recorded for this object/i)).toBeInTheDocument();
    const eventMetric = Array.from(container.querySelectorAll('.emp-metric-card')).find((card) => card.textContent?.startsWith('Events'));
    expect(eventMetric).toHaveTextContent('Events0latest import window');
  });

  it('renders Series/Time empty, loading, error, and populated states honestly', () => {
    observationState.events = [];
    observationState.series = [];
    const { rerender } = render(<EnterpriseMapPanel selectedNamespace="demo" />);
    expect(within(screen.getByTestId('series-time-panel')).getByText(/No object selected/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Select Failover control/i }));
    expect(within(screen.getByTestId('series-time-panel')).getByText(/No time-series records/i)).toBeInTheDocument();
    expect(within(screen.getByTestId('series-time-panel')).getByText(/No observation events recorded/i)).toBeInTheDocument();

    observationState.isLoading = true;
    rerender(<EnterpriseMapPanel selectedNamespace="demo" />);
    expect(within(screen.getByTestId('series-time-panel')).getByText(/Loading observation signals/i)).toBeInTheDocument();

    observationState.isLoading = false;
    observationState.error = 'boom';
    rerender(<EnterpriseMapPanel selectedNamespace="demo" />);
    expect(within(screen.getByTestId('series-time-panel')).getByText(/Could not load observation data: boom/i)).toBeInTheDocument();

    observationState.error = null;
    observationState.events = [
      { id: 'event-validation', namespace: 'demo', event_type: 'ValidationIssueRaised', subject_type: 'validation', subject_id: 'risk-1', occurred_at: '2026-06-03T00:00:00Z', actor: 'validator', value: 'warning', evidence_refs: ['prov-risk'], metadata: { profile_version: '1.0.0' } },
    ];
    observationState.series = [
      { id: 'series-risk-events', namespace: 'demo', subject_id: 'risk-1', metric_id: 'event_count', unit: 'count', evidence_refs: ['prov-risk'], points: [{ timestamp: '2026-06-03T00:00:00Z', value: 1, metadata: { profile_version: '1.0.0' } }], created_at: '2026-06-03T00:00:00Z', updated_at: '2026-06-03T00:00:00Z' },
    ];
    rerender(<EnterpriseMapPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /Select Vendor outage risk/i }));
    expect(within(screen.getByTestId('series-time-panel')).getByText(/event_count \(1 pts\)/i)).toBeInTheDocument();
    expect(within(screen.getByTestId('series-time-panel')).getByText(/Validation Issue Raised/i)).toBeInTheDocument();
  });

  it('renders the deterministic browser QA fixture without backend namespace data', () => {
    render(<EnterpriseMapFixturePanel />);
    expect(screen.getByTestId('enterprise-map-fixture-panel')).toBeInTheDocument();
    expect(screen.getByText('Enterprise Map trust metadata fixture')).toBeInTheDocument();
    expect(screen.getByTestId('enterprise-map-panel')).toBeInTheDocument();
    expect(screen.getByTestId('enterprise-node-evidence-1')).toHaveClass('candidate-instance');
    expect(screen.getAllByText(/Review state/i).length).toBeGreaterThan(0);
    expect(within(screen.getByTestId('series-time-panel')).getByText(/event_count \(3 pts\)/i)).toBeInTheDocument();
    expect(within(screen.getByTestId('series-time-panel')).getByText(/Validation Issue Raised/i)).toBeInTheDocument();
  });

});

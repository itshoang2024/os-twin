import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import EnterpriseMapPanel from '@/components/knowledge/EnterpriseMapPanel';

const getNodeDetail = vi.fn();

const nodes = [
  { id: 'risk-1', label: 'Risk', name: 'Vendor outage risk', score: 1, concept_type: 'risk', concept_label: 'Risk', layer_id: 'governance', layer_label: 'Governance', abstraction_level: 'control', abstraction_label: 'Control', pack_id: 'audit-risk-management', lifecycle_state: 'active', owner: 'Risk', description: 'Third party outage', map_group: 'audit-risk-management', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Risk', purpose: 'Track outage exposure' }, properties: {} },
  { id: 'control-1', label: 'Control', name: 'Failover control', score: 1, concept_type: 'control', concept_label: 'Control', layer_id: 'governance', layer_label: 'Governance', abstraction_level: 'control', abstraction_label: 'Control', pack_id: 'audit-risk-management', lifecycle_state: 'active', owner: 'Risk', description: 'Failover procedure', map_group: 'audit-risk-management', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Risk', purpose: 'Mitigate outage' }, properties: {} },
  { id: 'evidence-1', label: 'Evidence', name: 'DR test evidence', score: 1, concept_type: 'evidence', concept_label: 'Evidence', layer_id: 'evidence', layer_label: 'Evidence', abstraction_level: 'record', abstraction_label: 'Record', pack_id: 'audit-risk-management', lifecycle_state: 'draft', owner: 'Audit', description: 'Last DR test', map_group: 'audit-risk-management', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Audit', purpose: 'Evidence control' }, properties: {}, validation_issues: [{ message: 'Needs reviewer' }] },
  { id: 'order-1', label: 'Order', name: 'Order 1001', score: 1, concept_type: 'order', concept_label: 'Order', layer_id: 'commerce', layer_label: 'Commerce', abstraction_level: 'transaction', abstraction_label: 'Transaction', pack_id: 'ecommerce-logistics', lifecycle_state: 'active', owner: 'Ops', description: 'Customer order', map_group: 'ecommerce-logistics', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Ops', purpose: 'Fulfill order' }, properties: {} },
  { id: 'shipment-1', label: 'Shipment', name: 'Shipment 1001', score: 1, concept_type: 'shipment', concept_label: 'Shipment', layer_id: 'fulfillment', layer_label: 'Fulfillment', abstraction_level: 'transaction', abstraction_label: 'Transaction', pack_id: 'ecommerce-logistics', lifecycle_state: 'active', owner: 'Ops', description: 'Carrier movement', map_group: 'ecommerce-logistics', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Ops', purpose: 'Ship order' }, properties: {} },
  { id: 'integration-1', label: 'Integration', name: 'Carrier API', score: 1, concept_type: 'integration', concept_label: 'Integration', layer_id: 'platform', layer_label: 'Platform', abstraction_level: 'system', abstraction_label: 'System', pack_id: 'ecommerce-logistics', lifecycle_state: 'active', owner: 'Platform', description: 'Carrier sync', map_group: 'ecommerce-logistics', data_store: 'knowledge_graph', sync_mode: 'sync', metadata: { owner: 'Platform', purpose: 'Sync carriers' }, properties: {} },
];

const edges = [
  { source: 'order-1', target: 'shipment-1', map_source: 'shipment-1', map_target: 'order-1', label: 'depends_on', relationship_type: 'depends_on', family: 'dependency', weight: .9, inverse_label: 'Enables', style: 'dashed' },
  { source: 'shipment-1', target: 'integration-1', map_source: 'shipment-1', map_target: 'integration-1', label: 'consumes', relationship_type: 'consumes', family: 'flow', weight: .8, style: 'bold' },
  { source: 'evidence-1', target: 'control-1', map_source: 'evidence-1', map_target: 'control-1', label: 'evidences', relationship_type: 'evidences', family: 'evidence', weight: .7, style: 'dotted' },
  { source: 'control-1', target: 'risk-1', map_source: 'control-1', map_target: 'risk-1', label: 'mitigates', relationship_type: 'mitigates', family: 'validation', weight: .7, style: 'bold' },
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
      stats: { node_count: 6, edge_count: 6, layer_count: 5, concept_type_count: 6, relationship_type_count: 6, candidate_edge_count: 0, validation_issue_count: 1, ontology_candidate_count: 1, limit: 200 },
    },
    isLoading: false,
    error: null,
  }),
  useKnowledgeExplorer: () => ({ nodes, edges, isSeeded: true, seed: vi.fn(), getNodeDetail }),
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
}));

describe('EnterpriseMapPanel', () => {
  beforeEach(() => {
    getNodeDetail.mockResolvedValue({ node: null, edges: [], stats: {} });
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

  it('supports keyboard graph node selection and relationship chips', async () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    const node = screen.getByTestId('enterprise-node-risk-1');
    expect(node).toHaveAttribute('tabindex', '0');
    fireEvent.keyDown(node, { key: 'Enter' });
    const detail = await waitFor(() => screen.getByRole('dialog', { name: /detail drawer/i }));
    expect(within(detail).getByText(/Vendor outage risk/i)).toBeInTheDocument();
    expect(within(detail).getByRole('button', { name: /Mitigates: Failover control/i })).toBeInTheDocument();
  });

  it('exposes large graph safeguards and quality state filtering', () => {
    render(<EnterpriseMapPanel selectedNamespace="demo" />);
    expect(screen.getByTestId('enterprise-map-safeguards')).toBeInTheDocument();
    expect(screen.getByLabelText(/Density/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Page size/i)).toBeInTheDocument();
    expect(screen.getByText(/Quality state/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Needs Review/i)).toBeInTheDocument();
  });
});

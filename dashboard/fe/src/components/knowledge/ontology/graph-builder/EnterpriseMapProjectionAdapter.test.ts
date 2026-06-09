import { describe, expect, it } from 'vitest';
import { EnterpriseMapProjectionAdapter } from './EnterpriseMapProjectionAdapter';
import { getProjectionFixture } from './mock-fixtures';
import type { EnterpriseMapProjectionResponse } from './types';

describe('EnterpriseMapProjectionAdapter', () => {
  it('maps IDs, labels, badges, permissions, validation, provenance, and style metadata', () => {
    const projection = getProjectionFixture('basic', 'qa-namespace');
    const view = EnterpriseMapProjectionAdapter.toCanvasViewModel(projection);

    expect(view.meta.source).toBe('adapter');
    expect(view.nodes[0]).toMatchObject({
      id: 'object.customer',
      label: 'Customer Account',
      typeLabel: 'Customer',
      permissions: { level: 'read', allowedActions: ['view', 'search'] },
      validation: { count: 0, issues: [] },
      provenance: { refs: ['doc://crm/schema#customer'] },
      style: { color: '#2563eb', shape: 'rounded', opacity: 1 },
    });
    expect(view.nodes[0].badges).toContain('Customer');
    expect(view.nodes[0].badges).toContain('Semantic');
    expect(view.edges[0]).toMatchObject({
      id: 'rel.customer-policy',
      source: 'object.customer',
      target: 'object.policy',
      label: 'owns policy',
      permissions: { level: 'read', allowedActions: ['view'] },
      provenance: { refs: ['doc://crm/schema#customer_policy'] },
      style: { color: '#64748b', weight: 2, opacity: 1 },
    });
  });

  it('redacts properties and emits redacted badges/style', () => {
    const projection: EnterpriseMapProjectionResponse = {
      ...getProjectionFixture('redacted', 'qa-namespace'),
      nodes: [{
        id: 'sensitive-node',
        label: 'Sensitive Node',
        redacted: true,
        concept_label: 'Secret',
        properties: { ssn: '123-45-6789', token: 'secret-token' },
        permissions: { level: 'limited', reason: 'Hidden', allowed_actions: ['view_topology'] },
        validation_issues: ['Hidden issue'],
        provenance_refs: ['redacted://ref'],
      }],
      edges: [],
    };

    const view = EnterpriseMapProjectionAdapter.toCanvasViewModel(projection);
    expect(view.nodes[0].properties).toEqual({});
    expect(view.nodes[0].redacted).toBe(true);
    expect(view.nodes[0].badges).toContain('Redacted');
    expect(view.nodes[0].permissions.level).toBe('limited');
    expect(view.nodes[0].validation.issues).toEqual(['Hidden issue']);
    expect(view.nodes[0].provenance.refs).toEqual(['redacted://ref']);
    expect(view.nodes[0].style.opacity).toBeLessThan(1);
  });

  it('drops edges that reference missing nodes and creates deterministic layout', () => {
    const projection: EnterpriseMapProjectionResponse = {
      ...getProjectionFixture('basic', 'qa-namespace'),
      edges: [{ id: 'bad-edge', source: 'missing', target: 'object.customer', label: 'bad' }],
    };
    const view = EnterpriseMapProjectionAdapter.toCanvasViewModel(projection);
    expect(view.edges).toEqual([]);
    expect(view.nodes.map((node) => [node.x, node.y])).toEqual([[96, 96], [286, 96], [476, 96]]);
  });

  it('merges expand projections by stable node and edge IDs without duplicates', () => {
    const base = EnterpriseMapProjectionAdapter.toCanvasViewModel(getProjectionFixture('basic', 'qa-namespace'));
    const sourceProjection = getProjectionFixture('basic', 'qa-namespace');
    const incoming = EnterpriseMapProjectionAdapter.toCanvasViewModel({
      ...sourceProjection,
      nodes: [
        sourceProjection.nodes[0],
        { id: 'object.agent-session', label: 'Agent Session', concept_label: 'Agent Session', properties: {}, validation_issues: [], provenance_refs: [] },
      ],
      edges: [{ id: 'rel.customer-agent-session', source: 'object.customer', target: 'object.agent-session', label: 'observed in', weight: 1, properties: {}, validation_issues: [], provenance_refs: [] }],
    });

    const merged = EnterpriseMapProjectionAdapter.mergeViewModels(base, incoming);
    expect(merged.nodes.map((node) => node.id)).toEqual(['object.customer', 'object.policy', 'object.claim', 'object.agent-session']);
    expect(merged.edges.map((edge) => edge.id)).toContain('rel.customer-agent-session');
    expect(merged.stats.node_count).toBe(4);
  });
});

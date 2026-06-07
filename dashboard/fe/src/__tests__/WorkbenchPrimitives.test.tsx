import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, vi, afterEach } from 'vitest';
import GraphCanvas from '@/components/knowledge/workbench/GraphCanvas';
import HistogramPanel from '@/components/knowledge/workbench/HistogramPanel';
import LayersStylingPanel from '@/components/knowledge/workbench/LayersStylingPanel';
import { mapLensAdapter, specLensAdapter } from '@/components/knowledge/workbench';
import { layout } from '@/components/knowledge/workbench/layout/engine';
import type { EnterpriseMapProjectionData } from '@/hooks/use-knowledge-explorer';
import type { LayoutMode, WorkbenchModel } from '@/components/knowledge/workbench/model/workbenchModel';

afterEach(() => cleanup());

const nodes = [
  { id: 'a', label: 'Alpha', type: 'risk', layerId: 'governance', subtitle: 'Risk object', badges: ['active'], color: '#2563eb' },
  { id: 'b', label: 'Beta', type: 'control', layerId: 'governance', subtitle: 'Control object', color: '#16a34a' },
  { id: 'c', label: 'Gamma', type: 'evidence', layerId: 'evidence', color: '#d97706' },
];
const edges = [{ id: 'a-b', source: 'a', target: 'b', label: 'mitigates', style: 'dashed' }];
const model: WorkbenchModel = { id: 'test', title: 'Workbench test', nodes, edges };

describe('workbench layout engine', () => {
  it('returns deterministic positions for every supported mode', () => {
    const modes: LayoutMode[] = ['auto', 'hierarchy', 'grid', 'row', 'column', 'circular', 'radial', 'cluster', 'cartesian', 'layered'];
    for (const mode of modes) {
      const positions = layout(nodes, edges, mode, { width: 640, height: 480 });
      expect(Object.keys(positions).sort()).toEqual(['a', 'b', 'c']);
      expect(Number.isFinite(positions.a.x)).toBe(true);
      expect(Number.isFinite(positions.a.y)).toBe(true);
    }
  });
});

describe('GraphCanvas', () => {
  it('supports compact chips and extended cards', () => {
    render(<GraphCanvas model={model} renderMode="compact" layoutMode="grid" />);
    expect(screen.getByTestId('graph-canvas')).toHaveAttribute('data-render-mode', 'compact');
    expect(screen.queryByText('Risk object')).not.toBeInTheDocument();
    cleanup();

    render(<GraphCanvas model={model} renderMode="extended" layoutMode="grid" />);
    expect(screen.getByTestId('graph-canvas')).toHaveAttribute('data-render-mode', 'extended');
    expect(screen.getByText('Risk object')).toBeInTheDocument();
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('renders map-grade node card metadata, validation, and event badges', () => {
    const cardModel: WorkbenchModel = { id: 'flight', title: 'Flight map', nodes: [{ id: 'flight-1', label: 'AA 101', type: 'flight', subtitle: 'Departure JFK · Arrival LAX', color: '#123456', lifecycleState: 'active', reviewState: 'approved', qualityState: 'watch', eventCount: 1, validationIssueCount: 1, properties: { delayed: true } }], edges: [] };
    render(<GraphCanvas model={cardModel} renderMode="extended" layoutMode="grid" />);
    expect(screen.getByText('Departure JFK · Arrival LAX')).toBeInTheDocument();
    expect(screen.getByText('active')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-flight-1-event-count')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-flight-1-validation')).toBeInTheDocument();
    expect(screen.getByTestId('graph-node-flight-1').querySelector('rect')).toHaveAttribute('stroke', '#123456');
  });

  it('honors edge style, weight, color, and label pills', () => {
    const edgeModel: WorkbenchModel = { id: 'edges', title: 'Edges', nodes: [{ id: 'a', label: 'A', type: 'thing' }, { id: 'b', label: 'B', type: 'thing' }], edges: [{ id: 'a-b', source: 'a', target: 'b', label: 'Depends on', style: 'dotted', color: '#dc2626', weight: 2.4 }] };
    const { container } = render(<GraphCanvas model={edgeModel} renderMode="extended" layoutMode="grid" />);
    const line = container.querySelector('[data-testid="graph-edge-a-b"] line');
    expect(line).toHaveAttribute('stroke', '#dc2626');
    expect(line).toHaveAttribute('stroke-dasharray', '2 4');
    expect(Number(line?.getAttribute('stroke-width'))).toBeGreaterThan(2);
    expect(screen.getByText('Depends on')).toBeInTheDocument();
  });

  it('recolors by property with a categorical legend', () => {
    render(<GraphCanvas model={{ ...model, nodes: nodes.map((node, index) => ({ ...node, properties: { delayed: index === 0 ? 'true' : 'false' } })) }} renderMode="extended" layoutMode="grid" colorBy="property" propertyName="delayed" />);
    expect(screen.getByTestId('graph-color-legend')).toHaveTextContent('true');
    expect(screen.getByTestId('graph-color-legend')).toHaveTextContent('false');
  });

});

describe('HistogramPanel', () => {
  it('drives generic filter-to and filter-out actions', () => {
    const onFilterTo = vi.fn();
    const onFilterOut = vi.fn();
    render(<HistogramPanel facets={[{ id: 'type', label: 'Type', buckets: [{ id: 'risk', label: 'Risk', count: 2 }] }]} onFilterTo={onFilterTo} onFilterOut={onFilterOut} />);

    fireEvent.click(screen.getByText('Filter to'));
    fireEvent.click(screen.getByText('Filter out'));

    expect(onFilterTo).toHaveBeenCalledWith('type', 'risk');
    expect(onFilterOut).toHaveBeenCalledWith('type', 'risk');
  });
});

describe('LayersStylingPanel', () => {
  it('supports fixed, object_type, property modes and boolean fallback swatches', () => {
    const onColorByChange = vi.fn();
    render(<LayersStylingPanel layers={[{ id: 'governance', label: 'Governance', count: 2 }]} colorBy="fixed" onColorByChange={onColorByChange} />);

    fireEvent.change(screen.getByLabelText('Color by'), { target: { value: 'object_type' } });
    fireEvent.change(screen.getByLabelText('Color by'), { target: { value: 'property' } });

    expect(onColorByChange).toHaveBeenCalledWith('object_type');
    expect(onColorByChange).toHaveBeenCalledWith('property');
    expect(screen.getByText('true')).toBeInTheDocument();
    expect(screen.getByText('false')).toBeInTheDocument();
    expect(screen.getByText('fallback')).toBeInTheDocument();
    expect(screen.getByText('Governance (2)')).toBeInTheDocument();
  });
});

describe('mapLensAdapter', () => {
  it('adapts enterprise map projection data to a lens-agnostic workbench model', () => {
    const projection: EnterpriseMapProjectionData = {
      nodes: [{ id: 'risk-1', name: 'Vendor risk', label: 'Risk', score: 1, properties: {}, concept_type: 'risk', concept_color: '#be123c', layer_id: 'governance', layer_label: 'Governance', lifecycle_state: 'active', review_state: 'approved', owner: 'Risk' }],
      edges: [{ source: 'risk-1', target: 'control-1', map_source: 'risk-1', map_target: 'control-1', label: 'mitigates', relationship_type: 'mitigates', weight: 0.7, style: 'dashed' }],
      layers: [{ id: 'governance', label: 'Governance', order: 1, count: 1 }],
      abstraction_levels: [],
      concept_type_counts: { risk: 1 },
      relationship_type_counts: { mitigates: 1 },
      relationship_family_counts: {},
      stats: { node_count: 1, edge_count: 1, layer_count: 1, concept_type_count: 1, relationship_type_count: 1, candidate_edge_count: 0, validation_issue_count: 0 },
    };
    const adapted = mapLensAdapter(projection, 'demo');

    expect(adapted.id).toBe('demo');
    expect(adapted.nodes[0]).toMatchObject({ id: 'risk-1', label: 'Vendor risk', type: 'risk', layerId: 'governance', lifecycleState: 'active', reviewState: 'approved' });
    expect(adapted.edges[0]).toMatchObject({ source: 'risk-1', target: 'control-1', type: 'mitigates', style: 'dashed' });
    expect(adapted.facets?.find((facet) => facet.id === 'object_type')?.buckets[0]).toMatchObject({ id: 'risk', count: 1 });
    expect(adapted.metadata?.mapState).toBe('live');
  });

  it('exposes empty map state as a single adapter discriminator', () => {
    const adapted = mapLensAdapter(null, 'empty-ns', 'empty');
    expect(adapted.subtitle).toBe('No graph objects yet');
    expect(adapted.metadata?.mapState).toBe('empty');
    expect(adapted.nodes).toEqual([]);
  });
});


describe('specLensAdapter', () => {
  it('projects schema type nodes and cardinality-labeled relationship edges only', () => {
    const adapted = specLensAdapter({
      profile_id: 'schema',
      namespace: 'demo',
      version: '1.0.0',
      concept_types: {
        account: { id: 'account', label: 'Account', abstraction_level: 'entity', default_layer: 'core', source_mappings: [{ source_id: 'crm', source_label: 'CRM' }] },
        owner: { id: 'owner', label: 'Owner', abstraction_level: 'entity', default_layer: 'core' },
      },
      relationship_types: {
        owns: { id: 'owns', label: 'Owns', family: 'ownership', allowed_source_types: ['owner'], allowed_target_types: ['account'], cardinality: 'one_to_many', style: 'bold' },
      },
      aliases: {},
      concept_aliases: {},
      layers: { core: { id: 'core', label: 'Core' } },
      abstraction_levels: { entity: { id: 'entity', label: 'Entity' } },
      metadata_fields: {},
      validation_rules: [],
      graph_instruction: { concept_type_defaults: { account: { concept_type: 'account', color: '#111827', shape: 'hexagon' } } },
    });

    expect(adapted.nodes.map((node) => node.kind)).toEqual(['concept', 'concept']);
    expect(adapted.edges[0]).toMatchObject({ source: 'owner', target: 'account', type: 'owns', style: 'bold' });
    expect(adapted.edges[0].label).toContain('One To Many');
    expect(adapted.nodes.find((node) => node.id === 'account')?.sources).toEqual(['CRM']);
    expect(adapted.metadata?.layout).toBe('hierarchy');
  });
});

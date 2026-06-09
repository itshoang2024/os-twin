import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { apiGet, apiPost } from '@/lib/api-client';
import {
  getProjectionFixture,
  mockErrorFixtures,
  mockExpandResponse,
  mockFilteredSearchResults,
  mockNodeDetails,
  mockProjectionFixtures,
  mockSearchNoResults,
  searchMockObjects,
} from './mock-fixtures';
import { expandOntologyNode, searchOntologyObjects, useOntologyGraphProjection, useOntologyNodeDetail } from './useOntologyGraphBuilderData';
import type { ApiErrorResponse, EnterpriseMapProjectionResponse, ExplorerSearchResponse } from './types';

vi.mock('@/lib/api-client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

const mockApiGet = apiGet as ReturnType<typeof vi.fn>;
const mockApiPost = apiPost as ReturnType<typeof vi.fn>;

const previousMode = process.env.NEXT_PUBLIC_ONTOLOGY_GRAPH_BUILDER_DATA_MODE;

function expectProjectionShape(projection: EnterpriseMapProjectionResponse) {
  expect(Array.isArray(projection.nodes)).toBe(true);
  expect(Array.isArray(projection.edges)).toBe(true);
  expect(projection.stats).toEqual(expect.objectContaining({
    source_node_count: expect.any(Number),
    source_edge_count: expect.any(Number),
    node_count: expect.any(Number),
    edge_count: expect.any(Number),
    ontology_candidate_count: expect.any(Number),
    validation_issue_count: expect.any(Number),
    truncated: expect.any(Boolean),
  }));
  expect(projection.meta).toEqual(expect.objectContaining({
    namespace: expect.any(String),
    map_state: expect.stringMatching(/^(live|empty)$/),
    map_source_kind: expect.stringMatching(/^(knowledge_graph|none)$/),
    applied_filters: expect.any(Object),
    applied_group_by: expect.any(Array),
    applied_color_by: expect.any(String),
    truncated: expect.any(Boolean),
  }));
}

function expectCanonicalError(error: ApiErrorResponse) {
  expect(error).toEqual(expect.objectContaining({
    error: expect.objectContaining({
      code: expect.any(String),
      message: expect.any(String),
    }),
  }));
  expect('meta' in error).toBe(false);
}

describe('Scenario 02 frontend contract alignment fixtures', () => {
  it('covers empty, populated, redacted, and capped projection responses', () => {
    expectProjectionShape(getProjectionFixture('empty', 'contract-ns'));
    expect(getProjectionFixture('empty', 'contract-ns')).toMatchObject({ nodes: [], edges: [], meta: { map_state: 'empty', map_source_kind: 'none' } });

    const populated = getProjectionFixture('basic', 'contract-ns');
    expectProjectionShape(populated);
    expect(populated.nodes.map((node) => node.id)).toEqual(['object.customer', 'object.policy', 'object.claim']);
    expect(populated.edges.map((edge) => `${edge.source}->${edge.target}`)).toEqual(['object.customer->object.policy', 'object.policy->object.claim']);

    const redacted = getProjectionFixture('redacted', 'contract-ns');
    expectProjectionShape(redacted);
    for (const node of redacted.nodes.filter((item) => item.redacted)) {
      expect(node.properties).toEqual({});
      expect(JSON.stringify(node)).not.toMatch(/ssn|token|secret-token|dateOfBirth/i);
    }
    for (const edge of redacted.edges.filter((item) => item.redacted)) {
      expect(edge.properties).toEqual({});
      expect(JSON.stringify(edge)).not.toMatch(/ssn|token|secret-token|dateOfBirth/i);
    }

    const capped = getProjectionFixture('large', 'contract-ns');
    expectProjectionShape(capped);
    expect(capped.meta.truncated).toBe(true);
    expect(capped.stats.truncated).toBe(true);
    expect(capped.meta.node_cap).toBeGreaterThan(0);
    expect(capped.meta.warnings?.length).toBeGreaterThan(0);
  });

  it('covers search no-results, filtered results, projection-shaped expand, invalid expand, and canonical errors', () => {
    const noResults: ExplorerSearchResponse = mockSearchNoResults;
    expect(noResults.results).toEqual([]);
    expect(noResults.meta).toMatchObject({ query: 'no-match', truncated: false, limit: 20 });

    const filtered: ExplorerSearchResponse = mockFilteredSearchResults;
    expect(filtered.results).toHaveLength(1);
    expect(filtered.meta.filters).toEqual({ object_type: ['Knowledge Object'] });

    expectProjectionShape(mockExpandResponse);
    expect(mockExpandResponse.edges[0]).toMatchObject({ source: 'object.customer', target: 'object.agent-session' });

    expectCanonicalError(mockErrorFixtures.invalidExpand);
    expect(mockErrorFixtures.invalidExpand.error.code).toBe('NOT_FOUND');
    expect(mockErrorFixtures.invalidExpand.error.validation_issues).toEqual(['node_id does not exist']);
    expectCanonicalError(mockErrorFixtures.projection);
  });

  it('keeps optional projection additions optional in mock fixtures', () => {
    const minimalProjection: EnterpriseMapProjectionResponse = {
      nodes: [{ id: 'object.minimal', label: 'Minimal Object' }],
      edges: [{ source: 'object.minimal', target: 'object.minimal', label: 'self' }],
      stats: {
        source_node_count: 1,
        source_edge_count: 1,
        node_count: 1,
        edge_count: 1,
        ontology_candidate_count: 0,
        validation_issue_count: 0,
        event_count: 0,
        active_event_count: 0,
        truncated: false,
      },
      meta: {
        namespace: 'contract-ns',
        map_state: 'live',
        map_source_kind: 'knowledge_graph',
        source_node_count: 1,
        source_edge_count: 1,
        applied_filters: {},
        applied_group_by: [],
        applied_color_by: 'concept_type',
        truncated: false,
      },
    };

    expectProjectionShape(minimalProjection);
  });
});

describe('Scenario 02 frontend contract alignment live API behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.NEXT_PUBLIC_ONTOLOGY_GRAPH_BUILDER_DATA_MODE = 'live';
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_ONTOLOGY_GRAPH_BUILDER_DATA_MODE = previousMode;
  });

  it('POSTs enterprise-map query to the Scenario 02 contract endpoint', async () => {
    mockApiPost.mockResolvedValueOnce(mockProjectionFixtures.empty);

    renderHook(() => useOntologyGraphProjection('contract-ns', 'empty'));

    await waitFor(() => expect(mockApiPost).toHaveBeenCalledWith(
      '/knowledge/namespaces/contract-ns/ontology/enterprise-map/query',
      { filters: {}, limit: null }
    ));
  });

  it('POSTs explorer search with query, filters, and limit', async () => {
    mockApiPost.mockResolvedValueOnce(searchMockObjects('namespace'));

    await searchOntologyObjects('contract-ns', 'namespace', { object_type: ['Knowledge Object'] }, 10);

    expect(mockApiPost).toHaveBeenCalledWith(
      '/knowledge/namespaces/contract-ns/explorer/search',
      { query: 'namespace', filters: { object_type: ['Knowledge Object'] }, limit: 10 }
    );
  });

  it('POSTs explorer expand with selected node IDs, filters, depth, and cap', async () => {
    mockApiPost.mockResolvedValueOnce(mockExpandResponse);

    await expandOntologyNode('contract-ns', 'object.customer', { badges: ['Customer'] }, 25);

    expect(mockApiPost).toHaveBeenCalledWith(
      '/knowledge/namespaces/contract-ns/explorer/expand',
      { node_ids: ['object.customer'], depth: 1, filters: { badges: { values: ['Customer'], mode: 'include' } }, node_cap: 25 }
    );
  });

  it('GETs normalized explorer node detail from the Scenario 02 endpoint', async () => {
    mockApiGet.mockResolvedValueOnce(mockNodeDetails['object.customer']);

    renderHook(() => useOntologyNodeDetail('contract-ns', 'object.customer'));

    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith(
      '/knowledge/namespaces/contract-ns/explorer/node/object.customer'
    ));
  });
});

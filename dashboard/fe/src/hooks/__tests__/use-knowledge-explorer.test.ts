/**
 * Unit tests for useKnowledgeExplorer hook.
 *
 * Tests the accumulated graph state, actions (seed, ignite, expand, search,
 * findPath, getNodeDetail), brightness computation, and reset behavior.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useKnowledgeExplorer, useKnowledgeExplorerSummary } from '../use-knowledge-explorer';
import type { ExplorerGraphData, ExplorerPathData, ExplorerNodeDetail } from '../use-knowledge-explorer';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// We mock the api-client module entirely so no real fetch calls happen
vi.mock('@/lib/api-client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

import { apiGet, apiPost } from '@/lib/api-client';

const mockApiGet = apiGet as ReturnType<typeof vi.fn>;
const mockApiPost = apiPost as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const NAMESPACE = 'test-ns';

function makeNode(id: string, label = 'entity', name?: string, score = 0.5): ExplorerGraphData['nodes'][0] {
  return {
    id,
    label,
    name: name ?? `Node ${id}`,
    score,
    properties: {},
  };
}

function makeEdge(source: string, target: string, label = 'RELATES', weight = 1): ExplorerGraphData['edges'][0] {
  return { source, target, label, weight, properties: {} };
}

function makeGraphData(
  nodes: ExplorerGraphData['nodes'],
  edges: ExplorerGraphData['edges'],
  overrides?: Partial<ExplorerGraphData['stats']>
): ExplorerGraphData {
  return {
    nodes,
    edges,
    stats: {
      node_count: nodes.length,
      edge_count: edges.length,
      ...overrides,
    },
  };
}

// ---------------------------------------------------------------------------
// Tests: useKnowledgeExplorerSummary
// ---------------------------------------------------------------------------

describe('useKnowledgeExplorerSummary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns null summary when namespace is null', () => {
    const { result } = renderHook(() => useKnowledgeExplorerSummary(null));
    expect(result.current.summary).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('starts loading when namespace is provided', () => {
    // SWR will attempt to fetch; we just test initial loading state
    const { result } = renderHook(() => useKnowledgeExplorerSummary(NAMESPACE));
    // With SWR, the initial state may be loading or data depending on cache
    // At minimum, summary should be null before fetch resolves
    expect(result.current.summary).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Tests: useKnowledgeExplorer
// ---------------------------------------------------------------------------

describe('useKnowledgeExplorer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- Initial state ----

  it('starts with empty graph state', () => {
    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    expect(result.current.nodes).toEqual([]);
    expect(result.current.edges).toEqual([]);
    expect(result.current.activeIgnitionPoints).toEqual([]);
    expect(result.current.selectedPath).toBeNull();
    expect(result.current.activeLens).toBe('community');
    expect(result.current.expansionDepth).toBe(1);
    expect(result.current.nodeBrightness.size).toBe(0);
    expect(result.current.isSeeding).toBe(false);
    expect(result.current.isExpanding).toBe(false);
    expect(result.current.isSearching).toBe(false);
    expect(result.current.isFindingPath).toBe(false);
    expect(result.current.isLoading).toBe(false);
  });

  it('starts with empty state when namespace is null', () => {
    const { result } = renderHook(() => useKnowledgeExplorer(null));

    expect(result.current.nodes).toEqual([]);
    expect(result.current.edges).toEqual([]);
    expect(result.current.isLoading).toBe(false);
  });

  // ---- Seed action ----

  it('seed loads initial graph and sets ignition points', async () => {
    const n1 = makeNode('n1', 'entity', 'Alpha', 0.9);
    const n2 = makeNode('n2', 'person', 'Beta', 0.7);
    const e1 = makeEdge('n1', 'n2', 'KNOWS', 1.5);
    const graphData = makeGraphData([n1, n2], [e1], { seed_count: 2 });

    mockApiGet.mockResolvedValueOnce(graphData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    expect(mockApiGet).toHaveBeenCalledWith(
      expect.stringContaining('/explorer/seed?top_k=50')
    );

    // Nodes and edges merged
    expect(result.current.nodes).toHaveLength(2);
    expect(result.current.edges).toHaveLength(1);

    // Ignition points set to seed node IDs (seed_count=2 means both n1 and n2)
    expect(result.current.activeIgnitionPoints).toContain('n1');
    expect(result.current.activeIgnitionPoints).toContain('n2');

    // Brightness computed: both ignition points = 1.0
    expect(result.current.nodeBrightness.get('n1')).toBe(1.0);
    expect(result.current.nodeBrightness.get('n2')).toBe(1.0);
  });

  it('seed with seed_count=1 only sets top node as ignition point', async () => {
    const n1 = makeNode('n1', 'entity', 'Alpha', 0.9);
    const n2 = makeNode('n2', 'person', 'Beta', 0.7);
    const e1 = makeEdge('n1', 'n2', 'KNOWS', 1.5);
    const graphData = makeGraphData([n1, n2], [e1], { seed_count: 1 });

    mockApiGet.mockResolvedValueOnce(graphData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    // Only n1 is ignition point (seed_count=1, slice(0,1) = [n1])
    expect(result.current.activeIgnitionPoints).toEqual(['n1']);
  });

  it('seed sets isSeeding flag during loading', async () => {
    let resolveSeed: (data: ExplorerGraphData) => void;
    const seedPromise = new Promise<ExplorerGraphData>(resolve => {
      resolveSeed = resolve;
    });
    mockApiGet.mockReturnValueOnce(seedPromise);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    act(() => {
      result.current.seed(50);
    });

    // During loading
    expect(result.current.isSeeding).toBe(true);
    expect(result.current.isLoading).toBe(true);

    // Resolve
    await act(async () => {
      resolveSeed!(makeGraphData([makeNode('n1')], []));
    });

    expect(result.current.isSeeding).toBe(false);
    expect(result.current.isLoading).toBe(false);
  });

  it('seed does nothing when namespace is null', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(null));

    await act(async () => {
      await result.current.seed(50);
    });

    expect(mockApiGet).not.toHaveBeenCalled();
  });

  // ---- Ignite action ----

  it('ignite expands from a node and adds it to ignition points', async () => {
    // First seed
    const n1 = makeNode('n1', 'entity', 'Alpha', 0.9);
    const seedData = makeGraphData([n1], [], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    // Now ignite n1
    const n3 = makeNode('n3', 'concept', 'Gamma', 0.6);
    const e2 = makeEdge('n1', 'n3', 'MENTIONS', 1.0);
    const expandData = makeGraphData([n3], [e2]);
    mockApiPost.mockResolvedValueOnce(expandData);

    await act(async () => {
      await result.current.ignite('n1');
    });

    expect(mockApiPost).toHaveBeenCalledWith(
      expect.stringContaining('/explorer/expand'),
      { node_ids: ['n1'], depth: 1 }
    );

    // New node merged in
    expect(result.current.nodes).toHaveLength(2);
    expect(result.current.edges).toHaveLength(1);

    // n1 added to ignition points
    expect(result.current.activeIgnitionPoints).toContain('n1');
  });

  // ---- Expand action ----

  it('expand merges new nodes from multiple root nodes', async () => {
    // Seed first
    const n1 = makeNode('n1');
    const seedData = makeGraphData([n1], [], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    expect(result.current.nodes).toHaveLength(1);

    // Expand
    const n2 = makeNode('n2');
    const n3 = makeNode('n3');
    const expandData = makeGraphData([n2, n3], [makeEdge('n1', 'n2'), makeEdge('n1', 'n3')]);
    mockApiPost.mockResolvedValueOnce(expandData);

    await act(async () => {
      await result.current.expand(['n1'], 2);
    });

    expect(mockApiPost).toHaveBeenCalledWith(
      expect.stringContaining('/explorer/expand'),
      { node_ids: ['n1'], depth: 2 }
    );

    // 1 original + 2 new
    expect(result.current.nodes).toHaveLength(3);
  });

  it('expand does nothing when nodeIds is empty', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.expand([], 1);
    });

    expect(mockApiPost).not.toHaveBeenCalled();
  });

  it('expand does nothing when namespace is null', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(null));

    await act(async () => {
      await result.current.expand(['n1'], 1);
    });

    expect(mockApiPost).not.toHaveBeenCalled();
  });

  // ---- Search action ----

  it('search merges search results into graph', async () => {
    // Seed first
    const n1 = makeNode('n1');
    const seedData = makeGraphData([n1], [], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    expect(result.current.nodes).toHaveLength(1);

    // Search
    const searchResult = makeNode('s1', 'person', 'SearchResult', 0.8);
    const searchData = makeGraphData([searchResult], [], { query: 'test' });
    mockApiPost.mockResolvedValueOnce(searchData);

    await act(async () => {
      await result.current.search('test', 10);
    });

    expect(mockApiPost).toHaveBeenCalledWith(
      expect.stringContaining('/explorer/search'),
      { query: 'test', limit: 10, filters: {} }
    );

    // Original node still present + search result = 2
    expect(result.current.nodes).toHaveLength(2);
  });

  it('search accepts Scenario 02 ExplorerSearchResponse and normalizes results into graph nodes', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    mockApiPost.mockResolvedValueOnce({
      results: [{
        id: 'object.contract-result',
        label: 'Contract Result',
        object_type: 'Knowledge Object',
        description: 'Scenario 02 search result shape.',
        properties: { owner: 'Knowledge Ops' },
        validation_issues: [],
        provenance_refs: [],
        permissions: { level: 'read', allowed_actions: ['view'] },
      }],
      meta: { query: 'contract', truncated: false, limit: 20, filters: {}, warnings: [] },
    });

    await act(async () => {
      await result.current.search('contract');
    });

    expect(result.current.nodes).toHaveLength(1);
    expect(result.current.nodes[0]).toMatchObject({
      id: 'object.contract-result',
      name: 'Contract Result',
      label: 'Knowledge Object',
      properties: { owner: 'Knowledge Ops' },
    });
  });

  it('search does nothing with empty query', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.search('  ');
    });

    expect(mockApiPost).not.toHaveBeenCalled();
  });

  it('search does nothing when namespace is null', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(null));

    await act(async () => {
      await result.current.search('test');
    });

    expect(mockApiPost).not.toHaveBeenCalled();
  });

  // ---- FindPath action ----

  it('findPath sets selectedPath and merges path data', async () => {
    // Seed
    const n1 = makeNode('n1');
    const n2 = makeNode('n2');
    const seedData = makeGraphData([n1, n2], [], { seed_count: 2 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    // Path finding
    const pathData: ExplorerPathData = {
      nodes: [makeNode('n1'), makeNode('mid'), makeNode('n2')],
      edges: [makeEdge('n1', 'mid'), makeEdge('mid', 'n2')],
      stats: { node_count: 3, edge_count: 2, path_length: 3 },
      path: ['n1', 'mid', 'n2'],
    };
    mockApiPost.mockResolvedValueOnce(pathData);

    await act(async () => {
      await result.current.findPath('n1', 'n2');
    });

    expect(mockApiPost).toHaveBeenCalledWith(
      expect.stringContaining('/explorer/path'),
      { source_id: 'n1', target_id: 'n2' }
    );

    expect(result.current.selectedPath).toEqual({
      source: 'n1',
      target: 'n2',
      path: ['n1', 'mid', 'n2'],
    });
  });

  it('findPath clears selectedPath on error', async () => {
    // Seed
    const n1 = makeNode('n1');
    const n2 = makeNode('n2');
    const seedData = makeGraphData([n1, n2], [], { seed_count: 2 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    // First set a path
    const pathData: ExplorerPathData = {
      nodes: [n1, n2],
      edges: [makeEdge('n1', 'n2')],
      stats: { node_count: 2, edge_count: 1, path_length: 2 },
      path: ['n1', 'n2'],
    };
    mockApiPost.mockResolvedValueOnce(pathData);

    await act(async () => {
      await result.current.findPath('n1', 'n2');
    });

    expect(result.current.selectedPath).not.toBeNull();

    // Now findPath fails
    mockApiPost.mockRejectedValueOnce(new Error('No path'));

    await act(async () => {
      await result.current.findPath('n1', 'n3');
    });

    expect(result.current.selectedPath).toBeNull();
  });

  it('findPath does nothing when namespace is null', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(null));

    await act(async () => {
      await result.current.findPath('n1', 'n2');
    });

    expect(mockApiPost).not.toHaveBeenCalled();
  });

  // ---- ClearPath action ----

  it('clearPath clears selected path', async () => {
    const n1 = makeNode('n1');
    const n2 = makeNode('n2');
    const seedData = makeGraphData([n1, n2], [], { seed_count: 2 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    const pathData: ExplorerPathData = {
      nodes: [n1, n2],
      edges: [makeEdge('n1', 'n2')],
      stats: { node_count: 2, edge_count: 1, path_length: 2 },
      path: ['n1', 'n2'],
    };
    mockApiPost.mockResolvedValueOnce(pathData);

    await act(async () => {
      await result.current.findPath('n1', 'n2');
    });

    expect(result.current.selectedPath).not.toBeNull();

    act(() => {
      result.current.clearPath();
    });

    expect(result.current.selectedPath).toBeNull();
  });

  // ---- GetNodeDetail action ----

  it('getNodeDetail fetches and returns node detail', async () => {
    const mockDetail: ExplorerNodeDetail = {
      node: makeNode('n1', 'entity', 'Alpha', 0.9),
      edges: [makeEdge('n1', 'n2', 'KNOWS')],
      stats: { degree: 5, in_degree: 2, out_degree: 3 },
    };
    mockApiGet.mockResolvedValueOnce(mockDetail);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    const detailRef: { current: ExplorerNodeDetail | null } = { current: null };
    await act(async () => {
      detailRef.current = await result.current.getNodeDetail('n1');
    });

    expect(mockApiGet).toHaveBeenCalledWith(
      expect.stringContaining('/explorer/node/n1')
    );
    const returnedDetail = detailRef.current;
    if (returnedDetail === null) throw new Error('Expected node detail response');
    expect(returnedDetail.node?.id).toBe('n1');
    expect(returnedDetail.stats.degree).toBe(5);
  });

  it('getNodeDetail accepts Scenario 02 normalized object detail shape', async () => {
    mockApiGet.mockReset();
    mockApiGet.mockResolvedValueOnce({
      id: 'object.customer',
      label: 'Customer Account',
      properties: { owner: 'Data Stewardship' },
      relationships: [{ id: 'rel.customer-policy', label: 'owns policy', target: 'object.policy', direction: 'out' }],
      validation_issues: [],
      provenance_refs: [],
      permissions: { level: 'read', allowed_actions: ['view'] },
    });

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    const detailRef: { current: ExplorerNodeDetail | null } = { current: null };
    await act(async () => {
      detailRef.current = await result.current.getNodeDetail('object.customer');
    });

    const returnedDetail = detailRef.current;
    if (returnedDetail === null) throw new Error('Expected Scenario 02 node detail response');
    expect(returnedDetail.node).toMatchObject({ id: 'object.customer', name: 'Customer Account' });
    expect(returnedDetail.edges[0]).toMatchObject({ source: 'object.customer', target: 'object.policy', direction: 'outgoing' });
    expect(returnedDetail.stats.degree).toBe(1);
  });

  it('getNodeDetail returns null on error', async () => {
    // Important: clear any prior mock returns for this test
    mockApiGet.mockReset();
    mockApiGet.mockRejectedValueOnce(new Error('Not found'));

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    let detail: ExplorerNodeDetail | null = { node: makeNode('placeholder'), edges: [], stats: {} };
    await act(async () => {
      detail = await result.current.getNodeDetail('missing');
    });

    expect(detail).toBeNull();
  });

  it('getNodeDetail returns null when namespace is null', async () => {
    const { result } = renderHook(() => useKnowledgeExplorer(null));

    let detail: ExplorerNodeDetail | null = { node: makeNode('placeholder'), edges: [], stats: {} };
    await act(async () => {
      detail = await result.current.getNodeDetail('n1');
    });

    expect(detail).toBeNull();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  // ---- Reset action ----

  it('reset clears all accumulated state', async () => {
    const n1 = makeNode('n1');
    const n2 = makeNode('n2');
    const seedData = makeGraphData([n1, n2], [makeEdge('n1', 'n2')], { seed_count: 2 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    // State is populated
    expect(result.current.nodes.length).toBeGreaterThan(0);
    expect(result.current.activeIgnitionPoints.length).toBeGreaterThan(0);

    act(() => {
      result.current.reset();
    });

    expect(result.current.nodes).toEqual([]);
    expect(result.current.edges).toEqual([]);
    expect(result.current.activeIgnitionPoints).toEqual([]);
    expect(result.current.selectedPath).toBeNull();
    expect(result.current.nodeBrightness.size).toBe(0);
  });

  // ---- Lens and depth setters ----

  it('setLens changes the active lens', () => {
    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    expect(result.current.activeLens).toBe('community');

    act(() => {
      result.current.setLens('semantic');
    });

    expect(result.current.activeLens).toBe('semantic');

    act(() => {
      result.current.setLens('category');
    });

    expect(result.current.activeLens).toBe('category');
  });

  it('setExpansionDepth changes depth', () => {
    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    expect(result.current.expansionDepth).toBe(1);

    act(() => {
      result.current.setExpansionDepth(3);
    });

    expect(result.current.expansionDepth).toBe(3);
  });

  // ---- Brightness computation ----

  it('computeBrightness assigns 1.0 to ignition points, 0.7 to 1-hop neighbors, 0.3 base', async () => {
    const n1 = makeNode('n1', 'entity', 'A', 0.9);
    const n2 = makeNode('n2', 'entity', 'B', 0.7);
    const n3 = makeNode('n3', 'entity', 'C', 0.5);
    const e1 = makeEdge('n1', 'n2', 'KNOWS');
    // n3 is disconnected
    const seedData = makeGraphData([n1, n2, n3], [e1], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    // n1 is ignition point (seed_count=1) => brightness 1.0
    expect(result.current.nodeBrightness.get('n1')).toBe(1.0);
    // n2 is 1-hop neighbor of n1 => brightness 0.7
    expect(result.current.nodeBrightness.get('n2')).toBe(0.7);
    // n3 has no connection to ignition point => base 0.3
    expect(result.current.nodeBrightness.get('n3')).toBe(0.3);
  });

  // ---- Accumulation: data merges, not replaces ----

  it('multiple expands accumulate nodes rather than replacing', async () => {
    const n1 = makeNode('n1');
    const seedData = makeGraphData([n1], [], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    expect(result.current.nodes).toHaveLength(1);

    // First expand
    const n2 = makeNode('n2');
    mockApiPost.mockResolvedValueOnce(makeGraphData([n2], [makeEdge('n1', 'n2')]));
    await act(async () => {
      await result.current.expand(['n1']);
    });

    expect(result.current.nodes).toHaveLength(2);

    // Second expand
    const n3 = makeNode('n3');
    mockApiPost.mockResolvedValueOnce(makeGraphData([n3], [makeEdge('n2', 'n3')]));
    await act(async () => {
      await result.current.expand(['n2']);
    });

    expect(result.current.nodes).toHaveLength(3);
  });

  it('duplicate nodes are merged (updated), not duplicated', async () => {
    const n1 = makeNode('n1', 'entity', 'Alpha', 0.5);
    const seedData = makeGraphData([n1], [], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    // Expand returns the same node with updated score
    const n1Updated = makeNode('n1', 'entity', 'Alpha', 0.95);
    mockApiPost.mockResolvedValueOnce(makeGraphData([n1Updated], []));
    await act(async () => {
      await result.current.expand(['n1']);
    });

    // Still only 1 node, but with updated score
    expect(result.current.nodes).toHaveLength(1);
    expect(result.current.nodes[0].score).toBe(0.95);
  });

  // ---- Stats derived values ----

  it('stats reflect current accumulated node/edge counts', async () => {
    const seedData = makeGraphData([makeNode('n1'), makeNode('n2')], [makeEdge('n1', 'n2')], { seed_count: 2 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    expect(result.current.stats.node_count).toBe(2);
    expect(result.current.stats.edge_count).toBe(1);
  });

  // ---- Error handling ----

  it('seed handles API error gracefully', async () => {
    mockApiGet.mockRejectedValueOnce(new Error('Server error'));

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    // Should not throw
    await act(async () => {
      await result.current.seed(50);
    });

    // State remains empty
    expect(result.current.nodes).toEqual([]);
    expect(result.current.isSeeding).toBe(false);
  });

  it('expand handles API error gracefully', async () => {
    const n1 = makeNode('n1');
    const seedData = makeGraphData([n1], [], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    mockApiPost.mockRejectedValueOnce(new Error('Expand failed'));

    // Should not throw
    await act(async () => {
      await result.current.expand(['n1']);
    });

    // Original state preserved
    expect(result.current.nodes).toHaveLength(1);
    expect(result.current.isExpanding).toBe(false);
  });

  it('search handles API error gracefully', async () => {
    const n1 = makeNode('n1');
    const seedData = makeGraphData([n1], [], { seed_count: 1 });
    mockApiGet.mockResolvedValueOnce(seedData);

    const { result } = renderHook(() => useKnowledgeExplorer(NAMESPACE));

    await act(async () => {
      await result.current.seed(50);
    });

    mockApiPost.mockRejectedValueOnce(new Error('Search failed'));

    await act(async () => {
      await result.current.search('test');
    });

    expect(result.current.isSearching).toBe(false);
    // Original node preserved
    expect(result.current.nodes).toHaveLength(1);
  });
});

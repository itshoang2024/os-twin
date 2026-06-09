import useSWR from 'swr';
import { apiGet, apiPost } from '@/lib/api-client';
import { compareMockObjectSets, decideMockApproval, getMockGovernanceState, getProjectionFixture, makeMockObjectSet, mockExpandResponse, mockNodeDetails, mockRelationshipTypes, mockSavedObjectSets, previewMockSearchAround, publishMockChangeset, revertMockVersion, runMockSearchAround, searchMockObjects, submitMockChangeset, validateMockChangeset } from './mock-fixtures';
import type {
  ApiErrorResponse,
  EnterpriseMapProjectionResponse,
  ExplorerNodeDetailResponse,
  ExplorerSearchResponse,
  GraphFixtureKey,
  GraphBuilderFilterState,
  ObjectSetCompareSummary,
  ObjectSetRef,
  RelationshipTypeRef,
  SearchAroundPreviewRequest,
  SearchAroundPreviewResponse,
  SearchAroundRunResponse,
  GovernanceRole,
  GovernanceStateResponse,
  ApprovalDecisionRequest,
  SavedGraphResponse,
  SavedGraphVersionResponse,
  SavedSelectionResponse,
  GraphStyleResponse,
  ShareGraphPolicy,
  GraphTemplateResponse,
  TemplateRunResponse,
} from './types';

export type OntologyGraphDataMode = 'mock' | 'live';

export function getOntologyGraphDataMode(): OntologyGraphDataMode {
  const configured = process.env.NEXT_PUBLIC_ONTOLOGY_GRAPH_BUILDER_DATA_MODE;
  return configured === 'live' ? 'live' : 'mock';
}

function delay<T>(value: T, ms = 40): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

export function canonicalErrorDetails(error: unknown): { code?: string; message: string; requestId?: string; validationIssues: string[] } {
  if (!error) return { message: 'Unknown API error', validationIssues: [] };
  const data = (error as { data?: ApiErrorResponse & { message?: string } }).data;
  const canonical = data?.error;
  if (canonical?.message) {
    return {
      code: canonical.code,
      message: canonical.message,
      requestId: data?.request_id,
      validationIssues: canonical.validation_issues ?? [],
    };
  }
  if (data?.message) return { message: data.message, requestId: data.request_id, validationIssues: [] };
  return { message: error instanceof Error ? error.message : 'Unknown API error', validationIssues: [] };
}

export function canonicalErrorMessage(error: unknown): string {
  const details = canonicalErrorDetails(error);
  return details.code ? `${details.code}: ${details.message}` : details.message;
}

function serializeFilterState(filters?: GraphBuilderFilterState): Record<string, unknown> {
  const payload: Record<string, unknown> = filters?.badges?.length ? { badges: { values: filters.badges, mode: 'include' } } : {};
  if (filters?.timeRange) payload.time_range = filters.timeRange;
  return payload;
}

export function useOntologyGraphProjection(namespace: string, fixture: GraphFixtureKey, filters?: GraphBuilderFilterState) {
  const mode = getOntologyGraphDataMode();
  const key = namespace ? ['ontology-graph-projection', namespace, fixture, mode, filters?.badges.join('|') ?? '', filters?.timeRange?.start ?? '', filters?.timeRange?.end ?? ''] : null;

  const fetcher = async (): Promise<EnterpriseMapProjectionResponse> => {
    if (mode === 'mock') {
      return delay(getProjectionFixture(fixture, namespace, filters?.timeRange));
    }
    return apiPost<EnterpriseMapProjectionResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/enterprise-map/query`, { filters: serializeFilterState(filters), limit: null });
  };

  const { data, error, isLoading, mutate } = useSWR<EnterpriseMapProjectionResponse>(key, fetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });

  return { data, error: error as Error | undefined, isLoading, mutate, mode };
}

export async function searchOntologyObjects(namespace: string, query: string, filters: Record<string, unknown> = {}, limit = 20): Promise<ExplorerSearchResponse> {
  if (getOntologyGraphDataMode() === 'mock') {
    return delay(searchMockObjects(query), 30);
  }
  return apiPost<ExplorerSearchResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/explorer/search`, { query, filters, limit });
}

export async function expandOntologyNode(namespace: string, nodeId: string, filters: GraphBuilderFilterState = { badges: [] }, nodeCap = 300): Promise<EnterpriseMapProjectionResponse> {
  if (getOntologyGraphDataMode() === 'mock') {
    return delay({
      ...mockExpandResponse,
      meta: { ...mockExpandResponse.meta, namespace },
    }, 30);
  }
  return apiPost<EnterpriseMapProjectionResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/explorer/expand`, {
    node_ids: [nodeId],
    depth: 1,
    filters: serializeFilterState(filters),
    node_cap: nodeCap,
  });
}

export function useOntologyNodeDetail(namespace: string, nodeId?: string | null) {
  const mode = getOntologyGraphDataMode();
  const key = namespace && nodeId ? ['ontology-node-detail', namespace, nodeId, mode] : null;

  const fetcher = async (): Promise<ExplorerNodeDetailResponse> => {
    if (!nodeId) throw new Error('Node id is required');
    if (mode === 'mock') {
      return delay(mockNodeDetails[nodeId] ?? {
        id: nodeId,
        label: nodeId,
        properties: {},
        relationships: [],
        validation_issues: [],
        provenance_refs: [],
        permissions: { level: 'read', allowed_actions: ['view'] },
      });
    }
    return apiGet<ExplorerNodeDetailResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/explorer/node/${encodeURIComponent(nodeId)}`);
  };

  return useSWR<ExplorerNodeDetailResponse>(key, fetcher, { revalidateOnFocus: false, shouldRetryOnError: false });
}


export async function createOntologyObjectSet(namespace: string, name: string, objectIds: string[], source: ObjectSetRef['source']): Promise<ObjectSetRef> {
  const uniqueIds = Array.from(new Set(objectIds)).slice(0, 300);
  if (getOntologyGraphDataMode() === 'mock') {
    return delay(makeMockObjectSet(name, uniqueIds, source), 30);
  }
  const response = await apiPost<{ object_set: ObjectSetRef }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/object-sets`, { name, object_ids: uniqueIds, source });
  return response.object_set;
}

export async function listOntologyObjectSets(namespace: string): Promise<ObjectSetRef[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(mockSavedObjectSets, 30);
  const response = await apiGet<{ object_sets: ObjectSetRef[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/object-sets`);
  return response.object_sets;
}

export async function compareOntologyObjectSets(namespace: string, base: ObjectSetRef, candidate: ObjectSetRef): Promise<ObjectSetCompareSummary> {
  if (getOntologyGraphDataMode() === 'mock') return delay(compareMockObjectSets(base, candidate), 20);
  return apiPost<ObjectSetCompareSummary>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/object-sets/compare`, { base_id: base.id, candidate_id: candidate.id });
}

export async function listRelationshipTypes(namespace: string): Promise<RelationshipTypeRef[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(mockRelationshipTypes, 20);
  const response = await apiGet<{ relationship_types: RelationshipTypeRef[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/relationship-types`);
  return response.relationship_types;
}

export async function previewSearchAround(namespace: string, request: SearchAroundPreviewRequest): Promise<SearchAroundPreviewResponse> {
  if (getOntologyGraphDataMode() === 'mock') return delay(previewMockSearchAround(request), 35);
  return apiPost<SearchAroundPreviewResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/search-around/preview`, request);
}

export async function runSearchAround(namespace: string, request: SearchAroundPreviewRequest): Promise<SearchAroundRunResponse> {
  if (getOntologyGraphDataMode() === 'mock') return delay(runMockSearchAround(request, namespace), 45);
  return apiPost<SearchAroundRunResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/search-around/run`, request);
}


export function useGovernanceState(namespace: string) {
  const mode = getOntologyGraphDataMode();
  const key = namespace ? ['ontology-governance-state', namespace, mode] : null;
  const fetcher = async (): Promise<GovernanceStateResponse> => {
    if (mode === 'mock') return delay(getMockGovernanceState(namespace), 30);
    return apiGet<GovernanceStateResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/governance/state`);
  };
  const { data, error, isLoading, mutate } = useSWR<GovernanceStateResponse>(key, fetcher, { revalidateOnFocus: false, shouldRetryOnError: false });
  return { data, error: error as Error | undefined, isLoading, mutate, mode };
}

export async function validateChangeset(namespace: string, changesetId: string): Promise<GovernanceStateResponse> {
  if (getOntologyGraphDataMode() === 'mock') return delay(validateMockChangeset(namespace), 30);
  return apiPost<GovernanceStateResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/changesets/${encodeURIComponent(changesetId)}/validate`, {});
}

export async function submitChangeset(namespace: string, changesetId: string, role: GovernanceRole): Promise<GovernanceStateResponse> {
  if (getOntologyGraphDataMode() === 'mock') return delay(submitMockChangeset(namespace, role), 30);
  return apiPost<GovernanceStateResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/changesets/${encodeURIComponent(changesetId)}/submit`, { role });
}

export async function decideApproval(namespace: string, changesetId: string, role: GovernanceRole, request: ApprovalDecisionRequest): Promise<GovernanceStateResponse> {
  if (getOntologyGraphDataMode() === 'mock') return delay(decideMockApproval(namespace, role, request), 30);
  return apiPost<GovernanceStateResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/changesets/${encodeURIComponent(changesetId)}/approval-decision`, { ...request, role });
}

export async function publishChangeset(namespace: string, changesetId: string, role: GovernanceRole, simulateConflict = false): Promise<GovernanceStateResponse> {
  if (getOntologyGraphDataMode() === 'mock') return delay(publishMockChangeset(namespace, role, simulateConflict), 30);
  return apiPost<GovernanceStateResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/changesets/${encodeURIComponent(changesetId)}/publish`, { role, simulate_conflict: simulateConflict });
}

export async function revertVersion(namespace: string, targetVersionId: string, role: GovernanceRole): Promise<GovernanceStateResponse> {
  if (getOntologyGraphDataMode() === 'mock') return delay(revertMockVersion(namespace, role, targetVersionId), 30);
  return apiPost<GovernanceStateResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/versions/${encodeURIComponent(targetVersionId)}/revert`, { role });
}


const savedGraphStores = new Map<string, { graphs: SavedGraphResponse[]; versions: Record<string, SavedGraphVersionResponse[]>; selections: SavedSelectionResponse[]; styles: GraphStyleResponse[]; shares: ShareGraphPolicy[]; templates: GraphTemplateResponse[] }>();

function makeScenario07Store(namespace: string) {
  void namespace;
  return {
    graphs: [] as SavedGraphResponse[],
    versions: {} as Record<string, SavedGraphVersionResponse[]>,
    selections: [
      { id: 'selection-key-account', name: 'Key account triad', color: '#22d3ee', members: ['object.customer', 'object.policy'], overlay: true },
      { id: 'selection-deleted-ref', name: 'Legacy deleted selection', color: '#f59e0b', members: ['object.deleted-demo'], overlay: true, warnings: ['object.deleted-demo was deleted or is not visible in this graph'] },
    ],
    styles: [
      { id: 'style-risk', name: 'Risk review palette', node_rules: [{ match: 'Policy', color: '#f97316', stroke: '#fed7aa' }, { match: 'Claim', color: '#ef4444', stroke: '#fecaca' }, { match: 'Customer', color: '#38bdf8', stroke: '#bae6fd' }], edge_rules: [{ match: 'generates', color: '#f97316', weight: 3 }], legend: [{ label: 'Customer', color: '#38bdf8', description: 'Account anchor' }, { label: 'Policy', color: '#f97316', description: 'Review required' }, { label: 'Claim', color: '#ef4444', description: 'Downstream event' }] },
      { id: 'style-lineage', name: 'Lineage contrast', node_rules: [{ match: 'Agent', color: '#14b8a6' }, { match: 'Knowledge', color: '#a78bfa' }], edge_rules: [{ match: 'observed', color: '#14b8a6', weight: 2 }], legend: [{ label: 'Lineage event', color: '#14b8a6' }, { label: 'Knowledge object', color: '#a78bfa' }] },
    ],
    shares: [{ id: 'share-analyst', principal: 'Analyst role', permission: 'viewer' as const, redacted: false }, { id: 'share-limited', principal: 'Limited viewer', permission: 'limited_viewer' as const, redacted: true }],
    templates: [
      { id: 'template-risk-review', name: 'Risk review starter', description: 'Generate a graph from an object and an object set.', parameters: [{ id: 'root_object', label: 'Root object', type: 'object' as const, required: true }, { id: 'review_set', label: 'Review set', type: 'object_set' as const, required: true }], traversal_definitions: [{ relationship_type_id: 'owns', direction: 'outbound' as const }], filters: { badges: [] }, styles: ['style-risk'], layout: 'layered' as const },
    ],
  };
}

function scenario07Store(namespace: string) {
  if (!savedGraphStores.has(namespace)) savedGraphStores.set(namespace, makeScenario07Store(namespace));
  return savedGraphStores.get(namespace)!;
}

export async function listSavedGraphs(namespace: string): Promise<SavedGraphResponse[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(scenario07Store(namespace).graphs, 20);
  const response = await apiGet<{ saved_graphs: SavedGraphResponse[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/saved-graphs`);
  return response.saved_graphs;
}

export async function saveGraph(namespace: string, graph: Omit<SavedGraphResponse, 'id' | 'version' | 'updated_at'>, graphId?: string): Promise<SavedGraphResponse> {
  if (getOntologyGraphDataMode() === 'mock') {
    const store = scenario07Store(namespace);
    const now = '2026-06-09T10:00:00.000Z';
    const existing = graphId ? store.graphs.find((item) => item.id === graphId) : undefined;
    const saved: SavedGraphResponse = { ...graph, id: existing?.id ?? `graph-${graph.name.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'untitled'}-${store.graphs.length + 1}`, version: (existing?.version ?? 0) + 1, updated_at: now };
    store.graphs = [saved, ...store.graphs.filter((item) => item.id !== saved.id)];
    const prior = store.versions[saved.id]?.[0];
    const version: SavedGraphVersionResponse = { id: `${saved.id}-v${saved.version}`, graph_id: saved.id, version: saved.version, label: `v${saved.version} ${saved.name}`, created_at: now, immutable: true, snapshot: saved, diff: [{ id: 'diff-node-count', label: 'Visible nodes', before: prior ? String(prior.snapshot.view_state.nodes.length) : 'none', after: String(saved.view_state.nodes.length) }], warnings: saved.warnings };
    store.versions[saved.id] = [version, ...(store.versions[saved.id] ?? [])];
    return delay(saved, 25);
  }
  return graphId ? apiPost<SavedGraphResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/saved-graphs/${encodeURIComponent(graphId)}`, graph) : apiPost<SavedGraphResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/saved-graphs`, graph);
}

export async function duplicateSavedGraph(namespace: string, graph: SavedGraphResponse): Promise<SavedGraphResponse> {
  return saveGraph(namespace, { ...graph, name: `${graph.name} copy`, description: graph.description, warnings: graph.warnings }, undefined);
}

export async function listSavedGraphVersions(namespace: string, graphId: string): Promise<SavedGraphVersionResponse[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(scenario07Store(namespace).versions[graphId] ?? [], 20);
  const response = await apiGet<{ versions: SavedGraphVersionResponse[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/saved-graphs/${encodeURIComponent(graphId)}/versions`);
  return response.versions;
}

export async function listSavedSelections(namespace: string): Promise<SavedSelectionResponse[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(scenario07Store(namespace).selections, 20);
  const response = await apiGet<{ selections: SavedSelectionResponse[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/saved-selections`);
  return response.selections;
}

export async function upsertSavedSelection(namespace: string, selection: SavedSelectionResponse): Promise<SavedSelectionResponse[]> {
  if (getOntologyGraphDataMode() === 'mock') {
    const store = scenario07Store(namespace);
    store.selections = [selection, ...store.selections.filter((item) => item.id !== selection.id)];
    return delay(store.selections, 20);
  }
  const response = await apiPost<{ selections: SavedSelectionResponse[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/saved-selections`, selection);
  return response.selections;
}

export async function listGraphStyles(namespace: string): Promise<GraphStyleResponse[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(scenario07Store(namespace).styles, 20);
  const response = await apiGet<{ styles: GraphStyleResponse[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/graph-styles`);
  return response.styles;
}

export async function listSharePolicies(namespace: string): Promise<ShareGraphPolicy[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(scenario07Store(namespace).shares, 20);
  const response = await apiGet<{ shares: ShareGraphPolicy[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/saved-graphs/shares`);
  return response.shares;
}

export async function listGraphTemplates(namespace: string): Promise<GraphTemplateResponse[]> {
  if (getOntologyGraphDataMode() === 'mock') return delay(scenario07Store(namespace).templates, 20);
  const response = await apiGet<{ templates: GraphTemplateResponse[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/graph-templates`);
  return response.templates;
}

export async function upsertGraphTemplate(namespace: string, template: GraphTemplateResponse): Promise<GraphTemplateResponse[]> {
  if (getOntologyGraphDataMode() === 'mock') {
    const store = scenario07Store(namespace);
    store.templates = [template, ...store.templates.filter((item) => item.id !== template.id)];
    return delay(store.templates, 20);
  }
  const response = await apiPost<{ templates: GraphTemplateResponse[] }>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/graph-templates`, template);
  return response.templates;
}

export async function runGraphTemplate(namespace: string, template: GraphTemplateResponse, parameterValues: Record<string, string>): Promise<TemplateRunResponse> {
  const missing = template.parameters.filter((param) => param.required && !parameterValues[param.id]?.trim());
  if (missing.length) throw Object.assign(new Error('Required template parameters missing'), { data: { error: { code: 'VALIDATION_FAILED', message: `${missing[0].label} is required` } } });
  if (getOntologyGraphDataMode() === 'mock') {
    return delay({ projection: { ...runMockSearchAround({ object_set_id: parameterValues.review_set || 'set-key-accounts', steps: template.traversal_definitions, limit: 4 }, namespace), meta: { ...mockExpandResponse.meta, namespace } }, run_metadata: { template_id: template.id, run_id: `run-${template.id}`, parameter_values: parameterValues, generated_at: '2026-06-09T10:15:00.000Z', warnings: parameterValues.root_object === 'object.deleted-demo' ? ['Template parameter object.deleted-demo no longer exists'] : [] } }, 35);
  }
  return apiPost<TemplateRunResponse>(`/knowledge/namespaces/${encodeURIComponent(namespace)}/ontology/graph-templates/${encodeURIComponent(template.id)}/run`, { parameters: parameterValues });
}

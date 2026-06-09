"use client";

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { EnterpriseMapProjectionAdapter } from './EnterpriseMapProjectionAdapter';
import { InstanceAuthoringPanel } from './InstanceAuthoring';
import {
  canonicalErrorDetails,
  canonicalErrorMessage,
  compareOntologyObjectSets,
  decideApproval,
  createOntologyObjectSet,
  expandOntologyNode,
  listOntologyObjectSets,
  listRelationshipTypes,
  listGraphStyles,
  listGraphTemplates,
  listSavedGraphVersions,
  listSavedGraphs,
  listSavedSelections,
  listSharePolicies,
  previewSearchAround,
  duplicateSavedGraph,
  publishChangeset,
  runGraphTemplate,
  saveGraph,
  revertVersion,
  runSearchAround,
  searchOntologyObjects,
  submitChangeset,
  upsertGraphTemplate,
  upsertSavedSelection,
  useGovernanceState,
  useOntologyGraphProjection,
  useOntologyNodeDetail,
  validateChangeset,
} from './useOntologyGraphBuilderData';
import { REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS } from './types';
import type {
  CanvasEdge,
  CanvasNode,
  CanvasViewModel,
  EnterpriseMapProjectionResponse,
  ExplorerSearchResult,
  GraphBuilderFilterState,
  GraphFixtureKey,
  GraphLayoutPreset,
  GraphMode,
  GraphSelection,
  GovernanceRole,
  GovernanceStateResponse,
  GovernanceValidationIssue,
  ObjectSetCompareSummary,
  ObjectSetRef,
  RelationshipTypeRef,
  SearchAroundPreviewResponse,
  SearchAroundStepRequest,
  SavedGraphResponse,
  SavedGraphVersionResponse,
  SavedSelectionResponse,
  GraphStyleResponse,
  ShareGraphPolicy,
  GraphTemplateResponse,
  GraphTimeRange,
  GraphGroup,
  GroupedEdge,
  GraphEvent,
} from './types';

const fixtureOptions: { id: GraphFixtureKey; label: string }[] = [
  { id: 'basic', label: 'Basic' },
  { id: 'empty', label: 'Empty' },
  { id: 'redacted', label: 'Redacted' },
  { id: 'large', label: 'Large' },
  { id: 'error', label: 'Error' },
];

const layoutOptions: { id: GraphLayoutPreset; label: string }[] = [
  { id: 'grid', label: 'Grid' },
  { id: 'layered', label: 'Layered' },
  { id: 'compact', label: 'Compact' },
];

const inspectorTabs = ['Overview', 'Events', 'Time Series', 'Properties', 'Relationships', 'Validation', 'Provenance', 'Lineage', 'Permissions'] as const;
type InspectorTab = typeof inspectorTabs[number];

interface OntologyGraphBuilderPageProps {
  namespace: string;
  initialFixture?: GraphFixtureKey;
}

const DEFAULT_TIME_RANGE: GraphTimeRange = { start: '2026-06-09T08:00:00.000Z', end: '2026-06-09T12:00:00.000Z' };
const MAX_EVENT_LIST = 3;
const MAX_GROUP_LIST = 6;

function disabledFeatureFlags(flags?: Record<string, boolean>): string[] {
  return REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS.filter((flag) => flags?.[flag] === false);
}

function eventIntersectsRange(event: GraphEvent, range: GraphTimeRange): boolean {
  const start = Date.parse(event.starts_at);
  const end = event.ends_at ? Date.parse(event.ends_at) : start;
  return start <= Date.parse(range.end) && end >= Date.parse(range.start);
}

function activeEventsFor(item: { events: GraphEvent[] }, range: GraphTimeRange): GraphEvent[] {
  return item.events.filter((event) => event.status === 'active' && eventIntersectsRange(event, range));
}

function makeGroupNode(group: GraphGroup, members: CanvasNode[], index: number): CanvasNode {
  const first = members[0];
  const redactedCount = members.filter((node) => node.redacted || node.permissions.level === 'limited').length;
  const x = Math.round(members.reduce((sum, node) => sum + node.x, 0) / Math.max(1, members.length));
  const y = Math.round(members.reduce((sum, node) => sum + node.y, 0) / Math.max(1, members.length));
  const events = members.flatMap((node) => node.events);
  const timeSeries = members.flatMap((node) => node.timeSeries);
  return {
    id: group.id,
    label: group.label,
    typeLabel: 'Grouped node',
    badges: ['Grouped', `${members.length} objects`, redactedCount ? 'Mixed permissions' : 'Full read'],
    x: Number.isFinite(x) ? x : 120 + index * 190,
    y: Number.isFinite(y) ? y : 80,
    redacted: redactedCount > 0,
    properties: { memberIds: group.member_ids, redactedMembers: redactedCount, rule: group.rule.kind },
    permissions: redactedCount ? { level: 'limited', reason: 'Group contains mixed-permission objects; sensitive properties are redacted.', allowedActions: ['view_topology', 'ungroup'] } : (first?.permissions ?? { level: 'read', allowedActions: ['view', 'ungroup'] }),
    validation: { count: 0, issues: group.warnings ?? [] },
    provenance: { refs: members.flatMap((node) => node.provenance.refs).slice(0, MAX_GROUP_LIST) },
    style: { color: redactedCount ? '#b91c1c' : '#38bdf8', shape: 'group', opacity: redactedCount ? 0.76 : 1, stroke: '#67e8f9' },
    source: 'projection',
    events,
    activeEventCount: events.filter((event) => event.status === 'active').length,
    totalEventCount: events.length,
    timeSeries,
    group: { ...group, aggregate_stats: { member_count: members.length, redacted_count: redactedCount, event_count: events.length, active_event_count: events.filter((event) => event.status === 'active').length } },
  };
}

function makeIncomingViewModel(current: CanvasViewModel, nodes: CanvasNode[]): CanvasViewModel {
  return {
    ...current,
    nodes,
    edges: [],
    stats: { ...current.stats, node_count: nodes.length, edge_count: 0 },
    filters: [],
  };
}

export default function OntologyGraphBuilderPage({ namespace, initialFixture = 'basic' }: OntologyGraphBuilderPageProps) {
  const [fixture, setFixture] = useState<GraphFixtureKey>(initialFixture);
  const [mode, setMode] = useState<GraphMode>('explore');
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [activeFilters, setActiveFilters] = useState<string[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('Overview');
  const [layoutPreset, setLayoutPreset] = useState<GraphLayoutPreset>('grid');
  const [graphViewModel, setGraphViewModel] = useState<CanvasViewModel | null>(null);
  const [objectSets, setObjectSets] = useState<ObjectSetRef[]>([]);
  const [activeObjectSet, setActiveObjectSet] = useState<ObjectSetRef | null>(null);
  const [relationshipTypes, setRelationshipTypes] = useState<RelationshipTypeRef[]>([]);
  const [traversalSteps, setTraversalSteps] = useState<SearchAroundStepRequest[]>([{ relationship_type_id: 'owns', direction: 'outbound' }]);
  const [traversalPreview, setTraversalPreview] = useState<SearchAroundPreviewResponse | null>(null);
  const [traversalProjection, setTraversalProjection] = useState<EnterpriseMapProjectionResponse | null>(null);
  const [traversalLoading, setTraversalLoading] = useState(false);
  const [compareSummary, setCompareSummary] = useState<ObjectSetCompareSummary | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expanding, setExpanding] = useState(false);
  const [fitNonce, setFitNonce] = useState(0);
  const [governanceRole, setGovernanceRole] = useState<GovernanceRole>('steward');
  const [focusedGraphElementId, setFocusedGraphElementId] = useState<string | null>(null);
  const [approvalModalOpen, setApprovalModalOpen] = useState(false);
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);
  const [revertDialogOpen, setRevertDialogOpen] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState<string>('current');
  const [savedGraphs, setSavedGraphs] = useState<SavedGraphResponse[]>([]);
  const [activeSavedGraph, setActiveSavedGraph] = useState<SavedGraphResponse | null>(null);
  const [savedGraphVersions, setSavedGraphVersions] = useState<SavedGraphVersionResponse[]>([]);
  const [savedSelections, setSavedSelections] = useState<SavedSelectionResponse[]>([]);
  const [graphStyles, setGraphStyles] = useState<GraphStyleResponse[]>([]);
  const [activeStyle, setActiveStyle] = useState<GraphStyleResponse | null>(null);
  const [sharePolicies, setSharePolicies] = useState<ShareGraphPolicy[]>([]);
  const [graphTemplates, setGraphTemplates] = useState<GraphTemplateResponse[]>([]);
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [templateWizardOpen, setTemplateWizardOpen] = useState(false);
  const [templateRunOpen, setTemplateRunOpen] = useState(false);
  const [activeTemplate, setActiveTemplate] = useState<GraphTemplateResponse | null>(null);
  const [shareRedactionPreview, setShareRedactionPreview] = useState(false);
  const [savedGraphNotice, setSavedGraphNotice] = useState<string | null>(null);
  const [simulatePublishConflict, setSimulatePublishConflict] = useState(false);
  const [timeRange, setTimeRange] = useState<GraphTimeRange>(DEFAULT_TIME_RANGE);
  const [groups, setGroups] = useState<GraphGroup[]>([]);
  const lastProjectionRef = useRef<{ scope: string; data: EnterpriseMapProjectionResponse | null } | null>(null);

  const filterState = useMemo<GraphBuilderFilterState>(() => ({ badges: activeFilters, timeRange }), [activeFilters, timeRange]);
  const { data, error, isLoading, mutate, mode: dataMode } = useOntologyGraphProjection(namespace, fixture, filterState);
  const governance = useGovernanceState(namespace);
  const projectionScope = `${namespace}:${fixture}:${dataMode}:${timeRange.start}:${timeRange.end}`;

  useEffect(() => {
    if (!data) return;

    const previousProjection = lastProjectionRef.current;
    if (previousProjection?.scope === projectionScope && previousProjection.data === data) return;

    const incoming = EnterpriseMapProjectionAdapter.toCanvasViewModel(data, layoutPreset);
    const shouldReplace = previousProjection?.scope !== projectionScope;

    setGraphViewModel((current) => {
      if (!current || shouldReplace) return incoming;
      return EnterpriseMapProjectionAdapter.mergeViewModels(current, incoming);
    });
    lastProjectionRef.current = { scope: projectionScope, data };
  }, [data, layoutPreset, projectionScope]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listOntologyObjectSets(namespace), listRelationshipTypes(namespace)])
      .then(([sets, relationships]) => {
        if (cancelled) return;
        setObjectSets(sets);
        setRelationshipTypes(relationships);
        setActiveObjectSet((current) => current ?? sets[0] ?? null);
      })
      .catch((err) => setActionError(canonicalErrorMessage(err)));
    return () => { cancelled = true; };
  }, [namespace]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listSavedGraphs(namespace), listSavedSelections(namespace), listGraphStyles(namespace), listSharePolicies(namespace), listGraphTemplates(namespace)])
      .then(([graphs, selections, styles, shares, templates]) => {
        if (cancelled) return;
        setSavedGraphs(graphs);
        setSavedSelections(selections);
        setGraphStyles(styles);
        setActiveStyle((current) => current ?? styles[0] ?? null);
        setSharePolicies(shares);
        setGraphTemplates(templates);
        setActiveTemplate((current) => current ?? templates[0] ?? null);
      })
      .catch((err) => setActionError(canonicalErrorMessage(err)));
    return () => { cancelled = true; };
  }, [namespace]);

  useEffect(() => {
    if (!activeSavedGraph) { setSavedGraphVersions([]); return; }
    let cancelled = false;
    listSavedGraphVersions(namespace, activeSavedGraph.id).then((versions) => { if (!cancelled) setSavedGraphVersions(versions); }).catch((err) => setActionError(canonicalErrorMessage(err)));
    return () => { cancelled = true; };
  }, [namespace, activeSavedGraph]);

  const visibleNodes = useMemo(() => {
    if (!graphViewModel) return [];
    if (!activeFilters.length) return graphViewModel.nodes;
    return graphViewModel.nodes.filter((node) => activeFilters.some((filter) => node.badges.map((badge) => badge.toLowerCase()).includes(filter.toLowerCase())));
  }, [graphViewModel, activeFilters]);

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(() => (graphViewModel?.edges ?? []).filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)), [graphViewModel, visibleNodeIds]);

  const groupedView = useMemo(() => buildGroupedView(visibleNodes, visibleEdges, groups), [visibleNodes, visibleEdges, groups]);
  const displayedNodes = groupedView.nodes;
  const displayedEdges = groupedView.edges;
  const allEvents = useMemo(() => [...displayedNodes.flatMap((node) => node.events), ...displayedEdges.flatMap((edge) => edge.events)], [displayedNodes, displayedEdges]);
  const activeEvents = useMemo(() => allEvents.filter((event) => event.status === 'active' && eventIntersectsRange(event, timeRange)), [allEvents, timeRange]);
  const eventsTruncated = activeEvents.length > MAX_EVENT_LIST || Boolean(graphViewModel?.meta.event_truncation_warnings?.length);

  const selectedNode = selection?.kind === 'node' ? displayedNodes.find((node) => node.id === selection.id) : undefined;
  const selectedEdge = selection?.kind === 'edge' ? displayedEdges.find((edge) => edge.id === selection.id) : undefined;
  const governanceState = governance.data;
  const changeset = governanceState?.changeset;
  const historicalReadonly = selectedVersionId !== 'current';

  const handleAddResults = (results: ExplorerSearchResult[]) => {
    setActionError(null);
    setGraphViewModel((current) => {
      if (!current) return current;
      const ids = new Set(current.nodes.map((node) => node.id));
      const incomingNodes = results
        .filter((result) => !ids.has(result.id))
        .map((result, index) => EnterpriseMapProjectionAdapter.searchResultToNode(result, index, current.nodes.length, layoutPreset));
      if (!incomingNodes.length) return current;
      return EnterpriseMapProjectionAdapter.mergeViewModels(current, makeIncomingViewModel(current, incomingNodes));
    });
    setSearchOpen(false);
  };

  const handleExpandSelected = async () => {
    if (!selectedNode) return;
    setExpanding(true);
    setActionError(null);
    try {
      const projection = await expandOntologyNode(namespace, selectedNode.id, filterState);
      const incoming = EnterpriseMapProjectionAdapter.toCanvasViewModel(projection, layoutPreset);
      setGraphViewModel((current) => current ? EnterpriseMapProjectionAdapter.mergeViewModels(current, incoming) : incoming);
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    } finally {
      setExpanding(false);
    }
  };

  const upsertObjectSet = (objectSet: ObjectSetRef) => {
    setObjectSets((current) => [objectSet, ...current.filter((item) => item.id !== objectSet.id)]);
    setActiveObjectSet(objectSet);
  };

  const handleCreateSetFromSelected = async () => {
    if (!selectedNode) return;
    setActionError(null);
    try {
      upsertObjectSet(await createOntologyObjectSet(namespace, `${selectedNode.label} selection`, [selectedNode.id], 'selected'));
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    }
  };

  const handleCreateSetFromSearch = async (results: ExplorerSearchResult[]) => {
    if (!results.length) return;
    setActionError(null);
    try {
      upsertObjectSet(await createOntologyObjectSet(namespace, 'Search result object set', results.map((result) => result.id), 'search'));
      setSearchOpen(false);
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    }
  };

  const handleCompareWithSaved = async (candidate: ObjectSetRef) => {
    if (!activeObjectSet) return;
    setActionError(null);
    try {
      setCompareSummary(await compareOntologyObjectSets(namespace, activeObjectSet, candidate));
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    }
  };

  const handlePreviewTraversal = async () => {
    if (!activeObjectSet) return;
    setTraversalLoading(true);
    setActionError(null);
    try {
      setTraversalPreview(await previewSearchAround(namespace, { object_set_id: activeObjectSet.id, steps: traversalSteps, limit: 3 }));
      setTraversalProjection(null);
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    } finally {
      setTraversalLoading(false);
    }
  };

  const handleRunTraversal = async () => {
    if (!activeObjectSet) return;
    setTraversalLoading(true);
    setActionError(null);
    try {
      const projection = await runSearchAround(namespace, { object_set_id: activeObjectSet.id, steps: traversalSteps, limit: 3 });
      setTraversalProjection(projection);
      setTraversalPreview({ counts_by_object_type: projection.traversal.result_object_set.object_type_counts, total_count: projection.nodes.length, edge_count: projection.edges.length, truncated: projection.traversal.truncated, warnings: projection.traversal.warnings, validation_issues: projection.traversal.validation_issues, limit: projection.stats.limit ?? undefined });
      upsertObjectSet(projection.traversal.result_object_set);
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    } finally {
      setTraversalLoading(false);
    }
  };

  const handleAddTraversalToGraph = () => {
    if (!traversalProjection) return;
    const incoming = EnterpriseMapProjectionAdapter.toCanvasViewModel(traversalProjection, layoutPreset);
    setGraphViewModel((current) => current ? EnterpriseMapProjectionAdapter.mergeViewModels(current, incoming) : incoming);
    setActionError(null);
  };

  const upsertCanvasNode = (node: CanvasNode) => {
    setGraphViewModel((current) => {
      if (!current) return current;
      const exists = current.nodes.some((item) => item.id === node.id);
      return {
        ...current,
        nodes: exists ? current.nodes.map((item) => item.id === node.id ? node : item) : [...current.nodes, node],
        stats: { ...current.stats, node_count: exists ? current.stats.node_count : current.stats.node_count + 1 },
      };
    });
  };

  const deleteCanvasNode = (nodeId: string) => {
    setGraphViewModel((current) => {
      if (!current) return current;
      const nodes = current.nodes.filter((node) => node.id !== nodeId);
      const edges = current.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
      return { ...current, nodes, edges, stats: { ...current.stats, node_count: nodes.length, edge_count: edges.length } };
    });
  };

  const upsertCanvasEdge = (edge: CanvasEdge) => {
    setGraphViewModel((current) => {
      if (!current) return current;
      const exists = current.edges.some((item) => item.id === edge.id);
      return {
        ...current,
        edges: exists ? current.edges.map((item) => item.id === edge.id ? edge : item) : [...current.edges, edge],
        stats: { ...current.stats, edge_count: exists ? current.stats.edge_count : current.stats.edge_count + 1 },
      };
    });
  };

  const deleteCanvasEdge = (edgeId: string) => {
    setGraphViewModel((current) => {
      if (!current) return current;
      const edges = current.edges.filter((edge) => edge.id !== edgeId);
      return { ...current, edges, stats: { ...current.stats, edge_count: edges.length } };
    });
  };



  const applyGovernanceState = (state: GovernanceStateResponse) => {
    void governance.mutate(state, { revalidate: false });
  };

  const handleGovernanceAction = async (action: () => Promise<GovernanceStateResponse>) => {
    setActionError(null);
    try {
      applyGovernanceState(await action());
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    }
  };

  const handleValidationIssueFocus = (issue: GovernanceValidationIssue) => {
    const targetId = issue.target.kind === 'property' ? issue.target.id : issue.target.id;
    setFocusedGraphElementId(targetId);
    setSelection(issue.target.kind === 'edge' ? { kind: 'edge', id: targetId } : { kind: 'node', id: targetId });
    setInspectorTab(issue.target.kind === 'property' ? 'Properties' : 'Validation');
  };

  const buildSavedGraphPayload = (name: string, base?: SavedGraphResponse): Omit<SavedGraphResponse, 'id' | 'version' | 'updated_at'> | null => {
    if (!graphViewModel) return null;
    const missingWarnings = [
      ...savedSelections.flatMap((item) => item.warnings ?? []),
      ...(activeStyle?.warnings ?? []),
    ];
    return {
      name,
      description: base?.description ?? 'Scenario 07 curated graph view',
      view_state: graphViewModel,
      filters: filterState,
      layout: layoutPreset,
      pinned_positions: Object.fromEntries(graphViewModel.nodes.map((node) => [node.id, { x: node.x, y: node.y }])),
      style_refs: activeStyle ? [activeStyle.id] : [],
      selection_refs: savedSelections.filter((item) => item.overlay).map((item) => item.id),
      warnings: missingWarnings.length ? Array.from(new Set(missingWarnings)) : undefined,
      permission: base?.permission ?? 'owner',
    };
  };

  const handleSaveGraph = async (name?: string, base?: SavedGraphResponse | null) => {
    if (historicalReadonly) return;
    const payload = buildSavedGraphPayload(name ?? base?.name ?? activeSavedGraph?.name ?? 'Untitled graph', base ?? activeSavedGraph ?? undefined);
    if (!payload) return;
    setActionError(null);
    try {
      const saved = await saveGraph(namespace, payload, base?.id ?? activeSavedGraph?.id);
      setSavedGraphs((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setActiveSavedGraph(saved);
      setSavedGraphNotice(`Saved ${saved.name} at version ${saved.version}`);
      setSaveAsOpen(false);
    } catch (err) {
      setActionError(canonicalErrorMessage(err));
    }
  };

  const handleDuplicateGraph = async () => {
    if (!activeSavedGraph || historicalReadonly) return;
    try {
      const copy = await duplicateSavedGraph(namespace, activeSavedGraph);
      setSavedGraphs((current) => [copy, ...current]);
      setActiveSavedGraph(copy);
      setGraphViewModel(copy.view_state);
      setSavedGraphNotice(`Duplicated ${activeSavedGraph.name}`);
    } catch (err) { setActionError(canonicalErrorMessage(err)); }
  };

  const handleOpenSavedGraph = (graph: SavedGraphResponse) => {
    setActiveSavedGraph(graph);
    setGraphViewModel(graph.view_state);
    setActiveFilters(graph.filters.badges);
    setLayoutPreset(graph.layout);
    setSelection(null);
    setSavedGraphNotice(`Restored ${graph.name} with ${graph.view_state.nodes.length} nodes`);
  };

  const handleOpenVersion = (version: SavedGraphVersionResponse) => {
    setActiveSavedGraph(version.snapshot);
    setGraphViewModel(version.snapshot.view_state);
    setActiveFilters(version.snapshot.filters.badges);
    setLayoutPreset(version.snapshot.layout);
    setSelectedVersionId(version.id);
    setSavedGraphNotice(`Opened immutable ${version.label}`);
  };

  const handleCreateSelection = async () => {
    if (!selectedNode && !selectedEdge) return;
    const id = selectedNode?.id ?? selectedEdge!.id;
    const selectionRef: SavedSelectionResponse = { id: `selection-${id.replace(/[^a-z0-9]+/gi, '-')}`, name: `${selectedNode?.label ?? selectedEdge?.label} selection`, color: '#22d3ee', members: [id], overlay: true };
    setSavedSelections(await upsertSavedSelection(namespace, selectionRef));
  };

  const handleToggleSelectionOverlay = (selectionRef: SavedSelectionResponse) => {
    const next = { ...selectionRef, overlay: !selectionRef.overlay };
    setSavedSelections((current) => [next, ...current.filter((item) => item.id !== next.id)]);
    void upsertSavedSelection(namespace, next).catch((err) => setActionError(canonicalErrorMessage(err)));
  };

  const handleDeleteSelection = (selectionId: string) => {
    setSavedSelections((current) => current.filter((item) => item.id !== selectionId));
  };

  const handleApplyStyle = (style: GraphStyleResponse) => {
    setActiveStyle(style);
    setGraphViewModel((current) => current ? {
      ...current,
      nodes: current.nodes.map((node) => {
        const match = style.node_rules.find((rule) => `${node.label} ${node.typeLabel} ${node.badges.join(' ')}`.toLowerCase().includes(rule.match.toLowerCase()));
        return match ? { ...node, style: { ...node.style, color: match.color, stroke: match.stroke ?? node.style.stroke } } : node;
      }),
      edges: current.edges.map((edge) => {
        const match = style.edge_rules.find((rule) => `${edge.label} ${edge.badges.join(' ')}`.toLowerCase().includes(rule.match.toLowerCase()));
        return match ? { ...edge, style: { ...edge.style, color: match.color, weight: match.weight ?? edge.style.weight } } : edge;
      }),
    } : current);
  };

  const handleLimitedViewerPreview = () => {
    setShareRedactionPreview(true);
    setGraphViewModel((current) => current ? {
      ...current,
      nodes: current.nodes.map((node) => node.id.includes('restricted') ? { ...node, redacted: true, properties: {}, permissions: { level: 'limited', reason: 'Shared limited viewer redaction applied.', allowedActions: ['view_topology'] } } : node),
      edges: current.edges.map((edge) => edge.id.includes('person') ? { ...edge, redacted: true, properties: {}, permissions: { level: 'limited', reason: 'Shared limited viewer redaction applied.', allowedActions: ['view_topology'] } } : edge),
    } : current);
  };

  const handleCreateTemplate = async (template: GraphTemplateResponse) => {
    setGraphTemplates(await upsertGraphTemplate(namespace, template));
    setActiveTemplate(template);
    setTemplateWizardOpen(false);
  };

  const handleTemplateRun = async (template: GraphTemplateResponse, values: Record<string, string>) => {
    const run = await runGraphTemplate(namespace, template, values);
    const incoming = EnterpriseMapProjectionAdapter.toCanvasViewModel(run.projection, template.layout);
    setGraphViewModel(incoming);
    setLayoutPreset(template.layout);
    setSavedGraphNotice(`Template run ${run.run_metadata.run_id} generated ${incoming.nodes.length} nodes. ${run.run_metadata.warnings.join(' ')}`.trim());
    setTemplateRunOpen(false);
  };


  const createGroup = (label: string, memberIds: string[], rule: GraphGroup['rule']) => {
    const uniqueMemberIds = Array.from(new Set(memberIds)).filter((id) => graphViewModel?.nodes.some((node) => node.id === id));
    if (!uniqueMemberIds.length) return;
    const id = `group-${rule.kind}-${(rule.value ?? label).toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${Date.now()}`;
    const members = graphViewModel?.nodes.filter((node) => uniqueMemberIds.includes(node.id)) ?? [];
    const eventCount = members.reduce((sum, node) => sum + node.totalEventCount, 0);
    const activeEventCount = members.reduce((sum, node) => sum + node.activeEventCount, 0);
    const redactedCount = members.filter((node) => node.redacted || node.permissions.level === 'limited').length;
    const warnings = [uniqueMemberIds.length > MAX_GROUP_LIST ? `Group contains ${uniqueMemberIds.length} objects; list is capped in the inspector.` : null, redactedCount ? 'Mixed-permission group: restricted member details are redacted.' : null].filter((item): item is string => Boolean(item));
    setGroups((current) => [{ id, label, rule, member_ids: uniqueMemberIds, aggregate_stats: { member_count: uniqueMemberIds.length, redacted_count: redactedCount, event_count: eventCount, active_event_count: activeEventCount }, warnings }, ...current]);
    setSelection({ kind: 'node', id });
  };

  const handleGroupSelected = () => {
    if (!selectedNode || selectedNode.group) return;
    createGroup(`${selectedNode.typeLabel} selected group`, [selectedNode.id], { kind: 'selected' });
  };

  const handleGroupByType = () => {
    if (!graphViewModel?.nodes.length) return;
    const type = selectedNode && !selectedNode.group ? selectedNode.typeLabel : graphViewModel.nodes[0].typeLabel;
    createGroup(`${type} group`, graphViewModel.nodes.filter((node) => node.typeLabel === type).map((node) => node.id), { kind: 'type', value: type });
  };

  const handleGroupByOwner = () => {
    if (!graphViewModel?.nodes.length) return;
    const owner = String((selectedNode && !selectedNode.group ? selectedNode.properties.owner : graphViewModel.nodes[0].properties.owner) ?? 'Unknown owner');
    createGroup(`${owner} group`, graphViewModel.nodes.filter((node) => String(node.properties.owner ?? 'Unknown owner') === owner).map((node) => node.id), { kind: 'property', property: 'owner', value: owner });
  };

  const handleUngroupSelected = () => {
    if (selectedNode?.group) {
      setGroups((current) => current.filter((group) => group.id !== selectedNode.group?.id));
      setSelection(null);
    }
  };

  const toggleFilter = (label: string) => {
    setActiveFilters((current) => current.includes(label) ? current.filter((item) => item !== label) : [...current, label]);
  };

  const handleLayoutChange = (next: GraphLayoutPreset) => {
    setLayoutPreset(next);
    setGraphViewModel((current) => current ? EnterpriseMapProjectionAdapter.applyLayout(current, next) : current);
  };

  const filterChips = graphViewModel?.filters ?? [];

  return (
    <section data-testid="ontology-graph-builder-page" className="h-full min-h-[760px] flex flex-col overflow-hidden bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/95 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">Ontology Graph Builder</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">Enterprise map projection</h1>
            <p className="mt-1 text-sm text-slate-400">Namespace <span className="font-mono text-slate-200">{namespace}</span> · {dataMode} data mode</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(['explore', 'validate', 'provenance'] as GraphMode[]).map((item) => (
              <button key={item} type="button" onClick={() => setMode(item)} className={`rounded-full px-3 py-1.5 text-xs font-semibold capitalize transition ${mode === item ? 'bg-cyan-300 text-slate-950' : 'border border-slate-700 text-slate-300 hover:border-cyan-400'}`}>
                {item}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-900 px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setSearchOpen(true)} className="rounded-lg bg-cyan-400 px-3 py-2 text-xs font-bold text-slate-950 hover:bg-cyan-300">Search objects</button>
          <button data-testid="expand-node-button" type="button" disabled={!selectedNode || expanding} onClick={handleExpandSelected} className="rounded-lg border border-cyan-400/70 px-3 py-2 text-xs font-semibold text-cyan-100 disabled:border-slate-700 disabled:text-slate-500 disabled:opacity-70">{expanding ? 'Expanding…' : 'Expand selected'}</button>
          <button data-testid="create-object-set-button" type="button" disabled={!selectedNode} onClick={handleCreateSetFromSelected} className="rounded-lg border border-emerald-400/70 px-3 py-2 text-xs font-semibold text-emerald-100 disabled:border-slate-700 disabled:text-slate-500 disabled:opacity-70">Create object set</button>
          <button data-testid="toolbar-save-graph-button" type="button" onClick={() => activeSavedGraph ? void handleSaveGraph(activeSavedGraph.name, activeSavedGraph) : setSaveAsOpen(true)} disabled={historicalReadonly} className="rounded-lg border border-cyan-400/70 px-3 py-2 text-xs font-semibold text-cyan-100 disabled:border-slate-700 disabled:text-slate-500 disabled:opacity-70">Save graph</button>
          <button data-testid="toolbar-save-as-button" type="button" onClick={() => setSaveAsOpen(true)} disabled={historicalReadonly} className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 disabled:text-slate-500 disabled:opacity-70">Save as</button>
          <button data-testid="duplicate-graph-button" type="button" onClick={() => void handleDuplicateGraph()} disabled={!activeSavedGraph || historicalReadonly} className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 disabled:text-slate-500 disabled:opacity-70">Duplicate</button>
          <button type="button" onClick={() => setShareOpen(true)} className="rounded-lg border border-fuchsia-400/70 px-3 py-2 text-xs font-semibold text-fuchsia-100">Share</button>
          <button type="button" onClick={() => setTemplateWizardOpen(true)} className="rounded-lg border border-amber-300/70 px-3 py-2 text-xs font-semibold text-amber-100">Template</button>
          <button data-testid="open-approval-queue-button" type="button" onClick={() => setApprovalModalOpen(true)} disabled={!changeset || changeset.state !== 'submitted' || governanceRole !== 'approver'} className="rounded-lg border border-violet-400/70 px-3 py-2 text-xs font-semibold text-violet-100 disabled:border-slate-700 disabled:text-slate-500 disabled:opacity-70">Review approval</button>
          <button data-testid="open-publish-dialog-button" type="button" onClick={() => setPublishDialogOpen(true)} disabled={!changeset || changeset.state !== 'approved' || governanceRole !== 'steward'} className="rounded-lg border border-emerald-400/70 px-3 py-2 text-xs font-semibold text-emerald-100 disabled:border-slate-700 disabled:text-slate-500 disabled:opacity-70">Publish</button>
          <button data-testid="fit-view-button" type="button" onClick={() => setFitNonce((value) => value + 1)} className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-cyan-400">Fit view</button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            Layout
            <select data-testid="layout-preset-control" value={layoutPreset} onChange={(event) => handleLayoutChange(event.target.value as GraphLayoutPreset)} className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100">
              {layoutOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-400">
            Fixture
            <select value={fixture} onChange={(event) => { setFixture(event.target.value as GraphFixtureKey); setSelection(null); setActiveFilters([]); setActionError(null); }} className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100">
              {fixtureOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </label>
        </div>
      </div>

      {actionError && <div className="border-b border-red-400/30 bg-red-950/40 px-5 py-2 text-sm text-red-100">{actionError}</div>}
      {savedGraphNotice && <div className="border-b border-cyan-400/30 bg-cyan-950/40 px-5 py-2 text-sm text-cyan-100">{savedGraphNotice}</div>}
      {historicalReadonly && <div data-testid="historical-version-readonly-banner" className="border-b border-amber-400/30 bg-amber-950/40 px-5 py-2 text-sm text-amber-100">Historical version {selectedVersionId} is immutable and readonly. Revert creates a new version instead of mutating history.</div>}
      {governanceState && changeset && <GovernanceSummary
        state={governanceState}
        role={governanceRole}
        selectedVersionId={selectedVersionId}
        simulateConflict={simulatePublishConflict}
        onRoleChange={setGovernanceRole}
        onSelectVersion={setSelectedVersionId}
        onSimulateConflict={setSimulatePublishConflict}
        onValidate={() => void handleGovernanceAction(() => validateChangeset(namespace, changeset.id))}
        onSubmit={() => void handleGovernanceAction(() => submitChangeset(namespace, changeset.id, governanceRole))}
        onOpenApproval={() => setApprovalModalOpen(true)}
        onOpenPublish={() => setPublishDialogOpen(true)}
        onOpenRevert={() => setRevertDialogOpen(true)}
        onFocusIssue={handleValidationIssueFocus}
      />}

      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(520px,1fr)_380px] overflow-hidden">
        <aside className="overflow-auto border-r border-slate-800 bg-slate-950 p-4">
          <h2 className="text-sm font-semibold">Loaded graph</h2>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <Metric label="Nodes" value={visibleNodes.length} testId="visible-node-count" />
            <Metric label="Edges" value={visibleEdges.length} />
            <Metric label="Validation" value={graphViewModel?.stats.validation_issue_count ?? 0} />
            <Metric label="Candidates" value={graphViewModel?.stats.ontology_candidate_count ?? 0} />
            <Metric label="Active events" value={activeEvents.length} />
            <Metric label="Groups" value={groups.length} />
          </dl>
          {graphViewModel?.meta.truncated && (
            <div data-testid="truncation-warning" className="mt-4 rounded-xl border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100">
              Large graph truncated at {graphViewModel.stats.node_cap ?? graphViewModel.nodes.length} nodes. Refine filters before expanding.
            </div>
          )}
          <ReleaseGateSummary viewModel={graphViewModel} />
          <div className="mt-5">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Filter chips</h3>
              {activeFilters.length > 0 && <button type="button" onClick={() => setActiveFilters([])} className="text-[11px] text-cyan-300">Clear</button>}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {filterChips.length ? filterChips.map((chip) => (
                <button data-testid="filter-chip" key={chip.id} type="button" onClick={() => toggleFilter(chip.label)} className={`rounded-full border px-2.5 py-1 text-[11px] ${activeFilters.includes(chip.label) ? 'border-cyan-300 bg-cyan-300 text-slate-950' : 'border-slate-700 text-slate-300'}`}>
                  {chip.label} · {chip.count}
                </button>
              )) : <p className="text-xs text-slate-500">No filters available until graph data loads.</p>}
            </div>
          </div>
          <ObjectSetWorkspace
            objectSets={objectSets}
            activeObjectSet={activeObjectSet}
            onSelectObjectSet={setActiveObjectSet}
            onCompare={handleCompareWithSaved}
            compareSummary={compareSummary}
          />
          <SearchAroundPanel
            objectSet={activeObjectSet}
            relationshipTypes={relationshipTypes}
            steps={traversalSteps}
            preview={traversalPreview}
            loading={traversalLoading}
            hasRunResult={Boolean(traversalProjection)}
            onStepsChange={setTraversalSteps}
            onPreview={handlePreviewTraversal}
            onRun={handleRunTraversal}
            onAddToGraph={handleAddTraversalToGraph}
          />

          <SavedGraphsPanel savedGraphs={savedGraphs} activeGraph={activeSavedGraph} historicalReadonly={historicalReadonly} onOpen={handleOpenSavedGraph} onSaveAs={() => { if (!historicalReadonly) setSaveAsOpen(true); }} onDuplicate={() => void handleDuplicateGraph()} />
          <SavedSelectionsPanel selections={savedSelections} onCreate={handleCreateSelection} onToggleOverlay={handleToggleSelectionOverlay} onDelete={handleDeleteSelection} />
          <SavedStylesPanel styles={graphStyles} activeStyle={activeStyle} onApply={handleApplyStyle} />
          <TemplatePanel templates={graphTemplates} onCreate={() => setTemplateWizardOpen(true)} onRun={(template) => { setActiveTemplate(template); setTemplateRunOpen(true); }} />
          <TimeGroupingPanel timeRange={timeRange} onTimeRangeChange={setTimeRange} activeEvents={activeEvents} totalEvents={allEvents.length} eventsTruncated={eventsTruncated} eventWarnings={graphViewModel?.meta.event_truncation_warnings ?? []} selectedNode={selectedNode} groups={groups} onGroupSelected={handleGroupSelected} onGroupByType={handleGroupByType} onGroupByOwner={handleGroupByOwner} onUngroupSelected={handleUngroupSelected} onUngroupAll={() => { setGroups([]); setSelection(null); }} />
          <InstanceAuthoringPanel
            namespace={namespace}
            nodes={graphViewModel?.nodes ?? []}
            edges={graphViewModel?.edges ?? []}
            relationshipTypes={relationshipTypes}
            selectedNode={selectedNode}
            selectedEdge={selectedEdge}
            historicalReadonly={historicalReadonly}
            onCreateObject={upsertCanvasNode}
            onUpdateObject={upsertCanvasNode}
            onDeleteObject={deleteCanvasNode}
            onCreateRelationship={upsertCanvasEdge}
            onUpdateRelationship={upsertCanvasEdge}
            onDeleteRelationship={deleteCanvasEdge}
            onSelect={setSelection}
          />
          <div className="mt-5 rounded-xl border border-slate-800 p-3 text-xs text-slate-400">
            <p className="font-semibold text-slate-200">Mode guidance</p>
            <p className="mt-1">{mode === 'explore' ? 'Select objects and relationships.' : mode === 'validate' ? 'Validation overlays are read-only until backend rules ship.' : 'Provenance refs are available in the inspector.'}</p>
          </div>
        </aside>

        <main className="relative overflow-auto bg-[radial-gradient(circle_at_1px_1px,rgba(148,163,184,0.24)_1px,transparent_0)] [background-size:28px_28px]">
          <GraphCanvas nodes={displayedNodes} edges={displayedEdges} overlays={savedSelections.filter((item) => item.overlay)} isLoading={isLoading} error={error} hasData={Boolean(graphViewModel)} selection={selection} focusedGraphElementId={focusedGraphElementId} onSelect={(next) => { setSelection(next); setFocusedGraphElementId(next?.id ?? null); }} onRetry={() => void mutate()} fitNonce={fitNonce} />
        </main>

        <aside data-testid="selection-inspector" className="overflow-auto border-l border-slate-800 bg-slate-950 p-4">
          <GraphHistorySidebar versions={savedGraphVersions} selectedVersionId={selectedVersionId} onOpenVersion={handleOpenVersion} onSelectCurrent={() => setSelectedVersionId('current')} />
          <SelectionInspector namespace={namespace} node={selectedNode} edge={selectedEdge} activeTab={inspectorTab} onTabChange={setInspectorTab} lineage={governanceState?.lineage ?? []} timeRange={timeRange} />
        </aside>
      </div>

      {governanceState && changeset && approvalModalOpen && <ApprovalDecisionModal changeset={changeset} role={governanceRole} onClose={() => setApprovalModalOpen(false)} onDecide={(request) => void handleGovernanceAction(async () => { const next = await decideApproval(namespace, changeset.id, governanceRole, request); setApprovalModalOpen(false); return next; })} />}
      {governanceState && changeset && publishDialogOpen && <PublishDialog changeset={changeset} simulateConflict={simulatePublishConflict} onClose={() => setPublishDialogOpen(false)} onPublish={() => void handleGovernanceAction(async () => { const next = await publishChangeset(namespace, changeset.id, governanceRole, simulatePublishConflict); setPublishDialogOpen(false); setSelectedVersionId(next.current_version_id); return next; })} />}
      {governanceState && revertDialogOpen && <RevertDialog versions={governanceState.versions} currentVersionId={governanceState.current_version_id} onClose={() => setRevertDialogOpen(false)} onRevert={(versionId) => void handleGovernanceAction(async () => { const next = await revertVersion(namespace, versionId, governanceRole); setRevertDialogOpen(false); setSelectedVersionId(next.current_version_id); return next; })} />}
      {saveAsOpen && <SaveAsModal onClose={() => setSaveAsOpen(false)} onSave={(name) => void handleSaveGraph(name, null)} />}
      {shareOpen && <ShareGraphModal policies={sharePolicies} redactionPreview={shareRedactionPreview} onLimitedPreview={handleLimitedViewerPreview} onClose={() => setShareOpen(false)} />}
      {templateWizardOpen && <GraphTemplateWizard graphName={activeSavedGraph?.name ?? 'Current graph'} layout={layoutPreset} filters={filterState} activeStyleId={activeStyle?.id} onClose={() => setTemplateWizardOpen(false)} onCreate={(template) => void handleCreateTemplate(template)} />}
      {templateRunOpen && activeTemplate && <TemplateRunModal template={activeTemplate} onClose={() => setTemplateRunOpen(false)} onRun={(values) => void handleTemplateRun(activeTemplate, values)} />}
      {searchOpen && <ObjectSearchModal namespace={namespace} onClose={() => setSearchOpen(false)} onAdd={handleAddResults} onCreateSet={handleCreateSetFromSearch} />}
    </section>
  );
}



function severityCounts(issues: GovernanceValidationIssue[]) {
  return issues.reduce((acc, issue) => ({ ...acc, [issue.severity]: (acc[issue.severity] ?? 0) + 1 }), { error: 0, warning: 0, info: 0 } as Record<'error' | 'warning' | 'info', number>);
}

function GovernanceSummary({ state, role, selectedVersionId, simulateConflict, onRoleChange, onSelectVersion, onSimulateConflict, onValidate, onSubmit, onOpenApproval, onOpenPublish, onOpenRevert, onFocusIssue }: { state: GovernanceStateResponse; role: GovernanceRole; selectedVersionId: string; simulateConflict: boolean; onRoleChange: (role: GovernanceRole) => void; onSelectVersion: (versionId: string) => void; onSimulateConflict: (value: boolean) => void; onValidate: () => void; onSubmit: () => void; onOpenApproval: () => void; onOpenPublish: () => void; onOpenRevert: () => void; onFocusIssue: (issue: GovernanceValidationIssue) => void }) {
  const counts = severityCounts(state.changeset.validation_issues);
  const canSubmit = role === 'steward' && ['draft', 'rejected'].includes(state.changeset.state) && counts.error === 0;
  return (
    <section className="border-b border-slate-800 bg-slate-950/95 px-5 py-3">
      <div data-testid="validation-summary-banner" className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-50">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="font-semibold">Changeset {state.changeset.id} · {state.changeset.state}</p><p className="mt-1 text-xs text-amber-100/80">Errors {counts.error} · Warnings {counts.warning} · Info {counts.info} · Base {state.changeset.base_version_id}</p></div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-slate-300">Role <select aria-label="Governance role" value={role} onChange={(event) => onRoleChange(event.target.value as GovernanceRole)} className="ml-1 rounded border border-slate-700 bg-slate-950 px-2 py-1"><option value="steward">Steward</option><option value="approver">Approver</option><option value="auditor">Auditor</option></select></label>
            <label className="text-xs text-slate-300">Version <select aria-label="Version view" value={selectedVersionId} onChange={(event) => onSelectVersion(event.target.value)} className="ml-1 rounded border border-slate-700 bg-slate-950 px-2 py-1"><option value="current">Current draft/live</option>{state.versions.map((version) => <option key={version.id} value={version.id}>{version.label}</option>)}</select></label>
            <label className="text-xs text-slate-300"><input type="checkbox" checked={simulateConflict} onChange={(event) => onSimulateConflict(event.target.checked)} /> Simulate stale publish</label>
            <button data-testid="governance-validate-button" type="button" onClick={onValidate} disabled={role === 'auditor'} className="rounded-lg bg-amber-200 px-2 py-1 text-xs font-bold text-slate-950 disabled:opacity-40">Validate</button>
            <button data-testid="governance-submit-button" type="button" onClick={onSubmit} disabled={!canSubmit} className="rounded-lg bg-cyan-300 px-2 py-1 text-xs font-bold text-slate-950 disabled:opacity-40">Submit</button>
            <button data-testid="governance-approval-queue-button" type="button" onClick={onOpenApproval} disabled={role !== 'approver' || state.changeset.state !== 'submitted'} className="rounded-lg border border-violet-300 px-2 py-1 text-xs font-semibold text-violet-100 disabled:opacity-40">Approval queue</button>
            <button data-testid="governance-publish-button" type="button" onClick={onOpenPublish} disabled={role !== 'steward' || state.changeset.state !== 'approved'} className="rounded-lg border border-emerald-300 px-2 py-1 text-xs font-semibold text-emerald-100 disabled:opacity-40">Publish</button>
            <button data-testid="governance-revert-button" type="button" onClick={onOpenRevert} disabled={role !== 'steward'} className="rounded-lg border border-slate-600 px-2 py-1 text-xs font-semibold text-slate-200 disabled:opacity-40">Revert</button>
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-800 p-3"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Validation issues</h3><div className="mt-2 space-y-2">{state.changeset.validation_issues.length ? state.changeset.validation_issues.map((issue) => <button data-testid="validation-issue-row" key={issue.id} type="button" onClick={() => onFocusIssue(issue)} className="w-full rounded-lg border border-slate-800 p-2 text-left text-xs hover:border-amber-300"><span className="font-semibold text-slate-100">{issue.severity.toUpperCase()} · {issue.category}</span><span className="block text-slate-400">{issue.message}</span></button>) : <p className="text-xs text-emerald-200">No blocking issues. Ready to submit.</p>}</div></div>
        <div data-testid="changeset-diff-preview" className="rounded-xl border border-slate-800 p-3"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Changeset diff preview</h3><div className="mt-2 space-y-2">{state.changeset.diff.map((item) => <div key={item.id} className="rounded-lg bg-slate-900 p-2 text-xs"><p className="font-semibold text-slate-200">{item.action} {item.label}</p><p className="text-rose-200">− {item.before ?? 'none'}</p><p className="text-emerald-200">+ {item.after ?? 'none'}</p></div>)}</div></div>
        <div className="space-y-3"><div data-testid="approval-queue" className="rounded-xl border border-violet-400/30 p-3"><h3 className="text-xs font-bold uppercase tracking-wider text-violet-200">Approval queue</h3><p className="mt-2 text-xs text-slate-300">{state.approval_queue.length ? `${state.approval_queue.length} submitted changeset awaiting decision.` : 'No submitted changesets.'}</p>{state.changeset.rejection_comment && <p className="mt-2 text-xs text-rose-200">Rejected: {state.changeset.rejection_comment}</p>}</div><div data-testid="audit-timeline" className="rounded-xl border border-cyan-400/30 p-3"><h3 className="text-xs font-bold uppercase tracking-wider text-cyan-200">Audit timeline</h3><ol className="mt-2 space-y-1 text-xs text-slate-300">{state.audit_events.map((event) => <li key={event.id}><span className="font-mono text-slate-500">{event.timestamp}</span> · {event.actor} · {event.action}</li>)}</ol></div></div>
      </div>
    </section>
  );
}

function ApprovalDecisionModal({ changeset, role, onClose, onDecide }: { changeset: import('./types').ChangeSetResponse; role: GovernanceRole; onClose: () => void; onDecide: (request: import('./types').ApprovalDecisionRequest) => void }) {
  const [decision, setDecision] = useState<'approve' | 'reject'>('approve');
  const [comment, setComment] = useState('Looks consistent with evidence and lineage requirements.');
  const rejectMissing = decision === 'reject' && !comment.trim();
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6"><div data-testid="approval-decision-modal" className="w-full max-w-2xl rounded-2xl border border-violet-400/40 bg-slate-950 p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Approval decision</h2><button type="button" onClick={onClose}>Close</button></div><p className="mt-2 text-sm text-slate-400">{changeset.id} · role {role}</p><div data-testid="changeset-diff-preview" className="mt-4 rounded-xl bg-slate-900 p-3 text-xs">{changeset.diff.map((item) => <p key={item.id}>{item.label}: {item.before} → {item.after}</p>)}</div><label className="mt-4 block text-sm">Decision<select value={decision} onChange={(event) => { const next = event.target.value as 'approve' | 'reject'; setDecision(next); if (next === 'reject') setComment(''); }} className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2"><option value="approve">Approve</option><option value="reject">Reject</option></select></label><label className="mt-3 block text-sm">Comment<textarea data-testid="approval-comment-input" value={comment} onChange={(event) => setComment(event.target.value)} className="mt-1 min-h-24 w-full rounded border border-slate-700 bg-slate-900 p-2" /></label>{rejectMissing && <p className="mt-2 text-sm text-rose-200">Reject comment required.</p>}<div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded border border-slate-700 px-3 py-2 text-sm">Cancel</button><button type="button" disabled={rejectMissing || role !== 'approver'} onClick={() => onDecide({ decision, comment })} className="rounded bg-violet-300 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">Submit decision</button></div></div></div>;
}

function PublishDialog({ changeset, simulateConflict, onClose, onPublish }: { changeset: import('./types').ChangeSetResponse; simulateConflict: boolean; onClose: () => void; onPublish: () => void }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6"><div data-testid="publish-dialog" className="w-full max-w-2xl rounded-2xl border border-emerald-400/40 bg-slate-950 p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Publish immutable version</h2><button type="button" onClick={onClose}>Close</button></div>{simulateConflict && <p className="mt-3 rounded-lg border border-red-400/40 bg-red-950/40 p-2 text-sm text-red-100">STALE_CHANGESET_CONFLICT will be returned to model concurrent publish protection.</p>}<div data-testid="publish-diff-preview" className="mt-4 rounded-xl bg-slate-900 p-3 text-xs">{changeset.diff.map((item) => <p key={item.id}>{item.action} · {item.label}: {item.before} → {item.after}</p>)}</div><p className="mt-3 text-sm text-slate-300">Publishing creates a new immutable, auditable version from {changeset.base_version_id}.</p><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded border border-slate-700 px-3 py-2 text-sm">Cancel</button><button type="button" onClick={onPublish} className="rounded bg-emerald-300 px-3 py-2 text-sm font-bold text-slate-950">Publish version</button></div></div></div>;
}

function RevertDialog({ versions, currentVersionId, onClose, onRevert }: { versions: import('./types').PublishedVersionRef[]; currentVersionId: string; onClose: () => void; onRevert: (versionId: string) => void }) {
  const [target, setTarget] = useState(versions.find((version) => version.id !== currentVersionId)?.id ?? versions[0]?.id ?? '');
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6"><div data-testid="revert-dialog" className="w-full max-w-lg rounded-2xl border border-amber-400/40 bg-slate-950 p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Create revert version</h2><button type="button" onClick={onClose}>Close</button></div><p className="mt-2 text-sm text-slate-300">Revert never mutates historical versions; it creates a new immutable version pointing back to the selected target.</p><select aria-label="Revert target version" value={target} onChange={(event) => setTarget(event.target.value)} className="mt-4 w-full rounded border border-slate-700 bg-slate-900 p-2">{versions.map((version) => <option key={version.id} value={version.id}>{version.label}</option>)}</select><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded border border-slate-700 px-3 py-2 text-sm">Cancel</button><button type="button" disabled={!target} onClick={() => onRevert(target)} className="rounded bg-amber-200 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">Create new revert version</button></div></div></div>;
}

function ObjectSetWorkspace({ objectSets, activeObjectSet, onSelectObjectSet, onCompare, compareSummary }: { objectSets: ObjectSetRef[]; activeObjectSet: ObjectSetRef | null; onSelectObjectSet: (set: ObjectSetRef | null) => void; onCompare: (set: ObjectSetRef) => void; compareSummary: ObjectSetCompareSummary | null }) {
  return (
    <div className="mt-5 space-y-3">
      <section data-testid="object-set-picker" className="rounded-xl border border-emerald-400/30 bg-emerald-950/10 p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-200">Object sets</h3>
          <span className="text-[11px] text-slate-500">{objectSets.length} saved/local</span>
        </div>
        <select value={activeObjectSet?.id ?? ''} onChange={(event) => onSelectObjectSet(objectSets.find((set) => set.id === event.target.value) ?? null)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-2 text-xs text-slate-100">
          <option value="">Choose object set</option>
          {objectSets.map((set) => <option key={set.id} value={set.id}>{set.name} · {set.object_ids.length}</option>)}
        </select>
        {activeObjectSet ? <ObjectSetCard objectSet={activeObjectSet} /> : <p className="mt-2 text-xs text-slate-500">Select a graph node or search results, then create an object set.</p>}
      </section>
      <section data-testid="saved-object-set-panel" className="rounded-xl border border-slate-800 p-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Saved sets</h3>
        <div className="mt-2 space-y-2">
          {objectSets.filter((set) => set.source === 'saved').map((set) => (
            <button key={set.id} type="button" onClick={() => { onSelectObjectSet(set); onCompare(set); }} className="w-full rounded-lg border border-slate-800 p-2 text-left text-xs hover:border-emerald-400">
              <span className="block font-semibold text-slate-200">{set.name}</span>
              <span className="text-slate-500">{set.object_ids.length} objects · compare/load</span>
            </button>
          ))}
        </div>
        {compareSummary && (
          <div data-testid="object-set-compare-summary" className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
            <div className="rounded-lg bg-slate-900 p-2"><p className="text-slate-500">Added</p><p className="font-bold text-emerald-200">{compareSummary.added_count}</p></div>
            <div className="rounded-lg bg-slate-900 p-2"><p className="text-slate-500">Removed</p><p className="font-bold text-rose-200">{compareSummary.removed_count}</p></div>
            <div className="rounded-lg bg-slate-900 p-2"><p className="text-slate-500">Overlap</p><p className="font-bold text-cyan-200">{compareSummary.overlap_count}</p></div>
          </div>
        )}
      </section>
    </div>
  );
}

function ObjectSetCard({ objectSet }: { objectSet: ObjectSetRef }) {
  return (
    <div className="mt-3 rounded-lg bg-slate-900 p-2 text-xs">
      <p className="font-semibold text-slate-200">{objectSet.name}</p>
      <p className="mt-1 text-slate-500">{objectSet.source} · {objectSet.object_ids.length} objects</p>
      <div className="mt-2 flex flex-wrap gap-1">
        {Object.entries(objectSet.object_type_counts).map(([type, count]) => <span key={type} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">{type}: {count}</span>)}
      </div>
      {objectSet.warnings?.map((warning) => <p key={warning} className="mt-2 text-[11px] text-amber-200">{warning}</p>)}
    </div>
  );
}

function SearchAroundPanel({ objectSet, relationshipTypes, steps, preview, loading, hasRunResult, onStepsChange, onPreview, onRun, onAddToGraph }: { objectSet: ObjectSetRef | null; relationshipTypes: RelationshipTypeRef[]; steps: SearchAroundStepRequest[]; preview: SearchAroundPreviewResponse | null; loading: boolean; hasRunResult: boolean; onStepsChange: (steps: SearchAroundStepRequest[]) => void; onPreview: () => void; onRun: () => void; onAddToGraph: () => void }) {
  const localIssues = steps.flatMap((step, index) => {
    const relationship = relationshipTypes.find((item) => item.id === step.relationship_type_id);
    if (!relationship) return [{ code: 'RELATIONSHIP_REQUIRED', message: 'Choose a relationship type.', step_index: index, severity: 'error' as const }];
    if (relationship.retired) return [{ code: 'RELATIONSHIP_RETIRED', message: `${relationship.label} is retired.`, step_index: index, severity: 'error' as const }];
    if (relationship.id === 'generates' && step.direction === 'inbound') return [{ code: 'INCOMPATIBLE_DIRECTION', message: 'Inbound generates traversal is incompatible for this mock start set.', step_index: index, severity: 'error' as const }];
    return [];
  });
  const issues = preview?.validation_issues?.length ? preview.validation_issues : localIssues;
  const hasBlockingIssue = issues.some((issue) => issue.severity === 'error') || !objectSet;
  const updateStep = (index: number, patch: Partial<SearchAroundStepRequest>) => onStepsChange(steps.map((step, stepIndex) => stepIndex === index ? { ...step, ...patch } : step));
  return (
    <section data-testid="search-around-panel" className="mt-5 rounded-xl border border-cyan-400/30 bg-cyan-950/10 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-cyan-200">Search Around</h3>
        <button type="button" onClick={() => onStepsChange([...steps, { relationship_type_id: relationshipTypes[0]?.id ?? '', direction: 'outbound' }])} className="text-[11px] font-semibold text-cyan-300">+ Step</button>
      </div>
      <p className="mt-1 text-xs text-slate-500">Start: {objectSet?.name ?? 'No object set selected'}</p>
      <div className="mt-3 space-y-2">
        {steps.map((step, index) => (
          <div data-testid="traversal-step" key={index} className="rounded-lg border border-slate-800 p-2">
            <label className="block text-[11px] text-slate-500">Relationship</label>
            <select data-testid="relationship-type-picker" value={step.relationship_type_id} onChange={(event) => updateStep(index, { relationship_type_id: event.target.value })} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">
              {relationshipTypes.map((relationship) => <option key={relationship.id} value={relationship.id}>{relationship.label}{relationship.retired ? ' (retired)' : ''}</option>)}
            </select>
            <label className="mt-2 block text-[11px] text-slate-500">Direction</label>
            <select data-testid="direction-picker" value={step.direction} onChange={(event) => updateStep(index, { direction: event.target.value as SearchAroundStepRequest['direction'] })} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">
              <option value="outbound">Outbound</option>
              <option value="inbound">Inbound</option>
              <option value="either">Either</option>
            </select>
          </div>
        ))}
      </div>
      {issues.map((issue) => <div data-testid="validation-issue" key={`${issue.code}-${issue.step_index ?? 'global'}`} className="mt-2 rounded-lg border border-amber-400/40 bg-amber-400/10 p-2 text-xs text-amber-100">Step {(issue.step_index ?? 0) + 1}: {issue.message}</div>)}
      <div data-testid="traversal-preview-summary" className="mt-3 rounded-lg bg-slate-900 p-2 text-xs">
        <p className="font-semibold text-slate-200">Preview summary</p>
        {preview ? <><p className="mt-1 text-slate-400">{preview.total_count} objects · {preview.edge_count} relationships</p><div className="mt-2 flex flex-wrap gap-1">{Object.entries(preview.counts_by_object_type).map(([type, count]) => <span key={type} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px]">{type}: {count}</span>)}</div>{preview.truncated && <p className="mt-2 text-amber-200">Result capped/truncated at {preview.limit ?? 'configured'} objects. {preview.warnings.join(' ')}</p>}</> : <p className="mt-1 text-slate-500">Preview before running traversal.</p>}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onPreview} disabled={!objectSet || loading} className="rounded-lg border border-cyan-400 px-2 py-1.5 text-xs font-semibold text-cyan-100 disabled:opacity-40">{loading ? 'Working…' : 'Preview'}</button>
        <button data-testid="run-traversal-button" type="button" onClick={onRun} disabled={hasBlockingIssue || loading} className="rounded-lg bg-cyan-300 px-2 py-1.5 text-xs font-bold text-slate-950 disabled:opacity-40">Run traversal</button>
        <button data-testid="add-traversal-to-graph-button" type="button" onClick={onAddToGraph} disabled={!hasRunResult} className="rounded-lg border border-emerald-400 px-2 py-1.5 text-xs font-semibold text-emerald-100 disabled:opacity-40">Add traversal to graph</button>
      </div>
    </section>
  );
}


function buildGroupedView(nodes: CanvasNode[], edges: CanvasEdge[], groups: GraphGroup[]): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  if (!groups.length) return { nodes, edges };
  const memberToGroup = new Map<string, GraphGroup>();
  groups.forEach((group) => group.member_ids.forEach((id) => memberToGroup.set(id, group)));
  const groupedNodes = groups
    .map((group, index) => makeGroupNode(group, nodes.filter((node) => group.member_ids.includes(node.id)), index))
    .filter((node) => node.group?.member_ids.length);
  const passthroughNodes = nodes.filter((node) => !memberToGroup.has(node.id));
  const edgeBuckets = new Map<string, CanvasEdge[]>();
  edges.forEach((edge) => {
    const source = memberToGroup.get(edge.source)?.id ?? edge.source;
    const target = memberToGroup.get(edge.target)?.id ?? edge.target;
    if (source === target) return;
    const key = `${source}->${target}`;
    edgeBuckets.set(key, [...(edgeBuckets.get(key) ?? []), edge]);
  });
  const groupedEdges = Array.from(edgeBuckets.entries()).map(([key, bucket]) => {
    const [source, target] = key.split('->');
    if (bucket.length === 1 && bucket[0].source === source && bucket[0].target === target) return bucket[0];
    const containedObjectIds = Array.from(new Set(bucket.flatMap((edge) => [edge.source, edge.target])));
    const redactedCount = bucket.filter((edge) => edge.redacted || edge.permissions.level === 'limited').length;
    const groupedEdge: GroupedEdge = {
      id: `grouped-edge-${key.replace(/[^a-z0-9]+/gi, '-')}`,
      label: `${bucket.length} grouped relationships`,
      source,
      target,
      contained_edge_ids: bucket.map((edge) => edge.id),
      contained_object_ids: containedObjectIds,
      aggregate_labels: Array.from(new Set(bucket.map((edge) => edge.label))),
      redacted_count: redactedCount,
      warnings: [containedObjectIds.length > MAX_GROUP_LIST ? `Grouped edge contains ${containedObjectIds.length} object identities; list is capped.` : null, redactedCount ? 'Mixed-permission grouped edge: restricted details are redacted.' : null].filter((item): item is string => Boolean(item)),
    };
    const events = bucket.flatMap((edge) => edge.events);
    return { ...bucket[0], id: groupedEdge.id, source, target, label: groupedEdge.label, badges: ['Grouped edge', ...groupedEdge.aggregate_labels], redacted: redactedCount > 0, properties: { containedEdgeIds: groupedEdge.contained_edge_ids, containedObjectIds: groupedEdge.contained_object_ids }, permissions: redactedCount ? { level: 'limited' as const, reason: 'Grouped edge has mixed permissions; contained restricted objects are redacted.', allowedActions: ['view_topology'] } : bucket[0].permissions, events, activeEventCount: events.filter((event) => event.status === 'active').length, totalEventCount: events.length, timeSeries: bucket.flatMap((edge) => edge.timeSeries), groupedEdge };
  });
  return { nodes: [...passthroughNodes, ...groupedNodes], edges: groupedEdges };
}

function TimeGroupingPanel({ timeRange, onTimeRangeChange, activeEvents, totalEvents, eventsTruncated, eventWarnings, selectedNode, groups, onGroupSelected, onGroupByType, onGroupByOwner, onUngroupSelected, onUngroupAll }: { timeRange: GraphTimeRange; onTimeRangeChange: (range: GraphTimeRange) => void; activeEvents: GraphEvent[]; totalEvents: number; eventsTruncated: boolean; eventWarnings: string[]; selectedNode?: CanvasNode; groups: GraphGroup[]; onGroupSelected: () => void; onGroupByType: () => void; onGroupByOwner: () => void; onUngroupSelected: () => void; onUngroupAll: () => void }) {
  const shownEvents = activeEvents.slice(0, MAX_EVENT_LIST);
  const noEvents = activeEvents.length === 0;
  return (
    <section className="mt-5 space-y-3 rounded-xl border border-cyan-400/30 bg-cyan-950/10 p-3 text-xs">
      <div data-testid="time-selection-controls">
        <div className="flex items-center justify-between gap-2"><h3 className="font-bold uppercase tracking-wider text-cyan-200">Events / time grouping</h3><span className="text-slate-500">{activeEvents.length}/{totalEvents} active</span></div>
        <label className="mt-2 block text-slate-400">Start<input aria-label="Time range start" value={timeRange.start} onChange={(event) => onTimeRangeChange({ ...timeRange, start: event.target.value })} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100" /></label>
        <label className="mt-2 block text-slate-400">End<input aria-label="Time range end" value={timeRange.end} onChange={(event) => onTimeRangeChange({ ...timeRange, end: event.target.value })} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100" /></label>
      </div>
      <div data-testid="timeline-scrubber" className="rounded-lg bg-slate-900 p-2">
        <label className="block text-slate-400">Timeline scrubber · active window</label>
        <input type="range" min={0} max={24} value={new Date(timeRange.start).getUTCHours()} onChange={(event) => { const start = new Date(timeRange.start); start.setUTCHours(Number(event.target.value)); const end = new Date(start); end.setUTCHours(start.getUTCHours() + 4); onTimeRangeChange({ start: start.toISOString(), end: end.toISOString() }); }} className="mt-2 w-full" />
        <p className="mt-1 text-slate-500">{timeRange.start} → {timeRange.end}</p>
      </div>
      <div data-testid="events-panel" className="rounded-lg border border-slate-800 p-2">
        <div className="flex items-center justify-between"><span className="font-semibold text-slate-200">Events panel</span><span className="text-slate-500">active {activeEvents.length} / total {totalEvents}</span></div>
        <div className="mt-2 flex flex-wrap gap-1"><span className="rounded bg-red-900 px-1.5 py-0.5 text-red-100">critical</span><span className="rounded bg-amber-900 px-1.5 py-0.5 text-amber-100">warning</span><span className="rounded bg-sky-900 px-1.5 py-0.5 text-sky-100">info</span><span className="rounded bg-emerald-900 px-1.5 py-0.5 text-emerald-100">active</span></div>
        {noEvents ? <p className="mt-2 rounded bg-slate-900 p-2 text-slate-500">No events in this time range.</p> : shownEvents.map((event) => <div key={event.id} className="mt-2 rounded bg-slate-900 p-2"><p className="font-semibold text-slate-100">{event.severity} · {event.status}</p><p className="text-slate-400">{event.summary}</p></div>)}
        {eventsTruncated && <p data-testid="event-truncation-warning" className="mt-2 rounded border border-amber-400/40 bg-amber-400/10 p-2 text-amber-100">Event list capped at {MAX_EVENT_LIST}. {eventWarnings.join(' ')}</p>}
      </div>
      <div data-testid="group-context-menu" className="rounded-lg border border-slate-800 p-2">
        <p className="font-semibold text-slate-200">Grouping controls</p>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <button type="button" onClick={onGroupSelected} disabled={!selectedNode || Boolean(selectedNode.group)} className="rounded border border-cyan-400 px-2 py-1 text-cyan-100 disabled:opacity-40">Group selected</button>
          <button type="button" onClick={onGroupByType} className="rounded border border-cyan-400 px-2 py-1 text-cyan-100">Group by type</button>
          <button type="button" onClick={onGroupByOwner} className="rounded border border-cyan-400 px-2 py-1 text-cyan-100">Group by owner</button>
          <button data-testid="ungroup-button" type="button" onClick={selectedNode?.group ? onUngroupSelected : onUngroupAll} disabled={!groups.length} className="rounded border border-rose-400 px-2 py-1 text-rose-100 disabled:opacity-40">{selectedNode?.group ? 'Ungroup selected' : 'Ungroup all'}</button>
        </div>
        <p className="mt-2 text-slate-500">{groups.length} active groups. Grouped transactional objects render as grouped edges with contained identities preserved.</p>
      </div>
    </section>
  );
}


function ReleaseGateSummary({ viewModel }: { viewModel: CanvasViewModel | null }) {
  const flags = viewModel?.meta.feature_flags;
  const disabled = disabledFeatureFlags(flags);
  const permissions = viewModel?.permissions;
  const redactionNotice = permissions && (permissions.redacted_nodes > 0 || permissions.redacted_edges > 0)
    ? permissions.notice
    : 'No permission redaction applied to the current projection.';

  return (
    <section className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-300" aria-label="Release gate contract summary">
      <p className="font-semibold text-slate-100">Release gates</p>
      <p className="mt-2">Projection contract: nodes, edges, stats, meta · namespace {viewModel?.meta.namespace ?? 'loading'} · generated {viewModel?.meta.generated_at ?? 'pending'}</p>
      <p data-testid="permission-summary" className="mt-2 rounded-lg bg-slate-950 p-2">Permission summary: {permissions?.level ?? 'pending'} · redacted nodes {permissions?.redacted_nodes ?? 0} · redacted edges {permissions?.redacted_edges ?? 0}</p>
      <p data-testid="redaction-notice" className="mt-2 rounded-lg border border-red-400/20 bg-red-950/20 p-2 text-red-100">{redactionNotice}</p>
      {disabled.length > 0 ? (
        <p data-testid="feature-disabled-state" className="mt-2 rounded-lg border border-amber-400/30 bg-amber-950/30 p-2 text-amber-100">Feature disabled: {disabled.join(', ')}</p>
      ) : (
        <p data-testid="feature-disabled-state" className="mt-2 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-400">Unsupported backend-only functions remain disabled until feature flags are enabled.</p>
      )}
    </section>
  );
}

function Metric({ label, value, testId }: { label: string; value: number; testId?: string }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-900 p-3"><dt className="text-slate-500">{label}</dt><dd data-testid={testId} className="mt-1 text-xl font-semibold text-slate-100">{value}</dd></div>;
}

function GraphCanvas({ nodes, edges, overlays, isLoading, error, hasData, selection, focusedGraphElementId, onSelect, onRetry, fitNonce }: { nodes: CanvasNode[]; edges: CanvasEdge[]; overlays: SavedSelectionResponse[]; isLoading: boolean; error?: Error; hasData: boolean; selection: GraphSelection; focusedGraphElementId?: string | null; onSelect: (selection: GraphSelection) => void; onRetry: () => void; fitNonce: number }) {
  if (isLoading) return <div data-testid="graph-loading-state" className="flex h-full items-center justify-center text-sm text-slate-300"><span data-testid="loading-skeleton" className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-4 py-2">Loading graph projection…</span></div>;
  if (error) { const details = canonicalErrorDetails(error); return <div data-testid="graph-error-state" className="flex h-full items-center justify-center"><div className="rounded-2xl border border-red-400/40 bg-red-950/30 p-6 text-center"><p className="font-semibold text-red-100">Graph projection unavailable</p><p data-testid="canonical-error-message" className="mt-2 text-sm text-red-200">{details.code ? `${details.code}: ${details.message}` : details.message}</p>{details.requestId && <p data-testid="request-id" className="mt-2 font-mono text-xs text-red-200/80">Request ID: {details.requestId}</p>}{details.validationIssues.length > 0 && <ul className="mt-2 text-left text-xs text-red-100">{details.validationIssues.map((issue) => <li key={issue}>• {issue}</li>)}</ul>}<button data-testid="retry-button" type="button" onClick={onRetry} className="mt-4 rounded-lg bg-red-200 px-3 py-2 text-xs font-bold text-red-950">Retry</button></div></div>; }
  if (hasData && nodes.length === 0) return <div data-testid="graph-empty-state" className="flex h-full items-center justify-center"><div data-testid="empty-state" className="max-w-sm rounded-2xl border border-slate-700 bg-slate-950/90 p-6 text-center"><p className="text-lg font-semibold">Start with object search</p><p className="mt-2 text-sm text-slate-400">This namespace has no loaded ontology graph in the selected fixture. Search for objects or switch fixtures.</p></div></div>;

  const overlayTargets = overlays
    .flatMap((overlay) => overlay.members.map((memberId) => ({ overlay, node: nodes.find((item) => item.id === memberId) })))
    .filter((item): item is { overlay: SavedSelectionResponse; node: CanvasNode } => Boolean(item.node));

  return (
    <div data-testid="graph-canvas" data-fit-nonce={fitNonce} className="relative min-h-[900px] min-w-[900px]">
      <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
      {edges.map((edge) => {
          const source = nodes.find((node) => node.id === edge.source);
          const target = nodes.find((node) => node.id === edge.target);
          if (!source || !target) return null;
          return <line key={edge.id} x1={source.x + 70} y1={source.y + 34} x2={target.x + 70} y2={target.y + 34} stroke={edge.style.color} strokeWidth={Math.max(1, edge.style.weight)} strokeOpacity={edge.style.opacity} />;
        })}
      </svg>
      <div className="pointer-events-none absolute inset-0 z-10" aria-hidden="true">
        {overlayTargets.map(({ overlay, node }) => (
          <div data-testid="selection-overlay" key={`${overlay.id}-${node.id}`} className="absolute rounded-[1.25rem] border-2 border-dashed" style={{ left: node.x - 6, top: node.y - 6, width: 162, height: 82, borderColor: overlay.color, boxShadow: `0 0 0 3px ${overlay.color}22` }} />
        ))}
      </div>
      {edges.map((edge) => {
        const source = nodes.find((node) => node.id === edge.source);
        const target = nodes.find((node) => node.id === edge.target);
        if (!source || !target) return null;
        return <button data-testid={edge.groupedEdge ? 'grouped-edge' : focusedGraphElementId === edge.id ? 'focused-graph-element' : undefined} key={edge.id} type="button" onClick={() => onSelect({ kind: 'edge', id: edge.id })} className={`absolute -translate-x-1/2 rounded-full border px-2 py-1 text-[10px] ${edge.groupedEdge ? 'border-fuchsia-300 bg-fuchsia-950 text-fuchsia-100' : selection?.kind === 'edge' && selection.id === edge.id ? 'border-cyan-300 bg-cyan-300 text-slate-950' : 'border-slate-700 bg-slate-950 text-slate-300'}`} style={{ left: (source.x + target.x) / 2 + 70, top: (source.y + target.y) / 2 + 25 }}>{edge.label}{edge.activeEventCount > 0 && <span data-testid="event-badge" className="ml-1 rounded-full bg-red-500 px-1 text-white">{edge.activeEventCount}</span>}</button>;
      })}
      {nodes.map((node) => (
        <button data-testid={node.group ? 'grouped-node' : focusedGraphElementId === node.id ? 'focused-graph-element' : node.redacted ? 'redacted-node' : undefined} key={node.id} type="button" onClick={() => onSelect({ kind: 'node', id: node.id })} className={`absolute w-[150px] rounded-2xl border p-3 text-left shadow-2xl transition hover:-translate-y-0.5 ${node.group ? 'border-fuchsia-300 ring-2 ring-fuchsia-300/30' : selection?.kind === 'node' && selection.id === node.id ? 'border-cyan-300 ring-2 ring-cyan-300/40' : 'border-slate-700'}`} style={{ left: node.x, top: node.y, background: node.redacted ? 'rgba(127,29,29,0.9)' : node.group ? 'rgba(59,7,100,0.92)' : 'rgba(15,23,42,0.95)' }}>
          <div className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ background: node.style.color }} /><span className="truncate text-sm font-semibold">{node.label}</span>{node.activeEventCount > 0 && <span data-testid="event-badge" className="rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">{node.activeEventCount}</span>}</div>
          {node.typeLabel !== node.label && <p className="mt-1 truncate text-xs text-slate-400">{node.typeLabel}</p>}
          <div className="mt-2 flex flex-wrap gap-1">{node.badges.filter((badge) => badge !== node.label).slice(0, 3).map((badge) => <span key={badge} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">{badge}</span>)}</div>
        </button>
      ))}
    </div>
  );
}

function SelectionInspector({ namespace, node, edge, activeTab, onTabChange, lineage, timeRange }: { namespace: string; node?: CanvasNode; edge?: CanvasEdge; activeTab: InspectorTab; onTabChange: (tab: InspectorTab) => void; lineage: import('./types').LineageResponse[]; timeRange: GraphTimeRange }) {
  const detail = useOntologyNodeDetail(namespace, node?.id);
  const hydratedNode = useMemo(() => {
    if (!node || !detail.data) return node;
    const detailPatch = EnterpriseMapProjectionAdapter.detailToNodePatch(detail.data);
    const isTopologyOnlyGroupedNode = Boolean(node.group && (node.redacted || node.permissions.level === 'limited'));

    if (isTopologyOnlyGroupedNode) {
      return {
        ...node,
        ...detailPatch,
        label: detail.data.label || node.label,
        redacted: true,
        properties: {},
        permissions: node.permissions,
      };
    }

    return { ...node, ...detailPatch, label: detail.data.label || node.label };
  }, [detail.data, node]);
  const selected = hydratedNode ?? edge;
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Inspector</p>
      <h2 className="mt-1 text-lg font-semibold">{hydratedNode ? hydratedNode.label : edge ? edge.label : 'No selection'}</h2>
      <div className="mt-4 flex flex-wrap gap-1">
        {inspectorTabs.map((tab) => <button data-testid={tab === 'Properties' ? 'inspector-tab-properties' : tab === 'Lineage' ? 'lineage-tab' : undefined} key={tab} type="button" onClick={() => onTabChange(tab)} className={`rounded-lg px-2 py-1 text-[11px] ${activeTab === tab ? 'bg-cyan-300 text-slate-950' : 'bg-slate-900 text-slate-300'}`}>{tab}</button>)}
      </div>
      {!selected ? <p className="mt-6 rounded-xl border border-slate-800 p-4 text-sm text-slate-400">Select a node or relationship to inspect normalized fields.</p> : (
        <>
          {node && detail.isLoading && <p data-testid="node-detail-loading" className="mt-4 rounded-xl border border-cyan-400/30 bg-cyan-950/30 p-3 text-sm text-cyan-100">Hydrating node detail…</p>}
          {node && detail.error && <div className="mt-4 rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-100"><p>{canonicalErrorMessage(detail.error)}</p><button data-testid="retry-button" type="button" onClick={() => void detail.mutate()} className="mt-2 rounded-lg bg-red-200 px-2 py-1 text-xs font-bold text-red-950">Retry detail</button></div>}
          <InspectorTabContent node={hydratedNode} edge={edge} tab={activeTab} lineage={lineage} timeRange={timeRange} />
        </>
      )}
    </div>
  );
}

function InspectorTabContent({ node, edge, tab, lineage, timeRange }: { node?: CanvasNode; edge?: CanvasEdge; tab: InspectorTab; lineage: import('./types').LineageResponse[]; timeRange: GraphTimeRange }) {
  const selected = node ?? edge;
  if (!selected) return null;
  if (tab === 'Events') return <EventsInspectorPanel selected={selected} timeRange={timeRange} />;
  if (tab === 'Time Series') return <TimeSeriesInspectorPanel selected={selected} />;
  if (tab === 'Properties') {
    const entries = Object.entries(selected.properties);
    return <div className="mt-4 space-y-2">{selected.redacted ? <p data-testid="redaction-notice" className="rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-100">Properties redacted by permission policy.</p> : entries.length ? entries.map(([key, value]) => <div key={key} className="rounded-lg bg-slate-900 p-2 text-xs"><span className="text-slate-500">{key}</span><p className="mt-1 text-slate-200">{String(value)}</p></div>) : <p className="text-sm text-slate-500">No properties supplied.</p>}</div>;
  }
  if (tab === 'Relationships') return <div className="mt-4 text-sm text-slate-300">{node ? 'Use Expand selected or the Instance authoring panel to manage adjacent topology.' : `${edge?.source} → ${edge?.target}`}</div>;
  if (tab === 'Validation') return <ListBlock items={selected.validation.issues} empty="No validation issues." />;
  if (tab === 'Provenance') return <ListBlock items={selected.provenance.refs} empty="No provenance references." />;
  if (tab === 'Lineage') { const item = lineage.find((entry) => entry.entity_id === selected.id) ?? lineage[0]; return <div className="mt-4 rounded-xl border border-cyan-400/30 bg-cyan-950/20 p-3 text-sm text-cyan-50"><p className="font-semibold">Lineage for {item?.entity_id ?? selected.id}</p><p className="mt-2 text-xs text-slate-300">Upstream: {item?.upstream.join(', ') || 'none'}</p><p className="mt-1 text-xs text-slate-300">Downstream: {item?.downstream.join(', ') || 'none'}</p><p className="mt-1 text-xs text-slate-400">Sources: {item?.source_refs.join(', ') || 'none'}</p></div>; }
  if (tab === 'Permissions') return <div data-testid="permission-summary" className="mt-4 rounded-xl bg-slate-900 p-3 text-sm"><p>Level: <span className="font-semibold">{selected.permissions.level}</span></p><p className="mt-2 text-slate-400">{selected.permissions.reason ?? 'Read-only access granted for Scenario 03.'}</p><p className="mt-2 text-xs text-slate-500">Actions: {selected.permissions.allowedActions.join(', ') || 'none'}</p></div>;
  return <div className="mt-4 space-y-3 text-sm text-slate-300"><p>ID: <span className="font-mono text-slate-100">{selected.id}</span></p>{'badges' in selected && <p>Badges: {selected.badges.join(', ') || 'none'}</p>}<p>{selected.redacted ? 'This item is redacted; topology only.' : 'Normalized canvas view-model item.'}</p>{node?.group && <GroupedObjectList group={node.group} />}{edge?.groupedEdge && <GroupedEdgeObjectList groupedEdge={edge.groupedEdge} />}</div>;
}


function EventsInspectorPanel({ selected, timeRange }: { selected: CanvasNode | CanvasEdge; timeRange: GraphTimeRange }) {
  const active = activeEventsFor(selected, timeRange);
  const shown = active.slice(0, MAX_EVENT_LIST);
  return <div className="mt-4 space-y-2" data-testid="events-panel"><p className="text-sm font-semibold text-slate-100">Events active {active.length} / total {selected.events.length}</p>{shown.length ? shown.map((event) => <div key={event.id} className="rounded-lg bg-slate-900 p-2 text-xs"><p className="font-semibold text-slate-100">{event.severity.toUpperCase()} · {event.status}</p><p className="text-slate-400">{event.summary}</p><p className="mt-1 text-slate-500">{event.starts_at} → {event.ends_at ?? 'open'}</p></div>) : <p className="rounded-lg border border-slate-800 p-3 text-sm text-slate-500">No events in this time range.</p>}{active.length > MAX_EVENT_LIST && <p data-testid="event-truncation-warning" className="rounded border border-amber-400/40 bg-amber-400/10 p-2 text-xs text-amber-100">Event list capped at {MAX_EVENT_LIST} for inspector performance.</p>}</div>;
}

function TimeSeriesInspectorPanel({ selected }: { selected: CanvasNode | CanvasEdge }) {
  return <div data-testid="time-series-panel" className="mt-4 space-y-2">{selected.timeSeries.length ? selected.timeSeries.map((series) => <div key={series.metric} className="rounded-lg bg-slate-900 p-2 text-xs"><p className="font-semibold text-slate-100">{series.metric}</p><p className="text-slate-400">Latest {series.aggregates?.latest ?? 'n/a'} {series.unit ?? ''} · avg {series.aggregates?.avg ?? 'n/a'}</p><p className="mt-1 text-slate-500">{series.points?.length ?? 0} points · {series.time_range.start} → {series.time_range.end}</p>{series.truncated && <p className="mt-1 text-amber-200">Series points capped.</p>}</div>) : <p className="rounded-lg border border-slate-800 p-3 text-sm text-slate-500">No time-series points for this selection.</p>}</div>;
}

function GroupedObjectList({ group }: { group: GraphGroup }) {
  const shown = group.member_ids.slice(0, MAX_GROUP_LIST);
  return <div data-testid="grouped-object-list" className="rounded-lg border border-fuchsia-400/30 bg-fuchsia-950/20 p-2 text-xs"><p className="font-semibold text-fuchsia-100">Grouped objects · {group.aggregate_stats.member_count}</p><ul className="mt-2 space-y-1">{shown.map((id) => <li key={id} className="font-mono text-slate-300">{id}</li>)}</ul>{group.member_ids.length > MAX_GROUP_LIST && <p className="mt-2 text-amber-200">Group object list capped at {MAX_GROUP_LIST}.</p>}{group.warnings?.map((warning) => <p key={warning} className="mt-1 text-amber-200">{warning}</p>)}</div>;
}

function GroupedEdgeObjectList({ groupedEdge }: { groupedEdge: GroupedEdge }) {
  const shown = groupedEdge.contained_object_ids.slice(0, MAX_GROUP_LIST);
  return <div data-testid="grouped-edge-object-list" className="rounded-lg border border-fuchsia-400/30 bg-fuchsia-950/20 p-2 text-xs"><p className="font-semibold text-fuchsia-100">Grouped edge objects · {groupedEdge.contained_object_ids.length}</p><p className="mt-1 text-slate-500">Contained edges: {groupedEdge.contained_edge_ids.join(', ')}</p><ul className="mt-2 space-y-1">{shown.map((id) => <li key={id} className="font-mono text-slate-300">{id}</li>)}</ul>{groupedEdge.contained_object_ids.length > MAX_GROUP_LIST && <p className="mt-2 text-amber-200">Grouped edge object list capped at {MAX_GROUP_LIST}.</p>}{groupedEdge.warnings?.map((warning) => <p key={warning} className="mt-1 text-amber-200">{warning}</p>)}</div>;
}

function ListBlock({ items, empty }: { items: string[]; empty: string }) {
  return <ul className="mt-4 space-y-2 text-sm">{items.length ? items.map((item) => <li key={item} className="rounded-lg bg-slate-900 p-2 text-slate-200">{item}</li>) : <li className="text-slate-500">{empty}</li>}</ul>;
}


function SavedGraphsPanel({ savedGraphs, activeGraph, historicalReadonly, onOpen, onSaveAs, onDuplicate }: { savedGraphs: SavedGraphResponse[]; activeGraph: SavedGraphResponse | null; historicalReadonly: boolean; onOpen: (graph: SavedGraphResponse) => void; onSaveAs: () => void; onDuplicate: () => void }) {
  const actionsDisabled = historicalReadonly;
  return <section data-testid="saved-graphs-panel" className="mt-5 rounded-xl border border-cyan-400/30 bg-cyan-950/10 p-3"><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-cyan-200">Saved graphs</h3><button type="button" onClick={() => { if (!actionsDisabled) onSaveAs(); }} disabled={actionsDisabled} className="text-[11px] text-cyan-300 disabled:text-slate-500 disabled:opacity-60">Save as</button></div><div className="mt-2 space-y-2">{savedGraphs.length ? savedGraphs.map((graph) => <button key={graph.id} type="button" onClick={() => onOpen(graph)} className={`w-full rounded-lg border p-2 text-left text-xs ${activeGraph?.id === graph.id ? 'border-cyan-300 bg-cyan-300/10' : 'border-slate-800 hover:border-cyan-400'}`}><span className="block font-semibold text-slate-100">{graph.name}</span><span className="text-slate-500">v{graph.version} · {graph.view_state.nodes.length} nodes · {graph.layout}</span>{graph.warnings?.map((warning) => <span key={warning} className="mt-1 block text-amber-200">Missing/deleted refs: {warning}</span>)}</button>) : <p className="text-xs text-slate-500">No saved graphs yet. Save As creates a restorable graph snapshot.</p>}</div><button data-testid="duplicate-graph-button" type="button" onClick={() => { if (!actionsDisabled && activeGraph) onDuplicate(); }} disabled={!activeGraph || actionsDisabled} className="mt-3 w-full rounded-lg border border-slate-700 px-2 py-1.5 text-xs font-semibold text-slate-200 disabled:opacity-40">Duplicate active graph</button></section>;
}

function SavedSelectionsPanel({ selections, onCreate, onToggleOverlay, onDelete }: { selections: SavedSelectionResponse[]; onCreate: () => void; onToggleOverlay: (selection: SavedSelectionResponse) => void; onDelete: (id: string) => void }) {
  return <section data-testid="saved-selections-panel" className="mt-5 rounded-xl border border-emerald-400/30 bg-emerald-950/10 p-3"><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-emerald-200">Saved selections</h3><button type="button" onClick={onCreate} className="text-[11px] text-emerald-300">Save selected</button></div><div className="mt-2 space-y-2">{selections.map((item) => <div key={item.id} className="rounded-lg border border-slate-800 p-2 text-xs"><div className="flex items-center justify-between gap-2"><span className="font-semibold text-slate-100"><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />{item.name}</span><button type="button" onClick={() => onToggleOverlay(item)} className="text-cyan-300">{item.overlay ? 'Hide' : 'Overlay'}</button></div><p className="mt-1 text-slate-500">{item.members.length} members</p>{item.warnings?.map((warning) => <p key={warning} className="text-amber-200">{warning}</p>)}<button type="button" onClick={() => onDelete(item.id)} className="mt-1 text-rose-300">Delete</button></div>)}</div></section>;
}

function SavedStylesPanel({ styles, activeStyle, onApply }: { styles: GraphStyleResponse[]; activeStyle: GraphStyleResponse | null; onApply: (style: GraphStyleResponse) => void }) {
  return <section data-testid="saved-styles-panel" className="mt-5 rounded-xl border border-fuchsia-400/30 bg-fuchsia-950/10 p-3"><h3 className="text-xs font-bold uppercase tracking-wider text-fuchsia-200">Saved styles</h3><div className="mt-2 space-y-2">{styles.map((style) => <button key={style.id} type="button" onClick={() => onApply(style)} className={`w-full rounded-lg border p-2 text-left text-xs ${activeStyle?.id === style.id ? 'border-fuchsia-300 bg-fuchsia-300/10' : 'border-slate-800 hover:border-fuchsia-400'}`}><span className="block font-semibold text-slate-100">{style.name}</span><span className="text-slate-500">{style.node_rules.length} node rules · {style.edge_rules.length} edge rules</span></button>)}</div>{activeStyle && <div data-testid="style-legend" className="mt-3 rounded-lg bg-slate-900 p-2 text-xs"><p className="font-semibold text-slate-200">Legend · {activeStyle.name}</p>{activeStyle.legend.map((entry) => <div key={entry.label} className="mt-1 flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: entry.color }} /><span>{entry.label}</span><span className="text-slate-500">{entry.description}</span></div>)}</div>}</section>;
}

function TemplatePanel({ templates, onCreate, onRun }: { templates: GraphTemplateResponse[]; onCreate: () => void; onRun: (template: GraphTemplateResponse) => void }) {
  return <section className="mt-5 rounded-xl border border-amber-300/30 bg-amber-950/10 p-3"><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-amber-100">Templates</h3><button type="button" onClick={onCreate} className="text-[11px] text-amber-200">Create</button></div><div className="mt-2 space-y-2">{templates.map((template) => <button key={template.id} type="button" onClick={() => onRun(template)} className="w-full rounded-lg border border-slate-800 p-2 text-left text-xs hover:border-amber-300"><span className="block font-semibold text-slate-100">{template.name}</span><span className="text-slate-500">{template.parameters.length} params · {template.layout}</span></button>)}</div></section>;
}

function GraphHistorySidebar({ versions, selectedVersionId, onOpenVersion, onSelectCurrent }: { versions: SavedGraphVersionResponse[]; selectedVersionId: string; onOpenVersion: (version: SavedGraphVersionResponse) => void; onSelectCurrent: () => void }) {
  const selected = versions.find((version) => version.id === selectedVersionId) ?? versions[0];
  return <section data-testid="graph-history-sidebar" className="mb-4 rounded-xl border border-amber-400/30 bg-amber-950/10 p-3"><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-amber-100">Graph history</h3><button type="button" onClick={onSelectCurrent} className="text-[11px] text-cyan-300">Current</button></div><div className="mt-2 max-h-32 space-y-1 overflow-auto">{versions.length ? versions.map((version) => <button key={version.id} type="button" onClick={() => onOpenVersion(version)} className={`w-full rounded border p-1.5 text-left text-xs ${selectedVersionId === version.id ? 'border-amber-200' : 'border-slate-800'}`}>{version.label} · readonly</button>) : <p className="text-xs text-slate-500">Save a graph to create immutable versions.</p>}</div><div data-testid="version-diff-viewer" className="mt-3 rounded-lg bg-slate-900 p-2 text-xs"><p className="font-semibold text-slate-200">Version diff viewer</p>{selected ? selected.diff.map((item) => <p key={item.id} className="mt-1"><span className="text-slate-400">{item.label}</span>: <span className="text-rose-200">{item.before}</span> → <span className="text-emerald-200">{item.after}</span></p>) : <p className="mt-1 text-slate-500">No saved versions selected.</p>}</div></section>;
}

function SaveAsModal({ onClose, onSave }: { onClose: () => void; onSave: (name: string) => void }) {
  const [name, setName] = useState('');
  const invalid = !name.trim();
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6"><div data-testid="save-as-modal" className="w-full max-w-md rounded-2xl border border-cyan-400/40 bg-slate-950 p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Save graph as</h2><button type="button" onClick={onClose}>Close</button></div><label className="mt-4 block text-sm">Graph name<input value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" /></label>{invalid && <p className="mt-2 text-sm text-amber-200">Name is required.</p>}<div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded border border-slate-700 px-3 py-2 text-sm">Cancel</button><button type="button" disabled={invalid} onClick={() => onSave(name.trim())} className="rounded bg-cyan-300 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">Save graph</button></div></div></div>;
}

function ShareGraphModal({ policies, redactionPreview, onLimitedPreview, onClose }: { policies: ShareGraphPolicy[]; redactionPreview: boolean; onLimitedPreview: () => void; onClose: () => void }) {
  useEffect(() => { const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; document.addEventListener('keydown', handler); return () => document.removeEventListener('keydown', handler); }, [onClose]);
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6"><div data-testid="share-graph-modal" role="dialog" aria-modal="true" aria-labelledby="share-graph-title" className="w-full max-w-xl rounded-2xl border border-fuchsia-400/40 bg-slate-950 p-5"><div className="flex items-center justify-between"><h2 id="share-graph-title" className="text-lg font-semibold">Share graph</h2><button type="button" onClick={onClose} aria-label="Close share graph modal">Close</button></div><div className="mt-4 space-y-2">{policies.map((policy) => <div key={policy.id} className="rounded-lg border border-slate-800 p-3 text-sm"><p className="font-semibold text-slate-100">{policy.principal}</p><p className="text-slate-400">Permission: {policy.permission} · {policy.redacted ? 'redacted hydration' : 'full read hydration'}</p></div>)}</div><button type="button" onClick={onLimitedPreview} className="mt-4 rounded bg-fuchsia-300 px-3 py-2 text-sm font-bold text-slate-950">Preview limited viewer</button>{redactionPreview && <p data-testid="redaction-notice" className="mt-3 rounded-lg border border-red-400/30 bg-red-950/30 p-2 text-sm text-red-100">Redacted shared view active: limited viewers see topology only and no sensitive properties.</p>}</div></div>;
}

function GraphTemplateWizard({ graphName, layout, filters, activeStyleId, onClose, onCreate }: { graphName: string; layout: GraphLayoutPreset; filters: GraphBuilderFilterState; activeStyleId?: string; onClose: () => void; onCreate: (template: GraphTemplateResponse) => void }) {
  const [name, setName] = useState(`${graphName} template`);
  const [requiresSet, setRequiresSet] = useState(true);
  const invalid = !name.trim();
  const template: GraphTemplateResponse = { id: `template-${name.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'draft'}`, name, description: 'Created from current graph state.', parameters: [{ id: 'root_object', label: 'Root object', type: 'object', required: true }, ...(requiresSet ? [{ id: 'review_set', label: 'Review set', type: 'object_set' as const, required: true }] : [])], traversal_definitions: [{ relationship_type_id: 'owns', direction: 'outbound' }], filters, styles: activeStyleId ? [activeStyleId] : [], layout };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6"><div data-testid="graph-template-wizard" className="w-full max-w-xl rounded-2xl border border-amber-300/40 bg-slate-950 p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Graph template wizard</h2><button type="button" onClick={onClose}>Close</button></div><label className="mt-4 block text-sm">Template name<input value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" /></label><label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={requiresSet} onChange={(event) => setRequiresSet(event.target.checked)} /> Require object-set parameter</label><div className="mt-3 rounded-lg bg-slate-900 p-2 text-xs">Required params: {template.parameters.filter((param) => param.required).map((param) => param.label).join(', ')}</div>{invalid && <p className="mt-2 text-amber-200">Template name is required.</p>}<div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded border border-slate-700 px-3 py-2 text-sm">Cancel</button><button type="button" disabled={invalid} onClick={() => onCreate(template)} className="rounded bg-amber-200 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">Create template</button></div></div></div>;
}

function TemplateRunModal({ template, onClose, onRun }: { template: GraphTemplateResponse; onClose: () => void; onRun: (values: Record<string, string>) => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const missing = template.parameters.filter((param) => param.required && !values[param.id]?.trim());
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6"><div data-testid="template-run-modal" className="w-full max-w-xl rounded-2xl border border-amber-300/40 bg-slate-950 p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Run template · {template.name}</h2><button type="button" onClick={onClose}>Close</button></div><div className="mt-4 space-y-3">{template.parameters.map((param) => <label key={param.id} className="block text-sm">{param.label}{param.required ? ' *' : ''}<input data-testid="template-param-input" value={values[param.id] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [param.id]: event.target.value }))} placeholder={param.type === 'object_set' ? 'set-key-accounts' : 'object.customer'} className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" />{submitted && param.required && !values[param.id]?.trim() && <span className="mt-1 block text-xs text-amber-200">{param.label} is required.</span>}</label>)}</div><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded border border-slate-700 px-3 py-2 text-sm">Cancel</button><button type="button" onClick={() => { setSubmitted(true); if (!missing.length) onRun(values); }} className="rounded bg-amber-200 px-3 py-2 text-sm font-bold text-slate-950">Generate graph</button></div></div></div>;
}

function ObjectSearchModal({ namespace, onClose, onAdd, onCreateSet }: { namespace: string; onClose: () => void; onAdd: (results: ExplorerSearchResult[]) => void; onCreateSet: (results: ExplorerSearchResult[]) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ExplorerSearchResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSearch = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await searchOntologyObjects(namespace, query);
      setResults(response.results);
    } catch (err) {
      setError(canonicalErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void runSearch(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; document.addEventListener('keydown', handler); return () => document.removeEventListener('keydown', handler); }, [onClose]);

  const selectedResults = results.filter((result) => selectedIds.includes(result.id));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6">
      <div data-testid="search-modal" role="dialog" aria-modal="true" aria-labelledby="object-search-title" className="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-950 p-5 shadow-2xl">
        <div className="flex items-center justify-between"><h2 id="object-search-title" className="text-lg font-semibold">Object search</h2><button type="button" onClick={onClose} className="text-slate-400" aria-label="Close object search modal">Close</button></div>
        <div className="mt-4 flex gap-2"><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm" placeholder="Search objects" /><button type="button" onClick={runSearch} className="rounded-lg bg-cyan-300 px-3 py-2 text-sm font-bold text-slate-950">Search</button></div>
        {error && <div className="mt-3 rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-100"><p data-testid="canonical-error-message">{error}</p><button data-testid="retry-button" type="button" onClick={runSearch} className="mt-2 rounded bg-red-200 px-2 py-1 text-xs font-bold text-red-950">Retry</button></div>}
        <div className="mt-4 max-h-[360px] space-y-2 overflow-auto">
          {loading ? <p data-testid="loading-skeleton" className="text-sm text-slate-400">Searching…</p> : results.map((result) => (
            <label data-testid="search-result-row" key={result.id} className="flex cursor-pointer gap-3 rounded-xl border border-slate-800 p-3 hover:border-cyan-400">
              <input type="checkbox" checked={selectedIds.includes(result.id)} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, result.id] : current.filter((id) => id !== result.id))} />
              <span><span className="block text-sm font-semibold">{result.label}</span><span className="block text-xs text-slate-500">{result.object_type} · {result.description}</span>{result.redacted && <span className="mt-1 inline-block rounded bg-red-900 px-1.5 py-0.5 text-[10px] text-red-100">Redacted</span>}</span>
            </label>
          ))}
          {!loading && !error && results.length === 0 && <p data-testid="empty-state" className="text-sm text-slate-500">No matching objects.</p>}
        </div>
        <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-2 text-sm">Cancel</button><button data-testid="create-object-set-button" type="button" onClick={() => onCreateSet(selectedResults)} disabled={!selectedResults.length} className="rounded-lg border border-emerald-400 px-3 py-2 text-sm font-bold text-emerald-100 disabled:opacity-40">Create object set</button><button data-testid="add-to-graph-button" type="button" onClick={() => onAdd(selectedResults)} disabled={!selectedResults.length} className="rounded-lg bg-cyan-300 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">Add to graph</button></div>
      </div>
    </div>
  );
}

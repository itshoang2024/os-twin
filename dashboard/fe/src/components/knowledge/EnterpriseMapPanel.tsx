'use client';

import React from 'react';
import {
  useEnterpriseMap,
  useKnowledgeExplorer,
  type EnterpriseMapNode,
  type EnterpriseMapProjectionData,
  type ExplorerEdge,
  type ExplorerNode,
} from '@/hooks/use-knowledge-explorer';
import { useOntologyObservation, useOntologyProfile, type ObservationEvent, type OntologyProfile, type TimeSeries } from '@/hooks/use-ontology';
import { ENTERPRISE_MAP_MODULES } from './ontology/enterprise-map';
import { WorkbenchShell, mapLensAdapter } from './workbench';

type ViewName = 'map' | 'layers' | 'objects' | 'relations' | 'quality' | 'simulation';
type FilterKey = 'layer' | 'objectType' | 'abstraction' | 'relationshipFamily' | 'pack' | 'lifecycle' | 'review' | 'owner' | 'quality';
type ActiveFilters = Record<FilterKey, string[]>;

interface OntologyLayerView {
  id: string;
  label: string;
  order: number;
  description: string;
  count: number;
  lifecycleState?: string;
}

interface OntologyObject {
  id: string;
  name: string;
  label: string;
  objectType: string;
  objectTypeLabel: string;
  objectColor: string;
  objectShape?: string | null;
  layerId: string;
  layerLabel: string;
  layerOrder: number;
  abstractionId: string;
  abstractionLabel: string;
  packId: string;
  lifecycleState: string;
  owner: string;
  qualityState: string;
  description: string;
  metadata: Record<string, unknown>;
  properties: Record<string, unknown>;
  validationIssues: Array<Record<string, unknown>>;
  reviewState: string;
  confidence?: number | null;
  provenanceRefs: string[];
  externalRef: Record<string, unknown> | null;
  eventCount: number;
  activeEventCount: number;
  timeRange: Record<string, unknown> | string | null;
  seriesRefs: string[];
  flowRefs: string[];
  state: string | null;
  stateColor: string | null;
  stateMachineRef: string | null;
  simulationState: string | null;
  simulationRefs: string[];
  sourceNode?: ExplorerNode | EnterpriseMapNode;
}

interface OntologyRelation {
  source: string;
  target: string;
  mapSource: string;
  mapTarget: string;
  type: string;
  label: string;
  family: string;
  style: string;
  weight: number;
  reviewState: string;
  confidence?: number | null;
  provenanceRefs: string[];
  externalRef: Record<string, unknown> | null;
  mapDirection?: string | null;
  isCandidate: boolean;
  validationIssues: Array<Record<string, unknown>>;
}

interface OntologyMapData {
  namespace: string | null;
  profileId: string;
  profileVersion: string;
  profileStatus: string;
  profileExists: boolean;
  objects: OntologyObject[];
  relations: OntologyRelation[];
  layers: OntologyLayerView[];
  abstractionLevels: Array<{ id: string; label: string; order?: number; description?: string }>;
  conceptTypeCounts: Record<string, number>;
  relationshipTypeCounts: Record<string, number>;
  relationshipFamilyCounts: Record<string, number>;
  stats: {
    nodeCount: number;
    relationCount: number;
    layerCount: number;
    objectTypeCount: number;
    relationshipTypeCount: number;
    candidateEdgeCount: number;
    ontologyCandidateCount: number;
    validationIssueCount: number;
    sourceNodeCount?: number;
    sourceEdgeCount?: number;
    limit?: number;
    flowCount?: number;
    stateMachineCount?: number;
    simulationScenarioCount?: number;
  };
  analysis: { flow_count: number; state_machine_count: number; simulation_scenario_count: number; simulation_provider_required?: boolean; provider_contract?: string };
}

interface LayoutResult {
  positions: Record<string, { x: number; y: number }>;
  lanes: Array<{ layerId: string; label: string; y0: number; y1: number; count: number }>;
  width: number;
  height: number;
}

interface GraphEdge {
  source: OntologyObject;
  target: OntologyObject;
  relation: OntologyRelation;
  testId?: string;
}

const VIEW_BUTTONS: Array<{ id: ViewName; label: string }> = [
  { id: 'map', label: 'Map' },
  { id: 'layers', label: 'Layers' },
  { id: 'objects', label: 'Object Types' },
  { id: 'relations', label: 'Relations' },
  { id: 'quality', label: 'Quality' },
  { id: 'simulation', label: 'Simulation' },
];

const FILTER_KEYS: FilterKey[] = ['layer', 'objectType', 'abstraction', 'relationshipFamily', 'pack', 'lifecycle', 'review', 'owner', 'quality'];
const NODE_W = 178;
const NODE_H = 68;
const H_GAP = 16;
const V_GAP = 12;
const LANE_PAD_TOP = 36;
const LANE_PAD_BOTTOM = 16;
const SVG_PAD_X = 24;
const PAGE_SIZE_OPTIONS = [40, 80, 160] as const;
type DensityMode = 'compact' | 'comfortable' | 'spacious';
type TimeSelectionMode = 'none' | 'fixed_range' | 'latest_import' | 'current_profile_version';

const FALLBACK_LAYER_COLORS = ['#2563eb', '#0f766e', '#b7791f', '#7c3aed', '#be123c', '#475569', '#0e7490', '#9333ea'];
const RELATION_STYLE: Record<string, string> = {
  solid: '',
  dashed: '6 4',
  dotted: '2 4',
  bold: '',
};

const DEFAULT_MAP_DATA: OntologyMapData = {
  namespace: null,
  profileId: 'unavailable',
  profileVersion: 'n/a',
  profileStatus: 'unavailable',
  profileExists: false,
  objects: [],
  relations: [],
  layers: [],
  abstractionLevels: [],
  conceptTypeCounts: {},
  relationshipTypeCounts: {},
  relationshipFamilyCounts: {},
  stats: {
    nodeCount: 0,
    relationCount: 0,
    layerCount: 0,
    objectTypeCount: 0,
    relationshipTypeCount: 0,
    candidateEdgeCount: 0,
    ontologyCandidateCount: 0,
    validationIssueCount: 0,
    flowCount: 0,
    stateMachineCount: 0,
    simulationScenarioCount: 0,
  },
  analysis: { flow_count: 0, state_machine_count: 0, simulation_scenario_count: 0 },
};

const titleize = (value?: string | null) =>
  String(value || 'unassigned')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());

const asRecord = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {});
const asIssues = (value: unknown): Array<Record<string, unknown>> => Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') as Array<Record<string, unknown>> : [];
const asStringList = (value: unknown): string[] => Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : (typeof value === 'string' && value.trim() ? [value] : []);
const optionalNumber = (value: unknown): number | null => { const n = Number(value); return Number.isFinite(n) ? n : null; };
const optionalRecord = (value: unknown): Record<string, unknown> | null => (value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null);
const truncate = (value: string, limit: number) => (value.length > limit ? `${value.slice(0, limit - 3)}...` : value);
const relationKey = (source: string, target: string) => `${source}->${target}`;

function stableHash(value: string) {
  return value.split('').reduce((sum, char) => ((sum << 5) - sum + char.charCodeAt(0)) | 0, 0);
}

function fallbackColor(value: string) {
  const index = Math.abs(stableHash(value || 'fallback')) % FALLBACK_LAYER_COLORS.length;
  return FALLBACK_LAYER_COLORS[index];
}

function layerColor(layerId: string, label?: string) {
  return fallbackColor(layerId || label || 'layer');
}

function objectOwner(node: ExplorerNode | EnterpriseMapNode) {
  return String((node as EnterpriseMapNode).owner ?? node.metadata?.owner ?? node.properties?.owner ?? 'Unassigned');
}

function objectDescription(node: ExplorerNode | EnterpriseMapNode, conceptDescription?: string) {
  return String(
    (node as EnterpriseMapNode).description
      ?? node.metadata?.purpose
      ?? node.metadata?.description
      ?? node.properties?.purpose
      ?? node.properties?.description
      ?? node.properties?.entity_description
      ?? conceptDescription
      ?? 'No description metadata available.',
  );
}

function objectQuality(node: ExplorerNode | EnterpriseMapNode) {
  const projectedQuality = String((node as EnterpriseMapNode).quality_state ?? '').trim();
  if (projectedQuality) return projectedQuality;
  if (asIssues(node.validation_issues).length) return 'needs_review';
  if (node.lifecycle_state === 'deprecated') return 'deprecated';
  if (node.lifecycle_state === 'candidate') return 'unverified';
  if (node.lifecycle_state === 'draft') return 'draft';
  return 'healthy';
}

function profileMeta(map: EnterpriseMapProjectionData | null, profile: OntologyProfile | null, namespace: string | null) {
  const profileSummary = map?.meta?.ontology_profile as Record<string, unknown> | null | undefined;
  return {
    profileId: String(profileSummary?.profile_id ?? profile?.profile_id ?? 'enterprise_feature_map'),
    profileVersion: String(profileSummary?.version ?? profile?.version ?? 'n/a'),
    profileStatus: String(profileSummary?.status ?? profile?.status ?? 'active'),
    profileExists: Boolean(map?.meta?.profile_exists ?? profile),
    namespace,
  };
}

function conceptFromProfile(profile: OntologyProfile | null, conceptId?: string | null) {
  if (!conceptId) return null;
  return profile?.concept_types?.[conceptId] ?? null;
}

function relationFromProfile(profile: OntologyProfile | null, relationId?: string | null) {
  if (!relationId) return null;
  return profile?.relationship_types?.[relationId] ?? null;
}

function layerLabelFromProfile(profile: OntologyProfile | null, layerId?: string | null) {
  if (!layerId) return null;
  return profile?.layers?.[layerId]?.label ?? null;
}

function abstractionLabelFromProfile(profile: OntologyProfile | null, abstractionId?: string | null) {
  if (!abstractionId) return null;
  return profile?.abstraction_levels?.[abstractionId]?.label ?? null;
}

function graphConceptInstruction(profile: OntologyProfile | null, conceptId?: string | null) {
  if (!conceptId) return null;
  return profile?.graph_instruction?.concept_type_defaults?.[conceptId] ?? null;
}

function graphRelationshipInstruction(profile: OntologyProfile | null, relationType?: string | null) {
  if (!relationType) return null;
  return profile?.graph_instruction?.relationship_type_defaults?.[relationType] ?? null;
}

function layerIdFromNode(node: ExplorerNode | EnterpriseMapNode, profile: OntologyProfile | null) {
  const enterprise = node as EnterpriseMapNode;
  const conceptId = String(node.concept_type ?? '').trim();
  const concept = conceptFromProfile(profile, conceptId);
  const instruction = graphConceptInstruction(profile, conceptId);
  const explicit = String(enterprise.layer_id ?? node.layer ?? node.metadata?.layer ?? node.properties?.layer ?? instruction?.default_layer ?? concept?.default_layer ?? '').trim();
  if (explicit) return explicit;
  return 'unassigned';
}

function makeLayerFromObject(object: OntologyObject): OntologyLayerView {
  return {
    id: object.layerId,
    label: object.layerLabel,
    order: object.layerOrder,
    description: '',
    count: 0,
  };
}

function mapProjectionData(map: EnterpriseMapProjectionData, profile: OntologyProfile | null, namespace: string | null): OntologyMapData {
  const meta = profileMeta(map, profile, namespace);
  const layerById = new Map(
    map.layers.map((layer) => [
      layer.id,
      {
        id: layer.id,
        label: layer.label,
        order: layer.order,
        description: layer.description ?? '',
        count: layer.count,
        lifecycleState: layer.lifecycle_state,
      } satisfies OntologyLayerView,
    ]),
  );

  const objects = map.nodes.map<OntologyObject>((node) => {
    const concept = conceptFromProfile(profile, node.concept_type);
    const layerId = String(node.layer_id ?? node.layer ?? 'unassigned');
    const layer = layerById.get(layerId);
    const abstractionId = String(node.abstraction_level ?? 'unassigned');
    return {
      id: node.id,
      name: node.name || node.id,
      label: node.label || String(node.concept_type ?? 'object'),
      objectType: String(node.concept_type ?? node.label ?? 'object'),
      objectTypeLabel: String(node.concept_label ?? concept?.label ?? titleize(node.concept_type ?? node.label)),
      objectColor: String(node.concept_color ?? concept?.color ?? fallbackColor(String(node.concept_type ?? node.label ?? node.id))),
      objectShape: node.concept_shape ?? concept?.shape ?? null,
      layerId,
      layerLabel: String(node.layer_label ?? layer?.label ?? layerLabelFromProfile(profile, layerId) ?? titleize(layerId)),
      layerOrder: Number(node.layer_order ?? layer?.order ?? 999),
      abstractionId,
      abstractionLabel: String(node.abstraction_label ?? abstractionLabelFromProfile(profile, abstractionId) ?? titleize(abstractionId)),
      packId: String(node.pack_id ?? 'core'),
      lifecycleState: String(node.lifecycle_state ?? 'active'),
      owner: objectOwner(node),
      qualityState: objectQuality(node),
      description: objectDescription(node, concept?.description),
      metadata: asRecord(node.metadata),
      properties: asRecord(node.properties),
      validationIssues: asIssues(node.validation_issues),
      reviewState: String(node.review_state ?? node.candidate_state ?? 'unreviewed'),
      confidence: optionalNumber(node.confidence),
      provenanceRefs: asStringList(node.provenance_refs),
      externalRef: optionalRecord(node.external_ref),
      eventCount: Number((node as EnterpriseMapNode).event_count ?? 0),
      activeEventCount: Number((node as EnterpriseMapNode).active_event_count ?? 0),
      timeRange: ((node as EnterpriseMapNode).time_range ?? null) as Record<string, unknown> | string | null,
      seriesRefs: asStringList((node as EnterpriseMapNode).series_refs),
      flowRefs: asStringList((node as EnterpriseMapNode).flow_refs),
      state: typeof (node as EnterpriseMapNode).state === 'string' ? String((node as EnterpriseMapNode).state) : null,
      stateColor: typeof (node as EnterpriseMapNode & { state_color?: unknown }).state_color === 'string' ? String((node as EnterpriseMapNode & { state_color?: unknown }).state_color) : null,
      stateMachineRef: typeof (node as EnterpriseMapNode & { state_machine_ref?: unknown }).state_machine_ref === 'string' ? String((node as EnterpriseMapNode & { state_machine_ref?: unknown }).state_machine_ref) : null,
      simulationState: typeof (node as EnterpriseMapNode).simulation_state === 'string' ? String((node as EnterpriseMapNode).simulation_state) : null,
      simulationRefs: asStringList((node as EnterpriseMapNode & { simulation_refs?: unknown }).simulation_refs),
      sourceNode: node,
    };
  });

  const layers = mergeObservedLayers(Array.from(layerById.values()), objects);
  const relations = map.edges.map<OntologyRelation>((edge) => {
    const relationType = String(edge.relationship_type ?? edge.label ?? 'relates');
    const relation = relationFromProfile(profile, relationType);
    return {
      source: edge.source,
      target: edge.target,
      mapSource: String(edge.map_source ?? edge.source),
      mapTarget: String(edge.map_target ?? edge.target),
      type: relationType,
      label: String(edge.display_label ?? relation?.label ?? titleize(relationType)),
      family: String(edge.family ?? relation?.family ?? 'semantic'),
      style: String(edge.style ?? relationshipStyle(profile, relationType, null)),
      weight: Number(edge.weight ?? relationshipWeight(profile, relationType, null)),
      isCandidate: Boolean(edge.is_candidate),
      reviewState: String(edge.review_state ?? edge.candidate_state ?? 'unreviewed'),
      confidence: optionalNumber(edge.confidence),
      provenanceRefs: asStringList(edge.provenance_refs),
      externalRef: optionalRecord(edge.external_ref),
      mapDirection: edge.map_direction ?? null,
      validationIssues: asIssues(edge.validation_issues),
    };
  });

  return {
    ...meta,
    objects,
    relations,
    layers,
    abstractionLevels: map.abstraction_levels ?? [],
    conceptTypeCounts: map.concept_type_counts ?? countBy(objects, 'objectType'),
    relationshipTypeCounts: map.relationship_type_counts ?? countBy(relations, 'type'),
    relationshipFamilyCounts: map.relationship_family_counts ?? countBy(relations, 'family'),
    stats: {
      nodeCount: map.stats.node_count,
      relationCount: map.stats.edge_count,
      layerCount: map.stats.layer_count,
      objectTypeCount: map.stats.concept_type_count,
      relationshipTypeCount: map.stats.relationship_type_count,
      candidateEdgeCount: map.stats.candidate_edge_count,
      ontologyCandidateCount: Number(map.stats.ontology_candidate_count ?? map.meta?.ontology_candidate_count ?? 0),
      validationIssueCount: map.stats.validation_issue_count,
      sourceNodeCount: Number(map.stats.source_node_count ?? map.stats.node_count),
      sourceEdgeCount: Number(map.stats.source_edge_count ?? map.stats.edge_count),
      limit: typeof map.stats.limit === 'number' ? map.stats.limit : undefined,
      flowCount: Number(map.stats.flow_count ?? 0),
      stateMachineCount: Number(map.stats.state_machine_count ?? 0),
      simulationScenarioCount: Number(map.stats.simulation_scenario_count ?? 0),
    },
    analysis: {
      flow_count: Number((map.meta?.analysis as Record<string, unknown> | undefined)?.flow_count ?? map.stats.flow_count ?? 0),
      state_machine_count: Number((map.meta?.analysis as Record<string, unknown> | undefined)?.state_machine_count ?? map.stats.state_machine_count ?? 0),
      simulation_scenario_count: Number((map.meta?.analysis as Record<string, unknown> | undefined)?.simulation_scenario_count ?? map.stats.simulation_scenario_count ?? 0),
      simulation_provider_required: Boolean((map.meta?.analysis as Record<string, unknown> | undefined)?.simulation_provider_required),
      provider_contract: typeof (map.meta?.analysis as Record<string, unknown> | undefined)?.provider_contract === 'string' ? String((map.meta?.analysis as Record<string, unknown> | undefined)?.provider_contract) : undefined,
    },
  };
}

function relationshipMapDirection(profile: OntologyProfile | null, relationType: string) {
  const relationship = relationFromProfile(profile, relationType);
  const instruction = graphRelationshipInstruction(profile, relationType);
  return String(instruction?.map_direction ?? relationship?.map_direction ?? 'forward');
}

function relationshipStyle(profile: OntologyProfile | null, relationType: string, edgeStyle?: string | null) {
  const instruction = graphRelationshipInstruction(profile, relationType);
  if (instruction?.dash) return instruction.dash.startsWith('2') ? 'dotted' : 'dashed';
  return String(edgeStyle ?? relationFromProfile(profile, relationType)?.style ?? 'solid');
}

function relationshipWeight(profile: OntologyProfile | null, relationType: string, edgeWeight?: number | null) {
  const instruction = graphRelationshipInstruction(profile, relationType);
  return Number(instruction?.weight ?? edgeWeight ?? relationFromProfile(profile, relationType)?.weight ?? 1);
}

function mapExplorerFallback(nodes: ExplorerNode[], edges: ExplorerEdge[], profile: OntologyProfile | null, namespace: string | null): OntologyMapData {
  const meta = profileMeta(null, profile, namespace);
  const objects = nodes.map<OntologyObject>((node) => {
    const concept = conceptFromProfile(profile, node.concept_type);
    const layerId = layerIdFromNode(node, profile);
    const abstractionId = String(node.abstraction_level ?? concept?.abstraction_level ?? 'unassigned');
    return {
      id: node.id,
      name: node.name || node.id,
      label: node.label || String(node.concept_type ?? 'object'),
      objectType: String(node.concept_type ?? node.label ?? 'object'),
      objectTypeLabel: String(graphConceptInstruction(profile, node.concept_type)?.label_template ? titleize(node.concept_type ?? node.label) : concept?.label ?? titleize(node.concept_type ?? node.label)),
      objectColor: String(graphConceptInstruction(profile, node.concept_type)?.color ?? concept?.color ?? fallbackColor(String(node.concept_type ?? node.label ?? node.id))),
      objectShape: graphConceptInstruction(profile, node.concept_type)?.shape ?? concept?.shape ?? null,
      layerId,
      layerLabel: String(layerLabelFromProfile(profile, layerId) ?? titleize(layerId)),
      layerOrder: Number(profile?.layers?.[layerId]?.order ?? 999),
      abstractionId,
      abstractionLabel: String(abstractionLabelFromProfile(profile, abstractionId) ?? titleize(abstractionId)),
      packId: String(node.pack_id ?? 'core'),
      lifecycleState: String(node.lifecycle_state ?? 'active'),
      owner: objectOwner(node),
      qualityState: objectQuality(node),
      description: objectDescription(node, concept?.description),
      metadata: asRecord(node.metadata),
      properties: asRecord(node.properties),
      validationIssues: asIssues(node.validation_issues),
      reviewState: String(node.review_state ?? node.candidate_state ?? 'unreviewed'),
      confidence: optionalNumber(node.confidence),
      provenanceRefs: asStringList(node.provenance_refs),
      externalRef: optionalRecord(node.external_ref),
      eventCount: Number((node as ExplorerNode & Partial<EnterpriseMapNode>).event_count ?? 0),
      activeEventCount: Number((node as ExplorerNode & Partial<EnterpriseMapNode>).active_event_count ?? 0),
      timeRange: ((node as ExplorerNode & Partial<EnterpriseMapNode>).time_range ?? null) as Record<string, unknown> | string | null,
      seriesRefs: asStringList((node as ExplorerNode & Partial<EnterpriseMapNode>).series_refs),
      flowRefs: asStringList((node as ExplorerNode & Partial<EnterpriseMapNode>).flow_refs),
      state: typeof (node as ExplorerNode & Partial<EnterpriseMapNode>).state === 'string' ? String((node as ExplorerNode & Partial<EnterpriseMapNode>).state) : null,
      stateColor: typeof (node as ExplorerNode & Partial<EnterpriseMapNode> & { state_color?: unknown }).state_color === 'string' ? String((node as ExplorerNode & Partial<EnterpriseMapNode> & { state_color?: unknown }).state_color) : null,
      stateMachineRef: typeof (node as ExplorerNode & Partial<EnterpriseMapNode> & { state_machine_ref?: unknown }).state_machine_ref === 'string' ? String((node as ExplorerNode & Partial<EnterpriseMapNode> & { state_machine_ref?: unknown }).state_machine_ref) : null,
      simulationState: typeof (node as ExplorerNode & Partial<EnterpriseMapNode>).simulation_state === 'string' ? String((node as ExplorerNode & Partial<EnterpriseMapNode>).simulation_state) : null,
      simulationRefs: asStringList((node as ExplorerNode & Partial<EnterpriseMapNode> & { simulation_refs?: unknown }).simulation_refs),
      sourceNode: node,
    };
  });
  const layers = mergeObservedLayers([], objects);
  const relations = edges.map<OntologyRelation>((edge) => {
    const relationType = String(edge.relationship_type ?? edge.label ?? 'relates');
    const relation = relationFromProfile(profile, relationType);
    return {
      source: edge.source,
      target: edge.target,
      mapSource: relationshipMapDirection(profile, relationType) === 'reversed' ? edge.target : edge.source,
      mapTarget: relationshipMapDirection(profile, relationType) === 'reversed' ? edge.source : edge.target,
      type: relationType,
      label: String(edge.display_label ?? relation?.label ?? titleize(relationType)),
      family: String(edge.family ?? relation?.family ?? 'semantic'),
      style: relationshipStyle(profile, relationType, edge.style),
      weight: relationshipWeight(profile, relationType, edge.weight),
      reviewState: String(edge.review_state ?? edge.candidate_state ?? 'unreviewed'),
      confidence: optionalNumber(edge.confidence),
      provenanceRefs: asStringList(edge.provenance_refs),
      externalRef: optionalRecord(edge.external_ref),
      mapDirection: edge.map_direction ?? null,
      isCandidate: Boolean(edge.is_candidate || edge.review_state === 'candidate'),
      validationIssues: asIssues(edge.validation_issues),
    };
  });
  return {
    ...meta,
    objects,
    relations,
    layers,
    abstractionLevels: Object.values(profile?.abstraction_levels ?? {}),
    conceptTypeCounts: countBy(objects, 'objectType'),
    relationshipTypeCounts: countBy(relations, 'type'),
    relationshipFamilyCounts: countBy(relations, 'family'),
    stats: {
      nodeCount: objects.length,
      relationCount: relations.length,
      layerCount: layers.length,
      objectTypeCount: Object.keys(countBy(objects, 'objectType')).length,
      relationshipTypeCount: Object.keys(countBy(relations, 'type')).length,
      candidateEdgeCount: relations.filter((relation) => relation.isCandidate).length,
      ontologyCandidateCount: 0,
      validationIssueCount: objects.reduce((sum, object) => sum + object.validationIssues.length, 0)
        + relations.reduce((sum, relation) => sum + relation.validationIssues.length, 0),
      sourceNodeCount: objects.length,
      sourceEdgeCount: relations.length,
      flowCount: 0,
      stateMachineCount: 0,
      simulationScenarioCount: 0,
    },
    analysis: { flow_count: 0, state_machine_count: 0, simulation_scenario_count: 0 },
  };
}

function mergeObservedLayers(baseLayers: OntologyLayerView[], objects: OntologyObject[]) {
  const byId = new Map(baseLayers.map((layer) => [layer.id, { ...layer }]));
  let nextOrder = baseLayers.reduce((max, layer) => Math.max(max, layer.order), -1) + 1;
  objects.forEach((object) => {
    const layer = byId.get(object.layerId) ?? makeLayerFromObject(object);
    if (!byId.has(object.layerId)) {
      layer.order = nextOrder;
      nextOrder += 1;
    }
    layer.count += byId.has(object.layerId) ? 0 : 0;
    byId.set(object.layerId, layer);
  });
  const counts = countBy(objects, 'layerId');
  return Array.from(byId.values())
    .map((layer) => ({ ...layer, count: counts[layer.id] ?? layer.count ?? 0 }))
    .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
}

function countBy<T, K extends keyof T>(items: T[], key: K) {
  return items.reduce<Record<string, number>>((acc, item) => {
    const value = String(item[key] ?? 'unassigned');
    acc[value] = (acc[value] ?? 0) + 1;
    return acc;
  }, {});
}

function topEntries(values: Record<string, number>, limit = 3) {
  return Object.entries(values)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit);
}

function describeEntries(values: Record<string, number>, limit = 3) {
  const entries = topEntries(values, limit);
  if (!entries.length) return 'No values observed yet';
  return entries.map(([name, count]) => `${titleize(name)} (${count})`).join(', ');
}

function filterValues(data: OntologyMapData, key: FilterKey) {
  if (key === 'layer') return data.layers.map((layer) => layer.id);
  if (key === 'objectType') return Array.from(new Set(data.objects.map((object) => object.objectType))).sort();
  if (key === 'abstraction') return Array.from(new Set(data.objects.map((object) => object.abstractionId))).sort();
  if (key === 'relationshipFamily') return Array.from(new Set(data.relations.map((relation) => relation.family))).sort();
  if (key === 'pack') return Array.from(new Set(data.objects.map((object) => object.packId))).sort();
  if (key === 'lifecycle') return Array.from(new Set(data.objects.map((object) => object.lifecycleState))).sort();
  if (key === 'review') return Array.from(new Set([...data.objects.map((object) => object.reviewState), ...data.relations.map((relation) => relation.reviewState)])).sort();
  if (key === 'owner') return Array.from(new Set(data.objects.map((object) => object.owner))).sort();
  return Array.from(new Set(data.objects.map((object) => object.qualityState))).sort();
}

function displayValue(data: OntologyMapData, key: FilterKey, value: string) {
  if (key === 'layer') return data.layers.find((layer) => layer.id === value)?.label ?? titleize(value);
  return titleize(value);
}

function buildInitialFilters(data: OntologyMapData): ActiveFilters {
  return Object.fromEntries(FILTER_KEYS.map((key) => [key, filterValues(data, key)])) as ActiveFilters;
}

function objectVisible(object: OntologyObject, filters: ActiveFilters) {
  return (
    filters.layer.includes(object.layerId)
    && filters.objectType.includes(object.objectType)
    && filters.abstraction.includes(object.abstractionId)
    && filters.pack.includes(object.packId)
    && filters.lifecycle.includes(object.lifecycleState)
    && filters.review.includes(object.reviewState)
    && filters.owner.includes(object.owner)
    && filters.quality.includes(object.qualityState)
  );
}

function relationVisible(relation: OntologyRelation, visibleObjectIds: Set<string>, filters: ActiveFilters) {
  return visibleObjectIds.has(relation.mapSource)
    && visibleObjectIds.has(relation.mapTarget)
    && filters.relationshipFamily.includes(relation.family)
    && filters.review.includes(relation.reviewState);
}

function computeLayout(data: OntologyMapData, objects: OntologyObject[], hostWidth: number, density: DensityMode = 'comfortable'): LayoutResult {
  const densityScale = density === 'compact' ? 0.78 : density === 'spacious' ? 1.22 : 1;
  const usableWidth = Math.max(hostWidth - SVG_PAD_X * 2, NODE_W);
  const cols = Math.max(1, Math.floor((usableWidth + H_GAP) / (NODE_W + H_GAP * densityScale))); 
  const positions: LayoutResult['positions'] = {};
  const lanes: LayoutResult['lanes'] = [];
  let y = 0;

  const layerObjects = new Map<string, OntologyObject[]>();
  objects.forEach((object) => {
    const list = layerObjects.get(object.layerId) ?? [];
    list.push(object);
    layerObjects.set(object.layerId, list);
  });

  const layers = data.layers.length ? data.layers : mergeObservedLayers([], objects);
  layers.forEach((layer) => {
    const objectsInLayer = (layerObjects.get(layer.id) ?? []).sort((a, b) => {
      const typeCompare = a.objectTypeLabel.localeCompare(b.objectTypeLabel);
      return typeCompare || a.name.localeCompare(b.name);
    });
    const rows = Math.max(1, Math.ceil(objectsInLayer.length / cols));
    const laneHeight = Math.max(100, LANE_PAD_TOP + rows * NODE_H + (rows - 1) * V_GAP * densityScale + LANE_PAD_BOTTOM);
    lanes.push({ layerId: layer.id, label: layer.label, y0: y, y1: y + laneHeight, count: objectsInLayer.length });
    objectsInLayer.forEach((object, index) => {
      const row = Math.floor(index / cols);
      const col = index % cols;
      const rowCount = Math.min(cols, objectsInLayer.length - row * cols);
      const rowWidth = rowCount * NODE_W + (rowCount - 1) * H_GAP;
      const startX = SVG_PAD_X + Math.max(0, (usableWidth - rowWidth) / 2);
      positions[object.id] = {
        x: startX + col * (NODE_W + H_GAP),
        y: y + LANE_PAD_TOP + row * (NODE_H + V_GAP * densityScale),
      };
    });
    y += laneHeight;
  });

  return { positions, lanes, width: Math.max(hostWidth, 920), height: Math.max(y, 260) };
}

function connectedObjectIds(data: OntologyMapData, selectedId: string | null) {
  const connected = new Set<string>();
  if (!selectedId) return connected;
  connected.add(selectedId);
  data.relations.forEach((relation) => {
    if (relation.mapSource === selectedId) connected.add(relation.mapTarget);
    if (relation.mapTarget === selectedId) connected.add(relation.mapSource);
  });
  return connected;
}

function objectById(data: OntologyMapData, id: string) {
  return data.objects.find((object) => object.id === id);
}

function issueText(issue: Record<string, unknown>) {
  return String(issue.message ?? issue.code ?? issue.path ?? 'Ontology validation issue');
}

interface EnterpriseMapPanelProps {
  selectedNamespace: string | null;
  /** Deterministic browser-QA data. When provided, API hooks are disabled. */
  fixtureMap?: EnterpriseMapProjectionData;
  fixtureProfile?: OntologyProfile | null;
  fixtureInitialSelectedId?: string | null;
  fixtureObservationEvents?: ObservationEvent[];
  fixtureTimeSeries?: TimeSeries[];
  /** Workbench-shell profile draft used for labels/defaults without disabling live map hooks. */
  profileOverride?: OntologyProfile | null;
  /** Example-only map used only when no live/projection/explorer objects exist. */
  fallbackMap?: EnterpriseMapProjectionData | null;
  /** Optional shell-driven concept type focus from the Spec Lens selection. */
  conceptTypeFilter?: string | null;
  onInstanceSelect?: (selection: { id: string; title: string; concept_type: string; source: 'live' | 'example' }) => void;
}

export default function EnterpriseMapPanel({
  selectedNamespace,
  fixtureMap,
  fixtureProfile,
  fixtureInitialSelectedId = null,
  fixtureObservationEvents = [],
  fixtureTimeSeries = [],
  profileOverride = null,
  fallbackMap = null,
  conceptTypeFilter = null,
  onInstanceSelect,
}: EnterpriseMapPanelProps) {
  const hookNamespace = fixtureMap ? null : selectedNamespace;
  const enterpriseMap = useEnterpriseMap(hookNamespace, 200);
  const explorer = useKnowledgeExplorer(hookNamespace);
  const { isSeeded, seed } = explorer;
  const { profile } = useOntologyProfile(hookNamespace);
  const liveMap = fixtureMap ?? enterpriseMap.map;
  const effectiveProfile = fixtureProfile ?? profileOverride ?? profile;
  const shouldUseFallbackMap = !fixtureMap && !liveMap?.nodes.length && !explorer.nodes.length && Boolean(fallbackMap?.nodes.length);
  const effectiveMap = shouldUseFallbackMap ? fallbackMap : liveMap;
  const [activeView, setActiveView] = React.useState<ViewName>('map');
  const [selectedId, setSelectedId] = React.useState<string | null>(fixtureInitialSelectedId);
  const [savedFocusId, setSavedFocusId] = React.useState<string | null>(fixtureInitialSelectedId);
  const [page, setPage] = React.useState(0);
  const [pageSize, setPageSize] = React.useState<number>(PAGE_SIZE_OPTIONS[0]);
  const [density, setDensity] = React.useState<DensityMode>('comfortable');
  const [timeMode, setTimeMode] = React.useState<TimeSelectionMode>('none');
  const [hostWidth, setHostWidth] = React.useState(980);
  const graphHostRef = React.useRef<HTMLDivElement | null>(null);
  const svgUid = React.useId().replace(/:/g, '');

  React.useEffect(() => {
    if (fixtureMap || fallbackMap || !selectedNamespace || isSeeded || enterpriseMap.isLoading || effectiveMap?.nodes.length) return;
    void seed(40);
  }, [enterpriseMap.isLoading, effectiveMap?.nodes.length, fallbackMap, fixtureMap, isSeeded, seed, selectedNamespace]);

  React.useEffect(() => {
    const host = graphHostRef.current;
    if (!host) return;
    const update = () => setHostWidth(host.clientWidth || 980);
    update();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update);
      return () => window.removeEventListener('resize', update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  const enterpriseSignature = effectiveMap
    ? [
      effectiveMap.layers.map((layer) => `${layer.id}:${layer.label}:${layer.order}:${layer.count}`).join('|'),
      effectiveMap.nodes.map((node) => `${node.id}:${node.name}:${node.layer_id}:${node.layer_label}:${node.concept_type}:${node.lifecycle_state}:${node.pack_id}`).join('|'),
      effectiveMap.edges.map((edge) => `${edge.source}:${edge.target}:${edge.map_source}:${edge.map_target}:${edge.relationship_type || edge.label}`).join('|'),
      effectiveMap.stats.ontology_candidate_count ?? 0,
    ].join('::')
    : 'no-enterprise-map';
  const graphSignature = [
    explorer.nodes.map((node) => `${node.id}:${node.name}:${node.layer}:${node.concept_type}:${node.lifecycle_state}:${node.pack_id}`).join('|'),
    explorer.edges.map((edge) => `${edge.source}:${edge.target}:${edge.relationship_type || edge.label}`).join('|'),
  ].join('::');
  const profileSignature = effectiveProfile ? JSON.stringify({ profile_id: effectiveProfile.profile_id, version: effectiveProfile.version, concept_types: effectiveProfile.concept_types, relationship_types: effectiveProfile.relationship_types, graph_instruction: effectiveProfile.graph_instruction, layers: effectiveProfile.layers }) : 'no-profile';

  const data = React.useMemo(() => {
    if (effectiveMap?.nodes.length) return mapProjectionData(effectiveMap, effectiveProfile, selectedNamespace);
    if (!fixtureMap && explorer.nodes.length) return mapExplorerFallback(explorer.nodes, explorer.edges, effectiveProfile, selectedNamespace);
    return { ...DEFAULT_MAP_DATA, ...profileMeta(null, effectiveProfile, selectedNamespace) };
    // Hook adapters can return new identities while carrying identical graph content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enterpriseSignature, graphSignature, profileSignature, selectedNamespace]);

  const [filters, setFilters] = React.useState<ActiveFilters>(() => buildInitialFilters(data));

  React.useEffect(() => {
    setFilters(buildInitialFilters(data));
    setSelectedId(savedFocusId && data.objects.some((object) => object.id === savedFocusId) ? savedFocusId : null);
    setPage(0);
  }, [data, savedFocusId]);

  React.useEffect(() => {
    if (!conceptTypeFilter) return;
    setFilters((current) => ({
      ...current,
      objectType: data.objects.some((object) => object.objectType === conceptTypeFilter) ? [conceptTypeFilter] : current.objectType,
    }));
    setPage(0);
  }, [conceptTypeFilter, data.objects]);

  const filteredObjects = React.useMemo(() => data.objects.filter((object) => objectVisible(object, filters)), [data.objects, filters]);
  const totalPages = Math.max(1, Math.ceil(filteredObjects.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const visibleObjects = React.useMemo(() => filteredObjects.slice(safePage * pageSize, safePage * pageSize + pageSize), [filteredObjects, pageSize, safePage]);
  const visibleObjectIds = React.useMemo(() => new Set(visibleObjects.map((object) => object.id)), [visibleObjects]);
  const visibleRelations = React.useMemo(
    () => data.relations.filter((relation) => relationVisible(relation, visibleObjectIds, filters)),
    [data.relations, filters, visibleObjectIds],
  );
  const layout = React.useMemo(() => computeLayout(data, visibleObjects, hostWidth, density), [data, visibleObjects, hostWidth, density]);
  const selectedObject = selectedId ? data.objects.find((object) => object.id === selectedId) ?? null : null;
  const mapSourceKind: 'live' | 'example' = shouldUseFallbackMap ? 'example' : 'live';
  const hookObservation = useOntologyObservation(hookNamespace, selectedId);
  const rawObservationEvents = fixtureMap ? fixtureObservationEvents.filter((event) => !selectedId || event.subject_id === selectedId) : hookObservation.events;
  const rawTimeSeries = fixtureMap ? fixtureTimeSeries.filter((item) => !selectedId || item.subject_id === selectedId) : hookObservation.series;
  const observationEvents = React.useMemo(
    () => filterEventsForTimeMode(rawObservationEvents, timeMode, selectedObject, data.profileVersion),
    [rawObservationEvents, timeMode, selectedObject, data.profileVersion],
  );
  const observationSeries = React.useMemo(
    () => filterSeriesForTimeMode(rawTimeSeries, timeMode, observationEvents, selectedObject, data.profileVersion),
    [rawTimeSeries, timeMode, observationEvents, selectedObject, data.profileVersion],
  );
  const connected = React.useMemo(() => connectedObjectIds(data, selectedId), [data, selectedId]);
  const workbenchModel = React.useMemo(() => mapLensAdapter(effectiveMap, selectedNamespace ?? undefined), [effectiveMap, selectedNamespace]);
  const graphEdges = React.useMemo(() => {
    const seenTypes = new Set<string>();
    return visibleRelations.flatMap<GraphEdge>((relation) => {
      const source = objectById(data, relation.mapSource);
      const target = objectById(data, relation.mapTarget);
      if (!source || !target) return [];
      const testId = seenTypes.has(relation.type) ? undefined : `edge-${relation.type}`;
      seenTypes.add(relation.type);
      return [{ source, target, relation, testId }];
    });
  }, [data, visibleRelations]);

  React.useEffect(() => {
    if (page >= totalPages) setPage(totalPages - 1);
  }, [page, totalPages]);

  const toggleFilter = React.useCallback((key: FilterKey, value: string, checked: boolean) => {
    setFilters((prev) => {
      const current = new Set(prev[key]);
      if (checked) current.add(value);
      else current.delete(value);
      return { ...prev, [key]: Array.from(current) };
    });
    setSelectedId(null);
    setPage(0);
  }, []);

  const selectObject = React.useCallback((id: string) => {
    const object = data.objects.find((item) => item.id === id);
    setSelectedId(id);
    setSavedFocusId(id);
    setActiveView('map');
    if (object) onInstanceSelect?.({ id: object.id, title: object.name, concept_type: object.objectType, source: mapSourceKind });
  }, [data.objects, mapSourceKind, onInstanceSelect]);

  return (
    <WorkbenchShell model={workbenchModel} passthrough>
    <div className="enterprise-map-shell" data-testid="enterprise-map-panel" data-modules={ENTERPRISE_MAP_MODULES.join(',')}>
      <style>{MAP_PANEL_CSS}</style>
      <EnterpriseMapHeader data={data} activeView={activeView} onViewChange={setActiveView} />
      {shouldUseFallbackMap ? <div className="emp-example-banner" data-testid="enterprise-map-example-banner">Examples only — no confirmed company instances are available for this namespace. These cards come from GraphInstruction/domain-pack fallbacks and are not persisted.</div> : null}
      {conceptTypeFilter ? <div className="emp-filter-banner" data-testid="enterprise-map-concept-filter">Map Lens filtered to type: <strong>{titleize(conceptTypeFilter)}</strong></div> : null}

      <SummaryBar data={data} visibleObjectCount={visibleObjects.length} visibleRelationCount={visibleRelations.length} />
      <LargeGraphControls
        filteredCount={filteredObjects.length}
        visibleCount={visibleObjects.length}
        page={safePage}
        totalPages={totalPages}
        pageSize={pageSize}
        density={density}
        savedFocusId={savedFocusId}
        onPageChange={setPage}
        onPageSizeChange={(nextSize) => { setPageSize(nextSize); setPage(0); }}
        onDensityChange={setDensity}
        onRestoreFocus={() => savedFocusId && setSelectedId(savedFocusId)}
      />
      <OntologyPrinciples data={data} />
      <MapObjectSelectionRail objects={visibleObjects} onSelectObject={selectObject} />

      <div className="emp-layout">
        <FiltersSidebar data={data} filters={filters} onToggle={toggleFilter} />

        <main className="emp-main">
          <TimeSelectionControls mode={timeMode} onModeChange={(nextMode) => setTimeMode(nextMode)} />
          <EnterpriseMapViews
            activeView={activeView}
            data={data}
            layout={layout}
            graphEdges={graphEdges}
            selectedId={selectedId}
            connected={connected}
            svgUid={svgUid}
            graphHostRef={graphHostRef}
            onSelectObject={(id) => { setSelectedId(id); if (id) { setSavedFocusId(id); const object = data.objects.find((item) => item.id === id); if (object) onInstanceSelect?.({ id: object.id, title: object.name, concept_type: object.objectType, source: mapSourceKind }); } }}
            onClearFocus={() => setSelectedId(null)}
            onInspectObject={selectObject}
          />
          <SeriesTimePanel selectedObject={selectedObject} mode={timeMode} events={observationEvents} series={observationSeries} isLoading={fixtureMap ? false : hookObservation.isLoading} error={fixtureMap ? null : hookObservation.error} />
        </main>

        <DetailSidebar data={data} selectedObject={selectedObject} onSelectObject={selectObject} />
      </div>
    </div>
    </WorkbenchShell>
  );
}


function EnterpriseMapHeader({ data, activeView, onViewChange }: { data: OntologyMapData; activeView: ViewName; onViewChange: (view: ViewName) => void }) {
  return (
    <header className="emp-header">
      <div>
        <h1>Enterprise Ontology Map</h1>
        <div className="emp-meta">
          {data.namespace ? <span>{data.namespace}</span> : <span>No namespace selected</span>}
          <span>Profile {data.profileId} v{data.profileVersion}</span>
          <span>{data.profileStatus}</span>
        </div>
      </div>
      <nav className="emp-view-toggle" aria-label="Views">
        {VIEW_BUTTONS.map((button) => (
          <button
            key={button.id}
            type="button"
            className={activeView === button.id ? 'active' : undefined}
            onClick={() => onViewChange(button.id)}
          >
            {button.label}
          </button>
        ))}
      </nav>
    </header>
  );
}

function EnterpriseMapViews({
  activeView,
  data,
  layout,
  graphEdges,
  selectedId,
  connected,
  svgUid,
  graphHostRef,
  onSelectObject,
  onClearFocus,
  onInspectObject,
}: {
  activeView: ViewName;
  data: OntologyMapData;
  layout: LayoutResult;
  graphEdges: GraphEdge[];
  selectedId: string | null;
  connected: Set<string>;
  svgUid: string;
  graphHostRef: React.RefObject<HTMLDivElement | null>;
  onSelectObject: (id: string | null) => void;
  onClearFocus: () => void;
  onInspectObject: (id: string) => void;
}) {
  return (
    <>
      <section className={`emp-main-view ${activeView === 'map' ? 'active' : ''}`}>
        <div className="emp-graph-host" ref={graphHostRef}>
          <GraphSvg
            data={data}
            layout={layout}
            graphEdges={graphEdges}
            selectedId={selectedId}
            connected={connected}
            svgUid={svgUid}
            onSelectObject={onSelectObject}
          />
          <NodeHitOverlay
            objects={data.objects}
            layout={layout}
            onSelectObject={onSelectObject}
          />
          <FlowStateOverlay data={data} selectedId={selectedId} onSelectObject={onSelectObject} />
        </div>
        <button
          className={`emp-focus-hint ${selectedId ? 'show' : ''}`}
          type="button"
          onClick={onClearFocus}
        >
          Clear focus
        </button>
        <Legend data={data} />
      </section>

      <section className={`emp-main-view ${activeView === 'layers' ? 'active' : ''}`}>
        <LayersView data={data} onSelectObject={onInspectObject} />
      </section>
      <section className={`emp-main-view ${activeView === 'objects' ? 'active' : ''}`}>
        <ObjectTypesView data={data} onSelectObject={onInspectObject} />
      </section>
      <section className={`emp-main-view ${activeView === 'relations' ? 'active' : ''}`}>
        <RelationsView data={data} onSelectObject={onInspectObject} />
      </section>
      <section className={`emp-main-view ${activeView === 'quality' ? 'active' : ''}`}>
        <QualityView data={data} onSelectObject={onInspectObject} />
      </section>
      <section className={`emp-main-view ${activeView === 'simulation' ? 'active' : ''}`}>
        <SimulationView data={data} onSelectObject={onInspectObject} />
      </section>
    </>
  );
}

function LargeGraphControls({
  filteredCount,
  visibleCount,
  page,
  totalPages,
  pageSize,
  density,
  savedFocusId,
  onPageChange,
  onPageSizeChange,
  onDensityChange,
  onRestoreFocus,
}: {
  filteredCount: number;
  visibleCount: number;
  page: number;
  totalPages: number;
  pageSize: number;
  density: DensityMode;
  savedFocusId: string | null;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onDensityChange: (density: DensityMode) => void;
  onRestoreFocus: () => void;
}) {
  return (
    <section className="emp-safeguards" aria-label="Large graph safeguards" data-testid="enterprise-map-safeguards">
      <span>{visibleCount} of {filteredCount} objects shown</span>
      <label>
        Page size
        <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
          {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}</option>)}
        </select>
      </label>
      <label>
        Density
        <select value={density} onChange={(event) => onDensityChange(event.target.value as DensityMode)}>
          <option value="compact">Compact</option>
          <option value="comfortable">Comfortable</option>
          <option value="spacious">Spacious</option>
        </select>
      </label>
      <button type="button" disabled={page <= 0} onClick={() => onPageChange(page - 1)}>Previous page</button>
      <span>Page {page + 1} of {totalPages}</span>
      <button type="button" disabled={page >= totalPages - 1} onClick={() => onPageChange(page + 1)}>Next page</button>
      <button type="button" disabled={!savedFocusId} onClick={onRestoreFocus}>Restore saved focus</button>
    </section>
  );
}

function SummaryBar({ data, visibleObjectCount, visibleRelationCount }: { data: OntologyMapData; visibleObjectCount: number; visibleRelationCount: number }) {
  const cards = [
    ['Objects', data.stats.nodeCount, `${visibleObjectCount} visible across ${data.stats.layerCount} ontology layers`],
    ['Object types', data.stats.objectTypeCount, describeEntries(data.conceptTypeCounts)],
    ['Relationships', data.stats.relationshipTypeCount, describeEntries(data.relationshipTypeCounts)],
    ['Relation families', Object.keys(data.relationshipFamilyCounts).length, describeEntries(data.relationshipFamilyCounts)],
    ['Review state', data.stats.ontologyCandidateCount, `${data.stats.validationIssueCount} validation issues, ${data.stats.candidateEdgeCount} candidate edges`],
    ['Projection scope', data.stats.limit ? `${data.stats.sourceNodeCount ?? data.stats.nodeCount}/${data.stats.limit}` : data.stats.sourceNodeCount ?? data.stats.nodeCount, `${visibleRelationCount} visible relationships`],
  ];

  return (
    <section className="emp-summary-bar">
      {cards.map(([label, value, hint]) => (
        <div className="emp-summary-card" key={String(label)}>
          <div className="label">{label}</div>
          <div className="value">{value}</div>
          <div className="hint">{hint}</div>
        </div>
      ))}
    </section>
  );
}

function OntologyPrinciples({ data }: { data: OntologyMapData }) {
  const items = [
    ['Ontology layers', data.layers.length ? data.layers.map((layer) => layer.label).join(', ') : 'Layers are defined by the active namespace ontology profile.'],
    ['Object types', describeEntries(data.conceptTypeCounts, 5)],
    ['Relationship semantics', describeEntries(data.relationshipFamilyCounts, 5)],
    ['Governance loop', `${data.stats.ontologyCandidateCount} pending candidates and ${data.stats.validationIssueCount} validation issues keep the profile reviewable.`],
  ];
  return (
    <section className="emp-concept-strip">
      {items.map(([key, value], index) => (
        <div className="emp-concept" key={key}>
          <span className="emp-concept-accent" style={{ background: FALLBACK_LAYER_COLORS[index % FALLBACK_LAYER_COLORS.length] }} aria-hidden="true" />
          <div className="k">{key}</div>
          <div className="v">{value}</div>
        </div>
      ))}
    </section>
  );
}

function FiltersSidebar({ data, filters, onToggle }: { data: OntologyMapData; filters: ActiveFilters; onToggle: (key: FilterKey, value: string, checked: boolean) => void }) {
  const config: Array<{ key: FilterKey; label: string; color: (value: string) => string | null }> = [
    { key: 'layer', label: 'Ontology layer', color: (value) => layerColor(value, displayValue(data, 'layer', value)) },
    { key: 'objectType', label: 'Object type', color: (value) => data.objects.find((object) => object.objectType === value)?.objectColor ?? fallbackColor(value) },
    { key: 'abstraction', label: 'Abstraction', color: (value) => fallbackColor(value) },
    { key: 'relationshipFamily', label: 'Relationship family', color: (value) => fallbackColor(value) },
    { key: 'pack', label: 'Pack', color: () => null },
    { key: 'lifecycle', label: 'Lifecycle', color: (value) => fallbackColor(value) },
    { key: 'review', label: 'Review state', color: (value) => fallbackColor(value) },
    { key: 'owner', label: 'Owner', color: () => null },
    { key: 'quality', label: 'Quality state', color: (value) => fallbackColor(value) },
  ];

  return (
    <aside className="emp-filters" data-testid="enterprise-map-filters">
      {config.map((item) => {
        const values = filterValues(data, item.key);
        if (!values.length) return null;
        const counts = countFilterValues(data, item.key);
        return (
          <section key={item.key}>
            <h3>{item.label}</h3>
            <div>
              {values.map((value) => {
                const color = item.color(value);
                return (
                  <label key={value}>
                    <input
                      type="checkbox"
                      checked={filters[item.key]?.includes(value) ?? false}
                      onChange={(event) => onToggle(item.key, value, event.target.checked)}
                    />
                    {color && <span className="emp-swatch" style={{ background: `${color}22`, borderColor: color }} />}
                    <span>{displayValue(data, item.key, value)}</span>
                    <span className="emp-count">{counts[value] ?? 0}</span>
                  </label>
                );
              })}
            </div>
          </section>
        );
      })}
    </aside>
  );
}

function countFilterValues(data: OntologyMapData, key: FilterKey) {
  if (key === 'layer') return countBy(data.objects, 'layerId');
  if (key === 'objectType') return countBy(data.objects, 'objectType');
  if (key === 'abstraction') return countBy(data.objects, 'abstractionId');
  if (key === 'relationshipFamily') return countBy(data.relations, 'family');
  if (key === 'pack') return countBy(data.objects, 'packId');
  if (key === 'lifecycle') return countBy(data.objects, 'lifecycleState');
  if (key === 'review') return countBy(data.objects, 'reviewState');
  if (key === 'owner') return countBy(data.objects, 'owner');
  return countBy(data.objects, 'qualityState');
}

function GraphSvg({
  data,
  layout,
  graphEdges,
  selectedId,
  connected,
  svgUid,
  onSelectObject,
}: {
  data: OntologyMapData;
  layout: LayoutResult;
  graphEdges: GraphEdge[];
  selectedId: string | null;
  connected: Set<string>;
  svgUid: string;
  onSelectObject: (id: string | null) => void;
}) {
  return (
    <svg
      className="emp-graph-svg"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Enterprise ontology object relationship map"
      data-testid="enterprise-map-graph"
      width={layout.width}
      height={layout.height}
      viewBox={`0 0 ${layout.width} ${layout.height}`}
    >
      <defs>
        {data.layers.map((layer) => (
          <marker
            key={layer.id}
            id={`arrow-${svgUid}-${layer.id.replace(/\W+/g, '-')}`}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill={layerColor(layer.id, layer.label)} />
          </marker>
        ))}
      </defs>
      <rect x="0" y="0" width={layout.width} height={layout.height} fill="transparent" className="emp-graph-bg" onClick={() => onSelectObject(null)} />
      {layout.lanes.map((lane) => {
        const color = layerColor(lane.layerId, lane.label);
        const label = `${lane.label} - ${lane.count}`;
        const labelWidth = Math.min(360, label.length * 6.7 + 18);
        return (
          <g key={lane.layerId}>
            <rect x="0" y={lane.y0} width={layout.width} height={lane.y1 - lane.y0} className="emp-lane-bg" style={{ fill: `${color}10` }} />
            {lane.y1 < layout.height && <line x1="0" y1={lane.y1} x2={layout.width} y2={lane.y1} className="emp-lane-divider" />}
            <rect x="12" y={lane.y0 + 8} width={labelWidth} height="20" rx="5" className="emp-lane-label-bg" />
            <text x="20" y={lane.y0 + 22} className="emp-lane-label">{truncate(label, 46)}</text>
          </g>
        );
      })}
      {graphEdges.map((edge) => {
        const from = layout.positions[edge.source.id];
        const to = layout.positions[edge.target.id];
        if (!from || !to) return null;
        let cls = 'emp-edge';
        if (selectedId) cls += edge.source.id === selectedId || edge.target.id === selectedId ? ' focused' : ' dimmed';
        return (
          <path
            key={`${edge.source.id}-${edge.target.id}-${edge.relation.type}`}
            d={pathBetween(from.x + NODE_W / 2, from.y + NODE_H, to.x + NODE_W / 2, to.y)}
            className={cls}
            stroke={layerColor(edge.source.layerId, edge.source.layerLabel)}
            strokeWidth={edge.relation.style === 'bold' ? 2.4 : 1.6}
            strokeDasharray={RELATION_STYLE[edge.relation.style]}
            markerEnd={`url(#arrow-${svgUid}-${edge.source.layerId.replace(/\W+/g, '-')})`}
            data-testid={edge.testId}
          />
        );
      })}
      {data.objects.map((object) => {
        const pos = layout.positions[object.id];
        if (!pos) return null;
        let cls = `emp-node ${object.lifecycleState === 'candidate' ? 'candidate-instance' : ''} ${object.reviewState === 'pending' ? 'pending-candidate-entity' : ''}`;
        if (selectedId) {
          if (object.id === selectedId) cls += ' selected';
          else if (connected.has(object.id)) cls += ' related';
          else cls += ' dimmed';
        }
        return (
          <g
            key={object.id}
            className={cls}
            data-testid={`enterprise-node-${object.id}`}
            aria-hidden="true"
            onPointerDown={() => onSelectObject(object.id)}
            onMouseDown={() => onSelectObject(object.id)}
            onClick={() => onSelectObject(object.id)}
          >
            <rect
              x={pos.x}
              y={pos.y}
              width={NODE_W}
              height={NODE_H}
              rx={object.objectShape === 'rectangle' ? 2 : object.objectShape === 'diamond' ? 0 : 7}
              fill={`${object.objectColor}18`}
              stroke={object.objectColor}
              strokeWidth={object.lifecycleState === 'candidate' ? '2.2' : '1.6'}
              strokeDasharray={object.lifecycleState === 'candidate' ? '2 3' : object.validationIssues.length ? '5 4' : undefined}
            />
            <text x={pos.x + 9} y={pos.y + 17} className="id" fill="#354052">{truncate(object.id, 18)}</text>
            <text x={pos.x + 9} y={pos.y + 35} className="name" fill="#182230">{truncate(object.name, 24)}</text>
            <text x={pos.x + 9} y={pos.y + 54} className="meta" fill="#526071">{truncate(object.objectTypeLabel, 17)} - {truncate(object.lifecycleState, 10)}</text>
            <circle cx={pos.x + NODE_W - 13} cy={pos.y + 15} r="5" fill={object.objectColor} />
            {object.lifecycleState === 'candidate' && <text x={pos.x + NODE_W - 42} y={pos.y + 18} className="badge-text" fill="#92400e">C</text>}
            {object.validationIssues.length > 0 && <text x={pos.x + NODE_W - 30} y={pos.y + 18} className="badge-text" fill="#b91c1c">!</text>}
            {object.activeEventCount > 0 && <text x={pos.x + NODE_W - 19} y={pos.y + 34} className="badge-text" fill="#166534">A</text>}
            {object.eventCount > 0 && <text x={pos.x + NODE_W - 48} y={pos.y + 54} className="badge-text" fill="#1d4ed8">{object.eventCount}</text>}
            <title>{`Select ${object.name}. ${object.eventCount} observation events.`}</title>
          </g>
        );
      })}
      {!data.objects.some((object) => layout.positions[object.id]) && (
        <text x={layout.width / 2} y="130" textAnchor="middle" fill="#8a95a6">No ontology objects match the current filters.</text>
      )}
    </svg>
  );
}

function pathBetween(x1: number, y1: number, x2: number, y2: number) {
  const dy = Math.abs(y2 - y1);
  const c = Math.max(36, dy * 0.35);
  return `M ${x1} ${y1} C ${x1} ${y1 + c}, ${x2} ${y2 - c}, ${x2} ${y2}`;
}

function MapObjectSelectionRail({ objects, onSelectObject }: { objects: OntologyObject[]; onSelectObject: (id: string) => void }) {
  const railRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;

    const handleNativeSelection = (event: MouseEvent) => {
      const target = event.target instanceof HTMLElement ? event.target : null;
      const button = target?.closest<HTMLButtonElement>('[data-map-object-id]');
      const objectId = button?.dataset.mapObjectId;
      if (!objectId) return;
      event.preventDefault();
      onSelectObject(objectId);
    };

    rail.addEventListener('mousedown', handleNativeSelection);
    rail.addEventListener('click', handleNativeSelection);
    return () => {
      rail.removeEventListener('mousedown', handleNativeSelection);
      rail.removeEventListener('click', handleNativeSelection);
    };
  }, [onSelectObject]);

  if (!objects.length) return null;
  return (
    <div ref={railRef} className="emp-selection-rail" aria-label="Visible map objects">
      {objects.slice(0, 8).map((object) => (
        <button key={object.id} type="button" data-map-object-id={object.id} aria-label={`Focus ${object.name}`}>
          <span>{object.name}</span>
          <small>{object.objectTypeLabel} · {object.lifecycleState}</small>
        </button>
      ))}
    </div>
  );
}

function NodeHitOverlay({ objects, layout, onSelectObject }: { objects: OntologyObject[]; layout: LayoutResult; onSelectObject: (id: string | null) => void }) {
  return (
    <div className="emp-node-hit-overlay" aria-label="Enterprise map node hit targets">
      {objects.map((object) => {
        const pos = layout.positions[object.id];
        if (!pos) return null;
        return (
          <button
            key={object.id}
            type="button"
            className="emp-node-overlay-button"
            aria-label={`Select ${object.name}. ${object.eventCount} observation events.`}
            style={{ left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}
            onPointerDown={() => onSelectObject(object.id)}
            onMouseDown={() => onSelectObject(object.id)}
            onClick={() => onSelectObject(object.id)}
          >
            <span className="emp-sr-only">Select {object.name}</span>
          </button>
        );
      })}
    </div>
  );
}

function Legend({ data }: { data: OntologyMapData }) {
  return (
    <div className="emp-legend">
      <div className="emp-legend-title">Object fill = ontology object type</div>
      {topEntries(data.conceptTypeCounts, 8).map(([type]) => {
        const object = data.objects.find((item) => item.objectType === type);
        return <div className="emp-legend-item" key={type}><span className="emp-swatch" style={{ background: `${object?.objectColor ?? fallbackColor(type)}22`, borderColor: object?.objectColor ?? fallbackColor(type) }} />{object?.objectTypeLabel ?? titleize(type)}</div>;
      })}
      <div className="emp-legend-title">Lane and edge color = ontology layer</div>
      {data.layers.map((layer) => (
        <div className="emp-legend-item" key={layer.id}><span className="emp-swatch" style={{ background: layerColor(layer.id, layer.label) }} />{layer.label}</div>
      ))}
      <div className="emp-legend-title">Line style = relationship type style</div>
      <div className="emp-legend-item">Solid, dashed, dotted, and bold styles come from the relationship definition.</div>
    </div>
  );
}

function dateMs(value?: string | null) {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function selectedRangeMs(selectedObject: OntologyObject | null) {
  const range = optionalRecord(selectedObject?.timeRange);
  return { start: dateMs(String(range?.start ?? '')), end: dateMs(String(range?.end ?? '')) };
}

function eventMatchesCurrentProfile(event: ObservationEvent, profileVersion: string) {
  const metadata = asRecord(event.metadata);
  return String(metadata.profile_version ?? metadata.profileVersion ?? '') === profileVersion
    || String(metadata.active_profile_version ?? '') === profileVersion
    || event.subject_type === 'profile';
}

function filterEventsForTimeMode(events: ObservationEvent[], mode: TimeSelectionMode, selectedObject: OntologyObject | null, profileVersion: string) {
  if (mode === 'none') return events;
  if (mode === 'current_profile_version') return events.filter((event) => eventMatchesCurrentProfile(event, profileVersion));
  if (mode === 'latest_import') {
    const latestImport = events
      .filter((event) => event.event_type.toLowerCase().includes('import'))
      .map((event) => dateMs(event.occurred_at))
      .filter((value): value is number => value !== null)
      .sort((a, b) => b - a)[0];
    return latestImport ? events.filter((event) => (dateMs(event.occurred_at) ?? 0) >= latestImport) : [];
  }
  const range = selectedRangeMs(selectedObject);
  const fallbackStart = Date.now() - 30 * 24 * 60 * 60 * 1000;
  const start = range.start ?? fallbackStart;
  const end = range.end ?? Date.now();
  return events.filter((event) => {
    const occurred = dateMs(event.occurred_at);
    return occurred !== null && occurred >= start && occurred <= end;
  });
}

function filterSeriesForTimeMode(series: TimeSeries[], mode: TimeSelectionMode, events: ObservationEvent[], selectedObject: OntologyObject | null, profileVersion: string) {
  if (mode === 'none') return series;
  const eventTimes = new Set(events.map((event) => event.occurred_at));
  const range = selectedRangeMs(selectedObject);
  return series.map((item) => ({
    ...item,
    points: item.points.filter((point) => {
      if (mode === 'current_profile_version') {
        const metadata = asRecord(point.metadata);
        return String(metadata.profile_version ?? metadata.profileVersion ?? '') === profileVersion;
      }
      if (mode === 'latest_import') return eventTimes.has(point.timestamp) || events.some((event) => dateMs(point.timestamp) !== null && dateMs(event.occurred_at) !== null && (dateMs(point.timestamp) as number) >= (dateMs(event.occurred_at) as number));
      const timestamp = dateMs(point.timestamp);
      const start = range.start ?? Date.now() - 30 * 24 * 60 * 60 * 1000;
      const end = range.end ?? Date.now();
      return timestamp !== null && timestamp >= start && timestamp <= end;
    }),
  })).filter((item) => item.points.length > 0);
}

function TimeSelectionControls({ mode, onModeChange }: { mode: TimeSelectionMode; onModeChange: (mode: TimeSelectionMode) => void }) {
  const options: Array<{ id: TimeSelectionMode; label: string }> = [
    { id: 'none', label: 'All time' },
    { id: 'fixed_range', label: 'Fixed range' },
    { id: 'latest_import', label: 'Latest import' },
    { id: 'current_profile_version', label: 'Current profile' },
  ];
  return (
    <div className="emp-time-controls" aria-label="Observation time selection" role="group">
      <span>Time</span>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          className={mode === option.id ? 'active' : ''}
          aria-pressed={mode === option.id}
          data-testid={`time-mode-${option.id}`}
          onClick={() => onModeChange(option.id)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function SeriesTimePanel({ selectedObject, mode, events, series, isLoading, error }: { selectedObject: OntologyObject | null; mode: TimeSelectionMode; events: ObservationEvent[]; series: TimeSeries[]; isLoading: boolean; error: string | null }) {
  const isFilteredWindow = mode !== 'none';
  const candidateEvents = events.filter((event) => event.event_type.toLowerCase().includes('candidate')).length;
  const validationEvents = events.filter((event) => event.event_type.toLowerCase().includes('validation') || event.event_type.toLowerCase().includes('issue')).length;
  const activeEvents = events.filter((event) => isActiveObservationEvent(event)).length;
  const eventMetricValue = isFilteredWindow ? events.length : selectedObject?.eventCount || events.length;
  const activeMetricValue = isFilteredWindow ? activeEvents : selectedObject?.activeEventCount ?? activeEvents;
  const eventMetricHint = isFilteredWindow
    ? `${mode.replace(/_/g, ' ')} window`
    : selectedObject?.timeRange ? formatTimeRange(selectedObject.timeRange) : 'No time range recorded';
  return (
    <section className="emp-series-panel" aria-label="Series and time panel" data-testid="series-time-panel">
      <div className="emp-series-head">
        <div>
          <h3>Series / Time</h3>
          <p>{selectedObject ? `Observation signals for ${selectedObject.name}` : 'Select an object to inspect real observation signals.'}</p>
        </div>
        <span className="emp-badge">{mode.replace(/_/g, ' ')}</span>
      </div>
      {error ? <div className="emp-empty error">Could not load observation data: {error}</div> : null}
      {isLoading ? <div className="emp-empty">Loading observation signals...</div> : null}
      {!selectedObject && !isLoading ? <div className="emp-empty">No object selected. The panel stays empty rather than showing mock metrics.</div> : null}
      {selectedObject && !isLoading && !error ? (
        <div className="emp-series-grid">
          <MetricCard label="Events" value={eventMetricValue} hint={eventMetricHint} />
          <MetricCard label="Active" value={activeMetricValue} hint={isFilteredWindow ? 'active events in selected window' : 'confirmed/approved/issue events'} />
          <MetricCard label="Candidates" value={candidateEvents} hint={isFilteredWindow ? 'candidate events in selected window' : 'candidate lifecycle events'} />
          <MetricCard label="Validation" value={(isFilteredWindow ? 0 : selectedObject.validationIssues.length) + validationEvents} hint={isFilteredWindow ? 'validation events in selected window' : 'object issues + events'} />
          <div className="emp-series-list">
            <strong>Metric keys</strong>
            {series.length ? series.map((item) => <span key={item.id}>{item.metric_id} ({item.points.length} pts)</span>) : <span>No time-series records for this selection.</span>}
          </div>
          <div className="emp-series-list">
            <strong>Recent events</strong>
            {events.length ? events.slice(0, 4).map((event) => <span key={event.id}>{titleize(event.event_type)} · {new Date(event.occurred_at).toLocaleString()}</span>) : <span>No observation events recorded for this object.</span>}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: number; hint: string }) {
  return <div className="emp-metric-card"><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>;
}

function isActiveObservationEvent(event: ObservationEvent) {
  const type = event.event_type.toLowerCase();
  const value = String(event.value ?? '').toLowerCase();
  return type.includes('approved') || type.includes('validation') || type.includes('issue') || value === 'approved' || value === 'warning' || value === 'active';
}

function formatTimeRange(value: Record<string, unknown> | string | null) {
  if (!value) return 'No time window';
  if (typeof value === 'string') return value;
  const start = value.start ? new Date(String(value.start)).toLocaleDateString() : 'unknown';
  const end = value.end ? new Date(String(value.end)).toLocaleDateString() : 'unknown';
  return `${start} → ${end}`;
}

function FlowStateOverlay({ data, selectedId, onSelectObject }: { data: OntologyMapData; selectedId: string | null; onSelectObject: (id: string | null) => void }) {
  const flowObjects = data.objects.filter((object) => object.flowRefs.length || object.state);
  if (!flowObjects.length) return null;
  return (
    <div className="emp-analysis-overlay" aria-label="Flow and state overlays" data-testid="analysis-overlay">
      <strong>Flow / state overlays</strong>
      {flowObjects.slice(0, 4).map((object) => (
        <button key={object.id} type="button" className={selectedId === object.id ? 'active' : undefined} onClick={() => onSelectObject(object.id)}>
          <span>{object.name}</span>
          <small>{object.flowRefs.length ? `${object.flowRefs.length} flow` : 'no flow'} · {object.state ? `state ${object.state}` : 'state pending'}</small>
        </button>
      ))}
    </div>
  );
}

function SimulationView({ data, onSelectObject }: { data: OntologyMapData; onSelectObject: (id: string) => void }) {
  const scenarioObjects = data.objects.filter((object) => object.simulationState || object.simulationRefs.length);
  return (
    <>
      <h2 className="emp-panel-title">Simulation extension point</h2>
      <p className="emp-panel-subtitle">Simulation is provider-backed only. The core product stores scenarios and assumptions, but does not generate predictions or fake metrics.</p>
      <div className="emp-simulation-rail" data-testid="simulation-rail">
        {!data.analysis.simulation_scenario_count ? (
          <div className="emp-empty">No simulation scenario exists for this namespace. Add a saved scenario and a provider before any outputs can appear.</div>
        ) : null}
        {data.analysis.simulation_scenario_count > 0 && data.analysis.simulation_provider_required ? (
          <div className="emp-empty warning">Provider required: saved scenarios are present, but no registered analysis provider or saved result backs outputs yet.</div>
        ) : null}
        {data.analysis.provider_contract ? <div className="emp-provider-contract">{data.analysis.provider_contract}</div> : null}
        {scenarioObjects.length ? (
          <div className="emp-group-grid">
            {scenarioObjects.map((object) => (
              <article className="emp-group-card" key={object.id}>
                <div className="name">{object.name}</div>
                <div className="emp-pill-row"><span className="emp-pill">{object.simulationState?.replace(/_/g, ' ')}</span><span className="emp-pill">{object.simulationRefs.length} scenario refs</span></div>
                <button type="button" onClick={() => onSelectObject(object.id)}>Inspect graph object</button>
              </article>
            ))}
          </div>
        ) : data.analysis.simulation_scenario_count ? <div className="emp-empty">Scenarios exist, but none reference currently visible graph nodes.</div> : null}
      </div>
    </>
  );
}

function DetailSidebar({ data, selectedObject, onSelectObject }: { data: OntologyMapData; selectedObject: OntologyObject | null; onSelectObject: (id: string) => void }) {
  if (!selectedObject) {
    return (
      <aside className="emp-detail" role="dialog" aria-label="Detail drawer" data-testid="enterprise-detail-drawer">
        <div className="emp-detail-panel">
          <p className="emp-empty">Click an object to inspect its ontology path, metadata, relationships, and validation state.</p>
        </div>
      </aside>
    );
  }

  const incoming = data.relations.filter((relation) => relation.mapTarget === selectedObject.id);
  const outgoing = data.relations.filter((relation) => relation.mapSource === selectedObject.id);
  return (
    <aside className="emp-detail" role="dialog" aria-label="Detail drawer" data-testid="enterprise-detail-drawer">
      <div className="emp-node-card">
        <h2>{selectedObject.id} - {selectedObject.name}</h2>
        <div className="emp-badge-row">
          <span className="emp-badge" style={{ borderColor: layerColor(selectedObject.layerId, selectedObject.layerLabel), background: `${layerColor(selectedObject.layerId, selectedObject.layerLabel)}16` }}>{selectedObject.layerLabel}</span>
          <span className="emp-badge" style={{ borderColor: selectedObject.objectColor, background: `${selectedObject.objectColor}18` }}>{selectedObject.objectTypeLabel}</span>
          <span className="emp-badge">{selectedObject.abstractionLabel}</span>
          <span className="emp-badge">{selectedObject.lifecycleState === 'candidate' ? 'unverified candidate instance' : selectedObject.lifecycleState}</span>
          {selectedObject.eventCount > 0 && <span className="emp-badge emp-badge-event">{selectedObject.eventCount} events</span>}
          {selectedObject.activeEventCount > 0 && <span className="emp-badge emp-badge-active">active event</span>}
          {selectedObject.validationIssues.length > 0 && <span className="emp-badge emp-badge-warning">validation issue</span>}
          {selectedObject.reviewState && <span className="emp-badge">review: {selectedObject.reviewState}</span>}
          {selectedObject.flowRefs.length > 0 && <span className="emp-badge emp-badge-flow">{selectedObject.flowRefs.length} flow refs</span>}
          {selectedObject.state && <span className="emp-badge emp-badge-state" style={{ borderColor: selectedObject.stateColor ?? undefined }}>state: {selectedObject.state}</span>}
          {selectedObject.simulationState && <span className="emp-badge emp-badge-sim">simulation: {selectedObject.simulationState.replace(/_/g, ' ')}</span>}
          <span className="emp-badge">{selectedObject.provenanceRefs.length ? 'source-backed' : 'no source ref'}</span>
          <span className="emp-badge">{selectedObject.packId}</span>
        </div>
        <DetailField label="Description">{selectedObject.description}</DetailField>
        <DetailField label="Ontology path">
          Layer: <strong>{selectedObject.layerLabel}</strong><br />
          Object type: <strong>{selectedObject.objectTypeLabel}</strong><br />
          Abstraction: <strong>{selectedObject.abstractionLabel}</strong><br />
          Owner: <strong>{selectedObject.owner}</strong>
        </DetailField>
        <DetailField label="Trust metadata">
          Lifecycle: <strong>{selectedObject.lifecycleState}</strong><br />
          Review: <strong>{selectedObject.reviewState}</strong><br />
          Confidence: <strong>{formatConfidence(selectedObject.confidence)}</strong><br />
          Provenance refs: <strong>{selectedObject.provenanceRefs.length ? selectedObject.provenanceRefs.join(', ') : 'none'}</strong><br />
          External ref: <strong>{formatExternalRef(selectedObject.externalRef)}</strong>
        </DetailField>
        <DetailField label="Incoming relationships">
          <RelationChips relations={incoming} data={data} direction="incoming" onSelectObject={onSelectObject} empty="None" />
        </DetailField>
        <DetailField label="Outgoing relationships">
          <RelationChips relations={outgoing} data={data} direction="outgoing" onSelectObject={onSelectObject} empty="None" />
        </DetailField>
        <DetailField label="Metadata">
          <MetadataTable metadata={selectedObject.metadata} />
        </DetailField>
        <DetailField label="Analysis">
          Flows: <strong>{selectedObject.flowRefs.length ? selectedObject.flowRefs.join(', ') : 'none'}</strong><br />
          State machine: <strong>{selectedObject.stateMachineRef ?? 'none'}</strong><br />
          State: <strong>{selectedObject.state ?? 'not configured'}</strong><br />
          Simulation: <strong>{selectedObject.simulationState ? selectedObject.simulationState.replace(/_/g, ' ') : 'no scenario linked'}</strong>
        </DetailField>
        <DetailField label="Validation">
          {selectedObject.validationIssues.length ? <IssueList issues={selectedObject.validationIssues} /> : 'No object-level validation issues.'}
        </DetailField>
      </div>
    </aside>
  );
}

function formatConfidence(value?: number | null) {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : 'not recorded';
}

function formatExternalRef(value?: Record<string, unknown> | null) {
  if (!value) return 'none';
  const system = String(value.system ?? 'external');
  const id = String(value.id ?? value.external_id ?? 'unknown');
  return `${system}:${id}`;
}


function DetailField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="emp-field">
      <div className="emp-field-label">{label}</div>
      <div className="emp-field-value">{children}</div>
    </div>
  );
}

function RelationChips({ relations, data, direction, onSelectObject, empty }: { relations: OntologyRelation[]; data: OntologyMapData; direction: 'incoming' | 'outgoing'; onSelectObject: (id: string) => void; empty: string }) {
  if (!relations.length) return <>{empty}</>;
  return (
    <span className="emp-relations">
      {relations.map((relation) => {
        const peerId = direction === 'incoming' ? relation.mapSource : relation.mapTarget;
        const peer = objectById(data, peerId);
        return (
          <button key={`${relationKey(relation.mapSource, relation.mapTarget)}-${relation.type}`} type="button" onClick={() => onSelectObject(peerId)}>
            {relation.label}: {peer ? peer.name : peerId}
            <span className="emp-relation-meta">{relation.reviewState ?? 'unreviewed'}{relation.provenanceRefs.length ? ' · source-backed' : ''}{relation.externalRef ? ` · ${formatExternalRef(relation.externalRef)}` : ''}</span>
          </button>
        );
      })}
    </span>
  );
}

function MetadataTable({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (!entries.length) return <>No metadata fields recorded.</>;
  return (
    <table className="emp-mini-table">
      <tbody>
        {entries.slice(0, 10).map(([key, value]) => (
          <tr key={key}>
            <th>{titleize(key)}</th>
            <td>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function IssueList({ issues }: { issues: Array<Record<string, unknown>> }) {
  return (
    <ul>
      {issues.map((issue, index) => <li key={`${issueText(issue)}-${index}`}>{issueText(issue)}</li>)}
    </ul>
  );
}

function LayersView({ data, onSelectObject }: { data: OntologyMapData; onSelectObject: (id: string) => void }) {
  return (
    <>
      <h2 className="emp-panel-title">Ontology Layers</h2>
      <p className="emp-panel-subtitle">Layers are domain-neutral groupings from the active profile. They can represent strategy, product, delivery, risk, evidence, controls, assets, obligations, or any other domain boundary.</p>
      <div className="emp-group-grid">
        {data.layers.map((layer) => {
          const objects = data.objects.filter((object) => object.layerId === layer.id);
          return (
            <article className="emp-group-card" key={layer.id} style={{ boxShadow: `inset 0 3px 0 ${layerColor(layer.id, layer.label)}` }}>
              <div className="name">{layer.label}</div>
              <div className="emp-pill-row">
                <span className="emp-pill">{objects.length} objects</span>
                <span className="emp-pill">{new Set(objects.map((object) => object.objectType)).size} types</span>
                {layer.lifecycleState && <span className="emp-pill">{layer.lifecycleState}</span>}
              </div>
              {layer.description && <div className="deps">{layer.description}</div>}
              <ObjectButtons objects={objects.slice(0, 5)} onSelectObject={onSelectObject} />
            </article>
          );
        })}
      </div>
    </>
  );
}

function ObjectTypesView({ data, onSelectObject }: { data: OntologyMapData; onSelectObject: (id: string) => void }) {
  const groups = Object.entries(data.objects.reduce<Record<string, OntologyObject[]>>((acc, object) => {
    (acc[object.objectType] ??= []).push(object);
    return acc;
  }, {})).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  return (
    <>
      <h2 className="emp-panel-title">Object Types</h2>
      <p className="emp-panel-subtitle">Object types define the labels available for graph nodes. The same screen can describe product features, regulatory obligations, risks, vendors, documents, policies, or operational assets.</p>
      <div className="emp-group-grid">
        {groups.map(([type, objects]) => {
          const first = objects[0];
          return (
            <article className="emp-group-card" key={type} style={{ boxShadow: `inset 0 3px 0 ${first.objectColor}` }}>
              <div className="name">{first.objectTypeLabel}</div>
              <div className="emp-pill-row">
                <span className="emp-pill">{objects.length} objects</span>
                <span className="emp-pill">{new Set(objects.map((object) => object.layerLabel)).size} layers</span>
                <span className="emp-pill">{first.abstractionLabel}</span>
              </div>
              <ObjectButtons objects={objects.slice(0, 5)} onSelectObject={onSelectObject} />
            </article>
          );
        })}
      </div>
    </>
  );
}

function RelationsView({ data, onSelectObject }: { data: OntologyMapData; onSelectObject: (id: string) => void }) {
  const groups = Object.entries(data.relations.reduce<Record<string, OntologyRelation[]>>((acc, relation) => {
    (acc[relation.type] ??= []).push(relation);
    return acc;
  }, {})).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  return (
    <>
      <h2 className="emp-panel-title">Relationship Types</h2>
      <p className="emp-panel-subtitle">Relationship types define how objects compose, depend on, flow into, validate, own, or trace each other. Direction shown here uses the ontology map direction, not a software-specific roadmap sequence.</p>
      <div className="emp-relation-list">
        {groups.map(([type, relations]) => (
          <article className="emp-flow-card" key={type}>
            <h3>{relations[0].label}</h3>
            <div className="purpose">{titleize(relations[0].family)} family - {relations.length} relationships</div>
            <div className="emp-relation-rows">
              {relations.slice(0, 8).map((relation) => {
                const source = objectById(data, relation.mapSource);
                const target = objectById(data, relation.mapTarget);
                return (
                  <div className="emp-relation-row" key={`${relation.mapSource}-${relation.mapTarget}-${relation.type}`}>
                    <button type="button" onClick={() => source && onSelectObject(source.id)}>{source?.name ?? relation.mapSource}</button>
                    <span>{relation.label}</span>
                    <button type="button" onClick={() => target && onSelectObject(target.id)}>{target?.name ?? relation.mapTarget}</button>
                  </div>
                );
              })}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function QualityView({ data, onSelectObject }: { data: OntologyMapData; onSelectObject: (id: string) => void }) {
  const objectIssues = data.objects.filter((object) => object.validationIssues.length);
  const relationIssues = data.relations.filter((relation) => relation.validationIssues.length || relation.isCandidate);
  return (
    <>
      <h2 className="emp-panel-title">Ontology Quality</h2>
      <p className="emp-panel-subtitle">This view keeps profile drift visible as knowledge grows: candidate labels, validation issues, deprecated objects, and unresolved relationship semantics stay inspectable.</p>
      <div className="emp-quality-grid">
        <QualityMetric label="Pending candidates" value={data.stats.ontologyCandidateCount} body="Labels emitted by extraction that still need approval, mapping, or rejection." />
        <QualityMetric label="Candidate edges" value={data.stats.candidateEdgeCount} body="Relationships that did not resolve to a canonical profile relationship." />
        <QualityMetric label="Validation issues" value={data.stats.validationIssueCount} body="Object and relationship checks raised by the active ontology profile." />
      </div>
      <div className="emp-plan-grid">
        <section className="emp-plan-section">
          <h3>Object Issues</h3>
          {objectIssues.length ? <ObjectButtons objects={objectIssues} onSelectObject={onSelectObject} /> : <p>No object-level validation issues.</p>}
        </section>
        <section className="emp-plan-section">
          <h3>Relationship Issues</h3>
          {relationIssues.length ? (
            <div className="emp-relation-rows">
              {relationIssues.map((relation) => (
                <div className="emp-relation-row" key={`${relation.mapSource}-${relation.mapTarget}-${relation.type}`}>
                  <span>{relation.label}</span>
                  <span>{relation.isCandidate ? 'Candidate' : issueText(relation.validationIssues[0] ?? {})}</span>
                </div>
              ))}
            </div>
          ) : <p>No relationship-level validation issues.</p>}
        </section>
      </div>
    </>
  );
}

function QualityMetric({ label, value, body }: { label: string; value: number; body: string }) {
  return (
    <div className="emp-quality-card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      <div className="hint">{body}</div>
    </div>
  );
}

function ObjectButtons({ objects, onSelectObject }: { objects: OntologyObject[]; onSelectObject: (id: string) => void }) {
  if (!objects.length) return <p className="emp-muted">No objects in this group.</p>;
  return (
    <div className="emp-object-buttons">
      {objects.map((object) => (
        <button key={object.id} type="button" onClick={() => onSelectObject(object.id)}>
          <span>{object.id}</span>
          {object.name}
        </button>
      ))}
    </div>
  );
}

const MAP_PANEL_CSS = `
.emp-example-banner, .emp-filter-banner { margin: 0 0 12px; border: 1px solid rgba(245, 158, 11, 0.45); background: rgba(245, 158, 11, 0.12); color: #92400e; border-radius: 14px; padding: 10px 14px; font-size: 12px; font-weight: 700; }
.emp-filter-banner { border-color: rgba(37, 99, 235, 0.28); background: rgba(37, 99, 235, 0.08); color: #1d4ed8; }
.enterprise-map-shell {
  --emp-bg: #f7f8fa;
  --emp-panel: #ffffff;
  --emp-line: #d9dee7;
  --emp-muted: #728095;
  --emp-ink: #182230;
  --emp-soft: #eef2f7;
  width: 100%;
  min-height: 100%;
  background: var(--emp-bg);
  color: var(--emp-ink);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 12px;
  line-height: 1.4;
}
.enterprise-map-shell * { box-sizing: border-box; }
.enterprise-map-shell button,
.enterprise-map-shell input,
.enterprise-map-shell select { font: inherit; }
.emp-header {
  height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--emp-line);
  background: rgba(255, 255, 255, 0.92);
  position: sticky;
  top: 0;
  z-index: 2;
}
.emp-header h1 {
  margin: 0 0 3px;
  font-size: 18px;
  line-height: 1.05;
  font-weight: 760;
  letter-spacing: 0;
}
.emp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--emp-muted);
  font-size: 11px;
}
.emp-view-toggle {
  display: flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid #cfd6e1;
  background: #f8fafc;
  border-radius: 7px;
  flex: 0 0 auto;
}
.emp-view-toggle button {
  border: 0;
  background: transparent;
  color: #475569;
  border-radius: 5px;
  padding: 7px 10px;
  font-weight: 700;
  cursor: pointer;
}
.emp-view-toggle button.active {
  background: #ffffff;
  color: #172033;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}
.emp-view-toggle button:active,
.emp-relations button:active,
.emp-object-buttons button:active,
.emp-relation-row button:active {
  transform: translateY(1px);
}
.emp-summary-bar {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  border-bottom: 1px solid var(--emp-line);
  background: var(--emp-panel);
}
.emp-summary-card {
  min-height: 72px;
  padding: 11px 13px;
  border-right: 1px solid var(--emp-line);
}
.emp-summary-card .label,
.emp-quality-card .label {
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 10px;
  font-weight: 800;
}
.emp-summary-card .value,
.emp-quality-card .value {
  margin-top: 3px;
  font-size: 18px;
  font-weight: 780;
}
.emp-summary-card .hint,
.emp-quality-card .hint {
  margin-top: 2px;
  color: #6b7789;
  font-size: 11px;
}
.emp-safeguards {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #d8dee9;
  border-radius: 14px;
  background: #f8fafc;
  color: #526071;
  font-size: 12px;
}

.emp-safeguards label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.emp-safeguards select {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 4px 8px;
  background: #ffffff;
}

.emp-safeguards button {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 5px 10px;
  background: #ffffff;
  color: #344054;
}

.emp-safeguards button:disabled { opacity: 0.45; }

.emp-concept-strip {
  display: grid;
  grid-template-columns: 1.1fr 1.25fr 1.2fr 1fr;
  gap: 1px;
  background: var(--emp-line);
  border-bottom: 1px solid var(--emp-line);
}
.emp-concept {
  min-height: 66px;
  background: #f9fbfd;
  display: grid;
  grid-template-columns: 4px 1fr;
  column-gap: 10px;
  padding: 10px 12px 10px 0;
}
.emp-concept-accent { display: block; height: 100%; }
.emp-concept .k {
  grid-column: 2;
  color: #38445a;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}
.emp-concept .v {
  grid-column: 2;
  color: #556174;
  font-size: 11px;
}
.emp-layout {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr) 330px;
  min-height: calc(100dvh - 190px);
}
.emp-filters {
  background: #fbfcfe;
  border-right: 1px solid var(--emp-line);
  padding: 10px 10px 28px;
  overflow: auto;
}
.emp-filters section { margin-bottom: 18px; }
.emp-filters h3 {
  margin: 0 0 7px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 10px;
  font-weight: 850;
}
.emp-filters label {
  display: grid;
  grid-template-columns: 15px 14px minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  min-height: 23px;
  color: #3d4a5f;
  cursor: pointer;
}
.emp-filters input { width: 13px; height: 13px; margin: 0; accent-color: #2563eb; }
.emp-swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  border: 1px solid #94a3b8;
}
.emp-count {
  color: #9aa4b3;
  font-size: 10px;
}
.emp-main {
  min-width: 0;
  position: relative;
  background: #ffffff;
}
.emp-main-view {
  display: none;
  min-height: 100%;
}
.emp-main-view.active { display: block; }
.emp-graph-host {
  width: 100%;
  min-height: 620px;
  overflow: auto;
  position: relative;
}
.emp-graph-svg {
  display: block;
  min-width: 100%;
}
.emp-edge {
  fill: none;
  opacity: 0.48;
  transition: opacity 0.15s, stroke-width 0.15s;
}
.emp-edge.dimmed { opacity: 0.05; }
.emp-edge.focused { opacity: 1; stroke-width: 2.7; }
.emp-lane-bg,
.emp-lane-divider,
.emp-lane-label-bg,
.emp-lane-label { pointer-events: none; }
.emp-lane-divider { stroke: #dbe2eb; stroke-width: 1; stroke-dasharray: 4 5; }
.emp-lane-label-bg { fill: rgba(255, 255, 255, 0.78); stroke: #d8e0eb; }
.emp-lane-label {
  font-size: 11px;
  font-weight: 780;
  fill: #5b6677;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.emp-node {
  cursor: pointer;
  transition: opacity 0.15s, transform 0.15s;
}
.emp-node rect {
  filter: drop-shadow(0 1px 1px rgba(15, 23, 42, 0.08));
}
.emp-node .id {
  font-size: 10px;
  font-weight: 780;
}
.emp-node .name {
  font-size: 12px;
  font-weight: 780;
}
.emp-node .meta {
  font-size: 10px;
}
.emp-node text,
.emp-node circle,
.emp-node title {
  pointer-events: none;
}
.emp-node:focus-visible rect {
  outline: none;
  filter: drop-shadow(0 0 0 rgba(37, 99, 235, 0.46)) drop-shadow(0 2px 5px rgba(37, 99, 235, 0.22));
}
.emp-selection-rail {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--emp-line);
  border-bottom: 1px solid var(--emp-line);
  background: #f8fafc;
}
.emp-selection-rail button {
  border: 1px solid #dbe3ef;
  border-radius: 999px;
  background: #fff;
  color: #172033;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  font-size: 11px;
  font-weight: 760;
}
.emp-selection-rail small { color: #64748b; font-weight: 650; }
.emp-node-hit-overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  pointer-events: auto;
}
.emp-node-overlay-button {
  position: absolute;
  z-index: 2;
  border: 0;
  padding: 0;
  margin: 0;
  background: transparent;
  cursor: pointer;
  pointer-events: auto;
}
.emp-node-overlay-button:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.46);
  outline-offset: -3px;
  border-radius: 7px;
}
.emp-node-hit-target {
  width: 100%;
  height: 100%;
  border: 0;
  padding: 0;
  margin: 0;
  background: transparent;
  cursor: pointer;
}
.emp-node-hit-target:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.46);
  outline-offset: -3px;
}
.emp-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.emp-node.dimmed { opacity: 0.18; }
.emp-node.related { opacity: 0.88; }
.emp-node.candidate-instance rect {
  fill: rgba(245, 158, 11, 0.12);
  filter: drop-shadow(0 0 0 rgba(245, 158, 11, 0.18));
}
.emp-node.pending-candidate-entity rect {
  stroke-dasharray: 7 4;
}
.emp-node.selected rect {
  stroke-width: 2.6;
  filter: drop-shadow(0 2px 5px rgba(37, 99, 235, 0.22));
}
.emp-focus-hint {
  position: absolute;
  right: 16px;
  top: 16px;
  border: 1px solid #cfd6e1;
  background: #ffffff;
  color: #334155;
  border-radius: 7px;
  padding: 7px 10px;
  font-weight: 750;
  opacity: 0;
  pointer-events: none;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
}
.emp-focus-hint.show {
  opacity: 1;
  pointer-events: auto;
}
.emp-legend {
  position: fixed;
  pointer-events: none;
  right: 348px;
  bottom: 16px;
  width: 266px;
  max-height: 310px;
  overflow: auto;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid #d8e0eb;
  border-radius: 7px;
  padding: 10px;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
}
.emp-legend-title {
  margin: 8px 0 5px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-size: 10px;
  font-weight: 850;
}
.emp-legend-title:first-child { margin-top: 0; }
.emp-legend-item {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #485569;
  font-size: 11px;
  margin-bottom: 3px;
}
.emp-detail {
  border-left: 1px solid var(--emp-line);
  background: #fbfcfe;
  padding: 12px;
  overflow: auto;
}
.emp-detail-panel,
.emp-node-card {
  border: 1px solid #d9e0ea;
  border-radius: 8px;
  background: #ffffff;
  padding: 13px;
}
.emp-empty {
  margin: 0;
  color: #8a95a6;
  font-weight: 700;
}
.emp-node-card h2 {
  margin: 0 0 9px;
  font-size: 15px;
  line-height: 1.2;
}
.emp-badge-row,
.emp-pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.emp-badge,
.emp-pill {
  border: 1px solid #d8e0eb;
  background: #f8fafc;
  border-radius: 999px;
  padding: 3px 7px;
  color: #475569;
  font-size: 10px;
  font-weight: 750;
}
.emp-field {
  border-top: 1px solid #e5eaf1;
  padding-top: 10px;
  margin-top: 10px;
}
.emp-field-label {
  color: #64748b;
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 4px;
}
.emp-field-value {
  color: #334155;
  font-size: 12px;
}
.emp-field-value ul {
  margin: 0;
  padding-left: 16px;
}
.emp-relations {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.emp-relation-meta {
  display: block;
  color: #64748b;
  font-size: 10px;
  margin-top: 2px;
}
.emp-relations button,
.emp-object-buttons button,
.emp-relation-row button {
  border: 1px solid #d8e0eb;
  background: #ffffff;
  color: #334155;
  border-radius: 6px;
  padding: 4px 7px;
  cursor: pointer;
  text-align: left;
}
.emp-mini-table {
  width: 100%;
  border-collapse: collapse;
}
.emp-mini-table th,
.emp-mini-table td {
  border-top: 1px solid #edf1f6;
  padding: 5px 0;
  text-align: left;
  vertical-align: top;
  font-size: 11px;
}
.emp-mini-table th {
  color: #64748b;
  width: 38%;
  padding-right: 8px;
}
.emp-panel-title {
  margin: 0;
  padding: 22px 24px 4px;
  font-size: 18px;
  font-weight: 790;
}
.emp-panel-subtitle {
  margin: 0;
  padding: 0 24px 16px;
  color: #617085;
  max-width: 820px;
}
.emp-group-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
  padding: 0 24px 24px;
}
.emp-group-card,
.emp-flow-card,
.emp-plan-section,
.emp-quality-card {
  border: 1px solid #dbe2eb;
  border-radius: 8px;
  background: #ffffff;
  padding: 14px;
}
.emp-group-card .name {
  font-size: 14px;
  font-weight: 790;
  margin-bottom: 8px;
}
.emp-group-card .deps,
.emp-flow-card .purpose,
.emp-muted {
  color: #617085;
  margin-top: 9px;
}
.emp-object-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.emp-object-buttons button span {
  color: #64748b;
  font-weight: 800;
  margin-right: 5px;
}
.emp-relation-list {
  padding: 0 24px 24px;
  display: grid;
  gap: 12px;
}
.emp-flow-card h3,
.emp-plan-section h3 {
  margin: 0 0 5px;
  font-size: 14px;
}
.emp-relation-rows {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}
.emp-relation-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  border-top: 1px solid #edf1f6;
  padding-top: 6px;
}
.emp-relation-row span {
  color: #64748b;
  font-size: 11px;
  font-weight: 750;
}
.emp-plan-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  padding: 0 24px 24px;
}
.emp-quality-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  padding: 0 24px 16px;
}
@media (max-width: 1180px) {
  .emp-layout { grid-template-columns: 190px minmax(0, 1fr); }
  .emp-detail { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--emp-line); }
  .emp-legend { position: static; width: auto; margin: 12px; }
}
@media (max-width: 820px) {
  .emp-header { height: auto; align-items: flex-start; flex-direction: column; }
  .emp-summary-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .emp-safeguards {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #d8dee9;
  border-radius: 14px;
  background: #f8fafc;
  color: #526071;
  font-size: 12px;
}

.emp-safeguards label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.emp-safeguards select {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 4px 8px;
  background: #ffffff;
}

.emp-safeguards button {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 5px 10px;
  background: #ffffff;
  color: #344054;
}

.emp-safeguards button:disabled { opacity: 0.45; }

.emp-concept-strip { grid-template-columns: 1fr; }
  .emp-layout { grid-template-columns: 1fr; }
  .emp-filters { border-right: 0; border-bottom: 1px solid var(--emp-line); max-height: 320px; }
  .emp-plan-grid,
  .emp-quality-grid { grid-template-columns: 1fr; }
}

.emp-analysis-overlay {
  position: absolute;
  right: 14px;
  top: 14px;
  z-index: 3;
  width: min(260px, calc(100% - 28px));
  border: 1px solid #cbd5e1;
  border-radius: 14px;
  background: rgba(255,255,255,0.94);
  box-shadow: 0 12px 30px rgba(15,23,42,0.12);
  padding: 10px;
  display: grid;
  gap: 7px;
}
.emp-analysis-overlay strong { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: #475569; }
.emp-analysis-overlay button { border: 1px solid #e2e8f0; border-radius: 10px; background: #f8fafc; text-align: left; padding: 7px 8px; cursor: pointer; }
.emp-analysis-overlay button.active { border-color: #2563eb; background: #eff6ff; }
.emp-analysis-overlay span { display: block; font-weight: 760; color: #172033; }
.emp-analysis-overlay small { color: #64748b; }
.emp-simulation-rail { display: grid; gap: 12px; }
.emp-provider-contract { border: 1px dashed #94a3b8; border-radius: 12px; background: #f8fafc; padding: 10px 12px; color: #475569; }
.emp-empty.warning { border-color: #f59e0b; background: #fffbeb; color: #92400e; }
.emp-badge-flow { border-color: #0ea5e9; background: #e0f2fe; }
.emp-badge-state { background: #f8fafc; }
.emp-badge-sim { border-color: #8b5cf6; background: #f5f3ff; }
`;

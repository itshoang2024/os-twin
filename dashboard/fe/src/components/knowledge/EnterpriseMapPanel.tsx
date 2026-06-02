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
import { useOntologyProfile, type OntologyProfile } from '@/hooks/use-ontology';
import { ENTERPRISE_MAP_MODULES } from './ontology/enterprise-map';

type ViewName = 'map' | 'layers' | 'objects' | 'relations' | 'quality';
type FilterKey = 'layer' | 'objectType' | 'abstraction' | 'relationshipFamily' | 'pack' | 'lifecycle' | 'owner' | 'quality';
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
  };
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
];

const FILTER_KEYS: FilterKey[] = ['layer', 'objectType', 'abstraction', 'relationshipFamily', 'pack', 'lifecycle', 'owner', 'quality'];
const NODE_W = 178;
const NODE_H = 68;
const H_GAP = 16;
const V_GAP = 12;
const LANE_PAD_TOP = 36;
const LANE_PAD_BOTTOM = 16;
const SVG_PAD_X = 24;
const PAGE_SIZE_OPTIONS = [40, 80, 160] as const;
type DensityMode = 'compact' | 'comfortable' | 'spacious';

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
  },
};

const titleize = (value?: string | null) =>
  String(value || 'unassigned')
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());

const asRecord = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {});
const asIssues = (value: unknown): Array<Record<string, unknown>> => Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') as Array<Record<string, unknown>> : [];
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
  if (asIssues(node.validation_issues).length) return 'needs_review';
  if (node.lifecycle_state === 'deprecated') return 'deprecated';
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

function layerIdFromNode(node: ExplorerNode | EnterpriseMapNode, profile: OntologyProfile | null) {
  const enterprise = node as EnterpriseMapNode;
  const explicit = String(enterprise.layer_id ?? node.layer ?? node.metadata?.layer ?? node.properties?.layer ?? '').trim();
  if (explicit) return explicit;
  const abstraction = String(node.abstraction_level ?? '').trim();
  if (abstraction === 'portfolio') return profile?.layers?.strategy ? 'strategy' : 'portfolio';
  if (abstraction === 'capability' || abstraction === 'feature') return profile?.layers?.product ? 'product' : 'product';
  if (abstraction === 'implementation') return profile?.layers?.delivery ? 'delivery' : 'implementation';
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
      style: String(edge.style ?? relation?.style ?? 'solid'),
      weight: Number(edge.weight ?? relation?.weight ?? 1),
      isCandidate: Boolean(edge.is_candidate),
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
    },
  };
}

function relationshipMapDirection(profile: OntologyProfile | null, relationType: string) {
  const relationship = relationFromProfile(profile, relationType);
  const graphInstruction = profile?.graph_instruction as { relationship_type_defaults?: Record<string, { map_direction?: string }> } | undefined;
  return String(graphInstruction?.relationship_type_defaults?.[relationType]?.map_direction ?? relationship?.map_direction ?? 'forward');
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
      objectTypeLabel: String(concept?.label ?? titleize(node.concept_type ?? node.label)),
      objectColor: String(concept?.color ?? fallbackColor(String(node.concept_type ?? node.label ?? node.id))),
      objectShape: concept?.shape ?? null,
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
      style: String(edge.style ?? relation?.style ?? 'solid'),
      weight: Number(edge.weight ?? relation?.weight ?? 1),
      isCandidate: Boolean(edge.is_candidate),
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
    },
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
    && filters.owner.includes(object.owner)
    && filters.quality.includes(object.qualityState)
  );
}

function relationVisible(relation: OntologyRelation, visibleObjectIds: Set<string>, filters: ActiveFilters) {
  return visibleObjectIds.has(relation.mapSource)
    && visibleObjectIds.has(relation.mapTarget)
    && filters.relationshipFamily.includes(relation.family);
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

export default function EnterpriseMapPanel({ selectedNamespace }: { selectedNamespace: string | null }) {
  const enterpriseMap = useEnterpriseMap(selectedNamespace, 200);
  const explorer = useKnowledgeExplorer(selectedNamespace);
  const { isSeeded, seed } = explorer;
  const { profile } = useOntologyProfile(selectedNamespace);
  const [activeView, setActiveView] = React.useState<ViewName>('map');
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [savedFocusId, setSavedFocusId] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(0);
  const [pageSize, setPageSize] = React.useState<number>(PAGE_SIZE_OPTIONS[0]);
  const [density, setDensity] = React.useState<DensityMode>('comfortable');
  const [hostWidth, setHostWidth] = React.useState(980);
  const graphHostRef = React.useRef<HTMLDivElement | null>(null);
  const svgUid = React.useId().replace(/:/g, '');

  React.useEffect(() => {
    if (!selectedNamespace || isSeeded || enterpriseMap.isLoading || enterpriseMap.map?.nodes.length) return;
    void seed(40);
  }, [enterpriseMap.isLoading, enterpriseMap.map?.nodes.length, isSeeded, seed, selectedNamespace]);

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

  const enterpriseSignature = enterpriseMap.map
    ? [
      enterpriseMap.map.layers.map((layer) => `${layer.id}:${layer.label}:${layer.order}:${layer.count}`).join('|'),
      enterpriseMap.map.nodes.map((node) => `${node.id}:${node.name}:${node.layer_id}:${node.layer_label}:${node.concept_type}:${node.lifecycle_state}:${node.pack_id}`).join('|'),
      enterpriseMap.map.edges.map((edge) => `${edge.source}:${edge.target}:${edge.map_source}:${edge.map_target}:${edge.relationship_type || edge.label}`).join('|'),
      enterpriseMap.map.stats.ontology_candidate_count ?? 0,
    ].join('::')
    : 'no-enterprise-map';
  const graphSignature = [
    explorer.nodes.map((node) => `${node.id}:${node.name}:${node.layer}:${node.concept_type}:${node.lifecycle_state}:${node.pack_id}`).join('|'),
    explorer.edges.map((edge) => `${edge.source}:${edge.target}:${edge.relationship_type || edge.label}`).join('|'),
  ].join('::');
  const profileSignature = profile ? JSON.stringify({ profile_id: profile.profile_id, version: profile.version, concept_types: profile.concept_types, relationship_types: profile.relationship_types, layers: profile.layers }) : 'no-profile';

  const data = React.useMemo(() => {
    if (enterpriseMap.map?.nodes.length) return mapProjectionData(enterpriseMap.map, profile, selectedNamespace);
    if (explorer.nodes.length) return mapExplorerFallback(explorer.nodes, explorer.edges, profile, selectedNamespace);
    return { ...DEFAULT_MAP_DATA, ...profileMeta(null, profile, selectedNamespace) };
    // Hook adapters can return new identities while carrying identical graph content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enterpriseSignature, graphSignature, profileSignature, selectedNamespace]);

  const [filters, setFilters] = React.useState<ActiveFilters>(() => buildInitialFilters(data));

  React.useEffect(() => {
    setFilters(buildInitialFilters(data));
    setSelectedId(savedFocusId && data.objects.some((object) => object.id === savedFocusId) ? savedFocusId : null);
    setPage(0);
  }, [data, savedFocusId]);

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
  const connected = React.useMemo(() => connectedObjectIds(data, selectedId), [data, selectedId]);
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
    setSelectedId(id);
    setSavedFocusId(id);
    setActiveView('map');
  }, []);

  return (
    <div className="enterprise-map-shell" data-testid="enterprise-map-panel" data-modules={ENTERPRISE_MAP_MODULES.join(',')}>
      <style>{MAP_PANEL_CSS}</style>
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
              onClick={() => setActiveView(button.id)}
            >
              {button.label}
            </button>
          ))}
        </nav>
      </header>

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

      <div className="emp-layout">
        <FiltersSidebar data={data} filters={filters} onToggle={toggleFilter} />

        <main className="emp-main">
          <section className={`emp-main-view ${activeView === 'map' ? 'active' : ''}`}>
            <div className="emp-graph-host" ref={graphHostRef}>
              <GraphSvg
                data={data}
                layout={layout}
                graphEdges={graphEdges}
                selectedId={selectedId}
                connected={connected}
                svgUid={svgUid}
                onSelectObject={(id) => { setSelectedId(id); if (id) setSavedFocusId(id); }}
              />
            </div>
            <button
              className={`emp-focus-hint ${selectedId ? 'show' : ''}`}
              type="button"
              onClick={() => setSelectedId(null)}
            >
              Clear focus
            </button>
            <Legend data={data} />
          </section>

          <section className={`emp-main-view ${activeView === 'layers' ? 'active' : ''}`}>
            <LayersView data={data} onSelectObject={selectObject} />
          </section>
          <section className={`emp-main-view ${activeView === 'objects' ? 'active' : ''}`}>
            <ObjectTypesView data={data} onSelectObject={selectObject} />
          </section>
          <section className={`emp-main-view ${activeView === 'relations' ? 'active' : ''}`}>
            <RelationsView data={data} onSelectObject={selectObject} />
          </section>
          <section className={`emp-main-view ${activeView === 'quality' ? 'active' : ''}`}>
            <QualityView data={data} onSelectObject={selectObject} />
          </section>
        </main>

        <DetailSidebar data={data} selectedObject={selectedObject} onSelectObject={selectObject} />
      </div>
    </div>
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
        let cls = 'emp-node';
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
            role="button"
            aria-label={`Select ${object.name}`}
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onSelectObject(object.id);
              }
            }}
            onClick={(event) => {
              event.stopPropagation();
              onSelectObject(object.id);
            }}
          >
            <rect
              x={pos.x}
              y={pos.y}
              width={NODE_W}
              height={NODE_H}
              rx={object.objectShape === 'rectangle' ? 2 : object.objectShape === 'diamond' ? 0 : 7}
              fill={`${object.objectColor}18`}
              stroke={object.objectColor}
              strokeWidth="1.6"
              strokeDasharray={object.validationIssues.length ? '5 4' : undefined}
            />
            <text x={pos.x + 9} y={pos.y + 17} className="id" fill="#354052">{truncate(object.id, 18)}</text>
            <text x={pos.x + 9} y={pos.y + 35} className="name" fill="#182230">{truncate(object.name, 24)}</text>
            <text x={pos.x + 9} y={pos.y + 54} className="meta" fill="#526071">{truncate(object.objectTypeLabel, 17)} - {truncate(object.lifecycleState, 10)}</text>
            <circle cx={pos.x + NODE_W - 13} cy={pos.y + 15} r="5" fill={object.objectColor} />
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
          <span className="emp-badge">{selectedObject.lifecycleState}</span>
          <span className="emp-badge">{selectedObject.packId}</span>
        </div>
        <DetailField label="Description">{selectedObject.description}</DetailField>
        <DetailField label="Ontology path">
          Layer: <strong>{selectedObject.layerLabel}</strong><br />
          Object type: <strong>{selectedObject.objectTypeLabel}</strong><br />
          Abstraction: <strong>{selectedObject.abstractionLabel}</strong><br />
          Owner: <strong>{selectedObject.owner}</strong>
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
        <DetailField label="Validation">
          {selectedObject.validationIssues.length ? <IssueList issues={selectedObject.validationIssues} /> : 'No object-level validation issues.'}
        </DetailField>
      </div>
    </aside>
  );
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
.emp-node.dimmed { opacity: 0.18; }
.emp-node.related { opacity: 0.88; }
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
`;

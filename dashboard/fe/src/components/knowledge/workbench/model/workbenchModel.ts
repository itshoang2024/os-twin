export type WorkbenchSelection = { kind: string; id: string; title?: string; source?: string; properties?: Record<string, unknown> } | null;
export type RenderMode = 'compact' | 'extended';
export type LayoutMode = 'auto' | 'hierarchy' | 'grid' | 'row' | 'column' | 'circular' | 'radial' | 'cluster' | 'cartesian' | 'layered';
export type ColorBy = 'fixed' | 'object_type' | 'property';

export interface WorkbenchNode {
  id: string;
  label: string;
  type: string;
  kind?: string;
  source?: string;
  subtitle?: string;
  description?: string;
  icon?: string;
  color?: string;
  layerId?: string;
  groupId?: string;
  properties?: Record<string, unknown>;
  badges?: string[];
  sources?: string[];
}

export interface WorkbenchEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  type?: string;
  family?: string;
  weight?: number;
  style?: 'solid' | 'dashed' | 'dotted' | 'bold' | string;
  properties?: Record<string, unknown>;
}

export interface WorkbenchFacetBucket {
  id: string;
  label: string;
  count: number;
  color?: string;
}

export interface WorkbenchFacet {
  id: string;
  label: string;
  buckets: WorkbenchFacetBucket[];
  kind?: 'term' | 'numeric' | 'temporal';
  binning?: 'categorical' | 'numeric' | 'temporal';
}

export interface WorkbenchLayer {
  id: string;
  label: string;
  color?: string;
  order?: number;
  count?: number;
}

export interface WorkbenchModel {
  id: string;
  title: string;
  subtitle?: string;
  nodes: WorkbenchNode[];
  edges: WorkbenchEdge[];
  selection?: WorkbenchSelection;
  facets?: WorkbenchFacet[];
  layers?: WorkbenchLayer[];
  metadata?: Record<string, unknown>;
}

export type OntologyLayer = 'source' | 'semantic' | 'governance' | 'activation';
export type Cardinality = 'one_to_one' | 'one_to_many' | 'many_to_one' | 'many_to_many';
export type RelationshipDirection = 'forward' | 'reverse' | 'bidirectional';

export interface MetadataField {
  id: string;
  label: string;
  type: 'text' | 'number' | 'boolean' | 'date' | 'enum';
  required?: boolean;
  source?: string;
}

export interface SourceMapping {
  id: string;
  source: string;
  selector: string;
  evidenceRefs: string[];
}

export interface OntologyConceptType {
  id: string;
  label: string;
  description: string;
  layer: OntologyLayer;
  abstractionLevel: string;
  lifecycle: 'draft' | 'active' | 'deprecated';
  metadataFields: MetadataField[];
  sourceMappings: SourceMapping[];
}

export interface OntologyRelationshipType {
  id: string;
  label: string;
  description: string;
  family: string;
  allowedSourceTypes: string[];
  allowedTargetTypes: string[];
  cardinality: Cardinality;
  mapDirection: RelationshipDirection;
  inverse?: string;
  style: 'solid' | 'dashed' | 'dotted';
  weight: number;
  sourceMappings: SourceMapping[];
}

export interface GraphInstruction {
  conceptTypeDefaults: Record<string, { color: string; shape: 'circle' | 'rounded' | 'diamond' }>;
  relationshipTypeDefaults: Record<string, { color: string; style: OntologyRelationshipType['style']; weight: number }>;
}

export interface OntologyProfile {
  id: string;
  namespace: string;
  label: string;
  status: 'draft' | 'published';
  conceptTypes: Record<string, OntologyConceptType>;
  relationshipTypes: Record<string, OntologyRelationshipType>;
  graphInstruction: GraphInstruction;
  candidates: OntologyCandidate[];
  updatedAt: string;
}

export interface OntologyCandidate {
  id: string;
  label: string;
  kind: 'object' | 'relationship';
  evidenceRefs: string[];
  source: string;
}

export interface ValidationIssue {
  id: string;
  severity: 'error' | 'warning';
  message: string;
  path: string;
  focus: 'identity' | 'endpoint' | 'cardinality' | 'source' | 'governance';
}

export type WorkbenchSelection =
  | { kind: 'concept'; id: string; focus?: ValidationIssue['focus'] }
  | { kind: 'relationship'; id: string; focus?: ValidationIssue['focus'] }
  | { kind: 'candidate'; id: string; focus?: ValidationIssue['focus'] }
  | { kind: 'governance'; focus?: ValidationIssue['focus'] };

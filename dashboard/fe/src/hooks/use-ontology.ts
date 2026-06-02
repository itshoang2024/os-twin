import useSWR from 'swr';
import { apiPost, apiPut } from '@/lib/api-client';

const KNOWLEDGE_BASE = '/knowledge';

export type OntologySubject = 'profile' | 'node' | 'edge' | 'pack';

export interface OntologyValidationIssue {
  severity: 'info' | 'warning' | 'error' | string;
  code: string;
  path: string;
  message: string;
  suggested_fix?: string;
  subject?: string;
  metadata?: Record<string, unknown>;
}

export interface OntologyMetadataField {
  id: string;
  label: string;
  field_type?: string;
  allowed_values?: string[];
  description?: string;
  required?: boolean;
  [key: string]: unknown;
}

export interface OntologyAbstractionLevel {
  id: string;
  label: string;
  order?: number;
  description?: string;
  [key: string]: unknown;
}

export interface OntologyLayer {
  id: string;
  label: string;
  order?: number;
  description?: string;
  [key: string]: unknown;
}

export interface OntologyConceptType {
  id: string;
  label: string;
  abstraction_level?: string;
  layer?: string;
  default_layer?: string;
  description?: string;
  metadata_schema?: Record<string, OntologyMetadataField | string | unknown>;
  metadata_fields?: string[];
  color?: string;
  shape?: string;
  [key: string]: unknown;
}

export type OntologyMapDirection = 'forward' | 'reversed' | 'bidirectional' | 'none' | string;

export interface OntologyRelationshipType {
  id: string;
  label: string;
  family?: string;
  inverse?: string;
  allowed_source_types?: string[];
  allowed_target_types?: string[];
  weight?: number;
  style?: string;
  display_style?: string;
  map_direction?: OntologyMapDirection;
  description?: string;
  [key: string]: unknown;
}

export interface GraphInstructionDefaultView {
  id: string;
  label: string;
  lane_dimension?: string;
  filters?: Record<string, string[]>;
  description?: string;
}

export interface ConceptGraphInstruction {
  concept_type: string;
  default_layer?: string | null;
  label_template?: string;
  color?: string | null;
  shape?: string | null;
  group?: string | null;
  [key: string]: unknown;
}

export interface RelationshipGraphInstruction {
  relationship_type: string;
  map_direction?: OntologyMapDirection;
  label_template?: string;
  inverse_label_template?: string | null;
  color?: string | null;
  dash?: string | null;
  weight?: number | null;
  group?: string | null;
  [key: string]: unknown;
}

export interface GraphInstruction {
  schema_version?: number;
  default_lane_dimension?: string;
  layout_hints?: Record<string, unknown>;
  default_views?: GraphInstructionDefaultView[];
  concept_type_defaults?: Record<string, ConceptGraphInstruction>;
  relationship_type_defaults?: Record<string, RelationshipGraphInstruction>;
  validation_rules?: string[];
  examples?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface OntologyProfile {
  profile_id: string;
  namespace: string;
  version: string;
  status?: string;
  concept_types: Record<string, OntologyConceptType>;
  relationship_types: Record<string, OntologyRelationshipType>;
  aliases: Record<string, string>;
  concept_aliases?: Record<string, string>;
  layers: Record<string, OntologyLayer>;
  abstraction_levels: Record<string, OntologyAbstractionLevel>;
  metadata_fields: Record<string, OntologyMetadataField>;
  validation_rules?: Array<Record<string, unknown>>;
  graph_instruction?: GraphInstruction;
  [key: string]: unknown;
}

export interface OntologyProfileResponse {
  namespace: string;
  profile: OntologyProfile | null;
  profile_exists: boolean;
  default_suggested: boolean;
  default_profile: OntologyProfile | null;
  validation_issues: OntologyValidationIssue[];
}

export interface OntologyValidateResponse {
  namespace: string;
  subject: OntologySubject | string;
  valid: boolean;
  issues: OntologyValidationIssue[];
}

export interface OntologyProfileDiffResponse {
  namespace: string;
  base_version?: string | null;
  target_version?: string | null;
  history_id?: string | null;
  diff: Record<string, unknown>;
  migration_issues: Array<Record<string, unknown>>;
  would_mutate: boolean;
}

export interface OntologyProfileHistoryRecord {
  id: string;
  namespace: string;
  actor: string;
  timestamp: string;
  reason: string;
  previous_version?: string | null;
  new_version: string;
  changed_paths: string[];
  diff: Record<string, unknown>;
  migration_issues: Array<Record<string, unknown>>;
  validation_override?: Record<string, unknown> | null;
  migration_entries: Array<Record<string, unknown>>;
  profile?: OntologyProfile | null;
}

export interface OntologyProfileHistoryListResponse {
  namespace: string;
  history: OntologyProfileHistoryRecord[];
}

export interface OntologySummaryResponse {
  namespace: string;
  profile_exists: boolean;
  profile_id?: string | null;
  version?: string | null;
  concept_type_count: number;
  relation_type_count: number;
  alias_count: number;
  candidate_count: number;
  validation_issue_count: number;
  validation_issues: OntologyValidationIssue[];
}

export interface DomainPackManifest {
  pack_id: string;
  name: string;
  version: string;
  compatible_profile_versions?: string[];
  concept_types?: Record<string, OntologyConceptType | Record<string, unknown>>;
  relationship_types?: Record<string, OntologyRelationshipType | Record<string, unknown>>;
  layers?: Record<string, OntologyLayer | Record<string, unknown>>;
  abstraction_levels?: Record<string, OntologyAbstractionLevel | Record<string, unknown>>;
  aliases?: Record<string, string>;
  metadata_fields?: Record<string, OntologyMetadataField | Record<string, unknown>>;
  validation_rules?: Array<Record<string, unknown>>;
  graph_instruction?: GraphInstruction;
  fixtures?: Array<Record<string, unknown>>;
  migration_notes?: string[];
}

export interface DomainPackListResponse {
  packs: DomainPackManifest[];
}

export interface DomainPackInstalledResponse {
  namespace: string;
  schema_version: number;
  installed_packs: Record<string, unknown>;
}

export interface OntologyCandidate {
  id: string;
  namespace: string;
  candidate_type: string;
  source: string;
  original_label: string;
  normalized_label?: string;
  suggested_canonical?: string | null;
  confidence: number;
  sample_text: string;
  status: string;
  source_hash?: string;
  created_at: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  metadata?: Record<string, unknown>;
}

export interface OntologyCandidateListResponse {
  namespace: string;
  candidates: OntologyCandidate[];
}

export interface OntologyCandidateActionRequest {
  canonical_id?: string | null;
  payload?: Record<string, unknown>;
  reason?: string;
}

export interface OntologyCandidateBulkAction extends OntologyCandidateActionRequest {
  candidate_id: string;
  action: 'approve' | 'map' | 'reject';
}

export function getEditableProfile(response: OntologyProfileResponse | undefined): OntologyProfile | null {
  return response?.profile ?? response?.default_profile ?? null;
}

export function useOntologyProfile(namespace: string | null) {
  const key = namespace ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/profile` : null;
  const { data, error, isLoading, mutate } = useSWR<OntologyProfileResponse>(key, { revalidateOnFocus: false });

  const saveProfile = async (profile: OntologyProfile, options: { reason?: string; validation_override?: Record<string, unknown> | null } = {}): Promise<OntologyProfileResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    const requestBody: { profile: OntologyProfile; reason?: string; validation_override?: Record<string, unknown> | null } = { profile };
    if (options.reason !== undefined) requestBody.reason = options.reason;
    if (options.validation_override !== undefined) requestBody.validation_override = options.validation_override;
    const saved = await apiPut<OntologyProfileResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/profile`,
      requestBody,
    );
    await mutate(saved, false);
    return saved;
  };

  const resetDefault = async (): Promise<OntologyProfileResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    const reset = await apiPost<{ namespace: string; profile: OntologyProfile; replaced_existing: boolean }>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/reset-default`,
    );
    const response: OntologyProfileResponse = {
      namespace: reset.namespace,
      profile: reset.profile,
      profile_exists: true,
      default_suggested: false,
      default_profile: null,
      validation_issues: [],
    };
    await mutate(response, false);
    return response;
  };

  return {
    data,
    profile: getEditableProfile(data),
    profileExists: Boolean(data?.profile_exists),
    defaultSuggested: Boolean(data?.default_suggested),
    validationIssues: data?.validation_issues ?? [],
    isLoading,
    error: error ? String(error) : null,
    refresh: mutate,
    saveProfile,
    resetDefault,
  };
}

export function useOntologyValidation(namespace: string | null) {
  const validateProfile = async (profile: OntologyProfile): Promise<OntologyValidateResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    return apiPost<OntologyValidateResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/validate`,
      { subject: 'profile', profile },
    );
  };

  return { validateProfile };
}

export function useOntologyHistory(namespace: string | null) {
  const key = namespace ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/profile/history` : null;
  const { data, error, isLoading, mutate } = useSWR<OntologyProfileHistoryListResponse>(key, { revalidateOnFocus: false });

  const diffProfile = async (targetProfile: OntologyProfile, baseProfile?: OntologyProfile): Promise<OntologyProfileDiffResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    return apiPost<OntologyProfileDiffResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/profile/diff`,
      { target_profile: targetProfile, base_profile: baseProfile },
    );
  };

  const previewRollback = async (versionOrId: string): Promise<OntologyProfileDiffResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    return apiPost<OntologyProfileDiffResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/profile/diff`,
      { target_version: versionOrId },
    );
  };

  return {
    history: data?.history ?? [],
    isLoading,
    error: error ? String(error) : null,
    refresh: mutate,
    diffProfile,
    previewRollback,
  };
}

export function useOntologySummary(namespace: string | null) {
  const { data, error, isLoading, mutate } = useSWR<OntologySummaryResponse>(
    namespace ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/summary` : null,
    { revalidateOnFocus: false },
  );

  return {
    summary: data ?? null,
    isLoading,
    error: error ? String(error) : null,
    refresh: mutate,
  };
}

export function useOntologyPacks(namespace: string | null) {
  const available = useSWR<DomainPackListResponse>(`${KNOWLEDGE_BASE}/ontology/packs`, { revalidateOnFocus: false });
  const installed = useSWR<DomainPackInstalledResponse>(
    namespace ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/packs` : null,
    { revalidateOnFocus: false },
  );

  const installPack = async (packId: string) => {
    if (!namespace) throw new Error('Namespace is required');
    const result = await apiPost(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/packs/install`,
      { pack_id: packId },
    );
    await installed.mutate();
    return result;
  };

  const uninstallPack = async (packId: string) => {
    if (!namespace) throw new Error('Namespace is required');
    const result = await apiPost(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/packs/uninstall`,
      { pack_id: packId },
    );
    await installed.mutate();
    return result;
  };

  return {
    packs: available.data?.packs ?? [],
    installed: installed.data ?? null,
    isLoading: available.isLoading || installed.isLoading,
    error: available.error || installed.error ? String(available.error || installed.error) : null,
    installPack,
    uninstallPack,
  };
}

export function useOntologyCandidates(namespace: string | null, status = 'pending') {
  const key = namespace
    ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/candidates${status ? `?status=${encodeURIComponent(status)}` : ''}`
    : null;
  const { data, error, isLoading, mutate } = useSWR<OntologyCandidateListResponse>(key, { revalidateOnFocus: false });

  const approveCandidate = async (candidateId: string, request: OntologyCandidateActionRequest = {}) => {
    if (!namespace) throw new Error('Namespace is required');
    const candidate = await apiPost<OntologyCandidate>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/candidates/${encodeURIComponent(candidateId)}/approve`,
      request,
    );
    await mutate();
    return candidate;
  };

  const mapCandidate = async (candidateId: string, canonicalId: string, request: OntologyCandidateActionRequest = {}) => {
    if (!namespace) throw new Error('Namespace is required');
    const candidate = await apiPost<OntologyCandidate>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/candidates/${encodeURIComponent(candidateId)}/map`,
      { ...request, canonical_id: canonicalId },
    );
    await mutate();
    return candidate;
  };

  const rejectCandidate = async (candidateId: string, reason = '') => {
    if (!namespace) throw new Error('Namespace is required');
    const candidate = await apiPost<OntologyCandidate>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/candidates/${encodeURIComponent(candidateId)}/reject`,
      { reason },
    );
    await mutate();
    return candidate;
  };

  const bulkUpdateCandidates = async (actions: OntologyCandidateBulkAction[]) => {
    if (!namespace) throw new Error('Namespace is required');
    const result = await apiPost<OntologyCandidateListResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/candidates/bulk`,
      { actions },
    );
    await mutate();
    return result;
  };

  return {
    candidates: data?.candidates ?? [],
    isLoading,
    error: error ? String(error) : null,
    refresh: mutate,
    approveCandidate,
    mapCandidate,
    rejectCandidate,
    bulkUpdateCandidates,
  };
}

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

export type OntologyRelationshipFamily = 'composition' | 'dependency' | 'flow' | 'semantic' | 'ownership' | 'classification' | 'causality' | 'temporal' | 'validation' | 'traceability' | 'assurance' | 'synchronization';
export type OntologyRelationshipCardinality = 'one_to_one' | 'one_to_many' | 'many_to_one' | 'many_to_many';

export interface OntologySourceMapping {
  source_id: string;
  source_type?: 'document' | 'database' | 'api' | 'file' | 'event' | 'manual' | 'derived' | 'other' | string;
  source_label?: string;
  field_path?: string;
  transform?: string;
  confidence?: number | null;
  notes?: string;
  [key: string]: unknown;
}

export interface OntologyMetadataField {
  id: string;
  label: string;
  field_type?: string;
  allowed_values?: string[];
  description?: string;
  required?: boolean;
  source_mappings?: OntologySourceMapping[];
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
  source_mappings?: OntologySourceMapping[];
  [key: string]: unknown;
}

export type OntologyMapDirection = 'forward' | 'reversed' | 'bidirectional' | 'none' | string;

export interface OntologyRelationshipType {
  id: string;
  label: string;
  family?: OntologyRelationshipFamily | string;
  inverse?: string;
  allowed_source_types?: string[];
  allowed_target_types?: string[];
  weight?: number;
  style?: string;
  display_style?: string;
  map_direction?: OntologyMapDirection;
  cardinality?: OntologyRelationshipCardinality | null;
  description?: string;
  source_mappings?: OntologySourceMapping[];
  [key: string]: unknown;
}

export interface GraphInstructionDefaultView {
  id: string;
  label: string;
  lane_dimension?: string;
  filters?: Record<string, string[]>;
  excluded_filters?: Record<string, string[]>;
  color_by?: string;
  style_property?: string;
  selected_node_ids?: string[];
  search_around?: {
    direction?: string;
    relationship_family?: string;
    depth?: number;
  };
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

export interface OntologyUnit {
  id?: string | null;
  namespace: string;
  active_profile_id?: string | null;
  name?: string;
  purpose?: string;
  domain?: string;
  expected_users?: string[];
  source_material?: string[];
  governance_mode?: string;
  lifecycle?: string;
  installed_packs?: string[];
  auto_confirm_threshold?: number;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface OntologyUnitResponse {
  namespace: string;
  unit: OntologyUnit | null;
  unit_exists: boolean;
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
  dependencies?: string[];
}

export interface DomainPackListResponse {
  packs: DomainPackManifest[];
}

export interface DomainPackValidateResponse {
  namespace: string;
  pack_id: string;
  valid: boolean;
  issues: OntologyValidationIssue[];
  profile?: OntologyProfile | null;
  manifest?: DomainPackManifest | null;
}

export interface DomainPackInstalledResponse {
  namespace: string;
  schema_version: number;
  installed_packs: Record<string, { pack_id?: string; name?: string; version?: string; status?: string; additions?: Record<string, string[]>; installed_at?: string; disabled_at?: string | null } | unknown>;
}

export interface EvidenceArtifact {
  id: string;
  source_type: string;
  source_uri?: string | null;
  title?: string | null;
  checksum?: string;
  read_coverage?: string;
  source_state?: string;
  limitations?: string[];
  metadata?: Record<string, unknown>;
}

export interface EvidenceAnchor {
  id: string;
  artifact_id: string;
  locator?: Record<string, string | number | null | undefined>;
  excerpt?: string;
  extraction_method?: string;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface ProvenanceLinkDetail {
  provenance_link?: Record<string, unknown> | null;
  anchor?: EvidenceAnchor | null;
  artifact?: EvidenceArtifact | null;
}

export interface OntologyFactSubject {
  kind: 'node' | 'candidate' | 'label' | string;
  id: string;
  label?: string;
  concept_type?: string | null;
}

export interface OntologyFactSuggestedMapping {
  relationship_type?: string | null;
  source_id?: string | null;
  target_id?: string | null;
  source_kind?: string;
  target_kind?: string;
  direction?: string;
  confidence?: number | null;
}

export interface OntologyFact {
  id: string;
  namespace: string;
  statement: string;
  subjects: OntologyFactSubject[];
  subject_ids: string[];
  confidence: number;
  review_state: 'draft' | 'assistive' | 'reviewed' | 'approved' | 'rejected' | string;
  source: 'extraction' | 'assistant' | 'manual' | string;
  evidence_refs: string[];
  provenance_refs: string[];
  suggested_mapping?: OntologyFactSuggestedMapping | null;
  source_hash?: string;
  promoted_edge_id?: string | null;
  created_at: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  metadata?: Record<string, unknown>;
}

export interface OntologyFactListResponse {
  namespace: string;
  facts: OntologyFact[];
}

export interface OntologyFactCreateRequest {
  statement: string;
  subjects?: OntologyFactSubject[];
  confidence?: number;
  source?: 'extraction' | 'assistant' | 'manual';
  evidence_refs?: string[];
  provenance_refs?: string[];
  suggested_mapping?: OntologyFactSuggestedMapping | null;
  source_hash?: string;
  metadata?: Record<string, unknown>;
}

export interface OntologyFactPromoteRequest {
  relationship_type?: string | null;
  source_id?: string | null;
  target_id?: string | null;
}

export interface ObservationEvent {
  id: string;
  namespace: string;
  event_type: string;
  subject_type: string;
  subject_id: string;
  occurred_at: string;
  actor?: string | null;
  value?: string | number | boolean | null;
  evidence_refs: string[];
  metadata?: Record<string, unknown>;
}

export interface ObservationEventListResponse {
  namespace: string;
  events: ObservationEvent[];
}

export interface TimeSeriesPoint {
  timestamp: string;
  value: number;
  evidence_refs?: string[];
  metadata?: Record<string, unknown>;
}

export interface TimeSeries {
  id: string;
  namespace: string;
  subject_id: string;
  metric_id: string;
  unit: string;
  points: TimeSeriesPoint[];
  evidence_refs: string[];
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TimeSeriesListResponse {
  namespace: string;
  series: TimeSeries[];
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
  proposed_payload?: Record<string, unknown>;
  source_evidence_ref?: string | null;
  source_evidence?: ProvenanceLinkDetail | null;
  created_at: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  metadata?: Record<string, unknown>;
}

export interface OntologyCandidateListResponse {
  namespace: string;
  candidates: OntologyCandidate[];
}

export interface OntologyAssistantMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface OntologyAssistantRequest {
  message: string;
  profile: OntologyProfile;
  selected?: Record<string, unknown> | null;
  context?: Record<string, unknown> | null;
  history?: OntologyAssistantMessage[];
}

export interface OntologyAssistantResponse {
  namespace: string;
  conversation_id: string;
  text: string;
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
  return response?.profile ?? null;
}


export function useOntologyUnit(namespace: string | null) {
  const key = namespace ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/unit` : null;
  const { data, error, isLoading, mutate } = useSWR<OntologyUnitResponse>(key, { revalidateOnFocus: false });

  const saveUnit = async (unit: Partial<OntologyUnit>): Promise<OntologyUnitResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    const saved = await apiPut<OntologyUnitResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/unit`,
      { unit: { ...unit, namespace } },
    );
    await mutate(saved, false);
    return saved;
  };

  return {
    data,
    unit: data?.unit ?? null,
    unitExists: Boolean(data?.unit_exists),
    isLoading,
    error: error ? String(error) : null,
    refresh: mutate,
    saveUnit,
  };
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
    suggestedProfile: data?.profile_exists ? null : data?.default_profile ?? null,
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

  const validatePack = async (packId: string): Promise<DomainPackValidateResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    return apiPost<DomainPackValidateResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/packs/validate`,
      { pack_id: packId },
    );
  };

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
    validatePack,
    installPack,
    uninstallPack,
  };
}

export function useOntologyFacts(namespace: string | null, reviewState = '') {
  const key = namespace
    ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/facts${reviewState ? `?review_state=${encodeURIComponent(reviewState)}` : ''}`
    : null;
  const { data, error, isLoading, mutate } = useSWR<OntologyFactListResponse>(key, { revalidateOnFocus: false });

  const createFact = async (request: OntologyFactCreateRequest): Promise<OntologyFact> => {
    if (!namespace) throw new Error('Namespace is required');
    const fact = await apiPost<OntologyFact>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/facts`,
      request,
    );
    await mutate();
    return fact;
  };

  const reviewFact = async (factId: string, review_state: OntologyFact['review_state'], metadata: Record<string, unknown> = {}): Promise<OntologyFact> => {
    if (!namespace) throw new Error('Namespace is required');
    const fact = await apiPost<OntologyFact>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/facts/${encodeURIComponent(factId)}/review`,
      { review_state, metadata },
    );
    await mutate();
    return fact;
  };

  const promoteFactToEdge = async (factId: string, request: OntologyFactPromoteRequest = {}): Promise<Record<string, unknown>> => {
    if (!namespace) throw new Error('Namespace is required');
    const result = await apiPost<Record<string, unknown>>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/facts/${encodeURIComponent(factId)}/promote-edge`,
      request,
    );
    await mutate();
    return result;
  };

  const raiseRelationshipCandidate = async (factId: string, relationshipLabel: string): Promise<Record<string, unknown>> => {
    if (!namespace) throw new Error('Namespace is required');
    const result = await apiPost<Record<string, unknown>>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/facts/${encodeURIComponent(factId)}/relationship-candidate`,
      { relationship_label: relationshipLabel },
    );
    await mutate();
    return result;
  };

  return {
    facts: data?.facts ?? [],
    isLoading,
    error: error ? String(error) : null,
    refresh: mutate,
    createFact,
    reviewFact,
    promoteFactToEdge,
    raiseRelationshipCandidate,
  };
}

export function useOntologyObservation(namespace: string | null, subjectId?: string | null) {
  const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : '';
  const eventsKey = namespace ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/observation/events${query}` : null;
  const seriesKey = namespace ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/observation/series${query}` : null;
  const events = useSWR<ObservationEventListResponse>(eventsKey, { revalidateOnFocus: false });
  const series = useSWR<TimeSeriesListResponse>(seriesKey, { revalidateOnFocus: false });

  return {
    events: events.data?.events ?? [],
    series: series.data?.series ?? [],
    isLoading: events.isLoading || series.isLoading,
    error: events.error || series.error ? String(events.error || series.error) : null,
    refresh: async () => { await events.mutate(); await series.mutate(); },
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

export function useOntologyAssistant(namespace: string | null) {
  const askAssistant = async (request: OntologyAssistantRequest): Promise<OntologyAssistantResponse> => {
    if (!namespace) throw new Error('Namespace is required');
    return apiPost<OntologyAssistantResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/assistant`,
      request,
    );
  };

  return { askAssistant };
}

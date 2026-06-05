'use client';

import React from 'react';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import EnterpriseMapPanel from '@/components/knowledge/EnterpriseMapPanel';
import type { EnterpriseMapProjectionData } from '@/hooks/use-knowledge-explorer';
import { useOntologyAssistant, useOntologyCandidates, useOntologyHistory, useOntologyPacks, useOntologyProfile, useOntologySummary, useOntologyUnit, useOntologyValidation } from '@/hooks/use-ontology';
import type { DomainPackManifest, OntologyCandidate, OntologyProfile, OntologyProfileHistoryRecord, OntologyUnit, OntologyValidationIssue } from '@/hooks/use-ontology';
import AliasManager from './AliasManager';
import CandidateReview from './CandidateReview';
import ConceptTypeStudio from './ConceptTypeStudio';
import GraphInstructionStudio from './GraphInstructionStudio';
import ProfileSummary from './ProfileSummary';
import RelationshipStudio from './RelationshipStudio';
import { cloneProfile, IssueList, labelFor, validationErrorCount } from './ontology-ui';
import { applyOntologyProposalToDraft, parseOntologyAssistantResponse, proposalSectionCounts, type OntologyAssistantProposal, type ProposalStatus } from './assistant-proposals';
import { GraphCanvas, SelectionInspector, WorkbenchShell, specLensAdapter } from '@/components/knowledge/workbench';

type LensMode = 'spec' | 'map';
type SelectionKind = 'namespace' | 'concept' | 'relationship' | 'layer' | 'metadata' | 'candidate' | 'instance' | 'fact' | 'source';
type WorkbenchSelection = { kind: SelectionKind | string; id: string; title: string; concept_type?: string; instance_id?: string; source?: 'profile' | 'candidate' | 'live' | 'example' | 'graph_instruction' | string } | null;
type LeftDockTab = 'search' | 'sources' | 'candidates' | 'object_types' | 'properties' | 'relationships' | 'validation' | 'templates' | 'histogram';
type RightDockTab = 'object' | 'assistant' | 'model' | 'governance' | 'simulation';

const leftTabs: Array<{ id: LeftDockTab; label: string; icon: string }> = [
  { id: 'search', label: 'Search', icon: 'search' },
  { id: 'sources', label: 'Sources', icon: 'database' },
  { id: 'candidates', label: 'Candidates', icon: 'diamond' },
  { id: 'object_types', label: 'Object Types', icon: 'category' },
  { id: 'properties', label: 'Properties', icon: 'view_list' },
  { id: 'relationships', label: 'Relationships', icon: 'hub' },
  { id: 'validation', label: 'Validation', icon: 'rule_settings' },
  { id: 'templates', label: 'Templates', icon: 'dashboard_customize' },
  { id: 'histogram', label: 'Histogram', icon: 'monitoring' },
];

const rightTabs: Array<{ id: RightDockTab; label: string; icon: string }> = [
  { id: 'object', label: 'SelectionInspector', icon: 'view_in_ar' },
  { id: 'assistant', label: 'AI co-builder', icon: 'smart_toy' },
  { id: 'model', label: 'Model Config', icon: 'tune' },
  { id: 'governance', label: 'Governance', icon: 'verified' },
  { id: 'simulation', label: 'Simulation', icon: 'timeline' },
];


type SearchDirection = 'outgoing' | 'incoming' | 'bidirectional';
type GroupDimension = 'layer' | 'abstraction_level' | 'concept_type' | 'pack' | 'owner' | 'lifecycle' | 'quality_state' | 'event_state';
type LayoutMode = 'layered' | 'force' | 'hierarchical' | 'dependency-flow' | 'timeline' | 'table' | 'series';
type ColorDimension = 'type' | 'property' | 'layer' | 'abstraction_level' | 'candidate' | 'validation_state' | 'event_state' | 'fallback';
type HistogramAction = 'filter_to' | 'filter_out';

type VisualDraftState = {
  searchDirection: SearchDirection;
  relationshipFamily: string;
  depth: number;
  groupBy: GroupDimension;
  layout: LayoutMode;
  colorBy: ColorDimension;
  styleProperty: string;
  fallbackColor: string;
  selectedNodeIds: string[];
  filters: Record<string, string[]>;
  excludedFilters: Record<string, string[]>;
};

type HistogramRow = {
  dimension: string;
  key: string;
  label: string;
  count: number;
  binning?: string;
  selectedCount: number;
};

type PackLifecycleRecord = { pack_id?: string; name?: string; version?: string; status?: string; additions?: Record<string, string[]>; installed_at?: string; disabled_at?: string | null };
type PackPreview = { packId: string; action: 'install' | 'uninstall'; valid?: boolean; issues?: OntologyValidationIssue[]; affectedCounts: Record<string, number>; removed?: Record<string, string[]>; retained?: Record<string, string[]>; orphaned?: Record<string, string[]>; migrationNotes: string[] };
type PackOwnership = Record<string, { packId: string; name?: string; status?: string }>;
type DraftHistoryEntry = { profile: OntologyProfile; label: string; timestamp: number };
type OntologyUnitDraft = Pick<OntologyUnit, 'name' | 'purpose' | 'domain' | 'expected_users' | 'source_material' | 'governance_mode'>;

const groupDimensions: Array<{ value: GroupDimension; label: string }> = [
  { value: 'layer', label: 'Layer' },
  { value: 'abstraction_level', label: 'Abstraction level' },
  { value: 'concept_type', label: 'Concept type' },
  { value: 'pack', label: 'Pack' },
  { value: 'owner', label: 'Owner' },
  { value: 'lifecycle', label: 'Lifecycle' },
  { value: 'quality_state', label: 'Quality state' },
  { value: 'event_state', label: 'Event state' },
];

const layoutModes: Array<{ value: LayoutMode; label: string; available: boolean; reason?: string }> = [
  { value: 'layered', label: 'Layered', available: true },
  { value: 'force', label: 'Force', available: true },
  { value: 'hierarchical', label: 'Hierarchical', available: true },
  { value: 'dependency-flow', label: 'Dependency flow', available: true },
  { value: 'timeline', label: 'Timeline', available: false, reason: 'Needs Observation time events' },
  { value: 'table', label: 'Table', available: true },
  { value: 'series', label: 'Series', available: false, reason: 'Needs series projection' },
];

const colorDimensions: Array<{ value: ColorDimension; label: string }> = [
  { value: 'type', label: 'Object type' },
  { value: 'property', label: 'Property' },
  { value: 'layer', label: 'Layer' },
  { value: 'abstraction_level', label: 'Abstraction level' },
  { value: 'candidate', label: 'Candidate state' },
  { value: 'validation_state', label: 'Validation state' },
  { value: 'event_state', label: 'Event state' },
  { value: 'fallback', label: 'Fallback' },
];

const initialVisualDraft: VisualDraftState = {
  searchDirection: 'bidirectional',
  relationshipFamily: 'all',
  depth: 1,
  groupBy: 'layer',
  layout: 'layered',
  colorBy: 'type',
  styleProperty: '',
  fallbackColor: '#64748b',
  selectedNodeIds: [],
  filters: {},
  excludedFilters: {},
};

function relationshipFamilies(profile: OntologyProfile) {
  return ['all', ...Array.from(new Set(Object.values(profile.relationship_types ?? {}).map((item) => String(item.family ?? 'semantic')))).sort()];
}

function visualStateFromProfile(profile: OntologyProfile | null): VisualDraftState {
  const instruction = profile?.graph_instruction ?? {};
  const views = Array.isArray(instruction.default_views) ? instruction.default_views : [];
  const saved = views.find((view) => view.id === 'ontology_visual_analysis') ?? views[0] ?? {};
  const layoutHints = (instruction.layout_hints ?? {}) as Record<string, unknown>;
  return {
    ...initialVisualDraft,
    groupBy: String(saved.lane_dimension ?? instruction.default_lane_dimension ?? initialVisualDraft.groupBy) as GroupDimension,
    layout: String(layoutHints.mode ?? initialVisualDraft.layout) as LayoutMode,
    colorBy: String(saved.color_by ?? layoutHints.color_by ?? initialVisualDraft.colorBy) as ColorDimension,
    styleProperty: String(saved.style_property ?? ''),
    fallbackColor: String(layoutHints.fallback_color ?? initialVisualDraft.fallbackColor),
    selectedNodeIds: Array.isArray(saved.selected_node_ids) ? saved.selected_node_ids.map(String) : [],
    filters: saved.filters ?? {},
  };
}

function cloneForDraft<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function blankProfileId(namespace: string) {
  const normalized = namespace.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return `${normalized || 'namespace'}_ontology_unit`;
}

function makeBlankOntologyProfile(namespace: string): OntologyProfile {
  return {
    profile_id: blankProfileId(namespace),
    namespace,
    version: '0.1.0',
    status: 'draft',
    concept_types: {},
    relationship_types: {},
    aliases: {},
    concept_aliases: {},
    layers: {},
    abstraction_levels: {},
    metadata_fields: {},
    validation_rules: [],
    graph_instruction: {
      schema_version: 1,
      default_lane_dimension: 'layer',
      layout_hints: { mode: 'layered', color_by: 'type' },
      default_views: [{
        id: 'ontology_unit_draft',
        label: 'Ontology Unit Draft',
        lane_dimension: 'layer',
        description: 'Initial blank View-plane draft for a user-created ontology unit.',
      }],
    },
  };
}


function makeProfileFromPackTemplate(namespace: string, pack: DomainPackManifest): OntologyProfile {
  const base = makeBlankOntologyProfile(namespace);
  return {
    ...base,
    profile_id: `${blankProfileId(namespace)}_${pack.pack_id.replace(/[^a-z0-9]+/gi, '_')}`,
    concept_types: cloneForDraft(pack.concept_types ?? {}) as OntologyProfile['concept_types'],
    relationship_types: cloneForDraft(pack.relationship_types ?? {}) as OntologyProfile['relationship_types'],
    aliases: cloneForDraft(pack.aliases ?? {}),
    layers: cloneForDraft(pack.layers ?? {}) as OntologyProfile['layers'],
    abstraction_levels: cloneForDraft(pack.abstraction_levels ?? {}) as OntologyProfile['abstraction_levels'],
    metadata_fields: cloneForDraft(pack.metadata_fields ?? {}) as OntologyProfile['metadata_fields'],
    validation_rules: cloneForDraft(pack.validation_rules ?? []),
    graph_instruction: cloneForDraft(pack.graph_instruction ?? base.graph_instruction),
  };
}

function evidenceLabel(candidate: OntologyCandidate) {
  return candidate.source_evidence_ref
    ?? candidate.source_evidence?.anchor?.id
    ?? candidate.source_evidence?.artifact?.id
    ?? 'no evidence ref';
}

function candidateAssistantContext(candidate: OntologyCandidate) {
  return {
    id: candidate.id,
    type: candidate.candidate_type,
    label: candidate.original_label,
    normalized_label: candidate.normalized_label ?? null,
    suggested_canonical: candidate.suggested_canonical ?? null,
    confidence: candidate.confidence,
    sample_text: candidate.sample_text,
    proposed_payload: candidate.proposed_payload ?? null,
    source_evidence_ref: candidate.source_evidence_ref ?? null,
    evidence_ref: candidate.source_evidence_ref ?? null,
    source_evidence: candidate.source_evidence ?? null,
  };
}

function candidateEvidenceRefs(candidates: OntologyCandidate[], selectedCandidate?: OntologyCandidate | null) {
  const source = selectedCandidate ? [selectedCandidate] : candidates.slice(0, 5);
  return Array.from(new Set(source.map((candidate) => candidate.source_evidence_ref).filter((ref): ref is string => Boolean(ref))));
}

function templateCounts(profile: OntologyProfile | null | undefined) {
  return {
    objects: Object.keys(profile?.concept_types ?? {}).length,
    relationships: Object.keys(profile?.relationship_types ?? {}).length,
    layers: Object.keys(profile?.layers ?? {}).length,
    fields: Object.keys(profile?.metadata_fields ?? {}).length,
  };
}

function OntologyUnitLauncher({
  namespace,
  suggestedProfile,
  unitDraft,
  onUnitDraftChange,
  candidates,
  packs,
  onBuildFromKnowledge,
  onAskAssistant,
  onPreviewSeed,
  onPreviewPack,
  onStartBlank,
}: {
  namespace: string;
  suggestedProfile: OntologyProfile | null;
  unitDraft: OntologyUnitDraft;
  onUnitDraftChange: (next: OntologyUnitDraft) => void;
  candidates: OntologyCandidate[];
  packs: DomainPackManifest[];
  onBuildFromKnowledge: () => void;
  onAskAssistant: () => void;
  onPreviewSeed: () => void;
  onPreviewPack: (pack: DomainPackManifest) => void;
  onStartBlank: () => void;
}) {
  const counts = templateCounts(suggestedProfile);
  const updateField = (field: keyof OntologyUnitDraft, value: string) => {
    if (field === 'expected_users' || field === 'source_material') {
      onUnitDraftChange({ ...unitDraft, [field]: value.split(',').map((item) => item.trim()).filter(Boolean) });
      return;
    }
    onUnitDraftChange({ ...unitDraft, [field]: value });
  };
  return (
    <div className="h-full overflow-auto p-6" style={{ background: 'var(--color-background)' }} data-testid="ontology-workbench-shell">
      <section className="mx-auto max-w-6xl" data-testid="ontology-unit-launcher">
        <div className="border-b pb-5" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="material-symbols-outlined text-[24px]" style={{ color: 'var(--color-primary)' }} aria-hidden="true">hub</span>
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">{namespace}</span>
            <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: 'rgba(245,158,11,0.14)', color: '#b45309' }}>No active ontology unit</span>
          </div>
          <h2 className="mt-4 text-2xl font-semibold tracking-normal" style={{ color: 'var(--color-text-main)' }}>Create Ontology Unit</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6" style={{ color: 'var(--color-text-muted)' }}>
            Start with the domain problem, sources, and object model. The default seed is available as a template, but it will not become the visible graph until you choose it.
          </p>
        </div>

        <div className="mt-5 rounded-xl border p-4" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }} data-testid="ontology-unit-identity-form">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Unit identity</h3>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Persist governance metadata first. This does not publish a profile or render a default graph.</p>
            </div>
            <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>{unitDraft.governance_mode || 'manual'}</span>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Name<input value={unitDraft.name ?? ''} onChange={(event) => updateField('name', event.target.value)} placeholder="Audit Legal Process Ontology" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label>
            <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Domain<input value={unitDraft.domain ?? ''} onChange={(event) => updateField('domain', event.target.value)} placeholder="legal operations, airline audit, build software" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label>
            <label className="text-xs md:col-span-2" style={{ color: 'var(--color-text-muted)' }}>Purpose<textarea value={unitDraft.purpose ?? ''} onChange={(event) => updateField('purpose', event.target.value)} placeholder="Explain the business or governance problem this ontology unit represents." className="mt-1 min-h-[70px] w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label>
            <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Expected users<input value={(unitDraft.expected_users ?? []).join(', ')} onChange={(event) => updateField('expected_users', event.target.value)} placeholder="auditors, product managers" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label>
            <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Source material<input value={(unitDraft.source_material ?? []).join(', ')} onChange={(event) => updateField('source_material', event.target.value)} placeholder="policies, tickets, interviews" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label>
            <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Governance mode<select value={unitDraft.governance_mode ?? 'manual'} onChange={(event) => updateField('governance_mode', event.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}><option value="manual">Manual review</option><option value="assisted">Assisted proposal review</option><option value="strict">Strict governed approval</option></select></label>
          </div>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
          <div className="grid gap-3 md:grid-cols-2">
            <button type="button" onClick={onBuildFromKnowledge} className="rounded-xl border p-4 text-left transition active:translate-y-[1px]" style={{ borderColor: 'var(--color-primary)', background: 'var(--color-surface)', color: 'var(--color-text-main)' }}>
              <span className="material-symbols-outlined text-[22px]" style={{ color: 'var(--color-primary)' }} aria-hidden="true">travel_explore</span>
              <strong className="mt-3 block text-sm">Build from imported knowledge</strong>
              <span className="mt-2 block text-xs leading-5" style={{ color: 'var(--color-text-muted)' }}>{candidates.length} pending candidate(s) can seed object types, links, properties, and validation rules.</span>
              <span className="mt-3 block rounded-lg border px-3 py-2 text-[11px] leading-5" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }} data-testid="imported-knowledge-summary">
                {candidates.length ? candidates.slice(0, 3).map((candidate) => `${candidate.original_label} → ${evidenceLabel(candidate)}`).join(' · ') : 'No pending candidates yet; the assistant will start from namespace metadata.'}
              </span>
            </button>
            <button type="button" onClick={onAskAssistant} className="rounded-xl border p-4 text-left transition active:translate-y-[1px]" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)', color: 'var(--color-text-main)' }}>
              <span className="material-symbols-outlined text-[22px]" aria-hidden="true">smart_toy</span>
              <strong className="mt-3 block text-sm">Ask AI to draft</strong>
              <span className="mt-2 block text-xs leading-5" style={{ color: 'var(--color-text-muted)' }}>Open a blank governed draft and ask for a small proposal grounded in candidates and evidence refs.</span>
            </button>
            <button type="button" onClick={onPreviewSeed} disabled={!suggestedProfile} className="rounded-xl border p-4 text-left transition active:translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-50" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)', color: 'var(--color-text-main)' }}>
              <span className="material-symbols-outlined text-[22px]" aria-hidden="true">account_tree</span>
              <strong className="mt-3 block text-sm">Preview seed template</strong>
              <span className="mt-2 block text-xs leading-5" style={{ color: 'var(--color-text-muted)' }}>{suggestedProfile ? `${counts.objects} object type(s), ${counts.relationships} relationship(s), ${counts.layers} layer(s), ${counts.fields} field(s).` : 'No seed template was returned for this namespace.'}</span>
            </button>
            <button type="button" onClick={onStartBlank} className="rounded-xl border p-4 text-left transition active:translate-y-[1px]" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)', color: 'var(--color-text-main)' }}>
              <span className="material-symbols-outlined text-[22px]" aria-hidden="true">edit_square</span>
              <strong className="mt-3 block text-sm">Start blank</strong>
              <span className="mt-2 block text-xs leading-5" style={{ color: 'var(--color-text-muted)' }}>Create an empty local draft, then add the first object type, relationship, and property yourself.</span>
            </button>
          </div>

          <aside className="rounded-xl border p-4" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Template gallery</h3>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Template preview — not installed yet.</p>
            <div className="mt-3 grid gap-2" data-testid="ontology-template-gallery">
              <button type="button" onClick={onStartBlank} className="rounded-lg border p-3 text-left text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>
                <strong>Blank profile</strong>
                <span className="mt-1 block" style={{ color: 'var(--color-text-muted)' }}>Template preview — not installed yet. Opens an empty canvas with Add your first object type.</span>
              </button>
              {packs.map((pack) => {
                const packCounts = { objects: Object.keys(pack.concept_types ?? {}).length, relationships: Object.keys(pack.relationship_types ?? {}).length, layers: Object.keys(pack.layers ?? {}).length, fields: Object.keys(pack.metadata_fields ?? {}).length };
                return (
                  <button key={pack.pack_id} type="button" onClick={() => onPreviewPack(pack)} className="rounded-lg border p-3 text-left text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>
                    <strong>{pack.name}</strong>
                    <span className="mt-1 block" style={{ color: 'var(--color-text-muted)' }}>Template preview — not installed yet. {packCounts.objects} object type(s), {packCounts.relationships} relationship(s), {packCounts.layers} layer(s), {packCounts.fields} field(s).</span>
                  </button>
                );
              })}
            </div>
            <div className="mt-4 border-t pt-4" style={{ borderColor: 'var(--color-border)' }}>
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Cold-start contract</h3>
            <div className="mt-3 space-y-3 text-xs leading-5" style={{ color: 'var(--color-text-muted)' }}>
              <p><strong style={{ color: 'var(--color-text-main)' }}>Unit:</strong> name the business/domain problem first.</p>
              <p><strong style={{ color: 'var(--color-text-main)' }}>Spec:</strong> define object types, relationships, properties, and constraints.</p>
              <p><strong style={{ color: 'var(--color-text-main)' }}>Graph:</strong> inspect instances only after data or examples exist.</p>
              <p><strong style={{ color: 'var(--color-text-main)' }}>Governance:</strong> validate, preview diff, then save the active profile.</p>
            </div>
            <div className="mt-4 border-t pt-4" style={{ borderColor: 'var(--color-border)' }}>
              <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Available vocabulary bundles</div>
              <div className="flex flex-wrap gap-1">
                {packs.slice(0, 4).map((pack) => <span key={pack.pack_id} className="rounded-full border px-2 py-0.5 text-[11px]" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>{pack.name}</span>)}
                {!packs.length && <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No packs available yet.</span>}
              </div>
            </div>
            <button type="button" onClick={onPreviewSeed} disabled={!suggestedProfile} className="mt-4 w-full rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>
              Preview seed template locally
            </button>
            </div>
          </aside>
        </div>
      </section>
    </div>
  );
}

function setFilterRecord(record: Record<string, string[]>, dimension: string, value: string) {
  const next = { ...record };
  const existing = new Set(next[dimension] ?? []);
  existing.add(value);
  next[dimension] = Array.from(existing);
  return next;
}

function packAffectedCounts(pack: DomainPackManifest): Record<string, number> {
  return {
    concepts: Object.keys(pack.concept_types ?? {}).length,
    relationships: Object.keys(pack.relationship_types ?? {}).length,
    layers: Object.keys(pack.layers ?? {}).length,
    fields: Object.keys(pack.metadata_fields ?? {}).length,
    rules: (pack.validation_rules ?? []).length,
    fixtures: (pack.fixtures ?? []).length,
  };
}

function asPackLifecycleRecord(value: unknown): PackLifecycleRecord {
  return value && typeof value === 'object' ? value as PackLifecycleRecord : {};
}

function packOwnershipFromInstalled(installed: Record<string, unknown>): PackOwnership {
  const ownership: PackOwnership = {};
  Object.entries(installed ?? {}).forEach(([packId, raw]) => {
    const record = asPackLifecycleRecord(raw);
    if (record.status && record.status !== 'installed') return;
    Object.entries(record.additions ?? {}).forEach(([section, ids]) => {
      if (!Array.isArray(ids)) return;
      ids.forEach((id) => { ownership[`${section}:${id}`] = { packId, name: record.name, status: record.status ?? 'installed' }; });
    });
  });
  return ownership;
}
function diffArray(diff: Record<string, unknown> | null, bucket: 'added' | 'removed' | 'changed', section: string): string[] {
  const raw = diff?.[bucket];
  if (!raw || typeof raw !== 'object') return [];
  const value = (raw as Record<string, unknown>)[section];
  return Array.isArray(value) ? value.map(String) : [];
}

function diffOverlayItems(diff: Record<string, unknown> | null) {
  const sections = [
    { section: 'concept_types', label: 'Nodes' },
    { section: 'relationship_types', label: 'Edges' },
    { section: 'metadata_fields', label: 'Properties' },
    { section: 'validation_rules', label: 'Validation' },
    { section: 'graph_instruction', label: 'View styles' },
  ];
  return sections.flatMap(({ section, label }) => (['added', 'removed', 'changed'] as const).flatMap((bucket) =>
    diffArray(diff, bucket, section).map((id) => ({ key: `${bucket}:${section}:${id}`, bucket, label, id })),
  ));
}

function GraphDiffOverlay({ diff }: { diff: Record<string, unknown> | null }) {
  const items = diffOverlayItems(diff);
  if (!items.length) return <div className="mt-3 rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>Graph overlay: no node, edge, property, validation, or view-style changes detected.</div>;
  const styles: Record<string, string> = { added: 'border-emerald-400 bg-emerald-500/10 text-emerald-700', removed: 'border-rose-400 bg-rose-500/10 text-rose-700 line-through', changed: 'border-amber-400 bg-amber-500/10 text-amber-700' };
  return (
    <div className="mt-3 rounded-xl border p-3" style={{ borderColor: 'var(--color-border)' }} data-testid="ontology-graph-diff-overlay">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}><span className="material-symbols-outlined text-[16px]" aria-hidden="true">hub</span>Graph impact overlay</div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => <span key={item.key} className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${styles[item.bucket]}`}>{item.bucket.toUpperCase()} · {item.label}: {item.id}</span>)}
      </div>
    </div>
  );
}

function HistoryPanel({ history }: { history: OntologyProfileHistoryRecord[] }) {
  if (!history.length) return <section className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)', color: 'var(--color-text-muted)' }}><h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Schema history</h3><p className="mt-2">No profile_history records yet. Operational observation_events stay separate.</p></section>;
  return (
    <section className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }} data-testid="ontology-history-panel">
      <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Schema history</h3>
      <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Governance audit only: profile_history records schema/view changes; observation_events remain operational telemetry.</p>
      <div className="mt-3 space-y-2">
        {history.slice(0, 6).map((record) => {
          const paths = record.changed_paths ?? [];
          const sections = Array.from(new Set(paths.map((path) => path.split('.')[0] || 'profile')));
          const impact = diffOverlayItems(record.diff ?? {}).length;
          return (
            <article key={record.id} className="rounded-lg border p-3" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>
              <div className="flex flex-wrap items-center justify-between gap-2"><strong>{record.reason || 'Governed profile update'}</strong><span className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>v{record.previous_version ?? '∅'} → v{record.new_version}</span></div>
              <div className="mt-1 text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{record.actor} · {new Date(record.timestamp).toLocaleString()} · {impact} visual impact item(s)</div>
              <div className="mt-2 flex flex-wrap gap-1">{sections.map((section) => <span key={section} className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">{section}</span>)}</div>
            </article>
          );
        })}
      </div>
    </section>
  );
}



function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function objectValues(value: unknown): Record<string, unknown>[] {
  return value && typeof value === 'object' ? Object.values(value as Record<string, unknown>).filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item))) : [];
}

function packUninstallPreview(packId: string, installed: Record<string, unknown>, packs: DomainPackManifest[]): PackPreview {
  const record = asPackLifecycleRecord(installed?.[packId]);
  const additions = record.additions ?? {};
  const remainingInstalled = Object.entries(installed ?? {}).filter(([id, raw]) => id !== packId && asPackLifecycleRecord(raw).status === 'installed');
  const retained: Record<string, string[]> = {};
  const removed: Record<string, string[]> = {};
  const orphaned: Record<string, string[]> = {};
  Object.entries(additions).forEach(([section, ids]) => {
    const values = Array.isArray(ids) ? ids.map(String) : [];
    values.forEach((id) => {
      const keptByState = remainingInstalled.some(([, raw]) => (asPackLifecycleRecord(raw).additions?.[section] ?? []).includes(id));
      const keptByManifest = remainingInstalled.some(([otherPackId]) => {
        const manifest = packs.find((item) => item.pack_id === otherPackId);
        if (!manifest) return false;
        if (section === 'concept_types') return objectValues(manifest.relationship_types ?? {}).some((rel) => [...stringArray(rel.allowed_source_types), ...stringArray(rel.allowed_target_types)].includes(id));
        if (section === 'relationship_types') return Object.values(manifest.aliases ?? {}).map(String).includes(id);
        return false;
      });
      const target = keptByState || keptByManifest ? retained : removed;
      target[section] = [...(target[section] ?? []), id];
    });
  });
  Object.entries(removed).forEach(([section, ids]) => {
    if (section !== 'concept_types' && section !== 'relationship_types') return;
    ids.forEach((id) => {
      const dependentFixtures = remainingInstalled.flatMap(([otherPackId]) => packs.find((item) => item.pack_id === otherPackId)?.fixtures ?? []).filter((fixture) => JSON.stringify(fixture).includes(id));
      if (dependentFixtures.length) orphaned[section] = [...(orphaned[section] ?? []), id];
    });
  });
  const affectedCounts = Object.fromEntries(Object.entries(additions).map(([section, ids]) => [section, Array.isArray(ids) ? ids.length : 0]));
  return { packId, action: 'uninstall', affectedCounts, removed, retained, orphaned, migrationNotes: [`Disabling ${packId} previews removed, retained, and orphaned pack-owned elements before persistence.`] };
}

function histogramRows(profile: OntologyProfile, candidates: OntologyCandidate[], state: VisualDraftState): HistogramRow[] {
  const rows: HistogramRow[] = [];
  const add = (dimension: string, key: string, label: string, count: number, binning?: string) => {
    const selected = (state.filters[dimension] ?? []).includes(key) ? count : 0;
    rows.push({ dimension, key, label, count, binning, selectedCount: selected });
  };
  Object.entries(profile.concept_types ?? {}).forEach(([id, concept]) => add('concept_type', id, labelFor(id, concept?.label), 1));
  Object.entries(profile.layers ?? {}).forEach(([id, layer]) => {
    const count = Object.values(profile.concept_types ?? {}).filter((concept) => String(concept.default_layer ?? concept.layer ?? 'unassigned') === id).length;
    add('layer', id, labelFor(id, layer?.label), count, 'concept default layer');
  });
  Object.entries(profile.abstraction_levels ?? {}).forEach(([id, level]) => {
    const count = Object.values(profile.concept_types ?? {}).filter((concept) => String(concept.abstraction_level ?? 'unassigned') === id).length;
    add('abstraction_level', id, labelFor(id, level?.label), count, 'concept abstraction');
  });
  const lifecycleCounts = new Map<string, number>();
  Object.values(profile.concept_types ?? {}).forEach((concept) => lifecycleCounts.set(String(concept.lifecycle_state ?? 'unspecified'), (lifecycleCounts.get(String(concept.lifecycle_state ?? 'unspecified')) ?? 0) + 1));
  lifecycleCounts.forEach((count, key) => add('lifecycle', key, labelFor(key), count));
  if (candidates.length) add('candidate', 'pending', 'Pending candidates', candidates.length, 'candidate status');
  add('validation_state', 'issues', 'Validation issues', 0, 'profile validation');
  add('event_state', 'unavailable', 'No event state', 0, 'legacy safe fallback');
  return rows.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function applyVisualStateToProfile(profile: OntologyProfile, state: VisualDraftState): OntologyProfile {
  const next = cloneForDraft(profile);
  const instruction = { ...(next.graph_instruction ?? {}) };
  const defaultViews = Array.isArray(instruction.default_views) ? [...instruction.default_views] : [];
  const viewPayload = {
    id: 'ontology_visual_analysis',
    label: 'Ontology visual analysis',
    lane_dimension: state.groupBy,
    description: 'Saved View-plane controls for search around, grouping, layout, filters, and styling.',
    filters: state.filters,
    excluded_filters: state.excludedFilters,
    color_by: state.colorBy,
    style_property: state.styleProperty,
    selected_node_ids: state.selectedNodeIds,
    search_around: { direction: state.searchDirection, relationship_family: state.relationshipFamily, depth: state.depth },
  };
  const existingIndex = defaultViews.findIndex((view) => view.id === viewPayload.id);
  if (existingIndex >= 0) defaultViews[existingIndex] = { ...defaultViews[existingIndex], ...viewPayload };
  else defaultViews.unshift(viewPayload);
  instruction.default_lane_dimension = state.groupBy;
  instruction.default_views = defaultViews;
  instruction.layout_hints = { ...(instruction.layout_hints ?? {}), mode: state.layout, color_by: state.colorBy, fallback_color: state.fallbackColor };
  instruction.concept_type_defaults = { ...(instruction.concept_type_defaults ?? {}) };
  Object.keys(next.concept_types ?? {}).forEach((id) => {
    const previous = instruction.concept_type_defaults?.[id] ?? { concept_type: id };
    instruction.concept_type_defaults![id] = { ...previous, concept_type: id, group: state.groupBy === 'concept_type' ? id : String(next.concept_types[id]?.default_layer ?? next.concept_types[id]?.abstraction_level ?? state.groupBy), color: previous.color ?? next.concept_types[id]?.color ?? state.fallbackColor };
  });
  instruction.relationship_type_defaults = { ...(instruction.relationship_type_defaults ?? {}) };
  Object.keys(next.relationship_types ?? {}).forEach((id) => {
    const previous = instruction.relationship_type_defaults?.[id] ?? { relationship_type: id };
    instruction.relationship_type_defaults![id] = { ...previous, relationship_type: id, group: next.relationship_types[id]?.family ?? 'semantic' };
  });
  next.graph_instruction = instruction;
  return next;
}

function normalizeCandidateId(value: string | null | undefined): string {
  const normalized = String(value || 'candidate_item').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return normalized || 'candidate_item';
}

function stageCandidateApproval(profile: OntologyProfile, candidate: OntologyCandidate): { profile: OntologyProfile; path: string } | null {
  const next = cloneForDraft(profile);
  const canonical = normalizeCandidateId(candidate.suggested_canonical || candidate.normalized_label || candidate.original_label);
  const payload = { ...(candidate.proposed_payload ?? {}), ...(candidate.metadata ?? {}) };
  const label = String(payload.label || candidate.original_label || canonical);
  if (candidate.candidate_type === 'concept_type') {
    next.concept_types = { ...(next.concept_types ?? {}), [canonical]: { id: canonical, label, abstraction_level: String(payload.abstraction_level || Object.keys(next.abstraction_levels ?? {})[0] || 'implementation'), default_layer: String(payload.default_layer || payload.layer || Object.keys(next.layers ?? {})[0] || 'default'), description: String(payload.description || `Staged from candidate ${candidate.id}.`), color: String(payload.color || '#64748b'), shape: String(payload.shape || 'rounded_rectangle') } };
    return { profile: next, path: `concept_types.${canonical}` };
  }
  if (candidate.candidate_type === 'relationship_type' || candidate.candidate_type === 'alias') {
    next.relationship_types = { ...(next.relationship_types ?? {}), [canonical]: { id: canonical, label, family: String(payload.family || 'semantic'), description: String(payload.description || `Staged from candidate ${candidate.id}.`), allowed_source_types: Array.isArray(payload.allowed_source_types) ? payload.allowed_source_types.map(String) : [], allowed_target_types: Array.isArray(payload.allowed_target_types) ? payload.allowed_target_types.map(String) : [], weight: Number(payload.weight ?? 0.5), style: String(payload.style || 'solid'), is_directed: payload.is_directed !== false } };
    return { profile: next, path: `relationship_types.${canonical}` };
  }
  if (candidate.candidate_type === 'metadata_field') {
    next.metadata_fields = { ...(next.metadata_fields ?? {}), [canonical]: { id: canonical, label, field_type: String(payload.field_type || 'string'), description: String(payload.description || `Staged from candidate ${candidate.id}.`), required: Boolean(payload.required ?? false), allowed_values: Array.isArray(payload.allowed_values) ? payload.allowed_values.map(String) : [] } };
    return { profile: next, path: `metadata_fields.${canonical}` };
  }
  if (candidate.candidate_type === 'validation_rule') {
    const rules = Array.isArray(next.validation_rules) ? [...next.validation_rules] : [];
    rules.push({ id: canonical, label, rule_type: String(payload.rule_type || 'required_metadata'), severity: String(payload.severity || 'warning'), message: String(payload.message || `Validate ${label}`), enabled: payload.enabled !== false, params: typeof payload.params === 'object' && payload.params !== null ? payload.params : {} });
    next.validation_rules = rules;
    return { profile: next, path: `validation_rules.${canonical}` };
  }
  return null;
}

function stageCandidateMap(profile: OntologyProfile, candidate: OntologyCandidate, canonicalId: string): { profile: OntologyProfile; path: string } | null {
  const next = cloneForDraft(profile);
  const alias = normalizeCandidateId(candidate.normalized_label || candidate.original_label);
  const canonical = normalizeCandidateId(canonicalId);
  if (candidate.candidate_type === 'concept_type' || canonical in (next.concept_types ?? {})) {
    next.concept_aliases = { ...(next.concept_aliases ?? {}), [alias]: canonical };
    return { profile: next, path: `concept_aliases.${alias}` };
  }
  if (candidate.candidate_type === 'relationship_type' || candidate.candidate_type === 'alias' || canonical in (next.relationship_types ?? {})) {
    next.aliases = { ...(next.aliases ?? {}), [alias]: canonical };
    return { profile: next, path: `aliases.${alias}` };
  }
  return null;
}

function selectedSource(profile: OntologyProfile, selection: WorkbenchSelection) {
  if (!selection) return null;
  if (selection.kind === 'concept') return profile.concept_types[selection.id];
  if (selection.kind === 'relationship') return profile.relationship_types[selection.id];
  if (selection.kind === 'layer') return profile.layers[selection.id];
  if (selection.kind === 'metadata') return profile.metadata_fields[selection.id];
  return null;
}


function selectionChipLabel(selection: WorkbenchSelection, namespace: string | null) {
  if (!selection) return `Namespace · ${namespace ?? 'current'}`;
  const prefix: Record<string, string> = {
    concept: 'Type',
    relationship: 'Relationship',
    layer: 'Layer',
    metadata: 'Metadata',
    candidate: 'Candidate',
    instance: 'Instance',
    fact: 'Fact',
    source: 'Source',
  };
  const suffix = selection.source ? ` · ${labelFor(selection.source)}` : '';
  return `${prefix[selection.kind] ?? labelFor(selection.kind)} · ${selection.title || labelFor(selection.id)}${suffix}`;
}

function objectWorkbenchSelection(selection: WorkbenchSelection): WorkbenchSelection {
  if (selection?.kind === 'instance' && selection.concept_type) {
    return { kind: 'concept', id: selection.concept_type, title: labelFor(selection.concept_type), source: selection.source };
  }
  return selection;
}

function buildExampleMapFromProfile(profile: OntologyProfile, namespace: string | null, selectedConceptType?: string | null): EnterpriseMapProjectionData {
  const conceptEntries = Object.entries(profile.concept_types ?? {});
  const visibleConcepts = selectedConceptType && profile.concept_types?.[selectedConceptType]
    ? conceptEntries.filter(([id]) => id === selectedConceptType)
    : conceptEntries.slice(0, 6);
  const exampleConcepts = (visibleConcepts.length ? visibleConcepts : conceptEntries.slice(0, 3));
  const nodes = exampleConcepts.map(([id, concept], index) => {
    const layerId = String(concept.default_layer ?? concept.layer ?? 'examples');
    const abstractionId = String(concept.abstraction_level ?? 'example');
    return {
      id: `example-${id}-${index + 1}`,
      label: concept.label ?? labelFor(id),
      name: `Example ${concept.label ?? labelFor(id)}`,
      score: 1,
      concept_type: id,
      concept_label: concept.label ?? labelFor(id),
      concept_color: String(concept.color ?? profile.graph_instruction?.concept_type_defaults?.[id]?.color ?? '#64748b'),
      concept_shape: String(concept.shape ?? profile.graph_instruction?.concept_type_defaults?.[id]?.shape ?? 'rounded_rectangle'),
      abstraction_level: abstractionId,
      abstraction_label: profile.abstraction_levels?.[abstractionId]?.label ?? labelFor(abstractionId),
      layer_id: layerId,
      layer_label: profile.layers?.[layerId]?.label ?? labelFor(layerId),
      layer_order: Number(profile.layers?.[layerId]?.order ?? index + 1),
      pack_id: 'graph-instruction-examples',
      lifecycle_state: 'candidate',
      review_state: 'example',
      confidence: null,
      provenance_refs: ['GraphInstruction example fallback'],
      owner: 'Example only',
      description: `Example-only ${concept.label ?? labelFor(id)} card generated from the ontology spec because no live instances are available.`,
      metadata: { example: true, source: 'graph_instruction_fallback', concept_type: id },
      properties: { example: true },
      validation_issues: [{ message: 'Example fixture only — not confirmed company data.' }],
      event_count: 1,
    };
  });
  const nodeIdsByConcept = new Map(nodes.map((node) => [node.concept_type, node.id]));
  const edges = Object.entries(profile.relationship_types ?? {}).flatMap(([id, relationship]) => {
    const sources = relationship.allowed_source_types?.length ? relationship.allowed_source_types : Array.from(nodeIdsByConcept.keys()).slice(0, 1);
    const targets = relationship.allowed_target_types?.length ? relationship.allowed_target_types : Array.from(nodeIdsByConcept.keys()).slice(-1);
    return sources.flatMap((sourceType) => targets.flatMap((targetType) => {
      const source = nodeIdsByConcept.get(sourceType);
      const target = nodeIdsByConcept.get(targetType);
      if (!source || !target || source === target) return [];
      return [{ source, target, map_source: source, map_target: target, label: id, relationship_type: id, family: String(relationship.family ?? 'semantic'), style: String(relationship.style ?? 'dashed'), weight: Number(relationship.weight ?? 0.5), review_state: 'example', is_candidate: true, validation_issues: [{ message: 'Example relationship only — not persisted.' }] }];
    }));
  }).slice(0, 8);
  const layerMap = new Map<string, { id: string; label: string; order: number; count: number; description: string; lifecycle_state: string }>();
  nodes.forEach((node) => {
    const current = layerMap.get(node.layer_id) ?? { id: node.layer_id, label: node.layer_label, order: Number(node.layer_order ?? 999), count: 0, description: 'Example layer from ontology profile fallback.', lifecycle_state: 'example' };
    current.count += 1;
    layerMap.set(node.layer_id, current);
  });
  return {
    nodes,
    edges,
    layers: Array.from(layerMap.values()),
    abstraction_levels: Object.entries(profile.abstraction_levels ?? {}).map(([id, level]) => ({ id, label: level.label ?? labelFor(id), order: Number(level.order ?? 999), description: level.description })),
    concept_type_counts: Object.fromEntries(nodes.map((node) => [String(node.concept_type), nodes.filter((item) => item.concept_type === node.concept_type).length])),
    relationship_type_counts: Object.fromEntries(edges.map((edge) => [String(edge.relationship_type), edges.filter((item) => item.relationship_type === edge.relationship_type).length])),
    relationship_family_counts: Object.fromEntries(edges.map((edge) => [String(edge.family), edges.filter((item) => item.family === edge.family).length])),
    stats: { node_count: nodes.length, edge_count: edges.length, layer_count: layerMap.size, concept_type_count: new Set(nodes.map((node) => node.concept_type)).size, relationship_type_count: new Set(edges.map((edge) => edge.relationship_type)).size, candidate_edge_count: edges.length, validation_issue_count: nodes.length + edges.length, ontology_candidate_count: 0, source_node_count: 0, source_edge_count: 0 },
    meta: { profile_exists: true, ontology_profile: { profile_id: profile.profile_id, version: profile.version, status: profile.status ?? 'draft' }, fallback_source: 'graph_instruction_examples', fallback_label: 'Examples only — no confirmed company instances' },
  };
}

function objectSelectorOptions(profile: OntologyProfile, candidates: OntologyCandidate[]) {
  return [
    { value: 'namespace:current', label: `Namespace · ${profile.namespace}` },
    ...Object.keys(profile.concept_types ?? {}).map((id) => ({ value: `concept:${id}`, label: `Type · ${labelFor(id, profile.concept_types[id]?.label)}` })),
    ...Object.keys(profile.relationship_types ?? {}).map((id) => ({ value: `relationship:${id}`, label: `Relationship · ${labelFor(id, profile.relationship_types[id]?.label)}` })),
    ...Object.keys(profile.layers ?? {}).map((id) => ({ value: `layer:${id}`, label: `Layer · ${labelFor(id, profile.layers[id]?.label)}` })),
    ...Object.keys(profile.metadata_fields ?? {}).map((id) => ({ value: `metadata:${id}`, label: `Metadata · ${labelFor(id, profile.metadata_fields[id]?.label)}` })),
    ...candidates.slice(0, 10).map((candidate) => ({ value: `candidate:${candidate.id}`, label: `Candidate · ${candidate.original_label}` })),
  ];
}

function DockTabButton({ active, icon, label, onClick }: { active: boolean; icon: string; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={label}
      className={`inline-flex min-w-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition ${active ? 'bg-primary text-white' : ''}`}
      style={{ borderColor: 'var(--color-border)', color: active ? undefined : 'var(--color-text-main)' }}
    >
      <span className="material-symbols-outlined text-[16px]" aria-hidden="true">{icon}</span>
      <span className="truncate">{label}</span>
    </button>
  );
}

function ToolbarButton({ label, icon, onClick, disabled, danger = false }: { label: string; icon: string; onClick: () => void; disabled?: boolean; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-semibold disabled:opacity-50 ${danger ? 'text-danger' : ''}`}
      style={{ borderColor: 'var(--color-border)', color: danger ? undefined : 'var(--color-text-main)' }}
    >
      <span className="material-symbols-outlined text-[17px]" aria-hidden="true">{icon}</span>
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function PackPreviewPanel({ preview, onClear }: { preview: PackPreview | null; onClear: () => void }) {
  if (!preview) return null;
  return (
    <section className="rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }} data-testid="ontology-pack-preview">
      <div className="flex items-start justify-between gap-2">
        <div><h4 className="font-semibold" style={{ color: 'var(--color-text-main)' }}>{labelFor(preview.action)} preview · {preview.packId}</h4><p className="mt-1" style={{ color: 'var(--color-text-muted)' }}>Side-effect-free validation and migration preview. Install or disable only after reviewing the diff.</p></div>
        <button type="button" onClick={onClear} className="rounded-lg border px-2 py-1 font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Clear</button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1">{Object.entries(preview.affectedCounts).map(([key, value]) => <span key={key} className="rounded-full border px-2 py-0.5" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>{labelFor(key)} · {value}</span>)}</div>
      {preview.issues?.length ? <IssueList issues={preview.issues} /> : null}
      <pre className="mt-3 max-h-44 overflow-auto rounded-lg border p-2" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>{JSON.stringify({ removed: preview.removed, retained: preview.retained, orphaned: preview.orphaned, migration_notes: preview.migrationNotes }, null, 2)}</pre>
    </section>
  );
}

function DomainPacksPanel({ packs, installed, packPreview, pendingInstallPackId, onPreviewInstall, onInstall, onPreviewUninstall, onUninstall }: { packs: DomainPackManifest[]; installed: Record<string, unknown>; packPreview: PackPreview | null; pendingInstallPackId: string | null; onPreviewInstall: (packId: string) => void; onInstall: (packId: string) => void; onPreviewUninstall: (packId: string) => void; onUninstall: (packId: string) => void }) {
  return (
    <div className="space-y-3">
      <div><h4 className="text-xs font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Vocabulary bundles</h4><p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Reusable ontology starting points. They extend the horizontal product spine without hardcoded domain UI.</p></div>
      <PackPreviewPanel preview={packPreview} onClear={() => onPreviewInstall('')} />
      {packs.length === 0 ? (
        <p className="rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>No vocabulary bundles are available for this namespace.</p>
      ) : packs.map((pack) => {
        const installedRecord = asPackLifecycleRecord(installed?.[pack.pack_id]);
        const isInstalled = installedRecord.status === 'installed' || Boolean(installed?.[pack.pack_id] && !installedRecord.status);
        const counts = packAffectedCounts(pack);
        const canInstall = pendingInstallPackId === pack.pack_id && packPreview?.packId === pack.pack_id && packPreview.valid !== false;
        return (
          <article key={pack.pack_id} className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }} data-testid={`domain-pack-${pack.pack_id}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2"><div className="truncate text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{pack.name}</div>{isInstalled && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary">Installed</span>}</div>
                <div className="truncate text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{pack.pack_id} · v{pack.version}{pack.dependencies?.length ? ` · depends on ${pack.dependencies.join(', ')}` : ''}</div>
              </div>
              {isInstalled ? (
                <div className="flex gap-1"><button type="button" onClick={() => onPreviewUninstall(pack.pack_id)} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Preview disable</button><button type="button" onClick={() => onUninstall(pack.pack_id)} disabled={packPreview?.packId !== pack.pack_id || packPreview.action !== 'uninstall'} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold text-danger disabled:opacity-50" style={{ borderColor: 'var(--color-border)' }}>Disable</button></div>
              ) : (
                <div className="flex gap-1"><button type="button" onClick={() => onPreviewInstall(pack.pack_id)} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Preview install</button><button type="button" onClick={() => onInstall(pack.pack_id)} disabled={!canInstall} className="rounded-lg bg-primary px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-50">Install</button></div>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">{Object.entries(counts).map(([key, value]) => <span key={key} className="rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>{labelFor(key)} · {value}</span>)}</div>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-xs" style={{ color: 'var(--color-text-muted)' }}>{(pack.migration_notes?.length ? pack.migration_notes : ['Adds governed ontology definitions, graph defaults, fixtures, and audit metadata.']).slice(0, 2).map((note) => <li key={note}>{note}</li>)}</ul>
          </article>
        );
      })}
    </div>
  );
}

function AssistantProposalPanel({
  proposals,
  onApply,
  onValidate,
  onPreviewDiff,
  onSave,
  onDiscard,
}: {
  proposals: OntologyAssistantProposal[];
  onApply: (index: number) => void;
  onValidate: (index: number) => void;
  onPreviewDiff: (index: number) => void;
  onSave: (index: number) => void;
  onDiscard: (index: number) => void;
}) {
  if (!proposals.length) {
    return <p className="rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>No proposals yet. Ask for a small schema change; proposed JSON will be staged here before it can touch the draft.</p>;
  }
  return (
    <div className="space-y-3" data-testid="ontology-assistant-proposals">
      {proposals.map((proposal, index) => (
        <article key={`${proposal.status}-${index}`} className="rounded-xl border p-3" style={{ borderColor: proposal.status === 'parse_failed' ? 'var(--color-danger)' : 'var(--color-border)', background: 'var(--color-background)' }}>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: proposal.status === 'parse_failed' ? 'rgba(239,68,68,0.10)' : 'var(--color-primary-muted)', color: proposal.status === 'parse_failed' ? 'var(--color-danger)' : 'var(--color-primary)' }}>{proposal.status.replaceAll('_', ' ')}</span>
            <div className="flex flex-wrap gap-1">
              {proposalSectionCounts(proposal.proposedChanges).map((item) => <span key={item.section} className="rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>{labelFor(item.section)} · {item.count}</span>)}
            </div>
          </div>
          <p className="whitespace-pre-wrap text-xs leading-5" style={{ color: 'var(--color-text-main)' }}>{proposal.answer || 'Assistant returned structured proposal only.'}</p>
          {proposal.rationale && <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}><strong>Rationale:</strong> {proposal.rationale}</p>}
          {proposal.evidenceRefs.length > 0 && <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}><strong>Evidence refs:</strong> {proposal.evidenceRefs.join(', ')}</p>}
          {proposal.parseError && <p className="mt-2 rounded-lg border border-danger/40 bg-danger/10 p-2 text-xs text-danger">JSON parse failed: {proposal.parseError}. Natural-language answer is shown, but nothing can be applied.</p>}
          {proposal.proposedChanges && <pre className="mt-2 max-h-44 overflow-auto rounded-lg border p-2 text-[11px]" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>{JSON.stringify(proposal.proposedChanges, null, 2)}</pre>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" disabled={!proposal.proposedChanges || proposal.status === 'discarded'} onClick={() => onApply(index)} className="rounded-lg bg-primary px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-50">Apply to Draft</button>
            <button type="button" onClick={() => onValidate(index)} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Validate</button>
            <button type="button" onClick={() => onPreviewDiff(index)} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Preview Diff</button>
            <button type="button" onClick={() => onSave(index)} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Save</button>
            <button type="button" onClick={() => onDiscard(index)} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold text-danger" style={{ borderColor: 'var(--color-border)' }}>Discard</button>
          </div>
        </article>
      ))}
    </div>
  );
}


function SearchAroundPanel({ searchTerm, onSearchTerm, matches, families, state, onStateChange, onSelect }: { searchTerm: string; onSearchTerm: (value: string) => void; matches: Array<{ value: string; label: string }>; families: string[]; state: VisualDraftState; onStateChange: React.Dispatch<React.SetStateAction<VisualDraftState>>; onSelect: (match: { value: string; label: string }) => void }) {
  return (
    <div className="space-y-3" data-testid="ontology-search-around-controls">
      <input aria-label="Search ontology workbench" value={searchTerm} onChange={(event) => onSearchTerm(event.target.value)} placeholder="Search types, relationships, layers…" className="w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} />
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
        <h4 className="text-xs font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Search around</h4>
        <label className="mt-2 block text-xs" style={{ color: 'var(--color-text-muted)' }}>Direction<select aria-label="Search around direction" value={state.searchDirection} onChange={(event) => onStateChange((current) => ({ ...current, searchDirection: event.target.value as SearchDirection }))} className="mt-1 w-full rounded-lg border px-2 py-1.5" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}><option value="outgoing">Outgoing</option><option value="incoming">Incoming</option><option value="bidirectional">Bidirectional</option></select></label>
        <label className="mt-2 block text-xs" style={{ color: 'var(--color-text-muted)' }}>Relationship family<select aria-label="Search around relationship family" value={state.relationshipFamily} onChange={(event) => onStateChange((current) => ({ ...current, relationshipFamily: event.target.value }))} className="mt-1 w-full rounded-lg border px-2 py-1.5" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>{families.map((family) => <option key={family} value={family}>{labelFor(family)}</option>)}</select></label>
        <label className="mt-2 block text-xs" style={{ color: 'var(--color-text-muted)' }}>Depth {state.depth}<input aria-label="Search around depth" type="range" min="1" max="4" value={state.depth} onChange={(event) => onStateChange((current) => ({ ...current, depth: Number(event.target.value) }))} className="mt-1 w-full" /></label>
        <p className="mt-2 text-[11px]" style={{ color: 'var(--color-text-muted)' }}>Temporary neighborhood preview. It does not mutate Graph or profile data until saved as a View-plane rule.</p>
      </div>
      {matches.map((match) => <button key={match.value} type="button" onClick={() => onSelect(match)} className="block w-full rounded-lg border px-3 py-2 text-left text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>{match.label}</button>)}
    </div>
  );
}

function HistogramPanel({ rows, onFilterTo, onFilterOut, onClear }: { rows: HistogramRow[]; onFilterTo: (row: HistogramRow) => void; onFilterOut: (row: HistogramRow) => void; onClear: () => void }) {
  return (
    <div className="space-y-3" data-testid="ontology-left-histogram">
      <div className="flex items-center justify-between gap-2"><h4 className="text-xs font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Histograms</h4><button type="button" onClick={onClear} className="rounded-lg border px-2 py-1 text-[11px] font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Clear</button></div>
      {rows.map((row) => <article key={`${row.dimension}:${row.key}`} className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}><div className="flex items-start justify-between gap-2 text-xs"><div className="min-w-0"><strong className="block truncate" style={{ color: 'var(--color-text-main)' }}>{row.label}</strong><span style={{ color: 'var(--color-text-muted)' }}>{labelFor(row.dimension)}{row.binning ? ` · ${row.binning}` : ''}</span></div><div className="text-right"><strong style={{ color: 'var(--color-text-main)' }}>{row.count}</strong><div className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>selected {row.selectedCount}</div></div></div><div className="mt-2 h-2 rounded-full bg-slate-200"><div className="h-2 rounded-full bg-primary" style={{ width: `${Math.min(100, row.count * 18)}%` }} /></div><div className="mt-2 flex gap-2"><button type="button" onClick={() => onFilterTo(row)} className="rounded-lg bg-primary px-2 py-1 text-[11px] font-semibold text-white">Filter to</button><button type="button" onClick={() => onFilterOut(row)} className="rounded-lg border px-2 py-1 text-[11px] font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Filter out</button></div></article>)}
    </div>
  );
}

function VisualControlsPanel({ state, onStateChange, onSaveToView, onReset, isDirty }: { state: VisualDraftState; onStateChange: React.Dispatch<React.SetStateAction<VisualDraftState>>; onSaveToView: () => void; onReset: () => void; isDirty: boolean }) {
  return (
    <section className="rounded-xl border p-4" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }} data-testid="ontology-visual-controls">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Saved view, grouping, layout, and styling</h3><p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Edits are temporary visual state first. Save to View-plane draft before profile save.</p></div><div className="flex gap-2"><button type="button" onClick={onReset} className="rounded-lg border px-3 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Reset visual draft</button><button type="button" onClick={onSaveToView} className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white">Save to View-plane draft</button></div></div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Group by<select aria-label="Group by dimension" value={state.groupBy} onChange={(event) => onStateChange((current) => ({ ...current, groupBy: event.target.value as GroupDimension }))} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>{groupDimensions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Color by<select aria-label="Color by dimension" value={state.colorBy} onChange={(event) => onStateChange((current) => ({ ...current, colorBy: event.target.value as ColorDimension }))} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>{colorDimensions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Style property<input aria-label="Style property selector" value={state.styleProperty} onChange={(event) => onStateChange((current) => ({ ...current, styleProperty: event.target.value }))} placeholder="owner, lifecycle_state, quality_state…" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label>
        <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Fallback swatch<input aria-label="Fallback color" type="color" value={state.fallbackColor} onChange={(event) => onStateChange((current) => ({ ...current, fallbackColor: event.target.value }))} className="mt-1 h-10 w-full rounded-lg border px-2" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }} /></label>
      </div>
      <div className="mt-4"><div className="mb-2 text-xs font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Layout modes</div><div className="flex flex-wrap gap-2">{layoutModes.map((mode) => <button key={mode.value} type="button" disabled={!mode.available} title={mode.reason ?? mode.label} aria-pressed={state.layout === mode.value} onClick={() => onStateChange((current) => ({ ...current, layout: mode.value }))} className={`rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${state.layout === mode.value ? 'bg-primary text-white' : ''}`} style={{ borderColor: 'var(--color-border)', color: state.layout === mode.value ? undefined : 'var(--color-text-main)' }}>{mode.label}{!mode.available ? ' (unavailable)' : ''}</button>)}</div></div>
      <p className="mt-3 text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{isDirty ? 'Visual draft differs from saved GraphInstruction.' : 'Visual draft matches saved GraphInstruction.'}</p>
    </section>
  );
}

export default function OntologyPanel({ selectedNamespace }: { selectedNamespace: string | null }) {
  const addToast = useNotificationStore((state) => state.addToast);
  const { data, profile, suggestedProfile, profileExists, defaultSuggested, isLoading, error, saveProfile, resetDefault, refresh } = useOntologyProfile(selectedNamespace);
  const { unit, saveUnit, refresh: refreshUnit } = useOntologyUnit(selectedNamespace);
  const { validateProfile } = useOntologyValidation(selectedNamespace);
  const { summary, refresh: refreshSummary } = useOntologySummary(selectedNamespace);
  const { history, diffProfile } = useOntologyHistory(selectedNamespace);
  const { packs, installed, validatePack, installPack, uninstallPack } = useOntologyPacks(selectedNamespace);
  const { candidates, isLoading: candidatesLoading, rejectCandidate, bulkUpdateCandidates } = useOntologyCandidates(selectedNamespace, 'pending');
  const { askAssistant } = useOntologyAssistant(selectedNamespace);
  const [draft, setDraft] = React.useState<OntologyProfile | null>(null);
  const [unitDraft, setUnitDraft] = React.useState<OntologyUnitDraft>({ name: '', purpose: '', domain: '', expected_users: [], source_material: [], governance_mode: 'manual' });
  const [issues, setIssues] = React.useState<OntologyValidationIssue[]>([]);
  const [isSaving, setIsSaving] = React.useState(false);
  const [, setIsBootstrapping] = React.useState(false);
  const [diffPreview, setDiffPreview] = React.useState<Record<string, unknown> | null>(null);
  const [packPreview, setPackPreview] = React.useState<PackPreview | null>(null);
  const [pendingInstallPackId, setPendingInstallPackId] = React.useState<string | null>(null);
  const [migrationIssues, setMigrationIssues] = React.useState<Array<Record<string, unknown>>>([]);
  const [saveReason, setSaveReason] = React.useState('Governed ontology profile update');
  const [overrideTicket, setOverrideTicket] = React.useState('');
  const [overrideApprovedBy, setOverrideApprovedBy] = React.useState('');
  const [leftTab, setLeftTab] = React.useState<LeftDockTab>('object_types');
  const [rightTab, setRightTab] = React.useState<RightDockTab>('object');
  const [lens, setLens] = React.useState<LensMode>('spec');
  const [selection, setSelection] = React.useState<WorkbenchSelection>(null);
  const [, setSelectionClearToken] = React.useState(0);
  const [searchTerm, setSearchTerm] = React.useState('');
  const [assistantInput, setAssistantInput] = React.useState('');
  const [assistantHistory, setAssistantHistory] = React.useState<Array<{ role: 'user' | 'assistant'; content: string }>>([]);
  const [assistantProposals, setAssistantProposals] = React.useState<OntologyAssistantProposal[]>([]);
  const [isAskingAssistant, setIsAskingAssistant] = React.useState(false);
  const [visualDraft, setVisualDraft] = React.useState<VisualDraftState>(() => visualStateFromProfile(profile));
  const [undoStack, setUndoStack] = React.useState<DraftHistoryEntry[]>([]);
  const [redoStack, setRedoStack] = React.useState<DraftHistoryEntry[]>([]);

  React.useEffect(() => { setDraft(profile ? cloneProfile(profile) : null); setIssues(data?.validation_issues ?? []); setVisualDraft(visualStateFromProfile(profile)); setUndoStack([]); setRedoStack([]); setDiffPreview(null); setMigrationIssues([]); }, [profile, data?.validation_issues]);
  React.useEffect(() => {
    if (!unit) return;
    setUnitDraft({
      name: unit.name ?? '',
      purpose: unit.purpose ?? '',
      domain: unit.domain ?? '',
      expected_users: unit.expected_users ?? [],
      source_material: unit.source_material ?? [],
      governance_mode: unit.governance_mode ?? 'manual',
    });
  }, [unit]);

  const commitDraft = React.useCallback((next: OntologyProfile | null, label = 'Draft edit') => {
    setDraft((current) => {
      if (!current || !next) return next ? cloneProfile(next) : next;
      if (JSON.stringify(current) === JSON.stringify(next)) return current;
      setUndoStack((stack) => [...stack.slice(-19), { profile: cloneProfile(current), label, timestamp: Date.now() }]);
      setRedoStack([]);
      return cloneProfile(next);
    });
  }, []);

  const handleUndoDraft = React.useCallback(() => {
    setDraft((current) => {
      if (!current || undoStack.length === 0) return current;
      const previous = undoStack[undoStack.length - 1];
      setUndoStack((stack) => stack.slice(0, -1));
      setRedoStack((stack) => [...stack.slice(-19), { profile: cloneProfile(current), label: 'Redo draft edit', timestamp: Date.now() }]);
      return cloneProfile(previous.profile);
    });
  }, [undoStack]);

  const handleRedoDraft = React.useCallback(() => {
    setDraft((current) => {
      if (!current || redoStack.length === 0) return current;
      const next = redoStack[redoStack.length - 1];
      setRedoStack((stack) => stack.slice(0, -1));
      setUndoStack((stack) => [...stack.slice(-19), { profile: cloneProfile(current), label: 'Undo draft edit', timestamp: Date.now() }]);
      return cloneProfile(next.profile);
    });
  }, [redoStack]);

  const isDirty = React.useMemo(() => Boolean(draft && (!profile || JSON.stringify(draft) !== JSON.stringify(profile))), [draft, profile]);
  const selectorOptions = React.useMemo(() => {
    if (!draft) return [];
    const base = objectSelectorOptions(draft, candidates);
    const value = selection ? `${selection.kind}:${selection.id}` : 'namespace:current';
    return base.some((option) => option.value === value) ? base : [{ value, label: selectionChipLabel(selection, selectedNamespace) }, ...base];
  }, [draft, candidates, selection, selectedNamespace]);
  const selectedObjectValue = selection ? `${selection.kind}:${selection.id}` : 'namespace:current';
  const selectedObject = React.useMemo(() => draft ? selectedSource(draft, selection) : null, [draft, selection]);
  const selectedConceptType = selection?.kind === 'concept' ? selection.id : selection?.kind === 'instance' ? selection.concept_type : null;
  const exampleMap = React.useMemo(() => draft ? buildExampleMapFromProfile(draft, selectedNamespace, selectedConceptType) : null, [draft, selectedNamespace, selectedConceptType]);
  const validationSummary = React.useMemo(() => ({ errors: issues.filter((item) => item.severity === 'error').length, warnings: issues.filter((item) => item.severity === 'warning').length }), [issues]);
  const families = React.useMemo(() => draft ? relationshipFamilies(draft) : ['all'], [draft]);
  const histogram = React.useMemo(() => draft ? histogramRows(draft, candidates, visualDraft).slice(0, 12) : [], [draft, candidates, visualDraft]);
  const visualDraftDirty = React.useMemo(() => profile ? JSON.stringify(visualDraft) !== JSON.stringify(visualStateFromProfile(profile)) : false, [profile, visualDraft]);
  const packOwnership = React.useMemo(() => packOwnershipFromInstalled(installed?.installed_packs ?? {}), [installed?.installed_packs]);
  const specWorkbenchModel = React.useMemo(() => draft ? specLensAdapter(draft, selection as unknown as import('@/components/knowledge/workbench').WorkbenchSelection, packOwnership) : null, [draft, selection, packOwnership]);
  const handleSelectionChange = React.useCallback((next: WorkbenchSelection) => {
    setSelection(next ? { ...next, source: next.source ?? 'profile' } : null);
    setVisualDraft((current) => ({ ...current, selectedNodeIds: next ? [`${next.kind}:${next.id}`] : [] }));
  }, []);
  const handleSpecNodeSelect = React.useCallback((nodeId: string) => {
    const concept = draft?.concept_types?.[nodeId];
    if (!concept) return;
    handleSelectionChange({ kind: 'concept', id: nodeId, title: labelFor(nodeId, concept.label), source: 'profile' });
    setRightTab('object');
  }, [draft, handleSelectionChange]);
  const handleSpecEdgeSelect = React.useCallback((edgeId: string) => {
    const relationshipId = edgeId.split(':')[0];
    const relationship = draft?.relationship_types?.[relationshipId];
    if (!relationship) return;
    handleSelectionChange({ kind: 'relationship', id: relationshipId, title: labelFor(relationshipId, relationship.label), source: 'profile' });
    setRightTab('object');
  }, [draft, handleSelectionChange]);
  const handleClearSelection = React.useCallback(() => {
    handleSelectionChange(null);
    setSelectionClearToken((token) => token + 1);
  }, [handleSelectionChange]);
  const selectMapInstance = React.useCallback((trigger: HTMLElement) => {
    const instanceId = trigger.dataset.ontologyInstanceId;
    const conceptType = trigger.dataset.ontologyConceptType;
    const title = trigger.dataset.ontologyInstanceTitle;
    if (!instanceId || !conceptType || !title) return;
    handleSelectionChange({ kind: 'instance', id: instanceId, instance_id: instanceId, concept_type: conceptType, title, source: trigger.dataset.ontologySource ?? 'example' });
    setRightTab('object');
  }, [handleSelectionChange]);
  const handleMapInstanceTrigger = React.useCallback((event: React.SyntheticEvent<HTMLElement>) => {
    const rawTarget = event.target;
    const target = rawTarget instanceof HTMLElement ? rawTarget : rawTarget instanceof Node ? rawTarget.parentElement : null;
    const trigger = target?.closest<HTMLElement>('[data-ontology-instance-id]');
    if (!trigger) return;
    selectMapInstance(trigger);
  }, [selectMapInstance]);

  const runValidation = async (candidate: OntologyProfile) => {
    const result = await validateProfile(candidate);
    setIssues(result.issues ?? []);
    return result;
  };
  const handlePreviewDiff = async (candidate: OntologyProfile = draft as OntologyProfile) => {
    if (!candidate) return null;
    const preview = await diffProfile(candidate, profile ?? undefined);
    setDiffPreview(preview.diff ?? null);
    setMigrationIssues(preview.migration_issues ?? []);
    return preview;
  };
  const handleBootstrap = async () => {
    setIsBootstrapping(true);
    try {
      if (selectedNamespace) await saveUnit({ ...unitDraft, namespace: selectedNamespace, active_profile_id: null, lifecycle: 'draft' });
      await resetDefault();
      setUndoStack([]);
      setRedoStack([]);
      setDiffPreview(null);
      setMigrationIssues([]);
      await Promise.all([refresh(), refreshSummary(), refreshUnit()]);
      addToast({ type: 'success', title: 'Ontology profile created', message: 'Default ontology profile is now active.', autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Bootstrap failed', message: err instanceof Error ? err.message : 'Unable to create ontology profile.', autoDismiss: false });
    } finally { setIsBootstrapping(false); }
  };
  const persistDraftUnit = React.useCallback(async () => {
    if (!selectedNamespace) return null;
    const saved = await saveUnit({ ...unitDraft, namespace: selectedNamespace, active_profile_id: null, lifecycle: 'draft' });
    await refreshUnit();
    return saved.unit;
  }, [refreshUnit, saveUnit, selectedNamespace, unitDraft]);

  const handleStartBlankProfile = React.useCallback(() => {
    if (!selectedNamespace) return;
    const next = makeBlankOntologyProfile(selectedNamespace);
    setDraft(next);
    setIssues([]);
    setDiffPreview(null);
    setMigrationIssues([]);
    setUndoStack([]);
    setRedoStack([]);
    setLens('spec');
    setLeftTab('object_types');
    setRightTab('object');
    setSelection(null);
    setSaveReason('Create ontology unit draft');
  }, [selectedNamespace]);
  const handleCreateBlankUnit = React.useCallback(async () => {
    try {
      await persistDraftUnit();
      handleStartBlankProfile();
      addToast({ type: 'success', title: 'Ontology unit saved', message: 'Unit identity metadata was saved with no active profile.', autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Unit save failed', message: err instanceof Error ? err.message : 'Unable to save ontology unit metadata.', autoDismiss: false });
    }
  }, [addToast, handleStartBlankProfile, persistDraftUnit]);
  const handleBuildFromKnowledge = React.useCallback(() => {
    handleStartBlankProfile();
    setRightTab('assistant');
    setLeftTab('object_types');
    setAssistantInput(`Draft a starter ontology unit for ${selectedNamespace} from imported knowledge and pending candidates. Propose object types, relationship types, metadata fields, validation rules, and a first saved view. Keep changes small and return proposed_changes JSON.`);
  }, [handleStartBlankProfile, selectedNamespace]);
  const handleCreateBuildFromKnowledge = React.useCallback(async () => {
    await persistDraftUnit();
    handleBuildFromKnowledge();
  }, [handleBuildFromKnowledge, persistDraftUnit]);
  const handleAskAssistantDraft = React.useCallback(() => {
    handleStartBlankProfile();
    setRightTab('assistant');
    setAssistantInput(`Draft a small ontology unit for ${selectedNamespace}. Start with the business purpose, then propose object types, relationships, properties, validation rules, and view styling as governed proposed_changes JSON.`);
  }, [handleStartBlankProfile, selectedNamespace]);
  const handleCreateAssistantDraft = React.useCallback(async () => {
    await persistDraftUnit();
    if (!selectedNamespace || isAskingAssistant) {
      handleAskAssistantDraft();
      return;
    }
    const next = makeBlankOntologyProfile(selectedNamespace);
    setDraft(next);
    setIssues([]);
    setDiffPreview(null);
    setMigrationIssues([]);
    setUndoStack([]);
    setRedoStack([]);
    setLens('spec');
    setLeftTab('object_types');
    setRightTab('assistant');
    setSelection(null);
    setSaveReason('Create ontology unit draft from AI proposal');
    const message = `Draft a small ontology unit for ${selectedNamespace}. Start with the business purpose, then propose object types, relationships, properties, validation rules, and view styling as governed proposed_changes JSON.`;
    const nextHistory = [...assistantHistory, { role: 'user' as const, content: message }].slice(-8);
    setAssistantHistory(nextHistory);
    setAssistantInput(message);
    setIsAskingAssistant(true);
    try {
      const response = await askAssistant({
        message,
        profile: next,
        selected: { kind: 'namespace', namespace: selectedNamespace },
        history: nextHistory,
        context: {
          scope: { kind: 'namespace', id: selectedNamespace },
          candidate_refs: candidates.slice(0, 5).map(candidateAssistantContext),
          evidence_refs: candidateEvidenceRefs(candidates),
          fact_refs: [],
          pack_refs: Object.keys(installed?.installed_packs ?? {}),
        },
      });
      setAssistantHistory((turns) => [...turns, { role: 'assistant' as const, content: response.text }].slice(-8));
      setAssistantProposals((items) => [parseOntologyAssistantResponse(response.text), ...items].slice(0, 6));
    } catch (err) {
      const messageText = err instanceof Error ? err.message : 'Ontology assistant is unavailable.';
      setAssistantHistory((turns) => [...turns, { role: 'assistant' as const, content: messageText }].slice(-8));
      setAssistantProposals((items) => [{ answer: messageText, proposedChanges: null, evidenceRefs: [], status: 'parse_failed' as const, parseError: messageText }, ...items].slice(0, 6));
    } finally {
      setIsAskingAssistant(false);
    }
  }, [askAssistant, assistantHistory, candidates, handleAskAssistantDraft, installed?.installed_packs, isAskingAssistant, persistDraftUnit, selectedNamespace]);
  const handlePreviewSeedTemplate = React.useCallback(() => {
    if (!suggestedProfile || !selectedNamespace) return;
    const next = cloneForDraft(suggestedProfile);
    next.namespace = selectedNamespace;
    next.status = 'draft';
    setDraft(next);
    setIssues(data?.validation_issues ?? []);
    setDiffPreview(null);
    setMigrationIssues([]);
    setUndoStack([]);
    setRedoStack([]);
    setLens('spec');
    setLeftTab('object_types');
    setRightTab('governance');
    setSelection(null);
    setSaveReason('Create ontology unit from seed template');
    addToast({ type: 'info', title: 'Seed template loaded', message: 'Review this local draft, then validate, preview diff, and save before it becomes active.', autoDismiss: true });
  }, [addToast, data?.validation_issues, selectedNamespace, suggestedProfile]);
  const handlePreviewPackTemplate = React.useCallback((pack: DomainPackManifest) => {
    if (!selectedNamespace) return;
    const next = makeProfileFromPackTemplate(selectedNamespace, pack);
    setDraft(next);
    setIssues([]);
    setDiffPreview(null);
    setMigrationIssues([]);
    setUndoStack([]);
    setRedoStack([]);
    setLens('spec');
    setLeftTab('object_types');
    setRightTab('governance');
    setSelection(null);
    setSaveReason(`Create ontology unit from ${pack.name} template`);
    addToast({ type: 'info', title: 'Template preview loaded', message: `${pack.name} is a local draft only. Validate, preview diff, and save before it becomes active.`, autoDismiss: true });
  }, [addToast, selectedNamespace]);
  const handleSave = async (): Promise<boolean> => {
    if (!draft) return false;
    setIsSaving(true);
    try {
      const profileToPublish: OntologyProfile = { ...draft, status: 'active' };
      const validation = await runValidation(profileToPublish);
      if (!validation.valid || validationErrorCount(validation.issues) > 0) {
        addToast({ type: 'error', title: 'Validation blocked save', message: 'Fix ontology validation errors before publishing.', autoDismiss: false });
        return false;
      }
      const preview = await handlePreviewDiff(profileToPublish);
      const dangerous = (preview?.migration_issues ?? []).filter((issue) => String(issue.severity) === 'error');
      if (dangerous.length > 0 && (!overrideTicket.trim() || !overrideApprovedBy.trim())) {
        addToast({ type: 'error', title: 'Migration override required', message: 'Dangerous profile changes require preview plus override ticket and approver metadata.', autoDismiss: false });
        return false;
      }
      await saveProfile(profileToPublish, { reason: saveReason || 'Governed ontology profile update', validation_override: dangerous.length > 0 ? { ticket: overrideTicket, approved_by: overrideApprovedBy, reason: saveReason, previewed: true } : null });
      setUndoStack([]);
      setRedoStack([]);
      await Promise.all([refresh(), refreshSummary(), refreshUnit()]);
      addToast({ type: 'success', title: profileExists ? 'Ontology profile update saved' : 'Ontology profile published', message: 'Profile changes were validated, previewed, and persisted as the active profile.', autoDismiss: true });
      return true;
    } catch (err) {
      addToast({ type: 'error', title: 'Save failed', message: err instanceof Error ? err.message : 'Unable to save ontology profile.', autoDismiss: false });
      return false;
    } finally { setIsSaving(false); }
  };
  const handleReset = async () => {
    if (!window.confirm('Reset this namespace ontology profile to the default seed profile? Existing custom enum and metadata edits may be replaced.')) return;
    await handleBootstrap();
  };
  const handlePackPreviewInstall = async (packId: string) => {
    if (!packId) { setPackPreview(null); setPendingInstallPackId(null); return; }
    try {
      const validation = await validatePack(packId);
      const manifest = validation.manifest ?? packs.find((item) => item.pack_id === packId);
      setPackPreview({ packId, action: 'install', valid: validation.valid, issues: validation.issues ?? [], affectedCounts: manifest ? packAffectedCounts(manifest) : {}, migrationNotes: manifest?.migration_notes ?? [] });
      setPendingInstallPackId(validation.valid ? packId : null);
      if (!validation.valid || !validation.profile) {
        addToast({ type: 'error', title: 'Pack validation blocked install', message: `Review validation errors before installing ${packId}.`, autoDismiss: false });
        return;
      }
      const preview = await diffProfile(validation.profile, profile ?? undefined);
      setDiffPreview(preview.diff ?? null);
      setMigrationIssues(preview.migration_issues ?? []);
      addToast({ type: 'info', title: 'Pack install preview ready', message: `${packId} was validated. Review profile diff, migration notes, and affected counts before installing.`, autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Pack preview failed', message: err instanceof Error ? err.message : `Unable to preview ${packId}.`, autoDismiss: false });
    }
  };
  const handlePackPreviewUninstall = async (packId: string) => {
    const preview = packUninstallPreview(packId, installed?.installed_packs ?? {}, packs);
    setPackPreview(preview);
    setPendingInstallPackId(null);
    setDiffPreview({ action: 'uninstall_pack', pack_id: packId, removed: preview.removed, retained: preview.retained, orphaned: preview.orphaned });
    setMigrationIssues(Object.entries(preview.orphaned ?? {}).flatMap(([section, ids]) => ids.map((id) => ({ severity: 'warning', code: 'PACK_ORPHAN_PREVIEW', path: `${section}.${id}`, message: `${id} may be orphaned when ${packId} is disabled.` }))));
  };
  const handlePackInstall = async (packId: string) => {
    if (pendingInstallPackId !== packId || packPreview?.action !== 'install') {
      await handlePackPreviewInstall(packId);
      return;
    }
    try {
      await installPack(packId);
      await Promise.all([refresh(), refreshSummary()]);
      setPendingInstallPackId(null);
      addToast({ type: 'success', title: 'Domain pack installed', message: `${packId} is now active for ${selectedNamespace}.`, autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Pack install failed', message: err instanceof Error ? err.message : `Unable to install ${packId}.`, autoDismiss: false });
    }
  };
  const handlePackUninstall = async (packId: string) => {
    if (packPreview?.packId !== packId || packPreview.action !== 'uninstall') {
      await handlePackPreviewUninstall(packId);
      return;
    }
    try {
      await uninstallPack(packId);
      await Promise.all([refresh(), refreshSummary()]);
      addToast({ type: 'success', title: 'Domain pack disabled', message: `${packId} was disabled for ${selectedNamespace}.`, autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Pack uninstall failed', message: err instanceof Error ? err.message : `Unable to uninstall ${packId}.`, autoDismiss: false });
    }
  };

  const handleAskAssistant = async (message = assistantInput) => {
    const trimmed = message.trim();
    if (!trimmed || !draft || isAskingAssistant) return;
    const selectedCandidate = selection?.kind === 'candidate' ? candidates.find((candidate) => candidate.id === selection.id) : null;
    const nextHistory = [...assistantHistory, { role: 'user' as const, content: trimmed }].slice(-8);
    setAssistantHistory(nextHistory);
    setAssistantInput('');
    setIsAskingAssistant(true);
    try {
      const response = await askAssistant({
        message: trimmed,
        profile: draft,
        selected: selectedObject ? { kind: selection?.kind, id: selection?.id, object: selectedObject } : { kind: 'namespace', namespace: selectedNamespace },
        history: nextHistory,
        context: {
          scope: selection ? { kind: selection.kind, id: selection.id, title: selection.title } : { kind: 'namespace', id: selectedNamespace },
          candidate_refs: selectedCandidate ? [candidateAssistantContext(selectedCandidate)] : candidates.slice(0, 5).map(candidateAssistantContext),
          evidence_refs: candidateEvidenceRefs(candidates, selectedCandidate),
          fact_refs: [],
          pack_refs: Object.keys(installed?.installed_packs ?? {}),
        },
      });
      setAssistantHistory((turns) => [...turns, { role: 'assistant' as const, content: response.text }].slice(-8));
      setAssistantProposals((items) => [parseOntologyAssistantResponse(response.text), ...items].slice(0, 6));
    } catch (err) {
      const messageText = err instanceof Error ? err.message : 'Ontology assistant is unavailable.';
      setAssistantHistory((turns) => [...turns, { role: 'assistant' as const, content: messageText }].slice(-8));
      setAssistantProposals((items) => [{ answer: messageText, proposedChanges: null, evidenceRefs: [], status: 'parse_failed' as const, parseError: messageText }, ...items].slice(0, 6));
    } finally {
      setIsAskingAssistant(false);
    }
  };
  const markProposalStatus = (index: number, status: ProposalStatus) => {
    setAssistantProposals((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status } : item));
  };
  const handleApplyProposal = (index: number) => {
    const proposal = assistantProposals[index];
    if (!draft || !proposal?.proposedChanges) return;
    const result = applyOntologyProposalToDraft(draft, proposal.proposedChanges);
    commitDraft(result.profile, 'Assistant proposal applied');
    markProposalStatus(index, 'applied');
    addToast({ type: result.rejected.length ? 'warning' : 'success', title: 'Proposal applied to draft', message: result.rejected.length ? `Applied ${result.appliedPaths.length} paths; rejected ${result.rejected.length} advisory/unsupported changes.` : `Applied ${result.appliedPaths.length} proposed draft paths. Validate and preview diff before saving.`, autoDismiss: true });
  };
  const handleValidateProposal = async (index: number) => {
    if (!draft) return;
    const validation = await runValidation(draft);
    if (validation.valid && validationErrorCount(validation.issues) === 0) markProposalStatus(index, 'validated');
  };
  const handlePreviewProposalDiff = async (index: number) => {
    const preview = await handlePreviewDiff();
    if (preview) markProposalStatus(index, 'diffed');
  };
  const handleSaveProposal = async (index: number) => {
    if (await handleSave()) markProposalStatus(index, 'saved');
  };
  const handleDiscardProposal = (index: number) => {
    markProposalStatus(index, 'discarded');
  };


  const handleHistogramAction = (row: HistogramRow, action: HistogramAction) => {
    setVisualDraft((current) => action === 'filter_to'
      ? { ...current, filters: setFilterRecord(current.filters, row.dimension, row.key) }
      : { ...current, excludedFilters: setFilterRecord(current.excludedFilters, row.dimension, row.key) });
  };
  const handleClearVisualFilters = () => setVisualDraft((current) => ({ ...current, filters: {}, excludedFilters: {} }));
  const handleSaveVisualView = () => {
    if (!draft) return;
    commitDraft(applyVisualStateToProfile(draft, visualDraft), 'View-plane visual controls staged');
    addToast({ type: 'success', title: 'View-plane draft updated', message: 'Visual controls were staged in GraphInstruction. Save the profile to persist them.', autoDismiss: true });
  };

  const handleCandidateAction = async (kind: 'approve' | 'map' | 'reject', candidate: OntologyCandidate, canonicalId?: string) => {
    if (kind === 'approve') {
      if (!draft) {
        addToast({ type: 'error', title: 'Candidate not staged', message: 'Ontology profile data is not available yet.', autoDismiss: false });
        return;
      }
      const staged = stageCandidateApproval(draft, candidate);
      if (!staged) {
        addToast({ type: 'error', title: 'Candidate requires graph review', message: 'Graph-plane candidates are not persisted from this panel. Use governed graph review workflows with provenance.', autoDismiss: false });
        return;
      }
      commitDraft(staged.profile, `Candidate approval staged: ${candidate.id}`);
      setDiffPreview(null);
      addToast({ type: 'success', title: 'Candidate staged in draft', message: `${staged.path} was staged locally. Validate, preview diff, and save to persist.`, autoDismiss: true });
      return;
    }
    if (kind === 'map' && canonicalId) {
      if (!draft) {
        addToast({ type: 'error', title: 'Candidate map not staged', message: 'Ontology profile data is not available yet.', autoDismiss: false });
        return;
      }
      const staged = stageCandidateMap(draft, candidate, canonicalId);
      if (!staged) {
        addToast({ type: 'error', title: 'Candidate map not staged', message: 'Choose an existing concept or relationship type before mapping this candidate.', autoDismiss: false });
        return;
      }
      commitDraft(staged.profile, `Candidate map staged: ${candidate.id}`);
      setDiffPreview(null);
      addToast({ type: 'success', title: 'Candidate map staged in draft', message: `${staged.path} was staged locally. Validate, preview diff, and save to persist.`, autoDismiss: true });
      return;
    }
    if (kind === 'reject') await rejectCandidate(candidate.id, 'Rejected from Ontology UI');
    await Promise.all([refresh(), refreshSummary()]);
  };

  React.useEffect(() => {
    const handleNativeSelection = (event: PointerEvent | MouseEvent) => {
      const rawTarget = event.target;
      const target = rawTarget instanceof HTMLElement ? rawTarget : rawTarget instanceof Node ? rawTarget.parentElement : null;
      const clearTrigger = target?.closest<HTMLElement>('[data-ontology-clear-selection]');
      if (clearTrigger) {
        // Let React's own handlers run as well. Blocking propagation here can
        // prevent delegated React click handlers from flushing in browser QA.
        handleClearSelection();
        return;
      }
      const instanceTrigger = target?.closest<HTMLElement>('[data-ontology-instance-id]');
      if (!instanceTrigger) return;
      // Native capture bridges non-React/SVG hit targets, while deliberately
      // preserving propagation so button-level React handlers also commit.
      selectMapInstance(instanceTrigger);
    };
    document.addEventListener('pointerdown', handleNativeSelection, true);
    document.addEventListener('pointerup', handleNativeSelection, true);
    document.addEventListener('mousedown', handleNativeSelection, true);
    document.addEventListener('mouseup', handleNativeSelection, true);
    document.addEventListener('click', handleNativeSelection, true);
    return () => {
      document.removeEventListener('pointerdown', handleNativeSelection, true);
      document.removeEventListener('pointerup', handleNativeSelection, true);
      document.removeEventListener('mousedown', handleNativeSelection, true);
      document.removeEventListener('mouseup', handleNativeSelection, true);
      document.removeEventListener('click', handleNativeSelection, true);
    };
  }, [handleClearSelection, selectMapInstance]);

  if (!selectedNamespace) return <div className="p-6 text-sm" style={{ color: 'var(--color-text-muted)' }}>Select a namespace to manage its ontology profile.</div>;
  if (isLoading) return <div className="flex h-full items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading ontology profile…</div>;
  if (error) return <div className="p-6 text-sm text-danger">Failed to load ontology profile: {error}</div>;
  if (!profileExists && !draft) {
    return (
      <OntologyUnitLauncher
        namespace={selectedNamespace}
        suggestedProfile={suggestedProfile}
        unitDraft={unitDraft}
        onUnitDraftChange={setUnitDraft}
        candidates={candidates}
        packs={packs}
        onBuildFromKnowledge={() => { void handleCreateBuildFromKnowledge().catch((err) => addToast({ type: 'error', title: 'Unit save failed', message: err instanceof Error ? err.message : 'Unable to save ontology unit metadata.', autoDismiss: false })); }}
        onAskAssistant={() => { void handleCreateAssistantDraft().catch((err) => addToast({ type: 'error', title: 'Unit save failed', message: err instanceof Error ? err.message : 'Unable to save ontology unit metadata.', autoDismiss: false })); }}
        onPreviewSeed={handlePreviewSeedTemplate}
        onPreviewPack={handlePreviewPackTemplate}
        onStartBlank={() => { void handleCreateBlankUnit(); }}
      />
    );
  }
  if (!draft) return <div className="p-6 text-sm" style={{ color: 'var(--color-text-muted)' }}>No ontology profile data is available.</div>;

  const searchMatches = selectorOptions.filter((option) => option.label.toLowerCase().includes(searchTerm.toLowerCase())).slice(0, 8);
  const unitDisplayName = unit?.name?.trim() || unitDraft.name?.trim() || selectedNamespace;
  const activeProfileHeader = profileExists ? `${unitDisplayName} · Active profile v${draft.version}` : 'Ontology unit draft';
  const profileStateLabel = !profileExists
    ? (isDirty ? 'Ontology unit draft* · Unsaved draft' : 'Ontology unit draft')
    : isDirty
      ? `${unitDisplayName}* · Unsaved draft`
      : activeProfileHeader;
  const publishButtonLabel = profileExists ? 'Save profile update' : 'Publish profile';

  return (
    <div className="h-full overflow-hidden" style={{ background: 'var(--color-background)' }} data-testid="ontology-workbench-shell">
      <div className="flex h-full min-h-[760px] flex-col overflow-hidden rounded-none border-0 xl:rounded-2xl xl:border" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
        <header className="shrink-0 border-b p-3" style={{ borderColor: 'var(--color-border)' }} data-testid="ontology-workbench-top-rail">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-[220px]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="material-symbols-outlined text-[22px]" style={{ color: 'var(--color-primary)' }} aria-hidden="true">hub</span>
                <h2 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>Visual Ontology Workbench</h2>
                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">{selectedNamespace}</span>
                <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: isDirty ? 'rgba(245,158,11,0.14)' : 'var(--color-primary-muted)', color: isDirty ? '#b45309' : 'var(--color-primary)' }} data-testid="ontology-profile-state-label">{profileStateLabel}</span>
              </div>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Governed graph-first surface for Spec, Graph, Evidence, Observation, Analysis, and View affordances.</p>
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
              <label className="min-w-[220px] max-w-[360px] flex-1 text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>
                Scope selector
                <select
                  aria-label="Ontology scope selector"
                  value={selectorOptions.some((option) => option.value === selectedObjectValue) ? selectedObjectValue : 'namespace:current'}
                  onChange={(event) => {
                    const [kind, id] = event.target.value.split(':');
                    if (kind === 'namespace') handleClearSelection();
                    else handleSelectionChange({ kind, id, title: labelFor(id), source: kind === 'candidate' ? 'candidate' : 'profile' });
                  }}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm normal-case tracking-normal outline-none"
                  style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}
                >
                  {selectorOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label className="min-w-[140px] text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>
                Lens
                <select aria-label="Workbench lens" value={lens} onChange={(event) => setLens(event.target.value as typeof lens)} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm normal-case tracking-normal" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>
                  <option value="spec">Spec Lens · what can exist</option>
                  <option value="map">Map Lens · what exists</option>
                </select>
              </label>
              <div className="flex max-w-[320px] items-center gap-2 rounded-lg border px-3 py-2 text-xs" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)', color: 'var(--color-text-main)' }} data-testid="ontology-selection-chip">
                <span className="material-symbols-outlined text-[16px]" aria-hidden="true">ads_click</span>
                <span className="truncate">{selectionChipLabel(selection, selectedNamespace)}</span>
                {selection && <button type="button" data-ontology-clear-selection="true" onPointerDown={handleClearSelection} onMouseDown={handleClearSelection} onClick={handleClearSelection} className="rounded-full px-1 text-[11px] font-semibold" aria-label="Clear ontology selection" style={{ color: 'var(--color-text-muted)' }}>Clear</button>}
              </div>
              {!profileExists && suggestedProfile && <button type="button" onClick={handlePreviewSeedTemplate} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Load seed template</button>}
              <ToolbarButton label="Validate" icon="rule_settings" onClick={() => { void runValidation(draft); }} />
              <ToolbarButton label="Preview diff" icon="difference" onClick={() => { void handlePreviewDiff(); }} disabled={!isDirty} />
              <button type="button" onClick={handleSave} disabled={!isDirty || isSaving} aria-label="Validate and save ontology profile" title="Validate, preview diff, and publish active profile" className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><span className="material-symbols-outlined text-[17px]" aria-hidden="true">publish</span><span className="hidden sm:inline">{isSaving ? 'Publishing…' : publishButtonLabel}</span></button>
              <ToolbarButton label="Undo" icon="undo" onClick={handleUndoDraft} disabled={undoStack.length === 0} />
              <ToolbarButton label="Redo" icon="redo" onClick={handleRedoDraft} disabled={redoStack.length === 0} />
              <ToolbarButton label="Reset to default" icon="restart_alt" onClick={handleReset} danger />
              <ToolbarButton label="Help" icon="help" onClick={() => addToast({ type: 'info', title: 'Workbench help', message: 'Use the canvas for primary editing; advanced studios are in the right dock.', autoDismiss: true })} />
            </div>
          </div>
        </header>

        {!profileExists && <div className="shrink-0 border-b border-amber-300 bg-amber-500/10 px-4 py-2 text-sm text-amber-700">This is a local ontology unit draft. Validate, preview the diff, and publish it to create the active profile.</div>}
        {profileExists && defaultSuggested && <div className="shrink-0 border-b border-amber-300 bg-amber-500/10 px-4 py-2 text-sm text-amber-700">This namespace has no active ontology profile yet. Review the suggested defaults, then publish your edits.</div>}
        {issues.length > 0 && <div className="shrink-0 px-4 pt-3"><IssueList issues={issues} /></div>}
        {diffPreview && <div className="shrink-0 border-b px-4 py-3" style={{ borderColor: 'var(--color-border)' }} data-testid="ontology-diff-preview"><h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Profile diff and migration safety preview</h3><p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Preview is side-effect-free. Error-severity migration issues require override metadata before publish.</p><GraphDiffOverlay diff={diffPreview} /><pre className="mt-3 max-h-40 overflow-auto rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)', color: 'var(--color-text-main)' }}>{JSON.stringify({ diff: diffPreview, migration_issues: migrationIssues }, null, 2)}</pre><div className="mt-3 grid gap-3 md:grid-cols-3"><label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Reason<input value={saveReason} onChange={(event) => setSaveReason(event.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label><label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Override ticket<input value={overrideTicket} onChange={(event) => setOverrideTicket(event.target.value)} placeholder="Required for dangerous changes" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label><label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Approved by<input value={overrideApprovedBy} onChange={(event) => setOverrideApprovedBy(event.target.value)} placeholder="Required for dangerous changes" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label></div></div>}

        <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)_380px] overflow-hidden max-2xl:grid-cols-[250px_minmax(0,1fr)_340px] max-xl:grid-cols-[220px_minmax(0,1fr)] max-lg:grid-cols-1" data-testid="ontology-workbench-layout">
          <aside className="min-h-0 overflow-hidden border-r max-lg:max-h-[300px] max-lg:border-r-0 max-lg:border-b" style={{ borderColor: 'var(--color-border)' }} data-testid="ontology-left-dock">
            <div className="flex flex-wrap gap-2 border-b p-3" style={{ borderColor: 'var(--color-border)' }}>{leftTabs.map((tab) => <DockTabButton key={tab.id} active={leftTab === tab.id} icon={tab.icon} label={tab.label} onClick={() => setLeftTab(tab.id)} />)}</div>
            <div className="h-full overflow-auto p-3">
              {leftTab === 'search' && <SearchAroundPanel searchTerm={searchTerm} onSearchTerm={setSearchTerm} matches={searchMatches} families={families} state={visualDraft} onStateChange={setVisualDraft} onSelect={(match) => { const [kind, id] = match.value.split(':'); handleSelectionChange({ kind, id, title: match.label, source: kind === 'candidate' ? 'candidate' : 'profile' }); }} />}
              {leftTab === 'sources' && <div className="space-y-2 text-sm" style={{ color: 'var(--color-text-muted)' }}><p><strong style={{ color: 'var(--color-text-main)' }}>Unit sources:</strong> {(unit?.source_material?.length ? unit.source_material : unitDraft.source_material ?? []).join(', ') || 'Not specified'}</p><p>Schema source mappings are editable in SelectionInspector.</p></div>}
              {leftTab === 'candidates' && <CandidateReview profile={draft} candidates={candidates} isLoading={candidatesLoading} onApprove={(candidate) => handleCandidateAction('approve', candidate)} onMap={(candidate, canonicalId) => handleCandidateAction('map', candidate, canonicalId)} onReject={(candidate) => handleCandidateAction('reject', candidate)} onBulkReject={async (items) => { await bulkUpdateCandidates(items.map((candidate) => ({ candidate_id: candidate.id, action: 'reject', reason: 'Bulk rejected from Ontology UI' }))); await Promise.all([refresh(), refreshSummary()]); }} />}
              {leftTab === 'object_types' && <div className="space-y-2">{Object.entries(draft.concept_types ?? {}).map(([id, concept]) => <button key={id} type="button" onClick={() => handleSelectionChange({ kind: 'concept', id, title: labelFor(id, concept?.label), source: 'profile' })} className="w-full rounded-xl border p-3 text-left" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}><div className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{labelFor(id, concept?.label)}</div><p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>{concept?.description ?? 'No description yet.'}</p></button>)}</div>}
              {leftTab === 'properties' && <div className="space-y-2">{Object.entries(draft.metadata_fields ?? {}).map(([id, field]) => <button key={id} type="button" onClick={() => handleSelectionChange({ kind: 'metadata', id, title: labelFor(id, field?.label), source: 'profile' })} className="w-full rounded-xl border p-3 text-left" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}><div className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{labelFor(id, field?.label)}</div><p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>{field?.description ?? field?.field_type ?? 'No property details yet.'}</p></button>)}</div>}
              {leftTab === 'relationships' && <div className="space-y-2">{Object.entries(draft.relationship_types ?? {}).map(([id, relationship]) => <button key={id} type="button" onClick={() => handleSelectionChange({ kind: 'relationship', id, title: labelFor(id, relationship?.label), source: 'profile' })} className="w-full rounded-xl border p-3 text-left" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}><div className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{labelFor(id, relationship?.label)}</div><p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>{relationship?.family ?? 'semantic'} · {relationship?.cardinality ?? 'cardinality pending'}</p></button>)}</div>}
              {leftTab === 'validation' && <div className="space-y-3"><IssueList issues={issues} /><button type="button" onClick={() => { void runValidation(draft); }} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white">Validate draft</button><p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{validationSummary.errors} errors · {validationSummary.warnings} warnings</p></div>}
              {leftTab === 'templates' && <div className="space-y-3"><DomainPacksPanel packs={packs} installed={installed?.installed_packs ?? {}} packPreview={packPreview} pendingInstallPackId={pendingInstallPackId} onPreviewInstall={(packId) => { void handlePackPreviewInstall(packId); }} onInstall={(packId) => { void handlePackInstall(packId); }} onPreviewUninstall={(packId) => { void handlePackPreviewUninstall(packId); }} onUninstall={(packId) => { void handlePackUninstall(packId); }} /></div>}
              {leftTab === 'histogram' && <HistogramPanel rows={histogram} onFilterTo={(row) => handleHistogramAction(row, 'filter_to')} onFilterOut={(row) => handleHistogramAction(row, 'filter_out')} onClear={handleClearVisualFilters} />}
            </div>
          </aside>

          <main className="min-h-0 min-w-0 overflow-auto bg-slate-100 p-3" data-testid="ontology-central-canvas">
            {lens === 'spec' ? (
              specWorkbenchModel ? (
                <WorkbenchShell
                  model={specWorkbenchModel}
                  toolbar={false}
                  rightRail={<div data-testid="spec-right-rail-placeholder" className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Use the single SelectionInspector dock to edit schema types; this shell rail stays read-only to avoid duplicate inspectors.</div>}
                >
                  <section data-testid="ontology-schema-canvas" className="space-y-3">
                    {isLoading ? <div className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>Loading schema draft…</div> : null}
                    {!specWorkbenchModel.nodes.length ? <div className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>Add your first object type.</div> : null}
                    {issues.length ? <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-700">Validation: {validationSummary.errors} errors · {validationSummary.warnings} warnings</div> : null}
                    {specWorkbenchModel.nodes.length > 16 ? <div className="rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>Large schema: showing {specWorkbenchModel.nodes.length} type nodes with hierarchy layout and scrollable overflow.</div> : null}
                    <GraphCanvas model={specWorkbenchModel} renderMode="extended" layoutMode="hierarchy" onSelectNode={handleSpecNodeSelect} onSelectEdge={handleSpecEdgeSelect} />
                  </section>
                </WorkbenchShell>
              ) : null
            ) : (
              <>
                {exampleMap?.nodes.length ? (
                  <div
                    className="relative z-20 mb-3 flex flex-wrap gap-2 rounded-xl border bg-white p-2"
                    style={{ borderColor: 'var(--color-border)' }}
                    aria-label="Map Lens object selector"
                    onPointerDownCapture={handleMapInstanceTrigger}
                    onMouseDownCapture={handleMapInstanceTrigger}
                    onClickCapture={handleMapInstanceTrigger}
                  >
                    {exampleMap.nodes.slice(0, 8).map((node) => {
                      const title = String(node.name ?? node.label ?? node.id);
                      const conceptType = String(node.concept_type ?? '');
                      return (
                        <button
                          key={String(node.id)}
                          type="button"
                          aria-label={`Select ${title}`}
                          data-ontology-instance-id={String(node.id)}
                          data-ontology-concept-type={conceptType}
                          data-ontology-instance-title={title}
                          data-ontology-source="example"
                          onPointerDown={(event) => selectMapInstance(event.currentTarget)}
                          onPointerUp={(event) => selectMapInstance(event.currentTarget)}
                          onMouseDown={(event) => selectMapInstance(event.currentTarget)}
                          onMouseUp={(event) => selectMapInstance(event.currentTarget)}
                          onClick={(event) => selectMapInstance(event.currentTarget)}
                          className="rounded-full border px-3 py-1.5 text-xs font-semibold"
                          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}
                        >
                          {title} <span className="font-normal" style={{ color: 'var(--color-text-muted)' }}>· {labelFor(conceptType)}</span>
                        </button>
                      );
                    })}
                  </div>
                ) : null}
                <EnterpriseMapPanel
                  selectedNamespace={selectedNamespace}
                  profileOverride={draft}
                  fallbackMap={exampleMap ?? undefined}
                  conceptTypeFilter={selectedConceptType ?? undefined}
                  onInstanceSelect={(item) => {
                    handleSelectionChange({ kind: 'instance', id: item.id, instance_id: item.id, concept_type: item.concept_type, title: item.title, source: item.source });
                    setRightTab('object');
                  }}
                />
              </>
            )}
          </main>

          <aside className="min-h-0 overflow-hidden border-l max-xl:col-span-2 max-xl:border-l-0 max-xl:border-t max-lg:col-span-1" style={{ borderColor: 'var(--color-border)' }} data-testid="ontology-right-dock">
            <div className="flex flex-wrap gap-2 border-b p-3" style={{ borderColor: 'var(--color-border)' }}>{rightTabs.map((tab) => <DockTabButton key={tab.id} active={rightTab === tab.id} icon={tab.icon} label={tab.label} onClick={() => setRightTab(tab.id)} />)}</div>
            <div className="h-full overflow-auto p-3 pb-28">
              {rightTab === 'object' && <div className="space-y-4">{specWorkbenchModel ? <SelectionInspector model={specWorkbenchModel} selection={objectWorkbenchSelection(selection) as unknown as import('@/components/knowledge/workbench').WorkbenchSelection} profile={draft} onProfileChange={(next) => { if (!selection) { const firstConceptId = Object.keys(draft.concept_types ?? {})[0]; if (firstConceptId) handleSelectionChange({ kind: 'concept', id: firstConceptId, title: labelFor(firstConceptId, next.concept_types?.[firstConceptId]?.label), source: 'profile' }); } commitDraft(next, 'SelectionInspector edit'); }} onValidate={async (candidate) => { await runValidation(candidate); }} /> : null}<CandidateReview profile={draft} candidates={candidates} isLoading={candidatesLoading} onApprove={(candidate) => handleCandidateAction('approve', candidate)} onMap={(candidate, canonicalId) => handleCandidateAction('map', candidate, canonicalId)} onReject={(candidate) => handleCandidateAction('reject', candidate)} onBulkReject={async (items) => { await bulkUpdateCandidates(items.map((candidate) => ({ candidate_id: candidate.id, action: 'reject', reason: 'Bulk rejected from Ontology UI' }))); await Promise.all([refresh(), refreshSummary()]); }} /></div>}
              {rightTab === 'assistant' && <div className="space-y-4 rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)', color: 'var(--color-text-muted)' }} data-testid="ontology-assistant-review-panel"><div><h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>AI co-builder</h3><p className="mt-2">Advisory only: proposals must be applied to the draft, validated, diffed, and saved through governance before company knowledge changes.</p><p className="mt-1 text-xs">Conversation: ontology-schema:{selectedNamespace}:current-actor · Scope: {selection?.title ?? 'namespace'}</p></div><div className="grid gap-2"><textarea aria-label="Ask ontology co-builder" value={assistantInput} onChange={(event) => setAssistantInput(event.target.value)} placeholder="Build starter ontology from selected docs, review this object, add a relationship, map a candidate, draft a pack, or explain validation issues." className="min-h-[92px] rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /><div className="flex flex-wrap gap-2"><button type="button" disabled={!assistantInput.trim() || isAskingAssistant} onClick={() => { void handleAskAssistant(); }} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{isAskingAssistant ? 'Thinking…' : 'Ask assistant'}</button><button type="button" onClick={() => { void handleAskAssistant('Review the selected ontology object and propose one small valid improvement with evidence refs when available.'); }} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Review selected</button><button type="button" onClick={() => { void handleAskAssistant('Draft a small vocabulary bundle proposal with concept_types, relationship_types, layers, metadata_fields, graph_instruction, fixtures, and migration_notes. Keep it advisory and reviewable.'); }} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Draft pack</button></div></div><AssistantProposalPanel proposals={assistantProposals} onApply={handleApplyProposal} onValidate={(index) => { void handleValidateProposal(index); }} onPreviewDiff={(index) => { void handlePreviewProposalDiff(index); }} onSave={(index) => { void handleSaveProposal(index); }} onDiscard={handleDiscardProposal} /></div>}
              {rightTab === 'model' && <div className="space-y-4"><VisualControlsPanel state={visualDraft} onStateChange={setVisualDraft} onSaveToView={handleSaveVisualView} onReset={() => setVisualDraft(visualStateFromProfile(profile))} isDirty={visualDraftDirty} /><GraphInstructionStudio profile={draft} onChange={(next) => commitDraft(next, 'GraphInstruction edit')} onValidate={async (candidate) => { await runValidation(candidate); }} /><RelationshipStudio profile={draft} onChange={(next) => commitDraft(next, 'Relationship studio edit')} /><ConceptTypeStudio profile={draft} onChange={(next) => commitDraft(next, 'Concept type studio edit')} /><AliasManager profile={draft} onChange={(next) => commitDraft(next, 'Alias manager edit')} /></div>}
              {rightTab === 'governance' && <div className="space-y-4"><ProfileSummary profile={draft} summary={summary} profileExists={profileExists} defaultSuggested={defaultSuggested} /><DomainPacksPanel packs={packs} installed={installed?.installed_packs ?? {}} packPreview={packPreview} pendingInstallPackId={pendingInstallPackId} onPreviewInstall={(packId) => { void handlePackPreviewInstall(packId); }} onInstall={(packId) => { void handlePackInstall(packId); }} onPreviewUninstall={(packId) => { void handlePackPreviewUninstall(packId); }} onUninstall={(packId) => { void handlePackUninstall(packId); }} /><HistoryPanel history={history} /></div>}
              {rightTab === 'simulation' && <div className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)', color: 'var(--color-text-muted)' }}><h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Simulation</h3><p className="mt-2">No simulation run is selected. Future View-plane saved views can attach what-if overlays here without mutating Spec or Graph records.</p></div>}
            </div>
          </aside>
        </div>

        <footer className="shrink-0 border-t p-3" style={{ borderColor: 'var(--color-border)' }} data-testid="ontology-bottom-series-panel">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Series / Time Context</h3><p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Selection: {selectionChipLabel(selection, selectedNamespace)} · Lens: {lens === 'spec' ? 'what can exist' : 'what exists'} · Draft and detail state stay local until saved.</p></div>
            <div className="grid grid-cols-3 gap-2 text-center text-xs"><span className="rounded-lg border px-3 py-2" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>Events: 0</span><span className="rounded-lg border px-3 py-2" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>Series: 0</span><span className="rounded-lg border px-3 py-2" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>Window: none</span></div>
          </div>
        </footer>
      </div>
    </div>
  );
}

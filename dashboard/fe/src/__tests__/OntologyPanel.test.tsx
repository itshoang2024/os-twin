import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import OntologyPanel from '@/components/knowledge/ontology/OntologyPanel';
import type { OntologyCandidate, OntologyProfile, OntologyUnit } from '@/hooks/use-ontology';
import type { EnterpriseMapProjectionData, ExplorerEdge, ExplorerNode } from '@/hooks/use-knowledge-explorer';

const toast = vi.fn();
const saveProfile = vi.fn();
const resetDefault = vi.fn();
const validateProfile = vi.fn();
const diffProfile = vi.fn();
const validatePack = vi.fn();
const installPack = vi.fn();
const uninstallPack = vi.fn();
const approveCandidate = vi.fn();
const mapCandidate = vi.fn();
const rejectCandidate = vi.fn();
const bulkUpdateCandidates = vi.fn();
const askAssistant = vi.fn();
const saveUnit = vi.fn();
const refreshUnit = vi.fn();

const refreshProfile = vi.fn();
const refreshSummary = vi.fn();

let profileExists = true;
let defaultSuggested = false;
let candidates: OntologyCandidate[] = [];
let installedPacks: Record<string, unknown> = {};
let historyRecords: Array<Record<string, unknown>> = [];
let profile: OntologyProfile | null;
let ontologyUnit: OntologyUnit | null = null;
let suggestedProfile: OntologyProfile | null = null;
const profileData = { validation_issues: [] };
const enterpriseMapState = vi.hoisted(() => ({
  map: null as EnterpriseMapProjectionData | null,
  explorerNodes: [] as ExplorerNode[],
  explorerEdges: [] as ExplorerEdge[],
  seed: vi.fn(),
}));

vi.mock('@/lib/stores/notificationStore', () => ({ useNotificationStore: (selector: (state: { addToast: typeof toast }) => unknown) => selector({ addToast: toast }) }));
vi.mock('@/hooks/use-knowledge-explorer', () => ({
  useEnterpriseMap: () => ({ map: enterpriseMapState.map, isLoading: false, error: null }),
  useKnowledgeExplorer: () => ({ nodes: enterpriseMapState.explorerNodes, edges: enterpriseMapState.explorerEdges, isSeeded: true, seed: enterpriseMapState.seed }),
}));

vi.mock('@/hooks/use-ontology', () => ({
  useOntologyProfile: () => ({ data: profileData, profile, suggestedProfile, profileExists, defaultSuggested, isLoading: false, error: null, saveProfile, resetDefault, refresh: refreshProfile }),
  useOntologyUnit: () => ({ unit: ontologyUnit, unitExists: Boolean(ontologyUnit), isLoading: false, error: null, saveUnit, refresh: refreshUnit }),
  useOntologyValidation: () => ({ validateProfile }),
  useOntologyHistory: () => ({ history: historyRecords, isLoading: false, error: null, refresh: vi.fn(), diffProfile, previewRollback: vi.fn() }),
  useOntologySummary: () => ({ summary: { concept_type_count: 1, relation_type_count: 1, alias_count: 1, candidate_count: candidates.length, validation_issue_count: 0, validation_issues: [] }, refresh: refreshSummary }),
  useOntologyPacks: () => ({ packs: [{ pack_id: 'technology-saas', name: 'Technology SaaS', version: '1.0.0', concept_types: { service: { id: 'service', label: 'Service' } }, relationship_types: { supports: { id: 'supports', label: 'Supports', family: 'dependency' } }, layers: { platform: { id: 'platform', label: 'Platform' } }, metadata_fields: { owner: { id: 'owner', label: 'Owner' } }, validation_rules: [{ id: 'service_owner' }], fixtures: [{ id: 'saas_fixture' }], migration_notes: ['Adds SaaS service vocabulary.'] }], installed: { installed_packs: installedPacks }, isLoading: false, error: null, validatePack, installPack, uninstallPack }),
  useOntologyCandidates: () => ({ candidates, isLoading: false, approveCandidate, mapCandidate, rejectCandidate, bulkUpdateCandidates }),
  useOntologyAssistant: () => ({ askAssistant }),
  useOntologyObservation: () => ({ events: [], series: [], isLoading: false, error: null, refresh: vi.fn() }),
}));

function makeProfile(): OntologyProfile {
  return {
    profile_id: 'enterprise_feature_map',
    namespace: 'demo',
    version: '1.0.0',
    concept_types: { feature: { id: 'feature', label: 'Feature', abstraction_level: 'feature', default_layer: 'product', metadata_schema: { owner: { id: 'owner', label: 'Owner' } }, color: '#7c3aed', shape: 'rectangle' } },
    relationship_types: { depends_on: { id: 'depends_on', label: 'Depends on', family: 'dependency', allowed_source_types: ['feature'], allowed_target_types: ['feature'], weight: 0.7, style: 'dashed' } },
    aliases: { requires: 'depends_on' },
    concept_aliases: { capability: 'feature' },
    validation_rules: [{ id: 'feature_required_fields', subject: 'concept_type', concept_type: 'feature', rule_type: 'metadata_schema', severity: 'warning' }],
    graph_instruction: { concept_type_defaults: { feature: { concept_type: 'feature', color: '#2563eb', shape: 'rounded_rectangle', label_template: '{label}', group: 'product', default_layer: 'product' } } },
    layers: { product: { id: 'product', label: 'Product' } },
    abstraction_levels: { feature: { id: 'feature', label: 'Feature' } },
    metadata_fields: { owner: { id: 'owner', label: 'Owner', field_type: 'string' } },
  };
}

function makeCandidate(): OntologyCandidate {
  return { id: 'cand-1', namespace: 'demo', candidate_type: 'relationship_type', source: 'extractor', original_label: 'Blocks', normalized_label: 'blocks', suggested_canonical: 'depends_on', confidence: 0.83, sample_text: 'Feature A blocks Feature B', status: 'pending', proposed_payload: { id: 'blocks', label: 'Blocks', family: 'dependency' }, source_evidence_ref: 'anchor-blocks', source_evidence: { anchor: { id: 'anchor-blocks', artifact_id: 'artifact-1', excerpt: 'Feature A blocks Feature B' }, artifact: { id: 'artifact-1', source_type: 'document', title: 'Roadmap notes' } }, created_at: new Date().toISOString() };
}

function openModelConfig(): void {
  fireEvent.click(screen.getByRole('button', { name: /Model Config/i }));
}

function openGovernance(): void {
  fireEvent.click(screen.getByRole('button', { name: /Governance/i }));
}

function makeDirtyProfile(): void {
  openModelConfig();
  fireEvent.change(screen.getByLabelText(/Canonical type label/i), { target: { value: 'Depends upon' } });
}

describe('OntologyPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const activeProfile = makeProfile();
    profile = activeProfile;
    suggestedProfile = null;
    ontologyUnit = null;
    profileExists = true;
    defaultSuggested = false;
    candidates = [];
    installedPacks = {};
    historyRecords = [];
    validateProfile.mockResolvedValue({ valid: true, issues: [] });
    diffProfile.mockResolvedValue({ namespace: 'demo', diff: { changed_paths: ['relationship_types.depends_on.label'] }, migration_issues: [], would_mutate: false });
    saveProfile.mockResolvedValue({});
    saveUnit.mockResolvedValue({ unit: { namespace: 'demo', lifecycle: 'draft' } });
    resetDefault.mockResolvedValue({});
    validatePack.mockResolvedValue({ namespace: 'demo', pack_id: 'technology-saas', valid: true, issues: [], profile: { ...activeProfile, concept_types: { ...activeProfile.concept_types, service: { id: 'service', label: 'Service' } } }, manifest: { pack_id: 'technology-saas', name: 'Technology SaaS', version: '1.0.0', migration_notes: ['Adds SaaS service vocabulary.'] } });
    installPack.mockResolvedValue({});
    askAssistant.mockResolvedValue({ text: 'Looks good.' });
    uninstallPack.mockResolvedValue({});
    approveCandidate.mockResolvedValue({});
    mapCandidate.mockResolvedValue({});
    rejectCandidate.mockResolvedValue({});
    bulkUpdateCandidates.mockResolvedValue({});
    refreshProfile.mockResolvedValue(undefined);
    refreshSummary.mockResolvedValue(undefined);
    refreshUnit.mockResolvedValue(undefined);
    enterpriseMapState.map = null;
    enterpriseMapState.explorerNodes = [];
    enterpriseMapState.explorerEdges = [];
  });

  it('starts cold namespaces in the Ontology Unit launcher instead of rendering the seed graph', () => {
    profileExists = false;
    defaultSuggested = true;
    profile = null;
    suggestedProfile = makeProfile();
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(screen.getByTestId('ontology-unit-launcher')).toBeInTheDocument();
    expect(screen.getByText(/Create Ontology Unit/i)).toBeInTheDocument();
    expect(screen.getByText(/No active ontology unit/i)).toBeInTheDocument();
    expect(screen.getByTestId('ontology-workbench-shell')).toBeInTheDocument();
    expect(screen.queryByTestId('ontology-schema-canvas')).not.toBeInTheDocument();
    expect(screen.getAllByText(/Preview seed template/i).length).toBeGreaterThan(0);
  });


  it('shows pack and blank template preview cards without installing a profile', async () => {
    profileExists = false;
    defaultSuggested = true;
    profile = null;
    suggestedProfile = makeProfile();
    render(<OntologyPanel selectedNamespace="demo" />);

    const gallery = screen.getByTestId('ontology-template-gallery');
    expect(within(gallery).getByText(/Blank profile/i)).toBeInTheDocument();
    expect(within(gallery).getByText(/Technology SaaS/i)).toBeInTheDocument();
    expect(within(gallery).getAllByText(/Template preview — not installed yet/i).length).toBeGreaterThanOrEqual(2);

    fireEvent.click(within(gallery).getByText(/Technology SaaS/i));
    expect(await screen.findByTestId('ontology-schema-canvas')).toBeInTheDocument();
    expect(screen.getAllByText(/Service/i).length).toBeGreaterThan(0);
    expect(saveProfile).not.toHaveBeenCalled();
    expect(resetDefault).not.toHaveBeenCalled();
  });

  it('starts blank as an empty local draft canvas with first-object guidance', async () => {
    profileExists = false;
    defaultSuggested = true;
    profile = null;
    suggestedProfile = makeProfile();
    render(<OntologyPanel selectedNamespace="demo" />);

    const gallery = screen.getByTestId('ontology-template-gallery');
    fireEvent.click(within(gallery).getByText(/Blank profile/i));

    expect(await screen.findByTestId('ontology-schema-canvas')).toBeInTheDocument();
    expect(screen.getByText(/Add your first object type/i)).toBeInTheDocument();
    expect(saveUnit).toHaveBeenCalledWith(expect.objectContaining({ namespace: 'demo', lifecycle: 'draft', active_profile_id: null }));
    expect(saveProfile).not.toHaveBeenCalled();
    expect(resetDefault).not.toHaveBeenCalled();
  });

  it('asks AI from the launcher as a staged proposal with candidate evidence context only', async () => {
    profileExists = false;
    defaultSuggested = true;
    profile = null;
    suggestedProfile = makeProfile();
    candidates = [makeCandidate()];
    askAssistant.mockResolvedValueOnce({ text: 'Starter proposal.\n```json\n{"proposed_changes":{"concept_types":{"risk":{"id":"risk","label":"Risk"}}},"evidence_refs":["anchor-blocks"]}\n```' });
    render(<OntologyPanel selectedNamespace="demo" />);

    fireEvent.click(screen.getByText(/Ask AI to draft/i));

    expect(await screen.findByTestId('ontology-assistant-proposals')).toBeInTheDocument();
    expect(screen.getByText(/Starter proposal/i)).toBeInTheDocument();
    await waitFor(() => expect(askAssistant).toHaveBeenCalledWith(expect.objectContaining({
      profile: expect.objectContaining({ status: 'draft', concept_types: {} }),
      context: expect.objectContaining({
        candidate_refs: [expect.objectContaining({ id: 'cand-1', proposed_payload: expect.objectContaining({ id: 'blocks' }), source_evidence_ref: 'anchor-blocks' })],
        evidence_refs: ['anchor-blocks'],
      }),
    })));
    expect(saveProfile).not.toHaveBeenCalled();
    expect(resetDefault).not.toHaveBeenCalled();
  });

  it('renders the seed graph only after the user explicitly previews the seed template', async () => {
    profileExists = false;
    defaultSuggested = true;
    profile = null;
    suggestedProfile = makeProfile();
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getAllByText(/Preview seed template/i)[0]);
    expect(await screen.findByTestId('ontology-schema-canvas')).toBeInTheDocument();
    expect(screen.getAllByText(/Ontology unit draft/i).length).toBeGreaterThan(0);
  });

  it('publishes first activation with active status after validate and diff preview', async () => {
    profileExists = false;
    defaultSuggested = true;
    profile = null;
    suggestedProfile = { ...makeProfile(), version: '0.1.0', status: 'draft' };
    ontologyUnit = { namespace: 'demo', active_profile_id: null, name: 'Flight Delay Template' };
    const { rerender } = render(<OntologyPanel selectedNamespace="demo" />);

    fireEvent.click(screen.getAllByText(/Preview seed template/i)[0]);
    expect(await screen.findByRole('button', { name: /Validate and save ontology profile/i })).toHaveTextContent(/Publish profile/i);
    expect(screen.getByTestId('ontology-profile-state-label')).toHaveTextContent(/Ontology unit draft\* · Unsaved draft/i);

    fireEvent.click(screen.getByRole('button', { name: /Validate and save ontology profile/i }));

    await waitFor(() => expect(saveProfile).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'active', version: '0.1.0' }),
      expect.objectContaining({ reason: 'Create ontology unit from seed template' }),
    ));
    expect(validateProfile).toHaveBeenCalledWith(expect.objectContaining({ status: 'active' }));
    expect(diffProfile).toHaveBeenCalledWith(expect.objectContaining({ status: 'active' }), undefined);
    expect(validateProfile.mock.invocationCallOrder[0]).toBeLessThan(diffProfile.mock.invocationCallOrder[0]);
    expect(diffProfile.mock.invocationCallOrder[0]).toBeLessThan(saveProfile.mock.invocationCallOrder[0]);
    expect(refreshUnit).toHaveBeenCalled();

    profileExists = true;
    profile = { ...suggestedProfile, status: 'active' };
    ontologyUnit = { namespace: 'demo', active_profile_id: 'enterprise_feature_map', name: 'Flight Delay Template' };
    rerender(<OntologyPanel selectedNamespace="demo" />);
    await waitFor(() => expect(screen.getByTestId('ontology-profile-state-label')).toHaveTextContent('Flight Delay Template · Active profile v0.1.0'));
  });

  it('labels active profile updates separately from first publish', () => {
    profile = { ...makeProfile(), version: '0.1.0', status: 'active' };
    ontologyUnit = { namespace: 'demo', active_profile_id: 'enterprise_feature_map', name: 'Flight Delay Template' };

    render(<OntologyPanel selectedNamespace="demo" />);

    expect(screen.getByTestId('ontology-profile-state-label')).toHaveTextContent('Flight Delay Template · Active profile v0.1.0');
    makeDirtyProfile();
    expect(screen.getByRole('button', { name: /Validate and save ontology profile/i })).toHaveTextContent(/Save profile update/i);
    expect(screen.getByTestId('ontology-profile-state-label')).toHaveTextContent(/Flight Delay Template\* · Unsaved draft/i);
  });

  it('blocks save when validation returns errors', async () => {
    validateProfile.mockResolvedValue({ valid: false, issues: [{ severity: 'error', code: 'BAD_ALIAS', path: 'aliases.requires', message: 'Alias target is invalid' }] });
    render(<OntologyPanel selectedNamespace="demo" />);
    makeDirtyProfile();
    fireEvent.click(screen.getByRole('button', { name: /Validate and save ontology profile/i }));
    await waitFor(() => expect(validateProfile).toHaveBeenCalled());
    expect(saveProfile).not.toHaveBeenCalled();
    expect(await screen.findByText(/Alias target is invalid/i)).toBeInTheDocument();
  });

  it('surfaces save errors after validation succeeds', async () => {
    saveProfile.mockRejectedValue(new Error('backend unavailable'));
    render(<OntologyPanel selectedNamespace="demo" />);
    makeDirtyProfile();
    fireEvent.click(screen.getByRole('button', { name: /Validate and save ontology profile/i }));
    await waitFor(() => expect(saveProfile).toHaveBeenCalled());
    expect(diffProfile).toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Save failed', message: 'backend unavailable' }));
  });

  it('installs and disables domain packs through lifecycle controls', async () => {
    const { rerender } = render(<OntologyPanel selectedNamespace="demo" />);
    openGovernance();
    fireEvent.click(screen.getByText('Preview install'));
    await waitFor(() => expect(validatePack).toHaveBeenCalledWith('technology-saas'));
    expect(await screen.findByTestId('ontology-pack-preview')).toHaveTextContent(/install preview/i);
    fireEvent.click(screen.getByText('Install'));
    await waitFor(() => expect(installPack).toHaveBeenCalledWith('technology-saas'));
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Domain pack installed' }));

    installedPacks = { 'technology-saas': { version: '1.0.0', status: 'installed', name: 'Technology SaaS', additions: { concept_types: ['service'], relationship_types: ['supports'], fixtures: ['saas_fixture'] } } };
    rerender(<OntologyPanel selectedNamespace="demo" />);
    openGovernance();
    fireEvent.click(screen.getByText('Preview disable'));
    expect(await screen.findByTestId('ontology-pack-preview')).toHaveTextContent(/uninstall preview/i);
    fireEvent.click(screen.getByText('Disable'));
    await waitFor(() => expect(uninstallPack).toHaveBeenCalledWith('technology-saas'));
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Domain pack disabled' }));
  });



  it('blocks invalid pack installation at validation preview', async () => {
    validatePack.mockResolvedValueOnce({ namespace: 'demo', pack_id: 'technology-saas', valid: false, issues: [{ severity: 'error', code: 'ALIAS_CONFLICT', path: 'aliases.requires', message: 'Alias conflict', subject: 'pack', suggested_fix: 'Rename alias', metadata: {} }], profile: null, manifest: { pack_id: 'technology-saas', name: 'Technology SaaS', version: '1.0.0', migration_notes: [] } });
    render(<OntologyPanel selectedNamespace="demo" />);
    openGovernance();
    fireEvent.click(screen.getByText('Preview install'));
    expect(await screen.findByText(/Alias conflict/i)).toBeInTheDocument();
    expect(screen.getByText('Install')).toBeDisabled();
    expect(installPack).not.toHaveBeenCalled();
  });

  it('previews dangerous profile diffs and requires override metadata before publish', async () => {
    diffProfile.mockResolvedValue({
      namespace: 'demo',
      diff: { removed: ['relationship_types.depends_on'] },
      migration_issues: [{ severity: 'error', code: 'RELATION_REMOVED', message: 'Existing edges use depends_on' }],
      would_mutate: false,
    });
    render(<OntologyPanel selectedNamespace="demo" />);
    makeDirtyProfile();

    fireEvent.click(screen.getByText(/Preview diff/i));
    expect(await screen.findByText(/Profile diff and migration safety preview/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Override ticket/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Approved by/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Validate and save ontology profile/i }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Migration override required' })));
    expect(saveProfile).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Override ticket/i), { target: { value: 'RISK-123' } });
    fireEvent.change(screen.getByLabelText(/Approved by/i), { target: { value: 'qa-lead' } });
    fireEvent.change(screen.getByLabelText(/^Reason$/i), { target: { value: 'Approved migration override' } });
    fireEvent.click(screen.getByRole('button', { name: /Validate and save ontology profile/i }));

    await waitFor(() => expect(saveProfile).toHaveBeenCalledWith(expect.any(Object), expect.objectContaining({
      reason: 'Approved migration override',
      validation_override: { ticket: 'RISK-123', approved_by: 'qa-lead', reason: 'Approved migration override', previewed: true },
    })));
  });

  it('renders the workbench shell, canvas, docks, and bottom series panel', () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(screen.getByTestId('ontology-workbench-top-rail')).toBeInTheDocument();
    expect(screen.getByTestId('ontology-left-dock')).toBeInTheDocument();
    expect(screen.getByTestId('ontology-central-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('ontology-right-dock')).toBeInTheDocument();
    expect(screen.getByTestId('ontology-bottom-series-panel')).toBeInTheDocument();
    expect(screen.getByTestId('ontology-schema-canvas')).toBeInTheDocument();
    expect(screen.getByLabelText(/Ontology scope selector/i)).toBeInTheDocument();
  });




  it('shows pack ownership badges for installed schema objects', async () => {
    installedPacks = { 'technology-saas': { version: '1.0.0', status: 'installed', name: 'Technology SaaS', additions: { concept_types: ['feature'] } } };
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(await screen.findByTestId('schema-pack-origin')).toHaveTextContent(/Technology SaaS/i);
  });

  it('opens a full Object Workbench for selected concept types and edits identity plus rendering through GraphInstruction', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(await screen.findByTestId('object-workbench')).toBeInTheDocument();
    expect(screen.getByText(/Complete draft workspace/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Object label/i), { target: { value: 'Roadmap Feature' } });
    fireEvent.change(screen.getByLabelText(/Object lifecycle state/i), { target: { value: 'active' } });
    fireEvent.change(screen.getByLabelText(/Rendering shape/i), { target: { value: 'diamond' } });
    fireEvent.change(screen.getByLabelText(/Rendering label template/i), { target: { value: '{label} card' } });
    fireEvent.click(screen.getByText(/Preview diff/i));

    await waitFor(() => expect(diffProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        concept_types: expect.objectContaining({ feature: expect.objectContaining({ label: 'Roadmap Feature', lifecycle_state: 'active' }) }),
        graph_instruction: expect.objectContaining({
          concept_type_defaults: expect.objectContaining({ feature: expect.objectContaining({ shape: 'diamond', label_template: '{label} card' }) }),
        }),
      }),
      expect.any(Object),
    ));
    expect(screen.getByTestId('object-workbench-preview')).toHaveTextContent('Roadmap Feature card');
  });

  it('edits object properties, relationship constraints, aliases, and scoped rules in the draft', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(await screen.findByTestId('object-workbench')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Property owner label/i), { target: { value: 'DRI' } });
    fireEvent.change(screen.getByLabelText(/Property owner type/i), { target: { value: 'enum' } });
    fireEvent.change(screen.getByLabelText(/Property owner allowed values/i), { target: { value: 'alice, bob' } });
    fireEvent.click(screen.getByLabelText(/depends_on allows target feature/i));
    fireEvent.change(screen.getByLabelText(/Concept alias capability/i), { target: { value: 'product capability' } });
    fireEvent.click(screen.getByText(/Add rule/i));
    fireEvent.click(screen.getByText(/Preview diff/i));

    await waitFor(() => expect(diffProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata_fields: expect.objectContaining({ owner: expect.objectContaining({ label: 'DRI', field_type: 'enum', allowed_values: ['alice', 'bob'] }) }),
        relationship_types: expect.objectContaining({ depends_on: expect.objectContaining({ allowed_target_types: [] }) }),
        concept_aliases: expect.objectContaining({ 'product capability': 'feature' }),
        validation_rules: expect.arrayContaining([expect.objectContaining({ concept_type: 'feature' })]),
      }),
      expect.any(Object),
    ));
  });


  it('stages assistant proposed_changes before applying them to the governed draft', async () => {
    askAssistant.mockResolvedValue({
      text: 'Add a risk concept for review.\n```json\n{"proposed_changes":{"concept_types":{"risk":{"id":"risk","label":"Risk","description":"Potential adverse outcome."}}},"rationale":"Selected evidence describes risks.","evidence_refs":["anchor-risk"]}\n```',
    });
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /AI co-builder/i }));
    fireEvent.change(screen.getByLabelText(/Ask ontology co-builder/i), { target: { value: 'Build starter risk ontology' } });
    fireEvent.click(screen.getByRole('button', { name: /^Ask assistant$/i }));

    expect(await screen.findByTestId('ontology-assistant-proposals')).toBeInTheDocument();
    expect(screen.getByText(/Add a risk concept for review/i)).toBeInTheDocument();
    expect(screen.getByText(/anchor-risk/i)).toBeInTheDocument();
    expect(askAssistant).toHaveBeenCalledWith(expect.objectContaining({
      message: 'Build starter risk ontology',
      context: expect.objectContaining({ scope: expect.any(Object), evidence_refs: expect.any(Array) }),
    }));

    fireEvent.click(screen.getByText(/Apply to Draft/i));
    fireEvent.click(screen.getAllByText(/Preview Diff/i).at(-1)!);
    await waitFor(() => expect(diffProfile).toHaveBeenCalledWith(
      expect.objectContaining({ concept_types: expect.objectContaining({ risk: expect.objectContaining({ label: 'Risk' }) }) }),
      expect.any(Object),
    ));
  });

  it('shows invalid assistant JSON without applying proposed changes', async () => {
    askAssistant.mockResolvedValue({ text: 'Use this cautiously.\n```json\n{"proposed_changes": { invalid }\n```' });
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /AI co-builder/i }));
    fireEvent.change(screen.getByLabelText(/Ask ontology co-builder/i), { target: { value: 'bad proposal' } });
    fireEvent.click(screen.getByRole('button', { name: /^Ask assistant$/i }));

    expect(await screen.findByText(/JSON parse failed/i)).toBeInTheDocument();
    expect(screen.getByText(/Use this cautiously/i)).toBeInTheDocument();
    expect(diffProfile).not.toHaveBeenCalledWith(expect.objectContaining({ concept_types: expect.objectContaining({ risk: expect.any(Object) }) }), expect.anything());
  });

  it('marks proposal cards as applied, validated, diffed, saved, and discarded through governed actions', async () => {
    askAssistant.mockResolvedValue({
      text: 'Add a risk concept for review.\n```json\n{"proposed_changes":{"concept_types":{"risk":{"id":"risk","label":"Risk"}}},"rationale":"Reviewable only.","evidence_refs":["anchor-risk"]}\n```',
    });
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /AI co-builder/i }));
    fireEvent.change(screen.getByLabelText(/Ask ontology co-builder/i), { target: { value: 'Build starter risk ontology' } });
    fireEvent.click(screen.getByRole('button', { name: /^Ask assistant$/i }));

    const panel = await screen.findByTestId('ontology-assistant-proposals');
    const proposal = within(panel);
    expect(proposal.getByText('suggested')).toBeInTheDocument();

    fireEvent.click(proposal.getByText(/Apply to Draft/i));
    expect(proposal.getByText('applied')).toBeInTheDocument();

    fireEvent.click(proposal.getByText(/^Validate$/i));
    await waitFor(() => expect(validateProfile).toHaveBeenCalled());
    expect(proposal.getByText('validated')).toBeInTheDocument();

    fireEvent.click(proposal.getByText(/Preview Diff/i));
    await waitFor(() => expect(diffProfile).toHaveBeenCalledWith(
      expect.objectContaining({ concept_types: expect.objectContaining({ risk: expect.objectContaining({ label: 'Risk' }) }) }),
      expect.any(Object),
    ));
    expect(proposal.getByText('diffed')).toBeInTheDocument();

    fireEvent.click(proposal.getByText(/^Save$/i));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledWith(
      expect.objectContaining({ concept_types: expect.objectContaining({ risk: expect.objectContaining({ label: 'Risk' }) }) }),
      expect.any(Object),
    ));
    expect(proposal.getByText('saved')).toBeInTheDocument();

    fireEvent.click(proposal.getByText(/^Discard$/i));
    expect(proposal.getByText('discarded')).toBeInTheDocument();
  });


  it('keeps Search Around direction, family, and depth as temporary visual state', () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /Search/i }));

    expect(screen.getByTestId('ontology-search-around-controls')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Search around direction/i), { target: { value: 'incoming' } });
    fireEvent.change(screen.getByLabelText(/Search around relationship family/i), { target: { value: 'dependency' } });
    fireEvent.change(screen.getByLabelText(/Search around depth/i), { target: { value: '3' } });

    expect(screen.getByLabelText(/Search around direction/i)).toHaveValue('incoming');
    expect(screen.getByLabelText(/Search around relationship family/i)).toHaveValue('dependency');
    expect(screen.getByText(/Depth 3/i)).toBeInTheDocument();
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it('saves grouping, layout, styling, and selected nodes into GraphInstruction draft only after explicit View-plane action', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    openModelConfig();

    expect(screen.getByTestId('ontology-visual-controls')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Group by dimension/i), { target: { value: 'owner' } });
    fireEvent.change(screen.getByLabelText(/Color by dimension/i), { target: { value: 'validation_state' } });
    fireEvent.change(screen.getByLabelText(/Style property selector/i), { target: { value: 'quality_state' } });
    fireEvent.click(screen.getByRole('button', { name: /Dependency flow/i }));

    expect(saveProfile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Save to View-plane draft/i }));
    fireEvent.click(screen.getAllByText(/Preview diff/i).at(0)!);

    await waitFor(() => expect(diffProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        graph_instruction: expect.objectContaining({
          default_lane_dimension: 'owner',
          layout_hints: expect.objectContaining({ mode: 'dependency-flow', color_by: 'validation_state' }),
          default_views: expect.arrayContaining([expect.objectContaining({ id: 'ontology_visual_analysis', lane_dimension: 'owner', color_by: 'validation_state', style_property: 'quality_state' })]),
          concept_type_defaults: expect.objectContaining({ feature: expect.objectContaining({ concept_type: 'feature' }) }),
          relationship_type_defaults: expect.objectContaining({ depends_on: expect.objectContaining({ relationship_type: 'depends_on', group: 'dependency' }) }),
        }),
      }),
      expect.any(Object),
    ));
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it('renders actionable histogram rows with counts, selected counts, filter to, filter out, and clear', () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByRole('button', { name: /Histogram/i }));
    const histogram = screen.getByTestId('ontology-left-histogram');
    expect(within(histogram).getAllByText('Feature').length).toBeGreaterThan(0);
    expect(within(histogram).getAllByText(/selected 0/i).length).toBeGreaterThan(0);

    fireEvent.click(within(histogram).getAllByText(/Filter to/i)[0]);
    expect(within(histogram).getByText(/selected 1/i)).toBeInTheDocument();
    fireEvent.click(within(histogram).getAllByText(/Filter out/i)[0]);
    fireEvent.click(within(histogram).getByText(/Clear/i));
    expect(within(histogram).getAllByText(/selected 0/i).length).toBeGreaterThan(0);
  });


  it('switches between Spec Lens and Map Lens while preserving unsaved draft edits', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.change(screen.getByLabelText(/Object label/i), { target: { value: 'Roadmap Feature' } });
    expect(saveProfile).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'map' } });
    expect(await screen.findByTestId('enterprise-map-panel')).toBeInTheDocument();
    expect(screen.getByTestId('enterprise-map-example-banner')).toHaveTextContent(/Examples only/i);
    expect(screen.getAllByText(/Example Roadmap Feature/i).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'spec' } });
    expect(await screen.findByTestId('ontology-schema-canvas')).toBeInTheDocument();
    expect(screen.getByLabelText(/Object label/i)).toHaveValue('Roadmap Feature');
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it('uses the shared selection chip to filter Map Lens by selected concept type and clear scope', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.change(screen.getByLabelText(/Ontology scope selector/i), { target: { value: 'concept:feature' } });
    expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Type · Feature/i);

    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'map' } });
    expect(await screen.findByTestId('enterprise-map-concept-filter')).toHaveTextContent(/Feature/i);
    expect(screen.getAllByText(/Example Feature/i).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: /Clear ontology selection/i }));
    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Namespace · demo/i));

    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'spec' } });
    expect(await screen.findByTestId('ontology-schema-canvas')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Namespace · demo/i));
  });

  it('syncs selected map instances back to the Object Workbench concept type', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'map' } });
    const exampleButtons = await screen.findAllByRole('button', { name: /^Select Example Feature$/i });
    expect(exampleButtons).toHaveLength(1);
    fireEvent.click(exampleButtons[0]);

    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Instance · Example Feature · Example/i));
    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'spec' } });
    expect(screen.getByLabelText(/Object label/i)).toHaveValue('Feature');
  });



  it('clears browser-runtime selection from pointer events without reselecting a concept', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.change(screen.getByLabelText(/Object label/i), { target: { value: 'QA Draft Domain' } });
    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'map' } });
    expect(await screen.findByTestId('enterprise-map-panel')).toBeInTheDocument();
    expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Type · QA Draft Domain/i);

    const clearButton = screen.getByRole('button', { name: /Clear ontology selection/i });
    fireEvent.pointerDown(clearButton);

    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Namespace · demo/i));
    expect(screen.queryByTestId('enterprise-map-concept-filter')).not.toBeInTheDocument();
  });

  it('syncs map example instances from browser-native pointer and click events into the shared chip and Object Workbench', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.change(screen.getByLabelText(/Object label/i), { target: { value: 'QA Draft Domain' } });
    fireEvent.change(screen.getByLabelText(/Workbench lens/i), { target: { value: 'map' } });
    const exampleButton = (await screen.findAllByRole('button', { name: /^Select Example QA Draft Domain$/i }))[0];

    fireEvent.mouseDown(exampleButton);
    fireEvent.mouseUp(exampleButton);
    fireEvent.click(exampleButton);

    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Instance · Example QA Draft Domain · Example/i));
    expect(screen.getByLabelText(/Object label/i)).toHaveValue('QA Draft Domain');

    fireEvent.click(screen.getByRole('button', { name: /Clear ontology selection/i }));
    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Namespace · demo/i));
    const namespaceExampleButton = screen.getByRole('button', { name: /^Select Example QA Draft Domain$/i });
    fireEvent.click(namespaceExampleButton);
    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Instance · Example QA Draft Domain · Example/i));

    fireEvent.click(screen.getByRole('button', { name: /Clear ontology selection/i }));
    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Namespace · demo/i));
    const graphHitTarget = screen.getByRole('button', { name: /Select Example QA Draft Domain\. 1 observation events\./i });
    fireEvent.click(graphHitTarget);
    await waitFor(() => expect(screen.getByTestId('ontology-selection-chip')).toHaveTextContent(/Instance · Example QA Draft Domain · Example/i));
  });

  it('stages candidate map and approval in local draft before reject operations persist review state', async () => {
    candidates = [makeCandidate()];
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(screen.getByText('Blocks')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Map'));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Candidate map staged in draft' })));
    expect(mapCandidate).not.toHaveBeenCalled();
    expect(approveCandidate).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: /^Preview diff$/i })[0]);
    await waitFor(() => expect(diffProfile).toHaveBeenCalledWith(expect.objectContaining({ aliases: expect.objectContaining({ blocks: 'depends_on' }) }), expect.any(Object)));

    fireEvent.click(screen.getByText('Approve'));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Candidate staged in draft' })));
    expect(approveCandidate).not.toHaveBeenCalled();
    expect(mapCandidate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('Reject'));
    await waitFor(() => expect(rejectCandidate).toHaveBeenCalledWith('cand-1', 'Rejected from Ontology UI'));
    fireEvent.click(screen.getAllByLabelText(/Select Blocks/i).find((element) => element instanceof HTMLInputElement) as HTMLElement);
    fireEvent.click(screen.getByText(/Reject selected/i));
    await waitFor(() => expect(bulkUpdateCandidates).toHaveBeenCalledWith([{ candidate_id: 'cand-1', action: 'reject', reason: 'Bulk rejected from Ontology UI' }]));
  });
  it('renders graph diff overlay and schema history separate from observation events', async () => {
    diffProfile.mockResolvedValueOnce({
      namespace: 'demo',
      diff: { added: { concept_types: ['service'] }, removed: { relationship_types: ['blocks'] }, changed: { graph_instruction: ['default_views'] }, changed_paths: ['concept_types.service', 'relationship_types.blocks', 'graph_instruction.default_views'] },
      migration_issues: [],
      would_mutate: false,
    });
    historyRecords = [{
      id: 'hist-1',
      namespace: 'demo',
      actor: 'po@example.com',
      timestamp: new Date().toISOString(),
      reason: 'Governed schema update',
      previous_version: '1.0.0',
      new_version: '1.1.0',
      changed_paths: ['concept_types.service', 'graph_instruction.default_views'],
      diff: { added: { concept_types: ['service'] }, changed: { graph_instruction: ['default_views'] } },
      migration_issues: [],
      validation_override: null,
      migration_entries: [],
    }];
    render(<OntologyPanel selectedNamespace="demo" />);
    makeDirtyProfile();
    fireEvent.click(screen.getByText(/Preview diff/i));
    expect(await screen.findByTestId('ontology-graph-diff-overlay')).toHaveTextContent(/ADDED · Nodes: service/i);
    expect(screen.getByTestId('ontology-graph-diff-overlay')).toHaveTextContent(/REMOVED · Edges: blocks/i);

    openGovernance();
    expect(await screen.findByTestId('ontology-history-panel')).toHaveTextContent(/Governed schema update/i);
    expect(screen.getByTestId('ontology-history-panel')).toHaveTextContent(/observation_events remain operational telemetry/i);
  });

  it('keeps object and assistant draft edits in local undo and redo stacks', async () => {
    askAssistant.mockResolvedValueOnce({ text: '```json\n{ "proposed_changes": { "concept_types": { "service": { "id": "service", "label": "Service", "abstraction_level": "feature" } } } }\n```' });
    render(<OntologyPanel selectedNamespace="demo" />);

    fireEvent.change(screen.getByLabelText(/Object label/i), { target: { value: 'Roadmap Feature' } });
    expect(screen.getByText(/Unsaved draft/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Undo$/i }));
    await waitFor(() => expect(screen.queryByText(/Unsaved draft/i)).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /^Redo$/i }));
    expect(await screen.findByText(/Unsaved draft/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /AI co-builder/i }));
    fireEvent.change(screen.getByLabelText(/Ask ontology co-builder/i), { target: { value: 'Add service type' } });
    fireEvent.click(screen.getByText(/Ask assistant/i));
    await waitFor(() => expect(askAssistant).toHaveBeenCalled());
    fireEvent.click(await screen.findByText(/Apply to draft/i));
    expect(saveProfile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /^Undo$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^Redo$/i }));
    fireEvent.click(screen.getAllByRole('button', { name: /^Preview diff$/i })[0]);
    await waitFor(() => expect(diffProfile).toHaveBeenCalled());
  });

  it('clears local undo and redo stacks after governed save succeeds', async () => {
    render(<OntologyPanel selectedNamespace="demo" />);

    fireEvent.change(screen.getByLabelText(/Object label/i), { target: { value: 'Roadmap Feature' } });
    expect(screen.getByRole('button', { name: /^Undo$/i })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: /^Undo$/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Redo$/i })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /^Redo$/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Undo$/i })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: /Validate and save ontology profile/i }));

    await waitFor(() => expect(saveProfile).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: /^Undo$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^Redo$/i })).toBeDisabled();
  });

  it('clears local undo and redo stacks after reset refreshes the saved profile', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<OntologyPanel selectedNamespace="demo" />);

    fireEvent.change(screen.getByLabelText(/Object label/i), { target: { value: 'Roadmap Feature' } });
    fireEvent.click(screen.getByRole('button', { name: /^Undo$/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Redo$/i })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: /Reset to default/i }));

    await waitFor(() => expect(resetDefault).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: /^Undo$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^Redo$/i })).toBeDisabled();
    confirm.mockRestore();
  });

});

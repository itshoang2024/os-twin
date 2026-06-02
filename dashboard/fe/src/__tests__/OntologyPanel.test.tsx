import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import OntologyPanel from '@/components/knowledge/ontology/OntologyPanel';
import type { OntologyCandidate, OntologyProfile } from '@/hooks/use-ontology';

const toast = vi.fn();
const saveProfile = vi.fn();
const resetDefault = vi.fn();
const validateProfile = vi.fn();
const diffProfile = vi.fn();
const installPack = vi.fn();
const uninstallPack = vi.fn();
const approveCandidate = vi.fn();
const mapCandidate = vi.fn();
const rejectCandidate = vi.fn();
const bulkUpdateCandidates = vi.fn();

const refreshProfile = vi.fn();
const refreshSummary = vi.fn();

let profileExists = true;
let defaultSuggested = false;
let candidates: OntologyCandidate[] = [];
let installedPacks: Record<string, unknown> = {};
let profile: OntologyProfile;
const profileData = { validation_issues: [] };

vi.mock('@/lib/stores/notificationStore', () => ({ useNotificationStore: (selector: (state: { addToast: typeof toast }) => unknown) => selector({ addToast: toast }) }));
vi.mock('@/hooks/use-ontology', () => ({
  useOntologyProfile: () => ({ data: profileData, profile, profileExists, defaultSuggested, isLoading: false, error: null, saveProfile, resetDefault, refresh: refreshProfile }),
  useOntologyValidation: () => ({ validateProfile }),
  useOntologyHistory: () => ({ history: [], isLoading: false, error: null, refresh: vi.fn(), diffProfile, previewRollback: vi.fn() }),
  useOntologySummary: () => ({ summary: { concept_type_count: 1, relation_type_count: 1, alias_count: 1, candidate_count: candidates.length, validation_issue_count: 0, validation_issues: [] }, refresh: refreshSummary }),
  useOntologyPacks: () => ({ packs: [{ pack_id: 'technology-saas', name: 'Technology SaaS', version: '1.0.0' }], installed: { installed_packs: installedPacks }, isLoading: false, error: null, installPack, uninstallPack }),
  useOntologyCandidates: () => ({ candidates, isLoading: false, approveCandidate, mapCandidate, rejectCandidate, bulkUpdateCandidates }),
}));

function makeProfile(): OntologyProfile {
  return {
    profile_id: 'enterprise_feature_map',
    namespace: 'demo',
    version: '1.0.0',
    concept_types: { feature: { id: 'feature', label: 'Feature', abstraction_level: 'feature', default_layer: 'product', metadata_schema: { owner: { id: 'owner', label: 'Owner' } }, color: '#7c3aed', shape: 'rectangle' } },
    relationship_types: { depends_on: { id: 'depends_on', label: 'Depends on', family: 'dependency', allowed_source_types: ['feature'], allowed_target_types: ['feature'], weight: 0.7, style: 'dashed' } },
    aliases: { requires: 'depends_on' },
    layers: { product: { id: 'product', label: 'Product' } },
    abstraction_levels: { feature: { id: 'feature', label: 'Feature' } },
    metadata_fields: { owner: { id: 'owner', label: 'Owner', field_type: 'string' } },
  };
}

function makeCandidate(): OntologyCandidate {
  return { id: 'cand-1', namespace: 'demo', candidate_type: 'relationship_type', source: 'extractor', original_label: 'Blocks', normalized_label: 'blocks', suggested_canonical: 'depends_on', confidence: 0.83, sample_text: 'Feature A blocks Feature B', status: 'pending', created_at: new Date().toISOString() };
}

function makeDirtyProfile(): void {
  fireEvent.change(screen.getByLabelText(/Canonical type label/i), { target: { value: 'Depends upon' } });
}

describe('OntologyPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    profile = makeProfile();
    profileExists = true;
    defaultSuggested = false;
    candidates = [];
    installedPacks = {};
    validateProfile.mockResolvedValue({ valid: true, issues: [] });
    diffProfile.mockResolvedValue({ namespace: 'demo', diff: { changed_paths: ['relationship_types.depends_on.label'] }, migration_issues: [], would_mutate: false });
    saveProfile.mockResolvedValue({});
    resetDefault.mockResolvedValue({});
    installPack.mockResolvedValue({});
    uninstallPack.mockResolvedValue({});
    approveCandidate.mockResolvedValue({});
    mapCandidate.mockResolvedValue({});
    rejectCandidate.mockResolvedValue({});
    bulkUpdateCandidates.mockResolvedValue({});
    refreshProfile.mockResolvedValue(undefined);
    refreshSummary.mockResolvedValue(undefined);
  });

  it('shows a bootstrap action when no active profile exists', () => {
    profileExists = false;
    defaultSuggested = true;
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(screen.getByText(/Create default ontology profile/i)).toBeInTheDocument();
    expect(screen.getByText(/no active ontology profile/i)).toBeInTheDocument();
  });

  it('blocks save when validation returns errors', async () => {
    validateProfile.mockResolvedValue({ valid: false, issues: [{ severity: 'error', code: 'BAD_ALIAS', path: 'aliases.requires', message: 'Alias target is invalid' }] });
    render(<OntologyPanel selectedNamespace="demo" />);
    makeDirtyProfile();
    fireEvent.click(screen.getByText(/Validate & save/i));
    await waitFor(() => expect(validateProfile).toHaveBeenCalled());
    expect(saveProfile).not.toHaveBeenCalled();
    expect(await screen.findByText(/Alias target is invalid/i)).toBeInTheDocument();
  });

  it('surfaces save errors after validation succeeds', async () => {
    saveProfile.mockRejectedValue(new Error('backend unavailable'));
    render(<OntologyPanel selectedNamespace="demo" />);
    makeDirtyProfile();
    fireEvent.click(screen.getByText(/Validate & save/i));
    await waitFor(() => expect(saveProfile).toHaveBeenCalled());
    expect(diffProfile).toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Save failed', message: 'backend unavailable' }));
  });

  it('installs and disables domain packs through lifecycle controls', async () => {
    const { rerender } = render(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByText('Install'));
    await waitFor(() => expect(installPack).toHaveBeenCalledWith('technology-saas'));
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Domain pack installed' }));

    installedPacks = { 'technology-saas': { version: '1.0.0' } };
    rerender(<OntologyPanel selectedNamespace="demo" />);
    fireEvent.click(screen.getByText('Disable'));
    await waitFor(() => expect(uninstallPack).toHaveBeenCalledWith('technology-saas'));
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Domain pack disabled' }));
  });

  it('previews dangerous profile diffs and requires override metadata before save', async () => {
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

    fireEvent.click(screen.getByText(/Validate & save/i));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Migration override required' })));
    expect(saveProfile).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Override ticket/i), { target: { value: 'RISK-123' } });
    fireEvent.change(screen.getByLabelText(/Approved by/i), { target: { value: 'qa-lead' } });
    fireEvent.change(screen.getByLabelText(/^Reason$/i), { target: { value: 'Approved migration override' } });
    fireEvent.click(screen.getByText(/Validate & save/i));

    await waitFor(() => expect(saveProfile).toHaveBeenCalledWith(expect.any(Object), expect.objectContaining({
      reason: 'Approved migration override',
      validation_override: { ticket: 'RISK-123', approved_by: 'qa-lead', reason: 'Approved migration override', previewed: true },
    })));
  });

  it('maps, approves, rejects, and bulk rejects candidates', async () => {
    candidates = [makeCandidate()];
    render(<OntologyPanel selectedNamespace="demo" />);
    expect(screen.getByText('Blocks')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Map'));
    await waitFor(() => expect(mapCandidate).toHaveBeenCalledWith('cand-1', 'depends_on'));
    fireEvent.click(screen.getByText('Approve'));
    await waitFor(() => expect(approveCandidate).toHaveBeenCalled());
    fireEvent.click(screen.getByText('Reject'));
    await waitFor(() => expect(rejectCandidate).toHaveBeenCalledWith('cand-1', 'Rejected from Ontology UI'));
    fireEvent.click(screen.getByLabelText(/Select Blocks/i));
    fireEvent.click(screen.getByText(/Reject selected/i));
    await waitFor(() => expect(bulkUpdateCandidates).toHaveBeenCalledWith([{ candidate_id: 'cand-1', action: 'reject', reason: 'Bulk rejected from Ontology UI' }]));
  });
});

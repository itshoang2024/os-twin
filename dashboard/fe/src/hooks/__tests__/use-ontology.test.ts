import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';
import {
  useOntologyCandidates,
  useOntologyPacks,
  useOntologyProfile,
  useOntologyUnit,
  useOntologySummary,
  useOntologyValidation,
} from '../use-ontology';
import type { DomainPackManifest, OntologyCandidate, OntologyProfile } from '../use-ontology';

vi.mock('@/lib/api-client', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));

import { apiPost, apiPut } from '@/lib/api-client';

const mockApiPost = apiPost as ReturnType<typeof vi.fn>;
const mockApiPut = apiPut as ReturnType<typeof vi.fn>;

const profile: OntologyProfile = {
  profile_id: 'enterprise_feature_map',
  namespace: 'demo',
  version: '1.0.0',
  concept_types: {},
  relationship_types: {},
  aliases: {},
  layers: {},
  abstraction_levels: {},
  metadata_fields: {},
};

const pendingCandidate: OntologyCandidate = {
  id: 'cand-1',
  namespace: 'demo',
  candidate_type: 'relationship_type',
  source: 'extractor',
  original_label: 'Blocks',
  normalized_label: 'blocks',
  suggested_canonical: 'depends_on',
  confidence: 0.83,
  sample_text: 'Feature A blocks Feature B',
  status: 'pending',
  created_at: '2026-06-01T00:00:00Z',
};

function swrWrapper(fetcher: (key: string) => Promise<unknown>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      SWRConfig,
      { value: { provider: () => new Map(), fetcher, dedupingInterval: 0, shouldRetryOnError: false } },
      children,
    );
  };
}

describe('ontology hooks', () => {
  beforeEach(() => vi.clearAllMocks());

  it('loads a no-profile bootstrap payload from the ontology profile API', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      namespace: 'demo',
      profile: null,
      profile_exists: false,
      default_suggested: true,
      default_profile: profile,
      validation_issues: [],
    });

    const { result } = renderHook(() => useOntologyProfile('demo'), { wrapper: swrWrapper(fetcher) });

    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(fetcher).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/profile');
    expect(result.current.profileExists).toBe(false);
    expect(result.current.defaultSuggested).toBe(true);
    expect(result.current.profile).toBeNull();
    expect(result.current.suggestedProfile).toEqual(profile);
  });

  it('surfaces ontology profile loading errors without retrying', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('profile unavailable'));

    const { result } = renderHook(() => useOntologyProfile('demo'), { wrapper: swrWrapper(fetcher) });

    await waitFor(() => expect(result.current.error).toContain('profile unavailable'));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.profile).toBeNull();
  });

  it('loads ontology summary counters from the summary API', async () => {
    const summary = {
      namespace: 'demo',
      profile_exists: true,
      profile_id: 'enterprise_feature_map',
      version: '1.0.0',
      concept_type_count: 3,
      relation_type_count: 4,
      alias_count: 2,
      candidate_count: 1,
      validation_issue_count: 0,
      validation_issues: [],
    };
    const fetcher = vi.fn().mockResolvedValue(summary);

    const { result } = renderHook(() => useOntologySummary('demo'), { wrapper: swrWrapper(fetcher) });

    await waitFor(() => expect(result.current.summary).toEqual(summary));
    expect(fetcher).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/summary');
    expect(result.current.error).toBeNull();
  });

  it('loads available and installed ontology packs from backend APIs', async () => {
    const technologyPack: DomainPackManifest = {
      pack_id: 'technology-saas',
      name: 'Technology SaaS',
      version: '1.0.0',
      concept_types: { service: { id: 'service', label: 'Service', default_layer: 'delivery' } },
      relationship_types: { depends_on: { id: 'depends_on', label: 'Depends on', map_direction: 'reversed' } },
      layers: { delivery: { id: 'delivery', label: 'Delivery', order: 2 } },
      abstraction_levels: { implementation: { id: 'implementation', label: 'Implementation', order: 3 } },
      graph_instruction: {
        default_views: [{ id: 'technology_map', label: 'Technology Map' }],
        relationship_type_defaults: { depends_on: { relationship_type: 'depends_on', map_direction: 'reversed' } },
      },
    };
    const fetcher = vi.fn(async (key: string) => {
      if (key === '/knowledge/ontology/packs') {
        return { packs: [technologyPack] };
      }
      if (key === '/knowledge/namespaces/demo/ontology/packs') {
        return { namespace: 'demo', schema_version: 1, installed_packs: { 'technology-saas': { version: '1.0.0' } } };
      }
      throw new Error(`unexpected key ${key}`);
    });

    const { result } = renderHook(() => useOntologyPacks('demo'), { wrapper: swrWrapper(fetcher) });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fetcher).toHaveBeenCalledWith('/knowledge/ontology/packs');
    expect(fetcher).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/packs');
    expect(result.current.packs).toHaveLength(1);
    expect(result.current.packs[0].layers?.delivery?.id).toBe('delivery');
    expect(result.current.packs[0].abstraction_levels?.implementation?.id).toBe('implementation');
    expect(result.current.packs[0].relationship_types?.depends_on?.map_direction).toBe('reversed');
    expect(result.current.packs[0].graph_instruction?.default_views?.[0].id).toBe('technology_map');
    expect(result.current.packs[0].graph_instruction?.relationship_type_defaults?.depends_on?.map_direction).toBe('reversed');
    expect(result.current.installed?.installed_packs).toHaveProperty('technology-saas');
  });

  it('loads pending ontology candidates from the candidates API', async () => {
    const fetcher = vi.fn().mockResolvedValue({ namespace: 'demo', candidates: [pendingCandidate] });

    const { result } = renderHook(() => useOntologyCandidates('demo', 'pending'), { wrapper: swrWrapper(fetcher) });

    await waitFor(() => expect(result.current.candidates).toEqual([pendingCandidate]));
    expect(fetcher).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/candidates?status=pending');
    expect(result.current.isLoading).toBe(false);
  });

  it('does not load namespace-scoped ontology APIs without a namespace', async () => {
    const fetcher = vi.fn().mockResolvedValue({ packs: [] });

    renderHook(() => useOntologyProfile(null), { wrapper: swrWrapper(fetcher) });
    renderHook(() => useOntologyUnit(null), { wrapper: swrWrapper(fetcher) });
    renderHook(() => useOntologySummary(null), { wrapper: swrWrapper(fetcher) });
    renderHook(() => useOntologyCandidates(null), { wrapper: swrWrapper(fetcher) });

    await act(async () => {});
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('loads and saves ontology unit metadata without a profile', async () => {
    const unit = { namespace: 'demo', active_profile_id: null, name: 'Audit Unit', purpose: 'Govern audits', domain: 'audit', expected_users: ['auditor'], source_material: ['policy'], governance_mode: 'strict' };
    const fetcher = vi.fn().mockResolvedValue({ namespace: 'demo', unit, unit_exists: true });
    mockApiPut.mockResolvedValue({ namespace: 'demo', unit, unit_exists: true });

    const { result } = renderHook(() => useOntologyUnit('demo'), { wrapper: swrWrapper(fetcher) });

    await waitFor(() => expect(result.current.unit).toEqual(unit));
    expect(fetcher).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/unit');

    await act(async () => { await result.current.saveUnit({ active_profile_id: null, name: 'Audit Unit' }); });
    expect(mockApiPut).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/unit', { unit: { active_profile_id: null, name: 'Audit Unit', namespace: 'demo' } });
  });

  it('saves ontology profiles through the profile API', async () => {
    mockApiPut.mockResolvedValue({ namespace: 'demo', profile, profile_exists: true, default_suggested: false, default_profile: null, validation_issues: [] });
    const { result } = renderHook(() => useOntologyProfile('demo'));
    await act(async () => { await result.current.saveProfile(profile); });
    expect(mockApiPut).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/profile', { profile });
  });

  it('validates profile payloads without saving', async () => {
    mockApiPost.mockResolvedValue({ namespace: 'demo', subject: 'profile', valid: true, issues: [] });
    const { result } = renderHook(() => useOntologyValidation('demo'));
    await act(async () => { await result.current.validateProfile(profile); });
    expect(mockApiPost).toHaveBeenCalledWith('/knowledge/namespaces/demo/ontology/validate', { subject: 'profile', profile });
  });

  it('posts candidate approve, map, reject, and bulk actions', async () => {
    mockApiPost.mockResolvedValue({ id: 'cand-1' });
    const { result } = renderHook(() => useOntologyCandidates('demo'));
    await act(async () => { await result.current.approveCandidate('cand-1', { canonical_id: 'new_relation' }); });
    await act(async () => { await result.current.mapCandidate('cand-1', 'depends_on'); });
    await act(async () => { await result.current.rejectCandidate('cand-1', 'not useful'); });
    await act(async () => { await result.current.bulkUpdateCandidates([{ candidate_id: 'cand-1', action: 'reject', reason: 'bulk' }]); });
    expect(mockApiPost).toHaveBeenNthCalledWith(1, '/knowledge/namespaces/demo/ontology/candidates/cand-1/approve', { canonical_id: 'new_relation' });
    expect(mockApiPost).toHaveBeenNthCalledWith(2, '/knowledge/namespaces/demo/ontology/candidates/cand-1/map', { canonical_id: 'depends_on' });
    expect(mockApiPost).toHaveBeenNthCalledWith(3, '/knowledge/namespaces/demo/ontology/candidates/cand-1/reject', { reason: 'not useful' });
    expect(mockApiPost).toHaveBeenNthCalledWith(4, '/knowledge/namespaces/demo/ontology/candidates/bulk', { actions: [{ candidate_id: 'cand-1', action: 'reject', reason: 'bulk' }] });
  });
});

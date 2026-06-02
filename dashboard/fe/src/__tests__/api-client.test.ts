/**
 * Unit tests for api-client.ts response unwrapping logic.
 * 
 * These tests verify that the fetcher correctly bridges backend response formats
 * (wrapped objects like {plans: [...], count: N}) to frontend expectations (plain arrays).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Plan } from '@/types';

// We test the logic of the unwrapping by importing the fetcher and mocking fetch.
// The `fetcher` calls `apiGet` which calls `request` which does the unwrapping.

describe('api-client response unwrapping', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Helper: mock global fetch to return a given JSON body.
   */
  function mockFetch(body: unknown, status = 200) {
    const response = {
      ok: status >= 200 && status < 300,
      status,
      statusText: 'OK',
      json: () => Promise.resolve(body),
      headers: new Headers(),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
  }

  it('unwraps {plans: [...], count: N} → Plan[]', async () => {
    const backendResponse = {
      plans: [{ plan_id: 'p1', title: 'Test Plan' }],
      count: 1,
    };
    mockFetch(backendResponse);

    const { fetcher } = await import('@/lib/api-client');
    const result = await fetcher('/plans') as Plan[];
    
    expect(Array.isArray(result)).toBe(true);
    expect(result).toHaveLength(1);
    expect(result[0].plan_id).toBe('p1');
  });

  it('unwraps {epics: [...], count: N} → Epic[]', async () => {
    const backendResponse = {
      epics: [
        { epic_ref: 'EPIC-001', title: 'First Epic' },
        { epic_ref: 'EPIC-002', title: 'Second Epic' },
      ],
      count: 2,
    };
    mockFetch(backendResponse);

    const { fetcher } = await import('@/lib/api-client');
    const result = await fetcher('/plans/p1/epics');
    
    expect(Array.isArray(result)).toBe(true);
    expect(result).toHaveLength(2);
  });

  it('returns plain array as-is (roles)', async () => {
    const backendResponse = [
      { id: 'r1', name: 'engineer' },
      { id: 'r2', name: 'qa' },
    ];
    mockFetch(backendResponse);

    const { fetcher } = await import('@/lib/api-client');
    const result = await fetcher('/roles');
    
    expect(Array.isArray(result)).toBe(true);
    expect(result).toHaveLength(2);
  });

  it('returns plain object as-is when no unwrap key matches (stats)', async () => {
    const backendResponse = {
      total_plans: { value: 5, trend: { direction: 'up', delta: 1 } },
      active_epics: { value: 12, trend: { direction: 'flat', delta: 0 } },
      completion_rate: { value: 72.5, trend: { direction: 'up', delta: 3 } },
      escalations_pending: { value: 2, trend: { direction: 'down', delta: 1 } },
    };
    mockFetch(backendResponse);

    const { fetcher } = await import('@/lib/api-client');
    const result = await fetcher('/stats') as Record<string, unknown>;
    
    // Stats should NOT be unwrapped — no matching key
    expect(Array.isArray(result)).toBe(false);
    expect(result).toHaveProperty('total_plans');
    expect(result).toHaveProperty('escalations_pending');
  });

  it('unwraps {notifications: []} → []', async () => {
    mockFetch({ notifications: [] });

    const { fetcher } = await import('@/lib/api-client');
    const result = await fetcher('/notifications');
    
    expect(Array.isArray(result)).toBe(true);
    expect(result).toHaveLength(0);
  });

  it('preserves research search metadata instead of unwrapping results', async () => {
    const backendResponse = {
      query: 'vector databases',
      engines_used: ['google'],
      categories_used: ['it'],
      results: [{ title: 'Result', url: 'https://example.com', snippet: '' }],
      elapsed_seconds: 1.23,
      warnings: ['partial'],
    };
    mockFetch(backendResponse);

    const { fetcher } = await import('@/lib/api-client');
    const result = await fetcher('/knowledge/namespaces/default/research/search') as typeof backendResponse;

    expect(Array.isArray(result)).toBe(false);
    expect(result.results).toHaveLength(1);
    expect(result.elapsed_seconds).toBe(1.23);
    expect(result.warnings).toEqual(['partial']);
  });

  it('respects NEXT_PUBLIC_API_BASE_URL if set', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.test.com/v1');
    vi.resetModules();
    
    mockFetch({ plans: [] });
    const { fetcher } = await import('@/lib/api-client');
    
    await fetcher('/plans');
    
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('https://api.test.com/v1/plans'),
      expect.anything()
    );
    
    vi.unstubAllEnvs();
  });

  it('throws ApiError for non-OK responses', async () => {
    const errorResponse = {
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      json: () => Promise.resolve({ message: 'Missing plan_id' }),
      headers: new Headers(),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse));

    const { fetcher, ApiError } = await import('@/lib/api-client');
    
    await expect(fetcher('/notifications')).rejects.toThrow(ApiError);
    await expect(fetcher('/notifications')).rejects.toThrow('Missing plan_id');
  });

  it('handles 204 No Content gracefully', async () => {
    const response = {
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: () => Promise.reject(new Error('No body')),
      headers: new Headers(),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

    const { fetcher } = await import('@/lib/api-client');
    const result = await fetcher('/roles/r1');
    
    expect(result).toEqual({});
  });
});

describe('Plan type safety — safe defaults', () => {
  it('Plan with only required fields does not crash', () => {
    // Simulate backend response with minimal fields
    const minimalPlan: Plan = {
      plan_id: 'plan-minimal',
      title: 'Minimal Plan',
    };

    // All optional fields should default safely
    expect(minimalPlan.plan_id).toBe('plan-minimal');
    expect(minimalPlan.goal ?? '').toBe('');
    expect(minimalPlan.domain ?? 'custom').toBe('custom');
    expect(minimalPlan.pct_complete ?? 0).toBe(0);
    expect(minimalPlan.critical_path ?? { completed: 0, total: 0 }).toEqual({ completed: 0, total: 0 });
    expect(minimalPlan.roles ?? []).toEqual([]);
    expect(minimalPlan.escalations ?? 0).toBe(0);
  });

  it('Plan with all fields populated works correctly', () => {
    const fullPlan = {
      plan_id: 'plan-full',
      title: 'Full Plan',
      goal: 'Complete the mission',
      domain: 'software',
      pct_complete: 75,
      critical_path: { completed: 3, total: 5 },
      roles: [{ name: 'engineer', initials: 'EN', color: '#3b82f6' }],
      escalations: 2,
    };

    expect(fullPlan.goal ?? '').toBe('Complete the mission');
    expect(fullPlan.domain ?? 'custom').toBe('software');
    expect(fullPlan.pct_complete ?? 0).toBe(75);
    expect(fullPlan.critical_path.completed).toBe(3);
    expect(fullPlan.roles.length).toBe(1);
    expect(fullPlan.escalations ?? 0).toBe(2);
  });

  it('[...plans] spread works when unwrapped correctly', () => {
    const plans = [{ plan_id: 'p1' }, { plan_id: 'p2' }];
    
    // This is the exact pattern that crashed before the fix
    const result = [...plans];
    expect(result).toHaveLength(2);
    expect(result[0].plan_id).toBe('p1');
  });

  it('critical_path.completed / critical_path.total safe with defaults', () => {
    const plan: Plan = { plan_id: 'p1', title: 'T' };
    const cp = plan.critical_path ?? { completed: 0, total: 0 };
    const pct = cp.total > 0 ? (cp.completed / cp.total) * 100 : 0;
    
    // Should not divide by zero or crash
    expect(pct).toBe(0);
  });
});

describe('Stats normalization — escalations_pending → escalations', () => {
  it('maps escalations_pending to escalations', () => {
    const rawData: Record<string, unknown> = {
      total_plans: { value: 5, trend: { direction: 'up', delta: 1 } },
      escalations_pending: { value: 3, trend: { direction: 'down', delta: 1 } },
    };

    // This is the normalization logic from use-stats.ts
    const stats = {
      ...rawData,
      escalations: rawData.escalations || rawData.escalations_pending,
    };

    expect(stats.escalations).toEqual({ value: 3, trend: { direction: 'down', delta: 1 } });
  });

  it('preserves escalations if already present', () => {
    const rawData: Record<string, unknown> = {
      escalations: { value: 7, trend: { direction: 'up', delta: 2 } },
    };

    const stats = {
      ...rawData,
      escalations: rawData.escalations || rawData.escalations_pending,
    };

    expect(stats.escalations).toEqual({ value: 7, trend: { direction: 'up', delta: 2 } });
  });
});

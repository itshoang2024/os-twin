import { afterEach, describe, expect, it, vi } from 'vitest';

async function importRuntimeConfig() {
  vi.resetModules();
  return import('@/lib/runtime-config');
}

describe('runtime-config', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });
  it('uses same-origin /api by default for browser-safe dev proxying', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '');
    const { getApiBaseUrl } = await importRuntimeConfig();

    expect(getApiBaseUrl()).toBe('/api');
  });

  it('honors an explicit API base URL override without trailing slash', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'http://localhost:3366/api/');
    const { getApiBaseUrl, getWebSocketUrl } = await importRuntimeConfig();

    expect(getApiBaseUrl()).toBe('http://localhost:3366/api');
    expect(getWebSocketUrl()).toBe('ws://localhost:3366/api/ws');
  });
});

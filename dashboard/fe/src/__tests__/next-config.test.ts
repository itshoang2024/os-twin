import { afterEach, describe, expect, it, vi } from 'vitest';

async function importNextConfig() {
  vi.resetModules();
  return import('../../next.config');
}

describe('next.config API proxy target', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('defaults the development API rewrite to the standard FastAPI port', async () => {
    vi.stubEnv('OSTWIN_BACKEND_URL', '');
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '');
    vi.stubEnv('BACKEND_URL', '');
    const { default: config } = await importNextConfig();

    const rewrites = await config.rewrites?.();

    expect(rewrites).toEqual([
      {
        source: '/api/:path*',
        destination: 'http://localhost:3366/api/:path*',
      },
    ]);
  });

  it('honors an isolated QA backend URL and strips /api plus trailing slash', async () => {
    vi.stubEnv('OSTWIN_BACKEND_URL', 'http://127.0.0.1:3367/api/');
    const { default: config } = await importNextConfig();

    const rewrites = await config.rewrites?.();

    expect(rewrites).toEqual([
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:3367/api/:path*',
      },
    ]);
  });

  it('falls back to NEXT_PUBLIC_API_BASE_URL for browser QA launch scripts', async () => {
    vi.stubEnv('OSTWIN_BACKEND_URL', '');
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'http://127.0.0.1:4455/api');
    const { default: config } = await importNextConfig();

    const rewrites = await config.rewrites?.();

    expect(rewrites?.[0]).toMatchObject({
      destination: 'http://127.0.0.1:4455/api/:path*',
    });
  });

  it('allows loopback browser QA origins for Next dev resources', async () => {
    const { default: config } = await importNextConfig();

    expect(config.allowedDevOrigins).toEqual(expect.arrayContaining(['127.0.0.1', 'localhost']));
  });
});

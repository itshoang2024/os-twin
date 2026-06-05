const configuredApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();

// Use a same-origin API path by default. In Next dev, next.config.ts rewrites
// /api/* to the FastAPI backend; in production, FastAPI serves the static
// frontend and /api is already same-origin. This avoids CORS/auth failures
// during browser QA while still allowing explicit remote API overrides.
export const API_BASE_URL = (configuredApiBaseUrl || '/api').replace(/\/$/, '');

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function getWebSocketUrl(): string {
  const apiBase = getApiBaseUrl();
  if (/^https?:\/\//.test(apiBase)) {
    return apiBase.replace(/^http/, 'ws').replace(/\/$/, '') + '/ws';
  }

  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}${apiBase}/ws`;
  }

  return `ws://localhost:3366${apiBase}/ws`;
}

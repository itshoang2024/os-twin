/**
 * API Client Utility
 * Wraps fetch with base URL, standard error handling, and typed responses.
 */

import { getApiBaseUrl } from './runtime-config';

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const BASE_URL = getApiBaseUrl();
  const url = `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
  
  const response = await fetch(url, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = { message: response.statusText };
    }
    throw new ApiError(
      errorData.message || `API Request failed with status ${response.status}`,
      response.status,
      errorData
    );
  }

  if (response.status === 204) {
    return {} as T;
  }

  const json = await response.json();
  const preserveWrappedResponse = path.includes('/research/search');

  // Unwrap backend responses that wrap arrays in named keys.
  // e.g. { plans: [...], count: N } → [...] so SWR hooks get Plan[] directly.
  // Skip unwrap for detail endpoints (e.g. { plan: {}, epics: [] }).
  if (!preserveWrappedResponse && json && typeof json === 'object' && !Array.isArray(json)) {
    const UNWRAP_KEYS = ['plans', 'epics', 'roles', 'skills', 'notifications', 'versions', 'goals', 'results', 'entries', 'tree'];
    const DETAIL_KEYS = ['plan', 'epic', 'role', 'skill', 'version'];
    const jsonKeys = Object.keys(json);
    const hasDetailKey = jsonKeys.some(k => DETAIL_KEYS.includes(k) && json[k] && typeof json[k] === 'object' && !Array.isArray(json[k]));
    if (!hasDetailKey) {
      for (const key of UNWRAP_KEYS) {
        if (Array.isArray(json[key])) {
          return json[key] as T;
        }
      }
    }
  }

  return json as T;
}

export async function apiGet<T>(path: string, options?: RequestInit): Promise<T> {
  return request<T>(path, { ...options, method: 'GET' });
}

export async function apiPost<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...options,
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiPut<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...options,
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiPatch<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...options,
    method: 'PATCH',
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiDelete<T>(path: string, options?: RequestInit): Promise<T> {
  return request<T>(path, { ...options, method: 'DELETE' });
}

export const fetcher = <T = unknown>(url: string): Promise<T> => apiGet<T>(url);

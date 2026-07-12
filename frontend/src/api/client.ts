import type { ApiEnvelope } from './types';

export class ApiError extends Error {
  requestId: string | null;
  errors: ApiEnvelope<unknown>['errors'];

  constructor(message: string, requestId: string | null, errors: ApiEnvelope<unknown>['errors']) {
    super(message);
    this.name = 'ApiError';
    this.requestId = requestId;
    this.errors = errors;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
}

function buildUrl(path: string, query?: RequestOptions['query']) {
  const url = new URL(path, window.location.origin);
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  });
  return `${url.pathname}${url.search}`;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method || 'GET',
    headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  let envelope: ApiEnvelope<T> | null = null;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    if (!response.ok) throw new ApiError(`HTTP ${response.status}`, null, null);
  }

  if (!response.ok || envelope?.errors) {
    throw new ApiError(envelope?.message || `HTTP ${response.status}`, envelope?.request_id || null, envelope?.errors || null);
  }

  return envelope?.data as T;
}

export const apiClient = {
  get: <T>(path: string, query?: RequestOptions['query']) => request<T>(path, { query }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

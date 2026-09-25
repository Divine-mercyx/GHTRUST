/**
 * HTTP client for the GH Trust API.
 *
 * - Sends the version-gate headers on every call.
 * - Access token lives in memory only; the rotating refresh token in secure storage.
 * - On 401 TOKEN_INVALID: one refresh (single-flight), then one retry.
 * - Every mutating call carries an Idempotency-Key; the retry after a refresh
 *   reuses it, so a payment can never be applied twice.
 */
import * as Crypto from 'expo-crypto';
import { Platform } from 'react-native';

import { tokenStore } from '@/auth/storage';

import { API_BASE, APP_VERSION } from './config';
import { ApiError, SESSION_ENDED } from './errors';
import type { TokenPair } from './types';

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

export type RequestOptions = {
  body?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Reuse one key for every retry of the same user action (payments, withdrawals). */
  idempotencyKey?: string;
  auth?: boolean;
  timeoutMs?: number;
  signal?: AbortSignal;
};

type Listeners = {
  /** The session can't be recovered: forget it and show sign-in. */
  onSessionEnded: () => void;
  /** 426 / maintenance: the app shell shows a blocking screen. */
  onGate: (code: 'APP_UPDATE_REQUIRED' | 'MAINTENANCE_MODE', message: string) => void;
};

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let listeners: Listeners = { onSessionEnded: () => undefined, onGate: () => undefined };

export function configureClient(next: Listeners) {
  listeners = next;
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function hasAccessToken() {
  return accessToken !== null;
}

export const newIdempotencyKey = () => Crypto.randomUUID();

function buildUrl(path: string, query?: RequestOptions['query']) {
  const url = `${API_BASE}${path}`;
  if (!query) return url;
  const params = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return params.length ? `${url}?${params.join('&')}` : url;
}

function baseHeaders(): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (Platform.OS === 'ios' || Platform.OS === 'android') {
    headers['X-App-Platform'] = Platform.OS;
    headers['X-App-Version'] = APP_VERSION;
  }
  return headers;
}

async function toApiError(res: Response): Promise<ApiError> {
  let payload: any = null;
  try {
    payload = await res.json();
  } catch {
    // non-JSON (proxy error page etc.)
  }
  const retryAfter = Number(res.headers.get('retry-after')) || undefined;
  const requestId = payload?.request_id ?? res.headers.get('x-request-id') ?? undefined;
  let message: string = typeof payload?.detail === 'string' ? payload.detail : '';
  let errors: string[] = Array.isArray(payload?.errors) ? payload.errors.map(String) : [];
  // VALIDATION_ERROR: detail is a list of {loc, msg}
  if (Array.isArray(payload?.detail)) {
    errors = payload.detail.map((d: any) => d?.msg ?? String(d));
    message = errors[0] ?? 'Please check the details and try again.';
  }
  const code = payload?.code ?? (res.status === 401 ? 'TOKEN_INVALID' : `HTTP_${res.status}`);
  return new ApiError(res.status, code, message || res.statusText, errors, requestId, retryAfter);
}

async function send(method: Method, path: string, opts: RequestOptions, idempotencyKey?: string) {
  const headers = baseHeaders();
  if (opts.auth !== false && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form; // fetch sets the multipart boundary
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? 20_000);
  opts.signal?.addEventListener('abort', () => controller.abort());
  try {
    return await fetch(buildUrl(path, opts.query), { method, headers, body, signal: controller.signal });
  } catch (err) {
    if (opts.signal?.aborted) throw err;
    const timedOut = (err as Error)?.name === 'AbortError';
    const url = buildUrl(path, opts.query);
    throw new ApiError(0, timedOut ? 'TIMEOUT' : 'NETWORK', `${timedOut ? 'Timed out' : 'No response'}: ${method} ${url}`);
  } finally {
    clearTimeout(timeout);
  }
}

/** Exchange the stored refresh token for a new pair. Only one runs at a time. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    const refreshToken = await tokenStore.getRefresh();
    if (!refreshToken) return false;
    const res = await send('POST', '/auth/token/refresh', { body: { refresh_token: refreshToken }, auth: false });
    if (!res.ok) {
      const error = await toApiError(res);
      if (SESSION_ENDED.has(error.code) || res.status === 401) {
        await endSession();
        return false;
      }
      throw error; // transient (network/5xx): keep the session, let the caller retry
    }
    const pair = (await res.json()) as TokenPair;
    await tokenStore.setRefresh(pair.refresh_token); // rotates every time
    accessToken = pair.access_token;
    return true;
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function endSession() {
  accessToken = null;
  await tokenStore.clear();
  listeners.onSessionEnded();
}

export async function request<T>(method: Method, path: string, opts: RequestOptions = {}): Promise<T> {
  const needsAuth = opts.auth !== false;
  const idempotencyKey = method === 'GET' ? undefined : (opts.idempotencyKey ?? newIdempotencyKey());

  if (needsAuth && !accessToken && !(await refreshSession())) {
    throw new ApiError(401, 'SESSION_REVOKED', 'Please sign in again.');
  }

  let res = await send(method, path, opts, idempotencyKey);

  if (res.status === 401 && needsAuth) {
    const error = await toApiError(res);
    if (SESSION_ENDED.has(error.code)) {
      await endSession();
      throw error;
    }
    if (!(await refreshSession())) throw error;
    res = await send(method, path, opts, idempotencyKey);
  }

  if (!res.ok) {
    const error = await toApiError(res);
    if (error.code === 'APP_UPDATE_REQUIRED' || error.code === 'MAINTENANCE_MODE') {
      listeners.onGate(error.code, error.message);
    } else if (res.status === 401 && needsAuth) {
      await endSession();
    }
    throw error;
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('POST', path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PATCH', path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, opts),
};

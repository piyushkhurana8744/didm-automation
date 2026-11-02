/**
 * The one HTTP client for the backend API (same origin, cookie auth).
 *
 * - Unsafe methods send the `didm_csrf` cookie value back in `X-CSRF-Token` (double-submit).
 * - Errors become an ApiError carrying the HTTP status and the backend's `detail` message.
 * - A 401 on an authenticated call sends the browser to the login page.
 * Request bodies may carry secrets (passwords, invitation tokens): they are never logged here.
 */
export const BASE_PATH = '/app';
export const API_PREFIX = '/api/v1';
const CSRF_COOKIE = 'didm_csrf';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  /** The backend's machine-readable reason (the `X-Error-Code` response header), when it sends one. */
  readonly code: string | null;

  constructor(status: number, detail: string, code: string | null = null) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** The backend's error code for a failed call (from `X-Error-Code`), or null. */
export function errorCode(e: unknown): string | null {
  return isApiError(e) ? e.code : null;
}

/** A message that is safe and useful to show to the person. */
export function errorMessage(e: unknown): string {
  if (isApiError(e)) return e.detail;
  return 'Something went wrong. Please try again.';
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  for (const part of document.cookie.split(';')) {
    const eq = part.indexOf('=');
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === name) return decodeURIComponent(part.slice(eq + 1).trim());
  }
  return null;
}

function fallbackMessage(status: number): string {
  switch (status) {
    case 400:
      return 'The request could not be completed.';
    case 401:
      return 'Please log in.';
    case 403:
      return "You don't have access to this.";
    case 404:
      return 'Not found.';
    case 409:
      return 'This conflicts with the current state. Reload and try again.';
    case 422:
      return 'Some of the values are not valid.';
    case 429:
      return 'Too many attempts. Wait a few minutes and try again.';
    default:
      return status >= 500 ? 'The server had a problem. Please try again.' : 'Something went wrong.';
  }
}

function detailFrom(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((item) => {
          if (!item || typeof item !== 'object') return null;
          const { msg, loc } = item as { msg?: unknown; loc?: unknown };
          if (typeof msg !== 'string') return null;
          const field = Array.isArray(loc) ? loc[loc.length - 1] : null;
          return typeof field === 'string' && field !== 'body' ? `${field.replace(/_/g, ' ')}: ${msg}` : msg;
        })
        .filter((m): m is string => !!m);
      if (msgs.length) return msgs.join(' ');
    }
  }
  return fallbackMessage(status);
}

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

export interface RequestOptions {
  /** Default true. Set false for calls where 401 is an expected answer (login, "am I logged in?"). */
  redirectOn401?: boolean;
  signal?: AbortSignal;
}

export function redirectToLogin(): void {
  if (typeof window === 'undefined') return;
  const target = `${BASE_PATH}/login/`;
  if (window.location.pathname !== target) window.location.assign(target);
}

async function request<T>(method: Method, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`${API_PREFIX}${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      cache: 'no-store',
      body: method === 'GET' || body === undefined ? undefined : JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'Could not reach the server. Check your connection and try again.');
  }

  let payload: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!res.ok) {
    if (res.status === 401 && opts.redirectOn401 !== false) redirectToLogin();
    throw new ApiError(res.status, detailFrom(payload, res.status), res.headers.get('X-Error-Code'));
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('POST', path, body ?? {}, opts),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PATCH', path, body ?? {}, opts),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PUT', path, body ?? {}, opts),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, undefined, opts),
};

/** Encodes one path segment (ids come from the API, but never trust them into a URL raw). */
export const seg = (value: string) => encodeURIComponent(value);

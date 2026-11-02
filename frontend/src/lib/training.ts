/**
 * Shared helpers for training sessions: labels, plain-language explanations and small formatters.
 * Nothing here talks to a voice provider: sessions are started and tracked through our own API only.
 */
import type { SessionStatus, TrainingSession } from './types';

export const SESSION_STATUSES: SessionStatus[] = ['requested', 'preparing', 'connecting', 'active', 'completed', 'failed', 'cancelled', 'timed_out'];

export const SESSION_STATUS_LABELS: Record<SessionStatus, string> = {
  requested: 'Requested',
  preparing: 'Preparing',
  connecting: 'Calling you',
  active: 'In progress',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timed_out: 'Timed out',
};

export const SESSION_STATUS_BADGE: Record<SessionStatus, string> = {
  requested: 'badge badge-info',
  preparing: 'badge badge-info',
  connecting: 'badge badge-info',
  active: 'badge badge-ok',
  completed: 'badge badge-ok',
  failed: 'badge badge-danger',
  cancelled: 'badge',
  timed_out: 'badge badge-warn',
};

/** A session can be cancelled from the app only before the call is placed. */
export const CANCELLABLE: SessionStatus[] = ['requested', 'preparing'];

export function statusLabel(status: string): string {
  return (SESSION_STATUS_LABELS as Record<string, string>)[status] ?? status.replace(/_/g, ' ');
}

export function statusBadge(status: string): string {
  return (SESSION_STATUS_BADGE as Record<string, string>)[status] ?? 'badge';
}

/** "****1234" from a masked number like "******1234". */
export function shortPhone(masked: string | null | undefined): string | null {
  if (!masked) return null;
  const last4 = masked.replace(/\D/g, '').slice(-4);
  return last4 ? `****${last4}` : null;
}

/** "4 min 12 s", "45 s", or an em dash when unknown. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m === 0) return `${s} s`;
  return s ? `${m} min ${s} s` : `${m} min`;
}

/** What the session's current state means, in plain words. */
export function statusExplanation(s: TrainingSession): string {
  const phone = shortPhone(s.phone);
  switch (s.status) {
    case 'requested':
      return 'Your practice session was requested. We are checking your access and limits.';
    case 'preparing':
      return 'Getting the agent and your scenario ready.';
    case 'connecting':
      return s.channel === 'phone'
        ? `Sarvam is calling your phone${phone ? ` ending ${phone}` : ''}. Answer the call to start practising.`
        : 'Connecting to the agent.';
    case 'active':
      return s.channel === 'phone' ? 'You are on the call with the agent. Hang up when you are done.' : 'The session is in progress.';
    case 'completed':
      return 'The session has ended.';
    case 'failed':
      return 'The session could not be completed.';
    case 'cancelled':
      return 'This session was cancelled before the call was placed.';
    case 'timed_out':
      return 'The session did not finish in time and was closed.';
    default:
      return '';
  }
}

const EVENT_LABELS: Record<string, string> = {
  requested: 'Session requested',
  preparing: 'Preparing the agent',
  provider_initiated: 'Call placed by Sarvam',
  provider_result: 'Call result received',
  failed: 'Session failed',
  cancelled: 'Session cancelled',
  start_timeout: 'Call did not start in time',
  timed_out: 'Session timed out',
  browser_authorized: 'Browser session authorized',
  browser_connected: 'Browser connected',
  browser_ended: 'Browser session ended',
};

export function eventLabel(type: string): string {
  if (EVENT_LABELS[type]) return EVENT_LABELS[type];
  const t = type.replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** Messages for start errors the person can act on (the backend's detail is used otherwise). */
export function failureCodeLabel(code: string): string {
  return code.replace(/_/g, ' ');
}

/**
 * A random id for one start attempt, so a repeated request (double click, retry after a dropped
 * connection) is recognized by the server instead of starting a second call.
 */
export function newRequestId(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** A date input value (YYYY-MM-DD, local) as the ISO start of that day, or of the next day with `endOfDay`. */
export function dayToIso(value: string, endOfDay = false): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [y, m, d] = value.split('-').map(Number);
  const date = new Date(y, m - 1, d + (endOfDay ? 1 : 0));
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

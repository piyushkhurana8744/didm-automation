/**
 * Secret tokens arrive in the URL hash (never sent to servers). They are read here, sent only in POST
 * bodies, and never logged or kept in localStorage.
 *
 * The invitation token is kept in sessionStorage only while the person goes to the login page and back
 * ("Log in to accept"); it is removed as soon as the accept page reads it, and ignored after 30 minutes.
 */
const HANDOFF_KEY = 'didm_invite_handoff';
const HANDOFF_TTL_MS = 30 * 60 * 1000;

export function readHashToken(): string | null {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const token = params.get('token');
  return token && token.trim() ? token.trim() : null;
}

/** Removes the token from the address bar (after it has been used). */
export function clearHash(): void {
  if (typeof window === 'undefined') return;
  window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
}

/** Puts the token back into the hash (so a reload of the accept page keeps working). */
export function setHashToken(token: string): void {
  if (typeof window === 'undefined') return;
  const hash = `#${new URLSearchParams({ token }).toString()}`;
  window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search + hash);
}

export function stashInviteToken(token: string): void {
  try {
    sessionStorage.setItem(HANDOFF_KEY, JSON.stringify({ token, at: Date.now() }));
  } catch {
    /* storage unavailable: the person can reopen the link from their email */
  }
}

function readHandoff(): { token: string; at: number } | null {
  try {
    const raw = sessionStorage.getItem(HANDOFF_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as { token?: unknown; at?: unknown };
    if (typeof v.token !== 'string' || typeof v.at !== 'number' || Date.now() - v.at > HANDOFF_TTL_MS) {
      sessionStorage.removeItem(HANDOFF_KEY);
      return null;
    }
    return { token: v.token, at: v.at };
  } catch {
    return null;
  }
}

export function hasStashedInviteToken(): boolean {
  return readHandoff() !== null;
}

/** Returns the stashed token once and removes it. */
export function takeStashedInviteToken(): string | null {
  const v = readHandoff();
  try {
    sessionStorage.removeItem(HANDOFF_KEY);
  } catch {
    /* ignore */
  }
  return v?.token ?? null;
}

export function clearStashedInviteToken(): void {
  try {
    sessionStorage.removeItem(HANDOFF_KEY);
  } catch {
    /* ignore */
  }
}

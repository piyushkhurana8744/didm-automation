'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, isApiError, redirectToLogin } from './api';
import type { Me, Membership, Permission } from './types';
import { FullPageSpinner } from '@/components/Spinner';
import { ErrorState } from '@/components/ErrorState';

export interface SessionValue {
  me: Me;
  /** The selected organization id (from GET /auth/me), or null when none is selected. */
  activeOrgId: string | null;
  activeMembership: Membership | null;
  permissions: Permission[];
  can: (permission: Permission) => boolean;
  refresh: () => Promise<void>;
  switchOrg: (organizationId: string) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  const refresh = useCallback(async () => {
    const next = await api.get<Me>('/auth/me');
    setMe(next);
  }, []);

  useEffect(() => {
    let live = true;
    setError(null);
    api.get<Me>('/auth/me').then(
      (next) => live && setMe(next),
      (e: unknown) => {
        if (!live) return;
        if (isApiError(e) && e.status === 401) return; // api.ts is already sending the browser to login
        setError(e);
      },
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  const switchOrg = useCallback(
    async (organizationId: string) => {
      await api.post('/auth/active-organization', { organization_id: organizationId });
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout', {}, { redirectOn401: false });
    } finally {
      setMe(null);
      redirectToLogin();
    }
  }, []);

  const value = useMemo<SessionValue | null>(() => {
    if (!me) return null;
    const activeMembership =
      me.memberships.find((m) => m.organization.id === me.active_organization_id && m.organization.status === 'active') ??
      null;
    const permissions = activeMembership?.permissions ?? [];
    return {
      me,
      activeOrgId: activeMembership ? me.active_organization_id : null,
      activeMembership,
      permissions,
      can: (p: Permission) => permissions.includes(p),
      refresh,
      switchOrg,
      logout,
    };
  }, [me, refresh, switchOrg, logout]);

  if (error) {
    return (
      <main className="center-page">
        <ErrorState error={error} onRetry={() => setAttempt((a) => a + 1)} />
      </main>
    );
  }
  if (!value) return <FullPageSpinner label="Loading your account" />;
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error('useSession must be used inside <SessionProvider>');
  return v;
}

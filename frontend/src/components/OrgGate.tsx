'use client';

import { useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { useSession } from '@/lib/session';
import type { Membership, Permission } from '@/lib/types';
import { Forbidden } from './ErrorState';
import { Spinner } from './Spinner';

/**
 * Renders children only when an organization is selected and the membership has `permission`.
 * With no organization selected it goes to the organization picker. The server still enforces access.
 */
export function OrgGate({ permission, children }: { permission?: Permission; children: (m: Membership) => ReactNode }) {
  const { activeMembership } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!activeMembership) router.replace('/organizations/');
  }, [activeMembership, router]);

  if (!activeMembership) return <Spinner label="Choosing an organization" />;
  if (permission && !activeMembership.permissions.includes(permission)) return <Forbidden />;
  return <>{children(activeMembership)}</>;
}

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { errorMessage } from '@/lib/api';
import { formatDate } from '@/lib/format';
import { roleLabel } from '@/lib/roles';
import { useSession } from '@/lib/session';
import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { FormError } from '@/components/Field';
import { PageHeader } from '@/components/PageHeader';

export default function OrganizationsPage() {
  const { me, activeOrgId, switchOrg } = useSession();
  const router = useRouter();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function open(orgId: string) {
    setError(null);
    setBusyId(orgId);
    try {
      if (orgId !== activeOrgId) await switchOrg(orgId);
      router.push('/dashboard/');
    } catch (e) {
      setError(errorMessage(e));
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Organizations"
        description="Choose the organization you want to work in."
        actions={
          me.user.is_platform_admin ? (
            <Link href="/platform/" className="btn btn-secondary">
              Platform admin
            </Link>
          ) : undefined
        }
      />
      <FormError message={error} />
      {me.memberships.length === 0 ? (
        <EmptyState title="You are not a member of any organization yet.">
          <p>Ask an administrator of your organization to send you an invitation.</p>
          {me.user.is_platform_admin && (
            <p>
              As a platform administrator you can <Link href="/platform/">create an organization</Link>.
            </p>
          )}
        </EmptyState>
      ) : (
        <ul className="card-list">
          {me.memberships.map((m) => {
            const active = m.organization.status === 'active';
            const current = m.organization.id === activeOrgId;
            return (
              <li key={m.membership_id} className="card">
                <div className="card-main">
                  <h2 className="card-title">{m.organization.name}</h2>
                  <p className="card-meta">
                    {roleLabel(m.role)} · <span className="mono">{m.organization.slug}</span> · since {formatDate(m.organization.created_at)}
                  </p>
                  {!active && <span className="badge badge-warn">Suspended</span>}
                  {current && <span className="badge badge-ok">Current</span>}
                </div>
                <div className="card-actions">
                  {active ? (
                    <Button
                      variant={current ? 'secondary' : 'primary'}
                      busy={busyId === m.organization.id}
                      disabled={busyId !== null && busyId !== m.organization.id}
                      onClick={() => void open(m.organization.id)}
                      aria-label={`Open ${m.organization.name}`}
                    >
                      Open
                    </Button>
                  ) : (
                    <span className="muted">This organization is suspended.</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

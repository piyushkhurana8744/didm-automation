'use client';

import { api, seg } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import type { AuditEvent, Member, Membership } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

const LIMIT = 100;

function describeDetails(details: AuditEvent['details']): string {
  if (!details || typeof details !== 'object') return '';
  return Object.entries(details)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(', ');
}

function Audit({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const { data, error, loading, reload } = useLoad(() => api.get<AuditEvent[]>(`/organizations/${seg(orgId)}/audit-events?limit=${LIMIT}`), orgId);
  // Names for actor ids, when this role can see members. Failure only means ids are shown instead.
  const canSeeMembers = membership.permissions.includes('members.view');
  const members = useLoad(
    canSeeMembers ? () => api.get<Member[]>(`/organizations/${seg(orgId)}/members`).catch(() => [] as Member[]) : null,
    canSeeMembers ? orgId : null,
  );
  const names = new Map((members.data ?? []).map((m) => [m.user.id, m.user.name || m.user.email]));

  const columns: Column<AuditEvent>[] = [
    { key: 'when', header: 'When', render: (a) => formatDateTime(a.created_at) },
    { key: 'action', header: 'Action', render: (a) => <span className="mono">{a.action}</span> },
    {
      key: 'actor',
      header: 'By',
      render: (a) => (a.actor_user_id ? names.get(a.actor_user_id) ?? <span className="mono small">{a.actor_user_id}</span> : 'System'),
    },
    {
      key: 'target',
      header: 'Target',
      render: (a) => (a.target_type ? <span>{a.target_type} <span className="mono small">{a.target_id}</span></span> : '—'),
    },
    { key: 'details', header: 'Details', render: (a) => <span className="small break">{describeDetails(a.details) || '—'}</span> },
  ];

  return (
    <>
      <PageHeader
        title="Audit log"
        description={`The latest ${LIMIT} recorded changes in ${membership.organization.name}, newest first.`}
        actions={
          <Button variant="secondary" onClick={reload} busy={loading && !!data}>
            Refresh
          </Button>
        }
      />
      {loading && !data ? (
        <SkeletonRows label="Loading audit log" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <DataTable
          caption="Audit events"
          columns={columns}
          rows={data ?? []}
          rowKey={(a) => String(a.id)}
          empty={<EmptyState title="Nothing has been recorded yet." />}
        />
      )}
    </>
  );
}

export default function AuditPage() {
  return <OrgGate permission="audit.view">{(m) => <Audit membership={m} />}</OrgGate>;
}

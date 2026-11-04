'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { channelList, orgPath, query } from '@/lib/agents';
import { formatDate } from '@/lib/format';
import type { AgentListItem, Membership, Page } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button, ButtonLink } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { SelectField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Pagination } from '@/components/Pagination';
import { SkeletonRows } from '@/components/Spinner';

const LIMIT = 25;

function Agents({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const canManage = membership.permissions.includes('agents.manage');
  const [status, setStatus] = useState('active');
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [applied, setApplied] = useState({ q: '', category: '' });
  const [offset, setOffset] = useState(0);
  const [agentToDelete, setAgentToDelete] = useState<AgentListItem | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const key = `${orgId}|${status}|${applied.q}|${applied.category}|${offset}`;
  const { data, error, loading, reload } = useLoad(
    () => api.get<Page<AgentListItem>>(orgPath(orgId, `/agents${query({ status, q: applied.q, category: applied.category, limit: LIMIT, offset })}`)),
    key,
  );

  function onSearch(e: FormEvent) {
    e.preventDefault();
    setApplied({ q: q.trim(), category: category.trim() });
    setOffset(0);
  }

  const filtered = !!(applied.q || applied.category || status !== 'active');

  const columns: Column<AgentListItem>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (a) => (
        <>
          <Link href={`/agents/detail/?id=${encodeURIComponent(a.id)}`} className="cell-strong">
            {a.name}
          </Link>
          {a.status === 'archived' && <span className="badge">Archived</span>}
        </>
      ),
    },
    { key: 'category', header: 'Category', render: (a) => a.category || '—' },
    { key: 'channels', header: 'Channels', render: (a) => channelList(a.channels) },
    {
      key: 'version',
      header: 'Published',
      render: (a) =>
        a.published_internal_version ? (
          <>
            Version {a.published_internal_version}
            {a.published_provider_app_version ? <span className="muted small"> · Sarvam v{a.published_provider_app_version}</span> : null}
          </>
        ) : (
          <span className="badge badge-warn">Not published</span>
        ),
    },
    { key: 'draft', header: 'Draft', render: (a) => (a.has_draft ? <span className="badge badge-info">Draft open</span> : '—') },
    { key: 'updated', header: 'Updated', render: (a) => formatDate(a.updated_at) },
    ...(canManage
      ? [
          {
            key: 'actions',
            header: 'Actions',
            render: (a: AgentListItem) => (
              <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                <Link
                  href={`/agents/detail/?id=${encodeURIComponent(a.id)}`}
                  className="button button-sm button-secondary"
                  style={{ textDecoration: 'none', padding: '0.2rem 0.6rem' }}
                >
                  Edit
                </Link>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => {
                    setDeleteError(null);
                    setAgentToDelete(a);
                  }}
                >
                  Delete
                </Button>
              </div>
            ),
          },
        ]
      : []),
  ];

  return (
    <>
      <PageHeader
        title="Agents"
        description="Voice agents built in Sarvam and registered here for training."
        actions={canManage ? <ButtonLink href="/agents/new/" variant="primary">Register agent</ButtonLink> : undefined}
      />
      <form className="filters" onSubmit={onSearch} role="search" aria-label="Filter agents">
        <SelectField
          label="Status"
          options={[
            { value: 'active', label: 'Active' },
            { value: 'archived', label: 'Archived' },
            { value: 'all', label: 'All' },
          ]}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        />
        <TextField label="Search" type="search" placeholder="Name or description" maxLength={100} value={q} onChange={(e) => setQ(e.target.value)} />
        <TextField label="Category" placeholder="Exact category" maxLength={80} value={category} onChange={(e) => setCategory(e.target.value)} />
        <div>
          <Button type="submit" variant="secondary">
            Apply
          </Button>
        </div>
      </form>
      {loading && !data ? (
        <SkeletonRows label="Loading agents" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <>
          <DataTable
            caption="Agents"
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(a) => a.id}
            empty={
              filtered ? (
                <EmptyState title="No agents match these filters." />
              ) : (
                <EmptyState title="No agents are registered yet.">
                  {canManage ? (
                    <p>
                      Build the agent in Sarvam&apos;s dashboard first, then <Link href="/agents/new/">register it here</Link> with its app id.
                    </p>
                  ) : (
                    <p>An administrator registers agents.</p>
                  )}
                </EmptyState>
              )
            }
          />
          {data && <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} noun="agents" />}
        </>
      )}
      <ConfirmDialog
        open={agentToDelete !== null}
        title="Delete agent permanently?"
        confirmLabel="Delete permanently"
        danger
        busy={deleteBusy}
        error={deleteError}
        onConfirm={async () => {
          if (!agentToDelete) return;
          setDeleteBusy(true);
          setDeleteError(null);
          try {
            await api.delete(orgPath(orgId, `/agents/${seg(agentToDelete.id)}`));
            setAgentToDelete(null);
            reload();
          } catch (err) {
            setDeleteError(errorMessage(err));
          } finally {
            setDeleteBusy(false);
          }
        }}
        onCancel={() => {
          if (!deleteBusy) setAgentToDelete(null);
        }}
      >
        <p>
          Are you sure you want to permanently delete <strong>{agentToDelete?.name}</strong>? This will remove the agent, its versions, and practice data completely from the panel.
        </p>
      </ConfirmDialog>
    </>
  );
}

export default function AgentsPage() {
  return <OrgGate permission="agents.view">{(m) => <Agents membership={m} />}</OrgGate>;
}

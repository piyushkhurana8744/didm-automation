'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath, query } from '@/lib/agents';
import { capitalize, formatDate } from '@/lib/format';
import type { Membership, Team } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { CheckboxField, FormError, FormSuccess, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

function Teams({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const canManage = membership.permissions.includes('teams.manage');
  const [showArchived, setShowArchived] = useState(false);
  const { data, error, loading, reload } = useLoad(
    () => api.get<Team[]>(orgPath(orgId, `/teams${query({ include_archived: showArchived || undefined })}`)),
    `${orgId}|${showArchived}`,
  );

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [archiving, setArchiving] = useState<Team | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setNotice(null);
    if (!name.trim()) return setNameError('Enter a team name.');
    setNameError(null);
    setBusy(true);
    try {
      const t = await api.post<Team>(orgPath(orgId, '/teams'), { name: name.trim(), description: description.trim() });
      setName('');
      setDescription('');
      setNotice(`Team "${t.name}" was created. Open it to add members.`);
      reload();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmArchive() {
    if (!archiving) return;
    setArchiveBusy(true);
    setArchiveError(null);
    try {
      await api.post(orgPath(orgId, `/teams/${seg(archiving.id)}/archive`));
      setNotice(`Team "${archiving.name}" was archived.`);
      setArchiving(null);
      reload();
    } catch (err) {
      setArchiveError(errorMessage(err));
    } finally {
      setArchiveBusy(false);
    }
  }

  const columns: Column<Team>[] = [
    {
      key: 'name',
      header: 'Team',
      render: (t) => (
        <>
          <Link href={`/teams/detail/?id=${encodeURIComponent(t.id)}`} className="cell-strong">
            {t.name}
          </Link>
          {t.status === 'archived' && <span className="badge">Archived</span>}
        </>
      ),
    },
    { key: 'description', header: 'Description', render: (t) => <span className="small break">{t.description || '—'}</span> },
    { key: 'members', header: 'Members', align: 'end', render: (t) => t.member_count ?? 0 },
    { key: 'status', header: 'Status', render: (t) => capitalize(t.status) },
    { key: 'created', header: 'Created', render: (t) => formatDate(t.created_at) },
  ];
  if (canManage) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (t) =>
        t.status === 'active' ? (
          <div className="row row-end">
            <Link href={`/teams/detail/?id=${encodeURIComponent(t.id)}`} className="btn btn-secondary btn-sm">
              Members
            </Link>
            <Button
              size="sm"
              variant="danger"
              onClick={() => {
                setArchiveError(null);
                setArchiving(t);
              }}
              aria-label={`Archive team ${t.name}`}
            >
              Archive
            </Button>
          </div>
        ) : null,
    });
  }

  return (
    <>
      <PageHeader title="Teams" description="Group people so you can assign agents to everyone in a team at once." />
      <FormSuccess message={notice} />
      {canManage && (
        <section className="panel" aria-labelledby="new-team">
          <h2 id="new-team" className="panel-title">
            Create a team
          </h2>
          <form onSubmit={onCreate} noValidate className="form form-inline">
            <FormError message={formError} />
            <TextField label="Name" required maxLength={200} value={name} error={nameError} onChange={(e) => setName(e.target.value)} />
            <TextField label="Description" maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
            <Button type="submit" busy={busy}>
              Create team
            </Button>
          </form>
        </section>
      )}
      <section aria-labelledby="team-list">
        <div className="section-head">
          <h2 id="team-list">All teams</h2>
          <CheckboxField label="Show archived teams" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
        </div>
        {loading && !data ? (
          <SkeletonRows label="Loading teams" />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <DataTable
            caption="Teams"
            columns={columns}
            rows={data ?? []}
            rowKey={(t) => t.id}
            empty={<EmptyState title={showArchived ? 'There are no teams.' : 'There are no active teams yet.'} />}
          />
        )}
      </section>
      <ConfirmDialog
        open={archiving !== null}
        title="Archive team?"
        confirmLabel="Archive"
        danger
        busy={archiveBusy}
        error={archiveError}
        onConfirm={() => void confirmArchive()}
        onCancel={() => setArchiving(null)}
      >
        <p>
          {archiving ? (
            <>
              <strong>{archiving.name}</strong> can no longer get new members or new agents. Archiving cannot be undone here.
            </>
          ) : null}
        </p>
      </ConfirmDialog>
    </>
  );
}

export default function TeamsPage() {
  return <OrgGate permission="teams.view">{(m) => <Teams membership={m} />}</OrgGate>;
}

'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { capitalize, formatDate } from '@/lib/format';
import { roleLabel } from '@/lib/roles';
import type { AddTeamMembersResult, Member, Membership, Team, TeamMember } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { CheckList } from '@/components/CheckList';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState, NotFoundState } from '@/components/ErrorState';
import { FormError, FormSuccess, TextAreaField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows, Spinner } from '@/components/Spinner';
import { WithQuery } from '@/components/WithQuery';

function EditTeam({ orgId, team, onSaved }: { orgId: string; team: Team; onSaved: (t: Team) => void }) {
  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description);
  const [nameError, setNameError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dirty = name !== team.name || description !== team.description;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSaved(null);
    if (!name.trim()) return setNameError('Enter a team name.');
    setNameError(null);
    setBusy(true);
    try {
      const t = await api.patch<Team>(orgPath(orgId, `/teams/${seg(team.id)}`), { name: name.trim(), description: description.trim() });
      onSaved(t);
      setName(t.name);
      setDescription(t.description);
      setSaved('Team saved.');
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="form">
      <FormError message={formError} />
      <FormSuccess message={saved} />
      <TextField label="Name" required maxLength={200} value={name} error={nameError} onChange={(e) => setName(e.target.value)} />
      <TextAreaField label="Description" rows={2} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
      <div>
        <Button type="submit" busy={busy} disabled={!dirty}>
          Save team
        </Button>
      </div>
    </form>
  );
}

function TeamDetail({ membership, teamId }: { membership: Membership; teamId: string }) {
  const orgId = membership.organization.id;
  const canManage = membership.permissions.includes('teams.manage');
  // There is no single-team endpoint: the list (with archived teams) holds the details
  const teams = useLoad(() => api.get<Team[]>(orgPath(orgId, '/teams?include_archived=true')), orgId);
  const team = teams.data?.find((t) => t.id === teamId) ?? null;
  const members = useLoad(() => api.get<TeamMember[]>(orgPath(orgId, `/teams/${seg(teamId)}/members`)), `${orgId}|${teamId}`);
  const editable = canManage && team?.status === 'active';
  const orgMembers = useLoad(editable ? () => api.get<Member[]>(orgPath(orgId, '/members')) : null, editable ? orgId : null);

  const [picked, setPicked] = useState<string[]>([]);
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [removing, setRemoving] = useState<TeamMember | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  if (teams.loading && !teams.data) return <Spinner label="Loading team" />;
  if (teams.error) return <ErrorState error={teams.error} onRetry={teams.reload} />;
  if (!team) return <NotFoundState message="This team does not exist." />;

  const inTeam = new Set((members.data ?? []).map((m) => m.user_id));
  const candidates = (orgMembers.data ?? []).filter((m) => m.status === 'active' && !inTeam.has(m.user.id));

  async function addMembers(e: FormEvent) {
    e.preventDefault();
    setAddError(null);
    setNotice(null);
    if (picked.length === 0) return setAddError('Choose at least one person.');
    setAddBusy(true);
    try {
      const res = await api.post<AddTeamMembersResult>(orgPath(orgId, `/teams/${seg(teamId)}/members`), { user_ids: picked });
      setPicked([]);
      setNotice(
        `${res.added.length} ${res.added.length === 1 ? 'person was' : 'people were'} added.` +
          (res.already_members.length ? ` ${res.already_members.length} already in the team.` : ''),
      );
      members.reload();
      teams.reload();
    } catch (err) {
      setAddError(errorMessage(err));
    } finally {
      setAddBusy(false);
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      await api.delete(orgPath(orgId, `/teams/${seg(teamId)}/members/${seg(removing.user_id)}`));
      setNotice(`${removing.name || removing.email} was removed from the team.`);
      setRemoving(null);
      members.reload();
      teams.reload();
    } catch (err) {
      setRemoveError(errorMessage(err));
    } finally {
      setRemoveBusy(false);
    }
  }

  const columns: Column<TeamMember>[] = [
    { key: 'name', header: 'Name', render: (m) => <span className="cell-strong">{m.name || '—'}</span> },
    { key: 'email', header: 'Email', render: (m) => <span className="break">{m.email}</span> },
    { key: 'added', header: 'Added', render: (m) => formatDate(m.added_at) },
  ];
  if (editable) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (m) => (
        <Button
          size="sm"
          variant="danger"
          onClick={() => {
            setRemoveError(null);
            setRemoving(m);
          }}
          aria-label={`Remove ${m.name || m.email} from the team`}
        >
          Remove
        </Button>
      ),
    });
  }

  return (
    <>
      <p className="small">
        <Link href="/teams/">← Teams</Link>
      </p>
      <PageHeader
        title={team.name}
        description={
          <>
            {team.status === 'archived' ? <span className="badge">Archived</span> : null} {team.member_count ?? 0} members · {capitalize(team.status)}
          </>
        }
      />
      <FormSuccess message={notice} />
      {editable ? (
        <section className="panel" aria-labelledby="team-edit">
          <h2 id="team-edit" className="panel-title">
            Details
          </h2>
          <EditTeam orgId={orgId} team={team} onSaved={(t) => teams.setData((rows) => (rows ?? []).map((r) => (r.id === t.id ? { ...r, ...t } : r)))} />
        </section>
      ) : (
        team.description && <p className="break">{team.description}</p>
      )}
      {team.status === 'archived' && <div className="alert alert-warn">This team is archived. Its members can no longer be changed.</div>}

      {editable && (
        <section className="panel" aria-labelledby="team-add">
          <h2 id="team-add" className="panel-title">
            Add people
          </h2>
          {orgMembers.loading && !orgMembers.data ? (
            <SkeletonRows rows={2} label="Loading organization members" />
          ) : orgMembers.error ? (
            <ErrorState error={orgMembers.error} onRetry={orgMembers.reload} />
          ) : (
            <form onSubmit={addMembers} noValidate className="form form-wide">
              <CheckList
                legend="People"
                options={candidates.map((m) => ({ value: m.user.id, label: m.user.name || m.user.email, meta: `${m.user.email} · ${roleLabel(m.role)}` }))}
                selected={picked}
                onChange={(v) => {
                  setPicked(v);
                  setAddError(null);
                }}
                error={addError}
                empty="Everyone in the organization is already in this team."
              />
              <div>
                <Button type="submit" busy={addBusy} disabled={candidates.length === 0}>
                  Add to team
                </Button>
              </div>
            </form>
          )}
        </section>
      )}

      <section aria-labelledby="team-members">
        <h2 id="team-members">Members</h2>
        {members.loading && !members.data ? (
          <SkeletonRows label="Loading team members" />
        ) : members.error ? (
          <ErrorState error={members.error} onRetry={members.reload} />
        ) : (
          <DataTable
            caption={`Members of ${team.name}`}
            columns={columns}
            rows={members.data ?? []}
            rowKey={(m) => m.user_id}
            empty={<EmptyState title="This team has no members yet." />}
          />
        )}
      </section>
      <ConfirmDialog
        open={removing !== null}
        title="Remove from team?"
        confirmLabel="Remove"
        danger
        busy={removeBusy}
        error={removeError}
        onConfirm={() => void confirmRemove()}
        onCancel={() => setRemoving(null)}
      >
        <p>
          {removing ? (
            <>
              <strong>{removing.name || removing.email}</strong> will lose access to agents given to {team.name}. Agents assigned to them
              directly are not affected.
            </>
          ) : null}
        </p>
      </ConfirmDialog>
    </>
  );
}

export default function TeamDetailPage() {
  return (
    <OrgGate permission="teams.view">
      {(m) => (
        <WithQuery>
          {(params) => {
            const id = params.get('id');
            return id ? <TeamDetail key={id} membership={m} teamId={id} /> : <NotFoundState message="No team was chosen." />;
          }}
        </WithQuery>
      )}
    </OrgGate>
  );
}

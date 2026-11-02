'use client';

import { useState } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { formatDate } from '@/lib/format';
import { canManageMember, grantableRoles, roleLabel } from '@/lib/roles';
import { useSession } from '@/lib/session';
import type { Member, Membership, Role } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { FormError, FormSuccess, SelectField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

function RoleControl({ member, actorRole, onSave }: { member: Member; actorRole: Role; onSave: (role: Role) => Promise<void> }) {
  const [value, setValue] = useState<Role>(member.role);
  const [busy, setBusy] = useState(false);
  const roles = grantableRoles(actorRole);
  // The current role is always listed so the select shows it, even if the actor could not grant it.
  const options = (roles.includes(member.role) ? roles : [member.role, ...roles]).map((r) => ({ value: r, label: roleLabel(r) }));
  const who = member.user.name || member.user.email;

  return (
    <form
      className="inline-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (value === member.role) return;
        setBusy(true);
        try {
          await onSave(value);
        } finally {
          setBusy(false);
        }
      }}
    >
      <SelectField label={`Role for ${who}`} hideLabel options={options} value={value} onChange={(e) => setValue(e.target.value as Role)} />
      <Button type="submit" size="sm" variant="secondary" busy={busy} disabled={value === member.role}>
        Save
      </Button>
    </form>
  );
}

function Members({ membership }: { membership: Membership }) {
  const { me } = useSession();
  const orgId = membership.organization.id;
  const canManage = membership.permissions.includes('members.manage');
  const { data, error, loading, reload, setData } = useLoad(() => api.get<Member[]>(`/organizations/${seg(orgId)}/members`), orgId);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  async function changeRole(member: Member, role: Role) {
    setActionError(null);
    setNotice(null);
    try {
      const updated = await api.patch<Member>(`/organizations/${seg(orgId)}/members/${seg(member.membership_id)}`, { role });
      setData((rows) => (rows ?? []).map((r) => (r.membership_id === updated.membership_id ? updated : r)));
      setNotice(`${updated.user.name || updated.user.email} is now ${roleLabel(updated.role)}.`);
    } catch (e) {
      setActionError(errorMessage(e));
      throw e;
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      await api.delete(`/organizations/${seg(orgId)}/members/${seg(removing.membership_id)}`);
      setData((rows) => (rows ?? []).filter((r) => r.membership_id !== removing.membership_id));
      setNotice(`${removing.user.name || removing.user.email} was removed.`);
      setRemoving(null);
    } catch (e) {
      setRemoveError(errorMessage(e));
    } finally {
      setRemoveBusy(false);
    }
  }

  const columns: Column<Member>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (m) => (
        <>
          <span className="cell-strong">{m.user.name || '—'}</span>
          {m.user.id === me.user.id && <span className="badge">You</span>}
        </>
      ),
    },
    { key: 'email', header: 'Email', render: (m) => <span className="break">{m.user.email}</span> },
    {
      key: 'role',
      header: 'Role',
      render: (m) =>
        canManage && m.user.id !== me.user.id && canManageMember(membership.role, m.role) ? (
          <RoleControl key={`${m.membership_id}:${m.role}`} member={m} actorRole={membership.role} onSave={(r) => changeRole(m, r).catch(() => undefined)} />
        ) : (
          roleLabel(m.role)
        ),
    },
    { key: 'joined', header: 'Joined', render: (m) => formatDate(m.joined_at) },
  ];
  if (canManage) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (m) =>
        m.user.id !== me.user.id && canManageMember(membership.role, m.role) ? (
          <Button
            size="sm"
            variant="danger"
            onClick={() => {
              setRemoveError(null);
              setRemoving(m);
            }}
            aria-label={`Remove ${m.user.name || m.user.email}`}
          >
            Remove
          </Button>
        ) : null,
    });
  }

  return (
    <>
      <PageHeader title="Members" description={`People in ${membership.organization.name}.`} />
      <FormError message={actionError} />
      <FormSuccess message={notice} />
      {loading && !data ? (
        <SkeletonRows label="Loading members" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <DataTable
          caption={`Members of ${membership.organization.name}`}
          columns={columns}
          rows={data ?? []}
          rowKey={(m) => m.membership_id}
          empty={<EmptyState title="There are no members yet." />}
        />
      )}
      <ConfirmDialog
        open={removing !== null}
        title="Remove member?"
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
              <strong>{removing.user.name || removing.user.email}</strong> ({removing.user.email}) will lose access to{' '}
              {membership.organization.name}. You can invite them again later.
            </>
          ) : null}
        </p>
      </ConfirmDialog>
    </>
  );
}

export default function UsersPage() {
  return <OrgGate permission="members.view">{(m) => <Members membership={m} />}</OrgGate>;
}

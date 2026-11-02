'use client';

import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { capitalize, formatDateTime } from '@/lib/format';
import { grantableRoles, roleLabel } from '@/lib/roles';
import type { Invitation, IssuedInvitation, Membership, Role } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { FormError, SelectField, TextField } from '@/components/Field';
import { OneTimeLink } from '@/components/OneTimeLink';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';
import { WithQuery } from '@/components/WithQuery';

const STATUS_BADGE: Record<string, string> = {
  pending: 'badge badge-info',
  accepted: 'badge badge-ok',
  revoked: 'badge',
  expired: 'badge badge-warn',
};

function Invitations({ membership, initialRole }: { membership: Membership; initialRole: Role | null }) {
  const orgId = membership.organization.id;
  const roles = grantableRoles(membership.role);
  const { data, error, loading, reload } = useLoad(() => api.get<Invitation[]>(`/organizations/${seg(orgId)}/invitations`), orgId);

  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>(initialRole && roles.includes(initialRole) ? initialRole : roles.includes('trainee') ? 'trainee' : roles[0] ?? 'trainee');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedInvitation | null>(null);

  const [revoking, setRevoking] = useState<Invitation | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [resendingId, setResendingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  async function issue(targetEmail: string, targetRole: Role) {
    const inv = await api.post<IssuedInvitation>(`/organizations/${seg(orgId)}/invitations`, { email: targetEmail, role: targetRole });
    setIssued(inv);
    reload();
    return inv;
  }

  async function onInvite(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!email.trim()) return setFormError('Enter an email address.');
    setBusy(true);
    try {
      await issue(email.trim(), role);
      setEmail('');
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function resend(inv: Invitation) {
    setRowError(null);
    setResendingId(inv.id);
    try {
      await issue(inv.email, inv.role);
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setResendingId(null);
    }
  }

  async function confirmRevoke() {
    if (!revoking) return;
    setRevokeBusy(true);
    setRevokeError(null);
    try {
      await api.post(`/organizations/${seg(orgId)}/invitations/${seg(revoking.id)}/revoke`);
      setRevoking(null);
      reload();
    } catch (err) {
      setRevokeError(errorMessage(err));
    } finally {
      setRevokeBusy(false);
    }
  }

  const columns: Column<Invitation>[] = [
    { key: 'email', header: 'Email', render: (i) => <span className="break">{i.email}</span> },
    { key: 'role', header: 'Role', render: (i) => roleLabel(i.role) },
    { key: 'status', header: 'Status', render: (i) => <span className={STATUS_BADGE[i.status] ?? 'badge'}>{capitalize(i.status)}</span> },
    { key: 'sent', header: 'Sent', render: (i) => formatDateTime(i.created_at) },
    { key: 'expires', header: 'Expires', render: (i) => (i.status === 'pending' || i.status === 'expired' ? formatDateTime(i.expires_at) : '—') },
    {
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (i) => {
        const allowed = roles.includes(i.role);
        if (!allowed || (i.status !== 'pending' && i.status !== 'expired')) return null;
        return (
          <div className="row row-end">
            <Button size="sm" variant="secondary" busy={resendingId === i.id} onClick={() => void resend(i)} aria-label={`Send a new link to ${i.email}`}>
              New link
            </Button>
            {i.status === 'pending' && (
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  setRevokeError(null);
                  setRevoking(i);
                }}
                aria-label={`Revoke invitation for ${i.email}`}
              >
                Revoke
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <>
      <PageHeader title={role === 'trainee' ? 'Add a trainee' : 'Invite people'} description={`Send a secure activation link to join ${membership.organization.name}.`} />

      {issued && <OneTimeLink url={issued.accept_url} email={issued.email} emailed={issued.emailed} onDismiss={() => setIssued(null)} />}

      <section className="panel" aria-labelledby="invite-title">
        <h2 id="invite-title" className="panel-title">
          {role === 'trainee' ? 'Trainee details' : 'Invitation details'}
        </h2>
        {roles.length === 0 ? (
          <p>Your role cannot send invitations.</p>
        ) : (
          <form onSubmit={onInvite} noValidate className="form form-inline">
            <FormError message={formError} />
            <TextField label="Email" type="email" autoComplete="off" required value={email} onChange={(e) => setEmail(e.target.value)} maxLength={320} />
            <SelectField label="Role" options={roles.map((r) => ({ value: r, label: roleLabel(r) }))} value={role} onChange={(e) => setRole(e.target.value as Role)} />
            <Button type="submit" busy={busy}>
              {role === 'trainee' ? 'Invite trainee' : 'Send invitation'}
            </Button>
          </form>
        )}
        <p className="field-hint">Inviting an email that already has a pending invitation replaces its link with a new one.</p>
      </section>

      <section aria-labelledby="inv-list-title">
        <h2 id="inv-list-title">All invitations</h2>
        <FormError message={rowError} />
        {loading && !data ? (
          <SkeletonRows label="Loading invitations" />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <DataTable
            caption="Invitations"
            columns={columns}
            rows={data ?? []}
            rowKey={(i) => i.id}
            empty={<EmptyState title="No invitations have been sent yet." />}
          />
        )}
      </section>

      <ConfirmDialog
        open={revoking !== null}
        title="Revoke invitation?"
        confirmLabel="Revoke"
        danger
        busy={revokeBusy}
        error={revokeError}
        onConfirm={() => void confirmRevoke()}
        onCancel={() => setRevoking(null)}
      >
        <p>{revoking ? <>The link sent to <strong>{revoking.email}</strong> will stop working.</> : null}</p>
      </ConfirmDialog>
    </>
  );
}

export default function InvitationsPage() {
  return <OrgGate permission="invitations.manage">{(m) => <WithQuery>{(params) => {
    const requested = params.get('role');
    const initialRole = requested === 'trainee' || requested === 'trainer' ? requested : null;
    return <Invitations membership={m} initialRole={initialRole} />;
  }}</WithQuery>}</OrgGate>;
}

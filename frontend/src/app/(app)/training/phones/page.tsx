'use client';

import { useState } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { formatDateTime } from '@/lib/format';
import { roleLabel } from '@/lib/roles';
import type { MemberPhone, Membership } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { FormSuccess, SelectField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

const FILTERS = [
  { value: 'pending', label: 'Waiting for verification' },
  { value: 'verified', label: 'Verified' },
  { value: 'saved', label: 'Everyone with a number' },
  { value: 'all', label: 'Everyone' },
];

function Phones({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const { data, error, loading, reload } = useLoad(() => api.get<MemberPhone[]>(orgPath(orgId, '/training/phones')), orgId);
  const [filter, setFilter] = useState('pending');
  const [notice, setNotice] = useState<string | null>(null);

  const [verifying, setVerifying] = useState<MemberPhone | null>(null);
  const [typed, setTyped] = useState('');
  const [removing, setRemoving] = useState<MemberPhone | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const rows = (data ?? []).filter((p) => {
    if (filter === 'pending') return !!p.phone && !p.verified;
    if (filter === 'verified') return p.verified;
    if (filter === 'saved') return !!p.phone;
    return true;
  });

  async function confirmVerify() {
    if (!verifying) return;
    if (!typed.trim()) return setDialogError('Type the number you confirmed with this person.');
    setBusy(true);
    setDialogError(null);
    try {
      await api.post(orgPath(orgId, `/members/${seg(verifying.membership_id)}/verify-phone`), { phone: typed.trim() });
      setNotice(`The number for ${verifying.email} is verified. The agent can now call them.`);
      setVerifying(null);
      reload();
    } catch (e) {
      setDialogError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    setBusy(true);
    setDialogError(null);
    try {
      await api.delete(orgPath(orgId, `/members/${seg(removing.membership_id)}/verify-phone`));
      setNotice(`Verification was removed for ${removing.email}.`);
      setRemoving(null);
      reload();
    } catch (e) {
      setDialogError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<MemberPhone>[] = [
    {
      key: 'who',
      header: 'Member',
      render: (p) => (
        <>
          <span className="cell-strong break">{p.name || p.email}</span>
          {p.name && <span className="small muted break"> {p.email}</span>}
        </>
      ),
    },
    { key: 'role', header: 'Role', render: (p) => roleLabel(p.role) },
    { key: 'phone', header: 'Phone', render: (p) => (p.phone ? <span className="mono">{p.phone}</span> : <span className="muted">Not saved</span>) },
    {
      key: 'state',
      header: 'Verification',
      render: (p) =>
        p.verified ? (
          <>
            <span className="badge badge-ok">Verified</span>
            {p.verification_method && (
              <span className="small"> {p.verification_method === 'otp' ? 'With a code sent to the phone' : 'Confirmed by an admin'}</span>
            )}
            {p.verified_at && <span className="small muted"> {formatDateTime(p.verified_at)}</span>}
          </>
        ) : p.phone ? (
          <span className="badge badge-warn">Not verified</span>
        ) : (
          <span className="badge">No number</span>
        ),
    },
    {
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (p) =>
        p.verified ? (
          <Button
            size="sm"
            variant="danger"
            aria-label={`Remove verification for ${p.email}`}
            onClick={() => {
              setNotice(null);
              setDialogError(null);
              setRemoving(p);
            }}
          >
            Remove verification
          </Button>
        ) : p.phone ? (
          <Button
            size="sm"
            variant="secondary"
            aria-label={`Verify the number for ${p.email}`}
            onClick={() => {
              setNotice(null);
              setDialogError(null);
              setTyped('');
              setVerifying(p);
            }}
          >
            Verify
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        title="Phone numbers"
        description="Trainees save their own mobile number. Confirm it with them (for example by calling it), then verify it here so the agent can call them."
      />
      <FormSuccess message={notice} />
      <div className="filters">
        <SelectField label="Show" options={FILTERS} value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      {loading && !data ? (
        <SkeletonRows label="Loading phone numbers" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <DataTable
          caption="Members' phone numbers"
          columns={columns}
          rows={rows}
          rowKey={(p) => p.membership_id}
          empty={
            <EmptyState title={filter === 'pending' ? 'No numbers are waiting for verification.' : 'Nobody matches this filter.'}>
              <p>Members add their number on their profile page.</p>
            </EmptyState>
          }
        />
      )}

      <ConfirmDialog
        open={verifying !== null}
        title="Verify phone number"
        confirmLabel="Verify"
        busy={busy}
        error={dialogError}
        onConfirm={() => void confirmVerify()}
        onCancel={() => setVerifying(null)}
      >
        <div className="inline-form">
          <p>
            Type the number you confirmed with <strong className="break">{verifying?.email}</strong>. It must match the number they saved.
          </p>
          <TextField
            label="Phone number"
            type="tel"
            inputMode="tel"
            autoComplete="off"
            maxLength={30}
            hint="A 10-digit Indian mobile number."
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={removing !== null}
        title="Remove verification?"
        confirmLabel="Remove verification"
        danger
        busy={busy}
        error={dialogError}
        onConfirm={() => void confirmRemove()}
        onCancel={() => setRemoving(null)}
      >
        <p>
          The agent will not call <strong className="break">{removing?.email}</strong> until their number is verified again. Their saved number is kept.
        </p>
      </ConfirmDialog>
    </>
  );
}

export default function PhonesPage() {
  return <OrgGate permission="training.manage">{(m) => <Phones membership={m} />}</OrgGate>;
}

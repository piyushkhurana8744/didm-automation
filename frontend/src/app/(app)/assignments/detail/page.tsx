'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { ASSIGNMENT_STATE_BADGE, orgPath, settingsSummary } from '@/lib/agents';
import { capitalize, formatDateTime, fromLocalInput, toLocalInput } from '@/lib/format';
import type { Assignment, AssignmentDetail, Membership } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { assigneeLabel } from '@/components/AssignmentList';
import { AssignmentSettingsFields, settingsDraftFrom, settingsFromDraft, type SettingsDraft } from '@/components/AssignmentSettingsFields';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState, NotFoundState } from '@/components/ErrorState';
import { CheckboxField, FormError, FormSuccess, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';
import { WithQuery } from '@/components/WithQuery';

type Errors = Partial<Record<'starts' | 'expires' | 'maxSessions' | 'maxMinutes', string>>;

function EditAssignment({ orgId, assignment, onSaved }: { orgId: string; assignment: Assignment; onSaved: () => void }) {
  const [starts, setStarts] = useState(toLocalInput(assignment.starts_at));
  const [expires, setExpires] = useState(toLocalInput(assignment.expires_at));
  const [noEnd, setNoEnd] = useState(!assignment.expires_at);
  const [settings, setSettings] = useState<SettingsDraft>(settingsDraftFrom(assignment.settings));
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const next: Errors = {};
    const startsIso = fromLocalInput(starts);
    const expiresIso = noEnd ? null : fromLocalInput(expires);
    if (!startsIso) next.starts = 'Enter a valid start date and time.';
    if (!noEnd) {
      if (!expiresIso) next.expires = 'Enter an end date and time, or tick "No end date".';
      else if (startsIso && new Date(expiresIso) <= new Date(startsIso)) next.expires = 'The end must be after the start.';
    }
    const s = settingsFromDraft(settings, true);
    Object.assign(next, s.errors);
    setErrors(next);
    if (Object.keys(next).length) {
      setFormError('Fix the highlighted fields.');
      return;
    }
    setBusy(true);
    try {
      await api.patch<Assignment>(orgPath(orgId, `/assignments/${seg(assignment.id)}`), {
        starts_at: startsIso,
        ...(noEnd ? { clear_expiry: true } : { expires_at: expiresIso }),
        settings: s.settings,
      });
      onSaved();
    } catch (err) {
      setFormError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="form form-wide">
      <FormError message={formError} />
      <div className="form-grid">
        <TextField label="Starts" type="datetime-local" required value={starts} error={errors.starts} onChange={(e) => setStarts(e.target.value)} hint="Your local time." />
        <TextField
          label="Ends"
          type="datetime-local"
          value={noEnd ? '' : expires}
          disabled={noEnd}
          error={errors.expires}
          onChange={(e) => setExpires(e.target.value)}
        />
        <CheckboxField label="No end date" checked={noEnd} onChange={(e) => setNoEnd(e.target.checked)} />
      </div>
      <AssignmentSettingsFields
        orgId={orgId}
        agentId={assignment.agent_id}
        value={settings}
        onChange={setSettings}
        errors={{ maxSessions: errors.maxSessions, maxMinutes: errors.maxMinutes }}
      />
      <div>
        <Button type="submit" busy={busy}>
          Save changes
        </Button>
      </div>
    </form>
  );
}

function AssignmentView({ membership, assignmentId }: { membership: Membership; assignmentId: string }) {
  const orgId = membership.organization.id;
  const { data, error, loading, reload } = useLoad(
    () => api.get<AssignmentDetail>(orgPath(orgId, `/assignments/${seg(assignmentId)}`)),
    `${orgId}|${assignmentId}`,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  async function confirmRevoke() {
    setRevokeBusy(true);
    setRevokeError(null);
    try {
      await api.post(orgPath(orgId, `/assignments/${seg(assignmentId)}/revoke`));
      setRevoking(false);
      setNotice('Access was revoked.');
      reload();
    } catch (e) {
      setRevokeError(errorMessage(e));
    } finally {
      setRevokeBusy(false);
    }
  }

  if (loading && !data) return <Spinner label="Loading assignment" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const open = data.state === 'active' || data.state === 'scheduled';
  const editable = data.state !== 'revoked' && data.state !== 'replaced';
  const who = data.team_id ? `team ${data.team_name ?? ''}` : data.user_email ?? 'this person';

  const historyColumns: Column<Assignment>[] = [
    {
      key: 'created',
      header: 'Assigned',
      render: (h) => (
        <>
          {h.id === data.id ? <span className="cell-strong">{formatDateTime(h.created_at)}</span> : <Link href={`/assignments/detail/?id=${encodeURIComponent(h.id)}`}>{formatDateTime(h.created_at)}</Link>}
          {h.id === data.id && <span className="badge badge-info">This one</span>}
        </>
      ),
    },
    { key: 'state', header: 'State', render: (h) => <span className={ASSIGNMENT_STATE_BADGE[h.state] ?? 'badge'}>{capitalize(h.state)}</span> },
    { key: 'starts', header: 'Starts', render: (h) => formatDateTime(h.starts_at) },
    { key: 'expires', header: 'Ends', render: (h) => (h.expires_at ? formatDateTime(h.expires_at) : 'No end date') },
    { key: 'revoked', header: 'Revoked', render: (h) => (h.revoked_at ? formatDateTime(h.revoked_at) : '—') },
    { key: 'limits', header: 'Limits', render: (h) => <span className="small">{settingsSummary(h.settings)}</span> },
  ];

  return (
    <>
      <p className="small">
        <Link href="/assignments/">← Assignments</Link>
      </p>
      <PageHeader
        title={data.agent_name ?? 'Assignment'}
        description={
          <>
            <span className={ASSIGNMENT_STATE_BADGE[data.state] ?? 'badge'}>{capitalize(data.state)}</span> Assigned to {who}
          </>
        }
        actions={
          open ? (
            <Button
              variant="danger"
              onClick={() => {
                setRevokeError(null);
                setRevoking(true);
              }}
            >
              Revoke access
            </Button>
          ) : undefined
        }
      />
      <FormSuccess message={notice} />
      <section className="panel" aria-labelledby="assignment-facts">
        <h2 id="assignment-facts" className="panel-title">
          Details
        </h2>
        <dl className="facts facts-wide">
          <div>
            <dt>Agent</dt>
            <dd>
              {membership.permissions.includes('agents.view') ? (
                <Link href={`/agents/detail/?id=${encodeURIComponent(data.agent_id)}`}>{data.agent_name ?? data.agent_id}</Link>
              ) : (
                data.agent_name ?? data.agent_id
              )}
            </dd>
          </div>
          <div>
            <dt>Assigned to</dt>
            <dd>{assigneeLabel(data)}</dd>
          </div>
          <div>
            <dt>Starts</dt>
            <dd>{formatDateTime(data.starts_at)}</dd>
          </div>
          <div>
            <dt>Ends</dt>
            <dd>{data.expires_at ? formatDateTime(data.expires_at) : 'No end date'}</dd>
          </div>
          <div>
            <dt>Limits</dt>
            <dd>{settingsSummary(data.settings)}</dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>{formatDateTime(data.created_at)}</dd>
          </div>
          {data.revoked_at && (
            <div>
              <dt>{data.state === 'replaced' ? 'Replaced' : 'Revoked'}</dt>
              <dd>{formatDateTime(data.revoked_at)}</dd>
            </div>
          )}
        </dl>
      </section>
      {editable ? (
        <section className="panel" aria-labelledby="assignment-edit">
          <h2 id="assignment-edit" className="panel-title">
            Change dates and limits
          </h2>
          <EditAssignment
            key={formKey}
            orgId={orgId}
            assignment={data}
            onSaved={() => {
              setNotice('Assignment saved.');
              setFormKey((k) => k + 1);
              reload();
            }}
          />
        </section>
      ) : (
        <p className="field-hint">Revoked assignments cannot be changed. Assign the agent again to give access back.</p>
      )}
      <section aria-labelledby="assignment-history">
        <h2 id="assignment-history">History</h2>
        <p className="muted small">Every assignment of this agent to {who}, newest first.</p>
        <DataTable caption="Assignment history" columns={historyColumns} rows={data.history} rowKey={(h) => h.id} empty={<EmptyState title="No history." />} />
      </section>
      <ConfirmDialog
        open={revoking}
        title="Revoke access?"
        confirmLabel="Revoke"
        danger
        busy={revokeBusy}
        error={revokeError}
        onConfirm={() => void confirmRevoke()}
        onCancel={() => setRevoking(false)}
      >
        <p>
          {data.team_id ? `Members of ${data.team_name ?? 'the team'}` : data.user_email ?? 'This person'} will lose access to{' '}
          <strong>{data.agent_name ?? 'this agent'}</strong> through this assignment. This cannot be undone; assign again to give access back.
        </p>
      </ConfirmDialog>
    </>
  );
}

export default function AssignmentDetailPage() {
  return (
    <OrgGate permission="assignments.manage">
      {(m) => (
        <WithQuery>
          {(params) => {
            const id = params.get('id');
            return id ? <AssignmentView key={id} membership={m} assignmentId={id} /> : <NotFoundState message="No assignment was chosen." />;
          }}
        </WithQuery>
      )}
    </OrgGate>
  );
}

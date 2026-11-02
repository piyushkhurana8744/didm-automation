'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api, errorCode, errorMessage, seg } from '@/lib/api';
import { CHANNEL_LABELS, orgPath } from '@/lib/agents';
import { formatDateTime } from '@/lib/format';
import { CANCELLABLE, eventLabel, formatDuration, shortPhone, statusBadge, statusExplanation, statusLabel } from '@/lib/training';
import type { Permission, TrainingSession, TrainingSessionDetail } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { ConfirmDialog } from '../ConfirmDialog';
import { ErrorState } from '../ErrorState';
import { FormSuccess } from '../Field';
import { PageHeader } from '../PageHeader';
import { Spinner } from '../Spinner';
import { Scorecard } from './Scorecard';

const POLL_MS = 3000;
const CALL_IN_PROGRESS = 'The call is already placed. It ends when the call is hung up.';

export function StatusBadge({ status }: { status: string }) {
  return <span className={statusBadge(status)}>{statusLabel(status)}</span>;
}

/**
 * One training session, refreshed every few seconds until it reaches a final state. Shows status,
 * a timeline and timings; once the session has ended, the scorecard follows below.
 */
export function SessionView({
  orgId,
  sessionId,
  mode,
  canCancel,
  back,
  permissions = [],
}: {
  orgId: string;
  sessionId: string;
  /** `self`: the trainee's own page (offers "Practice again"); `admin`: read-only view for trainers and admins. */
  mode: 'self' | 'admin';
  canCancel: boolean;
  back: { href: string; label: string };
  /** The viewer's permissions, for the scorecard's admin actions. */
  permissions?: Permission[];
}) {
  const path = orgPath(orgId, `/training/sessions/${seg(sessionId)}`);
  const { data, error, loading, reload, setData } = useLoad(() => api.get<TrainingSessionDetail>(path), `${orgId}|${sessionId}`);
  const [pollError, setPollError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const terminal = data ? data.terminal : true;

  // Poll while the session is still open; stop once it is final.
  useEffect(() => {
    if (!data || terminal) return;
    let live = true;
    const timer = window.setTimeout(() => {
      api.get<TrainingSessionDetail>(path).then(
        (next) => {
          if (!live) return;
          setPollError(null);
          setData(next);
        },
        (e: unknown) => {
          if (!live) return;
          setPollError(`Could not refresh the status: ${errorMessage(e)} Trying again…`);
          // Keep polling: a copy of the same data re-arms the timer.
          setData((prev) => ({ ...(prev as TrainingSessionDetail) }));
        },
      );
    }, POLL_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // Re-arms after every response, because each response is a new `data` object.
  }, [data, terminal, path, setData]);

  async function onCancel() {
    setCancelBusy(true);
    setCancelError(null);
    try {
      const next = await api.post<TrainingSession>(`${path}/cancel`);
      setData((prev) => ({ ...(prev as TrainingSessionDetail), ...next }));
      setConfirm(false);
      setNotice('The session was cancelled.');
      reload();
    } catch (e) {
      if (errorCode(e) === 'call_in_progress') {
        setConfirm(false);
        setNotice(null);
        setCancelError(CALL_IN_PROGRESS);
        reload();
      } else {
        setCancelError(errorMessage(e));
      }
    } finally {
      setCancelBusy(false);
    }
  }

  if (loading && !data) return <Spinner label="Loading session" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const s = data;
  const showCancel = canCancel && CANCELLABLE.includes(s.status);
  const events = s.events ?? [];
  const title = `${s.agent_name ?? 'Agent'}${s.scenario_name ? ` · ${s.scenario_name}` : ''}`;

  return (
    <>
      <p className="small">
        <Link href={back.href}>← {back.label}</Link>
      </p>
      <PageHeader
        title={title}
        description={`${CHANNEL_LABELS[s.channel] ?? s.channel} practice · started ${formatDateTime(s.created_at)}`}
        actions={
          <>
            {showCancel && (
              <Button
                variant="danger"
                onClick={() => {
                  setCancelError(null);
                  setConfirm(true);
                }}
              >
                Cancel session
              </Button>
            )}
            {mode === 'self' && s.terminal && (
              <Link href={`/my-training/agent/?id=${encodeURIComponent(s.agent_id)}`} className="btn btn-primary">
                Practice again
              </Link>
            )}
          </>
        }
      />
      <FormSuccess message={notice} />
      {cancelError && !confirm && (
        <div className="alert alert-warn" role="alert">
          {cancelError}
        </div>
      )}

      <section className="panel" aria-labelledby="status-title" aria-live="polite">
        <h2 id="status-title" className="panel-title">
          Status
        </h2>
        <div className="status-hero">
          <p className="status-hero-line">
            <StatusBadge status={s.status} />
            <span>{statusExplanation(s)}</span>
            {!s.terminal && <Spinner label="Checking for updates" inline />}
          </p>
          {s.failure_reason && (s.status === 'failed' || s.status === 'timed_out' || s.status === 'cancelled') && (
            <p className="small">
              <strong>Reason:</strong> {s.failure_reason}
            </p>
          )}
          {!s.terminal && <p className="small muted">This page updates by itself every few seconds.</p>}
          {pollError && <p className="field-hint">{pollError}</p>}
        </div>
      </section>

      <section className="panel" aria-labelledby="details-title">
        <h2 id="details-title" className="panel-title">
          Details
        </h2>
        <dl className="facts">
          {mode === 'admin' && (
            <div>
              <dt>Trainee</dt>
              <dd className="break">{s.user_email ?? s.user_id}</dd>
            </div>
          )}
          <div>
            <dt>Agent</dt>
            <dd>{s.agent_name ?? s.agent_id}</dd>
          </div>
          <div>
            <dt>Scenario</dt>
            <dd>{s.scenario_name ?? 'None'}</dd>
          </div>
          <div>
            <dt>Channel</dt>
            <dd>
              {CHANNEL_LABELS[s.channel] ?? s.channel}
              {s.channel === 'phone' && shortPhone(s.phone) ? ` to ${shortPhone(s.phone)}` : ''}
            </dd>
          </div>
          {s.max_duration_seconds ? (
            <div>
              <dt>Time limit</dt>
              <dd>Up to {formatDuration(s.max_duration_seconds)}</dd>
            </div>
          ) : null}
          {s.connected_at && (
            <div>
              <dt>Connected</dt>
              <dd>{formatDateTime(s.connected_at)}</dd>
            </div>
          )}
          {s.ended_at && (
            <div>
              <dt>Ended</dt>
              <dd>{formatDateTime(s.ended_at)}</dd>
            </div>
          )}
          {s.duration_seconds !== null && s.duration_seconds !== undefined && (
            <div>
              <dt>Duration</dt>
              <dd>{formatDuration(s.duration_seconds)}</dd>
            </div>
          )}
          {mode === 'admin' && s.billable_seconds !== null && s.billable_seconds !== undefined && (
            <div>
              <dt>Billable</dt>
              <dd>{formatDuration(s.billable_seconds)}</dd>
            </div>
          )}
          {mode === 'admin' && s.failure_code && (
            <div>
              <dt>Failure code</dt>
              <dd className="mono">{s.failure_code}</dd>
            </div>
          )}
          {mode === 'admin' && s.provider_app_version !== null && s.provider_app_version !== undefined && (
            <div>
              <dt>Sarvam app version</dt>
              <dd>{s.provider_app_version}</dd>
            </div>
          )}
        </dl>
      </section>

      <section className="panel" aria-labelledby="timeline-title">
        <h2 id="timeline-title" className="panel-title">
          Timeline
        </h2>
        {events.length === 0 ? (
          <p className="muted">Nothing has happened yet.</p>
        ) : (
          <ol className="timeline">
            {events.map((e, i) => (
              <li key={`${e.type}-${i}`}>
                <span>{eventLabel(e.type)}</span>
                <span className="small muted">{formatDateTime(e.at)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {s.terminal && <Scorecard key={s.id} orgId={orgId} sessionId={s.id} mode={mode} permissions={permissions} />}

      <ConfirmDialog
        open={confirm}
        title="Cancel this session?"
        confirmLabel="Cancel session"
        cancelLabel="Keep it"
        danger
        busy={cancelBusy}
        error={cancelError}
        onConfirm={() => void onCancel()}
        onCancel={() => setConfirm(false)}
      >
        <p>The call has not been placed yet. Cancelling stops it from being placed. You can start a new session afterwards.</p>
      </ConfirmDialog>
    </>
  );
}

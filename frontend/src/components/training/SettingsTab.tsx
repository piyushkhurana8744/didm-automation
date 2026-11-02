'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath, parseOptionalInt } from '@/lib/agents';
import { formatDate, formatDateTime, plural } from '@/lib/format';
import { intelligenceApi, RETENTION_CATEGORIES, RETENTION_CATEGORY_LABELS } from '@/lib/intelligence';
import type { EvaluationBudget, RetentionCategory, RetentionCount, RetentionRun, Rubric, TrainingSettings } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { DataTable, type Column } from '../DataTable';
import { EmptyState } from '../EmptyState';
import { ErrorState } from '../ErrorState';
import { CheckboxField, FormError, FormSuccess, SelectField, TextAreaField, TextField } from '../Field';
import { SkeletonRows } from '../Spinner';
import { Bar } from './ProgressView';

function yesNo(v: boolean, on = 'Yes', off = 'No') {
  return <span className={v ? 'badge badge-ok' : 'badge'}>{v ? on : off}</span>;
}

function EvaluationStatus({ s }: { s: TrainingSettings }) {
  const e = s.evaluation;
  return (
    <section className="panel" aria-labelledby="set-eval">
      <h2 id="set-eval" className="panel-title">
        Evaluation
      </h2>
      <dl className="facts facts-wide">
        <div>
          <dt>Allowed by the platform</dt>
          <dd>{yesNo(e.allowed)}</dd>
        </div>
        <div>
          <dt>Evaluator set up</dt>
          <dd>{yesNo(e.evaluator_configured)}</dd>
        </div>
        <div>
          <dt>Sessions are scored</dt>
          <dd>{yesNo(e.active, 'Yes', 'No')}</dd>
        </div>
        {e.evaluator_configured && (
          <div>
            <dt>Evaluator</dt>
            <dd>
              {[e.evaluator, e.model].filter(Boolean).join(' ') || 'Unknown'} <span className="small muted">({e.evaluator_version})</span>
            </dd>
          </div>
        )}
        <div>
          <dt>Call checks with Sarvam</dt>
          <dd>{yesNo(s.provider_lookups, 'Set up', 'Not set up')}</dd>
        </div>
        <div>
          <dt>Phone codes by message</dt>
          <dd>{yesNo(s.phone_otp, 'Available', 'Not available')}</dd>
        </div>
      </dl>
      {(!e.active || e.reason) && (
        <p className="small muted">
          {e.reason ||
            (!e.allowed ? 'The platform administrator has not switched on evaluation for this organization.' : 'No evaluator is set up on the platform yet.')}{' '}
          Sessions still run; they are just not scored.
        </p>
      )}
      {e.budget && <BudgetUsage b={e.budget} />}
    </section>
  );
}

function BudgetUsage({ b }: { b: EvaluationBudget }) {
  return (
    <>
      <h3 className="feedback-title">Evaluation use this month</h3>
      <dl className="facts facts-wide">
        <div>
          <dt>Evaluator calls</dt>
          <dd>
            {b.calls.toLocaleString()} of {b.call_limit.toLocaleString()}
            <Bar value={b.calls} max={b.call_limit} label={`${b.calls} of ${b.call_limit} evaluator calls used this month`} />
          </dd>
        </div>
        <div>
          <dt>Evaluator tokens</dt>
          <dd>
            {b.tokens.toLocaleString()} of {b.token_limit.toLocaleString()}
            <Bar value={b.tokens} max={b.token_limit} label={`${b.tokens} of ${b.token_limit} evaluator tokens used this month`} />
          </dd>
        </div>
      </dl>
      <p className="small muted">
        Since {formatDate(b.month_start)}. Each session uses at most {plural(b.max_calls_per_session, 'call')}. When a limit is reached, sessions are not
        scored until next month; the platform administrator can raise the limits.
      </p>
    </>
  );
}

function rubricOptions(rubrics: Rubric[] | null | undefined, current: string | null) {
  const list = (rubrics ?? []).filter((r) => r.status === 'active' || r.id === current);
  return [
    { value: '', label: 'None' },
    ...list.map((r) => ({
      value: r.id,
      label: `${r.name}${r.published_version ? ` (version ${r.published_version})` : ' (not published yet)'}${r.status === 'archived' ? ' (archived)' : ''}`,
    })),
  ];
}

function ReadOnlySettings({ s, rubrics }: { s: TrainingSettings; rubrics: Rubric[] | null | undefined }) {
  const r = s.recording;
  const rubric = (rubrics ?? []).find((x) => x.id === s.default_rubric_id);
  return (
    <section className="panel" aria-labelledby="set-org">
      <h2 id="set-org" className="panel-title">
        Organization settings
      </h2>
      <p className="small muted">Only admins can change these.</p>
      <dl className="facts facts-wide">
        <div>
          <dt>Default rubric</dt>
          <dd>{s.default_rubric_id ? (rubric ? <Link href={`/rubrics/detail/?id=${encodeURIComponent(rubric.id)}`}>{rubric.name}</Link> : 'Set') : 'None'}</dd>
        </div>
        <div>
          <dt>Recordings</dt>
          <dd>
            {yesNo(r.available, 'On', 'Off')} {r.reason && <span className="small muted">{r.reason}</span>}
          </dd>
        </div>
        <div>
          <dt>Kept for</dt>
          <dd>{r.retention_days} days</dd>
        </div>
        <div>
          <dt>Recording storage</dt>
          <dd>{r.provider === 'cloudinary' ? 'Cloudinary' : r.provider === 's3' ? 'S3-compatible' : 'Disabled'}</dd>
        </div>
        <div>
          <dt>Consent notice</dt>
          <dd>{r.consent_text ? <span className="pre-line">{r.consent_text}</span> : <span className="muted">Not written yet</span>}</dd>
        </div>
        <div>
          <dt>Practice call notice</dt>
          <dd>{s.practice_notice?.text ? <span className="pre-line">{s.practice_notice.text}</span> : <span className="muted">None</span>}</dd>
        </div>
        {s.retention && (
          <>
            <div>
              <dt>Transcripts kept for</dt>
              <dd>{s.retention.transcript_retention_days ? plural(s.retention.transcript_retention_days, 'day') : 'Indefinitely'}</dd>
            </div>
            <div>
              <dt>Legal hold</dt>
              <dd>{yesNo(s.retention.legal_hold, 'On', 'Off')}</dd>
            </div>
          </>
        )}
      </dl>
    </section>
  );
}

function SettingsForm({
  orgId,
  initial,
  rubrics,
  onSaved,
}: {
  orgId: string;
  initial: TrainingSettings;
  rubrics: Rubric[] | null | undefined;
  onSaved: (s: TrainingSettings) => void;
}) {
  const [settings, setSettings] = useState(initial);
  const [rubricId, setRubricId] = useState(initial.default_rubric_id ?? '');
  const [enabled, setEnabled] = useState(initial.recording.enabled);
  const [consent, setConsent] = useState(initial.recording.consent_text ?? '');
  const [retention, setRetention] = useState(String(initial.recording.retention_days));
  const [storageProvider, setStorageProvider] = useState(initial.recording.provider ?? '');
  const [retentionError, setRetentionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const r = settings.recording;
  const toggleDisabled = !r.allowed && !enabled;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    const days = parseOptionalInt(retention);
    if (days === undefined || Number.isNaN(days) || days < 1 || days > 365) {
      setRetentionError('A whole number of days from 1 to 365.');
      return setError('Some of the values are not valid.');
    }
    setRetentionError(null);
    if (enabled && !consent.trim()) return setError('Write the consent notice trainees must accept before switching recordings on.');
    const body: Record<string, unknown> = {
      recording_enabled: enabled,
      recording_retention_days: days,
      consent_text: consent,
    };
    if (storageProvider) body.storage_provider = storageProvider;
    if (rubricId) body.default_rubric_id = rubricId;
    else body.clear_default_rubric = true;
    setBusy(true);
    try {
      const next = await intelligenceApi.saveSettings(orgId, body);
      setSettings(next);
      setEnabled(next.recording.enabled);
      setConsent(next.recording.consent_text ?? '');
      setRetention(String(next.recording.retention_days));
      setStorageProvider(next.recording.provider ?? '');
      setRubricId(next.default_rubric_id ?? '');
      setSaved('Training settings saved.');
      onSaved(next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const consentChanged = consent.trim() !== (settings.recording.consent_text ?? '').trim();

  return (
    <form onSubmit={onSubmit} noValidate className="form form-wide">
      <FormError message={error} />
      <FormSuccess message={saved} />
      <section className="panel" aria-labelledby="set-rubric">
        <h2 id="set-rubric" className="panel-title">
          Default rubric
        </h2>
        <SelectField
          label="Rubric for scenarios without their own"
          options={rubricOptions(rubrics, settings.default_rubric_id)}
          value={rubricId}
          onChange={(e) => setRubricId(e.target.value)}
          hint={
            <>
              Its latest published version is used. Manage rubrics on the <Link href="/rubrics/">Rubrics</Link> page.
            </>
          }
        />
      </section>

      <section className="panel" aria-labelledby="set-rec">
        <h2 id="set-rec" className="panel-title">
          Recordings
        </h2>
        <p className="status-hero-line small">
          {yesNo(r.available, 'Recording now', 'Not recording')}
          {r.reason && <span>{r.reason}</span>}
        </p>
        <CheckboxField
          label="Record practice sessions when the trainee agrees"
          checked={enabled}
          disabled={toggleDisabled}
          hint={!r.allowed ? 'Recordings are not allowed for this organization. The platform administrator can allow them.' : 'Trainees are asked each time and can say no.'}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <SelectField
          label="Recording storage"
          value={storageProvider}
          options={r.allowed_providers.map((value) => ({
            value,
            label: value === 'cloudinary' ? 'Cloudinary' : 'Amazon S3 / S3-compatible / Cloudflare R2',
          }))}
          disabled={!r.allowed_providers.length}
          hint="The platform administrator controls the available providers. Existing recordings stay with their original provider."
          onChange={(e) => setStorageProvider(e.target.value)}
        />
        <TextAreaField
          label="Consent notice"
          rows={4}
          maxLength={4000}
          value={consent}
          onChange={(e) => setConsent(e.target.value)}
          hint="Trainees read this and tick a box before a recorded session. If you change it, everyone is asked again."
        />
        {consentChanged && settings.recording.consent_text && <p className="field-hint">Saving a new notice means earlier consent no longer counts.</p>}
        <TextField
          label="Keep recordings for (days)"
          inputMode="numeric"
          value={retention}
          error={retentionError}
          hint="From 1 to 365 days. Recordings are deleted after this."
          onChange={(e) => setRetention(e.target.value)}
        />
      </section>
      <div>
        <Button type="submit" busy={busy}>
          Save settings
        </Button>
      </div>
    </form>
  );
}

function PracticeNoticeForm({ orgId, initial, onSaved }: { orgId: string; initial: TrainingSettings; onSaved: (s: TrainingSettings) => void }) {
  const [current, setCurrent] = useState(initial.practice_notice?.text ?? '');
  const [text, setText] = useState(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    setBusy(true);
    try {
      const next = await intelligenceApi.saveSettings(orgId, { practice_notice_text: text });
      const nextText = next.practice_notice?.text ?? '';
      setCurrent(nextText);
      setText(nextText);
      setSaved(nextText ? 'Practice call notice saved.' : 'Practice call notice removed.');
      onSaved(next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const changed = text.trim() !== current.trim();

  return (
    <form onSubmit={onSubmit} noValidate className="form form-wide">
      <section className="panel" aria-labelledby="set-notice">
        <h2 id="set-notice" className="panel-title">
          Practice call notice
        </h2>
        <FormError message={error} />
        <FormSuccess message={saved} />
        <TextAreaField
          label="Notice shown before every practice call"
          rows={4}
          maxLength={4000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          hint="Trainees must read this and tick a box before each call starts. Leave it empty and save to remove the notice."
        />
        {changed && current && <p className="field-hint">{text.trim() ? 'Trainees will be asked to accept the new notice.' : 'Saving removes the notice.'}</p>}
        <div>
          <Button type="submit" busy={busy} disabled={!changed}>
            Save notice
          </Button>
        </div>
      </section>
    </form>
  );
}

function platformPeriod(days: number | null | undefined): string {
  return days ? plural(days, 'day') : 'Not set';
}

function RetentionForm({ orgId, initial, onSaved }: { orgId: string; initial: TrainingSettings; onSaved: (s: TrainingSettings) => void }) {
  const [settings, setSettings] = useState(initial);
  const ret = settings.retention;
  const [keep, setKeep] = useState(!ret?.transcript_retention_days);
  const [days, setDays] = useState(ret?.transcript_retention_days ? String(ret.transcript_retention_days) : '');
  const [daysError, setDaysError] = useState<string | null>(null);
  const [hold, setHold] = useState(!!ret?.legal_hold);
  const [reason, setReason] = useState('');
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  if (!ret) return null;
  const wasHeld = ret.legal_hold;
  const settingHold = hold && !wasHeld;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    const body: Record<string, unknown> = {};
    let bad = false;
    if (keep) {
      body.keep_transcripts = true;
      setDaysError(null);
    } else {
      const n = parseOptionalInt(days);
      if (n === undefined || Number.isNaN(n) || n < 7 || n > 3650) {
        setDaysError('A whole number of days from 7 to 3,650.');
        bad = true;
      } else {
        setDaysError(null);
        body.transcript_retention_days = n;
      }
    }
    if (settingHold && !reason.trim()) {
      setReasonError('Give a reason for the legal hold.');
      bad = true;
    } else setReasonError(null);
    if (bad) return setError('Some of the values are not valid.');
    if (hold !== wasHeld) {
      body.legal_hold = hold;
      if (hold) body.legal_hold_reason = reason.trim();
    }
    setBusy(true);
    try {
      const next = await intelligenceApi.saveSettings(orgId, body);
      setSettings(next);
      const r = next.retention;
      setKeep(!r?.transcript_retention_days);
      setDays(r?.transcript_retention_days ? String(r.transcript_retention_days) : '');
      setHold(!!r?.legal_hold);
      setReason('');
      setSaved('Retention settings saved.');
      onSaved(next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="form form-wide">
      <section className="panel" aria-labelledby="set-retention">
        <h2 id="set-retention" className="panel-title">
          Data retention
        </h2>
        <FormError message={error} />
        <FormSuccess message={saved} />
        {ret.enforcement_enabled ? (
          <p className="small muted">The daily retention job removes data once it is older than the periods below.</p>
        ) : (
          <div className="alert alert-info" role="note">
            Retention is in report-only mode on this platform. The daily job only reports what is due; nothing is removed except recordings past their
            retention date.
          </div>
        )}
        <CheckboxField label="Keep transcripts indefinitely" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
        {!keep && (
          <TextField
            label="Keep transcripts for (days)"
            inputMode="numeric"
            value={days}
            error={daysError}
            hint="From 7 to 3,650 days. When a transcript is removed, quotes and explanations in its scorecard go too; scores and coaching feedback stay."
            onChange={(e) => setDays(e.target.value)}
          />
        )}
        <dl className="facts facts-wide">
        <div>
          <dt>Recordings</dt>
            <dd>{plural(ret.recording_retention_days, 'day')} (set under Recordings)</dd>
          </div>
          <div>
            <dt>Call result messages from Sarvam</dt>
            <dd>{platformPeriod(ret.platform.webhook_payload_days)}</dd>
          </div>
          <div>
            <dt>Browser session passes</dt>
            <dd>{platformPeriod(ret.platform.browser_token_days)}</dd>
          </div>
          <div>
            <dt>Phone verification codes</dt>
            <dd>{platformPeriod(ret.platform.phone_challenge_days)}</dd>
          </div>
        </dl>
        <p className="small muted">The last three are set by the platform.</p>

        <h3 className="feedback-title">Legal hold</h3>
        {ret.legal_hold && (
          <p className="small">
            {yesNo(true, 'On hold')} {ret.legal_hold_reason && <span className="pre-line">{ret.legal_hold_reason}</span>}
            {ret.legal_hold_set_at && <span className="muted"> · since {formatDateTime(ret.legal_hold_set_at)}</span>}
          </p>
        )}
        <CheckboxField
          label="Place this organization's training data on legal hold"
          checked={hold}
          onChange={(e) => setHold(e.target.checked)}
          hint="While on hold, nothing is removed, including recordings. Untick and save to release the hold."
        />
        {settingHold && (
          <TextAreaField
            label="Reason for the hold"
            rows={2}
            maxLength={500}
            value={reason}
            error={reasonError}
            onChange={(e) => setReason(e.target.value)}
            hint="Required. Recorded in the audit log."
          />
        )}
        {ret.legal_hold && !hold && <p className="field-hint">Saving releases the hold. Data already past its period becomes due for removal.</p>}
        <div>
          <Button type="submit" busy={busy}>
            Save retention settings
          </Button>
        </div>
      </section>
    </form>
  );
}

function countText(c: RetentionCount | undefined, field: keyof RetentionCount): string {
  return c ? c[field].toLocaleString() : '0';
}

function runSummary(run: RetentionRun): string {
  const parts = RETENTION_CATEGORIES.map((k) => {
    const c = run.counts?.[k];
    if (!c || (!c.removed && !c.failed && !c.due)) return null;
    const failed = c.failed ? `, ${c.failed} failed` : '';
    return `${RETENTION_CATEGORY_LABELS[k]}: ${c.removed} of ${c.due} removed${failed}`;
  }).filter(Boolean);
  return parts.length ? parts.join('; ') : 'Nothing was due.';
}

/** What is due for removal now (nothing is changed by looking) and the recent runs of the daily job. */
function RetentionReportPanel({ orgId, reloadKey }: { orgId: string; reloadKey: string }) {
  const { data, error, loading, reload } = useLoad(() => intelligenceApi.retention(orgId), `${orgId}|${reloadKey}`);
  const dueColumns: Column<RetentionCategory>[] = [
    { key: 'what', header: 'Data', render: (k) => <span className="cell-strong">{RETENTION_CATEGORY_LABELS[k]}</span> },
    { key: 'due', header: 'Due for removal now', align: 'end', render: (k) => countText(data?.due_now[k], 'due') },
  ];
  const runColumns: Column<RetentionRun>[] = [
    { key: 'when', header: 'Started', render: (r) => formatDateTime(r.started_at) },
    { key: 'status', header: 'Result', render: (r) => <span className="badge">{r.status.replace(/_/g, ' ')}</span> },
    { key: 'mode', header: 'Mode', render: (r) => (r.enforced ? 'Removing' : 'Report only') },
    { key: 'counts', header: 'What happened', render: (r) => <span className="small">{runSummary(r)}</span> },
  ];
  return (
    <section className="panel" aria-labelledby="set-ret-report">
      <h2 id="set-ret-report" className="panel-title">
        Retention report
      </h2>
      {loading && !data ? (
        <SkeletonRows rows={2} label="Loading the retention report" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data ? (
        <>
          {data.legal_hold && <p className="small">The organization is on legal hold: nothing below is removed while the hold is on.</p>}
          {!data.enforcement_enabled && (
            <p className="small muted">Report-only mode: apart from expired recordings, items due are counted but not removed.</p>
          )}
          <DataTable caption="Data due for removal now" columns={dueColumns} rows={RETENTION_CATEGORIES} rowKey={(k) => k} empty={null} />
          <h3 className="feedback-title">Recent runs</h3>
          <DataTable
            caption="Recent retention runs"
            columns={runColumns}
            rows={data.runs}
            rowKey={(r) => String(r.id ?? r.started_at)}
            empty={<EmptyState title="The retention job has not run for this organization yet." />}
          />
        </>
      ) : null}
    </section>
  );
}

function AdminSettings({ orgId, initial, rubrics }: { orgId: string; initial: TrainingSettings; rubrics: Rubric[] | null | undefined }) {
  const [settings, setSettings] = useState(initial);
  const [saves, setSaves] = useState(0);
  const onSaved = (next: TrainingSettings) => {
    setSettings(next);
    setSaves((n) => n + 1);
  };
  return (
    <>
      <EvaluationStatus s={settings} />
      <SettingsForm orgId={orgId} initial={initial} rubrics={rubrics} onSaved={onSaved} />
      <PracticeNoticeForm orgId={orgId} initial={initial} onSaved={onSaved} />
      <RetentionForm orgId={orgId} initial={initial} onSaved={onSaved} />
      <RetentionReportPanel orgId={orgId} reloadKey={String(saves)} />
    </>
  );
}

/**
 * Evaluation status and budget, the default rubric, recordings, the practice call notice and data retention.
 * Admins edit and see the retention report; trainers read.
 */
export function SettingsTab({ orgId, canEdit }: { orgId: string; canEdit: boolean }) {
  const { data, error, loading, reload } = useLoad(() => intelligenceApi.settings(orgId), orgId);
  const rubrics = useLoad(() => api.get<Rubric[]>(orgPath(orgId, '/rubrics')).catch(() => null), orgId);
  if ((loading && !data) || (rubrics.loading && !rubrics.data)) return <SkeletonRows label="Loading training settings" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  if (canEdit) return <AdminSettings orgId={orgId} initial={data} rubrics={rubrics.data} />;
  return (
    <>
      <EvaluationStatus s={data} />
      <ReadOnlySettings s={data} rubrics={rubrics.data} />
    </>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { errorMessage } from '@/lib/api';
import { formatDate, formatDateTime } from '@/lib/format';
import {
  evaluationErrorLabel,
  evaluationStatusBadge,
  evaluationStatusLabel,
  intelligenceApi,
  jobLabel,
  jobRunning,
  reconciliationLabel,
  RECORDING_STATUS_LABELS,
  scorecardBusy,
  scoreText,
  TRANSCRIPT_STATUS_BADGE,
  TRANSCRIPT_STATUS_LABELS,
} from '@/lib/intelligence';
import { formatDuration } from '@/lib/training';
import type { CriterionResult, Evaluation, Permission, Scorecard as ScorecardData, ScorecardRecording, ScorecardTranscript, Speaker } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { ConfirmDialog } from '../ConfirmDialog';
import { DataTable, type Column } from '../DataTable';
import { ErrorState } from '../ErrorState';
import { FormError, FormSuccess } from '../Field';
import { SkeletonRows, Spinner } from '../Spinner';

const POLL_MS = 10_000;

function speakerLabel(speaker: Speaker, mode: 'self' | 'admin'): string {
  if (speaker === 'trainee') return mode === 'self' ? 'You' : 'Trainee';
  if (speaker === 'agent') return 'Agent';
  return 'Unknown speaker';
}

function List({ title, items }: { title: string; items: string[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <h4 className="feedback-title">{title}</h4>
      <ul className="feedback-list">
        {items.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </div>
  );
}

function CriterionScore({ c, scale }: { c: CriterionResult; scale: number | null }) {
  if (c.score !== null && c.score !== undefined) return <span className="cell-strong">{scale ? `${c.score} / ${scale}` : c.score}</span>;
  return (
    <span className="small muted">
      Not scored. {c.unsupported_score_dropped ? 'A score was given without a supporting quote, so it was dropped.' : 'Not enough evidence in the call.'}
    </span>
  );
}

function CriteriaTable({ evaluation }: { evaluation: Evaluation }) {
  const scale = evaluation.rubric.scale_max;
  const columns: Column<CriterionResult>[] = [
    {
      key: 'name',
      header: 'Criterion',
      render: (c) => (
        <>
          <span className="cell-strong">{c.name}</span>
          {c.weight !== null && c.weight !== undefined && <span className="small muted"> weight {c.weight}</span>}
        </>
      ),
    },
    { key: 'score', header: 'Score', render: (c) => <CriterionScore c={c} scale={scale} /> },
    {
      key: 'explanation',
      header: 'What happened',
      render: (c) => (
        <div className="criterion-text">
          {c.explanation && <p>{c.explanation}</p>}
          {c.evidence && c.evidence.length > 0 && (
            <ul className="evidence-list" aria-label={`Evidence for ${c.name}`}>
              {c.evidence.map((q, i) => (
                <li key={i}>
                  <a href={`#turn-${q.turn}`}>Turn {q.turn}</a>: <q>{q.quote}</q>
                </li>
              ))}
            </ul>
          )}
        </div>
      ),
    },
    { key: 'improve', header: 'To improve', render: (c) => (c.improvement ? <span className="small">{c.improvement}</span> : null) },
  ];
  return <DataTable caption="Score for each criterion" columns={columns} rows={evaluation.criteria} rowKey={(c) => c.key} empty={null} />;
}

function rubricLine(e: Evaluation): string {
  const name = e.rubric.name ?? 'A rubric';
  const version = e.rubric.version !== null && e.rubric.version !== undefined ? ` version ${e.rubric.version}` : '';
  const scale = e.rubric.scale_max ? `, scored 0 to ${e.rubric.scale_max} per criterion` : '';
  return `${name}${version}${scale}`;
}

function evaluatorLine(e: Evaluation): string {
  const who = [e.evaluator.provider, e.evaluator.model].filter(Boolean).join(' ');
  return `${who || 'Unknown evaluator'}${e.evaluator.version ? ` (${e.evaluator.version})` : ''}`;
}

function EvaluationPanel({
  card,
  canRerun,
  busyAction,
  onAction,
}: {
  card: ScorecardData;
  canRerun: boolean;
  busyAction: 'evaluate' | 'reconcile' | null;
  onAction: (a: 'evaluate' | 'reconcile') => void;
}) {
  const ev = card.evaluation;
  const running = jobRunning(ev.job);
  const done = ev.status !== 'not_evaluated' ? ev : null;
  const hasScore = !!done && done.status === 'completed' && done.overall_score !== null;

  let reason: string | null = null;
  if (ev.status === 'not_evaluated') reason = ev.reason;
  else if (ev.status === 'insufficient_evidence') reason = ev.feedback.summary || evaluationErrorLabel(ev.error_code) || 'There was not enough evidence to score this session.';
  else if (ev.status === 'failed') reason = evaluationErrorLabel(ev.error_code) ?? 'The evaluation could not be completed.';

  const ended = ['completed', 'failed', 'timed_out', 'cancelled'].includes(card.session.status);
  const reconciled = card.provider.reconciliation_status === 'matched' || card.provider.reconciliation_status === 'corrected';

  return (
    <section className="panel" aria-labelledby="scorecard-title" aria-live="polite">
      <div className="section-head">
        <h2 id="scorecard-title" className="panel-title">
          Scorecard
        </h2>
        {canRerun && (
          <div className="row">
            <Button size="sm" variant="secondary" busy={busyAction === 'evaluate'} disabled={busyAction !== null || running} onClick={() => onAction('evaluate')}>
              Re-evaluate
            </Button>
            {ended && !reconciled && (
              <Button size="sm" variant="secondary" busy={busyAction === 'reconcile'} disabled={busyAction !== null} onClick={() => onAction('reconcile')}>
                Reconcile with Sarvam
              </Button>
            )}
          </div>
        )}
      </div>

      {hasScore && done ? (
        <div className="score-hero">
          <p className="score-big">
            <span className="score-number">{done.overall_score}</span>
            <span className="score-outof">/ 100</span>
          </p>
          <div className="small">
            {done.confidence !== null && done.confidence !== undefined && (
              <p className="score-meta">
                <strong>Confidence:</strong> {done.confidence} / 100
              </p>
            )}
            <p className="score-meta muted">Rubric: {rubricLine(done)}</p>
            <p className="score-meta muted">Evaluator: {evaluatorLine(done)}</p>
            {done.evaluated_at && <p className="score-meta muted">Evaluated {formatDateTime(done.evaluated_at)}</p>}
          </div>
        </div>
      ) : (
        <div className="status-hero">
          <p className="status-hero-line">
            <span className={evaluationStatusBadge(ev.status)}>{evaluationStatusLabel(ev.status)}</span>
            {reason && <span>{reason}</span>}
            {running && <Spinner label="Evaluating" inline />}
          </p>
          {done && (
            <p className="small muted">
              Rubric: {rubricLine(done)}. Evaluator: {evaluatorLine(done)}.
            </p>
          )}
        </div>
      )}
      {running && <p className="small muted">Evaluation: {jobLabel(ev.job)}. This section updates by itself.</p>}
      {!running && ev.job?.status === 'dead' && (
        <p className="small muted">The evaluation stopped after several tries{ev.job.error_code ? ` (${evaluationErrorLabel(ev.job.error_code)})` : ''}.</p>
      )}

      {done && done.feedback.summary && done.status === 'completed' && <p>{done.feedback.summary}</p>}
      {done && done.status !== 'failed' && (
        <div className="feedback-grid">
          <List title="Strengths" items={done.feedback.strengths} />
          <List title="To improve" items={done.feedback.improvements} />
          <List title="Practise next" items={done.feedback.practice_topics} />
        </div>
      )}
      {done && done.criteria.length > 0 && (
        <>
          <h3>By criterion</h3>
          <CriteriaTable evaluation={done} />
        </>
      )}
    </section>
  );
}

function TranscriptPanel({ transcript, mode }: { transcript: ScorecardTranscript; mode: 'self' | 'admin' }) {
  const running = jobRunning(transcript.job);
  return (
    <section className="panel" aria-labelledby="transcript-title">
      <h2 id="transcript-title" className="panel-title">
        Transcript
      </h2>
      <p className="status-hero-line small">
        <span className={TRANSCRIPT_STATUS_BADGE[transcript.status] ?? 'badge'}>{TRANSCRIPT_STATUS_LABELS[transcript.status] ?? transcript.status}</span>
        {transcript.status !== 'complete' && transcript.status !== 'removed' && transcript.reason && <span>{transcript.reason}</span>}
        {running && <Spinner label="Getting the transcript" inline />}
      </p>
      {transcript.text_variant === 'en_text' && (
        <p className="note small">This is English text from Sarvam. If the call was in another language, it may be a translation.</p>
      )}
      {transcript.status === 'removed' ? (
        <p className="muted">
          Removed under the organization&apos;s retention policy{transcript.purged_at ? ` on ${formatDate(transcript.purged_at)}` : ''}. Scores and coaching
          feedback stay; quotes from the call are no longer shown.
        </p>
      ) : transcript.turns.length === 0 ? (
        <p className="muted">{running ? 'The transcript is on its way.' : 'There is no transcript to show.'}</p>
      ) : (
        <ol className="transcript">
          {transcript.turns.map((t) => (
            <li key={t.n} id={`turn-${t.n}`} className={`turn turn-${t.speaker}`} tabIndex={-1}>
              <span className="turn-head">
                <span className="turn-speaker">{speakerLabel(t.speaker, mode)}</span>
                <span className="small muted">Turn {t.n}</span>
              </span>
              <span className="turn-text">{t.text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function RecordingPanel({
  orgId,
  sessionId,
  recording,
  canDelete,
  onDeleted,
}: {
  orgId: string;
  sessionId: string;
  recording: ScorecardRecording;
  canDelete: boolean;
  onDeleted: () => void;
}) {
  // The playback link lives only in memory while this page is open; it is never saved.
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function play() {
    setBusy(true);
    setError(null);
    try {
      const res = await intelligenceApi.playback(orgId, sessionId);
      setUrl(res.url);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await intelligenceApi.deleteRecording(orgId, sessionId);
      setUrl(null);
      setConfirm(false);
      onDeleted();
    } catch (e) {
      setDeleteError(errorMessage(e));
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="recording-title">
      <h2 id="recording-title" className="panel-title">
        Recording
      </h2>
      <p className="status-hero-line small">
        <span className={recording.status === 'stored' ? 'badge badge-ok' : 'badge'}>{RECORDING_STATUS_LABELS[recording.status] ?? recording.status}</span>
        {recording.reason && <span>{recording.reason}</span>}
      </p>
      {recording.status === 'stored' && (
        <p className="small muted">
          {recording.duration_seconds !== null ? `Length ${formatDuration(recording.duration_seconds)}. ` : ''}
          {recording.retention_until ? `Kept until ${formatDateTime(recording.retention_until)}.` : ''}
        </p>
      )}
      <FormError message={error} />
      {recording.can_play && (
        <div className="row">
          {url ? (
            <audio
              className="audio"
              controls
              autoPlay
              src={url}
              onError={() => {
                setUrl(null);
                setError('The recording could not be played. The link may have expired. Press Play again.');
              }}
            >
              Your browser cannot play this recording.
            </audio>
          ) : (
            <Button variant="secondary" busy={busy} onClick={() => void play()}>
              Play recording
            </Button>
          )}
          {canDelete && (
            <Button
              variant="danger"
              size="sm"
              onClick={() => {
                setDeleteError(null);
                setConfirm(true);
              }}
            >
              Delete recording
            </Button>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirm}
        title="Delete this recording?"
        confirmLabel="Delete recording"
        danger
        busy={deleteBusy}
        error={deleteError}
        onConfirm={() => void remove()}
        onCancel={() => setConfirm(false)}
      >
        <p>The recording is deleted for good. The transcript and the scorecard stay.</p>
      </ConfirmDialog>
    </section>
  );
}

function seconds(v: number | null | undefined): string {
  return v === null || v === undefined ? 'Not known' : formatDuration(v);
}

function UsagePanel({ card }: { card: ScorecardData }) {
  const u = card.usage;
  const p = card.provider;
  return (
    <section className="panel" aria-labelledby="usage-title">
      <h2 id="usage-title" className="panel-title">
        Call outcome and usage
      </h2>
      <dl className="facts facts-wide">
        <div>
          <dt>Sarvam call status</dt>
          <dd>{p.status ? p.status.replace(/_/g, ' ') : 'Not reported'}</dd>
        </div>
        <div>
          <dt>Sarvam call length</dt>
          <dd>{seconds(p.duration_seconds)}</dd>
        </div>
        <div>
          <dt>Checked with Sarvam</dt>
          <dd>
            {reconciliationLabel(p.reconciliation_status)}
            {p.reconciled_at ? ` · ${formatDateTime(p.reconciled_at)}` : ''}
          </dd>
        </div>
        <div>
          <dt>Practised</dt>
          <dd>{card.session.practised ? 'Yes, the trainee talked to the agent' : 'No'}</dd>
        </div>
      </dl>
      <h3>Minutes</h3>
      <dl className="facts facts-wide">
        <div>
          <dt>Reserved at start</dt>
          <dd>{seconds(u.reserved_seconds)}</dd>
        </div>
        <div>
          <dt>Billed</dt>
          <dd>{seconds(u.billed_seconds)}</dd>
        </div>
        <div>
          <dt>Adjustments</dt>
          <dd>{u.adjustment_seconds === 0 ? 'None' : `${u.adjustment_seconds > 0 ? '+' : '−'}${formatDuration(Math.abs(u.adjustment_seconds))}`}</dd>
        </div>
        <div>
          <dt>Counted against quota</dt>
          <dd>{formatDuration(u.quota_seconds)}</dd>
        </div>
        <div>
          <dt>Reported by Sarvam</dt>
          <dd>{seconds(u.provider_reported_seconds)}</dd>
        </div>
      </dl>
      <p className="small muted">{u.provider_billing_note}</p>
    </section>
  );
}

function EarlierEvaluations({ items }: { items: Evaluation[] }) {
  if (items.length === 0) return null;
  const columns: Column<Evaluation>[] = [
    { key: 'when', header: 'Evaluated', render: (e) => formatDateTime(e.evaluated_at) },
    { key: 'status', header: 'Result', render: (e) => <span className={evaluationStatusBadge(e.status)}>{evaluationStatusLabel(e.status)}</span> },
    { key: 'score', header: 'Score', align: 'end', render: (e) => scoreText(e.overall_score) ?? <span className="muted">No score</span> },
    { key: 'rubric', header: 'Rubric', render: (e) => rubricLine(e) },
    { key: 'why', header: 'Note', render: (e) => evaluationErrorLabel(e.error_code) },
  ];
  return (
    <section className="panel" aria-labelledby="earlier-title">
      <h2 id="earlier-title" className="panel-title">
        Other evaluations
      </h2>
      <DataTable caption="Other evaluations of this session" columns={columns} rows={items} rowKey={(e) => e.id} empty={null} />
    </section>
  );
}

/**
 * The scorecard of a finished session: score, feedback, transcript, recording and (for trainers) the usage
 * breakdown. Refreshes every 10 seconds while the transcript or evaluation is still being worked on.
 */
export function Scorecard({
  orgId,
  sessionId,
  mode,
  permissions,
}: {
  orgId: string;
  sessionId: string;
  mode: 'self' | 'admin';
  permissions: Permission[];
}) {
  const { data, error, loading, reload, setData } = useLoad(() => intelligenceApi.scorecard(orgId, sessionId), `${orgId}|${sessionId}`);
  const [pollError, setPollError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<'evaluate' | 'reconcile' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const busy = data ? scorecardBusy(data) : false;

  useEffect(() => {
    if (!data || !busy) return;
    let live = true;
    const timer = window.setTimeout(() => {
      intelligenceApi.scorecard(orgId, sessionId).then(
        (next) => {
          if (!live) return;
          setPollError(null);
          setData(next);
        },
        (e: unknown) => {
          if (!live) return;
          setPollError(`Could not refresh the scorecard: ${errorMessage(e)} Trying again…`);
          setData((prev) => ({ ...(prev as ScorecardData) }));
        },
      );
    }, POLL_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [data, busy, orgId, sessionId, setData]);

  async function onAction(a: 'evaluate' | 'reconcile') {
    setBusyAction(a);
    setActionError(null);
    setNotice(null);
    try {
      if (a === 'evaluate') await intelligenceApi.evaluate(orgId, sessionId);
      else await intelligenceApi.reconcile(orgId, sessionId);
      setNotice(a === 'evaluate' ? 'A new evaluation was queued.' : 'A check with Sarvam was queued.');
      reload();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusyAction(null);
    }
  }

  if (loading && !data) return <SkeletonRows rows={3} label="Loading the scorecard" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const can = (p: Permission) => permissions.includes(p);
  return (
    <>
      <FormSuccess message={notice} />
      <FormError message={actionError} />
      {pollError && <p className="field-hint">{pollError}</p>}
      <EvaluationPanel card={data} canRerun={mode === 'admin' && can('evaluations.manage')} busyAction={busyAction} onAction={(a) => void onAction(a)} />
      <TranscriptPanel transcript={data.transcript} mode={mode} />
      <RecordingPanel
        orgId={orgId}
        sessionId={sessionId}
        recording={data.recording}
        canDelete={mode === 'admin' && can('recordings.manage')}
        onDeleted={() => {
          setNotice('The recording was deleted.');
          reload();
        }}
      />
      {mode === 'admin' && <UsagePanel card={data} />}
      {mode === 'admin' && <EarlierEvaluations items={data.other_evaluations} />}
    </>
  );
}

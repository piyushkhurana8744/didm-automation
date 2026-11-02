/**
 * Shared helpers for training intelligence: scorecards, progress, analytics, rubrics and settings.
 * Scores come only from the API; nothing here invents a score when one is missing.
 */
import { API_PREFIX, api, seg } from './api';
import { orgPath, query } from './agents';
import type {
  JobState,
  Playback,
  RetentionCategory,
  RetentionReport,
  RubricCriterion,
  RubricDetail,
  Scorecard,
  ScorecardEvaluation,
  TrainingAnalytics,
  TrainingProgress,
  TrainingSettings,
  TraineeProgress,
  TranscriptStatus,
} from './types';

// ---------- API calls ----------

export const intelligenceApi = {
  scorecard: (orgId: string, sessionId: string) => api.get<Scorecard>(orgPath(orgId, `/training/sessions/${seg(sessionId)}/scorecard`)),
  playback: (orgId: string, sessionId: string) => api.post<Playback>(orgPath(orgId, `/training/sessions/${seg(sessionId)}/recording/playback`)),
  deleteRecording: (orgId: string, sessionId: string) => api.delete<{ ok: boolean }>(orgPath(orgId, `/training/sessions/${seg(sessionId)}/recording`)),
  evaluate: (orgId: string, sessionId: string, rubricVersionId?: string | null) =>
    api.post<{ queued: boolean }>(orgPath(orgId, `/training/sessions/${seg(sessionId)}/evaluate`), rubricVersionId ? { rubric_version_id: rubricVersionId } : {}),
  reconcile: (orgId: string, sessionId: string) => api.post<{ queued: boolean }>(orgPath(orgId, `/training/sessions/${seg(sessionId)}/reconcile`)),
  myProgress: (orgId: string) => api.get<TrainingProgress>(orgPath(orgId, '/my/training/progress')),
  traineeProgress: (orgId: string, userId: string) => api.get<TraineeProgress>(orgPath(orgId, `/training/analytics/trainees/${seg(userId)}`)),
  analytics: (orgId: string, params: AnalyticsFilters & { page?: number; page_size?: number }) =>
    api.get<TrainingAnalytics>(orgPath(orgId, `/training/analytics${query(params)}`)),
  settings: (orgId: string) => api.get<TrainingSettings>(orgPath(orgId, '/training/settings')),
  saveSettings: (orgId: string, body: Record<string, unknown>) => api.put<TrainingSettings>(orgPath(orgId, '/training/settings'), body),
  retention: (orgId: string) => api.get<RetentionReport>(orgPath(orgId, '/training/retention')),
  rubric: (orgId: string, rubricId: string) => api.get<RubricDetail>(orgPath(orgId, `/rubrics/${seg(rubricId)}`)),
};

export type AnalyticsFilters = {
  days: number;
  team_id?: string;
  agent_id?: string;
};

/**
 * The address of a CSV export for the current analytics filters. It is a plain link (the session cookie
 * authenticates it), so it points at the API directly, outside the app's base path.
 */
export function analyticsExportUrl(orgId: string, kind: 'sessions' | 'trainees', filters: AnalyticsFilters): string {
  return `${API_PREFIX}${orgPath(orgId, `/training/analytics/export.csv${query({ kind, ...filters })}`)}`;
}

// ---------- retention ----------

export const RETENTION_CATEGORIES: RetentionCategory[] = ['transcripts', 'recordings', 'webhook_payloads', 'browser_tokens', 'phone_challenges'];

export const RETENTION_CATEGORY_LABELS: Record<RetentionCategory, string> = {
  transcripts: 'Transcripts',
  recordings: 'Recordings',
  webhook_payloads: 'Call result messages from Sarvam',
  browser_tokens: 'Browser session passes',
  phone_challenges: 'Phone verification codes',
};

// ---------- jobs and polling ----------

export function jobRunning(job: JobState | null | undefined): boolean {
  return !!job && (job.status === 'queued' || job.status === 'running');
}

/** Poll while the transcript or the evaluation is still being worked on. */
export function scorecardBusy(card: Scorecard): boolean {
  return jobRunning(card.transcript.job) || jobRunning(card.evaluation.job);
}

// ---------- labels ----------

export const TRANSCRIPT_STATUS_LABELS: Record<TranscriptStatus, string> = {
  complete: 'Complete',
  partial: 'Partial',
  missing: 'Missing',
  failed: 'Failed',
  not_available: 'Not available',
  removed: 'Removed',
};

export const TRANSCRIPT_STATUS_BADGE: Record<TranscriptStatus, string> = {
  complete: 'badge badge-ok',
  partial: 'badge badge-warn',
  missing: 'badge badge-warn',
  failed: 'badge badge-danger',
  not_available: 'badge',
  removed: 'badge',
};

export function evaluationStatusLabel(status: ScorecardEvaluation['status']): string {
  switch (status) {
    case 'completed':
      return 'Scored';
    case 'insufficient_evidence':
      return 'Not enough evidence';
    case 'failed':
      return 'Evaluation failed';
    default:
      return 'Not evaluated';
  }
}

export function evaluationStatusBadge(status: ScorecardEvaluation['status']): string {
  if (status === 'completed') return 'badge badge-ok';
  if (status === 'insufficient_evidence') return 'badge badge-warn';
  if (status === 'failed') return 'badge badge-danger';
  return 'badge';
}

const ERROR_CODE_LABELS: Record<string, string> = {
  too_little_conversation: 'There was too little conversation to score.',
  low_coverage: 'Too few criteria had evidence to give an overall score.',
  invalid_output: 'The evaluator gave an answer we could not use.',
  no_rubric: 'No published rubric applies to this scenario.',
  internal_error: 'Something went wrong while evaluating.',
};

export function evaluationErrorLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  return ERROR_CODE_LABELS[code] ?? code.replace(/_/g, ' ');
}

export const RECORDING_STATUS_LABELS: Record<string, string> = {
  none: 'No recording',
  pending: 'Being saved',
  stored: 'Available',
  unavailable: 'Unavailable',
  failed: 'Could not be saved',
  deleted: 'Deleted',
};

const RECONCILIATION_LABELS: Record<string, string> = {
  pending: 'Waiting to check with Sarvam',
  matched: 'Matches Sarvam',
  corrected: 'Corrected from Sarvam',
  unresolved: 'Could not be checked',
};

export function reconciliationLabel(status: string | null | undefined): string {
  if (!status) return 'Not checked';
  return RECONCILIATION_LABELS[status] ?? status.replace(/_/g, ' ');
}

export function jobLabel(job: JobState | null | undefined): string | null {
  if (!job) return null;
  switch (job.status) {
    case 'queued':
      return 'Waiting to run';
    case 'running':
      return 'Running now';
    case 'succeeded':
      return 'Done';
    case 'skipped':
      return 'Skipped';
    case 'dead':
      return 'Gave up after several tries';
    default:
      return job.status;
  }
}

/** "72" with a suffix like " / 100", or null when there is no score. Never a placeholder. */
export function scoreText(score: number | null | undefined, outOf = 100): string | null {
  if (score === null || score === undefined || !Number.isFinite(score)) return null;
  return `${score} / ${outOf}`;
}

/** The badge class for a 0-100 score. */
export function scoreBadge(score: number): string {
  if (score >= 75) return 'badge badge-ok';
  if (score >= 50) return 'badge badge-info';
  return 'badge badge-warn';
}

export const PERIODS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
];

export const SCORE_BUCKETS = ['0-39', '40-59', '60-74', '75-89', '90-100'];

// ---------- rubric editing (mirrors the backend's checks) ----------

export const RUBRIC_SCALES = [3, 4, 5, 10];
export const CRITERION_KEY_RE = /^[a-z][a-z0-9_]{0,39}$/;
export const MAX_CRITERIA = 12;

export interface CriterionRow {
  uid: string;
  key: string;
  name: string;
  description: string;
  weight: string;
}

let rowSeq = 0;
export function criterionRow(c?: Partial<RubricCriterion>): CriterionRow {
  rowSeq += 1;
  return {
    uid: `c${rowSeq}`,
    key: c?.key ?? '',
    name: c?.name ?? '',
    description: c?.description ?? '',
    weight: c?.weight !== undefined ? String(c.weight) : '',
  };
}

/** A key made from a name: "Objection handling" -> "objection_handling". */
export function keyFromName(name: string): string {
  const k = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/^[0-9_]+/, '')
    .slice(0, 40);
  return k;
}

/** Validates the rows. Returns the criteria to send and per-row problems. */
export function criteriaFromRows(rows: CriterionRow[]): { criteria: RubricCriterion[]; problems: Record<string, string[]>; general: string[] } {
  const problems: Record<string, string[]> = {};
  const general: string[] = [];
  const seen = new Set<string>();
  const criteria: RubricCriterion[] = [];
  if (rows.length < 1 || rows.length > MAX_CRITERIA) general.push(`A rubric needs 1 to ${MAX_CRITERIA} criteria.`);
  for (const r of rows) {
    const p: string[] = [];
    const key = r.key.trim();
    if (!CRITERION_KEY_RE.test(key)) p.push('Key: start with a lower-case letter; use lower-case letters, digits and underscores (up to 40).');
    else if (seen.has(key)) p.push('Key: another criterion already uses this key.');
    seen.add(key);
    const name = r.name.trim();
    if (!name || name.length > 120) p.push('Name: 1 to 120 characters.');
    if (r.description.length > 1000) p.push('Description: up to 1000 characters.');
    const w = /^\d+$/.test(r.weight.trim()) ? Number(r.weight.trim()) : NaN;
    if (!Number.isInteger(w) || w < 1 || w > 100) p.push('Weight: a whole number from 1 to 100.');
    if (p.length) problems[r.uid] = p;
    criteria.push({ key, name, description: r.description.trim(), weight: Number.isInteger(w) ? w : 0 });
  }
  return { criteria, problems, general };
}

export function weightTotal(rows: CriterionRow[]): number {
  return rows.reduce((sum, r) => {
    const w = /^\d+$/.test(r.weight.trim()) ? Number(r.weight.trim()) : 0;
    return sum + w;
  }, 0);
}

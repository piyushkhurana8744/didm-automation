'use client';

import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { parseOptionalInt } from '@/lib/agents';
import type { StoredTrainingLimits, TrainingLimits } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { ErrorState } from '../ErrorState';
import { CheckboxField, FormError, FormSuccess, TextField } from '../Field';
import { SkeletonRows } from '../Spinner';

type NumberField =
  | 'max_concurrent_sessions'
  | 'max_concurrent_per_user'
  | 'max_sessions_per_user_per_day'
  | 'max_session_minutes'
  | 'monthly_minutes'
  | 'evaluation_monthly_calls'
  | 'evaluation_monthly_tokens';

/**
 * Each editable number, its bounds (mirroring the backend) and the matching effective value. The evaluation
 * budgets have no effective value in this response, so their default is described in words.
 */
const NUMBER_FIELDS: { field: NumberField; label: string; min: number; max: number; effective: keyof TrainingLimits['effective'] | null }[] = [
  { field: 'max_concurrent_sessions', label: 'Open sessions at once', min: 0, max: 500, effective: 'org_concurrency' },
  { field: 'max_concurrent_per_user', label: 'Open sessions per person', min: 0, max: 10, effective: 'user_concurrency' },
  { field: 'max_sessions_per_user_per_day', label: 'Sessions per person per day', min: 0, max: 500, effective: 'sessions_per_day' },
  { field: 'max_session_minutes', label: 'Longest session (minutes)', min: 1, max: 120, effective: 'session_minutes' },
  { field: 'monthly_minutes', label: 'Minutes per month', min: 0, max: 1_000_000, effective: 'monthly_minutes' },
  { field: 'evaluation_monthly_calls', label: 'Evaluator calls per month', min: 0, max: 1_000_000, effective: null },
  { field: 'evaluation_monthly_tokens', label: 'Evaluator tokens per month', min: 0, max: 10_000_000_000, effective: null },
];

function textFrom(stored: StoredTrainingLimits): Record<NumberField, string> {
  const out = {} as Record<NumberField, string>;
  for (const f of NUMBER_FIELDS) {
    const v = stored[f.field];
    out[f.field] = v === null || v === undefined ? '' : String(v);
  }
  return out;
}

function Form({ orgId, initial, onSaved }: { orgId: string; initial: TrainingLimits; onSaved: (l: TrainingLimits) => void }) {
  const [limits, setLimits] = useState(initial);
  const [enabled, setEnabled] = useState(!!initial.stored.enabled);
  const [phone, setPhone] = useState(initial.stored.phone_enabled ?? initial.effective.phone_enabled);
  const [browser, setBrowser] = useState(initial.stored.browser_enabled ?? initial.effective.browser_enabled);
  const [evaluation, setEvaluation] = useState(!!initial.stored.evaluation_enabled);
  const [recording, setRecording] = useState(!!initial.stored.recording_allowed);
  const [nums, setNums] = useState(textFrom(initial.stored));
  const [errors, setErrors] = useState<Partial<Record<NumberField, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    const body: Record<string, unknown> = {
      enabled,
      phone_enabled: phone,
      browser_enabled: browser,
      evaluation_enabled: evaluation,
      recording_allowed: recording,
    };
    const clear: string[] = [];
    const errs: Partial<Record<NumberField, string>> = {};
    for (const f of NUMBER_FIELDS) {
      const n = parseOptionalInt(nums[f.field]);
      if (n === undefined) {
        if (limits.stored[f.field] !== null && limits.stored[f.field] !== undefined) clear.push(f.field);
      } else if (Number.isNaN(n) || n < f.min || n > f.max) {
        errs[f.field] = `A whole number from ${f.min} to ${f.max.toLocaleString()}.`;
      } else {
        body[f.field] = n;
      }
    }
    setErrors(errs);
    if (Object.keys(errs).length) return setError('Some of the values are not valid.');
    if (clear.length) body.clear = clear;
    setBusy(true);
    try {
      const next = await api.put<TrainingLimits>(`/platform/organizations/${seg(orgId)}/training-limits`, body);
      setLimits(next);
      setNums(textFrom(next.stored));
      setSaved('Training limits saved.');
      onSaved(next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="form">
      <FormError message={error} />
      <FormSuccess message={saved} />
      <p className="small muted">
        On the platform right now: phone calls are {limits.platform.phone_channel_live ? 'live' : 'not live'}, browser voice is{' '}
        {limits.platform.browser_channel_live ? 'live' : 'not live'}. A channel works for this organization only when it is allowed here and live.
      </p>
      <CheckboxField label="Training is switched on" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
      <CheckboxField label="Allow phone practice" checked={phone} onChange={(e) => setPhone(e.target.checked)} />
      <CheckboxField
        label="Allow browser practice"
        hint="Has no effect until browser voice is live on the platform."
        checked={browser}
        onChange={(e) => setBrowser(e.target.checked)}
      />
      <CheckboxField
        label="Score practice sessions"
        hint="Sessions are evaluated against a rubric. Works only when an evaluator is set up on the platform."
        checked={evaluation}
        onChange={(e) => setEvaluation(e.target.checked)}
      />
      <CheckboxField
        label="Allow recordings"
        hint="The organization's admins still decide whether to record, and trainees must agree each time."
        checked={recording}
        onChange={(e) => setRecording(e.target.checked)}
      />
      <div className="var-grid">
        {NUMBER_FIELDS.map((f) => (
          <TextField
            key={f.field}
            label={f.label}
            inputMode="numeric"
            value={nums[f.field]}
            placeholder={f.effective ? `Default (${limits.effective[f.effective]})` : 'Platform default'}
            hint={
              f.effective
                ? `Now ${limits.effective[f.effective]}. Leave empty for the platform default.`
                : 'Scoring stops for the month once this is reached. Leave empty for the platform default.'
            }
            error={errors[f.field] ?? null}
            onChange={(e) => setNums((prev) => ({ ...prev, [f.field]: e.target.value }))}
          />
        ))}
      </div>
      <div>
        <Button type="submit" busy={busy}>
          Save training limits
        </Button>
      </div>
    </form>
  );
}

/** The platform administrator's editor for one organization's training limits. */
export function LimitsEditor({ orgId, onSaved }: { orgId: string; onSaved?: (l: TrainingLimits) => void }) {
  const { data, error, loading, reload } = useLoad(() => api.get<TrainingLimits>(`/platform/organizations/${seg(orgId)}/training-limits`), orgId);
  if (loading && !data) return <SkeletonRows rows={2} label="Loading training limits" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  return <Form key={orgId} orgId={orgId} initial={data} onSaved={(l) => onSaved?.(l)} />;
}

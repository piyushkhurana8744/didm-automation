'use client';

import { useState, type FormEvent } from 'react';
import { api, errorMessage, isApiError, seg } from '@/lib/api';
import { orgPath, parseOptionalInt } from '@/lib/agents';
import { criteriaFromRows, criterionRow, keyFromName, MAX_CRITERIA, RUBRIC_SCALES, weightTotal, type CriterionRow } from '@/lib/intelligence';
import type { RubricVersion } from '@/lib/types';
import { Button } from '../Button';
import { ConfirmDialog } from '../ConfirmDialog';
import { FormError, FormSuccess, SelectField, TextAreaField, TextField } from '../Field';

const PUBLISHED_MESSAGE = 'This version was already published, and published versions cannot change. Create a new draft to make changes.';

/** Edits one draft rubric version: criteria with weights, scale, minimum turns and scoring instructions. */
export function RubricDraftEditor({
  orgId,
  version,
  canDiscard,
  onSaved,
  onPublished,
  onDiscarded,
  onStale,
}: {
  orgId: string;
  version: RubricVersion;
  canDiscard: boolean;
  onSaved: (v: RubricVersion) => void;
  onPublished: (v: RubricVersion) => void;
  onDiscarded: () => void;
  /** The draft changed elsewhere (for example it was published): reload. */
  onStale: () => void;
}) {
  const [rows, setRows] = useState<CriterionRow[]>(() => version.criteria.map((c) => criterionRow(c)));
  const [scale, setScale] = useState(String(version.scale_max));
  const [turns, setTurns] = useState(String(version.min_trainee_turns));
  const [instructions, setInstructions] = useState(version.scoring_instructions ?? '');
  const [problems, setProblems] = useState<Record<string, string[]>>({});
  const [turnsError, setTurnsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'publish' | 'discard' | null>(null);
  const [dirty, setDirty] = useState(false);
  const [confirm, setConfirm] = useState<'publish' | 'discard' | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const total = weightTotal(rows);

  function edit(uid: string, patch: Partial<CriterionRow>) {
    setDirty(true);
    setNotice(null);
    setRows((prev) =>
      prev.map((r) => {
        if (r.uid !== uid) return r;
        const next = { ...r, ...patch };
        // Keep the key in step with the name while it still matches the name.
        if (patch.name !== undefined && (r.key === '' || r.key === keyFromName(r.name))) next.key = keyFromName(patch.name);
        return next;
      }),
    );
  }

  function move(uid: string, delta: number) {
    setDirty(true);
    setRows((prev) => {
      const i = prev.findIndex((r) => r.uid === uid);
      const j = i + delta;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = prev.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  /** Validates and saves. Returns the saved version, or null when something is wrong. */
  async function save(): Promise<RubricVersion | null> {
    setError(null);
    setNotice(null);
    const { criteria, problems: p, general } = criteriaFromRows(rows);
    setProblems(p);
    const t = parseOptionalInt(turns);
    const tErr = t === undefined || Number.isNaN(t) || t < 1 || t > 50 ? 'A whole number from 1 to 50.' : null;
    setTurnsError(tErr);
    if (general.length || Object.keys(p).length || tErr) {
      setError(general.length ? general.join(' ') : 'Fix the highlighted fields.');
      return null;
    }
    try {
      const saved = await api.patch<RubricVersion>(orgPath(orgId, `/rubric-versions/${seg(version.id)}`), {
        criteria,
        scale_max: Number(scale),
        min_trainee_turns: t,
        scoring_instructions: instructions,
      });
      setDirty(false);
      onSaved(saved);
      return saved;
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        setError(PUBLISHED_MESSAGE);
        onStale();
      } else {
        setError(errorMessage(err));
      }
      return null;
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy('save');
    const saved = await save();
    setBusy(null);
    if (saved) setNotice('Draft saved.');
  }

  async function publish() {
    setBusy('publish');
    setDialogError(null);
    // Save first so what is published is what is on screen.
    const saved = dirty ? await save() : version;
    if (!saved) {
      setBusy(null);
      setConfirm(null);
      return;
    }
    try {
      const published = await api.post<RubricVersion>(orgPath(orgId, `/rubric-versions/${seg(version.id)}/publish`));
      setConfirm(null);
      onPublished(published);
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        setConfirm(null);
        setError(PUBLISHED_MESSAGE);
        onStale();
      } else {
        setDialogError(errorMessage(err));
      }
    } finally {
      setBusy(null);
    }
  }

  async function discard() {
    setBusy('discard');
    setDialogError(null);
    try {
      await api.delete(orgPath(orgId, `/rubric-versions/${seg(version.id)}`));
      setConfirm(null);
      onDiscarded();
    } catch (err) {
      setDialogError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel panel-highlight" aria-labelledby="draft-title">
      <h2 id="draft-title" className="panel-title">
        Draft version {version.version}
      </h2>
      <p className="small muted">Changes here do not affect scoring until you publish. Once published, a version cannot change.</p>
      <form onSubmit={onSubmit} noValidate className="form form-wide">
        <FormError message={error} />
        <FormSuccess message={notice} />
        <fieldset className="fieldset">
          <legend>Criteria</legend>
          <ol className="var-rows">
            {rows.map((r, i) => {
              const p = problems[r.uid];
              return (
                <li key={r.uid} className={p ? 'var-row var-row-invalid' : 'var-row'}>
                  <div className="var-row-head">
                    <strong>
                      {i + 1}. {r.name || 'New criterion'}
                    </strong>
                    <div className="row">
                      <Button size="sm" variant="ghost" disabled={i === 0} onClick={() => move(r.uid, -1)} aria-label={`Move ${r.name || 'criterion'} up`}>
                        Up
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={i === rows.length - 1}
                        onClick={() => move(r.uid, 1)}
                        aria-label={`Move ${r.name || 'criterion'} down`}
                      >
                        Down
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={rows.length <= 1}
                        onClick={() => {
                          setDirty(true);
                          setRows((prev) => prev.filter((x) => x.uid !== r.uid));
                        }}
                        aria-label={`Remove ${r.name || 'criterion'}`}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                  <div className="var-row-fields">
                    <TextField label="Name" maxLength={120} value={r.name} onChange={(e) => edit(r.uid, { name: e.target.value })} />
                    <TextField
                      label="Key"
                      maxLength={40}
                      className="input mono"
                      value={r.key}
                      hint="Lower-case letters, digits and _."
                      onChange={(e) => edit(r.uid, { key: e.target.value })}
                    />
                    <TextField label="Weight" inputMode="numeric" value={r.weight} hint="1 to 100." onChange={(e) => edit(r.uid, { weight: e.target.value })} />
                  </div>
                  <TextAreaField
                    label="What good looks like"
                    rows={2}
                    maxLength={1000}
                    value={r.description}
                    onChange={(e) => edit(r.uid, { description: e.target.value })}
                  />
                  {p && (
                    <ul className="problem-list field-error" role="alert">
                      {p.map((m) => (
                        <li key={m}>{m}</li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ol>
          <div className="row">
            <Button
              variant="secondary"
              size="sm"
              disabled={rows.length >= MAX_CRITERIA}
              onClick={() => {
                setDirty(true);
                setRows((prev) => [...prev, criterionRow({ weight: 10 })]);
              }}
            >
              Add criterion
            </Button>
            <span className="small" aria-live="polite">
              Total weight: <strong>{total}</strong>
              {total !== 100 ? ' (weights are relative; a total of 100 makes each one read as a percentage)' : ''}
            </span>
          </div>
          {rows.length >= MAX_CRITERIA && <p className="field-hint">A rubric can have up to {MAX_CRITERIA} criteria.</p>}
        </fieldset>
        <div className="form-grid">
          <SelectField
            label="Score scale"
            options={RUBRIC_SCALES.map((n) => ({ value: String(n), label: `0 to ${n}` }))}
            value={scale}
            onChange={(e) => {
              setDirty(true);
              setScale(e.target.value);
            }}
          />
          <TextField
            label="Minimum trainee turns"
            inputMode="numeric"
            value={turns}
            error={turnsError}
            hint="From 1 to 50. Shorter calls are not scored."
            onChange={(e) => {
              setDirty(true);
              setTurns(e.target.value);
            }}
          />
        </div>
        <TextAreaField
          label="Scoring instructions"
          rows={4}
          maxLength={4000}
          value={instructions}
          hint="Optional. Extra guidance for the evaluator, up to 4000 characters."
          onChange={(e) => {
            setDirty(true);
            setInstructions(e.target.value);
          }}
        />
        <div className="form-actions">
          <Button type="submit" busy={busy === 'save'} disabled={busy !== null}>
            Save draft
          </Button>
          <Button
            variant="secondary"
            disabled={busy !== null}
            onClick={() => {
              setDialogError(null);
              setConfirm('publish');
            }}
          >
            Publish
          </Button>
          {canDiscard && (
            <Button
              variant="danger"
              disabled={busy !== null}
              onClick={() => {
                setDialogError(null);
                setConfirm('discard');
              }}
            >
              Discard draft
            </Button>
          )}
        </div>
        {dirty && <p className="field-hint">You have unsaved changes.</p>}
      </form>

      <ConfirmDialog
        open={confirm === 'publish'}
        title={`Publish version ${version.version}?`}
        confirmLabel="Publish"
        busy={busy === 'publish'}
        error={dialogError}
        onConfirm={() => void publish()}
        onCancel={() => setConfirm(null)}
      >
        <p>
          New evaluations will use this version. A published version cannot be changed; to change it later, create a new draft.
          {dirty ? ' Your unsaved changes are saved first.' : ''}
        </p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'discard'}
        title="Discard this draft?"
        confirmLabel="Discard draft"
        danger
        busy={busy === 'discard'}
        error={dialogError}
        onConfirm={() => void discard()}
        onCancel={() => setConfirm(null)}
      >
        <p>The draft and its changes are deleted. Published versions stay as they are.</p>
      </ConfirmDialog>
    </section>
  );
}

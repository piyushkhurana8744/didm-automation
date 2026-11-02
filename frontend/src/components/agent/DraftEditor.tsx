'use client';

import { useMemo, useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import {
  newVarRow,
  orgPath,
  parseConfiguration,
  parseOptionalInt,
  rowsFromSchema,
  schemaFromRows,
  splitOptions,
  VAR_TYPE_LABELS,
  VAR_TYPES,
  type VarRow,
} from '@/lib/agents';
import { formatDateTime } from '@/lib/format';
import type { AgentDetail, AgentVersion, ValidationResult, VarType } from '@/lib/types';
import { Button } from '../Button';
import { ConfirmDialog } from '../ConfirmDialog';
import { EmptyState } from '../EmptyState';
import { CheckboxField, FormError, FormSuccess, SelectField, TextAreaField, TextField } from '../Field';
import { VersionView } from './VersionView';

interface DraftValues {
  appVersion: string;
  config: string;
  rows: VarRow[];
  kb: string;
  rubric: string;
  notes: string;
}

function formFrom(v: AgentVersion): DraftValues {
  const config = v.configuration_snapshot ?? {};
  return {
    appVersion: v.provider_app_version !== null && v.provider_app_version !== undefined ? String(v.provider_app_version) : '',
    config: Object.keys(config).length ? JSON.stringify(config, null, 2) : '{}',
    rows: rowsFromSchema(v.variable_schema ?? []),
    kb: v.knowledge_base_reference ?? '',
    rubric: v.rubric_reference ?? '',
    notes: v.notes ?? '',
  };
}

/** Comparable form content (row keys are local ids, so they are left out). */
function fingerprint(f: DraftValues): string {
  return JSON.stringify({ ...f, rows: f.rows.map(({ key: _key, ...rest }) => rest) });
}

function VarRowEditor({
  row,
  index,
  problems,
  onChange,
  onRemove,
}: {
  row: VarRow;
  index: number;
  problems: string[] | undefined;
  onChange: (patch: Partial<VarRow>) => void;
  onRemove: () => void;
}) {
  const numeric = row.type === 'number' || row.type === 'integer';
  const label = row.name.trim() || `Variable ${index + 1}`;
  return (
    <li className={problems?.length ? 'var-row var-row-invalid' : 'var-row'}>
      <div className="var-row-head">
        <strong className="mono">{label}</strong>
        <Button size="sm" variant="ghost" onClick={onRemove} aria-label={`Remove variable ${label}`}>
          Remove
        </Button>
      </div>
      <div className="var-row-fields">
        <TextField
          label="Name"
          className="input mono"
          spellCheck={false}
          autoComplete="off"
          maxLength={64}
          value={row.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="customer_name"
        />
        <SelectField
          label="Type"
          options={VAR_TYPES.map((t) => ({ value: t, label: VAR_TYPE_LABELS[t] }))}
          value={row.type}
          onChange={(e) => onChange({ type: e.target.value as VarType, default: '' })}
        />
        <CheckboxField label="Required" checked={row.required} onChange={(e) => onChange({ required: e.target.checked })} />
      </div>
      <TextField label="Description" maxLength={500} value={row.description} onChange={(e) => onChange({ description: e.target.value })} />
      <div className="var-row-fields">
        {row.type === 'enum' && (
          <TextField label="Options" hint="Separate with commas." value={row.options} onChange={(e) => onChange({ options: e.target.value })} />
        )}
        {row.type === 'string' && (
          <TextField
            label="Max length"
            type="number"
            inputMode="numeric"
            min={1}
            max={5000}
            value={row.max_length}
            onChange={(e) => onChange({ max_length: e.target.value })}
            hint="Default 2000."
          />
        )}
        {numeric && (
          <>
            <TextField label="Minimum" type="number" step="any" value={row.min} onChange={(e) => onChange({ min: e.target.value })} />
            <TextField label="Maximum" type="number" step="any" value={row.max} onChange={(e) => onChange({ max: e.target.value })} />
          </>
        )}
        {row.type === 'boolean' ? (
          <SelectField
            label="Default"
            options={[
              { value: '', label: 'No default' },
              { value: 'true', label: 'Yes' },
              { value: 'false', label: 'No' },
            ]}
            value={row.default}
            onChange={(e) => onChange({ default: e.target.value })}
          />
        ) : row.type === 'enum' ? (
          <SelectField
            label="Default"
            options={[{ value: '', label: 'No default' }, ...splitOptions(row.options).map((o) => ({ value: o, label: o }))]}
            value={row.default}
            onChange={(e) => onChange({ default: e.target.value })}
          />
        ) : (
          <TextField
            label="Default"
            type={numeric ? 'number' : 'text'}
            step={row.type === 'integer' ? 1 : numeric ? 'any' : undefined}
            value={row.default}
            onChange={(e) => onChange({ default: e.target.value })}
          />
        )}
      </div>
      {problems && problems.length > 0 && (
        <ul className="field-error problem-list">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

function DraftForm({
  orgId,
  agent,
  draft,
  onSaved,
  onPublished,
  onDiscarded,
}: {
  orgId: string;
  agent: AgentDetail;
  draft: AgentVersion;
  onSaved: (v: AgentVersion) => void;
  onPublished: (v: AgentVersion) => void;
  onDiscarded: () => void;
}) {
  const base = `/agents/${seg(agent.id)}/versions/${seg(draft.id)}`;
  const [initial, setInitial] = useState(() => formFrom(draft));
  const [form, setForm] = useState<DraftValues>(initial);
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState<'save' | 'validate' | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [confirm, setConfirm] = useState<'publish' | 'discard' | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState(draft.updated_at);

  const dirty = useMemo(() => fingerprint(form) !== fingerprint(initial), [form, initial]);
  const configCheck = useMemo(() => parseConfiguration(form.config), [form.config]);
  const schemaCheck = useMemo(() => schemaFromRows(form.rows), [form.rows]);
  const appVersion = parseOptionalInt(form.appVersion);
  const appVersionError = appVersion !== undefined && (Number.isNaN(appVersion) || appVersion < 1) ? 'Enter a whole number, 1 or more.' : null;
  const schemaInvalid = Object.keys(schemaCheck.problems).length > 0;

  const set = (patch: Partial<DraftValues>) => {
    setForm((f) => ({ ...f, ...patch }));
    setNotice(null);
    setValidation(null);
  };
  const setRow = (key: string, patch: Partial<VarRow>) => set({ rows: form.rows.map((r) => (r.key === key ? { ...r, ...patch } : r)) });

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setNotice(null);
    setShowErrors(true);
    if (appVersionError || configCheck.error || schemaInvalid) {
      setFormError('Fix the highlighted problems before saving.');
      return;
    }
    setBusy('save');
    try {
      const saved = await api.patch<AgentVersion>(orgPath(orgId, base), {
        provider_app_version: appVersion ?? null,
        configuration_snapshot: configCheck.value ?? {},
        variable_schema: schemaCheck.schema,
        knowledge_base_reference: form.kb.trim(),
        rubric_reference: form.rubric.trim(),
        notes: form.notes,
      });
      const next = formFrom(saved);
      setInitial(next);
      setForm(next);
      setShowErrors(false);
      setSavedAt(saved.updated_at);
      setNotice('Draft saved.');
      onSaved(saved);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function onValidate() {
    setFormError(null);
    setNotice(null);
    setBusy('validate');
    try {
      setValidation(await api.post<ValidationResult>(orgPath(orgId, `${base}/validate`)));
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function onConfirm() {
    setConfirmBusy(true);
    setConfirmError(null);
    try {
      if (confirm === 'publish') {
        const v = await api.post<AgentVersion>(orgPath(orgId, `${base}/publish`));
        setConfirm(null);
        onPublished(v);
      } else {
        await api.delete(orgPath(orgId, base));
        setConfirm(null);
        onDiscarded();
      }
    } catch (err) {
      setConfirmError(errorMessage(err));
    } finally {
      setConfirmBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="draft-title">
      <div className="section-head">
        <h2 id="draft-title">
          Draft — version {draft.internal_version}
          <span className="title-badges">
            <span className="badge badge-info">Draft</span>
            {dirty && <span className="badge badge-warn">Unsaved changes</span>}
          </span>
        </h2>
        <span className="small muted">Last saved {formatDateTime(savedAt)}</span>
      </div>
      <p className="muted small">
        Edits here only change this draft. Trainees keep using the current published version until you publish. A published version can never
        be edited; to change it, start a new draft.
      </p>
      <form onSubmit={onSave} noValidate className="form form-wide">
        <FormError message={formError} />
        <FormSuccess message={notice} />
        <TextField
          label="Sarvam app version"
          type="number"
          inputMode="numeric"
          min={1}
          step={1}
          value={form.appVersion}
          error={showErrors || form.appVersion ? appVersionError : null}
          onChange={(e) => set({ appVersion: e.target.value })}
          hint="The exact app version in Sarvam's dashboard that this version uses. Required to publish."
        />
        <TextAreaField
          label="Configuration (JSON)"
          className="mono"
          rows={10}
          spellCheck={false}
          value={form.config}
          error={configCheck.error}
          onChange={(e) => set({ config: e.target.value })}
          hint="Settings recorded with this version, for example language or voice. Never put API keys or other credentials here."
        />
        <fieldset className="fieldset">
          <legend>Variables</legend>
          <p className="field-hint">Values each scenario can pass to the agent. Scenarios are checked against the published version&apos;s variables.</p>
          {form.rows.length === 0 ? (
            <p className="muted small">No variables yet.</p>
          ) : (
            <ul className="var-rows">
              {form.rows.map((r, i) => (
                <VarRowEditor
                  key={r.key}
                  row={r}
                  index={i}
                  problems={showErrors || r.name ? schemaCheck.problems[r.key] : undefined}
                  onChange={(patch) => setRow(r.key, patch)}
                  onRemove={() => set({ rows: form.rows.filter((x) => x.key !== r.key) })}
                />
              ))}
            </ul>
          )}
          <div>
            <Button variant="secondary" size="sm" disabled={form.rows.length >= 50} onClick={() => set({ rows: [...form.rows, newVarRow()] })}>
              Add variable
            </Button>
          </div>
        </fieldset>
        <div className="form-grid">
          <TextField label="Knowledge base reference" maxLength={500} value={form.kb} onChange={(e) => set({ kb: e.target.value })} hint="Where the agent's knowledge base lives (a name or link)." />
          <TextField label="Rubric reference" maxLength={500} value={form.rubric} onChange={(e) => set({ rubric: e.target.value })} hint="The scoring rubric used to evaluate sessions." />
        </div>
        <TextAreaField label="Notes" maxLength={5000} value={form.notes} onChange={(e) => set({ notes: e.target.value })} hint="What changed in this version." />
        <div className="form-actions">
          <Button type="submit" busy={busy === 'save'} disabled={!dirty || busy !== null}>
            Save draft
          </Button>
          <Button variant="secondary" busy={busy === 'validate'} disabled={dirty || busy !== null} onClick={() => void onValidate()}>
            Validate
          </Button>
          <Button
            variant="secondary"
            disabled={dirty || busy !== null}
            onClick={() => {
              setConfirmError(null);
              setConfirm('publish');
            }}
          >
            Publish
          </Button>
          <Button
            variant="danger"
            disabled={busy !== null}
            onClick={() => {
              setConfirmError(null);
              setConfirm('discard');
            }}
          >
            Discard draft
          </Button>
        </div>
        {dirty && <p className="field-hint">Save the draft before validating or publishing.</p>}
        {validation &&
          (validation.ok ? (
            <div className="alert alert-success" role="status">
              Ready to publish: no problems found.
            </div>
          ) : (
            <div className="alert alert-warn" role="alert">
              <strong>Fix these before publishing:</strong>
              <ul className="problem-list">
                {validation.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          ))}
      </form>
      <ConfirmDialog
        open={confirm !== null}
        title={confirm === 'publish' ? `Publish version ${draft.internal_version}?` : 'Discard this draft?'}
        confirmLabel={confirm === 'publish' ? 'Publish' : 'Discard'}
        danger={confirm === 'discard'}
        busy={confirmBusy}
        error={confirmError}
        onConfirm={() => void onConfirm()}
        onCancel={() => setConfirm(null)}
      >
        {confirm === 'publish' ? (
          <p>
            Version {draft.internal_version} becomes the current version of <strong>{agent.name}</strong> and can no longer be edited.
            {agent.published_version ? ` It replaces version ${agent.published_version.internal_version}.` : ''}
            {agent.published_version ? '' : ' After this the Sarvam app id is fixed.'}
          </p>
        ) : (
          <p>All changes in draft version {draft.internal_version} will be deleted. Published versions are not affected.</p>
        )}
      </ConfirmDialog>
    </section>
  );
}

/** The configuration tab: the open draft (editable by agents.manage), or the published version read-only. */
export function DraftEditor({
  orgId,
  agent,
  canManage,
  onChanged,
}: {
  orgId: string;
  agent: AgentDetail;
  canManage: boolean;
  onChanged: (notice?: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const draft = agent.draft_version;
  const pub = agent.published_version;

  async function startDraft() {
    setBusy(true);
    setError(null);
    try {
      await api.post<AgentVersion>(orgPath(orgId, `/agents/${seg(agent.id)}/versions`), {});
      onChanged('A new draft was started.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const editable = canManage && agent.status === 'active';

  return (
    <>
      {draft && editable ? (
        <DraftForm
          key={draft.id}
          orgId={orgId}
          agent={agent}
          draft={draft}
          onSaved={() => undefined}
          onPublished={(v) => onChanged(`Version ${v.internal_version} is published and now current.`)}
          onDiscarded={() => onChanged('The draft was discarded.')}
        />
      ) : (
        <section className="panel" aria-labelledby="draft-none">
          <h2 id="draft-none" className="panel-title">
            Draft
          </h2>
          <FormError message={error} />
          {!canManage ? (
            <p className="muted">
              {draft ? `Version ${draft.internal_version} is being drafted by an administrator.` : 'There is no draft.'} Only administrators change agent
              configuration.
            </p>
          ) : agent.status !== 'active' ? (
            <p className="muted">This agent is archived. Restore it to edit its configuration.</p>
          ) : (
            <>
              <p className="muted">
                There is no open draft. {pub ? `Start one to change version ${pub.internal_version}; it is copied into the new draft.` : 'Start one to configure this agent.'}
              </p>
              <Button busy={busy} onClick={() => void startDraft()}>
                Start a new draft
              </Button>
            </>
          )}
        </section>
      )}
      <section className="panel" aria-labelledby="published-title">
        <h2 id="published-title" className="panel-title">
          {pub ? `Current published version — version ${pub.internal_version}` : 'Published version'}
        </h2>
        {pub ? <VersionView version={pub} /> : <EmptyState title="Nothing has been published yet." />}
      </section>
    </>
  );
}

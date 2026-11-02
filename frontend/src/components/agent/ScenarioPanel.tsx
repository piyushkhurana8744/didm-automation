'use client';

import { useMemo, useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import {
  DIFFICULTIES,
  DIFFICULTY_LABELS,
  orgPath,
  query,
  rawFromValues,
  SCENARIO_STATUS_BADGE,
  valuesFromRaw,
  type RawVariables,
} from '@/lib/agents';
import { capitalize, formatDate } from '@/lib/format';
import type { AgentDetail, Difficulty, Rubric, Scenario, ScenarioStatus } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { ConfirmDialog } from '../ConfirmDialog';
import { DataTable, type Column } from '../DataTable';
import { EmptyState } from '../EmptyState';
import { ErrorState } from '../ErrorState';
import { FormError, FormSuccess, SelectField, TextAreaField, TextField } from '../Field';
import { SkeletonRows } from '../Spinner';
import { VariablesForm } from '../VariablesForm';

/** Picks the rubric that scores one scenario's sessions (or the organization default). */
function RubricPicker({ orgId, scenario, rubrics, onSaved, onError }: { orgId: string; scenario: Scenario; rubrics: Rubric[]; onSaved: (name: string) => void; onError: (m: string) => void }) {
  const [value, setValue] = useState(scenario.rubric_id ?? '');
  const [busy, setBusy] = useState(false);
  const options = [
    { value: '', label: 'Organization default' },
    ...rubrics
      .filter((r) => r.status === 'active' || r.id === value)
      .map((r) => ({ value: r.id, label: `${r.name}${r.published_version ? '' : ' (not published)'}${r.status === 'archived' ? ' (archived)' : ''}` })),
  ];
  async function change(next: string) {
    const prev = value;
    setValue(next);
    setBusy(true);
    try {
      await api.put(orgPath(orgId, `/scenarios/${seg(scenario.id)}/rubric`), { rubric_id: next || null });
      onSaved(next ? (rubrics.find((r) => r.id === next)?.name ?? 'the chosen rubric') : 'the organization default');
    } catch (e) {
      setValue(prev);
      onError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <SelectField
      label={`Rubric for ${scenario.name}`}
      hideLabel
      options={options}
      value={value}
      disabled={busy}
      onChange={(e) => void change(e.target.value)}
    />
  );
}

function ScenarioForm({
  orgId,
  agent,
  scenario,
  onDone,
  onCancel,
}: {
  orgId: string;
  agent: AgentDetail;
  scenario: Scenario | null;
  onDone: (s: Scenario, created: boolean) => void;
  onCancel: () => void;
}) {
  const schemaVersion = agent.published_version ?? agent.draft_version;
  const schema = useMemo(() => schemaVersion?.variable_schema ?? [], [schemaVersion]);
  const canActivate = !!agent.published_version;
  const existing = scenario?.agent_variables ?? {};
  const dropped = Object.keys(existing).filter((k) => !schema.some((v) => v.name === k));

  const [name, setName] = useState(scenario?.name ?? '');
  const [description, setDescription] = useState(scenario?.description ?? '');
  const [difficulty, setDifficulty] = useState<Difficulty>(scenario?.difficulty ?? 'beginner');
  const [persona, setPersona] = useState(scenario?.persona ?? '');
  const [objective, setObjective] = useState(scenario?.objective ?? '');
  const [opening, setOpening] = useState(scenario?.opening_context ?? '');
  const [expected, setExpected] = useState(scenario?.expected_behavior ?? '');
  const [criteria, setCriteria] = useState(scenario?.evaluation_criteria_reference ?? '');
  const [status, setStatus] = useState<ScenarioStatus>(scenario && scenario.status !== 'archived' ? scenario.status : 'draft');
  const [raw, setRaw] = useState<RawVariables>(() => rawFromValues(schema, existing));
  const [nameError, setNameError] = useState<string | null>(null);
  const [varErrors, setVarErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const nErr = name.trim() ? null : 'Enter a name.';
    setNameError(nErr);
    const { values, errors } = valuesFromRaw(schema, raw, status === 'active');
    setVarErrors(errors);
    if (nErr || Object.keys(errors).length) {
      setFormError('Fix the highlighted fields.');
      return;
    }
    const body = {
      name: name.trim(),
      description: description.trim(),
      difficulty,
      persona: persona.trim(),
      objective: objective.trim(),
      opening_context: opening.trim(),
      expected_behavior: expected.trim(),
      evaluation_criteria_reference: criteria.trim(),
      agent_variables: values,
      status,
    };
    setBusy(true);
    try {
      const saved = scenario
        ? await api.patch<Scenario>(orgPath(orgId, `/scenarios/${seg(scenario.id)}`), body)
        : await api.post<Scenario>(orgPath(orgId, `/agents/${seg(agent.id)}/scenarios`), body);
      onDone(saved, !scenario);
    } catch (err) {
      setFormError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-highlight" aria-labelledby="scenario-form-title">
      <h3 id="scenario-form-title" className="panel-title">
        {scenario ? `Edit scenario: ${scenario.name}` : 'New scenario'}
      </h3>
      <form onSubmit={onSubmit} noValidate className="form form-wide">
        <FormError message={formError} />
        <div className="form-grid">
          <TextField label="Name" required maxLength={200} value={name} error={nameError} onChange={(e) => setName(e.target.value)} />
          <SelectField
            label="Difficulty"
            options={DIFFICULTIES.map((d) => ({ value: d, label: DIFFICULTY_LABELS[d] }))}
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value as Difficulty)}
          />
          <SelectField
            label="Status"
            options={[
              { value: 'draft', label: 'Draft (hidden from trainees)' },
              ...(canActivate || status === 'active' ? [{ value: 'active', label: 'Active (trainees can see it)' }] : []),
            ]}
            value={status}
            onChange={(e) => setStatus(e.target.value as ScenarioStatus)}
            hint={canActivate ? undefined : 'Publish a version of the agent before activating scenarios.'}
          />
        </div>
        <TextAreaField label="Description" rows={2} maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} />
        <TextAreaField label="Objective" rows={2} maxLength={5000} value={objective} onChange={(e) => setObjective(e.target.value)} hint="What the trainee should achieve. Trainees see this." />
        <TextAreaField label="Persona" rows={3} maxLength={5000} value={persona} onChange={(e) => setPersona(e.target.value)} hint="Who the agent plays: mood, background, needs." />
        <TextAreaField label="Opening context" rows={3} maxLength={5000} value={opening} onChange={(e) => setOpening(e.target.value)} hint="The situation at the start of the call." />
        <TextAreaField label="Expected behaviour" rows={3} maxLength={5000} value={expected} onChange={(e) => setExpected(e.target.value)} hint="What a good trainee does." />
        <TextField label="Evaluation criteria reference" maxLength={500} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
        <fieldset className="fieldset">
          <legend>Agent variables</legend>
          {schemaVersion ? (
            <p className="field-hint">
              From {agent.published_version ? `published version ${schemaVersion.internal_version}` : `draft version ${schemaVersion.internal_version} (not published yet)`}.
              Leave a field empty to use the agent&apos;s default.
            </p>
          ) : (
            <p className="field-hint">This agent has no version yet.</p>
          )}
          {dropped.length > 0 && (
            <div className="alert alert-warn" role="note">
              These saved values are no longer variables of the agent and will be removed when you save: <span className="mono">{dropped.join(', ')}</span>
            </div>
          )}
          <VariablesForm
            schema={schema}
            raw={raw}
            errors={varErrors}
            onChange={(n, v) => {
              setRaw((r) => ({ ...r, [n]: v }));
              setVarErrors((errs) => {
                if (!(n in errs)) return errs;
                const next = { ...errs };
                delete next[n];
                return next;
              });
            }}
          />
        </fieldset>
        <div className="form-actions">
          <Button type="submit" busy={busy}>
            {scenario ? 'Save scenario' : 'Create scenario'}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}

export function ScenarioPanel({ orgId, agent, canManage, onCountChanged }: { orgId: string; agent: AgentDetail; canManage: boolean; onCountChanged: () => void }) {
  const [status, setStatus] = useState('');
  const { data, error, loading, reload } = useLoad(
    () => api.get<Scenario[]>(orgPath(orgId, `/agents/${seg(agent.id)}/scenarios${query({ status })}`)),
    `${orgId}|${agent.id}|${status}`,
  );
  const [editing, setEditing] = useState<Scenario | 'new' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [archiving, setArchiving] = useState<Scenario | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const editable = canManage && agent.status === 'active';
  // Only to show and pick rubrics; scenarios still work if this fails.
  const rubrics = useLoad(() => api.get<Rubric[]>(orgPath(orgId, '/rubrics')).catch(() => null), orgId);

  const versionLabel = (id: string | null) => {
    if (!id) return '—';
    if (id === agent.published_version?.id) return `Version ${agent.published_version.internal_version}`;
    if (id === agent.draft_version?.id) return `Draft ${agent.draft_version.internal_version}`;
    return 'An older version';
  };

  async function confirmArchive() {
    if (!archiving) return;
    setArchiveBusy(true);
    setArchiveError(null);
    try {
      await api.patch<Scenario>(orgPath(orgId, `/scenarios/${seg(archiving.id)}`), { status: 'archived' });
      setNotice(`"${archiving.name}" was archived.`);
      setArchiving(null);
      reload();
      onCountChanged();
    } catch (e) {
      setArchiveError(errorMessage(e));
    } finally {
      setArchiveBusy(false);
    }
  }

  async function restore(s: Scenario) {
    setRestoringId(s.id);
    setActionError(null);
    setNotice(null);
    try {
      await api.patch<Scenario>(orgPath(orgId, `/scenarios/${seg(s.id)}`), { status: 'draft' });
      setNotice(`"${s.name}" was restored as a draft.`);
      reload();
      onCountChanged();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setRestoringId(null);
    }
  }

  const columns: Column<Scenario>[] = [
    { key: 'name', header: 'Name', render: (s) => <span className="cell-strong">{s.name}</span> },
    { key: 'difficulty', header: 'Difficulty', render: (s) => DIFFICULTY_LABELS[s.difficulty] ?? s.difficulty },
    { key: 'status', header: 'Status', render: (s) => <span className={SCENARIO_STATUS_BADGE[s.status] ?? 'badge'}>{capitalize(s.status)}</span> },
    { key: 'checked', header: 'Variables checked against', render: (s) => versionLabel(s.validated_version_id) },
    { key: 'updated', header: 'Updated', render: (s) => formatDate(s.updated_at) },
  ];
  if (rubrics.data) {
    const list = rubrics.data;
    columns.push({
      key: 'rubric',
      header: 'Rubric',
      render: (s) =>
        editable && s.status !== 'archived' ? (
          <RubricPicker
            orgId={orgId}
            scenario={s}
            rubrics={list}
            onSaved={(name) => {
              setActionError(null);
              setNotice(`"${s.name}" is now scored with ${name}.`);
            }}
            onError={(m) => {
              setNotice(null);
              setActionError(m);
            }}
          />
        ) : s.rubric_id ? (
          (list.find((r) => r.id === s.rubric_id)?.name ?? 'A rubric')
        ) : (
          <span className="muted">Organization default</span>
        ),
    });
  }
  if (editable) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (s) => (
        <div className="row row-end">
          {s.status !== 'archived' ? (
            <>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setNotice(null);
                  setEditing(s);
                }}
                aria-label={`Edit ${s.name}`}
              >
                Edit
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  setArchiveError(null);
                  setArchiving(s);
                }}
                aria-label={`Archive ${s.name}`}
              >
                Archive
              </Button>
            </>
          ) : (
            <Button size="sm" variant="secondary" busy={restoringId === s.id} onClick={() => void restore(s)} aria-label={`Restore ${s.name}`}>
              Restore
            </Button>
          )}
        </div>
      ),
    });
  }

  return (
    <section aria-labelledby="scenarios-title">
      <div className="section-head">
        <h2 id="scenarios-title">Scenarios</h2>
        {editable && editing === null && (
          <Button
            onClick={() => {
              setNotice(null);
              setEditing('new');
            }}
          >
            New scenario
          </Button>
        )}
      </div>
      {!agent.published_version && (
        <p className="field-hint">Scenarios can be drafted now, but only become active after a version of this agent is published.</p>
      )}
      <FormSuccess message={notice} />
      <FormError message={actionError} />
      {editing !== null && (
        <ScenarioForm
          key={editing === 'new' ? 'new' : editing.id}
          orgId={orgId}
          agent={agent}
          scenario={editing === 'new' ? null : editing}
          onCancel={() => setEditing(null)}
          onDone={(s, created) => {
            setEditing(null);
            setNotice(created ? `Scenario "${s.name}" was created.` : `Scenario "${s.name}" was saved.`);
            reload();
            if (created) onCountChanged();
          }}
        />
      )}
      <div className="filters">
        <SelectField
          label="Status"
          options={[
            { value: '', label: 'All' },
            { value: 'draft', label: 'Draft' },
            { value: 'active', label: 'Active' },
            { value: 'archived', label: 'Archived' },
          ]}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        />
      </div>
      {loading && !data ? (
        <SkeletonRows label="Loading scenarios" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <DataTable
          caption="Scenarios"
          columns={columns}
          rows={data ?? []}
          rowKey={(s) => s.id}
          empty={
            <EmptyState title={status ? `No ${status} scenarios.` : 'No scenarios yet.'}>
              {editable && !status ? <p>Scenarios describe the situations trainees practise with this agent.</p> : null}
            </EmptyState>
          }
        />
      )}
      <ConfirmDialog
        open={archiving !== null}
        title="Archive scenario?"
        confirmLabel="Archive"
        danger
        busy={archiveBusy}
        error={archiveError}
        onConfirm={() => void confirmArchive()}
        onCancel={() => setArchiving(null)}
      >
        <p>{archiving ? <>Trainees will no longer see <strong>{archiving.name}</strong>. You can restore it later as a draft.</> : null}</p>
      </ConfirmDialog>
    </section>
  );
}

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath, parseOptionalInt } from '@/lib/agents';
import { capitalize, formatDate } from '@/lib/format';
import { RUBRIC_SCALES } from '@/lib/intelligence';
import type { Membership, Rubric, RubricDetail } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { FormError, SelectField, TextAreaField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

const STATUS_FILTERS = [
  { value: 'active', label: 'Active' },
  { value: 'archived', label: 'Archived' },
  { value: 'all', label: 'All' },
];

function CreateRubric({ orgId, onCancel }: { orgId: string; onCancel: () => void }) {
  const router = useRouter();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [scale, setScale] = useState('5');
  const [turns, setTurns] = useState('3');
  const [instructions, setInstructions] = useState('');
  const [errors, setErrors] = useState<{ name?: string; turns?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const errs: { name?: string; turns?: string } = {};
    if (!name.trim()) errs.name = 'Enter a name.';
    const t = parseOptionalInt(turns);
    if (t === undefined || Number.isNaN(t) || t < 1 || t > 50) errs.turns = 'A whole number from 1 to 50.';
    setErrors(errs);
    if (Object.keys(errs).length) return setError('Fix the highlighted fields.');
    setBusy(true);
    try {
      const created = await api.post<RubricDetail>(orgPath(orgId, '/rubrics'), {
        name: name.trim(),
        description: description.trim(),
        scale_max: Number(scale),
        min_trainee_turns: t,
        scoring_instructions: instructions,
      });
      router.push(`/rubrics/detail/?id=${encodeURIComponent(created.id)}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-highlight" aria-labelledby="new-rubric-title">
      <h2 id="new-rubric-title" className="panel-title">
        New rubric
      </h2>
      <p className="small muted">It starts as a draft with the standard criteria. You can change them before you publish it.</p>
      <form onSubmit={onSubmit} noValidate className="form form-wide">
        <FormError message={error} />
        <TextField label="Name" required maxLength={200} value={name} error={errors.name ?? null} onChange={(e) => setName(e.target.value)} />
        <TextAreaField label="Description" rows={2} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="form-grid">
          <SelectField
            label="Score scale"
            options={RUBRIC_SCALES.map((n) => ({ value: String(n), label: `0 to ${n}` }))}
            value={scale}
            onChange={(e) => setScale(e.target.value)}
            hint="Each criterion is scored on this scale."
          />
          <TextField
            label="Minimum trainee turns"
            inputMode="numeric"
            value={turns}
            error={errors.turns ?? null}
            onChange={(e) => setTurns(e.target.value)}
            hint="Shorter calls are not scored."
          />
        </div>
        <TextAreaField
          label="Scoring instructions"
          rows={3}
          maxLength={4000}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          hint="Optional. Extra guidance for the evaluator."
        />
        <div className="form-actions">
          <Button type="submit" busy={busy}>
            Create rubric
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}

function Rubrics({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const canManage = membership.permissions.includes('rubrics.manage');
  const { data, error, loading, reload } = useLoad(() => api.get<Rubric[]>(orgPath(orgId, '/rubrics')), orgId);
  const [filter, setFilter] = useState('active');
  const [creating, setCreating] = useState(false);

  const rows = (data ?? []).filter((r) => filter === 'all' || r.status === filter);
  const columns: Column<Rubric>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (r) => (
        <Link href={`/rubrics/detail/?id=${encodeURIComponent(r.id)}`} className="cell-strong">
          {r.name}
        </Link>
      ),
    },
    { key: 'status', header: 'Status', render: (r) => <span className={r.status === 'active' ? 'badge badge-ok' : 'badge'}>{capitalize(r.status)}</span> },
    {
      key: 'published',
      header: 'Published version',
      render: (r) => (r.published_version ? `Version ${r.published_version}` : <span className="muted">Not published</span>),
    },
    { key: 'draft', header: 'Draft', render: (r) => (r.has_draft ? <span className="badge badge-info">Draft open</span> : null) },
    { key: 'updated', header: 'Updated', render: (r) => formatDate(r.updated_at) },
  ];

  return (
    <>
      <PageHeader
        title="Rubrics"
        description="A rubric lists the skills a session is scored on, and how much each one counts."
        actions={
          canManage && !creating ? (
            <Button onClick={() => setCreating(true)}>New rubric</Button>
          ) : undefined
        }
      />
      {creating && <CreateRubric orgId={orgId} onCancel={() => setCreating(false)} />}
      <div className="filters">
        <SelectField label="Show" options={STATUS_FILTERS} value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      {loading && !data ? (
        <SkeletonRows label="Loading rubrics" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <DataTable
          caption="Rubrics"
          columns={columns}
          rows={rows}
          rowKey={(r) => r.id}
          empty={
            <EmptyState title={filter === 'archived' ? 'No archived rubrics.' : 'No rubrics yet.'}>
              {filter !== 'archived' && <p>Sessions are scored only after a rubric is published and set as the default or on a scenario.</p>}
            </EmptyState>
          }
        />
      )}
    </>
  );
}

export default function RubricsPage() {
  return <OrgGate permission="training.view">{(m) => <Rubrics membership={m} />}</OrgGate>;
}

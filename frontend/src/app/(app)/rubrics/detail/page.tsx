'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { capitalize, formatDate, formatDateTime } from '@/lib/format';
import { intelligenceApi } from '@/lib/intelligence';
import type { Membership, RubricCriterion, RubricDetail, RubricVersion } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState, NotFoundState } from '@/components/ErrorState';
import { FormError, FormSuccess, TextAreaField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';
import { WithQuery } from '@/components/WithQuery';
import { RubricDraftEditor } from '@/components/rubrics/RubricDraftEditor';

function VersionView({ version }: { version: RubricVersion }) {
  const total = version.criteria.reduce((s, c) => s + c.weight, 0);
  const columns: Column<RubricCriterion>[] = [
    {
      key: 'name',
      header: 'Criterion',
      render: (c) => (
        <>
          <span className="cell-strong">{c.name}</span> <span className="small muted mono">{c.key}</span>
        </>
      ),
    },
    { key: 'weight', header: 'Weight', align: 'end', render: (c) => c.weight },
    { key: 'desc', header: 'What good looks like', render: (c) => <span className="small">{c.description}</span> },
  ];
  return (
    <section className="panel" aria-labelledby="version-title">
      <h2 id="version-title" className="panel-title">
        Version {version.version} <span className={version.status === 'published' ? 'badge badge-ok' : 'badge badge-info'}>{capitalize(version.status)}</span>
      </h2>
      {version.status === 'published' && (
        <p className="small muted">
          Published {formatDateTime(version.published_at)}. Published versions cannot be changed. Create a new draft to make changes.
        </p>
      )}
      <dl className="facts facts-wide">
        <div>
          <dt>Score scale</dt>
          <dd>0 to {version.scale_max} per criterion</dd>
        </div>
        <div>
          <dt>Minimum trainee turns</dt>
          <dd>{version.min_trainee_turns}</dd>
        </div>
        <div>
          <dt>Total weight</dt>
          <dd>{total}</dd>
        </div>
        <div>
          <dt>Scoring instructions</dt>
          <dd>{version.scoring_instructions ? <span className="pre-line">{version.scoring_instructions}</span> : <span className="muted">None</span>}</dd>
        </div>
      </dl>
      <DataTable caption={`Criteria of version ${version.version}`} columns={columns} rows={version.criteria} rowKey={(c) => c.key} empty={<EmptyState title="No criteria." />} />
    </section>
  );
}

function DetailsForm({ orgId, rubric, onSaved, onCancel }: { orgId: string; rubric: RubricDetail; onSaved: (r: RubricDetail) => void; onCancel: () => void }) {
  const [name, setName] = useState(rubric.name);
  const [description, setDescription] = useState(rubric.description);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError('Enter a name.');
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.patch<RubricDetail>(orgPath(orgId, `/rubrics/${seg(rubric.id)}`), { name: name.trim(), description: description.trim() }));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-highlight" aria-labelledby="rubric-details-title">
      <h2 id="rubric-details-title" className="panel-title">
        Edit details
      </h2>
      <form onSubmit={onSubmit} noValidate className="form">
        <FormError message={error} />
        <TextField label="Name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        <TextAreaField label="Description" rows={2} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="form-actions">
          <Button type="submit" busy={busy}>
            Save details
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}

function RubricView({ membership, rubricId }: { membership: Membership; rubricId: string }) {
  const orgId = membership.organization.id;
  const canManage = membership.permissions.includes('rubrics.manage');
  const { data, error, loading, reload, setData } = useLoad(() => intelligenceApi.rubric(orgId, rubricId), `${orgId}|${rubricId}`);
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<'draft' | 'status' | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  if (loading && !data) return <Spinner label="Loading rubric" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const rubric = data;
  const versions = rubric.versions.slice().sort((a, b) => b.version - a.version);
  const draft = versions.find((v) => v.status === 'draft') ?? null;
  const current = versions.find((v) => v.id === selected) ?? draft ?? versions[0] ?? null;
  const archived = rubric.status === 'archived';

  async function newDraft() {
    setBusy('draft');
    setActionError(null);
    setNotice(null);
    try {
      const v = await api.post<RubricVersion>(orgPath(orgId, `/rubrics/${seg(rubric.id)}/versions`));
      setSelected(v.id);
      setNotice(`Draft version ${v.version} was created from the latest published version.`);
      reload();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(status: 'active' | 'archived') {
    setBusy('status');
    setDialogError(null);
    setActionError(null);
    setNotice(null);
    try {
      const next = await api.patch<RubricDetail>(orgPath(orgId, `/rubrics/${seg(rubric.id)}`), { status });
      setData(next);
      setConfirmArchive(false);
      setNotice(status === 'archived' ? 'The rubric was archived.' : 'The rubric was restored.');
    } catch (e) {
      if (status === 'archived') setDialogError(errorMessage(e));
      else setActionError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  function replaceVersion(v: RubricVersion) {
    setData((prev) => {
      const p = prev as RubricDetail;
      return { ...p, versions: p.versions.map((x) => (x.id === v.id ? v : x)) };
    });
  }

  const columns: Column<RubricVersion>[] = [
    {
      key: 'version',
      header: 'Version',
      render: (v) => (
        <Button size="sm" variant={current?.id === v.id ? 'primary' : 'ghost'} onClick={() => setSelected(v.id)} aria-pressed={current?.id === v.id}>
          Version {v.version}
        </Button>
      ),
    },
    { key: 'status', header: 'Status', render: (v) => <span className={v.status === 'published' ? 'badge badge-ok' : 'badge badge-info'}>{capitalize(v.status)}</span> },
    { key: 'criteria', header: 'Criteria', align: 'end', render: (v) => v.criteria.length },
    { key: 'scale', header: 'Scale', render: (v) => `0 to ${v.scale_max}` },
    { key: 'when', header: 'Published', render: (v) => (v.published_at ? formatDate(v.published_at) : '—') },
  ];

  return (
    <>
      <p className="small">
        <Link href="/rubrics/">← Rubrics</Link>
      </p>
      <PageHeader
        title={rubric.name}
        description={
          <>
            <span className={archived ? 'badge' : 'badge badge-ok'}>{capitalize(rubric.status)}</span> {rubric.description}
          </>
        }
        actions={
          canManage ? (
            <>
              {!archived && !editing && (
                <Button variant="secondary" onClick={() => setEditing(true)}>
                  Edit details
                </Button>
              )}
              {!archived && !draft && (
                <Button busy={busy === 'draft'} disabled={busy !== null} onClick={() => void newDraft()}>
                  New draft
                </Button>
              )}
              {archived ? (
                <Button variant="secondary" busy={busy === 'status'} onClick={() => void setStatus('active')}>
                  Restore
                </Button>
              ) : (
                <Button
                  variant="danger"
                  disabled={busy !== null}
                  onClick={() => {
                    setDialogError(null);
                    setConfirmArchive(true);
                  }}
                >
                  Archive
                </Button>
              )}
            </>
          ) : undefined
        }
      />
      <FormSuccess message={notice} />
      <FormError message={actionError} />
      {archived && <p className="alert alert-info">This rubric is archived. Restore it to change it or to create a new draft.</p>}
      {editing && (
        <DetailsForm
          orgId={orgId}
          rubric={rubric}
          onCancel={() => setEditing(false)}
          onSaved={(r) => {
            setData(r);
            setEditing(false);
            setNotice('Details saved.');
          }}
        />
      )}

      <section aria-labelledby="versions-title">
        <h2 id="versions-title">Versions</h2>
        <DataTable caption="Versions" columns={columns} rows={versions} rowKey={(v) => v.id} empty={<EmptyState title="No versions." />} />
      </section>

      {current &&
        (current.status === 'draft' && canManage && !archived ? (
          <RubricDraftEditor
            key={current.id}
            orgId={orgId}
            version={current}
            canDiscard={current.version > 1}
            onSaved={replaceVersion}
            onPublished={(v) => {
              replaceVersion(v);
              setSelected(v.id);
              setNotice(`Version ${v.version} was published. New evaluations use it.`);
              reload();
            }}
            onDiscarded={() => {
              setSelected(null);
              setNotice('The draft was discarded.');
              reload();
            }}
            onStale={reload}
          />
        ) : (
          <VersionView version={current} />
        ))}
      {current?.status === 'draft' && current.version === 1 && canManage && !archived && (
        <p className="small muted">The first version cannot be discarded. Archive the rubric instead if you no longer need it.</p>
      )}

      <ConfirmDialog
        open={confirmArchive}
        title="Archive this rubric?"
        confirmLabel="Archive"
        danger
        busy={busy === 'status'}
        error={dialogError}
        onConfirm={() => void setStatus('archived')}
        onCancel={() => setConfirmArchive(false)}
      >
        <p>It is hidden from the rubric pickers. Scenarios that already use it, and scores already given with it, stay as they are. You can restore it later.</p>
      </ConfirmDialog>
    </>
  );
}

export default function RubricDetailPage() {
  return (
    <OrgGate permission="training.view">
      {(m) => (
        <WithQuery>
          {(params) => {
            const id = params.get('id');
            return id ? <RubricView key={id} membership={m} rubricId={id} /> : <NotFoundState message="No rubric was chosen." />;
          }}
        </WithQuery>
      )}
    </OrgGate>
  );
}

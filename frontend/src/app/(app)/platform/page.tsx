'use client';

import { useState, type FormEvent } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { capitalize, formatDate } from '@/lib/format';
import { useSession } from '@/lib/session';
import { formatDuration } from '@/lib/training';
import type { IssuedInvitation, Organization, PlatformCreateResponse, PlatformOrganization, TrainingHealth } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState, Forbidden } from '@/components/ErrorState';
import { FormError, TextField } from '@/components/Field';
import { OneTimeLink } from '@/components/OneTimeLink';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';
import { LimitsEditor } from '@/components/training/LimitsEditor';

const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/;

function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/g, '');
}

function countList(counts: Record<string, number>): string {
  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  return entries.length ? entries.map(([k, n]) => `${k.replace(/_/g, ' ')}: ${n}`).join(' · ') : 'None';
}

/** Platform-wide training counts for operators: no names, numbers or organizations. */
function TrainingHealthPanel() {
  const { data, error, loading, reload } = useLoad(() => api.get<TrainingHealth>('/platform/training/health'), 'training-health');
  const open = data ? Object.values(data.open_sessions).reduce((a, b) => a + b, 0) : 0;
  return (
    <section className="panel" aria-labelledby="training-health">
      <div className="section-head">
        <h2 id="training-health" className="panel-title">
          Training health
        </h2>
        <Button size="sm" variant="secondary" onClick={reload} busy={loading && !!data}>
          Refresh
        </Button>
      </div>
      {loading && !data ? (
        <SkeletonRows rows={2} label="Loading training health" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data ? (
        <>
          <dl className="stats">
            <div className="stat">
              <dt>Open sessions</dt>
              <dd>
                {open} / {data.platform_capacity}
              </dd>
            </div>
            <div className="stat">
              <dt>Completed today</dt>
              <dd>{data.today.completed}</dd>
            </div>
            <div className="stat">
              <dt>Average length today</dt>
              <dd>{data.today.completed ? formatDuration(data.today.avg_duration_seconds) : '—'}</dd>
            </div>
          </dl>
          <dl className="facts facts-wide">
            <div>
              <dt>Open by channel</dt>
              <dd>{countList(data.open_sessions)}</dd>
            </div>
            <div>
              <dt>Failures today</dt>
              <dd>{countList(data.today.failures)}</dd>
            </div>
            <div>
              <dt>Result webhooks today</dt>
              <dd>{countList(data.training_webhooks_today)}</dd>
            </div>
          </dl>
        </>
      ) : null}
    </section>
  );
}

function Platform() {
  const { refresh } = useSession();
  const { data, error, loading, reload } = useLoad(() => api.get<PlatformOrganization[]>('/platform/organizations'), 'platform');

  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugTouched, setSlugTouched] = useState(false);
  const [ownerEmail, setOwnerEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [issued, setIssued] = useState<IssuedInvitation | null>(null);

  const [target, setTarget] = useState<{ org: PlatformOrganization; status: 'active' | 'suspended' } | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [limitsOrg, setLimitsOrg] = useState<PlatformOrganization | null>(null);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!name.trim()) return setFormError('Enter the organization name.');
    if (!SLUG_RE.test(slug)) return setFormError('Slug: lower-case letters, digits and dashes only.');
    if (!ownerEmail.trim()) return setFormError("Enter the owner's email.");
    setBusy(true);
    try {
      const res = await api.post<PlatformCreateResponse>('/platform/organizations', { name: name.trim(), slug, owner_email: ownerEmail.trim() });
      setIssued(res.owner_invitation);
      setName('');
      setSlug('');
      setSlugTouched(false);
      setOwnerEmail('');
      reload();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmStatus() {
    if (!target) return;
    setStatusBusy(true);
    setStatusError(null);
    try {
      await api.patch<Organization>(`/platform/organizations/${seg(target.org.id)}`, { status: target.status });
      setTarget(null);
      reload();
      await refresh(); // suspending an org you belong to changes your own memberships
    } catch (err) {
      setStatusError(errorMessage(err));
    } finally {
      setStatusBusy(false);
    }
  }

  const columns: Column<PlatformOrganization>[] = [
    { key: 'name', header: 'Name', render: (o) => <span className="cell-strong">{o.name}</span> },
    { key: 'slug', header: 'Slug', render: (o) => <span className="mono">{o.slug}</span> },
    {
      key: 'status',
      header: 'Status',
      render: (o) => <span className={o.status === 'active' ? 'badge badge-ok' : 'badge badge-warn'}>{capitalize(o.status)}</span>,
    },
    { key: 'members', header: 'Active members', align: 'end', render: (o) => o.active_members },
    { key: 'created', header: 'Created', render: (o) => formatDate(o.created_at) },
    {
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (o) => (
        <div className="row row-end">
          <Button
            size="sm"
            variant="secondary"
            aria-expanded={limitsOrg?.id === o.id}
            aria-controls="training-limits"
            onClick={() => setLimitsOrg((cur) => (cur?.id === o.id ? null : o))}
            aria-label={`Training limits for ${o.name}`}
          >
            Training limits
          </Button>
          {o.status === 'active' ? (
            <Button size="sm" variant="danger" onClick={() => { setStatusError(null); setTarget({ org: o, status: 'suspended' }); }} aria-label={`Suspend ${o.name}`}>
              Suspend
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={() => { setStatusError(null); setTarget({ org: o, status: 'active' }); }} aria-label={`Reactivate ${o.name}`}>
              Reactivate
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Platform admin" description="Create organizations, suspend or reactivate them, and set their training limits. This gives no access to an organization's data." />

      {issued && <OneTimeLink url={issued.accept_url} email={issued.email} emailed={issued.emailed} onDismiss={() => setIssued(null)} />}

      <section className="panel" aria-labelledby="create-org">
        <h2 id="create-org" className="panel-title">
          Create organization
        </h2>
        <form onSubmit={onCreate} noValidate className="form">
          <FormError message={formError} />
          <TextField
            label="Name"
            required
            maxLength={200}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!slugTouched) setSlug(slugify(e.target.value));
            }}
          />
          <TextField
            label="Slug"
            required
            maxLength={80}
            hint="Lower-case letters, digits and dashes. Must be unique."
            value={slug}
            onChange={(e) => {
              setSlugTouched(true);
              setSlug(e.target.value.toLowerCase());
            }}
          />
          <TextField
            label="Owner email"
            type="email"
            autoComplete="off"
            required
            maxLength={320}
            hint="This person gets an invitation to become the organization's owner."
            value={ownerEmail}
            onChange={(e) => setOwnerEmail(e.target.value)}
          />
          <div>
            <Button type="submit" busy={busy}>
              Create organization
            </Button>
          </div>
        </form>
      </section>

      <section aria-labelledby="all-orgs">
        <h2 id="all-orgs">All organizations</h2>
        {loading && !data ? (
          <SkeletonRows label="Loading organizations" />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <DataTable
            caption="All organizations"
            columns={columns}
            rows={data ?? []}
            rowKey={(o) => o.id}
            empty={<EmptyState title="There are no organizations yet." />}
          />
        )}
      </section>

      {limitsOrg && (
        <section className="panel panel-highlight" id="training-limits" aria-labelledby="training-limits-title">
          <div className="section-head">
            <h2 id="training-limits-title" className="panel-title">
              Training limits: {limitsOrg.name}
            </h2>
            <Button size="sm" variant="ghost" onClick={() => setLimitsOrg(null)}>
              Close
            </Button>
          </div>
          <LimitsEditor key={limitsOrg.id} orgId={limitsOrg.id} />
        </section>
      )}

      <TrainingHealthPanel />

      <ConfirmDialog
        open={target !== null}
        title={target?.status === 'suspended' ? 'Suspend organization?' : 'Reactivate organization?'}
        confirmLabel={target?.status === 'suspended' ? 'Suspend' : 'Reactivate'}
        danger={target?.status === 'suspended'}
        busy={statusBusy}
        error={statusError}
        onConfirm={() => void confirmStatus()}
        onCancel={() => setTarget(null)}
      >
        <p>
          {target?.status === 'suspended' ? (
            <>
              Members of <strong>{target.org.name}</strong> will lose access until it is reactivated, and its invitation links will stop working.
            </>
          ) : target ? (
            <>
              Members of <strong>{target.org.name}</strong> will be able to use it again.
            </>
          ) : null}
        </p>
      </ConfirmDialog>
    </>
  );
}

export default function PlatformPage() {
  const { me } = useSession();
  if (!me.user.is_platform_admin) return <Forbidden message="Only platform administrators can see this page." />;
  return <Platform />;
}

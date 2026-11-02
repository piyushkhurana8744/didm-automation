'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api';
import { CHANNEL_LABELS, CHANNELS, orgPath, query } from '@/lib/agents';
import { plural } from '@/lib/format';
import { dayToIso, failureCodeLabel, SESSION_STATUSES, statusLabel } from '@/lib/training';
import type { AgentListItem, Member, Membership, Page, TrainingLimits, TrainingSession, TrainingUsage } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { SelectField, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Pagination } from '@/components/Pagination';
import { SkeletonRows } from '@/components/Spinner';
import { Tabs, type TabItem } from '@/components/Tabs';
import { WithQuery } from '@/components/WithQuery';
import { AnalyticsTab } from '@/components/training/AnalyticsTab';
import { SessionTable } from '@/components/training/SessionTable';
import { SettingsTab } from '@/components/training/SettingsTab';
import { StatusBadge } from '@/components/training/SessionView';

const LIMIT = 25;

const STATUS_FILTERS = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open (not finished)' },
  ...SESSION_STATUSES.map((s) => ({ value: s, label: statusLabel(s) })),
];

function SessionsTab({ orgId }: { orgId: string }) {
  const [status, setStatus] = useState('');
  const [channel, setChannel] = useState('');
  const [agentId, setAgentId] = useState('');
  const [userId, setUserId] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [offset, setOffset] = useState(0);

  // Only for the filters; if they fail the list still works without them.
  const agents = useLoad(() => api.get<Page<AgentListItem>>(orgPath(orgId, '/agents?status=all&limit=200')).catch(() => null), orgId);
  const members = useLoad(() => api.get<Member[]>(orgPath(orgId, '/members')).catch(() => null), orgId);

  const sinceIso = dayToIso(since);
  const untilIso = dayToIso(until, true);
  const badRange = !!sinceIso && !!untilIso && sinceIso >= untilIso;
  const params = query({ status, channel, agent_id: agentId, user_id: userId, since: sinceIso, until: badRange ? null : untilIso, limit: LIMIT, offset });
  const { data, error, loading, reload } = useLoad(
    () => api.get<Page<TrainingSession>>(orgPath(orgId, `/training/sessions${params}`)),
    `${orgId}|${params}`,
  );

  function change<T>(set: (v: T) => void) {
    return (v: T) => {
      set(v);
      setOffset(0);
    };
  }

  const people = (members.data ?? []).slice().sort((a, b) => a.user.email.localeCompare(b.user.email));

  return (
    <>
      <div className="filters">
        <SelectField label="Status" options={STATUS_FILTERS} value={status} onChange={(e) => change(setStatus)(e.target.value)} />
        <SelectField
          label="Channel"
          options={[{ value: '', label: 'All channels' }, ...CHANNELS.map((c) => ({ value: c, label: CHANNEL_LABELS[c] }))]}
          value={channel}
          onChange={(e) => change(setChannel)(e.target.value)}
        />
        {agents.data && (
          <SelectField
            label="Agent"
            options={[
              { value: '', label: 'All agents' },
              ...agents.data.items.map((a) => ({ value: a.id, label: a.status === 'archived' ? `${a.name} (archived)` : a.name })),
            ]}
            value={agentId}
            onChange={(e) => change(setAgentId)(e.target.value)}
          />
        )}
        {members.data && (
          <SelectField
            label="Trainee"
            options={[{ value: '', label: 'Everyone' }, ...people.map((m) => ({ value: m.user.id, label: m.user.email }))]}
            value={userId}
            onChange={(e) => change(setUserId)(e.target.value)}
          />
        )}
        <TextField label="From" type="date" value={since} onChange={(e) => change(setSince)(e.target.value)} />
        <TextField
          label="To"
          type="date"
          value={until}
          error={badRange ? 'The end is before the start.' : null}
          onChange={(e) => change(setUntil)(e.target.value)}
        />
      </div>
      {loading && !data ? (
        <SkeletonRows label="Loading sessions" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <>
          <SessionTable
            sessions={data?.items ?? []}
            showTrainee
            detailHref={(s) => `/training/session/?id=${encodeURIComponent(s.id)}`}
            empty={<EmptyState title={status === 'open' ? 'No sessions are open right now.' : 'No sessions match these filters.'} />}
          />
          {data && <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} noun="sessions" />}
        </>
      )}
    </>
  );
}

function countRows(counts: Record<string, number>): { key: string; count: number }[] {
  return Object.entries(counts)
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count);
}

function UsageTab({ orgId }: { orgId: string }) {
  const { data, error, loading, reload } = useLoad(() => api.get<TrainingUsage>(orgPath(orgId, '/training/usage')), orgId);
  if (loading && !data) return <SkeletonRows label="Loading usage" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const statusRows = countRows(data.by_status);
  const failureRows = countRows(data.failure_codes);
  const agentColumns: Column<TrainingUsage['by_agent'][number]>[] = [
    { key: 'agent', header: 'Agent', render: (r) => <span className="cell-strong">{r.agent_name ?? r.agent_id}</span> },
    { key: 'sessions', header: 'Sessions', align: 'end', render: (r) => r.sessions },
    { key: 'minutes', header: 'Billable minutes', align: 'end', render: (r) => r.billable_minutes },
  ];

  return (
    <>
      <p className="muted">
        Usage for {data.month}. The organization has {data.limits.monthly_minutes} training minutes a month.
      </p>
      <dl className="stats">
        <div className="stat">
          <dt>Billable minutes</dt>
          <dd>{data.billable_minutes}</dd>
        </div>
        <div className="stat">
          <dt>Reserved minutes</dt>
          <dd>{data.reserved_minutes}</dd>
        </div>
        <div className="stat">
          <dt>Remaining minutes</dt>
          <dd>{data.remaining_minutes}</dd>
        </div>
        <div className="stat">
          <dt>Open sessions</dt>
          <dd>{data.active_sessions}</dd>
        </div>
        <div className="stat">
          <dt>Connected sessions</dt>
          <dd>{data.connected_sessions}</dd>
        </div>
      </dl>
      <p className="small muted">Reserved minutes are held for sessions that are still open; they are released or billed when each one ends.</p>

      <div className="var-grid">
        <section className="panel" aria-labelledby="usage-status">
          <h2 id="usage-status" className="panel-title">
            Sessions by status
          </h2>
          {statusRows.length === 0 ? (
            <p className="muted">No sessions this month.</p>
          ) : (
            <dl className="facts">
              {statusRows.map((r) => (
                <div key={r.key}>
                  <dt>
                    <StatusBadge status={r.key} />
                  </dt>
                  <dd>{r.count}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
        <section className="panel" aria-labelledby="usage-failures">
          <h2 id="usage-failures" className="panel-title">
            Failure reasons
          </h2>
          {failureRows.length === 0 ? (
            <p className="muted">No failed sessions this month.</p>
          ) : (
            <dl className="facts">
              {failureRows.map((r) => (
                <div key={r.key}>
                  <dt className="mono">{failureCodeLabel(r.key)}</dt>
                  <dd>{plural(r.count, 'session')}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </div>

      <section aria-labelledby="usage-agents">
        <h2 id="usage-agents">By agent</h2>
        <DataTable
          caption="Usage by agent"
          columns={agentColumns}
          rows={data.by_agent}
          rowKey={(r) => r.agent_id}
          empty={<EmptyState title="No agent has been used for training this month." />}
        />
      </section>
    </>
  );
}

function yesNo(v: boolean, on = 'On', off = 'Off') {
  return <span className={v ? 'badge badge-ok' : 'badge'}>{v ? on : off}</span>;
}

function LimitsTab({ orgId }: { orgId: string }) {
  const { data, error, loading, reload } = useLoad(() => api.get<TrainingLimits>(orgPath(orgId, '/training/limits')), orgId);
  if (loading && !data) return <SkeletonRows label="Loading limits" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const e = data.effective;
  return (
    <>
      <p className="muted">These limits are set by the platform administrator. Ask them if you need different ones.</p>
      <section className="panel" aria-labelledby="limits-channels">
        <h2 id="limits-channels" className="panel-title">
          Channels
        </h2>
        <dl className="facts facts-wide">
          <div>
            <dt>Training</dt>
            <dd>{yesNo(e.enabled)}</dd>
          </div>
          <div>
            <dt>Phone practice</dt>
            <dd>
              {yesNo(e.phone_enabled, 'Allowed', 'Not allowed')} {yesNo(data.platform.phone_channel_live, 'Live', 'Not live')}
            </dd>
          </div>
          <div>
            <dt>Browser practice</dt>
            <dd>
              {yesNo(e.browser_enabled, 'Allowed', 'Not allowed')} {yesNo(data.platform.browser_channel_live, 'Live', 'Not live')}
            </dd>
          </div>
        </dl>
        <p className="small muted">A channel works only when it is both allowed for this organization and live on the platform.</p>
      </section>
      <section className="panel" aria-labelledby="limits-numbers">
        <h2 id="limits-numbers" className="panel-title">
          Limits
        </h2>
        <dl className="facts facts-wide">
          <div>
            <dt>Open sessions at once</dt>
            <dd>{e.org_concurrency}</dd>
          </div>
          <div>
            <dt>Open sessions per person</dt>
            <dd>{e.user_concurrency}</dd>
          </div>
          <div>
            <dt>Sessions per person per day</dt>
            <dd>{e.sessions_per_day}</dd>
          </div>
          <div>
            <dt>Longest session</dt>
            <dd>{e.session_minutes} minutes</dd>
          </div>
          <div>
            <dt>Minutes per month</dt>
            <dd>{e.monthly_minutes}</dd>
          </div>
          <div>
            <dt>Platform capacity</dt>
            <dd>{plural(e.platform_concurrency, 'session')} at once, shared by all organizations</dd>
          </div>
        </dl>
      </section>
    </>
  );
}

function Training({ membership, tab }: { membership: Membership; tab: string }) {
  const orgId = membership.organization.id;
  const router = useRouter();
  const tabs: TabItem[] = [
    { id: 'sessions', label: 'Sessions' },
    { id: 'analytics', label: 'Analytics' },
    { id: 'usage', label: 'Usage' },
    { id: 'limits', label: 'Limits' },
    { id: 'settings', label: 'Settings' },
  ];
  const current = tabs.some((t) => t.id === tab) ? tab : 'sessions';
  return (
    <>
      <PageHeader title="Training" description={`Practice sessions, scores, usage and settings in ${membership.organization.name}.`} />
      <Tabs label="Training sections" tabs={tabs} selected={current} onSelect={(id) => router.replace(`/training/?tab=${id}`, { scroll: false })}>
        {current === 'sessions' && <SessionsTab orgId={orgId} />}
        {current === 'usage' && <UsageTab orgId={orgId} />}
        {current === 'limits' && <LimitsTab orgId={orgId} />}
        {current === 'analytics' && <AnalyticsTab orgId={orgId} />}
        {current === 'settings' && <SettingsTab orgId={orgId} canEdit={membership.permissions.includes('recordings.manage')} />}
      </Tabs>
    </>
  );
}

export default function TrainingPage() {
  return (
    <OrgGate permission="training.view">
      {(m) => <WithQuery>{(params) => <Training membership={m} tab={params.get('tab') ?? 'sessions'} />}</WithQuery>}
    </OrgGate>
  );
}

'use client';

import Link from 'next/link';
import { api } from '@/lib/api';
import { accessLine, channelList, orgPath, settingsSummary } from '@/lib/agents';
import { formatDateTime, plural } from '@/lib/format';
import type { Membership, MyAgent, MyAssignment } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

function MyTraining({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const agents = useLoad(() => api.get<MyAgent[]>(orgPath(orgId, '/my/agents')), orgId);
  const assignments = useLoad(() => api.get<MyAssignment[]>(orgPath(orgId, '/my/assignments')), orgId);
  const scheduled = (assignments.data ?? []).filter((a) => a.state === 'scheduled');

  return (
    <>
      <PageHeader title="My training" description={`Voice agents you can practise with in ${membership.organization.name}.`} />
      <p>
        Open an agent to pick a scenario and start a practice session. <Link href="/my-training/history/">See your past sessions</Link> or{' '}
        <Link href="/my-training/progress/">your progress</Link>.
      </p>
      <section aria-labelledby="my-agents">
        <h2 id="my-agents">Your agents</h2>
        {agents.loading && !agents.data ? (
          <SkeletonRows label="Loading your agents" />
        ) : agents.error ? (
          <ErrorState error={agents.error} onRetry={agents.reload} />
        ) : (agents.data ?? []).length === 0 ? (
          <EmptyState title="No agents have been assigned to you yet.">
            <p>When a trainer gives you access to a voice agent, it will show up here.</p>
          </EmptyState>
        ) : (
          <ul className="card-list">
            {(agents.data ?? []).map((a) => (
              <li key={a.id} className="card">
                <div className="card-main">
                  <h3 className="card-title">
                    <Link href={`/my-training/agent/?id=${encodeURIComponent(a.id)}`}>{a.name}</Link>
                  </h3>
                  <p className="card-meta">
                    {a.category && <span className="badge">{a.category}</span>}
                    {plural(a.scenario_count, 'scenario')} · version {a.version.internal_version}
                  </p>
                  {a.description && <p className="small">{a.description}</p>}
                  <p className="small muted">{accessLine(a)}</p>
                  <p className="small muted">Channels: {channelList(a.channels)}</p>
                </div>
                <Link href={`/my-training/agent/?id=${encodeURIComponent(a.id)}`} className="btn btn-secondary">
                  Practise
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {scheduled.length > 0 && (
        <section aria-labelledby="my-upcoming">
          <h2 id="my-upcoming">Starting later</h2>
          <ul className="card-list">
            {scheduled.map((a) => (
              <li key={a.id} className="card">
                <div className="card-main">
                  <h3 className="card-title">{a.agent_name ?? 'Agent'}</h3>
                  <p className="card-meta">
                    Starts {formatDateTime(a.starts_at)}
                    {a.expires_at ? `, ends ${formatDateTime(a.expires_at)}` : ''}
                    {a.team_name ? ` · through ${a.team_name}` : ''}
                  </p>
                  <p className="small muted">{settingsSummary(a.settings)}</p>
                </div>
                <span className="badge badge-info">Scheduled</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {assignments.error ? <p className="field-hint">Upcoming assignments could not be loaded.</p> : null}
    </>
  );
}

export default function MyTrainingPage() {
  return <OrgGate permission="training.self">{(m) => <MyTraining membership={m} />}</OrgGate>;
}

'use client';

import Link from 'next/link';
import { api, seg } from '@/lib/api';
import { accessLine, DIFFICULTY_LABELS, orgPath } from '@/lib/agents';
import { formatDate, plural } from '@/lib/format';
import type { Membership, MyAgentDetail } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState, NotFoundState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';
import { WithQuery } from '@/components/WithQuery';
import { StartPractice } from '@/components/training/StartPractice';
import { PersonalAgentTraining } from '@/components/training/PersonalAgentTraining';

function MyAgentView({ membership, agentId }: { membership: Membership; agentId: string }) {
  const orgId = membership.organization.id;
  const { data, error, loading, reload } = useLoad(
    () => api.get<MyAgentDetail>(orgPath(orgId, `/my/agents/${seg(agentId)}`)),
    `${orgId}|${agentId}`,
  );

  if (loading && !data) return <Spinner label="Loading agent" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <p className="small">
        <Link href="/my-training/">← My training</Link>
      </p>
      <PageHeader title={data.name} description={data.description || undefined} />
      <section className="panel" aria-labelledby="access-title">
        <h2 id="access-title" className="panel-title">
          Your access
        </h2>
        <dl className="facts">
          {data.category && (
            <div>
              <dt>Category</dt>
              <dd>{data.category}</dd>
            </div>
          )}
          <div>
            <dt>Access</dt>
            <dd>{accessLine(data)}</dd>
          </div>
          <div>
            <dt>Agent version</dt>
            <dd>
              Version {data.version.internal_version}
              {data.version.published_at ? `, published ${formatDate(data.version.published_at)}` : ''}
            </dd>
          </div>
        </dl>
      </section>

      <section className="panel" aria-labelledby="channels-title">
        <h2 id="channels-title" className="panel-title">
          Start practising
        </h2>
        <p className="muted">
          Choose a scenario and the agent will call you. <Link href="/my-training/history/">See your past sessions</Link>.
        </p>
        <StartPractice orgId={orgId} agent={data} />
      </section>

      <PersonalAgentTraining orgId={orgId} agentId={data.id} variableSchema={data.version.variable_schema ?? []} />

      <section aria-labelledby="scenarios-title">
        <h2 id="scenarios-title">Scenarios ({plural(data.scenarios.length, 'scenario')})</h2>
        {data.scenarios.length === 0 ? (
          <EmptyState title="No scenarios are available for you yet." />
        ) : (
          <ul className="card-list scenario-list">
            {data.scenarios.map((s) => (
              <li key={s.id} className="card">
                <div className="card-main">
                  <h3 className="card-title">{s.name}</h3>
                  <p className="card-meta">
                    <span className="badge">{DIFFICULTY_LABELS[s.difficulty] ?? s.difficulty}</span>
                  </p>
                  {s.description && <p className="small">{s.description}</p>}
                  {s.objective && (
                    <p className="small">
                      <strong>Objective:</strong> {s.objective}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

export default function MyAgentPage() {
  return (
    <OrgGate permission="training.self">
      {(m) => (
        <WithQuery>
          {(params) => {
            const id = params.get('id');
            return id ? <MyAgentView key={id} membership={m} agentId={id} /> : <NotFoundState message="No agent was chosen." />;
          }}
        </WithQuery>
      )}
    </OrgGate>
  );
}

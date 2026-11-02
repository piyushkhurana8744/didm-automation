'use client';

import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/lib/api';
import { CHANNEL_LABELS, orgPath } from '@/lib/agents';
import { formatDate, plural } from '@/lib/format';
import { analyticsExportUrl, intelligenceApi, PERIODS, SCORE_BUCKETS, type AnalyticsFilters } from '@/lib/intelligence';
import type { AgentListItem, AnalyticsAgent, AnalyticsScenario, AnalyticsTeam, AnalyticsTrainee, Page, Team } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { DataTable, type Column } from '../DataTable';
import { EmptyState } from '../EmptyState';
import { ErrorState } from '../ErrorState';
import { SelectField } from '../Field';
import { Pagination } from '../Pagination';
import { SkeletonRows } from '../Spinner';
import { Bar, ScoreValue, SkillsTable } from './ProgressView';

const TRAINEES_PAGE_SIZE = 50;

function Score({ value }: { value: number | null }) {
  return value === null || value === undefined ? <span className="muted">No score</span> : <>{value}</>;
}

/** Scores, participation and practice across the organization, for trainers and admins. */
export function AnalyticsTab({ orgId }: { orgId: string }) {
  const [days, setDays] = useState('30');
  const [teamId, setTeamId] = useState('');
  const [agentId, setAgentId] = useState('');
  const [traineeOffset, setTraineeOffset] = useState(0);
  const filters: AnalyticsFilters = { days: Number(days), team_id: teamId, agent_id: agentId };
  // A new filter starts the trainee table from its first page again.
  const setFilter = (set: (v: string) => void) => (v: string) => {
    set(v);
    setTraineeOffset(0);
  };

  // Only for the filters; if they fail the analytics still work without them.
  const teams = useLoad(() => api.get<Team[]>(orgPath(orgId, '/teams')).catch(() => null), orgId);
  const agents = useLoad(() => api.get<Page<AgentListItem>>(orgPath(orgId, '/agents?status=all&limit=200')).catch(() => null), orgId);

  const key = `${orgId}|${days}|${teamId}|${agentId}|${traineeOffset}`;
  const { data, error, loading, reload } = useLoad(
    () => intelligenceApi.analytics(orgId, { ...filters, page: Math.floor(traineeOffset / TRAINEES_PAGE_SIZE) + 1, page_size: TRAINEES_PAGE_SIZE }),
    key,
  );
  const traineesPage = data?.trainees_page;

  const traineeColumns: Column<AnalyticsTrainee>[] = [
    {
      key: 'who',
      header: 'Trainee',
      render: (t) => (
        <Link href={`/training/trainee/?id=${encodeURIComponent(t.user_id)}`} className="cell-strong break">
          {t.name || t.email || t.user_id}
        </Link>
      ),
    },
    { key: 'sessions', header: 'Sessions', align: 'end', render: (t) => t.sessions },
    { key: 'practice', header: 'Practised', align: 'end', render: (t) => t.practice_sessions },
    { key: 'evaluated', header: 'Scored', align: 'end', render: (t) => t.evaluated },
    { key: 'score', header: 'Average score', align: 'end', render: (t) => <Score value={t.average_score} /> },
    { key: 'minutes', header: 'Minutes', align: 'end', render: (t) => t.practice_minutes },
    { key: 'last', header: 'Last session', render: (t) => formatDate(t.last_session_at) },
  ];
  const teamColumns: Column<AnalyticsTeam>[] = [
    { key: 'name', header: 'Team', render: (t) => <span className="cell-strong">{t.name}</span> },
    { key: 'members', header: 'Members', align: 'end', render: (t) => t.members },
    { key: 'active', header: 'Practised', align: 'end', render: (t) => t.active_trainees },
    { key: 'practice', header: 'Practice sessions', align: 'end', render: (t) => t.practice_sessions },
    { key: 'evaluated', header: 'Scored', align: 'end', render: (t) => t.evaluated },
    { key: 'score', header: 'Average score', align: 'end', render: (t) => <Score value={t.average_score} /> },
  ];
  const agentColumns: Column<AnalyticsAgent>[] = [
    { key: 'name', header: 'Agent', render: (a) => <span className="cell-strong">{a.agent_name ?? a.agent_id}</span> },
    { key: 'sessions', header: 'Sessions', align: 'end', render: (a) => a.sessions },
    { key: 'completed', header: 'Completed', align: 'end', render: (a) => a.completed },
    { key: 'failed', header: 'Failed', align: 'end', render: (a) => a.failed + a.timed_out },
    { key: 'practice', header: 'Practised', align: 'end', render: (a) => a.practice_sessions },
    { key: 'evaluated', header: 'Scored', align: 'end', render: (a) => a.evaluated },
    { key: 'score', header: 'Average score', align: 'end', render: (a) => <Score value={a.average_score} /> },
    { key: 'minutes', header: 'Minutes', align: 'end', render: (a) => a.practice_minutes },
  ];
  const scenarioColumns: Column<AnalyticsScenario>[] = [
    { key: 'name', header: 'Scenario', render: (s) => <span className="cell-strong">{s.scenario_name ?? s.scenario_id}</span> },
    { key: 'practice', header: 'Practice sessions', align: 'end', render: (s) => s.practice_sessions },
    { key: 'trainees', header: 'Trainees', align: 'end', render: (s) => s.trainees },
    { key: 'score', header: 'Average score', align: 'end', render: (s) => <Score value={s.average_score} /> },
  ];

  const dist = data?.score_distribution ?? {};
  const buckets = [...SCORE_BUCKETS, ...Object.keys(dist).filter((k) => !SCORE_BUCKETS.includes(k))];
  const maxBucket = Math.max(0, ...buckets.map((b) => dist[b] ?? 0));

  return (
    <>
      <div className="filters">
        <SelectField label="Period" options={PERIODS} value={days} onChange={(e) => setFilter(setDays)(e.target.value)} />
        {teams.data && (
          <SelectField
            label="Team"
            options={[{ value: '', label: 'All teams' }, ...teams.data.map((t) => ({ value: t.id, label: t.name }))]}
            value={teamId}
            onChange={(e) => setFilter(setTeamId)(e.target.value)}
          />
        )}
        {agents.data && (
          <SelectField
            label="Agent"
            options={[
              { value: '', label: 'All agents' },
              ...agents.data.items.map((a) => ({ value: a.id, label: a.status === 'archived' ? `${a.name} (archived)` : a.name })),
            ]}
            value={agentId}
            onChange={(e) => setFilter(setAgentId)(e.target.value)}
          />
        )}
      </div>
      <div className="row">
        {/* Plain links: the session cookie authenticates the download, and the API is outside the app's base path. */}
        <a className="btn btn-secondary btn-sm" href={analyticsExportUrl(orgId, 'sessions', filters)} download>
          Download sessions CSV
        </a>
        <a className="btn btn-secondary btn-sm" href={analyticsExportUrl(orgId, 'trainees', filters)} download>
          Download trainees CSV
        </a>
      </div>
      {loading && !data ? (
        <SkeletonRows label="Loading analytics" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data ? (
        <>
          <dl className="stats">
            <div className="stat">
              <dt>Sessions</dt>
              <dd>{data.totals.sessions}</dd>
            </div>
            <div className="stat">
              <dt>Practice sessions</dt>
              <dd>{data.totals.practice_sessions}</dd>
            </div>
            <div className="stat">
              <dt>Scored sessions</dt>
              <dd>{data.totals.evaluated_sessions}</dd>
            </div>
            <div className="stat">
              <dt>Average score</dt>
              <dd>
                <ScoreValue score={data.totals.average_score} />
              </dd>
            </div>
            <div className="stat">
              <dt>Practice minutes</dt>
              <dd>{data.totals.practice_minutes}</dd>
            </div>
            <div className="stat">
              <dt>Active trainees</dt>
              <dd>{data.totals.active_trainees}</dd>
            </div>
          </dl>
          <p className="small muted">
            The last {plural(data.period_days, 'day')}. {data.rules}
          </p>

          <div className="var-grid">
            <section className="panel" aria-labelledby="an-participation">
              <h2 id="an-participation" className="panel-title">
                Participation
              </h2>
              {data.participation.trainees === 0 ? (
                <p className="muted">There are no active trainees{teamId ? ' in this team' : ''}.</p>
              ) : (
                <>
                  <p>
                    <strong>{data.participation.practised}</strong> of {plural(data.participation.trainees, 'trainee')} practised in this period.
                  </p>
                  <Bar
                    value={data.participation.practised}
                    max={data.participation.trainees}
                    label={`${data.participation.practised} of ${data.participation.trainees} trainees practised`}
                  />
                </>
              )}
              {data.by_channel.length > 0 && (
                <dl className="facts">
                  {data.by_channel.map((c) => (
                    <div key={c.channel}>
                      <dt>{CHANNEL_LABELS[c.channel] ?? c.channel}</dt>
                      <dd>
                        {plural(c.sessions, 'session')} · {c.practice_minutes} min
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </section>
            <section className="panel" aria-labelledby="an-dist">
              <h2 id="an-dist" className="panel-title">
                Score distribution
              </h2>
              {data.totals.evaluated_sessions === 0 ? (
                <p className="muted">No sessions were scored in this period.</p>
              ) : (
                <ul className="dist-list">
                  {buckets.map((b) => (
                    <li key={b} className="bar-row">
                      <span className="dist-label">{b}</span>
                      <Bar value={dist[b] ?? 0} max={maxBucket} label={`${dist[b] ?? 0} sessions scored ${b}`} />
                      <span className="dist-count">{dist[b] ?? 0}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section aria-labelledby="an-trainees">
            <h2 id="an-trainees">Trainees</h2>
            <DataTable
              caption="Trainees"
              columns={traineeColumns}
              rows={data.trainees}
              rowKey={(t) => t.user_id}
              empty={<EmptyState title="Nobody had a session in this period." />}
            />
            {traineesPage && (
              <Pagination
                total={traineesPage.total}
                limit={traineesPage.page_size}
                offset={(traineesPage.page - 1) * traineesPage.page_size}
                onChange={setTraineeOffset}
                noun="trainees"
              />
            )}
          </section>
          <section aria-labelledby="an-teams">
            <h2 id="an-teams">Teams</h2>
            <DataTable caption="Teams" columns={teamColumns} rows={data.teams} rowKey={(t) => t.team_id} empty={<EmptyState title="There are no teams." />} />
          </section>
          <section aria-labelledby="an-agents">
            <h2 id="an-agents">Agents</h2>
            <DataTable
              caption="Agents"
              columns={agentColumns}
              rows={data.agents}
              rowKey={(a) => a.agent_id}
              empty={<EmptyState title="No agent was used in this period." />}
            />
          </section>
          <section aria-labelledby="an-scenarios">
            <h2 id="an-scenarios">Scenarios</h2>
            <DataTable
              caption="Scenarios"
              columns={scenarioColumns}
              rows={data.scenarios}
              rowKey={(s) => s.scenario_id}
              empty={<EmptyState title="No scenario was practised in this period." />}
            />
          </section>
          <section aria-labelledby="an-skills">
            <h2 id="an-skills">Skills</h2>
            <SkillsTable skills={data.skills} caption="Average score per skill" />
          </section>
        </>
      ) : null}
    </>
  );
}

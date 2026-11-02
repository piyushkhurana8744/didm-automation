'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { api, errorMessage } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { fromLocalInput } from '@/lib/format';
import { roleLabel } from '@/lib/roles';
import type { AgentListItem, AssignResult, Member, Membership, Page, Team } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { AssignmentSettingsFields, settingsFromDraft, type SettingsDraft } from '@/components/AssignmentSettingsFields';
import { Button } from '@/components/Button';
import { CheckList } from '@/components/CheckList';
import { ErrorState } from '@/components/ErrorState';
import { FormError, TextField } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';
import { WithQuery } from '@/components/WithQuery';

type Errors = Partial<Record<'agents' | 'targets' | 'starts' | 'expires' | 'maxSessions' | 'maxMinutes', string>>;

function NewAssignment({ membership, initialAgent }: { membership: Membership; initialAgent: string | null }) {
  const orgId = membership.organization.id;
  const isTrainer = membership.role === 'trainer';
  const canSeeTeams = membership.permissions.includes('teams.view');
  const agents = useLoad(() => api.get<Page<AgentListItem>>(orgPath(orgId, '/agents?status=active&limit=200')), orgId);
  const members = useLoad(() => api.get<Member[]>(orgPath(orgId, '/members')), orgId);
  const teams = useLoad(canSeeTeams ? () => api.get<Team[]>(orgPath(orgId, '/teams')) : null, canSeeTeams ? orgId : null);

  const [agentIds, setAgentIds] = useState<string[]>(initialAgent ? [initialAgent] : []);
  const [userIds, setUserIds] = useState<string[]>([]);
  const [teamIds, setTeamIds] = useState<string[]>([]);
  const [starts, setStarts] = useState('');
  const [expires, setExpires] = useState('');
  const [settings, setSettings] = useState<SettingsDraft>({ scenarioIds: [], maxSessions: '', maxMinutes: '' });
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AssignResult | null>(null);

  // The trainee API intentionally exposes only agents backed by an immutable published version.
  // Do not offer drafts here: accepting one creates an assignment that looks active to an admin but
  // cannot (and must not) appear to its trainee.
  const agentList = (agents.data?.items ?? []).filter((a) => a.published_version_id !== null);
  const people = (members.data ?? []).filter((m) => m.status === 'active' && (!isTrainer || m.role === 'trainee'));
  const singleAgent = agentIds.length === 1 ? agentIds[0] : null;
  const agentName = new Map(agentList.map((a) => [a.id, a.name]));
  const personName = new Map((members.data ?? []).map((m) => [m.user.id, m.user.name || m.user.email]));
  const teamName = new Map((teams.data ?? []).map((t) => [t.id, t.name]));

  function chooseAgents(ids: string[]) {
    // Allowed scenarios belong to one agent: clear them when the selection changes
    if ((ids.length === 1 ? ids[0] : null) !== singleAgent) setSettings((s) => ({ ...s, scenarioIds: [] }));
    setAgentIds(ids);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const next: Errors = {};
    if (agentIds.length === 0) next.agents = 'Choose at least one agent.';
    if (userIds.length === 0 && teamIds.length === 0) next.targets = 'Choose at least one person or team.';
    else if (agentIds.length * (userIds.length + teamIds.length) > 1000) next.targets = 'At most 1000 assignments at a time.';
    const startsIso = fromLocalInput(starts);
    const expiresIso = fromLocalInput(expires);
    if (starts && !startsIso) next.starts = 'Enter a valid date and time.';
    if (expires && !expiresIso) next.expires = 'Enter a valid date and time.';
    else if (expiresIso) {
      if (new Date(expiresIso).getTime() <= Date.now()) next.expires = 'The end must be in the future.';
      else if (startsIso && new Date(expiresIso) <= new Date(startsIso)) next.expires = 'The end must be after the start.';
    }
    const s = settingsFromDraft(settings, !!singleAgent);
    Object.assign(next, s.errors);
    setErrors(next);
    if (Object.keys(next).length) {
      setFormError('Fix the highlighted fields.');
      return;
    }
    setBusy(true);
    try {
      const res = await api.post<AssignResult>(orgPath(orgId, '/assignments'), {
        agent_ids: agentIds,
        user_ids: userIds,
        team_ids: teamIds,
        ...(startsIso ? { starts_at: startsIso } : {}),
        ...(expiresIso ? { expires_at: expiresIso } : {}),
        settings: s.settings,
      });
      setResult(res);
      setUserIds([]);
      setTeamIds([]);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const loadingAny = (agents.loading && !agents.data) || (members.loading && !members.data);
  const loadError = agents.error || members.error;

  return (
    <>
      <p className="small">
        <Link href="/assignments/">← Assignments</Link>
      </p>
      <PageHeader title="Assign agents" description="Choose agents, then the people and teams who should have them." />
      {result && (
        <section className="panel panel-highlight" aria-labelledby="assign-result" role="status">
          <h2 id="assign-result" className="panel-title">
            {result.created.length} {result.created.length === 1 ? 'assignment' : 'assignments'} created
          </h2>
          {result.skipped.length > 0 && (
            <>
              <p>These already had open access and were left unchanged:</p>
              <ul className="link-list">
                {result.skipped.map((s) => (
                  <li key={s.assignment_id}>
                    {agentName.get(s.agent_id) ?? 'Agent'} →{' '}
                    {s.team_id ? `team ${teamName.get(s.team_id) ?? s.team_id}` : personName.get(s.user_id ?? '') ?? s.user_id}{' '}
                    (<Link href={`/assignments/detail/?id=${encodeURIComponent(s.assignment_id)}`}>existing assignment</Link>)
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="form-actions">
            <Link href="/assignments/" className="btn btn-secondary">
              View all assignments
            </Link>
            <Button variant="ghost" onClick={() => setResult(null)}>
              Assign more
            </Button>
          </div>
        </section>
      )}
      {loadingAny ? (
        <SkeletonRows label="Loading agents and people" />
      ) : loadError ? (
        <ErrorState
          error={loadError}
          onRetry={() => {
            agents.reload();
            members.reload();
          }}
        />
      ) : (
        <section className="panel">
          <form onSubmit={onSubmit} noValidate className="form form-wide">
            <FormError message={formError} />
            <CheckList
              legend="Agents"
              options={agentList.map((a) => ({
                value: a.id,
                label: a.name,
                meta: `version ${a.published_internal_version}`,
              }))}
              selected={agentIds}
              onChange={(ids) => {
                chooseAgents(ids);
                setErrors((x) => ({ ...x, agents: undefined }));
              }}
              error={errors.agents}
              empty={<>There are no published active agents. <Link href="/agents/">Publish an agent first</Link>.</>}
            />
            <CheckList
              legend={isTrainer ? 'Trainees' : 'People'}
              hint={isTrainer ? 'As a trainer you can assign agents to trainees only.' : undefined}
              options={people.map((m) => ({ value: m.user.id, label: m.user.name || m.user.email, meta: `${m.user.email} · ${roleLabel(m.role)}` }))}
              selected={userIds}
              onChange={(ids) => {
                setUserIds(ids);
                setErrors((x) => ({ ...x, targets: undefined }));
              }}
              error={errors.targets}
              empty="There is nobody you can assign to."
            />
            {canSeeTeams &&
              (teams.error ? (
                <p className="field-error">Teams could not be loaded.</p>
              ) : (
                <CheckList
                  legend="Teams"
                  hint="Everyone in the team gets access, including people added to it later."
                  options={(teams.data ?? []).map((t) => ({ value: t.id, label: t.name, meta: `${t.member_count ?? 0} members` }))}
                  selected={teamIds}
                  onChange={(ids) => {
                    setTeamIds(ids);
                    setErrors((x) => ({ ...x, targets: undefined }));
                  }}
                  empty="There are no active teams."
                />
              ))}
            <div className="form-grid">
              <TextField
                label="Starts (optional)"
                type="datetime-local"
                value={starts}
                error={errors.starts}
                onChange={(e) => setStarts(e.target.value)}
                hint="Empty means now. Times are in your local time zone."
              />
              <TextField
                label="Ends (optional)"
                type="datetime-local"
                value={expires}
                error={errors.expires}
                onChange={(e) => setExpires(e.target.value)}
                hint="Empty means no end date."
              />
            </div>
            <AssignmentSettingsFields
              orgId={orgId}
              agentId={singleAgent}
              value={settings}
              onChange={setSettings}
              errors={{ maxSessions: errors.maxSessions, maxMinutes: errors.maxMinutes }}
            />
            <div className="form-actions">
              <Button type="submit" busy={busy}>
                Assign
              </Button>
              <Link href="/assignments/" className="btn btn-ghost">
                Cancel
              </Link>
            </div>
          </form>
        </section>
      )}
    </>
  );
}

export default function NewAssignmentPage() {
  return (
    <OrgGate permission="assignments.manage">
      {(m) => <WithQuery>{(params) => <NewAssignment membership={m} initialAgent={params.get('agent_id')} />}</WithQuery>}
    </OrgGate>
  );
}

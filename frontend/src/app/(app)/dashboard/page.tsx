'use client';

import Link from 'next/link';
import { api, seg } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import type { DashboardSummary, Membership } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { ButtonLink } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';

const ACTION_LABELS: Record<string, string> = {
  'invitation.created': 'Invitation created',
  'invitation.resent': 'Invitation link renewed',
  'invitation.revoked': 'Invitation revoked',
  'invitation.accepted': 'New member joined',
  'assignment.created': 'AI coach assigned',
  'assignment.revoked': 'Assignment revoked',
  'agent.created': 'Agent registered',
  'agent.version_published': 'Agent version published',
  'training.session_requested': 'Practice session requested',
};

function Dashboard({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const { data, error, loading, reload } = useLoad(() => api.get<DashboardSummary>(`/organizations/${seg(orgId)}/dashboard`), orgId);
  const canInvite = membership.permissions.includes('invitations.manage');
  const canAssign = membership.permissions.includes('assignments.manage');
  const canManageAgents = membership.permissions.includes('agents.manage');

  return <>
    <PageHeader title={`Welcome back to ${membership.organization.name}`} description="Onboard your team, connect AI coaches and follow training outcomes from one place."
      actions={canInvite ? <ButtonLink href="/invitations/?role=trainee" variant="primary">Add trainee</ButtonLink> : undefined} />
    <section className="quick-actions" aria-labelledby="quick-actions-title">
      <div><p className="eyebrow">Get started</p><h2 id="quick-actions-title">Quick actions</h2></div>
      <div className="quick-action-links">
        {canInvite && <ButtonLink href="/invitations/?role=trainee">Add trainee</ButtonLink>}
        {canInvite && <ButtonLink href="/invitations/?role=trainer">Invite trainer</ButtonLink>}
        {canAssign && <ButtonLink href="/assignments/new/">Assign AI agent</ButtonLink>}
        {canManageAgents && <ButtonLink href="/agents/new/">Register agent</ButtonLink>}
        {membership.permissions.includes('training.view') && <ButtonLink href="/training/">View training reports</ButtonLink>}
      </div>
    </section>
    {loading && !data ? <SkeletonRows label="Loading dashboard" /> : error ? <ErrorState error={error} onRetry={reload} /> : data ? <>
      <section aria-labelledby="overview-title"><h2 id="overview-title">Training overview</h2>
        <dl className="stats stats-dashboard">
          <div className="stat"><dt>Active trainees</dt><dd>{data.active_trainees}</dd><span>{data.total_trainees} total</span></div>
          <div className="stat"><dt>Active agents</dt><dd>{data.active_agents}</dd><span>ready in your catalog</span></div>
          <div className="stat"><dt>Assigned trainees</dt><dd>{data.assigned_trainees}</dd><span>with at least one coach</span></div>
          <div className="stat"><dt>Training sessions</dt><dd>{data.training_sessions}</dd><span>all time</span></div>
          <div className="stat"><dt>Average score</dt><dd>{data.average_score === null ? '—' : `${data.average_score}%`}</dd><span>completed evaluations</span></div>
          <div className="stat"><dt>Pending invitations</dt><dd>{data.pending_invitations}</dd><span>awaiting acceptance</span></div>
        </dl>
      </section>
      <div className="dashboard-columns">
        <section className="panel" aria-labelledby="onboarding-title"><p className="eyebrow">Recommended workflow</p><h2 id="onboarding-title" className="panel-title">Launch your first practice session</h2>
          <ol className="workflow-list">
            <li><span>1</span><div><strong>Invite a trainee</strong><p>They receive a secure, expiring activation link.</p></div></li>
            <li><span>2</span><div><strong>Register and publish an agent</strong><p>Link the agent you built in Sarvam.</p></div></li>
            <li><span>3</span><div><strong>Assign the AI coach</strong><p>Choose a scenario, quota and expiry.</p></div></li>
            <li><span>4</span><div><strong>Review performance</strong><p>Follow sessions, evaluations and feedback.</p></div></li>
          </ol>{canInvite && <Link href="/invitations/?role=trainee">Start with a trainee →</Link>}
        </section>
        <section className="panel" aria-labelledby="activity-title"><h2 id="activity-title" className="panel-title">Recent activity</h2>
          {data.recent_activity.length ? <ul className="activity-list">{data.recent_activity.map((item) => <li key={item.id}><span className="activity-dot" aria-hidden="true" /><div><strong>{ACTION_LABELS[item.action] ?? item.action.replaceAll('.', ' ')}</strong><p>{formatDateTime(item.created_at)}</p></div></li>)}</ul> : <EmptyState title="No activity yet.">Invite a trainee or register an agent to get started.</EmptyState>}
        </section>
      </div>
    </> : null}
  </>;
}

export default function DashboardPage() {
  return <OrgGate permission="org.view">{(m) => <Dashboard membership={m} />}</OrgGate>;
}

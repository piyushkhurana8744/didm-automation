'use client';

import { api } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import type { AgentListItem, Membership, Page } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { AssignmentList } from '@/components/AssignmentList';
import { ButtonLink } from '@/components/Button';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';

function Assignments({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  // Only for the agent filter; if it fails the list still works without it
  const agents = useLoad(
    () => api.get<Page<AgentListItem>>(orgPath(orgId, '/agents?status=all&limit=200')).catch(() => null),
    orgId,
  );
  return (
    <>
      <PageHeader
        title="Assignments"
        description={
          membership.role === 'trainer'
            ? 'Give trainees and teams access to agents. Trainers can assign agents to trainees and teams only.'
            : 'Give people and teams access to agents, for a period you choose.'
        }
        actions={<ButtonLink href="/assignments/new/" variant="primary">Assign agents</ButtonLink>}
      />
      <AssignmentList orgId={orgId} agents={agents.data?.items ?? []} />
    </>
  );
}

export default function AssignmentsPage() {
  return <OrgGate permission="assignments.manage">{(m) => <Assignments membership={m} />}</OrgGate>;
}

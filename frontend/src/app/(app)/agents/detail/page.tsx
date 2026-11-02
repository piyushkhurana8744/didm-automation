'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import type { Agent, AgentDetail, Membership, Permission } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { AssignmentList } from '@/components/AssignmentList';
import { Button } from '@/components/Button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { ErrorState, NotFoundState } from '@/components/ErrorState';
import { FormSuccess } from '@/components/Field';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';
import { Tabs, type TabItem } from '@/components/Tabs';
import { WithQuery } from '@/components/WithQuery';
import { AgentOverview } from '@/components/agent/AgentOverview';
import { AgentTraining } from '@/components/agent/AgentTraining';
import { DraftEditor } from '@/components/agent/DraftEditor';
import { ScenarioPanel } from '@/components/agent/ScenarioPanel';
import { VersionHistory } from '@/components/agent/VersionHistory';

function AgentDetailView({ membership, agentId, tab }: { membership: Membership; agentId: string; tab: string }) {
  const orgId = membership.organization.id;
  const router = useRouter();
  const can = (p: Permission) => membership.permissions.includes(p);
  const canManage = can('agents.manage');
  const { data: agent, error, loading, reload, setData } = useLoad(
    () => api.get<AgentDetail>(orgPath(orgId, `/agents/${seg(agentId)}`)),
    `${orgId}|${agentId}`,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<'archive' | 'restore' | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const tabs: TabItem[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'configuration', label: agent?.draft_version ? 'Configuration (draft)' : 'Configuration' },
    { id: 'training', label: 'Training' },
    { id: 'versions', label: 'Versions' },
    { id: 'scenarios', label: agent ? `Scenarios (${agent.counts.scenarios})` : 'Scenarios' },
  ];
  if (can('assignments.manage')) tabs.push({ id: 'assignments', label: agent ? `Assignments (${agent.counts.open_assignments})` : 'Assignments' });
  const current = tabs.some((t) => t.id === tab) ? tab : 'overview';

  function selectTab(id: string) {
    router.replace(`/agents/detail/?id=${encodeURIComponent(agentId)}&tab=${id}`, { scroll: false });
  }

  function changed(message?: string) {
    setNotice(message ?? null);
    reload();
  }

  async function onConfirm() {
    if (!confirm) return;
    setConfirmBusy(true);
    setConfirmError(null);
    try {
      await api.post<Agent>(orgPath(orgId, `/agents/${seg(agentId)}/${confirm}`));
      setNotice(confirm === 'archive' ? 'The agent was archived.' : 'The agent was restored.');
      setConfirm(null);
      reload();
    } catch (e) {
      setConfirmError(errorMessage(e));
    } finally {
      setConfirmBusy(false);
    }
  }

  if (loading && !agent) return <Spinner label="Loading agent" />;
  if (error && !agent) return <ErrorState error={error} onRetry={reload} />;
  if (!agent) return null;

  return (
    <>
      <p className="small">
        <Link href="/agents/">← Agents</Link>
      </p>
      <PageHeader
        title={agent.name}
        description={
          <>
            {agent.status === 'archived' ? <span className="badge">Archived</span> : null}{' '}
            {agent.published_version ? `Current version ${agent.published_version.internal_version}` : 'Not published yet'}
            {agent.category ? ` · ${agent.category}` : ''}
          </>
        }
        actions={
          canManage ? (
            agent.status === 'active' ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setConfirmError(null);
                  setConfirm('archive');
                }}
              >
                Archive agent
              </Button>
            ) : (
              <Button
                variant="secondary"
                onClick={() => {
                  setConfirmError(null);
                  setConfirm('restore');
                }}
              >
                Restore agent
              </Button>
            )
          ) : undefined
        }
      />
      <FormSuccess message={notice} />
      {error ? <ErrorState error={error} onRetry={reload} /> : null}
      <Tabs label="Agent sections" tabs={tabs} selected={current} onSelect={selectTab}>
        {current === 'overview' && (
          <AgentOverview
            orgId={orgId}
            agent={agent}
            canManage={canManage}
            onSaved={(a) => setData((prev) => ({ ...(prev as AgentDetail), ...a }))}
          />
        )}
        {current === 'configuration' && <DraftEditor orgId={orgId} agent={agent} canManage={canManage} onChanged={changed} />}
        {current === 'training' && <AgentTraining orgId={orgId} agent={agent} canManage={canManage} onChanged={changed} />}
        {current === 'versions' && (
          <VersionHistory
            orgId={orgId}
            agent={agent}
            canManage={canManage}
            onDraftCreated={(message) => {
              changed(message);
              selectTab('configuration');
            }}
          />
        )}
        {current === 'scenarios' && <ScenarioPanel orgId={orgId} agent={agent} canManage={can('scenarios.manage')} onCountChanged={reload} />}
        {current === 'assignments' && (
          <section aria-labelledby="agent-assignments">
            <div className="section-head">
              <h2 id="agent-assignments">Assignments</h2>
              {agent.status === 'active' && (
                <Link href={`/assignments/new/?agent_id=${encodeURIComponent(agent.id)}`} className="btn btn-primary">
                  Assign this agent
                </Link>
              )}
            </div>
            <AssignmentList orgId={orgId} agentId={agent.id} />
          </section>
        )}
      </Tabs>
      <ConfirmDialog
        open={confirm !== null}
        title={confirm === 'archive' ? 'Archive agent?' : 'Restore agent?'}
        confirmLabel={confirm === 'archive' ? 'Archive' : 'Restore'}
        danger={confirm === 'archive'}
        busy={confirmBusy}
        error={confirmError}
        onConfirm={() => void onConfirm()}
        onCancel={() => setConfirm(null)}
      >
        {confirm === 'archive' ? (
          <p>
            <strong>{agent.name}</strong> will be hidden from trainees and cannot be assigned or edited until it is restored. Its versions,
            scenarios and assignment history are kept. Nothing changes at Sarvam.
          </p>
        ) : (
          <p>
            <strong>{agent.name}</strong> becomes active again. Assignments that are still within their dates give access again.
          </p>
        )}
      </ConfirmDialog>
    </>
  );
}

export default function AgentDetailPage() {
  return (
    <OrgGate permission="agents.view">
      {(m) => (
        <WithQuery>
          {(params) => {
            const id = params.get('id');
            return id ? (
              <AgentDetailView key={id} membership={m} agentId={id} tab={params.get('tab') ?? 'overview'} />
            ) : (
              <NotFoundState message="No agent was chosen." />
            );
          }}
        </WithQuery>
      )}
    </OrgGate>
  );
}

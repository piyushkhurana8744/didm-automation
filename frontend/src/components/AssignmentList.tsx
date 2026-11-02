'use client';

import Link from 'next/link';
import { useState } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { ASSIGNMENT_STATE_BADGE, orgPath, query, settingsSummary } from '@/lib/agents';
import { capitalize, formatDateTime } from '@/lib/format';
import type { AgentListItem, Assignment, Page } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from './Button';
import { ConfirmDialog } from './ConfirmDialog';
import { DataTable, type Column } from './DataTable';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { FormSuccess, SelectField } from './Field';
import { Pagination } from './Pagination';
import { SkeletonRows } from './Spinner';

const LIMIT = 25;

const STATE_FILTERS = [
  { value: 'open', label: 'Open (active or scheduled)' },
  { value: 'active', label: 'Active now' },
  { value: 'expired', label: 'Expired' },
  { value: 'revoked', label: 'Revoked or replaced' },
  { value: 'all', label: 'All' },
];

export function assigneeLabel(a: Pick<Assignment, 'user_id' | 'user_email' | 'team_id' | 'team_name'>) {
  if (a.team_id) {
    return (
      <>
        <span className="badge">Team</span> <span className="break">{a.team_name ?? a.team_id}</span>
      </>
    );
  }
  return <span className="break">{a.user_email ?? a.user_id ?? '—'}</span>;
}

/** Assignments with a state filter, paging and revoke. With `agentId` the list is limited to that agent. */
export function AssignmentList({ orgId, agentId, agents }: { orgId: string; agentId?: string; agents?: AgentListItem[] }) {
  const [state, setState] = useState('open');
  const [agentFilter, setAgentFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const agent = agentId ?? agentFilter;
  const key = `${orgId}|${agent}|${state}|${offset}`;
  const { data, error, loading, reload } = useLoad(
    () => api.get<Page<Assignment>>(orgPath(orgId, `/assignments${query({ agent_id: agent, state, limit: LIMIT, offset })}`)),
    key,
  );

  const [revoking, setRevoking] = useState<Assignment | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function confirmRevoke() {
    if (!revoking) return;
    setRevokeBusy(true);
    setRevokeError(null);
    try {
      await api.post(orgPath(orgId, `/assignments/${seg(revoking.id)}/revoke`));
      setNotice(`Access to ${revoking.agent_name ?? 'the agent'} was revoked.`);
      setRevoking(null);
      reload();
    } catch (e) {
      setRevokeError(errorMessage(e));
    } finally {
      setRevokeBusy(false);
    }
  }

  const columns: Column<Assignment>[] = [];
  if (!agentId) {
    columns.push({ key: 'agent', header: 'Agent', render: (a) => <span className="cell-strong">{a.agent_name ?? a.agent_id}</span> });
  }
  columns.push(
    { key: 'who', header: 'Assigned to', render: assigneeLabel },
    { key: 'state', header: 'State', render: (a) => <span className={ASSIGNMENT_STATE_BADGE[a.state] ?? 'badge'}>{capitalize(a.state)}</span> },
    { key: 'starts', header: 'Starts', render: (a) => formatDateTime(a.starts_at) },
    { key: 'expires', header: 'Ends', render: (a) => (a.expires_at ? formatDateTime(a.expires_at) : 'No end date') },
    { key: 'limits', header: 'Limits', render: (a) => <span className="small">{settingsSummary(a.settings)}</span> },
    {
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (a) => (
        <div className="row row-end">
          <Link href={`/assignments/detail/?id=${encodeURIComponent(a.id)}`} className="btn btn-secondary btn-sm">
            Details
          </Link>
          {(a.state === 'active' || a.state === 'scheduled') && (
            <Button
              size="sm"
              variant="danger"
              onClick={() => {
                setRevokeError(null);
                setNotice(null);
                setRevoking(a);
              }}
              aria-label={`Revoke ${a.agent_name ?? 'agent'} for ${a.team_name ?? a.user_email ?? 'assignee'}`}
            >
              Revoke
            </Button>
          )}
        </div>
      ),
    },
  );

  return (
    <>
      <div className="filters">
        <SelectField
          label="State"
          options={STATE_FILTERS}
          value={state}
          onChange={(e) => {
            setState(e.target.value);
            setOffset(0);
          }}
        />
        {!agentId && agents && (
          <SelectField
            label="Agent"
            options={[{ value: '', label: 'All agents' }, ...agents.map((a) => ({ value: a.id, label: a.status === 'archived' ? `${a.name} (archived)` : a.name }))]}
            value={agentFilter}
            onChange={(e) => {
              setAgentFilter(e.target.value);
              setOffset(0);
            }}
          />
        )}
      </div>
      <FormSuccess message={notice} />
      {loading && !data ? (
        <SkeletonRows label="Loading assignments" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <>
          <DataTable
            caption="Assignments"
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(a) => a.id}
            empty={
              <EmptyState title={state === 'open' ? 'No open assignments.' : 'No assignments match this filter.'}>
                <p>Assign an agent to people or teams so they can see it under My training.</p>
              </EmptyState>
            }
          />
          {data && <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} noun="assignments" />}
        </>
      )}
      <ConfirmDialog
        open={revoking !== null}
        title="Revoke access?"
        confirmLabel="Revoke"
        danger
        busy={revokeBusy}
        error={revokeError}
        onConfirm={() => void confirmRevoke()}
        onCancel={() => setRevoking(null)}
      >
        <p>
          {revoking ? (
            <>
              {revoking.team_id ? `Members of the team ${revoking.team_name ?? ''}` : revoking.user_email ?? 'This person'} will lose access to{' '}
              <strong>{revoking.agent_name ?? 'this agent'}</strong> through this assignment. Revoked assignments cannot be changed; assign again to give access back.
            </>
          ) : null}
        </p>
      </ConfirmDialog>
    </>
  );
}

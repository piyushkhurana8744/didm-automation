'use client';

import { useState } from 'react';
import { api, errorMessage, seg } from '@/lib/api';
import { orgPath } from '@/lib/agents';
import { formatDateTime } from '@/lib/format';
import type { AgentDetail, AgentVersion, VersionListItem } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { Button } from '../Button';
import { DataTable, type Column } from '../DataTable';
import { EmptyState } from '../EmptyState';
import { ErrorState } from '../ErrorState';
import { FormError } from '../Field';
import { SkeletonRows } from '../Spinner';
import { VersionView } from './VersionView';

export function VersionHistory({
  orgId,
  agent,
  canManage,
  onDraftCreated,
}: {
  orgId: string;
  agent: AgentDetail;
  canManage: boolean;
  onDraftCreated: (notice: string) => void;
}) {
  // Reloads whenever the agent's current or draft version changes
  const key = `${orgId}|${agent.id}|${agent.published_version_id ?? ''}|${agent.draft_version?.id ?? ''}`;
  const { data, error, loading, reload } = useLoad(() => api.get<VersionListItem[]>(orgPath(orgId, `/agents/${seg(agent.id)}/versions`)), key);
  const [viewing, setViewing] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const hasDraft = !!agent.draft_version;
  const canDraft = canManage && agent.status === 'active';

  async function draftFrom(v: VersionListItem) {
    setBusyId(v.id);
    setActionError(null);
    try {
      const d = await api.post<AgentVersion>(orgPath(orgId, `/agents/${seg(agent.id)}/versions`), { based_on_version_id: v.id });
      onDraftCreated(`Draft version ${d.internal_version} was started from version ${v.internal_version}.`);
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  }

  const versionNo = new Map((data ?? []).map((v) => [v.id, v.internal_version]));
  const selected = (data ?? []).find((v) => v.id === viewing) ?? null;

  const columns: Column<VersionListItem>[] = [
    {
      key: 'version',
      header: 'Version',
      render: (v) => (
        <>
          <span className="cell-strong">Version {v.internal_version}</span>
          {v.is_current && <span className="badge badge-ok">Current</span>}
          {v.status === 'draft' && <span className="badge badge-info">Draft</span>}
        </>
      ),
    },
    { key: 'app', header: 'Sarvam app version', render: (v) => v.provider_app_version ?? '—' },
    { key: 'published', header: 'Published', render: (v) => (v.published_at ? formatDateTime(v.published_at) : '—') },
    {
      key: 'based',
      header: 'Based on',
      render: (v) => (v.based_on_version_id ? `Version ${versionNo.get(v.based_on_version_id) ?? '?'}` : '—'),
    },
    { key: 'notes', header: 'Notes', render: (v) => <span className="small break">{v.notes ? (v.notes.length > 120 ? `${v.notes.slice(0, 120)}…` : v.notes) : '—'}</span> },
    {
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (v) => (
        <div className="row row-end">
          <Button size="sm" variant="secondary" aria-expanded={viewing === v.id} onClick={() => setViewing(viewing === v.id ? null : v.id)}>
            {viewing === v.id ? 'Hide' : 'View'}
          </Button>
          {canDraft && v.status === 'published' && (
            <Button
              size="sm"
              variant="secondary"
              busy={busyId === v.id}
              disabled={hasDraft}
              title={hasDraft ? 'Publish or discard the open draft first.' : undefined}
              onClick={() => void draftFrom(v)}
            >
              New draft from this
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <section aria-labelledby="versions-title">
      <div className="section-head">
        <h2 id="versions-title">Version history</h2>
      </div>
      {canDraft && hasDraft && <p className="field-hint">Version {agent.draft_version?.internal_version} is an open draft. Publish or discard it before starting another.</p>}
      <FormError message={actionError} />
      {selected && (
        <section className="panel panel-highlight" aria-labelledby="version-view-title">
          <div className="section-head">
            <h3 id="version-view-title">
              Version {selected.internal_version}
              {selected.is_current && <span className="title-badges"><span className="badge badge-ok">Current</span></span>}
            </h3>
            <Button size="sm" variant="ghost" onClick={() => setViewing(null)}>
              Close
            </Button>
          </div>
          <VersionView version={selected} />
        </section>
      )}
      {loading && !data ? (
        <SkeletonRows label="Loading versions" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <DataTable caption="Versions" columns={columns} rows={data ?? []} rowKey={(v) => v.id} empty={<EmptyState title="No versions yet." />} />
      )}
    </section>
  );
}

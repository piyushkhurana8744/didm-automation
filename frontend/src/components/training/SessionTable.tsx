'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { CHANNEL_LABELS } from '@/lib/agents';
import { formatDateTime } from '@/lib/format';
import { formatDuration } from '@/lib/training';
import type { TrainingSession } from '@/lib/types';
import { DataTable, type Column } from '../DataTable';
import { StatusBadge } from './SessionView';

/** A table of training sessions; each row links to `detailHref`. With `showTrainee` it adds the trainee's email. */
export function SessionTable({
  sessions,
  detailHref,
  showTrainee = false,
  empty,
}: {
  sessions: TrainingSession[];
  detailHref: (s: TrainingSession) => string;
  showTrainee?: boolean;
  empty: ReactNode;
}) {
  const columns: Column<TrainingSession>[] = [
    {
      key: 'when',
      header: 'Started',
      render: (s) => (
        <Link href={detailHref(s)} className="cell-strong">
          {formatDateTime(s.created_at)}
        </Link>
      ),
    },
  ];
  if (showTrainee) columns.push({ key: 'who', header: 'Trainee', render: (s) => <span className="break">{s.user_email ?? s.user_id}</span> });
  columns.push(
    { key: 'agent', header: 'Agent', render: (s) => s.agent_name ?? s.agent_id },
    { key: 'scenario', header: 'Scenario', render: (s) => s.scenario_name ?? '—' },
    { key: 'channel', header: 'Channel', render: (s) => CHANNEL_LABELS[s.channel] ?? s.channel },
    { key: 'status', header: 'Status', render: (s) => <StatusBadge status={s.status} /> },
    { key: 'duration', header: 'Duration', align: 'end', render: (s) => formatDuration(s.duration_seconds) },
    {
      key: 'actions',
      header: 'Actions',
      align: 'end',
      render: (s) => (
        <Link href={detailHref(s)} className="btn btn-secondary btn-sm" aria-label={`View session from ${formatDateTime(s.created_at)}`}>
          View
        </Link>
      ),
    },
  );
  return <DataTable caption="Training sessions" columns={columns} rows={sessions} rowKey={(s) => s.id} empty={empty} />;
}

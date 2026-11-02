'use client';

import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/lib/api';
import { orgPath, query } from '@/lib/agents';
import type { Membership, Page, TrainingSession } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { Pagination } from '@/components/Pagination';
import { SkeletonRows } from '@/components/Spinner';
import { SessionTable } from '@/components/training/SessionTable';

const LIMIT = 25;

function MySessions({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const [offset, setOffset] = useState(0);
  const { data, error, loading, reload } = useLoad(
    () => api.get<Page<TrainingSession>>(orgPath(orgId, `/my/training/sessions${query({ limit: LIMIT, offset })}`)),
    `${orgId}|${offset}`,
  );

  return (
    <>
      <PageHeader title="My sessions" description="Your practice sessions in this organization, newest first." />
      {loading && !data ? (
        <SkeletonRows label="Loading your sessions" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <>
          <SessionTable
            sessions={data?.items ?? []}
            detailHref={(s) => `/my-training/session/?id=${encodeURIComponent(s.id)}`}
            empty={
              <EmptyState title="You have not practised yet.">
                <p>
                  Open an agent under <Link href="/my-training/">My training</Link> to start a practice session.
                </p>
              </EmptyState>
            }
          />
          {data && <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} noun="sessions" />}
        </>
      )}
    </>
  );
}

export default function MySessionsPage() {
  return <OrgGate permission="training.self">{(m) => <MySessions membership={m} />}</OrgGate>;
}

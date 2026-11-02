'use client';

import Link from 'next/link';
import { intelligenceApi } from '@/lib/intelligence';
import type { Membership } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { ErrorState, NotFoundState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';
import { WithQuery } from '@/components/WithQuery';
import { ProgressView } from '@/components/training/ProgressView';

function TraineeProgressView({ membership, userId }: { membership: Membership; userId: string }) {
  const orgId = membership.organization.id;
  const { data, error, loading, reload } = useLoad(() => intelligenceApi.traineeProgress(orgId, userId), `${orgId}|${userId}`);
  return (
    <>
      <p className="small">
        <Link href="/training/?tab=analytics">← Analytics</Link>
      </p>
      {loading && !data ? (
        <SkeletonRows label="Loading progress" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data ? (
        <>
          <PageHeader
            title={data.user.name || data.user.email}
            description={
              <>
                <span className="break">{data.user.email}</span> · progress from all of their sessions.{' '}
                <Link href={`/training/?tab=sessions`}>See all sessions</Link>
              </>
            }
          />
          <ProgressView progress={data} self={false} sessionHref={(id) => `/training/session/?id=${encodeURIComponent(id)}`} />
        </>
      ) : null}
    </>
  );
}

export default function TraineePage() {
  return (
    <OrgGate permission="training.view">
      {(m) => (
        <WithQuery>
          {(params) => {
            const id = params.get('id');
            return id ? <TraineeProgressView key={id} membership={m} userId={id} /> : <NotFoundState message="No trainee was chosen." />;
          }}
        </WithQuery>
      )}
    </OrgGate>
  );
}

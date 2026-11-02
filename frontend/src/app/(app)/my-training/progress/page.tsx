'use client';

import Link from 'next/link';
import { intelligenceApi } from '@/lib/intelligence';
import type { Membership } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { ErrorState } from '@/components/ErrorState';
import { OrgGate } from '@/components/OrgGate';
import { PageHeader } from '@/components/PageHeader';
import { SkeletonRows } from '@/components/Spinner';
import { ProgressView } from '@/components/training/ProgressView';

function MyProgress({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id;
  const { data, error, loading, reload } = useLoad(() => intelligenceApi.myProgress(orgId), orgId);
  return (
    <>
      <p className="small">
        <Link href="/my-training/">← My training</Link>
      </p>
      <PageHeader title="My progress" description="How your practice is going, from your evaluated sessions." />
      {loading && !data ? (
        <SkeletonRows label="Loading your progress" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : data ? (
        <ProgressView progress={data} self sessionHref={(id) => `/my-training/session/?id=${encodeURIComponent(id)}`} />
      ) : null}
    </>
  );
}

export default function MyProgressPage() {
  return <OrgGate permission="training.self">{(m) => <MyProgress membership={m} />}</OrgGate>;
}

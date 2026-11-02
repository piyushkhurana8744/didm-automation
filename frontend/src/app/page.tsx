'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, isApiError } from '@/lib/api';
import type { Me } from '@/lib/types';
import { FullPageSpinner } from '@/components/Spinner';
import { ErrorState } from '@/components/ErrorState';

/** Sends people where they belong: login, the organization picker, or their dashboard. */
export default function StartPage() {
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setError(null);
    api.get<Me>('/auth/me', { redirectOn401: false }).then(
      (me) => {
        if (!live) return;
        router.replace(me.active_organization_id ? '/dashboard/' : '/organizations/');
      },
      (e: unknown) => {
        if (!live) return;
        if (isApiError(e) && e.status === 401) router.replace('/login/');
        else setError(e);
      },
    );
    return () => {
      live = false;
    };
  }, [router, attempt]);

  if (error) {
    return (
      <main id="main" className="center-page">
        <ErrorState error={error} onRetry={() => setAttempt((a) => a + 1)} />
      </main>
    );
  }
  return <FullPageSpinner label="Loading" />;
}

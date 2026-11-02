'use client';

import Link from 'next/link';
import { errorMessage, isApiError } from '@/lib/api';
import { Button } from './Button';

export function Forbidden({ message }: { message?: string }) {
  return (
    <div className="state state-error" role="alert">
      <h2 className="state-title">You don&apos;t have access</h2>
      <p className="state-body">{message ?? 'Your role in this organization does not include this page.'}</p>
      <p>
        <Link href="/dashboard/">Back to dashboard</Link>
      </p>
    </div>
  );
}

export function NotFoundState({ message }: { message?: string }) {
  return (
    <div className="state state-error" role="alert">
      <h2 className="state-title">Not found</h2>
      <p className="state-body">{message ?? 'This page or item does not exist, or it was removed.'}</p>
      <p>
        <Link href="/">Go to the start page</Link>
      </p>
    </div>
  );
}

/** Shows an error from the API: 403 and 404 get their own states, everything else a retry. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (isApiError(error) && error.status === 403) return <Forbidden message={error.detail} />;
  if (isApiError(error) && error.status === 404) return <NotFoundState message={error.detail} />;
  if (isApiError(error) && error.status === 401) {
    return (
      <div className="state" role="status">
        <p className="state-title">Your session has ended. Taking you to log in…</p>
      </div>
    );
  }
  return (
    <div className="state state-error" role="alert">
      <h2 className="state-title">Could not load this</h2>
      <p className="state-body">{errorMessage(error)}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

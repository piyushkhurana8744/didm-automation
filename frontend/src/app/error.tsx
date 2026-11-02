'use client';

import { useEffect } from 'react';
import { BASE_PATH } from '@/lib/api';

export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Only the error's name is logged: messages could echo user input.
    console.error('Page error:', error.name);
  }, [error]);

  return (
    <main id="main" className="center-page">
      <div className="state state-error" role="alert">
        <h1 className="state-title">Something went wrong</h1>
        <p className="state-body">This page hit an unexpected problem. You can try again, or go back to the start.</p>
        <div className="row">
          <button type="button" className="btn btn-primary" onClick={reset}>
            Try again
          </button>
          <a className="btn btn-secondary" href={`${BASE_PATH}/`}>
            Go to start
          </a>
        </div>
      </div>
    </main>
  );
}

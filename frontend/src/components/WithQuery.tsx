'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense, type ReactNode } from 'react';
import { Spinner } from './Spinner';

function Reader({ children }: { children: (params: URLSearchParams) => ReactNode }) {
  const params = useSearchParams();
  return <>{children(new URLSearchParams(params?.toString() ?? ''))}</>;
}

/**
 * Gives children the page's query string. The app is a static export, so pages that need an id take it
 * from `?id=` instead of a dynamic route segment; reading it needs a Suspense boundary at build time.
 */
export function WithQuery({ children }: { children: (params: URLSearchParams) => ReactNode }) {
  return (
    <Suspense fallback={<Spinner label="Loading" />}>
      <Reader>{children}</Reader>
    </Suspense>
  );
}

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export interface LoadState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (value: T | ((prev: T | undefined) => T)) => void;
}

/**
 * Runs `loader` on mount and whenever `key` changes (pass null to skip). Results of stale runs are dropped.
 */
export function useLoad<T>(loader: (() => Promise<T>) | null, key: string | null): LoadState<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(loader !== null && key !== null);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    const run = loaderRef.current;
    if (!run || key === null) {
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    setError(null);
    run().then(
      (value) => {
        if (!live) return;
        setDataState(value);
        setLoading(false);
      },
      (e: unknown) => {
        if (!live) return;
        setError(e);
        setLoading(false);
      },
    );
    return () => {
      live = false;
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((value: T | ((prev: T | undefined) => T)) => {
    setDataState((prev) => (typeof value === 'function' ? (value as (p: T | undefined) => T)(prev) : value));
  }, []);

  return { data, error, loading, reload, setData };
}

/** One read, its loading state, its error, and a way to ask again. */
import { useCallback, useEffect, useState } from 'react';

export interface Async<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((value) => value + 1), []);

  // The caller owns the dependency list, the way `useEffect` does; `load` is rebuilt from
  // it on every render, so listing it here would re-run the read forever.
  const run = useCallback(load, deps);

  useEffect(() => {
    let live = true;
    setLoading(true);
    run()
      .then((value) => {
        if (!live) return;
        setData(value);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setData(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [run, tick]);

  return { data, error, loading, reload };
}

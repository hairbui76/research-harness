/**
 * One read, its loading state, its error, and a way to ask again.
 *
 * A refusal and a silence are not the same failure. When the daemon answers with a fault
 * the page has been told something, and it says it. When nothing answered at all the page
 * has been told nothing — so a read that never reached the daemon keeps the answer the last
 * one returned, and raises no error of its own: the shell states the outage once, for the
 * whole window, and says how old what is on screen is. Without that rule every page put a
 * second retry notice under the first one, which is the stacked-notice pattern this cockpit
 * is trying to leave behind.
 *
 * Only *this* read's own last answer is kept. A read whose dependencies changed is a
 * different question — another candidate, another work — and answering it with the previous
 * one's data would be the cockpit inventing a result rather than keeping one.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { daemonReachability } from '../api/client';

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

  /** The last answer this exact read was given, kept for the silence case only. */
  const answered = useRef<{ run: () => Promise<T>; data: T } | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    run()
      .then((value) => {
        if (!live) return;
        answered.current = { run, data: value };
        setData(value);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        const kept = answered.current?.run === run ? (answered.current?.data ?? null) : null;
        if (daemonReachability.get() !== null && kept !== null) {
          setData(kept);
          setError(null);
          return;
        }
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

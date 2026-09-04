/**
 * Keeping the project rail's background-work indicator honest, and only then.
 *
 * Switching projects does not cancel what was running in the one you left (design §10), so
 * the rail has to say "2 active" about a project nobody is looking at. Nothing pushes that
 * number — the registry is read over HTTP — so the shell re-reads it on a timer.
 *
 * The timer exists only while there is something to watch. With no project reporting a run
 * the registry cannot change on its own: it changes when the researcher adds, renames,
 * locates or forgets a project, and every one of those refreshes the list itself
 * (`useProjectLifecycle`). Polling then would be a request every five seconds, forever, for
 * an answer that is already correct — so the effect starts when the first run appears and
 * stops when the last one ends, and on unmount.
 */
import { useEffect, useRef } from 'react';
import type { Host } from './host';

/** How often the registry is re-read while any project reports a running workflow. */
export const PROJECT_POLL_INTERVAL_MS = 5000;

/**
 * Refresh `host.projects` every five seconds while any project has active runs.
 *
 * Takes a nullable host so the shell can call it unconditionally: `null` — a legacy window,
 * or one still detecting its host — polls nothing.
 */
export function useProjectPolling(
  host: Host | null,
  intervalMs: number = PROJECT_POLL_INTERVAL_MS,
): void {
  const running =
    host?.mode === 'multi' && host.projects.some((project) => project.active_runs > 0);
  const refresh = host?.refreshProjects;

  // The refresher is read through a ref so that a host object rebuilt on every render — a
  // new `refreshProjects` identity each time — does not restart the interval and postpone
  // the tick indefinitely. Only `running` may start or stop it.
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      // A poll that fails changes nothing and interrupts nobody: the rail keeps showing the
      // last answer the host gave, and the next tick asks again.
      void latest.current?.().catch(() => undefined);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [running, intervalMs]);
}

/**
 * Whether the local daemon is answering this window, as a value a component can render.
 *
 * The fact itself is recorded by the transport (`api/client.ts`), because every read and
 * every write goes through the transport and nothing else sees all of them. This is the
 * one line of React over it, kept out of both the shell and the views so that a page can
 * ask without importing the shell that renders the notice.
 */
import { useSyncExternalStore } from 'react';
import { daemonReachability } from '../api/client';
import type { DaemonOutage } from '../api/client';

/** The current outage, or null while the daemon is answering. */
export function useDaemonOutage(): DaemonOutage | null {
  return useSyncExternalStore(
    daemonReachability.subscribe,
    daemonReachability.get,
    daemonReachability.get,
  );
}

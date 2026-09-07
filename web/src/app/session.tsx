/**
 * The one client every view shares, and who the daemon says we are.
 *
 * `principal` comes from `GET /overview`: the daemon decides it from the token, and the
 * cockpit renders that decision. A view never guesses whether a mutation is allowed — it
 * asks `canMutate` and, when the answer is no, says why (Product 29, ADR-007).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { HarnessClient, daemonReachability } from '../api/client';
import type { OverviewReport } from '../api/dto';
import { readToken, storeToken } from '../api/session';

export interface Session {
  client: HarnessClient;
  token: string | null;
  setToken: (token: string | null) => void;
  overview: OverviewReport | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
  /**
   * When the report on screen was read, ISO-8601, or null before the first answer.
   *
   * It is the transport's own stamp for the round trip that answered — the one the outage
   * notice reports as "last read at" — so the cockpit keeps one clock and a page saying how
   * old its content is cannot drift from the shell saying the same thing.
   */
  readAt: string | null;
  /** True when the daemon accepted our token; an agent host may read and stage only. */
  canMutate: boolean;
  /** Why the mutation controls are disabled, in one sentence a researcher can act on. */
  mutationBlockedReason: string | null;
}

const SessionContext = createContext<Session | null>(null);

export const AGENT_HOST_EXPLANATION =
  'This cockpit is connected without the local token, so the daemon treats it as an agent ' +
  'host: it may read and propose, and only the researcher accepts. Paste the token from ' +
  '.research/daemon-token to review.';

export function SessionProvider({
  children,
  client: injected,
}: {
  children: ReactNode;
  client?: HarnessClient;
}) {
  const [token, setTokenState] = useState<string | null>(() => (injected ? null : readToken()));
  const [overview, setOverview] = useState<OverviewReport | null>(null);
  const [readAt, setReadAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const client = useMemo(
    () => injected ?? new HarnessClient({ token }),
    [injected, token],
  );

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  const setToken = useCallback((next: string | null) => {
    storeToken(next);
    setTokenState(next);
  }, []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    client
      .overview()
      .then((report) => {
        if (!live) return;
        setOverview(report);
        setError(null);
        setReadAt(daemonReachability.lastAnsweredAt());
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setOverview(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [client, tick]);

  const canMutate = overview?.principal === 'human';
  const value: Session = {
    client,
    token,
    setToken,
    overview,
    error,
    loading,
    refresh,
    readAt,
    canMutate,
    mutationBlockedReason: canMutate ? null : AGENT_HOST_EXPLANATION,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error('useSession must be used inside a SessionProvider');
  return session;
}

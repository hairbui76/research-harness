/**
 * Which host is on the other end of this bundle, and what it lets us see.
 *
 * The same built bundle is served by two different servers (design §11): `research serve`,
 * which owns exactly one workspace and has no idea what a project is, and `research app`,
 * which owns a registry of them. The bundle cannot be told at build time which one it is
 * inside, so it asks: one `GET /api/app/health` at mount, whose answer selects the whole
 * route tree.
 *
 * The classification is deliberately conservative. Only a well-formed
 * `{ok: true, kind: "multi_project"}` selects `multi`. A 404 — or a 200 that is really the
 * SPA's own `index.html`, which is what the legacy daemon serves for a route it does not
 * know — selects `legacy`. A network failure selects `error` and never `legacy`, because
 * silently degrading a multi-project app to a single-workspace one would point every
 * subsequent request at a workspace nobody chose.
 *
 * Authentication happens here too, and once. The launch URL carries a single-use bootstrap
 * nonce; it is exchanged for the app token, the token goes into `sessionStorage`, and the
 * nonce is dropped from the address bar and never written down (design §8.1). A tab opened
 * without a nonce and without a stored token is still a multi-project host — it just has no
 * authority, so `authRequired` is set and Project Home says how to get one.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AppClient, ControlError } from '../api/projects';
import type { ProjectView } from '../api/projects';
import { readBootstrap, storeAppToken, storedAppToken } from '../api/session';

export type HostMode = 'loading' | 'legacy' | 'multi' | 'error';

export interface Host {
  mode: HostMode;
  /** Why we cannot proceed, in one sentence; null unless `mode` is `error`. */
  error: string | null;
  /** The control-plane client, carrying the app token once there is one. */
  appClient: AppClient | null;
  projects: ProjectView[];
  /** A multi-project host we hold no token for: the researcher must relaunch the app. */
  authRequired: boolean;
  refreshProjects: () => Promise<void>;
  setProjects: (projects: ProjectView[]) => void;
}

/** What the researcher is told when a launch link has already been used, or has expired. */
export const BOOTSTRAP_EXPIRED_EXPLANATION =
  'This launch link has already been used or has expired. Start Research Harness again ' +
  'with `research app` to open a fresh window.';

/** What Project Home explains when the tab holds no application token at all. */
export const APP_TOKEN_MISSING_EXPLANATION =
  'This tab is not signed in to the local application. Start Research Harness with ' +
  '`research app`, which opens an authenticated window.';

const HostContext = createContext<Host | null>(null);

/** The part of the host state one detection run decides. */
interface Detection {
  mode: HostMode;
  error: string | null;
  projects: ProjectView[];
  authRequired: boolean;
  token: string | null;
}

const LOADING: Detection = {
  mode: 'loading',
  error: null,
  projects: [],
  authRequired: false,
  token: null,
};

export interface HostProviderProps {
  children: ReactNode;
  /** The control-plane client to probe with; tests inject one over a fake transport. */
  appClient?: AppClient;
  fetchImpl?: typeof fetch;
  /** Where the bootstrap nonce is read from; defaults to the real address bar. */
  location?: Location;
  /** A ready-made host state. Tests that are not testing detection mount this directly. */
  value?: Host;
}

export function HostProvider({
  children,
  appClient: injected,
  fetchImpl,
  location,
  value,
}: HostProviderProps) {
  const probe = useMemo(
    () => injected ?? new AppClient({ token: null, fetchImpl }),
    [injected, fetchImpl],
  );
  const [detection, setDetection] = useState<Detection>(LOADING);
  // One detection per provider, memoised in a ref rather than in the effect, so that
  // StrictMode's deliberate double-mount does not exchange the single-use nonce twice.
  const run = useRef<Promise<Detection> | null>(null);
  const skip = Boolean(value);

  useEffect(() => {
    if (skip) return;
    let live = true;
    run.current ??= detectHost(probe, location ?? window.location);
    void run.current.then((next) => {
      if (live) setDetection(next);
    });
    return () => {
      live = false;
    };
  }, [probe, location, skip]);

  const client = useMemo(
    () => (detection.token ? probe.withToken(detection.token) : probe),
    [probe, detection.token],
  );

  const setProjects = useCallback((projects: ProjectView[]) => {
    setDetection((current) => ({ ...current, projects }));
  }, []);

  const refreshProjects = useCallback(async () => {
    if (!client.authenticated) return;
    const projects = await client.projects();
    setProjects(projects);
  }, [client, setProjects]);

  const host = useMemo<Host>(
    () => ({
      mode: detection.mode,
      error: detection.error,
      appClient: detection.mode === 'multi' ? client : null,
      projects: detection.projects,
      authRequired: detection.authRequired,
      refreshProjects,
      setProjects,
    }),
    [detection, client, refreshProjects, setProjects],
  );

  return <HostContext.Provider value={value ?? host}>{children}</HostContext.Provider>;
}

export function useHost(): Host {
  const host = useContext(HostContext);
  if (!host) throw new Error('useHost must be used inside a HostProvider');
  return host;
}

/**
 * Ask the host what it is, and — if it is the multi-project one — sign in and list.
 *
 * Runs exactly once per provider. Every failure it can name becomes a state rather than a
 * rejection, because the caller is a React effect and there is nothing above it to catch.
 */
async function detectHost(client: AppClient, location: Location): Promise<Detection> {
  try {
    await client.health();
  } catch (cause) {
    if (cause instanceof ControlError) {
      if (cause.status === 404 || cause.code === 'not_multi_project') return legacy();
      return failure(cause.message);
    }
    return failure(
      `Research Harness is not answering on this address. ${describe(cause)}`.trim(),
    );
  }

  const bootstrap = readBootstrap(location);
  let token = storedAppToken();
  if (bootstrap) {
    try {
      token = await client.session(bootstrap);
      storeAppToken(token);
    } catch (cause) {
      const expired = cause instanceof ControlError && cause.status === 401;
      return failure(expired ? BOOTSTRAP_EXPIRED_EXPLANATION : describe(cause));
    }
  }
  if (!token) {
    return { mode: 'multi', error: null, projects: [], authRequired: true, token: null };
  }

  try {
    const projects = await client.withToken(token).projects();
    return { mode: 'multi', error: null, projects, authRequired: false, token };
  } catch (cause) {
    return failure(describe(cause));
  }
}

function legacy(): Detection {
  return { mode: 'legacy', error: null, projects: [], authRequired: false, token: null };
}

function failure(error: string): Detection {
  return { mode: 'error', error, projects: [], authRequired: false, token: null };
}

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

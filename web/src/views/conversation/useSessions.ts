/**
 * The session history: list, search, create, rename, and which one is open.
 *
 * The open session travels in the URL — `/?session=CS0001` — so a session is linkable,
 * bookmarkable and survives a reload, and `rh://session/CS0001?message=M0042` has somewhere
 * to land. The *last* session is remembered in `localStorage` per project, which is what
 * makes conversation spec §10.1 true: reopening a project restores the session you were in,
 * with its transcript intact (the transcript itself is `session.get`; nothing about it is
 * cached here).
 *
 * Search is `session.search`, a direct transcript read, so it keeps working when the graph
 * projection has been deleted (spec §8). An empty query lists everything.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type {
  ConfigureSessionRequest,
  ConversationSession,
  SessionMatch,
  SessionVisibility,
} from '../../api/dto';
import type { HarnessClient } from '../../api/client';
import { CapabilityError } from '../../api/client';

const LAST_SESSION = 'research-harness.conversation.last-session';

function lastSessionKey(project: string | null): string {
  return project ? `${LAST_SESSION}.${project}` : LAST_SESSION;
}

function readLastSession(project: string | null): string | null {
  try {
    return window.localStorage.getItem(lastSessionKey(project));
  } catch {
    return null;
  }
}

function writeLastSession(project: string | null, sessionId: string | null): void {
  try {
    if (sessionId) window.localStorage.setItem(lastSessionKey(project), sessionId);
    else window.localStorage.removeItem(lastSessionKey(project));
  } catch {
    /* a browser with storage disabled simply starts at the newest session */
  }
}

export interface SessionsApi {
  sessions: ConversationSession[];
  /** Search hits for the current query, or null when nothing is being searched. */
  matches: SessionMatch[] | null;
  query: string;
  setQuery: (query: string) => void;
  activeId: string | null;
  active: ConversationSession | null;
  open: (sessionId: string) => void;
  /**
   * Open a session. `visibility` is the daemon's own vocabulary and is sent only when the
   * researcher chose one — omitting it leaves the default where it belongs, on the daemon.
   */
  create: (title?: string, visibility?: SessionVisibility) => Promise<ConversationSession | null>;
  rename: (sessionId: string, title: string) => Promise<void>;
  /**
   * Bind this session to a runtime and model, to an entry, or clear it.
   *
   * The record the daemon answers with replaces the one in `sessions`, so every surface
   * reads the binding back from the daemon rather than from a local guess (binding spec
   * §10). A refusal is *returned* rather than put in `refusal`: the pick was made in the
   * composer, so the daemon's sentence belongs beside the selector and not in the rail's
   * notice about the session history. `null` means it was stored.
   */
  configure: (
    sessionId: string,
    input: Omit<ConfigureSessionRequest, 'session'>,
  ) => Promise<string | null>;
  loading: boolean;
  error: string | null;
  reload: () => void;
  /** Set by a failed create or rename; rendered by the rail, never inferred. */
  refusal: string | null;
}

export interface SessionsOptions {
  /** The workspace the last-session memory is keyed by. */
  project?: string | null;
  /** False for a window the daemon will not let write (an agent host). */
  canMutate?: boolean;
}

export function useSessions(client: HarnessClient, options: SessionsOptions = {}): SessionsApi {
  const { project = null, canMutate = true } = options;
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<ConversationSession[]>([]);
  const [matches, setMatches] = useState<SessionMatch[] | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const restored = useRef(false);

  const urlSession = params.get('session');

  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    client
      .sessions()
      .then((list) => {
        if (!live) return;
        setSessions(list);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setSessions([]);
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [client, tick]);

  // Searching is the daemon's; this only reports the typing and holds the answer.
  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length === 0) {
      setMatches(null);
      return;
    }
    let live = true;
    client
      .searchSessions(trimmed)
      .then((results) => live && setMatches(results.matches))
      .catch(() => live && setMatches([]));
    return () => {
      live = false;
    };
  }, [client, query]);

  /**
   * Choosing a session in the rail is choosing a conversation, so it goes to `/`.
   *
   * The rail is on every screen; clicking a session from the Claims page and staying on
   * the Claims page would be the wrong reading of the click by some distance. The message
   * anchor is dropped on the way: a different session is a different transcript, and
   * `?message=` from the old one would name nothing.
   */
  const open = useCallback(
    (sessionId: string) => {
      writeLastSession(project, sessionId);
      navigate(`/?session=${encodeURIComponent(sessionId)}`);
    },
    [navigate, project],
  );

  /**
   * Reopening the project: the URL wins, then the session this project was last in, then
   * the most recently updated one.
   *
   * Done once, so it never fights a deliberate navigation, and written with `replace` on
   * whatever route is open — restoring is not a place a researcher navigated to, and on a
   * research page it only tells the rail which session is current.
   */
  useEffect(() => {
    if (restored.current || loading || urlSession) return;
    restored.current = true;
    const remembered = readLastSession(project);
    const known = new Set(sessions.map((session) => session.id));
    const fallback = [...sessions].sort((a, b) =>
      (b.last_message_at ?? b.updated_at).localeCompare(a.last_message_at ?? a.updated_at),
    )[0];
    const chosen = remembered && known.has(remembered) ? remembered : (fallback?.id ?? null);
    if (!chosen) return;
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set('session', chosen);
        return next;
      },
      { replace: true },
    );
  }, [loading, project, sessions, setParams, urlSession]);

  useEffect(() => {
    if (urlSession) writeLastSession(project, urlSession);
  }, [project, urlSession]);

  const create = useCallback(
    async (
      title = 'New session',
      visibility?: SessionVisibility,
    ): Promise<ConversationSession | null> => {
      if (!canMutate) return null;
      setRefusal(null);
      try {
        const session = await client.createSession({
          title,
          ...(visibility ? { visibility } : {}),
        });
        setSessions((previous) => [...previous, session]);
        open(session.id);
        return session;
      } catch (cause) {
        setRefusal(cause instanceof CapabilityError ? cause.message : String(cause));
        return null;
      }
    },
    [canMutate, client, open],
  );

  const rename = useCallback(
    async (sessionId: string, title: string): Promise<void> => {
      if (!canMutate) return;
      setRefusal(null);
      try {
        const session = await client.renameSession(sessionId, title);
        setSessions((previous) =>
          previous.map((entry) => (entry.id === session.id ? session : entry)),
        );
      } catch (cause) {
        setRefusal(cause instanceof CapabilityError ? cause.message : String(cause));
      }
    },
    [canMutate, client],
  );

  const configure = useCallback(
    async (
      sessionId: string,
      input: Omit<ConfigureSessionRequest, 'session'>,
    ): Promise<string | null> => {
      if (!canMutate) return null;
      try {
        const session = await client.configureSession({ session: sessionId, ...input });
        setSessions((previous) =>
          previous.map((entry) => (entry.id === session.id ? session : entry)),
        );
        return null;
      } catch (cause) {
        return cause instanceof CapabilityError ? cause.message : String(cause);
      }
    },
    [canMutate, client],
  );

  const active = useMemo(
    () => sessions.find((session) => session.id === urlSession) ?? null,
    [sessions, urlSession],
  );

  return {
    sessions,
    matches,
    query,
    setQuery,
    activeId: urlSession,
    active,
    open,
    create,
    rename,
    configure,
    loading,
    error,
    reload,
    refusal,
  };
}

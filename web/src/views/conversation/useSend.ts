/**
 * Send, stream, stop, retry — and reconcile.
 *
 * The shape of this hook is the answer to plan §3's "streaming through a capability-only
 * write surface": `session.send` is the mutation and it returns as soon as the user
 * message, the `ContextPack` and the run are durable; `GET /runs/{id}/events` is a *read*
 * of what the run has already persisted. So the client never owns the answer. It shows the
 * deltas as they arrive for immediacy, and the moment the run reaches a terminal state —
 * or the stream simply breaks — it throws its buffer away and re-reads `session.get`.
 *
 * Three consequences, each of them a spec requirement rather than an optimisation:
 *
 * - **A reload mid-stream recovers.** The run id is stored beside the draft, so a remount
 *   resubscribes; the daemon replays from delta zero, and the buffer is rebuilt rather
 *   than appended to, so nothing is doubled.
 * - **An interruption keeps what arrived** (spec §8). We do not synthesise a status: the
 *   `incomplete` marker on the message comes from the attempt the daemon wrote.
 * - **A refusal leaves the draft alone** (spec §8). `send` reports the daemon's own
 *   message and returns false; clearing the composer is the caller's, and only on success.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { CapabilityError } from '../../api/client';
import type { HarnessClient } from '../../api/client';
import type { SendStarted, SessionTranscript } from '../../api/dto';
import { useProjectPaths } from '../../app/projectPaths';
import { subscribeRunEvents } from '../../api/sse';
import type { RunState } from '../../api/sse';

const RUN_PREFIX = 'research-harness.conversation.run';

/**
 * Where the open run of one session is remembered, so a reload resubscribes to it.
 *
 * Keyed by project as well as session for the same reason the draft is: one browser origin
 * now holds every project, and `CS0001` names a different conversation in each. A null
 * project is the legacy host and keeps the key it has always used, so a `research serve`
 * window mid-stream still finds its run after a reload.
 */
export function runKey(sessionId: string, projectId: string | null = null): string {
  return projectId ? `${RUN_PREFIX}.${projectId}.${sessionId}` : `${RUN_PREFIX}.${sessionId}`;
}

interface StoredRun {
  runId: string;
  messageId: string;
  attempt: number;
}

function readRun(sessionId: string | null, projectId: string | null): StoredRun | null {
  if (!sessionId) return null;
  try {
    const raw = window.localStorage.getItem(runKey(sessionId, projectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredRun>;
    return typeof parsed.runId === 'string' && typeof parsed.messageId === 'string'
      ? { runId: parsed.runId, messageId: parsed.messageId, attempt: parsed.attempt ?? 1 }
      : null;
  } catch {
    return null;
  }
}

function writeRun(sessionId: string, projectId: string | null, run: StoredRun | null): void {
  try {
    if (run) window.localStorage.setItem(runKey(sessionId, projectId), JSON.stringify(run));
    else window.localStorage.removeItem(runKey(sessionId, projectId));
  } catch {
    /* without storage a reload simply falls back to `session.get`, which already has it */
  }
}

/** What the transcript needs to draw the answer that is still arriving. */
export interface Streaming {
  messageId: string;
  runId: string;
  attempt: number;
  /** Everything the stream has delivered for this message so far. */
  text: string;
  state: RunState;
}

export interface SendInput {
  text: string;
  references?: string[];
  attachments?: string[];
  model?: string | null;
}

export interface SendApi {
  /** Non-null while a run is open or being replayed. */
  streaming: Streaming | null;
  /** True between the click and `session.send` answering. */
  sending: boolean;
  /** The daemon's own refusal or transport failure, rendered verbatim. */
  error: string | null;
  /** Whether the failure can be tried again, as the daemon reported it. */
  retryable: boolean;
  dismissError: () => void;
  /** `@` tokens the assembler could not resolve on the last send. */
  unresolved: string[];
  /** The receipt id the last send recorded, so the composer can show it immediately. */
  contextPackId: string | null;
  send: (input: SendInput) => Promise<boolean>;
  stop: () => Promise<void>;
  retry: (messageId: string, model?: string | null) => Promise<boolean>;
}

export interface SendOptions {
  /** Re-read the transcript. Called on every terminal state and every dropped stream. */
  reconcile: () => Promise<SessionTranscript | null>;
  /** False for a window the daemon will not let write. */
  canMutate?: boolean;
  /** False while the conversation is not the screen: no stream is picked back up. */
  enabled?: boolean;
}

export function useSend(
  client: HarnessClient,
  sessionId: string | null,
  options: SendOptions,
): SendApi {
  const { reconcile, canMutate = true, enabled = true } = options;
  const { projectId } = useProjectPaths();
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [unresolved, setUnresolved] = useState<string[]>([]);
  const [contextPackId, setContextPackId] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const live = useRef(true);
  const reconcileRef = useRef(reconcile);
  reconcileRef.current = reconcile;

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      abort.current?.abort();
    };
  }, []);

  /**
   * Follow one run to its end.
   *
   * Deltas *replace* the buffer's tail rather than extending an existing one, because a
   * resubscription replays from index zero: appending would show the answer twice.
   */
  const follow = useCallback(
    async (session: string, started: { runId: string; messageId: string; attempt: number }) => {
      const controller = new AbortController();
      abort.current?.abort();
      abort.current = controller;
      writeRun(session, projectId, {
        runId: started.runId,
        messageId: started.messageId,
        attempt: started.attempt,
      });
      let text = '';
      setStreaming({ ...started, text: '', state: 'running' });

      await subscribeRunEvents(
        client.stream.baseUrl,
        client.stream.token,
        started.runId,
        {
          onDelta: (event) => {
            if (event.messageId && event.messageId !== started.messageId) return;
            text += event.text;
            if (live.current) setStreaming((previous) => (previous ? { ...previous, text } : previous));
          },
          onStatus: (event) => {
            if (live.current) {
              setStreaming((previous) => (previous ? { ...previous, state: event.state } : previous));
            }
          },
          onError: (event) => {
            if (!live.current) return;
            setError(event.message);
            setRetryable(event.retryable);
          },
        },
        { signal: controller.signal, fetchImpl: client.stream.fetchImpl },
      );

      // Terminal, dropped or aborted — all three end the same way: the transcript on disk
      // is the answer, so read it and stop pretending to hold one.
      writeRun(session, projectId, null);
      if (!live.current) return;
      setStreaming(null);
      await reconcileRef.current();
    },
    [client, projectId],
  );

  // A reload mid-stream: resubscribe to the run this session was following. A run that has
  // since finished replays its whole answer and then its terminal status, which reconciles.
  useEffect(() => {
    if (!sessionId || !enabled) return;
    const stored = readRun(sessionId, projectId);
    if (!stored) return;
    void follow(sessionId, stored);
  }, [enabled, follow, projectId, sessionId]);

  const begin = useCallback(
    async (session: string, call: () => Promise<SendStarted>): Promise<boolean> => {
      setSending(true);
      setError(null);
      setRetryable(false);
      try {
        const started = await call();
        setUnresolved(started.unresolved ?? []);
        setContextPackId(started.context_pack);
        // The user's message is already durable; showing it before the answer arrives is
        // a read of the transcript, not an optimistic guess.
        await reconcileRef.current();
        void follow(session, {
          runId: started.run_id,
          messageId: started.assistant_message,
          attempt: started.attempt,
        });
        return true;
      } catch (cause) {
        if (!live.current) return false;
        setError(cause instanceof Error ? cause.message : String(cause));
        // A capability refusal is a decision, not a hiccup: the same request would be
        // refused the same way, so nothing here offers to repeat it. A transport failure
        // is the other case, and that one is worth trying again.
        setRetryable(!(cause instanceof CapabilityError));
        return false;
      } finally {
        if (live.current) setSending(false);
      }
    },
    [follow],
  );

  const send = useCallback(
    async (input: SendInput): Promise<boolean> => {
      if (!sessionId) return false;
      if (!canMutate) {
        setError('This window may only read and propose, so it cannot send a message.');
        setRetryable(false);
        return false;
      }
      return begin(sessionId, () =>
        client.sendMessage({
          session: sessionId,
          text: input.text,
          ...(input.references?.length ? { references: input.references } : {}),
          ...(input.attachments?.length ? { attachments: input.attachments } : {}),
          ...(input.model ? { model: input.model } : {}),
        }),
      );
    },
    [begin, canMutate, client, sessionId],
  );

  const retry = useCallback(
    async (messageId: string, model?: string | null): Promise<boolean> => {
      if (!sessionId || !canMutate) return false;
      return begin(sessionId, () =>
        client.retryMessage(messageId, {
          session: sessionId,
          ...(model ? { model } : {}),
        }),
      );
    },
    [begin, canMutate, client, sessionId],
  );

  const stop = useCallback(async (): Promise<void> => {
    const open = streaming;
    if (!open) return;
    try {
      // The capability is the stop; aborting the read alone would leave the run running.
      await client.stopSend(open.runId);
    } catch (cause) {
      if (live.current) setError(cause instanceof Error ? cause.message : String(cause));
    }
    abort.current?.abort();
  }, [client, streaming]);

  const dismissError = useCallback(() => {
    setError(null);
    setRetryable(false);
  }, []);

  return {
    streaming,
    sending,
    error,
    retryable,
    dismissError,
    unresolved,
    contextPackId,
    send,
    stop,
    retry,
  };
}

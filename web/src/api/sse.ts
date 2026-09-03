/**
 * The run event stream: `GET /runs/{run_id}/events`.
 *
 * Not `EventSource`, and the reason is the token. The daemon's authority travels in an
 * `Authorization` header (see `client.ts`), and `EventSource` cannot send one — putting the
 * token in the query string instead would write it into every log and history entry that
 * sees the URL. So the stream is read with `fetch` and a `ReadableStream`, which also gives
 * the caller an `AbortSignal` for `session.stop`.
 *
 * The frame contract is plan §0.4, exactly:
 *
 *   event: delta   {"message_id": "M0042", "attempt": 1, "text": "…"}
 *   event: status  {"run_id": "…", "state": "queued|running|succeeded|failed|cancelled|incomplete",
 *                   "message_id": "M0042", "attempt": 1, "context_pack_id": "CP0007", "detail": "…"}
 *   event: error   {"code": "…", "message": "…", "retryable": true}
 *
 * Two things this client does not do, on purpose. It does not reconnect: the daemon
 * persists every delta into the message *before* emitting it, so the honest recovery from
 * a dropped stream is to read `session.get` and reconcile, and that decision belongs to the
 * caller. And it does not synthesise a terminal state — a stream that ends without one is
 * reported as `{kind: 'disconnected'}`, because "the connection dropped" and "the run
 * finished" are different facts about the world (conversation spec §8).
 */

/** The run states of plan §0.4. The last four end the stream. */
export type RunState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'incomplete';

const TERMINAL: ReadonlySet<string> = new Set(['succeeded', 'failed', 'cancelled', 'incomplete']);

/** Text appended to a message that the daemon has already persisted. */
export interface DeltaEvent {
  kind: 'delta';
  messageId: string;
  attempt: number;
  text: string;
}

export interface StatusEvent {
  kind: 'status';
  runId: string;
  state: RunState;
  messageId: string | null;
  attempt: number | null;
  contextPackId: string | null;
  detail: string | null;
  /** True for the state that ends the stream. */
  terminal: boolean;
}

/** A failure the daemon reported *inside* the stream, with its stable code. */
export interface RunErrorEvent {
  kind: 'error';
  code: string;
  message: string;
  retryable: boolean;
}

/**
 * The stream ended without a terminal status.
 *
 * The caller reconciles through `session.get`: the transcript on disk is authoritative and
 * already holds every delta that was emitted.
 */
export interface DisconnectedEvent {
  kind: 'disconnected';
  reason: string;
  lastState: RunState | null;
}

export type RunEvent = DeltaEvent | StatusEvent | RunErrorEvent | DisconnectedEvent;

export interface RunEventHandlers {
  onDelta?: (event: DeltaEvent) => void;
  onStatus?: (event: StatusEvent) => void;
  onError?: (event: RunErrorEvent) => void;
  onDisconnected?: (event: DisconnectedEvent) => void;
  /** Every event, after the specific handler above, for a caller with one reducer. */
  onEvent?: (event: RunEvent) => void;
}

export interface SubscribeOptions {
  /** Aborts the request; `session.stop` is the mutation, this is the read stopping. */
  signal?: AbortSignal;
  /** For tests and for a caller that already wraps `fetch`. */
  fetchImpl?: typeof fetch;
}

export interface RunSubscription {
  /** `terminal` the run finished, `disconnected` the stream broke, `aborted` we stopped. */
  ended: 'terminal' | 'disconnected' | 'aborted';
  /** The last status seen, whatever the ending was. */
  lastStatus: StatusEvent | null;
}

/** Where the events for one run are read from. */
export function runEventsUrl(baseUrl: string, runId: string): string {
  return `${baseUrl.replace(/\/$/, '')}/runs/${encodeURIComponent(runId)}/events`;
}

/**
 * Read one run's events until it finishes, the stream breaks, or the caller aborts.
 *
 * Resolves rather than rejects: a transport failure is an event the conversation has to
 * render, not an exception a React effect has to catch.
 */
export async function subscribeRunEvents(
  baseUrl: string,
  token: string | null,
  runId: string,
  handlers: RunEventHandlers,
  options: SubscribeOptions = {},
): Promise<RunSubscription> {
  const http = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const signal = options.signal;
  let lastStatus: StatusEvent | null = null;

  const dispatch = (event: RunEvent): void => {
    switch (event.kind) {
      case 'delta':
        handlers.onDelta?.(event);
        break;
      case 'status':
        lastStatus = event;
        handlers.onStatus?.(event);
        break;
      case 'error':
        handlers.onError?.(event);
        break;
      case 'disconnected':
        handlers.onDisconnected?.(event);
        break;
    }
    handlers.onEvent?.(event);
  };

  const drop = (reason: string): RunSubscription => {
    dispatch({ kind: 'disconnected', reason, lastState: lastStatus?.state ?? null });
    return { ended: 'disconnected', lastStatus };
  };

  let response: Response;
  try {
    response = await http(runEventsUrl(baseUrl, runId), {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      cache: 'no-store',
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    if (signal?.aborted) return { ended: 'aborted', lastStatus };
    return drop(messageOf(cause));
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    dispatch({
      kind: 'error',
      code: `http_${response.status}`,
      message: detail || `the daemon answered ${response.status} for run ${runId}`,
      // A 5xx or a 429 is worth trying again; a 401 or a 404 is not.
      retryable: response.status >= 500 || response.status === 429,
    });
    return drop(`the daemon answered ${response.status}`);
  }

  if (!response.body) return drop('the daemon sent no stream body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const consume = (chunk: string): boolean => {
    buffer += chunk;
    const { frames, rest } = splitFrames(buffer);
    buffer = rest;
    for (const frame of frames) {
      const event = readFrame(frame, dispatch);
      if (event) dispatch(event);
      if (event?.kind === 'status' && event.terminal) return true;
    }
    return false;
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      if (consume(decoder.decode(value, { stream: true }))) {
        await reader.cancel().catch(() => undefined);
        return { ended: 'terminal', lastStatus };
      }
    }
    // A last frame the server did not close with a blank line is still a frame it sent;
    // dropping a terminal status over a missing newline would strand the caller.
    if (consume(decoder.decode())) return { ended: 'terminal', lastStatus };
    if (buffer.trim() && consume('\n\n')) return { ended: 'terminal', lastStatus };
  } catch (cause) {
    if (signal?.aborted) return { ended: 'aborted', lastStatus };
    return drop(messageOf(cause));
  }

  if (signal?.aborted) return { ended: 'aborted', lastStatus };
  return drop('the stream ended before the run reached a terminal state');
}

/**
 * Split off every frame the buffer holds in full.
 *
 * Frames end at a blank line in any of the three line endings SSE allows, so a chunk that
 * cuts a frame — or even a `\r\n` — in half leaves the remainder in `rest` for the next
 * read to complete.
 */
function splitFrames(buffer: string): { frames: string[]; rest: string } {
  const frames: string[] = [];
  const separator = /\r\n\r\n|\n\n|\r\r/g;
  let start = 0;
  let match: RegExpExecArray | null;
  while ((match = separator.exec(buffer)) !== null) {
    frames.push(buffer.slice(start, match.index));
    start = match.index + match[0].length;
  }
  return { frames, rest: buffer.slice(start) };
}

/** One `event:`/`data:` frame, as the event it names. Comments and keepalives are skipped. */
function readFrame(frame: string, dispatch: (event: RunEvent) => void): RunEvent | null {
  let name = '';
  const data: string[] = [];

  for (const line of frame.split(/\r\n|\n|\r/)) {
    if (!line || line.startsWith(':')) continue; // a keepalive comment
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    const raw = colon < 0 ? '' : line.slice(colon + 1);
    const value = raw.startsWith(' ') ? raw.slice(1) : raw;
    if (field === 'event') name = value;
    else if (field === 'data') data.push(value);
    // `id:` and `retry:` are part of SSE and mean nothing to this contract.
  }

  if (!data.length) return null;
  const body = data.join('\n');

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(body) as Record<string, unknown>;
  } catch (cause) {
    dispatch({
      kind: 'error',
      code: 'malformed_event',
      message: `unreadable ${name || 'message'} frame: ${messageOf(cause)}`,
      retryable: false,
    });
    return null;
  }

  if (name === 'delta') {
    return {
      kind: 'delta',
      messageId: text(payload.message_id),
      attempt: number(payload.attempt, 1),
      text: text(payload.text),
    };
  }

  if (name === 'status') {
    const state = text(payload.state) as RunState;
    return {
      kind: 'status',
      runId: text(payload.run_id),
      state,
      messageId: optional(payload.message_id),
      attempt: payload.attempt === undefined || payload.attempt === null
        ? null
        : number(payload.attempt, 1),
      contextPackId: optional(payload.context_pack_id),
      detail: optional(payload.detail),
      terminal: TERMINAL.has(state),
    };
  }

  if (name === 'error') {
    return {
      kind: 'error',
      code: text(payload.code) || 'internal_error',
      message: text(payload.message),
      retryable: payload.retryable === true,
    };
  }

  // An event name this version does not know about is skipped rather than guessed at.
  return null;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function optional(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

function number(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

/**
 * The run event stream, against a scripted `ReadableStream`.
 *
 * These tests are about the two things a transcript cannot be wrong about. The frames are
 * parsed exactly as plan §0.4 writes them, whatever the network did to the chunk
 * boundaries — a delta cut in half mid-JSON is still one delta, not two lost ones. And an
 * ending is never invented: a stream that stops without a terminal status is reported as a
 * disconnection, so the caller reconciles through `session.get` instead of showing a
 * half-written answer as if it were finished (conversation spec §8).
 */
import { describe, expect, it, vi } from 'vitest';
import { subscribeRunEvents, runEventsUrl } from './sse';
import type { RunEvent } from './sse';

/** A body that yields exactly these chunks, in order, one `read()` at a time. */
function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

function daemon(body: BodyInit | null, init: ResponseInit = {}) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, requestInit?: RequestInit) => {
    calls.push({ url: String(input), init: requestInit });
    return new Response(body, { status: 200, ...init });
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, calls };
}

/** Collect everything the subscription reports, in order. */
function collector() {
  const events: RunEvent[] = [];
  return { events, handlers: { onEvent: (event: RunEvent) => events.push(event) } };
}

const DELTA = (text: string, attempt = 1) =>
  `event: delta\ndata: ${JSON.stringify({ message_id: 'M0042', attempt, text })}\n\n`;

const STATUS = (state: string, extra: Record<string, unknown> = {}) =>
  `event: status\ndata: ${JSON.stringify({ run_id: 'R0001', state, message_id: 'M0042', attempt: 1, context_pack_id: 'CP0007', ...extra })}\n\n`;

describe('subscribeRunEvents', () => {
  it('reads deltas and ends on a terminal status', async () => {
    const { fetchImpl, calls } = daemon(
      streamOf(STATUS('running'), DELTA('The '), DELTA('estimate '), STATUS('succeeded')),
    );
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test/', 'local-token', 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('terminal');
    expect(result.lastStatus?.state).toBe('succeeded');
    expect(result.lastStatus?.contextPackId).toBe('CP0007');
    expect(events.map((event) => event.kind)).toEqual(['status', 'delta', 'delta', 'status']);
    expect(events.filter((e): e is Extract<RunEvent, { kind: 'delta' }> => e.kind === 'delta')
      .map((e) => e.text)
      .join('')).toBe('The estimate ');

    // The token rides in a header, which is why this is `fetch` and not `EventSource`.
    expect(calls[0]?.url).toBe('http://daemon.test/runs/R0001/events');
    const headers = calls[0]?.init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer local-token');
    expect(headers.Accept).toBe('text/event-stream');
  });

  it('does not care where the chunks were cut', async () => {
    const whole = STATUS('running') + DELTA('β̂ = 0.42') + STATUS('succeeded');
    // Cut mid-JSON, mid-frame, and between the two newlines that end a frame.
    const chunks = [whole.slice(0, 12), whole.slice(12, 61), whole.slice(61, 120), whole.slice(120)];
    const { fetchImpl } = daemon(streamOf(...chunks));
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('terminal');
    expect(events.map((event) => event.kind)).toEqual(['status', 'delta', 'status']);
    expect(events[1]).toMatchObject({ kind: 'delta', text: 'β̂ = 0.42', attempt: 1 });
  });

  it('reads a frame the server never closed with a blank line', async () => {
    const { fetchImpl } = daemon(streamOf(DELTA('one'), STATUS('succeeded').trimEnd()));
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('terminal');
    expect(events.map((event) => event.kind)).toEqual(['delta', 'status']);
  });

  it('stops at the terminal status and ignores whatever follows it', async () => {
    const { fetchImpl } = daemon(streamOf(STATUS('cancelled') + DELTA('too late')));
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('terminal');
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ kind: 'status', state: 'cancelled', terminal: true });
  });

  it('keeps an interrupted stream honest: incomplete is terminal, and says so', async () => {
    const { fetchImpl } = daemon(
      streamOf(DELTA('half an answ'), STATUS('incomplete', { detail: 'the provider stopped' })),
    );
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('terminal');
    expect(events[1]).toMatchObject({
      kind: 'status',
      state: 'incomplete',
      terminal: true,
      detail: 'the provider stopped',
    });
  });

  it('surfaces an error frame with the daemon’s own code', async () => {
    const error = `event: error\ndata: ${JSON.stringify({ code: 'provider_unavailable', message: 'the provider refused', retryable: true })}\n\n`;
    const { fetchImpl } = daemon(streamOf(error, STATUS('failed')));
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('terminal');
    expect(events[0]).toEqual({
      kind: 'error',
      code: 'provider_unavailable',
      message: 'the provider refused',
      retryable: true,
    });
  });

  it('reports a stream that ends without a terminal status as a disconnection', async () => {
    const { fetchImpl } = daemon(streamOf(STATUS('running'), DELTA('half an answ')));
    const onDisconnected = vi.fn();
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', {
      ...handlers,
      onDisconnected,
    }, { fetchImpl });

    expect(result.ended).toBe('disconnected');
    expect(onDisconnected).toHaveBeenCalledTimes(1);
    expect(events.at(-1)).toMatchObject({ kind: 'disconnected', lastState: 'running' });
    // Nothing was invented: the last status the caller saw is still `running`.
    expect(result.lastStatus?.state).toBe('running');
  });

  it('ignores keepalive comments and event names it does not know', async () => {
    const { fetchImpl } = daemon(
      streamOf(': ping\n\n', 'event: telemetry\ndata: {"whatever": 1}\n\n', STATUS('succeeded')),
    );
    const { events, handlers } = collector();

    await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, { fetchImpl });

    expect(events.map((event) => event.kind)).toEqual(['status']);
  });

  it('names an unreadable frame instead of dropping it silently', async () => {
    const { fetchImpl } = daemon(streamOf('event: delta\ndata: {not json\n\n', STATUS('failed')));
    const { events, handlers } = collector();

    await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, { fetchImpl });

    expect(events[0]).toMatchObject({ kind: 'error', code: 'malformed_event', retryable: false });
    expect(events[1]).toMatchObject({ kind: 'status', state: 'failed' });
  });

  it('turns an HTTP refusal into an error and a disconnection', async () => {
    const { fetchImpl } = daemon('no token', { status: 401 });
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('disconnected');
    expect(events[0]).toMatchObject({ kind: 'error', code: 'http_401', retryable: false });
    expect(events[1]).toMatchObject({ kind: 'disconnected' });
  });

  it('reports a transport failure rather than throwing at the caller', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('failed to fetch');
    }) as unknown as typeof fetch;
    const { events, handlers } = collector();

    const result = await subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
    });

    expect(result.ended).toBe('disconnected');
    expect(events[0]).toMatchObject({ kind: 'disconnected', reason: 'failed to fetch' });
  });

  it('ends quietly when the caller aborts', async () => {
    const controller = new AbortController();
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(inner) {
        stream = inner;
        inner.enqueue(new TextEncoder().encode(STATUS('running')));
      },
    });
    // What a real fetch does to its body when the signal fires.
    controller.signal.addEventListener('abort', () =>
      stream.error(new DOMException('aborted', 'AbortError')),
    );

    const { fetchImpl } = daemon(body);
    const { events, handlers } = collector();
    const subscription = subscribeRunEvents('http://daemon.test', null, 'R0001', handlers, {
      fetchImpl,
      signal: controller.signal,
    });

    await vi.waitFor(() => expect(events).toHaveLength(1));
    controller.abort();

    expect(await subscription).toMatchObject({ ended: 'aborted' });
    // Stopping on purpose is not a disconnection to reconcile.
    expect(events.map((event) => event.kind)).toEqual(['status']);
  });
});

describe('runEventsUrl', () => {
  it('escapes the run id and tolerates a trailing slash', () => {
    expect(runEventsUrl('http://127.0.0.1:8765/', 'R 1')).toBe(
      'http://127.0.0.1:8765/runs/R%201/events',
    );
    expect(runEventsUrl('', 'R0001')).toBe('/runs/R0001/events');
  });
});

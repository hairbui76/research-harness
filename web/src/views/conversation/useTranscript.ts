/**
 * One session's transcript, and the reconciliation every other part of the workspace uses.
 *
 * `session.get` is authoritative. The daemon persists every streamed delta into the message
 * *before* it emits it (v1.1 plan §0.4), so re-reading here is how a dropped stream, a
 * reload, a stop and a retry all recover — there is no client-side merge of a partial
 * answer with a stored one, because there is nothing to merge: the file already has it.
 *
 * The page is the whole session by default (`session.get` caps at 500 messages a call and
 * reports `next_offset`), and `loadMore` walks backwards through longer histories.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { HarnessClient } from '../../api/client';
import type { SessionTranscript } from '../../api/dto';

const PAGE = 200;

export interface TranscriptApi {
  transcript: SessionTranscript | null;
  loading: boolean;
  error: string | null;
  /** Re-read the session. Returns the page it read, so a caller can act on it. */
  reconcile: () => Promise<SessionTranscript | null>;
  /** Read the next page of a long history, appending to what is loaded. */
  loadMore: () => void;
  /** True while more of the transcript is on disk than is loaded. */
  hasMore: boolean;
}

export function useTranscript(
  client: HarnessClient,
  sessionId: string | null,
  options: { enabled?: boolean } = {},
): TranscriptApi {
  const enabled = options.enabled ?? true;
  const [transcript, setTranscript] = useState<SessionTranscript | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  useEffect(() => {
    setLimit(PAGE);
    if (!sessionId || !enabled) setTranscript(null);
  }, [enabled, sessionId]);

  const read = useCallback(async (): Promise<SessionTranscript | null> => {
    if (!sessionId || !enabled) return null;
    setLoading(true);
    try {
      const first = await client.sessionTranscript(sessionId, { offset: 0, limit });
      // A conversation shows its tail. One read covers a session that fits in the page;
      // only a longer history costs the second, anchored at the end.
      const page =
        first.next_offset === null || first.next_offset === undefined
          ? first
          : await client.sessionTranscript(sessionId, {
              offset: Math.max(0, first.total - limit),
              limit,
            });
      if (!live.current) return page;
      setTranscript(page);
      setError(null);
      return page;
    } catch (cause) {
      if (live.current) {
        setError(cause instanceof Error ? cause.message : String(cause));
        setTranscript(null);
      }
      return null;
    } finally {
      if (live.current) setLoading(false);
    }
  }, [client, enabled, limit, sessionId]);

  useEffect(() => {
    void read();
  }, [read]);

  const loadMore = useCallback(() => setLimit((value) => value + PAGE), []);

  return {
    transcript,
    loading,
    error,
    reconcile: read,
    loadMore,
    hasMore: transcript !== null && transcript.offset > 0,
  };
}

/**
 * The composer draft, per session, in `localStorage`.
 *
 * Conversation spec §8 asks for one thing and asks for it absolutely: *composer drafts
 * persist through navigation, refresh, and individual send failures*. So the draft is
 * written on every keystroke, keyed by session, and it is cleared in exactly one place —
 * after `session.send` has answered, which is the moment the words became a durable
 * message. A refusal, a provider outage, a dropped stream and a remount all leave it
 * exactly as it was.
 *
 * Every access is wrapped: a browser with storage disabled (or a private window that
 * throws on write) still types, it simply forgets between reloads. Losing the memory of a
 * draft is acceptable; losing the draft in front of the researcher is not, so the in-memory
 * state is authoritative and storage is only its backup.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ComposerValue, EntityRefModel } from '@research-harness/design';

const PREFIX = 'research-harness.conversation.draft';

export const EMPTY_DRAFT: ComposerValue = { text: '', tokens: [] };

export function draftKey(sessionId: string): string {
  return `${PREFIX}.${sessionId}`;
}

/** Reads one session's stored draft. Anything unreadable is treated as "no draft". */
export function readDraft(sessionId: string | null): ComposerValue {
  if (!sessionId) return EMPTY_DRAFT;
  try {
    const raw = window.localStorage.getItem(draftKey(sessionId));
    if (!raw) return EMPTY_DRAFT;
    const parsed = JSON.parse(raw) as Partial<ComposerValue>;
    return {
      text: typeof parsed.text === 'string' ? parsed.text : '',
      tokens: Array.isArray(parsed.tokens) ? (parsed.tokens as EntityRefModel[]) : [],
    };
  } catch {
    return EMPTY_DRAFT;
  }
}

function writeDraft(sessionId: string, value: ComposerValue): void {
  try {
    if (value.text.length === 0 && value.tokens.length === 0) {
      window.localStorage.removeItem(draftKey(sessionId));
      return;
    }
    window.localStorage.setItem(draftKey(sessionId), JSON.stringify(value));
  } catch {
    /* storage is unavailable; the draft still lives in React state for this tab */
  }
}

export interface DraftApi {
  value: ComposerValue;
  setValue: (value: ComposerValue) => void;
  /** Drop the draft. Called once a send has produced a durable message, and never on failure. */
  clear: () => void;
}

/** The draft for `sessionId`, restored on mount and on every session change. */
export function useDraft(sessionId: string | null): DraftApi {
  const [value, setValueState] = useState<ComposerValue>(() => readDraft(sessionId));
  const current = useRef(sessionId);

  // Switching sessions swaps drafts rather than carrying one across: the words belong to
  // the conversation they were typed into.
  useEffect(() => {
    if (current.current === sessionId) return;
    current.current = sessionId;
    setValueState(readDraft(sessionId));
  }, [sessionId]);

  const setValue = useCallback(
    (next: ComposerValue) => {
      setValueState(next);
      if (sessionId) writeDraft(sessionId, next);
    },
    [sessionId],
  );

  const clear = useCallback(() => {
    setValueState(EMPTY_DRAFT);
    if (sessionId) writeDraft(sessionId, EMPTY_DRAFT);
  }, [sessionId]);

  return { value, setValue, clear };
}

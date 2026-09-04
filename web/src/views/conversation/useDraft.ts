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
import { projectHref, useProjectPaths } from '../../app/projectPaths';

const PREFIX = 'research-harness.conversation.draft';

export const EMPTY_DRAFT: ComposerValue = { text: '', tokens: [] };

/**
 * Where one session's draft is kept.
 *
 * Session ids are per-workspace — two projects both have a `CS0001` — and one browser
 * origin now holds every project the researcher opened, so the key carries the project as
 * well. A null project is the legacy host and keeps the key it has always used, which is
 * what makes an existing `research serve` draft survive this change (design §11).
 */
export function draftKey(sessionId: string, projectId: string | null = null): string {
  return projectId ? `${PREFIX}.${projectId}.${sessionId}` : `${PREFIX}.${sessionId}`;
}

/** Reads one session's stored draft. Anything unreadable is treated as "no draft". */
export function readDraft(sessionId: string | null, projectId: string | null = null): ComposerValue {
  if (!sessionId) return EMPTY_DRAFT;
  try {
    const raw = window.localStorage.getItem(draftKey(sessionId, projectId));
    if (!raw) return EMPTY_DRAFT;
    const parsed = JSON.parse(raw) as Partial<ComposerValue>;
    return {
      text: typeof parsed.text === 'string' ? parsed.text : '',
      tokens: Array.isArray(parsed.tokens)
        ? (parsed.tokens as EntityRefModel[]).map((token) => withProjectHref(token, projectId))
        : [],
    };
  } catch {
    return EMPTY_DRAFT;
  }
}

function writeDraft(sessionId: string, projectId: string | null, value: ComposerValue): void {
  try {
    if (value.text.length === 0 && value.tokens.length === 0) {
      window.localStorage.removeItem(draftKey(sessionId, projectId));
      return;
    }
    window.localStorage.setItem(
      draftKey(sessionId, projectId),
      JSON.stringify({ ...value, tokens: value.tokens.map(localHrefOf) }),
    );
  } catch {
    /* storage is unavailable; the draft still lives in React state for this tab */
  }
}

/** The `/projects/{id}` a stored token must not carry, so a route is never frozen in storage. */
const PROJECT_PREFIX = /^\/projects\/[^/]+(?=\/|$)/;

/** One token as it is stored: its route back to a workspace-local path. */
function localHrefOf(token: EntityRefModel): EntityRefModel {
  if (token.href === undefined) return token;
  const local = token.href.replace(PROJECT_PREFIX, '');
  return local === token.href ? token : { ...token, href: local.length > 0 ? local : '/' };
}

/** One stored token as it is rendered: its route pointed back into this project's tree. */
function withProjectHref(token: EntityRefModel, projectId: string | null): EntityRefModel {
  if (token.href === undefined || !projectId) return token;
  return { ...token, href: projectHref(projectId, token.href) };
}

export interface DraftApi {
  value: ComposerValue;
  setValue: (value: ComposerValue) => void;
  /** Drop the draft. Called once a send has produced a durable message, and never on failure. */
  clear: () => void;
}

/** The draft for `sessionId`, restored on mount and on every session change. */
export function useDraft(sessionId: string | null): DraftApi {
  const { projectId } = useProjectPaths();
  const [value, setValueState] = useState<ComposerValue>(() => readDraft(sessionId, projectId));
  const current = useRef<{ session: string | null; project: string | null }>({
    session: sessionId,
    project: projectId,
  });

  // Switching sessions swaps drafts rather than carrying one across: the words belong to
  // the conversation they were typed into — and, since one window now holds several
  // projects, to the project that conversation is in.
  useEffect(() => {
    if (current.current.session === sessionId && current.current.project === projectId) return;
    current.current = { session: sessionId, project: projectId };
    setValueState(readDraft(sessionId, projectId));
  }, [projectId, sessionId]);

  const setValue = useCallback(
    (next: ComposerValue) => {
      setValueState(next);
      if (sessionId) writeDraft(sessionId, projectId, next);
    },
    [projectId, sessionId],
  );

  const clear = useCallback(() => {
    setValueState(EMPTY_DRAFT);
    if (sessionId) writeDraft(sessionId, projectId, EMPTY_DRAFT);
  }, [projectId, sessionId]);

  return { value, setValue, clear };
}

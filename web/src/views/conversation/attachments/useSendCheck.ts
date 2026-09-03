/**
 * `attachment.check_send`: may these files go to the model that is selected right now?
 *
 * The check runs on every change to the pair that decides the answer — the selected model
 * and the set of attachments — and again immediately before a send, because the model
 * selector and the tray are two controls a researcher can change between one and the other.
 * It is a read: it looks at the attachment records and the configured provider capabilities
 * and writes nothing.
 *
 * Everything it produces is the daemon's. Size, page and count limits, media support,
 * egress rules and the compatible-model suggestion are all decided in
 * `conversation/attachments.py::sendability`, and this hook renames the answer into the
 * composer's `blockedReasons` without adding a rule of its own. That matters twice over:
 * the refusal a researcher reads here is the same sentence `session.send` would refuse
 * with, and a client that guessed could disagree with the daemon about what travelled.
 *
 * A check that could not run at all — no providers configured, a model the daemon does not
 * know — is reported as a note and blocks nothing. `session.send` runs the same check
 * inside the mutation and refuses there, with the draft and the attachments untouched, so
 * the honest answer to "we could not ask" is to say so rather than to bar the send.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ComposerBlockedReason } from '@research-harness/design';
import type { HarnessClient } from '../../../api/client';
import type { AttachmentSendCheck, AttachmentSendItem } from '../../../api/dto';
import { blockedReasonsOf } from './mappers';

export interface SendCheckApi {
  /** The last verdict, or null when nothing has been checked yet. */
  check: AttachmentSendCheck | null;
  /** The per-item verdicts, keyed by `SA####`. */
  items: Map<string, AttachmentSendItem>;
  /** Every reason the send is blocked, one per item, with the daemon's suggestion. */
  blockedReasons: ComposerBlockedReason[];
  /** True when nothing blocks the send. True as well when there is nothing to check. */
  ok: boolean;
  loading: boolean;
  /** Why the check could not be made. Never a refusal; the send is not blocked by it. */
  error: string | null;
  /** Ask again — the composer does this immediately before it sends. */
  refresh: () => Promise<AttachmentSendCheck | null>;
}

export interface SendCheckOptions {
  /** The selected model's id, which is the configured entry's name. Null uses the default. */
  model: string | null;
  /** The attachments to check. Empty means there is nothing to ask about. */
  attachments: readonly string[];
  /** False while the conversation is not the screen. */
  enabled?: boolean;
}

export function useSendCheck(
  client: HarnessClient,
  sessionId: string | null,
  options: SendCheckOptions,
): SendCheckApi {
  const { model, attachments, enabled = true } = options;
  const [check, setCheck] = useState<AttachmentSendCheck | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The ids as one string, so a re-rendered but unchanged list does not re-ask the daemon.
  const key = attachments.join(',');
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  /**
   * Ask once, and answer with what came back.
   *
   * The arguments are read from the parameters rather than from state so that a `refresh()`
   * awaited inside a send is checking the model and the files as they are at that moment.
   */
  const run = useCallback(async (): Promise<AttachmentSendCheck | null> => {
    if (!sessionId || attachments.length === 0) {
      if (live.current) {
        setCheck(null);
        setError(null);
      }
      return null;
    }
    setLoading(true);
    try {
      const answer = await client.checkAttachmentSend({
        session: sessionId,
        // The daemon matches the configured entry by name, and `ProviderModel.id` *is* that
        // name. Omitting it asks about the entry the router would choose, which is exactly
        // what an unset model selector means.
        ...(model ? { provider: model } : {}),
        attachments: [...attachments],
      });
      if (live.current) {
        setCheck(answer);
        setError(null);
      }
      return answer;
    } catch (cause: unknown) {
      if (live.current) {
        setCheck(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      }
      return null;
    } finally {
      if (live.current) setLoading(false);
    }
    // Keyed on the ids rather than on the array: a re-render hands over a new array with
    // the same files in it, and re-asking the daemon on every render is not a check, it is
    // a loop.
  }, [client, key, model, sessionId]);

  useEffect(() => {
    if (!enabled) return;
    void run();
  }, [enabled, run]);

  const items = useMemo(
    () => new Map((check?.items ?? []).map((item) => [item.attachment, item])),
    [check],
  );

  const blockedReasons = useMemo(() => blockedReasonsOf(check), [check]);

  return {
    check,
    items,
    blockedReasons,
    ok: check === null ? true : check.ok,
    loading,
    error,
    refresh: run,
  };
}

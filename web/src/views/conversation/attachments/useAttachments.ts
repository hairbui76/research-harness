/**
 * The session's attachments: what is there, what is arriving, and what failed.
 *
 * The lifecycle is the attachments design's, and it is *mirrored*, never invented:
 * `selected → validating → ready | failed`. A file the researcher drops appears in the
 * tray immediately as a local item in `validating`; the byte route answers with the record
 * the daemon wrote, and that record — `ready`, or `failed` carrying the daemon's own
 * reason — replaces it. This client never decides that a PNG is too large or that a PDF
 * has too many pages: it asks, and it renders the answer.
 *
 * Three promises hold everywhere below, because each one is a spec requirement rather than
 * a nicety:
 *
 * - **One failure never takes the others.** Files are uploaded one at a time and each
 *   result is recorded on its own, so a batch of three with one refusal leaves two ready.
 * - **A failed item stays visible.** It keeps its `File`, so `retry` re-uploads exactly
 *   what was chosen rather than asking the researcher to find it again.
 * - **Nothing here is corpus state.** Attaching writes session-only bytes; the corpus is
 *   reached only through `SaveToCorpusFlow`, and only when somebody asks for it.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import type { AttachmentModel, ComposerBlockedReason } from '@research-harness/design';
import type { HarnessClient } from '../../../api/client';
import type { AttachmentSendItem, AttachmentView, SessionAttachmentRecord } from '../../../api/dto';
import { useAttachmentUrls } from '../useAttachmentUrls';
import type { AttachmentUrls } from '../useAttachmentUrls';
import { attachmentModelOf, pendingModelOf, toSendability } from './mappers';
import type { PendingAttachment } from './mappers';
import { useSaveToCorpus } from './SaveToCorpusFlow';
import type { SaveToCorpusApi } from './SaveToCorpusFlow';
import { useSendCheck } from './useSendCheck';
import type { SendCheckApi } from './useSendCheck';

/** The states in which the daemon durably holds bytes a message can carry. */
const SENDABLE = new Set(['ready', 'session_only', 'in_corpus']);

/** One identity for "nothing", so a stable option object does not re-run every memo. */
const NONE: readonly string[] = [];

export interface AttachmentsApi {
  /**
   * The tray's list: the files riding along with the *current draft*, arriving ones first
   * included. An attachment a message already carries is not one of them — it was sent
   * with that turn and belongs to it, and a tray that re-offered it would attach the same
   * file to every later message.
   */
  models: AttachmentModel[];
  /** Every attachment of this session, for the transcript and the inspector. */
  allModels: AttachmentModel[];
  /** The records the daemon holds, for anything that needs the DTO rather than the model. */
  records: AttachmentView[];
  /** The ids `session.send` carries. Only what the daemon says it durably holds. */
  sendableIds: string[];
  /** Copy files into the session. Multiple files; one refusal never touches the rest. */
  attach: (files: readonly File[]) => Promise<void>;
  /** Delete one attachment, its bytes and its previews. */
  remove: (id: string) => Promise<void>;
  /** Try a failed upload again with the bytes already chosen. */
  retry: (id: string) => Promise<void>;
  /** True while any upload is in flight. */
  busy: boolean;
  /** False for a window the daemon will not let write; the intake says so and does nothing. */
  canAttach: boolean;
  /** Why the intake is closed, in the daemon's own sentence. */
  blockedReason: string | null;
  /** Byte and preview URLs per attachment, shared with the transcript. */
  urls: Map<string, AttachmentUrls>;
  /** A record this client just learned about, from any capability that returned one. */
  applyRecord: (record: AttachmentView) => void;
}

export interface AttachmentsOptions {
  /** The attachments the transcript already lists, as `session.get` returned them. */
  records: readonly SessionAttachmentRecord[];
  /** The ids messages in this session already carry; they belong to those turns. */
  usedIds?: readonly string[];
  /** False for a window the daemon will not let write (an agent host). */
  canMutate?: boolean;
  /** The daemon's sentence for why it will not. */
  blockedReason?: string | null;
}

export function useAttachments(
  client: HarnessClient,
  sessionId: string | null,
  options: AttachmentsOptions,
): AttachmentsApi {
  const {
    records: fromTranscript,
    usedIds = NONE,
    canMutate = true,
    blockedReason = null,
  } = options;
  // Records this client learned about directly — an upload's answer, a save's answer.
  const [local, setLocal] = useState<Record<string, AttachmentView>>({});
  const [pending, setPending] = useState<PendingAttachment[]>([]);
  // Ids the daemon has deleted. The transcript still lists them until it is re-read, and a
  // file the researcher removed must not reappear while that read is in flight.
  const [removed, setRemoved] = useState<ReadonlySet<string>>(() => new Set<string>());
  const [busy, setBusy] = useState(false);
  const nextKey = useRef(0);

  const applyRecord = useCallback((record: AttachmentView) => {
    setLocal((previous) => ({ ...previous, [record.id]: record }));
  }, []);

  /**
   * The transcript's records, overlaid with the ones we have been told about since.
   *
   * `updated_at` decides, not the source: a `session.get` that landed after a save is as
   * authoritative as the save's own answer, and taking the later of the two means neither
   * a stale read nor a stale overlay can put an attachment back into a state it has left.
   */
  const visible = useMemo<AttachmentView[]>(() => {
    const merged = new Map<string, AttachmentView>();
    for (const record of fromTranscript) merged.set(record.id, record);
    for (const [id, record] of Object.entries(local)) {
      const existing = merged.get(id);
      merged.set(id, existing && isNewer(existing, record) ? existing : record);
    }
    return [...merged.values()].filter((record) => !removed.has(record.id));
  }, [fromTranscript, local, removed]);

  const urls = useAttachmentUrls(client, sessionId, visible);

  /** Upload one file and record whatever came back, refusal included. */
  const upload = useCallback(
    async (session: string, entry: PendingAttachment): Promise<void> => {
      setPending((items) =>
        items.map((item) =>
          item.key === entry.key
            ? { ...item, state: 'validating', failureReason: undefined }
            : item,
        ),
      );
      try {
        const record = await client.addSessionAttachment(session, entry.file, {
          filename: entry.filename,
        });
        applyRecord(record);
        // The file now has an `SA####`, so the local placeholder has nothing left to say.
        setPending((items) => items.filter((item) => item.key !== entry.key));
      } catch (cause: unknown) {
        setPending((items) =>
          items.map((item) =>
            item.key === entry.key
              ? { ...item, state: 'failed', failureReason: messageOf(cause) }
              : item,
          ),
        );
      }
    },
    [applyRecord, client],
  );

  const attach = useCallback(
    async (files: readonly File[]): Promise<void> => {
      if (!sessionId || !canMutate || files.length === 0) return;
      const entries: PendingAttachment[] = files.map((file) => ({
        key: `upload-${(nextKey.current += 1)}`,
        file,
        filename: file.name || 'attachment',
        mediaType: file.type || 'application/octet-stream',
        size: file.size,
        state: 'selected',
      }));
      setPending((items) => [...items, ...entries]);
      setBusy(true);
      try {
        // One at a time and awaited individually: a refusal is recorded against the file it
        // belongs to, and every later file is still attempted.
        for (const entry of entries) await upload(sessionId, entry);
      } finally {
        setBusy(false);
      }
    },
    [canMutate, sessionId, upload],
  );

  const retry = useCallback(
    async (id: string): Promise<void> => {
      if (!sessionId || !canMutate) return;
      const entry = pending.find((item) => item.key === id);
      if (!entry) return;
      setBusy(true);
      try {
        await upload(sessionId, entry);
      } finally {
        setBusy(false);
      }
    },
    [canMutate, pending, sessionId, upload],
  );

  const remove = useCallback(
    async (id: string): Promise<void> => {
      // A file that never reached the daemon is forgotten here; there is nothing to delete.
      if (pending.some((item) => item.key === id)) {
        setPending((items) => items.filter((item) => item.key !== id));
        return;
      }
      if (!sessionId || !canMutate) return;
      await client.removeSessionAttachment(sessionId, id);
      setLocal((previous) => {
        const next = { ...previous };
        delete next[id];
        return next;
      });
      setRemoved((previous) => new Set(previous).add(id));
    },
    [canMutate, client, pending, sessionId],
  );

  const allModels = useMemo(
    () => visible.map((record) => attachmentModelOf(record, { urls: urls.get(record.id) ?? {} })),
    [urls, visible],
  );

  /*
   * The draft's files, which is not the same as the session's files.
   *
   * `session.get` lists every attachment the session holds, including the ones past
   * messages carry. Those belong to their turn: the transcript draws them and the
   * inspector can save them, but the composer must not offer them again, or every later
   * message would silently carry every earlier file.
   */
  const used = useMemo(() => new Set(usedIds), [usedIds]);
  const models = useMemo(
    () => [...allModels.filter((model) => !used.has(model.id)), ...pending.map(pendingModelOf)],
    [allModels, pending, used],
  );

  const sendableIds = useMemo(
    () =>
      visible
        .filter((record) => SENDABLE.has(record.state) && !used.has(record.id))
        .map((record) => record.id),
    [used, visible],
  );

  return {
    models,
    allModels,
    records: visible,
    sendableIds,
    attach,
    remove,
    retry,
    busy,
    canAttach: canMutate && sessionId !== null,
    blockedReason: canMutate ? null : blockedReason,
    urls,
    applyRecord,
  };
}

/** Everything the composer, the transcript and the inspector need for attachments. */
export interface AttachmentWorkspace {
  files: AttachmentsApi;
  send: SendCheckApi;
  save: SaveToCorpusApi;
  /** Every reason the composer must not send, per item, with the daemon's suggestion. */
  blockedReasons: ComposerBlockedReason[];
  /** One attachment's view model, wherever it is drawn. */
  modelOf: (attachmentId: string) => AttachmentModel | null;
}

/**
 * The whole attachment surface for one session, assembled once.
 *
 * The composer's tray, the transcript's rows and the inspector's entry are three places in
 * the tree that have to agree about one file: its state, its verdict against the selected
 * model, and whether it has been saved. So the list, the send check and the save flow are
 * built here and shared, rather than each surface asking its own question and drawing its
 * own answer.
 */
export function useAttachmentWorkspace(
  client: HarnessClient,
  sessionId: string | null,
  options: AttachmentsOptions & { model?: string | null; enabled?: boolean },
): AttachmentWorkspace {
  const files = useAttachments(client, sessionId, options);
  const send = useSendCheck(client, sessionId, {
    model: options.model ?? null,
    attachments: files.sendableIds,
    enabled: options.enabled ?? true,
  });
  const save = useSaveToCorpus(client, sessionId, {
    canMutate: options.canMutate ?? true,
    blockedReason: options.blockedReason ?? null,
    onRecord: files.applyRecord,
  });

  // The verdict the daemon has just given outranks the reason stored on the record: it is
  // an answer about *this* model, and the tray must not show yesterday's sentence beside it.
  const verdictOf = useCallback(
    (model: AttachmentModel): AttachmentModel => {
      const verdict: AttachmentSendItem | undefined = send.items.get(model.id);
      return verdict ? { ...model, sendability: toSendability(verdict) } : model;
    },
    [send.items],
  );
  const decorated = useMemo(() => files.models.map(verdictOf), [files.models, verdictOf]);
  const decoratedAll = useMemo(() => files.allModels.map(verdictOf), [files.allModels, verdictOf]);

  const byId = useMemo(
    () => new Map(decoratedAll.map((model) => [model.id, model])),
    [decoratedAll],
  );
  const modelOf = useCallback((id: string) => byId.get(id) ?? null, [byId]);

  return {
    files: { ...files, models: decorated, allModels: decoratedAll },
    send,
    save,
    blockedReasons: send.blockedReasons,
    modelOf,
  };
}

/** True when `a` is at least as recent as `b`; an unstamped record loses to a stamped one. */
function isNewer(a: AttachmentView, b: AttachmentView): boolean {
  if (!a.updated_at) return false;
  if (!b.updated_at) return true;
  return a.updated_at > b.updated_at;
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

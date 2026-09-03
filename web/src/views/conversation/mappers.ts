/**
 * Daemon DTOs → Design System view models.
 *
 * One direction, no rules. Everything here is a rename or a lookup: which cockpit route a
 * stable id opens, which of the Design System's four message statuses an attempt status
 * is, which class a context item was packed under. Nothing decides authority, resolution,
 * sendability or omission — those words arrive from the daemon and are carried through
 * unchanged, because a client that re-derives them is a client that can disagree with the
 * transcript (PRODUCT §5 P10).
 *
 * The one judgement this file *does* make is presentational and is stated where it is
 * made: an id whose prefix names no graph node kind, and a context item with no stable id
 * at all, still have to be drawn as something.
 */
import type {
  AttachmentModel,
  AuthorityLabel,
  ContextAllocation,
  ContextClass,
  ContextItem,
  ContextReceiptModel,
  EntityKind,
  EntityRefModel,
  MessageBlock,
  MessageModel,
  MessageStatus,
  ModelOption,
  OmissionReason,
  OmittedContextItem,
  ResolutionState,
  SessionSummary,
} from '@research-harness/design';
import type {
  ContentBlock,
  ContextItemView,
  ContextPackView,
  ConversationMessage,
  ConversationSession,
  OmittedContextItemView,
  ProviderModel,
  SessionAttachmentRecord,
} from '../../api/dto';
import type { DeepLink } from '../../render';

/* ------------------------------------------------------------------------- */
/* identity                                                                   */
/* ------------------------------------------------------------------------- */

/**
 * Id prefix → graph node kind, longest prefix first.
 *
 * The order matters exactly as it does in `domain/ids.py::_BY_PREFIX_LENGTH`: `CS` has to
 * win over `C`, `SA` and `SR` over `S`, or a session id would read as a claim. `CP`
 * (context pack), `I` (interrogation) and `SR` (search run) are ids that exist but name no
 * `EntityKind`, so they resolve to `null` and are rendered as plain text rather than
 * mislabelled as something they are not.
 */
const KIND_BY_PREFIX: readonly (readonly [string, EntityKind])[] = [
  ['RQ', 'question'],
  ['CS', 'session'],
  ['SA', 'attachment'],
  ['W', 'work'],
  ['V', 'version'],
  ['A', 'artifact'],
  ['B', 'block'],
  ['E', 'evidence'],
  ['C', 'claim'],
  ['D', 'decision'],
  ['S', 'synthesis'],
  ['M', 'message'],
];

/** The graph node kind a stable id names, or null when its prefix names none. */
export function entityKindOf(id: string): EntityKind | null {
  if (id.startsWith('file:')) return 'manuscript_file';
  for (const [prefix, kind] of KIND_BY_PREFIX) {
    if (id.startsWith(prefix) && /^\d/.test(id.slice(prefix.length))) return kind;
  }
  return null;
}

/** `A0017-3`, `V0017-2` → `W0017`: the Work a work-scoped id belongs to. */
function workOf(id: string): string {
  const digits = /^[A-Z]+(\d+)/.exec(id);
  return digits ? `W${digits[1]}` : id;
}

export interface RouteContext {
  /** The session a message or attachment id is read in. */
  session?: string | null;
}

/**
 * The cockpit route a reference opens.
 *
 * `EntityRef` renders a real `<a href>` when it has one — middle-clickable, readable by
 * assistive technology — and calls `onOpen` for the plain left click, exactly as
 * `components/ObjectRef.tsx` does for the research pages.
 */
export function routeForEntity(
  kind: EntityKind,
  id: string,
  context: RouteContext = {},
): string | null {
  switch (kind) {
    case 'work':
      return `/corpus/${encodeURIComponent(id)}`;
    case 'version':
    case 'artifact':
    case 'block':
      return `/corpus/${encodeURIComponent(workOf(id))}`;
    case 'evidence':
      return `/evidence/${encodeURIComponent(id)}`;
    case 'claim':
      return `/claims/${encodeURIComponent(id)}`;
    case 'question':
      return '/questions';
    case 'decision':
      return '/claims';
    case 'synthesis':
      return '/synthesis';
    case 'session':
      return `${CONVERSATION_PATH}?session=${encodeURIComponent(id)}`;
    case 'message':
    case 'attachment':
      return context.session
        ? `${CONVERSATION_PATH}?session=${encodeURIComponent(context.session)}&${
            kind === 'message' ? 'message' : 'attachment'
          }=${encodeURIComponent(id)}`
        : null;
    case 'manuscript_file':
    case 'manuscript_anchor':
      return '/manuscript';
  }
}

/** Where the conversation workspace lives. The session travels in the query (`?session=`). */
export const CONVERSATION_PATH = '/';

/**
 * `rh://<kind>/<id>[?query]` → the cockpit route that opens it.
 *
 * The deep-link vocabulary of plan §0.1 is not the graph's node kinds: it says
 * `manuscript` where the graph says `manuscript_file`, and `session` carries the message
 * in its query. Returns null for a link this cockpit has no screen for, so the caller can
 * say so rather than navigate somewhere plausible.
 */
export function routeForDeepLink(link: DeepLink): string | null {
  const message = link.params.get('message');
  switch (link.kind) {
    case 'session':
      return `${CONVERSATION_PATH}?session=${encodeURIComponent(link.id)}${
        message ? `&message=${encodeURIComponent(message)}` : ''
      }`;
    case 'manuscript':
      return '/manuscript';
    case 'attachment':
      return null;
    default: {
      const kind = entityKindOf(link.id) ?? kindFromDeepLink(link.kind);
      return kind === null ? null : routeForEntity(kind, link.id);
    }
  }
}

function kindFromDeepLink(kind: string): EntityKind | null {
  const known: Record<string, EntityKind> = {
    work: 'work',
    version: 'version',
    artifact: 'artifact',
    block: 'block',
    evidence: 'evidence',
    claim: 'claim',
    question: 'question',
    decision: 'decision',
    synthesis: 'synthesis',
  };
  return known[kind] ?? null;
}

export interface EntityRefOptions {
  label?: string | null;
  authority?: AuthorityLabel | null;
  resolution?: ResolutionState;
  session?: string | null;
}

/**
 * One stable id as a reference chip.
 *
 * `resolution` defaults to `resolved` for the same reason `ObjectRef` does: these ids came
 * out of the daemon's own transcript and listings, so the object exists and this window
 * may read it. A caller that knows better — an unresolved `@` token, a private omission —
 * passes the state it was told.
 */
export function entityRefFor(id: string, options: EntityRefOptions = {}): EntityRefModel {
  const kind = entityKindOf(id) ?? 'block';
  const href = routeForEntity(kind, id, { session: options.session ?? null });
  return {
    id,
    kind,
    resolution: options.resolution ?? 'resolved',
    ...(options.label ? { label: options.label } : {}),
    ...(options.authority ? { authority: options.authority } : {}),
    ...(href ? { href } : {}),
  };
}

/* ------------------------------------------------------------------------- */
/* sessions                                                                   */
/* ------------------------------------------------------------------------- */

/** One session as the rail lists it. `preview` is the search snippet, when there was one. */
export function toSessionSummary(
  session: ConversationSession,
  preview?: string | null,
): SessionSummary {
  return {
    id: session.id,
    title: session.title,
    updatedAt: session.last_message_at ?? session.updated_at,
    messageCount: session.message_count,
    visibility: session.visibility,
    ...(preview ? { preview } : {}),
  };
}

/* ------------------------------------------------------------------------- */
/* transcript                                                                 */
/* ------------------------------------------------------------------------- */

/** One turn: the first attempt, and every retry that names it. */
export interface MessageTurn {
  /** The id of the first attempt; stable across retries, so it keys a list row. */
  key: string;
  attempts: ConversationMessage[];
}

/**
 * Group a transcript into turns.
 *
 * A retry is a *new* message carrying `attempt.retry_of`, so the failed attempt survives
 * (`domain/conversation.py::MessageAttempt`). The transcript shows one row per turn with
 * the attempts navigable inside it, rather than the same question answered three times in
 * a row — and nothing is hidden: every attempt is still reachable.
 */
export function groupAttempts(messages: readonly ConversationMessage[]): MessageTurn[] {
  const turns: MessageTurn[] = [];
  const turnOf = new Map<string, MessageTurn>();
  for (const message of messages) {
    const parent = message.attempt.retry_of;
    const existing = parent ? turnOf.get(parent) : undefined;
    if (existing) {
      existing.attempts.push(message);
      turnOf.set(message.id, existing);
      continue;
    }
    const turn: MessageTurn = { key: message.id, attempts: [message] };
    turns.push(turn);
    turnOf.set(message.id, turn);
  }
  return turns;
}

const STATUS_BY_ATTEMPT: Record<string, MessageStatus> = {
  complete: 'complete',
  interrupted: 'incomplete',
  failed: 'failed',
};

export interface MessageOptions {
  /** Session attachments, by id, so an attachment block can be drawn. */
  attachments?: ReadonlyMap<string, AttachmentModel>;
  /** Text that has arrived on the stream but is not yet in the persisted message. */
  streamingText?: string;
  /** True while this message's run is still open. */
  streaming?: boolean;
  /** `@` tokens the assembler could not resolve, from `SendStarted.unresolved`. */
  unresolved?: ReadonlySet<string>;
  /** Which attempt of its turn this is, and how many there are. */
  attempt?: number;
  attempts?: number;
}

/** One transcript entry as the Design System's `Message` takes it. */
export function toMessageModel(
  message: ConversationMessage,
  options: MessageOptions = {},
): MessageModel {
  const status: MessageStatus = options.streaming
    ? 'streaming'
    : (STATUS_BY_ATTEMPT[message.attempt.status] ?? 'complete');

  const blocks: MessageBlock[] = message.blocks.map((block) =>
    toMessageBlock(block, message.session, options),
  );

  if (options.streamingText) {
    blocks.push({ kind: 'text', text: options.streamingText });
  }
  if (message.attempt.status === 'failed' && message.attempt.error) {
    blocks.push({ kind: 'error', message: message.attempt.error, retryable: true });
  }

  return {
    id: message.id,
    role: message.role,
    createdAt: message.created_at,
    status,
    blocks,
    ...(message.context_pack ? { contextPackId: message.context_pack } : {}),
    ...(message.model ? { provider: message.model.provider, model: message.model.model } : {}),
    ...(options.attempt !== undefined ? { attempt: options.attempt } : {}),
    ...(options.attempts !== undefined && options.attempts > 1
      ? { attempts: options.attempts }
      : {}),
  };
}

function toMessageBlock(
  block: ContentBlock,
  session: string,
  options: MessageOptions,
): MessageBlock {
  switch (block.kind) {
    case 'text':
      return { kind: 'text', text: block.text };
    case 'reference':
      return {
        kind: 'reference',
        ref: entityRefFor(block.target, {
          label: block.label ?? null,
          authority: block.authority ?? null,
          resolution: options.unresolved?.has(block.target) === true ? 'unresolved' : 'resolved',
          session,
        }),
      };
    case 'attachment': {
      const known = options.attachments?.get(block.attachment);
      return { kind: 'attachment', attachment: known ?? missingAttachment(block.attachment) };
    }
  }
}

/**
 * An attachment block whose record is not in this page of the transcript.
 *
 * It is still drawn, with its id and a `failed` state, rather than dropped: a message that
 * carried a file must not silently look like a message that did not.
 */
function missingAttachment(id: string): AttachmentModel {
  return {
    id,
    name: id,
    mediaType: 'application/octet-stream',
    size: 0,
    state: 'failed',
    sendability: { ok: false, reason: 'This attachment is not in the loaded transcript page.' },
  };
}

/** One session attachment record as the Design System draws it. `urls` come from the host. */
export function toAttachmentModel(
  record: SessionAttachmentRecord,
  urls: { previewUrl?: string; thumbnailUrl?: string; downloadUrl?: string } = {},
): AttachmentModel {
  return {
    id: record.id,
    name: record.filename,
    mediaType: record.media_type,
    size: record.size_bytes,
    state: record.state,
    ...(record.page_count ? { pageCount: record.page_count } : {}),
    ...(urls.thumbnailUrl ? { thumbnailUrl: urls.thumbnailUrl } : {}),
    ...(urls.previewUrl ? { previewUrl: urls.previewUrl } : {}),
    ...(urls.downloadUrl ? { downloadUrl: urls.downloadUrl } : {}),
    ...(record.failure_reason
      ? { sendability: { ok: false, reason: record.failure_reason } }
      : {}),
  };
}

/**
 * Every message in `messages` that referenced `target`.
 *
 * The other half of the two-way navigation of conversation spec §2: a chat reference opens
 * its object, and the object lists the messages it was used in. It reads the transcript
 * already loaded rather than asking the graph, so it keeps working when the projection is
 * being rebuilt (spec §8).
 */
export function messagesReferencing(
  messages: readonly ConversationMessage[],
  target: string,
): ConversationMessage[] {
  return messages.filter((message) =>
    message.blocks.some((block) => block.kind === 'reference' && block.target === target),
  );
}

/* ------------------------------------------------------------------------- */
/* the `Context used` receipt                                                 */
/* ------------------------------------------------------------------------- */

/**
 * Context class → the node kind used to draw an item that carries no stable id.
 *
 * Packed policy text, a session excerpt and a corpus block are real material with a source
 * pointer and no `E####` of their own. They are still listed — a receipt that omitted what
 * it could not name would not be a receipt — so each one is drawn under the kind its class
 * describes, with the source pointer as its identity.
 */
const KIND_BY_CONTEXT_CLASS: Record<ContextClass, EntityKind> = {
  policy: 'block',
  accepted_state: 'block',
  current_session: 'message',
  prior_sessions: 'session',
  attachments: 'attachment',
  corpus_blocks: 'block',
  discovery: 'block',
};

/** A research id embedded in a source pointer, e.g. `CS0001/messages.jsonl#M0042`. */
const ID_IN_POINTER = /\b((?:RQ|CS|SA|SR|CP)\d{4,}|[WVABECDSMI]\d{4,}(?:-\d+)?)\b/;

/** How a resolution state follows from why something was left out. */
const RESOLUTION_BY_OMISSION: Partial<Record<OmissionReason, ResolutionState>> = {
  unresolved_reference: 'unresolved',
  privacy_policy: 'private',
  egress_blocked: 'private',
  stale: 'stale',
};

function contextRef(item: ContextItemView, resolution: ResolutionState): EntityRefModel {
  const id = item.id ?? ID_IN_POINTER.exec(item.source)?.[1] ?? null;
  if (id !== null && entityKindOf(id) !== null) {
    return entityRefFor(id, { label: item.label ?? null, authority: item.authority, resolution });
  }
  return {
    id: item.label ?? item.source,
    kind: KIND_BY_CONTEXT_CLASS[item.context_class],
    resolution,
    authority: item.authority,
  };
}

function toContextItem(item: ContextItemView): ContextItem {
  return {
    ref: contextRef(item, 'resolved'),
    cls: item.context_class,
    authority: item.authority,
    tokens: item.tokens,
    sourcePointer: item.source,
  };
}

function toOmittedItem(item: OmittedContextItemView): OmittedContextItem {
  return {
    ...toContextItem(item),
    ref: contextRef(item, RESOLUTION_BY_OMISSION[item.reason] ?? 'resolved'),
    reason: item.reason,
    ...(item.detail ? { detail: item.detail } : {}),
  };
}

/**
 * One `Context used` receipt, from `context.get` or `context.preview`.
 *
 * `egress: 'none'` — an assembled but unsent preview — is reported as `local`, because
 * nothing left the machine, and `ReceiptPanel` says in words that it was not sent. The
 * Design System's `EgressClass` has two members and both of them are claims about where
 * the request went; there is no third one to invent here.
 */
export function toContextReceiptModel(view: ContextPackView): ContextReceiptModel {
  const pack = view.pack;
  const allocation: ContextAllocation[] = Object.entries(view.tokens_by_class).map(
    ([cls, tokens]) => ({ cls: cls as ContextClass, tokens }),
  );
  return {
    packId: pack.id,
    provider: pack.model?.provider ?? 'not sent',
    model: pack.model?.model ?? '—',
    egressClass: pack.egress === 'external' ? 'external' : 'local',
    tokenBudget: pack.token_budget ?? view.tokens,
    allocation,
    included: pack.receipt.included.map(toContextItem),
    omitted: pack.receipt.omitted.map(toOmittedItem),
  };
}

/* ------------------------------------------------------------------------- */
/* models                                                                     */
/* ------------------------------------------------------------------------- */

/** One `provider.list` entry as the `ModelSelector` takes it. */
export function toModelOption(model: ProviderModel): ModelOption {
  return {
    id: model.id,
    label: model.label,
    provider: model.provider,
    egressClass: model.egress_class,
    vision: model.vision,
    contextTokens: model.context_tokens,
    available: model.available,
    ...(model.unavailable_reason ? { unavailableReason: model.unavailable_reason } : {}),
  };
}

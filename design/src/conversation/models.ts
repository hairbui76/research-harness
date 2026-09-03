/**
 * The conversation view models.
 *
 * Presentation shapes for a session, its transcript, its attachments and the models it can
 * be sent to. As in `research/models.ts` these mirror the daemon vocabularies of the v1.1
 * plan §0.3 exactly; the Web client maps DTOs onto them.
 *
 * Nothing here is a rule. A component is told that an attachment is unsendable and why; it
 * never works out sendability, compatibility, privacy or authority for itself.
 */
import type { IconName } from '../primitives/Icon';
import type { EgressClass, EntityRefModel, Visibility } from '../research/models';

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

/**
 * - `complete`   the turn finished normally;
 * - `streaming`  tokens are still arriving;
 * - `incomplete` the stream stopped early and what arrived was kept;
 * - `failed`     the attempt produced nothing usable.
 */
export type MessageStatus = 'complete' | 'streaming' | 'incomplete' | 'failed';

/** The attachment lifecycle of the attachments spec §2. */
export const ATTACHMENT_STATES = [
  'selected',
  'validating',
  'ready',
  'sending',
  'session_only',
  'promoting',
  'in_corpus',
  'failed',
] as const;

export type AttachmentState = (typeof ATTACHMENT_STATES)[number];

/** What the host decided about sending one attachment to the selected model. */
export interface AttachmentSendability {
  ok: boolean;
  reason?: string;
  /** A model that would accept it, when the host can name one. */
  suggestedModel?: string;
}

/** Where a session attachment ended up in the corpus, once it was explicitly promoted. */
export interface AttachmentCorpusLinks {
  work?: EntityRefModel;
  version?: EntityRefModel;
  artifact?: EntityRefModel;
}

export interface AttachmentModel {
  id: string;
  /** Display metadata only — never treated as a path. */
  name: string;
  mediaType: string;
  /** Bytes. */
  size: number;
  state: AttachmentState;
  pageCount?: number;
  thumbnailUrl?: string;
  previewUrl?: string;
  downloadUrl?: string;
  sendability?: AttachmentSendability;
  corpus?: AttachmentCorpusLinks;
}

export type MessageBlock =
  | { kind: 'text'; text: string }
  | { kind: 'reference'; ref: EntityRefModel }
  | { kind: 'attachment'; attachment: AttachmentModel }
  | { kind: 'error'; message: string; retryable: boolean };

export interface MessageModel {
  id: string;
  role: MessageRole;
  author?: string;
  /** ISO 8601 timestamp. */
  createdAt: string;
  status: MessageStatus;
  /** 1-based attempt number, when the turn was retried. */
  attempt?: number;
  attempts?: number;
  blocks: MessageBlock[];
  /** The `CP####` receipt for the call that produced this message. */
  contextPackId?: string;
  provider?: string;
  model?: string;
}

/** What a message can be promoted into. Promotion opens the host's review form. */
export const PROMOTION_TARGETS = [
  'note',
  'question',
  'claim_candidate',
  'decision_candidate',
] as const;

export type PromotionTarget = (typeof PROMOTION_TARGETS)[number];

export interface ModelOption {
  id: string;
  label: string;
  provider: string;
  egressClass: EgressClass;
  /** Whether the model reads images. */
  vision: boolean;
  contextTokens: number;
  available: boolean;
  /** Why it cannot be selected. Incompatible options stay visible with this reason. */
  unavailableReason?: string;
}

export interface SessionSummary {
  id: string;
  title: string;
  /** ISO 8601 timestamp. */
  updatedAt: string;
  messageCount: number;
  visibility: Visibility;
  preview?: string;
}

/**
 * The composer's value.
 *
 * `tokens` are structured references, kept beside the prose rather than pasted into it, so
 * `@E0482` is an object the assembler resolves at send time and not a string that happens
 * to look like an id. The host maps each one onto a `{ kind: 'reference', ref }` block.
 */
export interface ComposerValue {
  text: string;
  tokens: EntityRefModel[];
}

/** One reason the host is refusing to send. Rendered verbatim; never inferred here. */
export interface ComposerBlockedReason {
  /** The attachment it concerns, when it concerns one. */
  attachmentId?: string;
  reason: string;
  suggestedModel?: string;
}

export type ComposerSendState = 'idle' | 'sending' | 'streaming';

/* Presentation metadata ---------------------------------------------------------------- */

export interface RoleMeta {
  label: string;
  icon: IconName;
}

export const MESSAGE_ROLE_META: Record<MessageRole, RoleMeta> = {
  user: { label: 'You', icon: 'user' },
  assistant: { label: 'Assistant', icon: 'bot' },
  system: { label: 'System', icon: 'settings' },
  tool: { label: 'Tool', icon: 'wrench' },
};

export interface AttachmentStateMeta {
  /** Always rendered as text: attachment state is never a colour alone. */
  label: string;
  icon: IconName;
  description: string;
  /** Work is in flight. */
  busy: boolean;
  /** The bytes are durable in the session and can be acted on. */
  settled: boolean;
}

export const ATTACHMENT_STATE_META: Record<AttachmentState, AttachmentStateMeta> = {
  selected: {
    label: 'Selected',
    icon: 'circle-dashed',
    description: 'Chosen in the composer, not yet copied into the session.',
    busy: false,
    settled: false,
  },
  validating: {
    label: 'Checking',
    icon: 'loader',
    description: 'Type, size and page count are being checked.',
    busy: true,
    settled: false,
  },
  ready: {
    label: 'Ready',
    icon: 'circle-check',
    description: 'Copied into the session and ready to send.',
    busy: false,
    settled: true,
  },
  sending: {
    label: 'Sending',
    icon: 'loader',
    description: 'Being sent to the selected model with this message.',
    busy: true,
    settled: true,
  },
  session_only: {
    label: 'Session only',
    icon: 'lock',
    description: 'Working material in this session. Not part of the corpus.',
    busy: false,
    settled: true,
  },
  promoting: {
    label: 'Saving',
    icon: 'loader',
    description: 'Being copied into canonical corpus storage.',
    busy: true,
    settled: true,
  },
  in_corpus: {
    label: 'In corpus',
    icon: 'library',
    description: 'Saved to the corpus with a Work, Version and Artifact identity.',
    busy: false,
    settled: true,
  },
  failed: {
    label: 'Failed',
    icon: 'alert-circle',
    description: 'Something went wrong. The original file is untouched.',
    busy: false,
    settled: false,
  },
};

export const PROMOTION_TARGET_META: Record<
  PromotionTarget,
  { label: string; icon: IconName; description: string }
> = {
  note: {
    label: 'Research note',
    icon: 'pen-line',
    description: 'Keep this as a note, with provenance back to this message.',
  },
  question: {
    label: 'Research question',
    icon: 'circle-help',
    description: 'Open a question the project should answer.',
  },
  claim_candidate: {
    label: 'Claim candidate',
    icon: 'scale',
    description: 'Propose this as a claim. It enters review; it is not accepted.',
  },
  decision_candidate: {
    label: 'Decision candidate',
    icon: 'gavel',
    description: 'Propose this as a decision. It enters review; it is not accepted.',
  },
};

/** `1.4 MB`, `812 kB`, `640 B` — deterministic, locale-independent, SI units. */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1000) return `${Math.round(bytes)} B`;
  const units = ['kB', 'MB', 'GB', 'TB'] as const;
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const suffix = units[unit] ?? 'TB';
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${suffix}`;
}

/**
 * `2026-09-03 14:20` from an ISO timestamp.
 *
 * Deliberately not `toLocaleString`: the package renders the same DOM in a test, in a
 * snapshot and on the researcher's machine, and a locale-dependent timestamp makes that
 * untrue. A surface with a real locale passes its own formatter.
 */
export function formatMessageTime(iso: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return match ? `${match[1]} ${match[2]}` : iso;
}

/** True for the attachment states where `Save to corpus` is a meaningful offer. */
export function canSaveToCorpus(state: AttachmentState): boolean {
  return (
    state === 'ready' || state === 'session_only' || state === 'promoting' || state === 'in_corpus'
  );
}

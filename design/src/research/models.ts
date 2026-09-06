/**
 * The research view models.
 *
 * These are presentation shapes, not domain objects: the Web client maps the daemon's DTOs
 * onto them and hands them to a component. Nothing here decides anything — a component is
 * told what authority a thing has, whether an anchor is stale, whether a reference resolved
 * and what a model was and was not sent. It never works any of that out.
 *
 * The vocabularies mirror `domain/conversation.py` and `domain/graph.py` (v1.1 plan §0.3)
 * word for word, so a rename on either side is a compile error rather than a silent drift.
 */
import type { StatusName } from '../primitives/Badge';
import { STATUS_NAMES } from '../primitives/Badge';
import type { IconName } from '../primitives/Icon';

/**
 * Scientific authority. Identical to the Badge primitive's `StatusName`, aliased rather
 * than restated so the six states cannot fork between the token layer and this one.
 */
export type AuthorityLabel = StatusName;

/** Every authority label, in the order the product lists them. */
export const AUTHORITY_LABELS: readonly AuthorityLabel[] = STATUS_NAMES;

/**
 * `private` never leaves the machine unless policy explicitly allows it; `project` may
 * reach the selected provider under the egress policy.
 */
export type Visibility = 'private' | 'project';

/** The graph node kinds a reference can point at. */
export const ENTITY_KINDS = [
  'work',
  'version',
  'artifact',
  'block',
  'evidence',
  'claim',
  'question',
  'decision',
  'synthesis',
  'session',
  'message',
  'attachment',
  'manuscript_file',
  'manuscript_anchor',
] as const;

export type EntityKind = (typeof ENTITY_KINDS)[number];

/**
 * What the resolver said about a reference at render time.
 *
 * - `resolved`   the object exists, is visible here, and its anchor still matches;
 * - `unresolved` nothing with that id was found (yet — the index may be rebuilding);
 * - `stale`      it resolves, but the source moved under its anchor;
 * - `private`    it resolves, but this surface may not show or send it;
 * - `broken`     the id is malformed or points outside the project.
 */
export type ResolutionState = 'resolved' | 'unresolved' | 'stale' | 'private' | 'broken';

export interface EntityRefModel {
  /** Stable id, e.g. `W0017`, `E0482`, `CS0001`, or `file:main.tex`. */
  id: string;
  kind: EntityKind;
  /** Human title. Falls back to the id when the object could not be read. */
  label?: string;
  authority?: AuthorityLabel;
  resolution: ResolutionState;
  /** `rh://` deep link, when one exists. */
  href?: string;
}

/** An exact place inside a source artifact. */
export interface SourceAnchorModel {
  artifactId: string;
  page?: number;
  block?: string;
  table?: string;
  span?: { start: number; end: number };
  quote?: string;
  /** The document changed after the anchor was recorded. */
  stale?: boolean;
  href?: string;
}

export interface EvidenceNumeric {
  value: string;
  unit?: string;
  metric?: string;
  dataset?: string;
}

export interface EvidenceModel {
  id: string;
  workId: string;
  workLabel: string;
  quote: string;
  field?: string;
  evidenceType: string;
  strength: string;
  origin: string;
  authority: AuthorityLabel;
  anchor: SourceAnchorModel;
  numeric?: EvidenceNumeric;
  stale?: boolean;
}

/** How many accepted evidence relations point at a claim, by relation. */
export interface ClaimSupport {
  supports: number;
  contradicts: number;
  qualifies: number;
}

export interface ClaimModel {
  id: string;
  text: string;
  claimType: string;
  scope: string;
  status: string;
  authority: AuthorityLabel;
  support: ClaimSupport;
  stale?: boolean;
  /** The strongest wording the evidence supports, when the reviewer capped it. */
  wordingCeiling?: string;
}

export interface ProvenanceStep {
  ref: EntityRefModel;
  /** Edge label leading to this step, e.g. `supports`, `anchored_at`. */
  relation?: string;
}

export interface ProvenancePathModel {
  steps: ProvenanceStep[];
}

/** The classes a context pack budgets tokens across, in packing order. */
export const CONTEXT_CLASSES = [
  'policy',
  'accepted_state',
  'current_session',
  'prior_sessions',
  'attachments',
  'corpus_blocks',
  'discovery',
] as const;

export type ContextClass = (typeof CONTEXT_CLASSES)[number];

/** Why something the researcher might have expected was left out. */
export const OMISSION_REASONS = [
  'token_budget',
  'privacy_policy',
  'egress_blocked',
  'unsupported_media',
  'stale',
  'low_relevance',
  'unresolved_reference',
  'conflicts_with_accepted',
] as const;

export type OmissionReason = (typeof OMISSION_REASONS)[number];

export interface ContextItem {
  ref: EntityRefModel;
  cls: ContextClass;
  authority?: AuthorityLabel;
  tokens?: number;
  /** Where the packed text came from, e.g. `CS0001/messages.jsonl#M0042`. */
  sourcePointer?: string;
}

export interface OmittedContextItem extends ContextItem {
  reason: OmissionReason;
  detail?: string;
}

export interface ContextAllocation {
  cls: ContextClass;
  tokens: number;
}

/** Where a request went. `local` never leaves the machine. */
export type EgressClass = 'local' | 'external';

export interface ContextReceiptModel {
  packId: string;
  provider: string;
  model: string;
  egressClass: EgressClass;
  tokenBudget: number;
  allocation: ContextAllocation[];
  included: ContextItem[];
  omitted: OmittedContextItem[];
}

/** The decisions a review surface can offer. The host says which ones apply. */
export const REVIEW_DECISIONS = [
  'accept',
  'qualify',
  'edit',
  'reject',
  'defer',
  'request_more_evidence',
] as const;

export type ReviewDecision = (typeof REVIEW_DECISIONS)[number];

/**
 * Remembered conversation contradicting accepted state. Accepted always wins; the notice
 * exists so the researcher can see the disagreement rather than only its resolution.
 */
export interface ConflictNoticeModel {
  chat: { ref: EntityRefModel; excerpt: string };
  accepted: { ref: EntityRefModel; excerpt: string };
  explanation: string;
}

/** The Save-to-corpus lifecycle of the attachments spec §2/§6. */
export type SaveToCorpusState =
  | 'idle'
  | 'resolving'
  | 'choose_identity'
  | 'promoting'
  | 'in_corpus'
  | 'failed';

/**
 * One corpus identity the host resolved for a file. The component renders the choices and
 * reports which one the researcher picked; it never ranks or invents them.
 */
export interface IdentityChoice {
  kind: 'existing_artifact' | 'existing_work_new_version' | 'new_work';
  work?: EntityRefModel;
  version?: EntityRefModel;
  artifact?: EntityRefModel;
  label: string;
  detail?: string;
}

/* Presentation metadata ---------------------------------------------------------------- */

export interface KindMeta {
  /** Singular noun, used in a row. */
  label: string;
  /** Plural noun, used as a group heading. */
  plural: string;
  icon: IconName;
}

export const ENTITY_KIND_META: Record<EntityKind, KindMeta> = {
  work: { label: 'Work', plural: 'Works', icon: 'book-open' },
  version: { label: 'Version', plural: 'Versions', icon: 'layers' },
  artifact: { label: 'Artifact', plural: 'Artifacts', icon: 'file-text' },
  block: { label: 'Block', plural: 'Blocks', icon: 'hash' },
  evidence: { label: 'Evidence', plural: 'Evidence', icon: 'quote' },
  claim: { label: 'Claim', plural: 'Claims', icon: 'scale' },
  question: { label: 'Question', plural: 'Questions', icon: 'circle-help' },
  decision: { label: 'Decision', plural: 'Decisions', icon: 'gavel' },
  synthesis: { label: 'Synthesis', plural: 'Syntheses', icon: 'git-branch' },
  session: { label: 'Session', plural: 'Sessions', icon: 'messages-square' },
  message: { label: 'Message', plural: 'Messages', icon: 'message-square' },
  attachment: { label: 'Attachment', plural: 'Attachments', icon: 'paperclip' },
  manuscript_file: { label: 'Manuscript file', plural: 'Manuscript files', icon: 'file' },
  manuscript_anchor: { label: 'Manuscript anchor', plural: 'Manuscript anchors', icon: 'bookmark' },
};

export interface ResolutionMeta {
  /** Always rendered as text beside the glyph: resolution is never colour alone. */
  label: string;
  icon: IconName;
  description: string;
  /** `false` for the states a researcher must not silently rely on. */
  usable: boolean;
}

export const RESOLUTION_META: Record<ResolutionState, ResolutionMeta> = {
  resolved: {
    label: 'Resolved',
    icon: 'circle-check',
    description: 'This reference points at an object that exists and is readable here.',
    usable: true,
  },
  unresolved: {
    label: 'Unresolved',
    icon: 'circle-help',
    description:
      'Nothing with this id was found. The index may still be rebuilding, or the object may never have existed.',
    usable: false,
  },
  stale: {
    label: 'Stale',
    icon: 'clock',
    description: 'The object resolves, but its source moved after the anchor was recorded.',
    usable: false,
  },
  private: {
    label: 'Private',
    icon: 'lock',
    description: 'The object resolves but is private: it will not be sent to an external provider.',
    usable: false,
  },
  broken: {
    label: 'Broken',
    icon: 'link-2-off',
    description: 'This id is malformed, or it points outside this project.',
    usable: false,
  },
};

export const CONTEXT_CLASS_META: Record<ContextClass, { label: string; icon: IconName }> = {
  policy: { label: 'Policy', icon: 'shield-off' },
  accepted_state: { label: 'Accepted state', icon: 'circle-check' },
  current_session: { label: 'This session', icon: 'message-square' },
  prior_sessions: { label: 'Prior sessions', icon: 'messages-square' },
  attachments: { label: 'Attachments', icon: 'paperclip' },
  corpus_blocks: { label: 'Corpus blocks', icon: 'library' },
  discovery: { label: 'Discovery', icon: 'search' },
};

export const OMISSION_REASON_META: Record<OmissionReason, { label: string; description: string }> =
  {
    token_budget: {
      label: 'Token budget',
      description: 'The pack ran out of room before this item.',
    },
    privacy_policy: {
      label: 'Privacy policy',
      description: 'The project privacy classification kept this item local.',
    },
    egress_blocked: {
      label: 'Egress blocked',
      description: 'The egress policy refused to send this item to the selected provider.',
    },
    unsupported_media: {
      label: 'Unsupported media',
      description: 'The selected model cannot read this media type.',
    },
    stale: {
      label: 'Stale',
      description: 'The source moved under this item’s anchor, so it was not sent.',
    },
    low_relevance: {
      label: 'Low relevance',
      description: 'Retrieval scored this item below the threshold for this request.',
    },
    unresolved_reference: {
      label: 'Unresolved reference',
      description: 'The reference did not resolve, so there was nothing to send.',
    },
    conflicts_with_accepted: {
      label: 'Conflicts with accepted state',
      description: 'Accepted scientific state was sent instead of this conversational memory.',
    },
  };

export const EGRESS_META: Record<EgressClass, { label: string; icon: IconName; hint: string }> = {
  local: {
    label: 'Local',
    icon: 'hard-drive',
    hint: 'This request stayed on the machine.',
  },
  external: {
    label: 'External',
    icon: 'globe',
    hint: 'This request left the machine for the named provider.',
  },
};

export interface ReviewDecisionMeta {
  label: string;
  icon: IconName;
  /**
   * Button variant. `accept` is the primary action, and `primary` is the neutral inverse
   * fill rather than the accent or any scientific status colour: an accent that said
   * "true" would be the one thing the token contract forbids.
   *
   * `danger` is absent from this union on purpose. Every decision here is a considered,
   * recoverable record — rejecting marks the candidate reviewed and destroys nothing that
   * was accepted — so none of them may wear the colour that means "this loses work".
   */
  variant: 'primary' | 'secondary' | 'ghost';
  description: string;
}

export const REVIEW_DECISION_META: Record<ReviewDecision, ReviewDecisionMeta> = {
  accept: {
    label: 'Accept',
    icon: 'circle-check',
    variant: 'primary',
    description: 'Add this to the project’s accepted scientific state.',
  },
  qualify: {
    label: 'Qualify',
    icon: 'info',
    variant: 'secondary',
    description: 'Accept it with a stated condition or scope limit.',
  },
  edit: {
    label: 'Edit',
    icon: 'pen-line',
    variant: 'secondary',
    description: 'Change the wording before deciding.',
  },
  reject: {
    label: 'Reject',
    icon: 'circle-x',
    variant: 'secondary',
    description: 'Record that this was considered and not accepted.',
  },
  defer: {
    label: 'Defer',
    icon: 'clock',
    variant: 'ghost',
    description: 'Leave it in the queue for later.',
  },
  request_more_evidence: {
    label: 'Request more evidence',
    icon: 'search',
    variant: 'secondary',
    description: 'Send it back for a stronger source before deciding.',
  },
};

/** Formats an anchor as the one-line target a researcher reads: `A0017-3 · p.6 · B0081`. */
export function formatAnchorTarget(anchor: SourceAnchorModel): string {
  const parts: string[] = [anchor.artifactId];
  if (anchor.page !== undefined) parts.push(`p.${anchor.page}`);
  if (anchor.block !== undefined) parts.push(anchor.block);
  if (anchor.table !== undefined) parts.push(`table ${anchor.table}`);
  if (anchor.span !== undefined) parts.push(`chars ${anchor.span.start}–${anchor.span.end}`);
  return parts.join(' · ');
}

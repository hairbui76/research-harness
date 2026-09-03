import type { ReactNode } from 'react';
import type { IconName } from '../primitives/Icon';
import type { ButtonVariant } from '../primitives/Button';

/**
 * The seven presentations every asynchronous surface in the product resolves to.
 *
 * - `loading`   work is in flight and nothing is wrong;
 * - `empty`     the request succeeded and there is nothing to show;
 * - `partial`   some of the result arrived and is worth keeping;
 * - `stale`     the content is real but no longer matches its source;
 * - `blocked`   a policy or capability refuses the operation - retrying will not help;
 * - `retryable` the operation failed for a transient reason and can be attempted again;
 * - `fatal`     the operation failed and the researcher must do something else.
 */
export type AsyncStateKind =
  | 'loading'
  | 'empty'
  | 'partial'
  | 'stale'
  | 'blocked'
  | 'retryable'
  | 'fatal';

/** What happened to something the researcher cares about keeping. */
export type SafetyStatus = 'safe' | 'at-risk' | 'lost' | 'unknown';

/**
 * The sentence a researcher actually needs during a failure: is my writing still there,
 * and is the source still what I cited? Every research state answers at least one.
 */
export interface SafetyNote {
  /** The researcher's unsent message, unsaved edit or in-progress manuscript. */
  draft?: SafetyStatus;
  /** The source document, attachment or canonical corpus file. */
  source?: SafetyStatus;
  /** One more sentence, when the two statements are not specific enough. */
  note?: ReactNode;
}

/**
 * A recovery action offered by the caller. The state components never retry, reload,
 * re-anchor or recompile: they render a button and call back.
 */
export interface StateAction {
  label: string;
  onClick: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  iconStart?: IconName;
}

export interface AsyncStateMeta {
  /** Always rendered, so the state never depends on colour or an icon alone. */
  label: string;
  icon: IconName;
  /** Drives the token set used for the icon and rule. */
  tone: 'neutral' | 'info' | 'warning' | 'error';
  /** Announced assertively rather than politely. */
  urgent: boolean;
}

export const ASYNC_STATE_META: Record<AsyncStateKind, AsyncStateMeta> = {
  loading: { label: 'Loading', icon: 'loader', tone: 'neutral', urgent: false },
  empty: { label: 'Nothing here yet', icon: 'inbox', tone: 'neutral', urgent: false },
  partial: { label: 'Partial', icon: 'circle-dashed', tone: 'warning', urgent: false },
  stale: { label: 'Stale', icon: 'clock', tone: 'warning', urgent: false },
  blocked: { label: 'Blocked', icon: 'shield-off', tone: 'error', urgent: true },
  retryable: { label: 'Try again', icon: 'refresh-cw', tone: 'warning', urgent: false },
  fatal: { label: 'Failed', icon: 'alert-circle', tone: 'error', urgent: true },
};

export const SAFETY_SENTENCE: {
  draft: Record<SafetyStatus, string>;
  source: Record<SafetyStatus, string>;
} = {
  draft: {
    safe: 'Your draft is safe.',
    'at-risk': 'Your draft is not saved yet.',
    lost: 'Your draft could not be recovered.',
    unknown: 'Whether your draft was saved is unknown.',
  },
  source: {
    safe: 'The source is unchanged.',
    'at-risk': 'The source may have changed.',
    lost: 'The source is no longer available.',
    unknown: 'The state of the source is unknown.',
  },
};

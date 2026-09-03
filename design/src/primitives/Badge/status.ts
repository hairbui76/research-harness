import type { IconName } from '../Icon';

/**
 * The scientific authority vocabulary, shared with the daemon's `AuthorityLabel`.
 *
 * These six states are the only ones the Design System knows about, and they are kept
 * strictly apart from the AI/action accent: an accent-coloured thing is a model action,
 * never a statement about what is true.
 */
export const STATUS_NAMES = [
  'accepted',
  'candidate',
  'qualified',
  'contested',
  'stale',
  'private',
] as const;

export type StatusName = (typeof STATUS_NAMES)[number];

export interface StatusMeta {
  /** Default visible text. Status is never signalled by colour alone. */
  label: string;
  /** Default glyph, drawn beside the text — a second, non-colour channel. */
  icon: IconName;
  /** One line a surface can use as help text or a tooltip. */
  description: string;
}

export const STATUS_META: Record<StatusName, StatusMeta> = {
  accepted: {
    label: 'Accepted',
    icon: 'circle-check',
    description: 'Reviewed and part of the project’s accepted scientific state.',
  },
  candidate: {
    label: 'Candidate',
    icon: 'circle-dashed',
    description: 'Proposed and awaiting review. Not accepted state.',
  },
  qualified: {
    label: 'Qualified',
    icon: 'info',
    description: 'Accepted with a stated condition or scope limit.',
  },
  contested: {
    label: 'Contested',
    icon: 'alert-triangle',
    description: 'Conflicting evidence or claims are on record.',
  },
  stale: {
    label: 'Stale',
    icon: 'clock',
    description: 'The source or anchor moved since this was recorded.',
  },
  private: {
    label: 'Private',
    icon: 'lock',
    description: 'Local only. Never leaves the machine unless policy allows it.',
  },
};

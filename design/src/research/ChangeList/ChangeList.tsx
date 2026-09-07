import { forwardRef } from 'react';
import type { HTMLAttributes, MouseEvent as ReactMouseEvent } from 'react';
import { Icon } from '../../primitives/Icon';
import type { IconName } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { humaniseTerm } from '../labels';
import { ENTITY_KIND_META } from '../models';

/** The kinds of change the research surfaces record. A host may name others. */
export const CHANGE_KINDS = ['work', 'evidence', 'claim', 'decision', 'conflict'] as const;

export type ChangeKind = (typeof CHANGE_KINDS)[number];

export interface ChangeKindMeta {
  /** Always rendered as text beside the glyph: a kind is never a glyph alone. */
  label: string;
  icon: IconName;
}

/**
 * What a person reads for each kind, and the glyph beside it.
 *
 * The four that are research objects borrow the package's own glyph for that object, so a
 * Claim looks like a Claim wherever it appears; a conflict is not an object and takes the
 * comparison glyph, since a disagreement is two readings held side by side (Product 25).
 */
export const CHANGE_KIND_META: Record<ChangeKind, ChangeKindMeta> = {
  work: { label: ENTITY_KIND_META.work.label, icon: ENTITY_KIND_META.work.icon },
  evidence: { label: ENTITY_KIND_META.evidence.label, icon: ENTITY_KIND_META.evidence.icon },
  claim: { label: ENTITY_KIND_META.claim.label, icon: ENTITY_KIND_META.claim.icon },
  decision: { label: ENTITY_KIND_META.decision.label, icon: ENTITY_KIND_META.decision.icon },
  conflict: { label: 'Conflict', icon: 'git-compare' },
};

/** Who the host's record says made a change. A change it attributes to nobody has none. */
export type ChangeBy = 'researcher' | 'daemon';

/**
 * The word each actor leads their own sentence with.
 *
 * It is prose, not a label: the host's sentences are verb-initial ("accepted evidence
 * E0001…"), so the subject in front of one makes the row a sentence a person reads. Who
 * acted is never told by a colour or a chip — a returning researcher scanning for what she
 * decided has to be able to read it, in greyscale and out loud.
 */
export const CHANGE_BY_META: Record<ChangeBy, string> = {
  researcher: 'You',
  daemon: 'The daemon',
};

export interface ChangeListEntry {
  id: string;
  /** One of `CHANGE_KINDS`, or any other word the host records; unknown kinds still render. */
  kind: string;
  /**
   * Who the host's record says did it. Absent when the record attributes it to nobody, and
   * the sentence then stands on its own rather than naming a subject the host never gave.
   */
  by?: ChangeBy | undefined;
  /** The sentence the host wrote for this change. Never assembled here. */
  label: string;
  /** The instant, machine-readable: the `datetime` of the rendered `<time>`. */
  at: string;
  /** The same instant in the words a person reads. Formatted by the host, not here. */
  when: string;
  /** Where the changed object lives. Absent when the host has no screen for it. */
  href?: string;
}

export interface ChangeListProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  entries: readonly ChangeListEntry[];
  /** Accessible name for the list. Defaults to "What changed". */
  label?: string;
  /**
   * Open a change from the host's own router. The entry still renders as a real link, so
   * a middle click, a new tab and the browser's own affordances keep working.
   */
  onOpen?: (entry: ChangeListEntry) => void;
}

/**
 * What changed, newest first, in the order the host gave.
 *
 * A research log is read as prose: each row is one sentence, the moment it happened, and
 * the kind of thing that moved — never a bare timestamp beside an identifier. The list
 * sorts nothing, groups nothing and interprets nothing; ordering and wording are the
 * daemon's, because deciding what counts as a change is a research judgement and this
 * package holds none (Product 5 P10).
 *
 * The one word this package puts in front of the host's sentence is the subject of it —
 * "You", "The daemon" — for a change the host attributed to one of them. It is what lets a
 * researcher back after a week tell her own decisions from what ran while she was away, and
 * it is words rather than a tint, because that difference is the point of reading the list.
 *
 * It is an ordered list, so assistive technology reads "3 of 8" and a reader knows where
 * they are in a run of similar rows.
 */
export const ChangeList = forwardRef<HTMLOListElement, ChangeListProps>(function ChangeList(
  { entries, label = 'What changed', onOpen, className, ...rest },
  ref,
) {
  return (
    <ol ref={ref} aria-label={label} className={cx('rh-change-list', className)} {...rest}>
      {entries.map((entry) => {
        const meta = CHANGE_KIND_META[entry.kind as ChangeKind] ?? {
          label: humaniseTerm(entry.kind),
          icon: 'history' as IconName,
        };
        const handleClick = (event: ReactMouseEvent<HTMLAnchorElement>): void => {
          if (onOpen === undefined) return;
          event.preventDefault();
          onOpen(entry);
        };
        return (
          <li
            key={entry.id}
            className="rh-change-list__entry"
            data-kind={entry.kind}
            {...(entry.by ? { 'data-by': entry.by } : {})}
          >
            <span className="rh-change-list__kind">
              <Icon name={meta.icon} size={14} />
              <span>{meta.label}</span>
            </span>
            <p className="rh-change-list__what">
              {entry.by ? (
                <>
                  <span className="rh-change-list__by">{CHANGE_BY_META[entry.by]}</span>{' '}
                </>
              ) : null}
              {entry.href === undefined ? (
                entry.label
              ) : (
                <a className="rh-change-list__link" href={entry.href} onClick={handleClick}>
                  {entry.label}
                </a>
              )}
            </p>
            <time className="rh-change-list__when" dateTime={entry.at}>
              {entry.when}
            </time>
          </li>
        );
      })}
    </ol>
  );
});

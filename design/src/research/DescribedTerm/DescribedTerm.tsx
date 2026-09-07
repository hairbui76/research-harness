import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { useId } from '../../hooks/useId';
import { cx } from '../../utils/cx';

export interface DescribedTermProps {
  /** The word a person reads. Never an identifier. */
  children: ReactNode;
  /** The one line the product states about it. */
  description: ReactNode;
  className?: string;
}

/**
 * One word of a controlled vocabulary, with its meaning on the page.
 *
 * `AuthorityBadge` already does this for the six scientific authorities and
 * `ReviewDecisionBar` for the six review decisions: the word takes a tab stop, is
 * `aria-describedby` its own sentence, and prints that sentence underneath while it has
 * focus. This is the same act for a word that is not a badge and not a button — a `<dd>`
 * under a `<dt>`, the tier beside a queue row — so that the review screen explains
 * "Tier 2 — deep review", "Source observed" and "Direct" the way it already explains
 * Candidate and Contested, rather than in a second shape a reader has to learn.
 *
 * Focus, and not hover, is what opens it, for the reason the badge gives: these words sit
 * in rows beside links, and a sentence that appeared under one as the pointer crossed it
 * would move those links out from under the pointer. The sentence is in flow rather than
 * an overlay, so a scrolling pane cannot clip it, and it is never a `title` — which
 * reaches neither the keyboard nor touch.
 *
 * A word the product says nothing about does not come here at all: the caller renders it
 * plainly rather than offering a tab stop that leads to nothing.
 */
export function DescribedTerm({ children, description, className }: DescribedTermProps) {
  const term = useDescribedTerm(description);

  return (
    <span className={cx('rh-described-term', className)}>
      <span className="rh-described-term__word" {...term.word}>
        {children}
      </span>
      {term.named}
      {term.hint}
    </span>
  );
}

/** What a caller needs to draw a described term itself. */
export interface DescribedTermParts {
  /** Whether the sentence is on show for the eye right now. */
  shown: boolean;
  /** Spread on the word: a tab stop that names its own sentence. Empty without one. */
  word: {
    tabIndex?: number;
    'aria-describedby'?: string;
    onFocus?: () => void;
    onBlur?: () => void;
  };
  /** The named half, for assistive technology. Render it wherever; the id is what binds. */
  named: ReactElement | null;
  /** The visible half while the word has focus, or null. */
  hint: ReactElement | null;
}

/**
 * The same act as `DescribedTerm`, with the two halves handed back separately.
 *
 * `DescribedTerm` puts the sentence directly under the word, which is right where the word
 * sits in a sentence or a row: the meaning appears where the eye already is. It is wrong
 * inside a grid of terms, where a sentence opening under one column widens that column and
 * re-wraps the row, moving the terms beside it — and those terms are the next tab stops.
 * A caller in that position places the sentence itself, on a row of its own beneath the
 * terms, and uses this to keep the wiring: one tab stop, one `aria-describedby`, one
 * sentence heard once and seen once.
 *
 * A term the product says nothing about gets nothing back: no tab stop, no sentence.
 */
export function useDescribedTerm(description: ReactNode | undefined): DescribedTermParts {
  const descriptionId = useId(undefined, 'rh-described-term');
  const [shown, setShown] = useState(false);
  if (description === undefined) return { shown: false, word: {}, named: null, hint: null };

  return {
    shown,
    word: {
      tabIndex: 0,
      'aria-describedby': descriptionId,
      onFocus: () => setShown(true),
      onBlur: () => setShown(false),
    },
    named: (
      // The named half, for assistive technology.
      <span id={descriptionId} className="rh-visually-hidden">
        {description}
      </span>
    ),
    // The visible half is the same sentence, so it is hidden from assistive technology:
    // hearing the meaning twice is worse than hearing it once.
    hint: shown ? (
      <span className="rh-described-term__hint" aria-hidden="true">
        {description}
      </span>
    ) : null,
  };
}

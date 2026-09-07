import { useState } from 'react';
import type { ReactNode } from 'react';
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
  const descriptionId = useId(undefined, 'rh-described-term');
  const [shown, setShown] = useState(false);

  return (
    <span className={cx('rh-described-term', className)}>
      <span
        className="rh-described-term__word"
        tabIndex={0}
        aria-describedby={descriptionId}
        onFocus={() => setShown(true)}
        onBlur={() => setShown(false)}
      >
        {children}
      </span>
      {/* The named half, for assistive technology. */}
      <span id={descriptionId} className="rh-visually-hidden">
        {description}
      </span>
      {/* The visible half is the same sentence, so it is hidden from assistive technology:
          hearing the meaning twice is worse than hearing it once. */}
      {shown ? (
        <span className="rh-described-term__hint" aria-hidden="true">
          {description}
        </span>
      ) : null}
    </span>
  );
}

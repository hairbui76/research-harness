import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent, ReactElement, ReactNode } from 'react';
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
 * How long a pointer has to rest on a word before its meaning opens.
 *
 * Long enough that a pointer crossing the row on its way to a link opens nothing — which
 * is the whole of wave two's objection — and short enough that resting on a word you do
 * not know answers before you reach for the keyboard. It is an intent delay and not a
 * transition: nothing animates, so this is not a third motion duration.
 */
export const DESCRIBED_TERM_HOVER_MS = 400;

/**
 * How long a finger has to hold the word.
 *
 * Long-press is the touch gesture for "what is this?", and it is the only one available:
 * a finger cannot hover and a touch device has no `title`. The press focuses the word, so
 * the sentence stays on the page after the finger lifts and the keyboard is where the
 * touch was.
 */
export const DESCRIBED_TERM_PRESS_MS = 500;

/**
 * One word of a controlled vocabulary, with its meaning on the page.
 *
 * `AuthorityBadge` already does this for the six scientific authorities and
 * `ReviewDecisionBar` for the six review decisions: the word takes a tab stop, is
 * `aria-describedby` its own sentence, and prints that sentence underneath. This is the
 * same act for a word that is not a badge and not a button — a `<dd>` under a `<dt>`, the
 * tier beside a queue row — so that the review screen explains "Tier 2 — deep review",
 * "Source observed" and "Direct" the way it already explains Candidate and Contested,
 * rather than in a second shape a reader has to learn.
 *
 * Three gestures open it and they open the same sentence: focus, a pointer that rests on
 * the word, and a long press. Wave two allowed only focus, because a sentence that
 * appeared under a badge the instant a pointer crossed it moved the row's links out from
 * under the pointer — but the cost was that a mouse never learned what `Candidate` meant.
 * What answers both is the delay and the slot: the pointer has to stay
 * ({@link DESCRIBED_TERM_HOVER_MS}ms) rather than pass, and the sentence is printed where
 * it cannot reflow the row it belongs to. A pointer needs to see that there is something
 * to ask, too, so the word wears a dotted underline in its own ink and a `help` cursor.
 *
 * The sentence is in flow rather than an overlay, so a scrolling pane cannot clip it, and
 * it is never a `title` — which reaches neither the keyboard nor touch.
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

/** Everything spread on the word: a tab stop that names its own sentence, and the gestures. */
export interface DescribedTermWordProps {
  tabIndex?: number;
  'aria-describedby'?: string;
  onFocus?: () => void;
  onBlur?: () => void;
  onPointerEnter?: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerLeave?: () => void;
  onPointerDown?: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerUp?: () => void;
  onPointerCancel?: () => void;
}

/** What a caller needs to draw a described term itself. */
export interface DescribedTermParts {
  /** Whether the sentence is on show for the eye right now. */
  shown: boolean;
  /** Spread on the word: a tab stop that names its own sentence. Empty without one. */
  word: DescribedTermWordProps;
  /** The named half, for assistive technology. Render it wherever; the id is what binds. */
  named: ReactElement | null;
  /** The visible half while the word is being asked about, or null. */
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
  const [focused, setFocused] = useState(false);
  const [rested, setRested] = useState(false);
  const waiting = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const stopWaiting = useCallback(() => {
    if (waiting.current === undefined) return;
    clearTimeout(waiting.current);
    waiting.current = undefined;
  }, []);

  // A word can be unmounted — a queue re-reads, a row is filtered away — while a pointer
  // is still resting on it, so the timer has to go with it.
  useEffect(() => stopWaiting, [stopWaiting]);

  const waitThen = useCallback(
    (delay: number, act: () => void) => {
      stopWaiting();
      waiting.current = setTimeout(() => {
        waiting.current = undefined;
        act();
      }, delay);
    },
    [stopWaiting],
  );

  if (description === undefined) return { shown: false, word: {}, named: null, hint: null };

  return {
    shown: focused || rested,
    word: {
      tabIndex: 0,
      'aria-describedby': descriptionId,
      onFocus: () => setFocused(true),
      onBlur: () => setFocused(false),
      // A pointer that rests opens the sentence; one that is only crossing the row on its
      // way to a link leaves before the delay is up and opens nothing.
      onPointerEnter: (event) => {
        if (event.pointerType === 'touch' || event.pointerType === 'pen') return;
        waitThen(DESCRIBED_TERM_HOVER_MS, () => setRested(true));
      },
      onPointerLeave: () => {
        stopWaiting();
        setRested(false);
      },
      // A long press focuses the word rather than showing the sentence directly, so that a
      // finger and a Tab key leave the page in exactly the same state.
      onPointerDown: (event) => {
        if (event.pointerType !== 'touch' && event.pointerType !== 'pen') return;
        const word = event.currentTarget;
        waitThen(DESCRIBED_TERM_PRESS_MS, () => word.focus());
      },
      onPointerUp: stopWaiting,
      onPointerCancel: stopWaiting,
    },
    named: (
      // The named half, for assistive technology.
      <span id={descriptionId} className="rh-visually-hidden">
        {description}
      </span>
    ),
    // The visible half is the same sentence, so it is hidden from assistive technology:
    // hearing the meaning twice is worse than hearing it once.
    hint: focused || rested ? (
      <span className="rh-described-term__hint" aria-hidden="true">
        {description}
      </span>
    ) : null,
  };
}

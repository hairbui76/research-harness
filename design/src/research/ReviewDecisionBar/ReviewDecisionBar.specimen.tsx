import type { ReactNode } from 'react';
import { REVIEW_DECISIONS } from '../models';
import { ReviewDecisionBar } from './ReviewDecisionBar';

export const title = 'ReviewDecisionBar';

/*
 * Two things to look at here, both of them decisions rather than defaults.
 *
 * No button is `danger`. Rejecting records that a candidate was considered and not
 * accepted; it destroys nothing that was accepted, and colouring it as destruction told
 * the reviewer the opposite of the truth. Accept keeps the neutral `primary` fill — never
 * the accent, and never a scientific status colour, because the accent must not say
 * whether a claim is true. What makes acceptance weighty is the confirmation the review
 * surface asks for, not the hue of the button.
 *
 * Point at or tab to any decision and its meaning appears under the bar. The same sentence
 * is the button's accessible description, so the keyboard, touch and a screen reader all
 * reach what used to live in a `title` attribute.
 */
export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Every decision — hover or focus one to read what it records',
    render: () => <ReviewDecisionBar available={REVIEW_DECISIONS} onDecide={() => undefined} />,
  },
  {
    name: 'A narrower set',
    render: () => (
      <ReviewDecisionBar available={['accept', 'reject', 'defer']} onDecide={() => undefined} />
    ),
  },
  {
    name: 'Recording a decision',
    render: () => (
      <ReviewDecisionBar
        available={['accept', 'qualify', 'reject']}
        busy="accept"
        onDecide={() => undefined}
      />
    ),
  },
  {
    name: 'Read-only host — the reason is on the page',
    render: () => (
      <ReviewDecisionBar
        available={REVIEW_DECISIONS}
        disabledReason="This workspace is open read-only, so no decision can be recorded here."
        onDecide={() => undefined}
      />
    ),
  },
];

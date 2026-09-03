import type { ReactNode } from 'react';
import { REVIEW_DECISIONS } from '../models';
import { ReviewDecisionBar } from './ReviewDecisionBar';

export const title = 'ReviewDecisionBar';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Every decision',
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

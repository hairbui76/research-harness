import type { ReactNode } from 'react';
import { ReviewDecisionBar } from '../ReviewDecisionBar';
import { SAMPLE_CLAIM } from '../samples';
import { ClaimCard } from './ClaimCard';

export const title = 'ClaimCard';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Qualified claim with a wording ceiling',
    render: () => <ClaimCard claim={SAMPLE_CLAIM} onOpenSupport={() => undefined} />,
  },
  {
    name: 'Accepted, with no contradicting evidence',
    render: () => (
      <ClaimCard
        claim={{
          ...SAMPLE_CLAIM,
          id: 'C0012',
          authority: 'accepted',
          status: 'accepted',
          support: { supports: 6, contradicts: 0, qualifies: 0 },
          wordingCeiling: undefined,
        }}
      />
    ),
  },
  {
    name: 'Contested',
    render: () => (
      <ClaimCard
        claim={{
          ...SAMPLE_CLAIM,
          id: 'C0058',
          authority: 'contested',
          status: 'contested',
          support: { supports: 3, contradicts: 4, qualifies: 1 },
        }}
      />
    ),
  },
  {
    name: 'Candidate, in review',
    render: () => (
      <ClaimCard
        claim={{ ...SAMPLE_CLAIM, id: 'C0102', authority: 'candidate', status: 'proposed' }}
        actions={
          <ReviewDecisionBar available={['accept', 'qualify', 'edit', 'reject']} onDecide={() => undefined} />
        }
      />
    ),
  },
];

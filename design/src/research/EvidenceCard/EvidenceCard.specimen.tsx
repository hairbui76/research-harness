import type { ReactNode } from 'react';
import { ReviewDecisionBar } from '../ReviewDecisionBar';
import { SAMPLE_EVIDENCE, SAMPLE_STALE_ANCHOR } from '../samples';
import { EvidenceCard } from './EvidenceCard';

export const title = 'EvidenceCard';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Accepted evidence',
    render: () => <EvidenceCard evidence={SAMPLE_EVIDENCE} onOpenAnchor={() => undefined} />,
  },
  {
    name: 'Candidate, awaiting review',
    render: () => (
      <EvidenceCard
        evidence={{ ...SAMPLE_EVIDENCE, id: 'E0511', authority: 'candidate', origin: 'model' }}
        actions={
          <ReviewDecisionBar
            available={['accept', 'qualify', 'reject', 'request_more_evidence']}
            onDecide={() => undefined}
          />
        }
      />
    ),
  },
  {
    name: 'Stale anchor',
    render: () => (
      <EvidenceCard evidence={{ ...SAMPLE_EVIDENCE, anchor: SAMPLE_STALE_ANCHOR, stale: true }} />
    ),
  },
  {
    name: 'Compact, for a review queue',
    render: () => <EvidenceCard evidence={SAMPLE_EVIDENCE} compact />,
  },
];

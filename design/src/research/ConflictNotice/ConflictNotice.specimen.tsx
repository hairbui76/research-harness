import type { ReactNode } from 'react';
import { SAMPLE_CONFLICT } from '../samples';
import { ConflictNotice } from './ConflictNotice';

export const title = 'ConflictNotice';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Accepted state outranks remembered chat',
    render: () => <ConflictNotice conflict={SAMPLE_CONFLICT} onOpen={() => undefined} />,
  },
  {
    name: 'A decision, not a claim',
    render: () => (
      <ConflictNotice
        title="An accepted decision was used"
        conflict={{
          ...SAMPLE_CONFLICT,
          accepted: {
            ref: {
              id: 'D0003',
              kind: 'decision',
              label: 'Exclude 2D cultures from the meta-analysis',
              authority: 'accepted',
              resolution: 'resolved',
            },
            excerpt: 'Only 3D cultures enter the pooled estimate.',
          },
          explanation:
            'A message in this session assumed 2D cultures were included. The accepted decision says otherwise and was sent instead.',
        }}
        onOpen={() => undefined}
      />
    ),
  },
];

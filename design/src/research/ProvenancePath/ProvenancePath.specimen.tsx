import type { ReactNode } from 'react';
import { SAMPLE_PROVENANCE, SAMPLE_UNRESOLVED_REF } from '../samples';
import { ProvenancePath } from './ProvenancePath';

export const title = 'ProvenancePath';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Claim → Evidence → Artifact',
    render: () => <ProvenancePath path={SAMPLE_PROVENANCE} onOpen={() => undefined} />,
  },
  {
    name: 'Vertical, for a narrow inspector',
    render: () => (
      <div style={{ maxWidth: 260 }}>
        <ProvenancePath path={SAMPLE_PROVENANCE} orientation="vertical" onOpen={() => undefined} />
      </div>
    ),
  },
  {
    name: 'A chain that breaks in the middle',
    render: () => (
      <ProvenancePath
        path={{
          steps: [
            SAMPLE_PROVENANCE.steps[0] ?? { ref: SAMPLE_UNRESOLVED_REF },
            { ref: SAMPLE_UNRESOLVED_REF, relation: 'supports' },
            SAMPLE_PROVENANCE.steps[2] ?? { ref: SAMPLE_UNRESOLVED_REF },
          ],
        }}
        onOpen={() => undefined}
      />
    ),
  },
];

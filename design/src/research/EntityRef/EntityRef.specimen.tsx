import type { ReactNode } from 'react';
import {
  SAMPLE_BROKEN_REF,
  SAMPLE_CLAIM_REF,
  SAMPLE_EVIDENCE_REF,
  SAMPLE_PRIVATE_REF,
  SAMPLE_STALE_REF,
  SAMPLE_UNRESOLVED_REF,
  SAMPLE_WORK,
} from '../samples';
import { EntityRef } from './EntityRef';

export const title = 'EntityRef';

const row = { display: 'flex', flexWrap: 'wrap' as const, gap: 8, alignItems: 'center' };

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Resolved references',
    render: () => (
      <div style={row}>
        <EntityRef entity={SAMPLE_WORK} onOpen={() => undefined} />
        <EntityRef entity={SAMPLE_EVIDENCE_REF} onOpen={() => undefined} />
        <EntityRef entity={SAMPLE_CLAIM_REF} onOpen={() => undefined} />
      </div>
    ),
  },
  {
    name: 'Every resolution state, marked in words',
    render: () => (
      <div style={row}>
        <EntityRef entity={SAMPLE_STALE_REF} onOpen={() => undefined} />
        <EntityRef entity={SAMPLE_PRIVATE_REF} onOpen={() => undefined} />
        <EntityRef entity={SAMPLE_UNRESOLVED_REF} onOpen={() => undefined} />
        <EntityRef entity={SAMPLE_BROKEN_REF} onOpen={() => undefined} />
      </div>
    ),
  },
  {
    name: 'Inline in prose',
    render: () => (
      <p style={{ maxWidth: '38rem' }}>
        The measurement in <EntityRef entity={SAMPLE_EVIDENCE_REF} size="sm" showAuthority={false} />{' '}
        supports the weaker wording of{' '}
        <EntityRef entity={SAMPLE_CLAIM_REF} size="sm" showAuthority={false} />, but the anchor in{' '}
        <EntityRef entity={SAMPLE_STALE_REF} size="sm" showAuthority={false} /> moved.
      </p>
    ),
  },
  {
    name: 'Static, with nothing to open',
    render: () => <EntityRef entity={SAMPLE_CLAIM_REF} />,
  },
];

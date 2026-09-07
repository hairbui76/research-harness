import type { ReactNode } from 'react';
import { AUTHORITY_LABELS } from '../models';
import { AuthorityBadge } from './AuthorityBadge';

export const title = 'AuthorityBadge';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Every authority',
    render: () => (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {AUTHORITY_LABELS.map((authority) => (
          <AuthorityBadge key={authority} authority={authority} />
        ))}
      </div>
    ),
  },
  {
    name: 'Small, for dense rows',
    render: () => (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {AUTHORITY_LABELS.map((authority) => (
          <AuthorityBadge key={authority} authority={authority} size="sm" />
        ))}
      </div>
    ),
  },
  {
    name: 'With its own wording, and its meaning on focus or hover',
    render: () => (
      <AuthorityBadge
        authority="qualified"
        label="Accepted for 3D cultures"
        describe
        reason="The reviewer limited the scope to 3D cultures."
      />
    ),
  },
];

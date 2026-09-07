import type { ReactNode } from 'react';
import { ChangeList } from './ChangeList';
import type { ChangeListEntry } from './ChangeList';

export const title = 'ChangeList';

const SINCE_LAST_SESSION: ChangeListEntry[] = [
  {
    id: 'conflict.opened',
    kind: 'conflict',
    label:
      'Conflict opened: the staged storage modulus differs from the accepted reading of Table 1',
    at: '2026-09-06T16:41:00+00:00',
    when: '6 September, 16:41',
    href: '/conflicts',
  },
  {
    id: 'decision.accepted',
    kind: 'decision',
    label: 'accepted D0002: count only held-out splits',
    at: '2026-09-06T14:03:00+00:00',
    when: '6 September, 14:03',
  },
  {
    id: 'claim.audited',
    kind: 'claim',
    label: 'audited C0041: qualified at L1 observed subset',
    at: '2026-09-06T13:58:00+00:00',
    when: '6 September, 13:58',
    href: '/claims/C0041',
  },
  {
    id: 'evidence.accepted',
    kind: 'evidence',
    label: 'accepted evidence E0482 anchored in A0017-3',
    at: '2026-09-06T11:20:00+00:00',
    when: '6 September, 11:20',
    href: '/evidence/E0482',
  },
  {
    id: 'work.ingested',
    kind: 'work',
    label: 'registered W0017 from hydrogel-stiffness-neurites.pdf',
    at: '2026-09-05T09:12:00+00:00',
    when: '5 September, 09:12',
    href: '/corpus/W0017',
  },
];

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'What changed since the last session',
    render: () => <ChangeList entries={SINCE_LAST_SESSION} onOpen={() => undefined} />,
  },
  {
    name: 'One change, in a narrow pane',
    render: () => (
      <div style={{ maxWidth: 300 }}>
        <ChangeList entries={SINCE_LAST_SESSION.slice(0, 1)} onOpen={() => undefined} />
      </div>
    ),
  },
  {
    name: 'A kind the package has never heard of',
    render: () => (
      <ChangeList
        entries={[
          {
            id: 'taxonomy.revised',
            kind: 'taxonomy_revision',
            label: 'revised the transport taxonomy under D0003',
            at: '2026-09-06T08:00:00+00:00',
            when: '6 September, 08:00',
          },
        ]}
      />
    ),
  },
];

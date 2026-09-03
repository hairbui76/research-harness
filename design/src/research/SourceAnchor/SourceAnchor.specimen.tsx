import type { ReactNode } from 'react';
import { SAMPLE_ANCHOR, SAMPLE_STALE_ANCHOR } from '../samples';
import { SourceAnchor } from './SourceAnchor';

export const title = 'SourceAnchor';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Inline target',
    render: () => <SourceAnchor anchor={SAMPLE_ANCHOR} onOpen={() => undefined} />,
  },
  {
    name: 'With the quote',
    render: () => (
      <SourceAnchor anchor={SAMPLE_ANCHOR} variant="block" onOpen={() => undefined} />
    ),
  },
  {
    name: 'Stale — the document moved under the anchor',
    render: () => (
      <SourceAnchor anchor={SAMPLE_STALE_ANCHOR} variant="block" onOpen={() => undefined} />
    ),
  },
  {
    name: 'A table cell, and a character span',
    render: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <SourceAnchor anchor={{ artifactId: 'A0021-1', page: 4, table: 'T2' }} />
        <SourceAnchor anchor={{ artifactId: 'A0021-1', span: { start: 88, end: 140 } }} />
      </div>
    ),
  },
];

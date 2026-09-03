import type { ReactElement, ReactNode } from 'react';
import { ResearchInspector } from './ResearchInspector';
import { Badge } from '../../primitives/Badge';

function framed(node: ReactNode): ReactElement {
  return (
    <div
      style={{
        inlineSize: '100%',
        blockSize: '26rem',
        border: '1px solid var(--rh-border-subtle)',
        borderRadius: 'var(--rh-radius-card)',
        overflow: 'hidden',
      }}
    >
      {node}
    </div>
  );
}

const panels = {
  context: (
    <div style={{ display: 'grid', gap: 'var(--rh-space-2)' }}>
      <p style={{ margin: 0 }}>Context pack CP0007 — 9 items included, 2 omitted.</p>
      <p style={{ margin: 0, color: 'var(--rh-text-muted)' }}>
        Omitted: one private prior-session excerpt (egress policy), one corpus block (token
        budget).
      </p>
    </div>
  ),
  evidence: (
    <div style={{ display: 'grid', gap: 'var(--rh-space-2)' }}>
      <p style={{ margin: 0 }}>
        <Badge status="accepted" size="sm" /> E0482 — thermal maxima table, A0017-3 p.6
      </p>
      <p style={{ margin: 0 }}>
        <Badge status="qualified" size="sm" /> E0501 — one dataset only
      </p>
    </div>
  ),
  claims: (
    <p style={{ margin: 0 }}>
      <Badge status="candidate" size="sm" /> C0041 — tolerance rises with acclimation
    </p>
  ),
};

export const title = 'ResearchInspector';

export const specimens = [
  {
    name: 'Following a reference',
    render: () =>
      framed(
        <ResearchInspector
          counts={{ context: 9, evidence: 2, claims: 1, review: 4, conflicts: 1, stale: 3 }}
          selection={{
            kind: 'reference',
            label: 'E0482',
            detail: 'Cited in M0042',
            ref: { kind: 'evidence', id: 'E0482', href: 'rh://evidence/E0482' },
          }}
          panels={panels}
          onNavigate={() => undefined}
          onFollow={() => undefined}
        />,
      ),
  },
  {
    name: 'Following a message, not following',
    render: () =>
      framed(
        <ResearchInspector
          defaultTab="evidence"
          counts={{ evidence: 2 }}
          following={false}
          selection={{
            kind: 'message',
            label: 'M0042',
            detail: 'assistant, 10:02',
            ref: { kind: 'message', id: 'M0042' },
          }}
          panels={panels}
          onNavigate={() => undefined}
          onFollow={() => undefined}
        />,
      ),
  },
  {
    name: 'Nothing selected',
    render: () => framed(<ResearchInspector />),
  },
];

import type { ReactElement, ReactNode } from 'react';
import { ConversationWorkspace } from './ConversationWorkspace';
import { ProjectRail } from '../ProjectRail';
import { ResearchInspector } from '../ResearchInspector';
import {
  Composer,
  SessionList,
  Transcript,
  project,
  projects,
  providerOk,
  railItems,
} from '../workspace.specimen-data';

function framed(node: ReactNode): ReactElement {
  return (
    <div
      className="gallery-block"
      style={{
        blockSize: '34rem',
        border: '1px solid var(--rh-border-subtle)',
        borderRadius: 'var(--rh-radius-card)',
        overflow: 'hidden',
      }}
    >
      {node}
    </div>
  );
}

const rail = (
  <ProjectRail
    project={project}
    projects={projects}
    onSelectProject={() => undefined}
    onNewSession={() => undefined}
    sessionList={<SessionList />}
    items={railItems.slice(0, 5)}
    onNavigate={() => undefined}
    onOpenSettings={() => undefined}
    providerStatus={providerOk}
  />
);

const inspector = (
  <ResearchInspector
    counts={{ context: 9, evidence: 2, review: 4 }}
    selection={{
      kind: 'reference',
      label: 'E0482',
      detail: 'Cited in M0042',
      ref: { kind: 'evidence', id: 'E0482' },
    }}
    panels={{ context: <p style={{ margin: 0 }}>CP0007 — 9 in, 2 out.</p> }}
    onNavigate={() => undefined}
    onFollow={() => undefined}
  />
);

export const title = 'ConversationWorkspace';

export const specimens = [
  {
    name: 'Three panes — rail, transcript with composer, inspector',
    render: () =>
      framed(
        <ConversationWorkspace
          rail={rail}
          transcript={<Transcript />}
          composer={<Composer />}
          inspector={inspector}
          toolbar={
            <span style={{ fontFamily: 'var(--rh-font-mono)', fontSize: 'var(--rh-type-mono-size)', color: 'var(--rh-text-muted)' }}>
              CS0003 · Acclimation window
            </span>
          }
        />,
      ),
  },
  {
    name: 'Inspector collapsed',
    render: () =>
      framed(
        <ConversationWorkspace
          rail={rail}
          transcript={<Transcript />}
          composer={<Composer />}
          inspector={inspector}
          defaultInspectorOpen={false}
        />,
      ),
  },
  {
    name: 'Without a rail — inside an AppShell that already supplies one',
    render: () =>
      framed(
        <ConversationWorkspace
          transcript={<Transcript />}
          composer={<Composer />}
          inspector={inspector}
        />,
      ),
  },
];

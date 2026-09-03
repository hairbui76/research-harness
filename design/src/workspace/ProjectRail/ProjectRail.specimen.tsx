import type { ReactElement, ReactNode } from 'react';
import { ProjectRail } from './ProjectRail';
import {
  SessionList,
  project,
  projects,
  providerOffline,
  providerOk,
  railItems,
} from '../workspace.specimen-data';

function framed(node: ReactNode): ReactElement {
  return (
    <div
      style={{
        blockSize: '32rem',
        border: '1px solid var(--rh-border-subtle)',
        borderRadius: 'var(--rh-radius-card)',
        overflow: 'hidden',
      }}
    >
      {node}
    </div>
  );
}

export const title = 'ProjectRail';

export const specimens = [
  {
    name: 'Expanded',
    render: () =>
      framed(
        <ProjectRail
          project={project}
          projects={projects}
          onSelectProject={() => undefined}
          onNewSession={() => undefined}
          sessionList={<SessionList />}
          items={railItems}
          onNavigate={() => undefined}
          onOpenSettings={() => undefined}
          providerStatus={providerOk}
        />,
      ),
  },
  {
    name: 'Collapsed to icons — every label survives as a tooltip and an accessible name',
    render: () =>
      framed(
        <ProjectRail
          project={project}
          projects={projects}
          defaultCollapsed
          onNewSession={() => undefined}
          items={railItems}
          onNavigate={() => undefined}
          onOpenSettings={() => undefined}
          providerStatus={providerOk}
        />,
      ),
  },
  {
    name: 'Provider offline',
    render: () =>
      framed(
        <ProjectRail
          project={project}
          onNewSession={() => undefined}
          items={railItems.slice(0, 4)}
          onNavigate={() => undefined}
          onOpenSettings={() => undefined}
          providerStatus={providerOffline}
        />,
      ),
  },
];

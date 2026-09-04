import type { ReactElement, ReactNode } from 'react';
import { ProjectRail } from './ProjectRail';
import type { ProjectModel } from '../models';
import {
  SessionList,
  project,
  projects,
  providerOffline,
  providerOk,
  railItems,
} from '../workspace.specimen-data';

/** A registry with something wrong in it: the states the rail has to say out loud. */
const mixedProjects: ProjectModel[] = [
  { ...project, activeRuns: 2 },
  {
    id: 'P2',
    name: 'Reef survey',
    availability: 'unavailable',
    detail: 'Folder not found',
  },
  {
    id: 'P3',
    name: 'Kelp forest',
    path: '/home/researcher/projects/kelp',
    availability: 'busy',
    detail: 'Another window holds the lock',
  },
  {
    id: 'P4',
    name: 'Larval dispersal',
    path: '/home/researcher/projects/larval',
    availability: 'incompatible',
    detail: 'Written by a newer schema',
  },
];

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
    name: 'Multi-project — availability and background work are stated as text; open the switcher for the rest',
    render: () =>
      framed(
        <ProjectRail
          project={mixedProjects[0] as ProjectModel}
          projects={mixedProjects}
          onSelectProject={() => undefined}
          onAddProject={() => undefined}
          onOpenProjectHome={() => undefined}
          onProjectAction={() => undefined}
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
    name: 'Unavailable project — the open project cannot be reached, and Locate is one menu away',
    render: () =>
      framed(
        <ProjectRail
          project={mixedProjects[1] as ProjectModel}
          projects={mixedProjects}
          onSelectProject={() => undefined}
          onAddProject={() => undefined}
          onOpenProjectHome={() => undefined}
          onProjectAction={() => undefined}
          items={railItems.slice(0, 4)}
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

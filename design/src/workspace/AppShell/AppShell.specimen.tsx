import { useState } from 'react';
import type { ReactElement } from 'react';
import { AppShell } from './AppShell';
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
    counts={{ context: 9, review: 4 }}
    panels={{ context: <p style={{ margin: 0 }}>CP0007 — 9 in, 2 out.</p> }}
  />
);

function Shell({ narrow }: { narrow: boolean }): ReactElement {
  const [railOpen, setRailOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(!narrow);
  return (
    <div
      className="gallery-block"
      style={{
        blockSize: '32rem',
        border: '1px solid var(--rh-border-subtle)',
        borderRadius: 'var(--rh-radius-card)',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <AppShell
        narrow={narrow}
        // The narrow bar is the only place these two are readable once the rail is a
        // drawer, so the specimen passes what the cockpit passes: the open project, and
        // the destination in the navigation's own words.
        barTitle={project.name}
        pageLabel="Conversation"
        rail={rail}
        main={
          <>
            <div style={{ flex: '1 1 auto', minBlockSize: 0, overflow: 'auto' }}>
              <Transcript />
            </div>
            <Composer />
          </>
        }
        inspector={inspector}
        railOpen={railOpen}
        onRailOpenChange={setRailOpen}
        inspectorOpen={inspectorOpen}
        onInspectorOpenChange={setInspectorOpen}
      />
    </div>
  );
}

export const title = 'AppShell';

export const specimens = [
  {
    name: 'Wide — rail, main, inspector',
    render: () => <Shell narrow={false} />,
  },
  {
    name: 'Narrow — the side panes become drawers, the draft stays mounted',
    render: () => <Shell narrow />,
  },
];

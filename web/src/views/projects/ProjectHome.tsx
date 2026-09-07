/**
 * Project Home: every workspace this machine has been shown, and nothing else.
 *
 * It is the one screen that exists before a workspace does, so it draws itself rather than
 * the cockpit shell. What it shows per row is fixed by spec §4.2 — name, folder, when it
 * was last opened, whether it can be opened, and whether anything is still running in it —
 * and every one of those is text, never colour alone.
 *
 * The judgement about a folder belongs to the host, not to this file. `availability` is
 * what the control plane said a moment ago; this screen only decides what a researcher may
 * press. Unavailable, invalid and incompatible projects cannot be opened and say why in the
 * host's own words; an unavailable one is offered Locate, because a moved folder is the one
 * failure the researcher can fix from here. A busy project stays openable: a lock somewhere
 * in it is not a reason to lock the researcher out of reading it (spec §10).
 *
 * Nothing on this screen deletes anything. Forget removes a row from a list.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AsyncState,
  Badge,
  Button,
  Card,
  ErrorNotice,
  Icon,
  Menu,
  PROJECT_AVAILABILITY_META,
  formatTimestamp,
} from '@research-harness/design';
import type { BadgeTone, IconName, ProjectAction } from '@research-harness/design';
import type { ProjectAvailability, ProjectView } from '../../api/projects';
import { APP_TOKEN_MISSING_EXPLANATION, useHost } from '../../app/host';
import { projectHref } from '../../app/projectPaths';
import { ProjectDialogs, describeCause, useProjectLifecycle } from './ProjectDialogs';
import type { ProjectDialog } from './ProjectDialogs';
import './projects.css';

/** The availabilities a researcher may open a workspace in. A lock is not a wall. */
const OPENABLE: readonly ProjectAvailability[] = ['available', 'busy'];

/**
 * The lifecycle actions, in the rail's order and the rail's words.
 *
 * The rail keeps these four behind one "Project actions" menu; this screen used to spread
 * an overlapping subset across five flat buttons, in another order, under shorter verbs.
 * A researcher should not have to learn the vocabulary twice, so this list mirrors
 * `PROJECT_ACTIONS` in the Design System's `ProjectRail` exactly, and `browser-tests/
 * layout.spec.ts` compares the two on screen so the copies cannot drift apart.
 */
const PROJECT_ACTION_ITEMS: readonly { action: ProjectAction; label: string; icon: IconName }[] = [
  { action: 'reveal', label: 'Show in file manager', icon: 'folder-open' },
  { action: 'locate', label: 'Locate folder', icon: 'search' },
  { action: 'rename', label: 'Rename', icon: 'pen-line' },
  { action: 'forget', label: 'Forget project', icon: 'trash-2' },
];

/** What each availability is called on this screen. The rail's `null` means "available". */
export function availabilityLabel(availability: ProjectAvailability): string {
  return PROJECT_AVAILABILITY_META[availability].label ?? 'Available';
}

function availabilityTone(availability: ProjectAvailability): BadgeTone {
  return PROJECT_AVAILABILITY_META[availability].tone;
}

export interface ProjectHomeProps {
  /**
   * A project id from the address bar that the registry does not know — a stale bookmark,
   * or a project forgotten in another window. Reported above the list rather than as a
   * dead end.
   */
  notFoundProjectId?: string | null;
}

export function ProjectHome({ notFoundProjectId = null }: ProjectHomeProps) {
  const host = useHost();
  const navigate = useNavigate();
  const lifecycle = useProjectLifecycle();
  const [dialog, setDialog] = useState<ProjectDialog>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const close = (): void => setDialog(null);
  const reveal = async (project: ProjectView): Promise<void> => {
    setActionError(null);
    try {
      await lifecycle.reveal(project.project_id);
    } catch (cause) {
      setActionError(describeCause(cause));
    }
  };

  return (
    <main className="rh-projects">
      <header className="rh-projects__header">
        <div>
          <h1 className="rh-projects__title">Your research projects</h1>
          <p className="rh-projects__lede">
            Every workspace this application has been shown, most recently opened first.
          </p>
        </div>
        <div className="rh-projects__actions">
          <Button
            variant="primary"
            iconStart="plus"
            disabled={!lifecycle.ready}
            onClick={() => setDialog({ kind: 'create' })}
          >
            New project
          </Button>
          <Button
            iconStart="folder"
            disabled={!lifecycle.ready}
            onClick={() => setDialog({ kind: 'open' })}
          >
            Open folder
          </Button>
        </div>
      </header>

      {notFoundProjectId ? (
        <ErrorNotice
          kind="blocked"
          title="That project is not in this list"
          description={
            `No registered project has the id ${notFoundProjectId}. It may have been ` +
            'forgotten, or the link may be from another machine. Open its folder to add it ' +
            'again.'
          }
        />
      ) : null}

      {actionError ? (
        <ErrorNotice
          kind="retryable"
          title="The application refused"
          description={actionError}
          onDismiss={() => setActionError(null)}
        />
      ) : null}

      {host.authRequired ? (
        <ErrorNotice
          kind="blocked"
          title="Not signed in to the local application"
          description={APP_TOKEN_MISSING_EXPLANATION}
        />
      ) : null}

      {host.mode === 'loading' ? (
        <AsyncState
          kind="loading"
          title="Opening Research Harness"
          description="Asking the local application which workspaces it holds."
        />
      ) : null}

      {host.mode === 'error' ? (
        <ErrorNotice
          kind="retryable"
          title="Cannot reach Research Harness"
          description={host.error ?? 'The local application did not answer.'}
        />
      ) : null}

      {host.mode !== 'loading' && host.mode !== 'error' && !host.authRequired ? (
        host.projects.length === 0 ? (
          <AsyncState
            kind="empty"
            title="No projects yet"
            description={
              'Create a project to start a new workspace, or open a folder that already ' +
              'holds one. Research Harness only ever sees folders you choose.'
            }
          />
        ) : (
          <ul className="rh-projects__list" aria-label="Registered projects">
            {host.projects.map((project) => (
              <ProjectRow
                key={project.project_id}
                project={project}
                onOpen={() => navigate(projectHref(project.project_id, '/'))}
                onLocate={() => setDialog({ kind: 'locate', project })}
                onRename={() => setDialog({ kind: 'rename', project })}
                onForget={() => setDialog({ kind: 'forget', project })}
                onReveal={() => void reveal(project)}
              />
            ))}
          </ul>
        )
      ) : null}

      <ProjectDialogs dialog={dialog} onClose={close} onDialog={setDialog} />
    </main>
  );
}

interface ProjectRowProps {
  project: ProjectView;
  onOpen: () => void;
  onLocate: () => void;
  onRename: () => void;
  onForget: () => void;
  onReveal: () => void;
}

function ProjectRow({
  project,
  onOpen,
  onLocate,
  onRename,
  onForget,
  onReveal,
}: ProjectRowProps) {
  const openable = OPENABLE.includes(project.availability);
  const lastOpened = project.last_opened_at
    ? `Last opened ${formatTimestamp(project.last_opened_at)}`
    : 'Never opened';
  const perform: Record<ProjectAction, () => void> = {
    reveal: onReveal,
    locate: onLocate,
    rename: onRename,
    forget: onForget,
  };

  return (
    <Card as="li" className="rh-projects__card" padding="md">
      <div className="rh-projects__row">
        <div className="rh-projects__identity">
          <h2 className="rh-projects__name">{project.display_name}</h2>
          <p className="rh-projects__meta">
            <span className="rh-projects__path">{project.path}</span>
          </p>
          <p className="rh-projects__meta">
            <Badge
              size="sm"
              tone={availabilityTone(project.availability)}
              icon={PROJECT_AVAILABILITY_META[project.availability].icon}
            >
              {availabilityLabel(project.availability)}
            </Badge>
            {project.active_runs > 0 ? (
              <Badge size="sm" tone="info" icon="loader">
                {`${project.active_runs} active`}
              </Badge>
            ) : null}
            <span>{lastOpened}</span>
          </p>
          {project.detail ? <p className="rh-projects__detail">{project.detail}</p> : null}
        </div>
        <div className="rh-projects__row-actions">
          <Button variant="primary" disabled={!openable} onClick={onOpen}>
            Open
          </Button>
          {/*
            * The one action promoted out of the menu, and only where it is the repair.
            * A folder that moved is the single failure a researcher can fix from this
            * screen, so on an unavailable row Locate stands beside a disabled Open rather
            * than behind a menu; it keeps the menu's own words, and stays in the menu too.
            */}
          {project.availability === 'unavailable' ? (
            <Button iconStart="search" onClick={onLocate}>
              Locate folder
            </Button>
          ) : null}
          <Menu placement="bottom" align="end">
            <Menu.Trigger asChild>
              <Button variant="ghost" iconStart="more-horizontal">
                Project actions
              </Button>
            </Menu.Trigger>
            <Menu.Content aria-label={`Actions for ${project.display_name}`}>
              {PROJECT_ACTION_ITEMS.map(({ action, label, icon }) => (
                <Menu.Item
                  key={action}
                  icon={<Icon name={icon} size={14} />}
                  onSelect={() => perform[action]()}
                >
                  {label}
                </Menu.Item>
              ))}
            </Menu.Content>
          </Menu>
        </div>
      </div>
    </Card>
  );
}

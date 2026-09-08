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
import { useId, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AsyncState,
  Badge,
  Button,
  Card,
  ErrorNotice,
  Icon,
  IconButton,
  Input,
  Menu,
  PROJECT_AVAILABILITY_META,
  formatTimestamp,
} from '@research-harness/design';
import type { BadgeTone, IconName, ProjectAction } from '@research-harness/design';
import type { ProjectAvailability, ProjectView } from '../../api/projects';
import { APP_TOKEN_MISSING_EXPLANATION, useHost } from '../../app/host';
import { Empty } from '../../components/Feedback';
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

/**
 * What each availability is called on this screen.
 *
 * The rail's `null` means "available", which this screen never prints: a row that can be
 * opened says so by offering Open. The fallback keeps the function total.
 */
export function availabilityLabel(availability: ProjectAvailability): string {
  return PROJECT_AVAILABILITY_META[availability].label ?? 'Available';
}

function availabilityTone(availability: ProjectAvailability): BadgeTone {
  return PROJECT_AVAILABILITY_META[availability].tone;
}

/** `1 project` / `2 projects` — a count is only ever read inside the thing it counts. */
function counted(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * Whether one project answers what was typed into the find field.
 *
 * Every term has to match somewhere, and a term may match the name a researcher gave the
 * workspace or the folder it lives in — the two things a row prints and the two ways a
 * researcher remembers a project. It only ever *hides*: the registry's order is the
 * host's (`registry.py` sorts by `last_opened_at`), and a find that reordered it would be
 * this screen deciding which workspace matters (PRODUCT §5 P10).
 */
export function matchesProject(project: ProjectView, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = `${project.display_name} ${project.path}`.toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

/**
 * The three ages a registered project can have, newest first.
 *
 * Not a taxonomy of projects — a reading of one timestamp. The names answer the question
 * a researcher opens this screen with ("where was I?") at the resolution they can hold:
 * today, the week behind it, and everything before that.
 */
const AGES = ['Today', 'This week', 'Earlier'] as const;
type ProjectAge = (typeof AGES)[number];

/** The UTC day an instant falls on, as a whole number, so two of them subtract. */
function utcDay(at: Date): number {
  return Math.floor(Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate()) / 86_400_000);
}

/**
 * Which age a project's last opening falls in, counted in UTC.
 *
 * UTC because the row prints its timestamp in UTC (`formatTimestamp`), and a group that
 * said "Today" over a row dated yesterday would be the screen disagreeing with itself.
 * "This week" is the six days before today, not a calendar week: a Monday morning where
 * everything opened last week fell into "Earlier" would answer no question at all.
 *
 * A project the host sent with no opening at all sorts last there and reads "Never
 * opened" on its row; the control plane always sends one, so this is the defensive branch.
 */
export function ageOf(lastOpenedAt: string | null, now: Date): ProjectAge {
  if (lastOpenedAt === null) return 'Earlier';
  const at = new Date(lastOpenedAt);
  if (Number.isNaN(at.getTime())) return 'Earlier';
  const days = utcDay(now) - utcDay(at);
  if (days <= 0) return 'Today';
  if (days < 7) return 'This week';
  return 'Earlier';
}

export interface ProjectAgeGroup {
  age: ProjectAge;
  projects: ProjectView[];
}

/**
 * The host's list cut into its runs, in the host's own order.
 *
 * A project keeps its place: the daemon already returns the registry newest-first, so
 * every run is a slice of that one sequence and an age with nothing in it is not drawn.
 */
export function groupByAge(
  projects: readonly ProjectView[],
  now: Date,
): ProjectAgeGroup[] {
  const held = new Map<ProjectAge, ProjectView[]>();
  for (const project of projects) {
    const age = ageOf(project.last_opened_at, now);
    const run = held.get(age);
    if (run === undefined) held.set(age, [project]);
    else run.push(project);
  }
  return AGES.flatMap((age) => {
    const run = held.get(age);
    return run === undefined ? [] : [{ age, projects: run }];
  });
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
  const [query, setQuery] = useState('');
  const listingId = useId();
  const shown = useMemo(
    () => host.projects.filter((project) => matchesProject(project, query)),
    [host.projects, query],
  );
  const groups = useMemo(() => groupByAge(shown, new Date()), [shown]);

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
        {/*
          The product's name, and the only place the cockpit prints it.

          Every other screen is inside a workspace, where the frame says which project is
          open and takes the name of the application for granted. This one is reached
          before a workspace exists, so a researcher who arrives here — or a stranger
          looking over their shoulder — has nothing to read the product's identity from.
          There is no mark and no logotype to draw (PRODUCT, Evidence on Hand: no logo,
          wordmark or brand asset exists, and none may be invented), so the name set in
          the ramp's page-title role *is* the identity. The list of workspaces keeps its
          own name one step down, where it belongs: it is a section of this screen, not
          the screen itself.
        */}
        <h1 className="rh-projects__title">Research Harness</h1>
        {/*
          The one paragraph that defines the object this screen lists. Nothing else in
          the product ever says it: a researcher who has not opened a project yet has
          not met the rail, the review inbox or a claim, and a list of folder names
          teaches none of the three. What a project *is* comes from PRODUCT §8.1 — a
          folder holding the canonical research state — and what opening one does is
          the sentence the rest of the cockpit is built on.
        */}
        <p className="rh-projects__lede">
          A project is a folder on this machine that holds one body of research — its
          corpus, evidence, claims, questions and manuscript — in files that stay
          readable without this application. Opening one points the whole cockpit at
          that folder; forgetting one removes it from this list and leaves the folder
          exactly where it is.
        </p>
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
        <section className="rh-projects__listing" aria-labelledby={listingId}>
          <div className="rh-projects__list-head">
            <div>
              <h2 className="rh-text-h2" id={listingId}>
                Your research projects
              </h2>
              {/*
                The note is the list's own caption, not part of the lead: it describes
                what the rows are and the order they are in, which is a fact about the
                list.
              */}
              <p className="rh-projects__list-note">
                Every workspace this application has been shown, most recently opened first.
              </p>
            </div>
            {/*
              One field, and only where there is something to narrow. It hides rows; it
              never asks the host again and never re-sorts what came back.
            */}
            {host.projects.length > 0 ? (
              <Input
                label="Find a project by name or folder"
                hideLabel
                size="sm"
                type="search"
                iconStart="search"
                placeholder="Name or folder"
                fieldClassName="rh-projects__find"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            ) : null}
          </div>

          {host.projects.length === 0 ? (
            <AsyncState
              kind="empty"
              // The title names the state in this screen's own words, so the component's
              // generic label above it would be a kicker saying it twice.
              hideKind
              title="No projects yet"
              description={
                'Create a project to start a new workspace, or open a folder that already ' +
                'holds one. Research Harness only ever sees folders you choose.'
              }
              // The pattern's third part: one real next step, and the only one that can
              // end this state from here. It carries its own words rather than the header
              // button's, so a researcher reading the state is never told to press a
              // control they cannot see the name of twice over.
              actions={[
                {
                  label: 'Create your first project',
                  onClick: () => setDialog({ kind: 'create' }),
                  variant: 'primary',
                  iconStart: 'plus',
                  disabled: !lifecycle.ready,
                },
              ]}
            />
          ) : shown.length === 0 ? (
            <Empty
              description={
                'The find only hides. Every workspace this application has been shown is ' +
                'still registered underneath it.'
              }
              action={
                <Button size="sm" variant="secondary" onClick={() => setQuery('')}>
                  Clear the find
                </Button>
              }
            >
              No project matches this find
            </Empty>
          ) : (
            <ul className="rh-projects__list" aria-label="Registered projects">
              {groups.map((group, index) => (
                <li key={group.age} className="rh-projects__group">
                  {/*
                    The naming line and the run's accessible name at once, the way the
                    rail names its own runs: a researcher reads it, a screen reader is
                    told which age it has entered, and Tab never lands on it. The count
                    belongs on it because it is a fact about the run, and because it is
                    the only place a researcher can see how much of the registry each
                    age holds without counting rows.
                  */}
                  <p className="rh-projects__group-heading" id={`${listingId}-age-${index}`}>
                    {`${group.age} — ${counted(group.projects.length, 'project')}`}
                  </p>
                  <ul
                    className="rh-projects__rows"
                    aria-labelledby={`${listingId}-age-${index}`}
                  >
                    {group.projects.map((project) => (
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
                </li>
              ))}
            </ul>
          )}
        </section>
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
            {/*
              * Availability badges the exception and nothing else.
              *
              * Spec §4.2 asks for availability in words rather than in colour, and it is:
              * every state that stops or qualifies an opening keeps its word, its glyph
              * and the host's sentence under it. What it does not ask for is a badge on
              * the ordinary case. "Available" on every row of a healthy registry is a
              * constant — it says nothing about the row it sits on, and it hides the two
              * rows that were trying to say something. The row that can simply be opened
              * makes its claim with the Open button beside it.
              */}
            {project.availability === 'available' ? null : (
              <Badge
                size="sm"
                tone={availabilityTone(project.availability)}
                icon={PROJECT_AVAILABILITY_META[project.availability].icon}
              >
                {availabilityLabel(project.availability)}
              </Badge>
            )}
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
            {/*
              * The rail's trigger, verbatim: a glyph whose accessible name is the menu's
              * own words. It used to print those words, which made every row offer two
              * things where it has one — Open — and a registry of thirty rows print the
              * same second offer thirty times. The menu holds the rest; the row reads
              * once. The content still names the project it acts on, so a screen reader
              * hears which workspace it has opened the menu for.
              */}
            <Menu.Trigger asChild>
              <IconButton icon="more-horizontal" label="Project actions" />
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

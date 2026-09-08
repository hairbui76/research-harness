/**
 * Task 10.1/10.3: Project Home says what each folder is, and only offers what is possible.
 *
 * Two things carry weight here. The first is that availability is *text*: a researcher who
 * cannot distinguish the badge colours must still read "Unavailable" and the sentence the
 * host wrote (spec §4.2). The second is that this screen never decides a folder's fate — it
 * disables Open for the states the host called unopenable, offers Locate for the one the
 * researcher can fix, and leaves a busy project openable, because a lock inside a workspace
 * is not a reason to lock someone out of reading it (spec §10).
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { AppClient } from '../../api/projects';
import { APP_TOKEN_MISSING_EXPLANATION } from '../../app/host';
import type { FolderSelection, ProjectView } from '../../api/projects';
import {
  expectNoAxeViolations,
  fakeAppDaemon,
  projectView,
  renderWithHost,
} from '../../test/harness';
import { ProjectHome } from './ProjectHome';

const AVAILABLE = projectView();
const MOVED = projectView({
  project_id: 'prj_moved',
  display_name: 'Reef survey',
  path: '/mnt/usb/reef-survey',
  availability: 'unavailable',
  detail: 'The folder /mnt/usb/reef-survey is not readable from here.',
  last_opened_at: '2026-08-30T09:00:00Z',
});
const BUSY = projectView({
  project_id: 'prj_busy',
  display_name: 'Thermal tolerance',
  path: '/research/thermal',
  availability: 'busy',
  detail: 'A workflow is holding the repository lock.',
  active_runs: 2,
});

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="path">{`${location.pathname}${location.search}`}</p>;
}

interface SetupOptions {
  projects?: readonly ProjectView[];
  folder?: FolderSelection;
  authRequired?: boolean;
  mode?: 'multi' | 'error';
  error?: string | null;
  notFoundProjectId?: string | null;
  route?: string;
}

function setup(options: SetupOptions = {}) {
  const projects = options.projects ?? [AVAILABLE];
  const daemon = fakeAppDaemon({ projects, folder: options.folder });
  const appClient = new AppClient({
    baseUrl: 'http://app.test',
    token: options.authRequired ? null : 'app-token',
    fetchImpl: daemon.fetch,
  });
  const spies = {
    chooseFolder: vi.spyOn(appClient, 'chooseFolder'),
    createProject: vi.spyOn(appClient, 'createProject'),
    revealProject: vi.spyOn(appClient, 'revealProject'),
  };
  const refreshProjects = vi.fn(async () => {});
  const view = renderWithHost(
    <>
      <ProjectHome notFoundProjectId={options.notFoundProjectId ?? null} />
      <LocationProbe />
    </>,
    {
      route: options.route ?? '/',
      path: '*',
      host: {
        mode: options.mode ?? 'multi',
        error: options.error ?? null,
        projects,
        appClient,
        authRequired: options.authRequired ?? false,
        refreshProjects,
      },
    },
  );
  return { ...view, appClient, daemon, refreshProjects, spies };
}

/**
 * The project rows, and not the run each of them sits in.
 *
 * The registry is grouped by when each project was last opened, so the list named
 * "Registered projects" holds one item per run and the rows live in a nested list under
 * each run's naming line. A row is a list item whose own list is not the outer one.
 */
function rows(): HTMLElement[] {
  const list = screen.getByRole('list', { name: 'Registered projects' });
  return within(list)
    .getAllByRole('listitem')
    .filter((item) => item.closest('ul') !== list);
}

/** Each run as a researcher reads it: its naming line, and the projects under it. */
function groups(): { line: string; projects: (string | null)[] }[] {
  const list = screen.getByRole('list', { name: 'Registered projects' });
  return within(list)
    .getAllByRole('list')
    .map((group) => ({
      line: document.getElementById(group.getAttribute('aria-labelledby') ?? '')?.textContent ?? '',
      projects: within(group)
        .getAllByRole('listitem')
        .map((row) => within(row).getByRole('heading').textContent),
    }));
}

function rowNames(): (string | null)[] {
  return rows().map((row) => within(row).getByRole('heading').textContent);
}

/** The one field that narrows the list. Its label is hidden, so it is asked for by name. */
function find(): HTMLElement {
  return screen.getByRole('searchbox', { name: 'Find a project by name or folder' });
}

describe('Project Home', () => {
  it('offers create and open when no project has been registered', async () => {
    setup({ projects: [] });

    expect(
      await screen.findByRole('heading', { name: 'Your research projects' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New project' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open folder' })).toBeInTheDocument();
    expect(screen.getByText(/Create a project to start a new workspace/)).toBeInTheDocument();
  });

  /*
   * The product has a name and no mark, so the name is the identity.
   *
   * This is the only screen a researcher can reach before a workspace exists, and the
   * shell that would otherwise say where they are does not exist yet either. The page's
   * title line is therefore the product's name in the ramp's h1 role, and the registry it
   * lists becomes a section under it with a heading of its own (PRODUCT, Brand
   * Commitments: the name is "Research Harness", and there is no logo to draw).
   */
  it('names the product on its first screen, above what a project is', () => {
    setup({ projects: [AVAILABLE] });

    const title = screen.getByRole('heading', { level: 1, name: 'Research Harness' });
    const lead = screen.getByText(/A project is a folder on this machine/);
    const listing = screen.getByRole('heading', { level: 2, name: 'Your research projects' });

    expect(title.compareDocumentPosition(lead)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(lead.compareDocumentPosition(listing)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('puts the two ways in on a row of their own, under the lead', () => {
    setup({ projects: [AVAILABLE] });

    // The lead is read at the prose measure; the buttons are pressed. Stacking them under
    // it rather than floating them opposite it is what stops the title, the sentence and
    // the two controls from being three columns of one short row on a wide screen.
    const lead = screen.getByText(/A project is a folder on this machine/);
    const create = screen.getByRole('button', { name: 'New project' });
    const open = screen.getByRole('button', { name: 'Open folder' });

    expect(lead.compareDocumentPosition(create)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(create.parentElement).toBe(open.parentElement);
  });

  it('says what a project is, and what opening one does, above the list', () => {
    setup({ projects: [AVAILABLE] });

    // A first-timer arrives here before anything in this product has a name. The lead is
    // the only sentence that can define the object the whole screen is a list of.
    const lead = screen.getByText(/A project is a folder on this machine/);
    expect(lead).toHaveTextContent(/Opening one points the whole cockpit at that folder/);
    expect(lead).toHaveTextContent(/forgetting one removes it from this list/);

    // And it leads: one registered project is a card under a paragraph, not a card alone.
    const list = screen.getByRole('list', { name: 'Registered projects' });
    expect(lead.compareDocumentPosition(list)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(
      screen.getByText(/Every workspace this application has been shown/),
    ).toBeInTheDocument();
  });

  it('offers the one step that ends the empty state, and says what it will do', async () => {
    const user = userEvent.setup();
    setup({ projects: [] });

    // The shared empty-state pattern: the fact, then what a project is for, then one real
    // next action — which here is the only way a first project can come to exist.
    expect(screen.getByText('No projects yet')).toBeInTheDocument();
    expect(screen.getByText(/Create a project to start a new workspace/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create your first project' }));

    expect(await screen.findByRole('dialog', { name: 'New project' })).toBeInTheDocument();
  });

  it('keeps the order the host returned, most recently opened first', () => {
    setup({ projects: [BUSY, AVAILABLE, MOVED] });

    expect(rowNames()).toEqual(['Thermal tolerance', 'Latency study', 'Reef survey']);
  });

  /*
   * A registry that grows stays readable, and the daemon still decides the order.
   *
   * `registry.py` sorts by `last_opened_at`, newest first, and PRODUCT §5 P10 leaves that
   * judgement where it is made. Grouping only cuts that one sequence into the three ages
   * a researcher actually asks about — what did I have open today, what this week, what
   * before that — so no project ever moves past another.
   */
  it('cuts the list into the three ages, and keeps the host order inside each', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-08T12:00:00Z'));
    try {
      setup({
        projects: [
          projectView({ project_id: 'prj_1', display_name: 'Kelp cover', last_opened_at: '2026-09-08T09:30:00Z' }),
          projectView({ project_id: 'prj_2', display_name: 'Reef survey', last_opened_at: '2026-09-08T01:05:00Z' }),
          projectView({ project_id: 'prj_3', display_name: 'Thermal tolerance', last_opened_at: '2026-09-05T22:00:00Z' }),
          projectView({ project_id: 'prj_4', display_name: 'Latency study', last_opened_at: '2026-09-02T08:00:00Z' }),
          projectView({ project_id: 'prj_5', display_name: 'Salt marsh', last_opened_at: '2026-09-01T23:59:00Z' }),
        ],
      });

      // The naming line carries the count and is the run's accessible name, so a screen
      // reader is told which age it has entered and how much of it there is.
      expect(groups()).toEqual([
        { line: 'Today — 2 projects', projects: ['Kelp cover', 'Reef survey'] },
        { line: 'This week — 2 projects', projects: ['Thermal tolerance', 'Latency study'] },
        { line: 'Earlier — 1 project', projects: ['Salt marsh'] },
      ]);
    } finally {
      vi.useRealTimers();
    }
  });

  it('draws no age that has nothing in it', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-08T12:00:00Z'));
    try {
      setup({ projects: [projectView({ last_opened_at: '2026-06-01T10:00:00Z' })] });

      expect(groups().map((group) => group.line)).toEqual(['Earlier — 1 project']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('narrows the list to what was typed, over a name and over a folder', async () => {
    const user = userEvent.setup();
    setup({ projects: [BUSY, AVAILABLE, MOVED] });

    await user.type(find(), 'reef');
    expect(rowNames()).toEqual(['Reef survey']);

    await user.clear(find());
    await user.type(find(), '/research/latency');
    expect(rowNames()).toEqual(['Latency study']);
  });

  it('says a find only hides, and offers to clear it', async () => {
    const user = userEvent.setup();
    setup({ projects: [BUSY, AVAILABLE] });

    await user.type(find(), 'plankton');

    expect(screen.getByText('No project matches this find')).toBeInTheDocument();
    expect(screen.getByText(/The find only hides/)).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Registered projects' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Clear the find' }));

    expect(rowNames()).toEqual(['Thermal tolerance', 'Latency study']);
  });

  it('offers no find where there is nothing to find', () => {
    setup({ projects: [] });

    expect(
      screen.queryByRole('searchbox', { name: 'Find a project by name or folder' }),
    ).toBeNull();
  });

  it('states the folder, the last time it was opened, and what is running in it', () => {
    setup({ projects: [BUSY] });

    const row = rows()[0] as HTMLElement;
    expect(within(row).getByText('/research/thermal')).toBeInTheDocument();
    expect(within(row).getByText(/Last opened 2026-09-01/)).toBeInTheDocument();
    expect(within(row).getByText('2 active')).toBeInTheDocument();
  });

  it('names every availability in words and keeps a busy project openable', () => {
    setup({ projects: [AVAILABLE, BUSY] });

    const [available, busy] = rows() as [HTMLElement, HTMLElement];
    expect(within(available).getByText('Available')).toBeInTheDocument();
    expect(within(available).getByRole('button', { name: 'Open' })).toBeEnabled();
    expect(within(busy).getByText('Busy')).toBeInTheDocument();
    expect(within(busy).getByRole('button', { name: 'Open' })).toBeEnabled();
    expect(within(busy).getByText(/holding the repository lock/)).toBeInTheDocument();
  });

  it('refuses to open an unavailable project and offers to locate it instead', () => {
    setup({ projects: [MOVED] });

    const row = rows()[0] as HTMLElement;
    expect(within(row).getByText('Unavailable')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Open' })).toBeDisabled();
    expect(within(row).getByText(/is not readable from here/)).toBeInTheDocument();
    // The rail's verb, not a second one for the same act.
    expect(within(row).getByRole('button', { name: 'Locate folder' })).toBeInTheDocument();
  });

  /*
   * One vocabulary for the lifecycle.
   *
   * The rail offers these four in a "Project actions" menu; this screen used to offer an
   * overlapping subset as flat buttons, in another order, under other verbs. A researcher
   * who learns them in one place must recognise them in the other, so the set, the order,
   * the words and the affordance are the rail's.
   */
  it('offers the rail\u2019s project actions, in the rail\u2019s words and order', async () => {
    const user = userEvent.setup();
    setup({ projects: [AVAILABLE] });

    const row = rows()[0] as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Project actions' }));

    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Show in file manager',
      'Locate folder',
      'Rename',
      'Forget project',
    ]);
  });

  it('keeps one visible action per row: the one that opens the workspace', () => {
    setup({ projects: [AVAILABLE, BUSY] });

    for (const row of rows()) {
      expect(within(row).getAllByRole('button').map((button) => button.textContent)).toEqual([
        'Open',
        'Project actions',
      ]);
    }
  });

  it.each([
    ['invalid', 'Invalid'],
    ['incompatible', 'Incompatible'],
  ] as const)('refuses to open a %s project and says why', (availability, label) => {
    setup({
      projects: [projectView({ availability, detail: 'research.yaml does not parse.' })],
    });

    const row = rows()[0] as HTMLElement;
    expect(within(row).getByText(label)).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Open' })).toBeDisabled();
    expect(within(row).getByText('research.yaml does not parse.')).toBeInTheDocument();
    // Locating helps a folder that moved, not one whose contents the host rejected: the
    // action stays in the menu rather than being promoted beside Open.
    expect(within(row).queryByRole('button', { name: 'Locate folder' })).not.toBeInTheDocument();
  });

  it('opens a project at its own URL', async () => {
    const user = userEvent.setup();
    setup({ projects: [AVAILABLE] });

    await user.click(screen.getByRole('button', { name: 'Open' }));

    expect(screen.getByTestId('path')).toHaveTextContent('/projects/prj_abc/');
  });

  it('asks the host to reveal a project, and never a path', async () => {
    const user = userEvent.setup();
    const { spies } = setup({ projects: [AVAILABLE] });

    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Show in file manager' }));

    await waitFor(() => expect(spies.revealProject).toHaveBeenCalledWith('prj_abc'));
  });

  it('creates from the parent returned by the native picker', async () => {
    const user = userEvent.setup();
    const { spies } = setup({
      projects: [],
      folder: { path: 'D:\\research', method: 'native', cancelled: false, fallback_required: false },
    });

    await user.click(screen.getByRole('button', { name: 'New project' }));
    await user.type(await screen.findByLabelText('Project name'), 'Latency study');
    await user.click(screen.getByRole('button', { name: 'Choose parent folder' }));
    await screen.findByText(/D:\\research/);
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    await waitFor(() =>
      expect(spies.createProject).toHaveBeenCalledWith('D:\\research', 'Latency study', 'strict'),
    );
  });

  it('returns focus to the control that opened a dialog', async () => {
    const user = userEvent.setup();
    setup({ projects: [] });

    const opener = screen.getByRole('button', { name: 'New project' });
    await user.click(opener);
    await screen.findByRole('dialog', { name: 'New project' });
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('tells a tab with no application token how to get one', () => {
    setup({ authRequired: true, projects: [] });

    expect(screen.getByText(APP_TOKEN_MISSING_EXPLANATION)).toBeInTheDocument();
    expect(APP_TOKEN_MISSING_EXPLANATION).toContain('research app');
    expect(screen.getByRole('button', { name: 'New project' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Open folder' })).toBeDisabled();
  });

  it('reports a registry it could not read, without pretending the list is empty', () => {
    setup({ mode: 'error', error: 'projects.json is not readable.', projects: [] });

    expect(screen.getByText('projects.json is not readable.')).toBeInTheDocument();
    expect(screen.queryByText(/No projects yet/)).not.toBeInTheDocument();
  });

  it('says so when the address bar names a project the registry does not know', () => {
    setup({ notFoundProjectId: 'prj_gone' });

    expect(screen.getByText(/No registered project has the id prj_gone/)).toBeInTheDocument();
    // The list is still there: an unknown id is a notice, not a dead end.
    expect(rows()).toHaveLength(1);
  });

  it('has no axe violations', async () => {
    const { container } = setup({ projects: [AVAILABLE, MOVED, BUSY] });
    await expectNoAxeViolations(container);
  });
});

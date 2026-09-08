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
 * The project rows, and not the naming lines between them.
 *
 * The registry is windowed and grouped by when each project was last opened, so the list
 * named "Registered projects" is one sequence: a run's naming line, then the workspaces it
 * names, then the next line. A row is a list item that holds a workspace card.
 */
function rows(): HTMLElement[] {
  const list = screen.getByRole('list', { name: 'Registered projects' });
  return within(list)
    .getAllByRole('listitem')
    .filter((item) => item.querySelector('.rh-projects__card') !== null);
}

/**
 * Each run as a researcher reads it: its naming line, and the projects under it.
 *
 * Read off the sequence rather than off a container, because the runs are no longer
 * nested lists: only a window of the registry is mounted at a time, and a group whose
 * members come and go as that window moves is not something a reader can be sent into.
 */
function groups(): { line: string; projects: (string | null)[] }[] {
  const list = screen.getByRole('list', { name: 'Registered projects' });
  const runs: { line: string; projects: (string | null)[] }[] = [];
  for (const item of within(list).getAllByRole('listitem')) {
    const line = item.querySelector('.rh-projects__group-heading');
    if (line !== null) {
      runs.push({ line: line.textContent ?? '', projects: [] });
      continue;
    }
    const name = within(item).getByRole('heading').textContent;
    runs.at(-1)?.projects.push(name);
  }
  return runs;
}

function rowNames(): (string | null)[] {
  return rows().map((row) => within(row).getByRole('heading').textContent);
}

/** The link a row offers into its workspace, or null where the host will not open one. */
function openLink(row: HTMLElement): HTMLElement | null {
  return within(row).queryByRole('link');
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

  it('keeps one outline: the product, the registry, and a workspace in it', () => {
    setup({ projects: [AVAILABLE] });

    // Three levels and no fourth. The run's naming line is a paragraph on purpose — the
    // rail's runs are paragraphs too — so cutting the list into ages adds no heading.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Research Harness');
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Your research projects');
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Latency study');
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

  /*
   * A registry nothing bounds.
   *
   * The critique photographed forty-six rows here, every one of them mounted: this screen
   * is the one a researcher meets before any workspace exists, and the only thing that
   * decides its length is how many folders this machine has been shown. It is windowed
   * now, with the same instrument the Corpus and the Synthesis grid use.
   */
  it('windows a long registry instead of mounting every workspace', () => {
    const many = Array.from({ length: 200 }, (_, index) =>
      projectView({
        project_id: `prj_${index}`,
        display_name: `Workspace ${index}`,
        last_opened_at: '2026-09-08T09:30:00Z',
      }),
    );
    setup({ projects: many });

    const mounted = rows().length;
    expect(mounted, `a registry of 200 mounted ${mounted} rows`).toBeLessThan(40);
    // And the list still says how long it is, so a reader is told where they are in the
    // whole registry rather than in the slice that happens to exist.
    const list = screen.getByRole('list', { name: 'Registered projects' });
    expect(within(list).getAllByRole('listitem')[0]).toHaveAttribute('aria-setsize', '201');
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
    // Changed on purpose: this row used to assert an "Available" badge. A badge every row
    // wears is not a state, it is wallpaper — and it made the two rows that *are* saying
    // something harder to find. Availability is still text wherever it is news.
    expect(within(available).queryByText('Available')).toBeNull();
    // Changed on purpose: the row's way in used to be a filled Open beside a name that did
    // nothing. The name is the link now — one act per row, and the page's loud emphasis
    // spent on the two header controls rather than on every row of the registry.
    expect(openLink(available)).toHaveAccessibleName('Latency study');
    expect(within(busy).getByText('Busy')).toBeInTheDocument();
    expect(openLink(busy)).toHaveAccessibleName('Thermal tolerance');
    expect(within(busy).getByText(/holding the repository lock/)).toBeInTheDocument();
  });

  /*
   * The badge is for the exception, and the row still says everything else.
   *
   * Spec §4.2 requires availability to be *text* and not colour, which it still is: what
   * changed is that a project a researcher can simply open makes no claim about it at
   * all — pressing Open is the claim — while every state that stops or qualifies an
   * opening keeps its word and its sentence.
   */
  it('badges an availability only where it is not simply available', () => {
    setup({ projects: [AVAILABLE, BUSY, MOVED] });

    const [available, busy, moved] = rows() as [HTMLElement, HTMLElement, HTMLElement];
    expect(within(available).queryByText('Available')).toBeNull();
    expect(within(available).getByText('/research/latency-study')).toBeInTheDocument();
    expect(within(available).getByText(/Last opened 2026-09-01/)).toBeInTheDocument();

    expect(within(busy).getByText('Busy')).toBeInTheDocument();
    expect(within(busy).getByText(/holding the repository lock/)).toBeInTheDocument();

    expect(within(moved).getByText('Unavailable')).toBeInTheDocument();
    expect(within(moved).getByText(/is not readable from here/)).toBeInTheDocument();
  });

  it('refuses to open an unavailable project and offers to locate it instead', () => {
    setup({ projects: [MOVED] });

    const row = rows()[0] as HTMLElement;
    expect(within(row).getByText('Unavailable')).toBeInTheDocument();
    // A workspace the host will not open is not a link: the badge and the host's sentence
    // say why, where a disabled button said only that something was wrong.
    expect(openLink(row)).toBeNull();
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
      /*
       * Changed on purpose, twice over. The row used to print "Project actions" beside
       * Open — one row read as two offers, thirty read as sixty — so the words became the
       * trigger's accessible name over its glyph, which is what the rail's own trigger has
       * always been. Then Open went too: a filled button on every row of a registry of
       * forty-six is the page's loudest emphasis spent forty-six times, and the name a
       * researcher is already reading is what they reach for. So the row's one act is its
       * name, and its one button is the overflow.
       */
      expect(openLink(row)).toBeInTheDocument();
      const buttons = within(row).getAllByRole('button');
      expect(buttons).toHaveLength(1);
      expect(buttons[0]).toHaveAccessibleName('Project actions');
      expect(buttons[0]).toHaveTextContent('');
    }
  });

  it('says the overflow\u2019s name once per row, and never twice on screen', () => {
    setup({ projects: [AVAILABLE, BUSY, MOVED] });

    expect(screen.getAllByRole('button', { name: 'Project actions' })).toHaveLength(3);
    // Nothing on this screen prints the words: a menu is an affordance, not an action,
    // and a list repeats its rows, not its furniture.
    expect(screen.queryAllByText('Project actions')).toHaveLength(0);
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
    expect(openLink(row)).toBeNull();
    expect(within(row).getByText('research.yaml does not parse.')).toBeInTheDocument();
    // Locating helps a folder that moved, not one whose contents the host rejected: the
    // action stays in the menu rather than being promoted beside Open.
    expect(within(row).queryByRole('button', { name: 'Locate folder' })).not.toBeInTheDocument();
  });

  it('opens a project at its own URL', async () => {
    const user = userEvent.setup();
    setup({ projects: [AVAILABLE] });

    const link = openLink(rows()[0] as HTMLElement) as HTMLElement;
    // A real link, so it is opened the way a researcher opens one: in this tab, in a new
    // one, or copied. A button could do none of the last two.
    expect(link).toHaveAttribute('href', '/projects/prj_abc/');
    await user.click(link);

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

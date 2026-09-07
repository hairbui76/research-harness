/**
 * The shell: the rail, the routes it reaches, and the appearance settings.
 *
 * What is asserted here is what the routes build on. The research navigation is one list
 * (`routes.tsx`) — the conversation first, then the Overview and the research pages — the
 * counts on it are the daemon's own (`overview.attention[].route`), the active route
 * carries `aria-current="page"`, a plain click on a rail link is a client-side navigation
 * rather than a page load, and the theme and density toggles write the Design System's
 * `data-theme` / `data-density` onto the document.
 *
 * The rail also carries the conversation's session history on every route, which is why
 * the shell mounts the conversation state (`views/conversation/state.tsx`) above it. A
 * daemon that answers no `session.list` — every fixture below — leaves the history empty
 * and changes nothing else about the rail.
 *
 * The second half of the file is the multi-project host of design §4.5. The rail becomes
 * the switcher, and the two rules that make switching safe are asserted rather than assumed:
 * selecting a project is a *navigation*, so the URL — not a variable — says which project a
 * screen belongs to; and every lifecycle action either writes nothing (Show in file manager)
 * or asks first, in the dialogs of `views/projects`. The legacy shell is asserted to have
 * gained none of it, because `research serve` owns one workspace and has no list to change.
 */
import { describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { Layout } from './Layout';
import { HostProvider } from './host';
import type { Host } from './host';
import { ProjectPathProvider } from './projectPaths';
import { SessionProvider } from './session';
import { PROJECT_POLL_INTERVAL_MS } from './useProjectPolling';
import { AppClient } from '../api/projects';
import type { FolderSelection, ProjectView } from '../api/projects';
import sessions from '../test/fixtures/conversation/sessions.json';
import {
  FIXTURES,
  expectNoAxeViolations,
  fakeAppDaemon,
  fakeDaemon,
  hostValue,
  projectView,
  renderView,
} from '../test/harness';

/** `path: '*'` keeps the shell mounted while a rail link changes the route under it. */
function renderShell(daemon = fakeDaemon(), token: string | null = 'local-token') {
  return renderView(<Layout />, { daemon, token, route: '/review', path: '*' });
}

/**
 * The shell's own bar, the one it draws below its breakpoint.
 *
 * Selected by class rather than by role: `main` carries a second `<header>` — the project
 * bar — and jsdom's role mapping does not scope either of them, so "the banner" is
 * ambiguous here in a way it is not in a browser.
 */
function shellBar(): HTMLElement {
  const bar = document.querySelector('.rh-app-shell__bar');
  expect(bar).not.toBeNull();
  expect((bar as HTMLElement).tagName).toBe('HEADER');
  return bar as HTMLElement;
}

/**
 * A window narrower than the shell's breakpoint, for the layout where the rail is a drawer.
 *
 * jsdom has no `matchMedia` at all, so the shell answers "wide" and never draws its bar.
 * The stub answers the one query the shell asks — and returns it here, so the tests that
 * need a wide window are not left in a narrow one.
 */
function stubNarrowViewport(): () => void {
  const original = Object.getOwnPropertyDescriptor(window, 'matchMedia');
  const query = (media: string): MediaQueryList =>
    ({
      matches: /max-width:\s*960px/.test(media),
      media,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
  Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: query });
  return () => {
    if (original) Object.defineProperty(window, 'matchMedia', original);
    else Reflect.deleteProperty(window, 'matchMedia');
  };
}

describe('the project rail', () => {
  it('lists the research navigation with the counts the daemon reported', async () => {
    renderShell();

    const rail = await screen.findByRole('navigation', { name: 'Project navigation' });
    const items = Array.from(rail.querySelectorAll('.rh-project-rail__nav-item')).map((node) =>
      node.querySelector('.rh-project-rail__nav-label')?.textContent,
    );
    // Taxonomy and Synthesis swapped on 2026-09-08 (roadmap 3L, option A): Taxonomy is part
    // of the record and Synthesis is an output, and a group is a run of consecutive items.
    expect(items).toEqual([
      'Conversation',
      'Overview',
      'Review inbox',
      'Conflicts',
      'Stale',
      'Corpus',
      'Claims',
      'Questions',
      'Taxonomy',
      'Synthesis',
      'Manuscript',
    ]);

    // `2 review items` on `/review` in the fixture; the groups reporting 0 show no count.
    const review = FIXTURES.overview.attention.find((group) => group.route === '/review');
    expect(screen.getByRole('link', { name: /Review inbox/ }).textContent).toContain(
      String(review?.count),
    );
    expect(screen.getByRole('link', { name: /Conflicts/ }).textContent).not.toMatch(/\d/);
  });

  it('draws the three groups the roadmap named, over the pages they hold', async () => {
    renderShell();

    await screen.findByRole('navigation', { name: 'Project navigation' });
    for (const [name, labels] of [
      ['Waiting', ['Review inbox', 'Conflicts', 'Stale']],
      ['The record', ['Corpus', 'Claims', 'Questions', 'Taxonomy']],
      ['Outputs', ['Synthesis', 'Manuscript']],
    ] as const) {
      const group = screen.getByRole('list', { name });
      expect(screen.getByText(name)).toBeInTheDocument();
      expect(
        Array.from(group.querySelectorAll('.rh-project-rail__nav-label')).map(
          (node) => node.textContent,
        ),
      ).toEqual([...labels]);
    }

    // A heading is text; the rail's tab stops are still its links and its own controls.
    expect(screen.queryByRole('link', { name: 'The record' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'The record' })).not.toBeInTheDocument();
  });

  it('carries the conversation session history, on every route', async () => {
    renderShell();

    // The slot is filled from `session.list`; this fixture daemon answers none, so the
    // history is present and empty rather than absent. Nothing else about the rail moves.
    await screen.findByRole('navigation', { name: 'Project navigation' });
    expect(screen.getByRole('searchbox', { name: 'Search sessions' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New session' })).toBeInTheDocument();
  });

  it('marks the active route with aria-current, and follows a click without reloading', async () => {
    const user = userEvent.setup();
    renderShell();

    const review = await screen.findByRole('link', { name: /Review inbox/ });
    expect(review).toHaveAttribute('aria-current', 'page');

    await user.click(screen.getByRole('link', { name: /Corpus/ }));

    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Corpus/ })).toHaveAttribute('aria-current', 'page'),
    );
    expect(screen.getByRole('link', { name: /Review inbox/ })).not.toHaveAttribute('aria-current');
  });

  it('says which principal the daemon resolved, in words', async () => {
    renderShell(fakeDaemon(), 'local-token');

    await waitFor(() => expect(screen.getByText('Researcher — may accept')).toBeInTheDocument());
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('says an agent host may only read and propose', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    renderShell(fakeDaemon({ gets: { '/overview': asHost } }), null);

    await waitFor(() =>
      expect(screen.getByText('agent_host — reads and proposes only')).toBeInTheDocument(),
    );
    expect(screen.getByText('Degraded')).toBeInTheDocument();
  });

  it('offers no switcher and no project actions on a single-workspace host', async () => {
    renderShell();

    // `research serve` owns exactly one workspace and holds no registry: there is nothing
    // to switch to, add, or forget, so none of those controls exists to be pressed.
    await screen.findByRole('navigation', { name: 'Project navigation' });
    expect(screen.getByText(FIXTURES.overview.project)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Switch project/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Project actions' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add project' })).not.toBeInTheDocument();
    expect(document.querySelector('.rh-web-project-bar')).toBeNull();
    expect(screen.getByRole('link', { name: /Review inbox/ })).toHaveAttribute('href', '/review');
  });
});

describe('the shell', () => {
  it('puts a skip link ahead of the rail, pointing at the main surface', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.tab();
    const skip = screen.getByRole('link', { name: 'Skip to main content' });
    expect(skip).toHaveFocus();
    const main = screen.getByRole('main', { name: 'Research workspace' });
    expect(skip.getAttribute('href')).toBe(`#${main.id}`);
  });

  it('switches the theme and the density from settings, on the document', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(await screen.findByRole('button', { name: 'Settings' }));
    await screen.findByRole('dialog', { name: 'Settings' });

    await user.selectOptions(screen.getByLabelText('Theme'), 'light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    await user.selectOptions(screen.getByLabelText('Density'), 'compact');
    expect(document.documentElement.getAttribute('data-density')).toBe('compact');
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderShell();

    await screen.findByRole('navigation', { name: 'Project navigation' });
    await expectNoAxeViolations(container);
  });

  it('names the workspace and the destination in the collapsed bar', async () => {
    const restore = stubNarrowViewport();
    try {
      renderShell();

      // Below the breakpoint the rail is a drawer, so the bar is the only thing left on
      // screen that can say which screen this is. It says it in the rail's own words.
      await waitFor(() =>
        expect(within(shellBar()).getByText(FIXTURES.overview.project)).toBeInTheDocument(),
      );
      const bar = shellBar();
      expect(within(bar).getByText('Review inbox')).toBeInTheDocument();
      // And the control that opens the drawer keeps the name it is found by.
      expect(
        within(bar).getByRole('button', { name: 'Project navigation' }),
      ).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('follows the route it is on, and names no destination the navigation has not got', async () => {
    const restore = stubNarrowViewport();
    try {
      const user = userEvent.setup();
      renderShell();

      await waitFor(() =>
        expect(within(shellBar()).getByText('Review inbox')).toBeInTheDocument(),
      );

      // The destinations are in the drawer at this width, so this is the whole narrow
      // journey: open the rail, go somewhere, and read where you are from the bar.
      await user.click(within(shellBar()).getByRole('button', { name: 'Project navigation' }));
      await user.click(await screen.findByRole('link', { name: /Corpus/ }));

      await waitFor(() => expect(within(shellBar()).getByText('Corpus')).toBeInTheDocument());
      const bar = shellBar();
      expect(within(bar).queryByText('Review inbox')).not.toBeInTheDocument();
      // The workspace is still named beside it, whichever screen is on show.
      expect(within(bar).getByText(FIXTURES.overview.project)).toBeInTheDocument();
    } finally {
      restore();
    }
  });
});

// -- the multi-project host ------------------------------------------------------------

const OPEN = projectView({
  project_id: 'prj_abc',
  display_name: 'Latency study',
  path: '/research/latency-study',
});
const RUNNING = projectView({
  project_id: 'prj_thermal',
  display_name: 'Thermal tolerance',
  path: '/research/thermal',
  active_runs: 2,
});
const MOVED = projectView({
  project_id: 'prj_reef',
  display_name: 'Reef survey',
  path: '/mnt/usb/reef-survey',
  availability: 'unavailable',
  detail: 'The folder /mnt/usb/reef-survey is not readable from here.',
});

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="path">{`${location.pathname}${location.search}`}</p>;
}

interface MultiOptions {
  projects?: readonly ProjectView[];
  route?: string;
  folder?: FolderSelection;
  /** Capability answers for the workspace routes beneath `/api/projects/prj_abc`. */
  workspace?: Record<string, unknown>;
}

/**
 * The shell as `research app` mounts it: one project's workspace, under the registry.
 *
 * This is `App.tsx`'s multi-project tree written out — the host, the path prefix and a
 * workspace client scoped to `prj_abc` — because the shell is the piece that reads all
 * three, and a test that stubbed any of them would prove nothing about how they meet.
 */
function setupMulti(options: MultiOptions = {}) {
  const projects = options.projects ?? [OPEN, RUNNING, MOVED];
  const daemon = fakeAppDaemon({
    projects,
    lifecycleResult: OPEN,
    ...(options.folder ? { folder: options.folder } : {}),
    ...(options.workspace ? { workspace: { capabilities: options.workspace } } : {}),
  });
  const appClient = new AppClient({
    baseUrl: 'http://app.test',
    token: 'app-token',
    fetchImpl: daemon.fetch,
  });
  const spies = {
    revealProject: vi.spyOn(appClient, 'revealProject'),
    renameProject: vi.spyOn(appClient, 'renameProject'),
    forgetProject: vi.spyOn(appClient, 'forgetProject'),
    openProject: vi.spyOn(appClient, 'openProject'),
  };
  const refreshProjects = vi.fn(async () => {});
  const client = appClient.workspaceClient('prj_abc');

  function Tree({ host }: { host: Host }) {
    return (
      <ThemeProvider defaultTheme="dark" storageKey={null}>
        <ToastProvider>
          <MemoryRouter
            initialEntries={[options.route ?? '/projects/prj_abc/review']}
            future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
          >
            <HostProvider value={host}>
              <ProjectPathProvider projectId="prj_abc">
                <SessionProvider client={client}>
                  <Routes>
                    <Route
                      path="*"
                      element={
                        <>
                          <Layout />
                          <LocationProbe />
                        </>
                      }
                    />
                  </Routes>
                </SessionProvider>
              </ProjectPathProvider>
            </HostProvider>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    );
  }

  const host = (registry: readonly ProjectView[]): Host =>
    hostValue({ mode: 'multi', projects: registry, appClient, refreshProjects });
  const view = render(<Tree host={host(projects)} />);

  return {
    ...view,
    daemon,
    appClient,
    refreshProjects,
    spies,
    /** The registry as a later poll found it. */
    setProjects: (next: readonly ProjectView[]) => view.rerender(<Tree host={host(next)} />),
  };
}

/** The switcher, opened. */
async function openSwitcher(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(await screen.findByRole('button', { name: /Switch project/ }));
}

/** The per-project actions menu, opened. */
async function openActions(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(await screen.findByRole('button', { name: 'Project actions' }));
}

describe('the project rail on a multi-project host', () => {
  it('names the open project in the rail, in the header, and in every rail link', async () => {
    setupMulti();

    expect(
      await screen.findByRole('button', { name: 'Project: Latency study. Switch project' }),
    ).toBeInTheDocument();

    // Spec §4.5 / §11 item 6: the name stays readable in `main`, where it survives the rail
    // becoming a drawer below the shell's breakpoint.
    const header = document.querySelector('.rh-web-project-bar');
    expect(header).not.toBeNull();
    expect(within(header as HTMLElement).getByText('Latency study')).toBeInTheDocument();
    expect(within(header as HTMLElement).getByText('/research/latency-study')).toBeInTheDocument();

    // Every workspace screen lives below `/projects/{project_id}`, and the daemon's counts
    // are still keyed by the unprefixed route it reported.
    const review = screen.getByRole('link', { name: /Review inbox/ });
    expect(review).toHaveAttribute('href', '/projects/prj_abc/review');
    expect(review).toHaveAttribute('aria-current', 'page');
    expect(review.textContent).toContain('2');
    expect(screen.getByRole('link', { name: /Conversation/ })).toHaveAttribute(
      'href',
      '/projects/prj_abc/',
    );
  });

  it('names the open project and the destination in the collapsed bar', async () => {
    const restore = stubNarrowViewport();
    try {
      setupMulti();

      // The registry's name for the project, not the daemon's name for the workspace: two
      // windows on two projects must be told apart from the bar alone.
      await waitFor(() =>
        expect(within(shellBar()).getByText('Latency study')).toBeInTheDocument(),
      );
      expect(within(shellBar()).getByText('Review inbox')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('switches project by navigating, so the URL says which one is open', async () => {
    const user = userEvent.setup();
    setupMulti();

    await openSwitcher(user);
    await user.click(screen.getByRole('menuitem', { name: /Thermal tolerance/ }));

    await waitFor(() =>
      expect(screen.getByTestId('path')).toHaveTextContent('/projects/prj_thermal/'),
    );
  });

  it('refuses a project the host cannot open, and says why in words', async () => {
    const user = userEvent.setup();
    setupMulti();

    await openSwitcher(user);
    const moved = screen.getByRole('menuitem', { name: /Reef survey.*Unavailable/ });
    // An ARIA menu item is not a form control, so the disabled state is `aria-disabled`.
    expect(moved).toHaveAttribute('aria-disabled', 'true');

    await user.click(moved);
    expect(screen.getByTestId('path')).toHaveTextContent('/projects/prj_abc/review');
  });

  it('shows what is still running in a project nobody is looking at', async () => {
    const user = userEvent.setup();
    setupMulti();

    await openSwitcher(user);
    // Switching projects leaves the other project's workflow running (spec §10); the rail
    // is where that is visible.
    expect(
      screen.getByRole('menuitem', { name: /Thermal tolerance.*2 active/ }),
    ).toBeInTheDocument();
  });

  it('reveals the open project in the file manager, writing nothing', async () => {
    const user = userEvent.setup();
    const { spies } = setupMulti();

    await openActions(user);
    await user.click(screen.getByRole('menuitem', { name: 'Show in file manager' }));

    await waitFor(() => expect(spies.revealProject).toHaveBeenCalledWith('prj_abc'));
    // Nothing to confirm and nothing written, so no dialog appears.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renames the open project through the dialog, then re-reads the registry', async () => {
    const user = userEvent.setup();
    const { spies, refreshProjects } = setupMulti();

    await openActions(user);
    await user.click(screen.getByRole('menuitem', { name: 'Rename' }));

    await screen.findByRole('dialog', { name: 'Rename project' });
    const field = screen.getByLabelText('Display name');
    await user.clear(field);
    await user.type(field, 'Latency study II');
    await user.click(screen.getByRole('button', { name: 'Rename project' }));

    await waitFor(() =>
      expect(spies.renameProject).toHaveBeenCalledWith('prj_abc', 'Latency study II'),
    );
    expect(refreshProjects).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('forgets the open project only after saying the files remain on disk', async () => {
    const user = userEvent.setup();
    const { spies } = setupMulti();

    await openActions(user);
    await user.click(screen.getByRole('menuitem', { name: 'Forget project' }));

    const dialog = await screen.findByRole('alertdialog', { name: 'Forget project' });
    expect(within(dialog).getByText(/files remain on disk/)).toBeInTheDocument();
    expect(spies.forgetProject).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole('button', { name: 'Forget project' }));

    await waitFor(() => expect(spies.forgetProject).toHaveBeenCalledWith('prj_abc'));
    // The project this window was in no longer exists, so the window goes to Project Home.
    await waitFor(() => expect(screen.getByTestId('path')).toHaveTextContent('/'));
  });

  it('adds a project by asking the host for a folder, never by typing a path for it', async () => {
    const user = userEvent.setup();
    const { spies, daemon } = setupMulti({
      folder: {
        path: '/research/new-study',
        method: 'zenity',
        cancelled: false,
        fallback_required: false,
      },
    });

    await openSwitcher(user);
    await user.click(screen.getByRole('menuitem', { name: 'Add project' }));

    await waitFor(() =>
      expect(daemon.calls.some((call) => call.path === '/api/dialogs/folder')).toBe(true),
    );
    await waitFor(() => expect(spies.openProject).toHaveBeenCalledWith('/research/new-study'));
  });

  it('leaves the workspace for Project Home from the top of the switcher', async () => {
    const user = userEvent.setup();
    setupMulti();

    await openSwitcher(user);
    await user.click(screen.getByRole('menuitem', { name: 'All projects' }));

    await waitFor(() => expect(screen.getByTestId('path')).toHaveTextContent('/'));
  });

  it('re-reads the registry only while some project is still running', async () => {
    vi.useFakeTimers();
    try {
      const view = setupMulti({ projects: [OPEN, RUNNING] });
      expect(view.refreshProjects).not.toHaveBeenCalled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(PROJECT_POLL_INTERVAL_MS);
      });
      expect(view.refreshProjects).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(PROJECT_POLL_INTERVAL_MS);
      });
      expect(view.refreshProjects).toHaveBeenCalledTimes(2);

      // The run finished. Nothing else can change the registry behind our back, so the
      // timer stops rather than asking forever for an answer that is already correct.
      view.setProjects([OPEN, { ...RUNNING, active_runs: 0 }]);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(PROJECT_POLL_INTERVAL_MS * 3);
      });
      expect(view.refreshProjects).toHaveBeenCalledTimes(2);

      // And it stops on unmount, so a closed workspace polls nothing.
      view.setProjects([OPEN, RUNNING]);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(PROJECT_POLL_INTERVAL_MS);
      });
      expect(view.refreshProjects).toHaveBeenCalledTimes(3);
      view.unmount();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(PROJECT_POLL_INTERVAL_MS * 3);
      });
      expect(view.refreshProjects).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  /**
   * The switcher rail is still the session rail.
   *
   * The two features that met in this file both rewrote the rail: one made it the project
   * switcher, the other made its New-session button ask what kind of session is being
   * opened. A rail that switched projects but created a private session in silence would
   * have passed both features' own tests and still be wrong, so the seam is asserted here:
   * the click asks, and the answer reaches the daemon under the project the URL names.
   */
  it('asks what kind of session to open, and creates it in the project the URL names', async () => {
    const created = {
      ...sessions.sessions[0],
      id: 'CS0009',
      title: 'New session',
      visibility: 'private',
      message_count: 0,
      last_message: null,
      last_message_at: null,
    };
    const user = userEvent.setup();
    const view = setupMulti({ workspace: { 'session.create': { session: created } } });

    await screen.findByRole('navigation', { name: 'Project navigation' });
    await user.click(screen.getByRole('button', { name: 'New session' }));

    // `private` is the answer that is no longer the default, so it is the one that has to
    // survive the trip through the project-scoped client.
    const dialog = await screen.findByRole('dialog', { name: 'New session' });
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Visibility' }), 'private');
    await user.click(within(dialog).getByRole('button', { name: 'Create session' }));

    const create = await waitFor(() => {
      const call = view.daemon.calls.find(
        (entry) => entry.path === '/api/projects/prj_abc/capabilities/session.create',
      );
      expect(call).toBeDefined();
      return call;
    });
    expect(create?.body).toEqual({ title: 'New session', visibility: 'private' });

    // And the session the daemon named is opened, below this project's prefix.
    await waitFor(() =>
      expect(screen.getByTestId('path')).toHaveTextContent('/projects/prj_abc/?session=CS0009'),
    );
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = setupMulti();

    await screen.findByRole('navigation', { name: 'Project navigation' });
    await expectNoAxeViolations(container);
  });
});

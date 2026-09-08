/**
 * Task 13.4: the whole cockpit, against a host that remembers what was done to it.
 *
 * Every other Web test in this feature mounts one piece — a view, the shell, the dialogs —
 * over a host state it was handed. This file mounts `App` itself over nothing but a fake
 * `fetch`: the real `HostProvider` asks which host answered, exchanges the launch nonce for
 * the app token, lists the registry, and only then does the real route tree exist. So what
 * is asserted here is not that a component behaves, but that the pieces meet — which is
 * where a multi-project bug can actually live.
 *
 * The invariant the file is built around is **no crossed project data**. Each project in
 * `statefulAppDaemon` answers the same routes from the same fixtures except for one claim
 * statement, so "the left project's sentence is on screen and the right project's is not"
 * is a statement about which client the cockpit built and which URL it read it from. The
 * rest follows the failure modes of spec §10 and the end-to-end list of §13.4: a deep link
 * restores a project rather than a variable, a cancelled picker mutates nothing, a machine
 * with no folder dialog can still say which folder, a replayed nonce is an error rather
 * than a silent downgrade, and Forget says in words that it deletes nothing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BOOTSTRAP_EXPIRED_EXPLANATION } from './host';
import {
  CANCELLED_FOLDER,
  FIXTURES,
  NO_PICKER_FOLDER,
  expectNoAxeViolations,
  fakeDaemon,
  nativeFolder,
  renderMultiProjectApp,
  statefulAppDaemon,
} from '../test/harness';
import type { ProjectSeed } from '../test/harness';

/** Where the application token lives for this tab only (design §8.1). */
const APP_TOKEN_KEY = 'research-harness.app-token';

const LEFT: ProjectSeed = {
  project_id: 'prj_left',
  display_name: 'Latency study',
  path: '/research/latency-study',
  claim: 'left claim',
};
const RIGHT: ProjectSeed = {
  project_id: 'prj_right',
  display_name: 'Thermal tolerance',
  path: '/research/thermal',
  claim: 'right claim',
};
/** The folder that was on a drive nobody has plugged in: the one failure Locate can fix. */
const MOVED: ProjectSeed = {
  project_id: 'prj_reef',
  display_name: 'Reef survey',
  path: '/mnt/usb/reef-survey',
  availability: 'unavailable',
  detail: 'The folder /mnt/usb/reef-survey is not readable from here.',
  claim: 'reef claim',
};

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * The project rows, and not the run each of them sits in.
 *
 * Project Home groups the registry by when each project was last opened, so the list
 * named "Registered projects" holds one item per run and the rows live in a nested list
 * under each run's naming line. A row is a list item whose own list is not the outer one.
 */
function rows(): HTMLElement[] {
  const list = screen.getByRole('list', { name: 'Registered projects' });
  return within(list)
    .getAllByRole('listitem')
    .filter((item) => item.closest('ul') !== list);
}

function rowNames(): (string | null)[] {
  return rows().map((row) => within(row).getByRole('heading').textContent);
}

function rowFor(name: string): HTMLElement {
  const row = rows().find((item) => within(item).queryByRole('heading', { name }) !== null);
  if (!row) throw new Error(`Project Home has no row for ${name}: ${rowNames().join(', ')}`);
  return row;
}

/** Everything this origin has written down, so a test can assert a secret is not in it. */
function storedValues(): string[] {
  const values: string[] = [];
  for (const store of [window.sessionStorage, window.localStorage]) {
    for (let index = 0; index < store.length; index += 1) {
      const key = store.key(index);
      if (key) values.push(key, store.getItem(key) ?? '');
    }
  }
  return values;
}

describe('the multi-project application', () => {
  it(
    'creates, switches, refreshes, locates, and forgets without crossing project data',
    async () => {
      const user = userEvent.setup();
      const daemon = statefulAppDaemon({
        projects: [LEFT, RIGHT, MOVED],
        folders: [nativeFolder('/research'), nativeFolder('/research/reef-survey')],
      });
      renderMultiProjectApp(daemon);

      // -- Project Home lists what the host holds, in the host's order -----------------
      expect(
        await screen.findByRole('heading', { name: 'Your research projects' }),
      ).toBeInTheDocument();
      expect(rowNames()).toEqual(['Latency study', 'Thermal tolerance', 'Reef survey']);

      // -- create: a name, a parent folder a human chose, and the app opens it ----------
      await user.click(screen.getByRole('button', { name: 'New project' }));
      await user.type(await screen.findByLabelText('Project name'), 'Fresh study');
      await user.click(screen.getByRole('button', { name: 'Choose parent folder' }));
      await screen.findByText('/research');
      await user.click(screen.getByRole('button', { name: 'Create project' }));

      await waitFor(() =>
        expect(daemon.callsTo('POST', '/api/projects/create')[0]?.body).toEqual({
          parent: '/research',
          name: 'Fresh study',
          policy: 'strict',
        }),
      );
      // Creating opens it, so the shell — and its switcher — is now on screen.
      expect(
        await screen.findByRole('button', { name: /Project: Fresh study\./ }),
      ).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /Switch project/ }));
      await user.click(await screen.findByRole('menuitem', { name: 'All projects' }));
      await screen.findByRole('heading', { name: 'Your research projects' });
      expect(rowNames()).toEqual([
        'Fresh study',
        'Latency study',
        'Thermal tolerance',
        'Reef survey',
      ]);

      // -- open the left project, and read its claim through the rail -------------------
      await user.click(within(rowFor('Latency study')).getByRole('button', { name: 'Open' }));
      await user.click(await screen.findByRole('link', { name: /Claims/ }));

      expect(await screen.findByText('left claim')).toBeInTheDocument();
      expect(screen.queryByText('right claim')).not.toBeInTheDocument();

      // -- switch to the right project: the other project's claim, and only it ----------
      await user.click(screen.getByRole('button', { name: /Switch project/ }));
      await user.click(await screen.findByRole('menuitem', { name: /Thermal tolerance/ }));
      await user.click(await screen.findByRole('link', { name: /Claims/ }));

      expect(await screen.findByText('right claim')).toBeInTheDocument();
      expect(screen.queryByText('left claim')).not.toBeInTheDocument();
      expect(daemon.paths()).toContain('/api/projects/prj_right/overview');

      // -- rename the open project from the rail; the list is what changed --------------
      await user.click(screen.getByRole('button', { name: 'Project actions' }));
      await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
      const field = await screen.findByLabelText('Display name');
      await user.clear(field);
      await user.type(field, 'Thermal tolerance II');
      await user.click(screen.getByRole('button', { name: 'Rename project' }));

      await waitFor(() =>
        expect(daemon.project('prj_right')?.display_name).toBe('Thermal tolerance II'),
      );
      expect(
        await screen.findByRole('button', { name: /Project: Thermal tolerance II\./ }),
      ).toBeInTheDocument();

      // -- locate the project whose folder moved ---------------------------------------
      await user.click(screen.getByRole('button', { name: /Switch project/ }));
      await user.click(await screen.findByRole('menuitem', { name: 'All projects' }));
      await screen.findByRole('heading', { name: 'Your research projects' });
      await user.click(within(rowFor('Reef survey')).getByRole('button', { name: 'Locate folder' }));

      await waitFor(() =>
        expect(daemon.callsTo('POST', '/api/projects/prj_reef/locate')[0]?.body).toEqual({
          path: '/research/reef-survey',
        }),
      );
      // Changed on purpose: this used to wait for an "Available" badge. Project Home
      // badges an availability only where it is not simply available, so a located folder
      // is proved by the refusal leaving the row, not by a new word arriving on it.
      await waitFor(() =>
        expect(within(rowFor('Reef survey')).queryByText('Unavailable')).toBeNull(),
      );
      expect(within(rowFor('Reef survey')).getByRole('button', { name: 'Open' })).toBeEnabled();
      expect(within(rowFor('Reef survey')).getByText('/research/reef-survey')).toBeInTheDocument();

      // -- forget: a row leaves the list, and nothing leaves the disk -------------------
      await user.click(
        within(rowFor('Latency study')).getByRole('button', { name: 'Project actions' }),
      );
      await user.click(await screen.findByRole('menuitem', { name: 'Forget project' }));
      const confirm = await screen.findByRole('alertdialog', { name: 'Forget project' });
      expect(within(confirm).getByText(/files remain on disk/)).toBeInTheDocument();
      expect(daemon.callsTo('DELETE', '/api/projects/prj_left')).toHaveLength(0);

      await user.click(within(confirm).getByRole('button', { name: 'Forget project' }));

      await waitFor(() => expect(daemon.project('prj_left')).toBeNull());
      await screen.findByRole('heading', { name: 'Your research projects' });
      await waitFor(() => expect(rowNames()).not.toContain('Latency study'));
      expect(daemon.callsTo('DELETE', '/api/projects/prj_left')).toHaveLength(1);
      expect(daemon.files('prj_left')).toEqual([
        'research.yaml',
        'corpus/',
        'claims/',
        'events/',
      ]);
      expect(daemon.filesRemoved).toBe(false);
    },
    30000,
  );
});

describe('a browser refresh and a deep link', () => {
  it('restores the project the URL names, and asks nothing of any other', async () => {
    const daemon = statefulAppDaemon({ projects: [LEFT, RIGHT] });
    renderMultiProjectApp(daemon, { route: '/projects/prj_right/claims/C0001' });

    // The claim page prints the statement more than once — as the page description and
    // inside the claim card — so what matters is that it is there and the other is not.
    expect((await screen.findAllByText('right claim')).length).toBeGreaterThan(0);
    expect(screen.queryAllByText('left claim')).toHaveLength(0);

    const scoped = daemon.paths().filter((path) => path.startsWith('/api/projects/'));
    expect(scoped.length).toBeGreaterThan(0);
    expect(scoped.every((path) => path.startsWith('/api/projects/prj_right/'))).toBe(true);
    expect(daemon.paths().some((path) => path.includes('prj_left'))).toBe(false);
  });

  it('reloads on the stored application token, without a second bootstrap', async () => {
    window.sessionStorage.setItem(APP_TOKEN_KEY, 'app-token');
    const daemon = statefulAppDaemon({ projects: [LEFT] });
    // A reload carries no nonce: the launch link was single-use and is long gone.
    renderMultiProjectApp(daemon, { route: '/projects/prj_left/claims/C0001', bootstrap: null });

    expect((await screen.findAllByText('left claim')).length).toBeGreaterThan(0);
    expect(daemon.callsTo('POST', '/api/app/session')).toHaveLength(0);
  });

  it('lands an unknown project id on Project Home with a notice, and opens no client', async () => {
    const daemon = statefulAppDaemon({ projects: [LEFT, RIGHT] });
    renderMultiProjectApp(daemon, { route: '/projects/prj_ffffffffffffffff/overview' });

    expect(
      await screen.findByText(/No registered project has the id prj_ffffffffffffffff/),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Your research projects' })).toBeInTheDocument();
    expect(daemon.paths().some((path) => path.includes('prj_ffffffffffffffff'))).toBe(false);
  });
});

describe('the native folder picker', () => {
  it('mutates nothing at all when the researcher cancels it', async () => {
    const user = userEvent.setup();
    const daemon = statefulAppDaemon({ projects: [LEFT], folders: [CANCELLED_FOLDER] });
    renderMultiProjectApp(daemon);

    await screen.findByRole('heading', { name: 'Your research projects' });
    await user.click(screen.getByRole('button', { name: 'Open folder' }));

    await waitFor(() => expect(daemon.callsTo('POST', '/api/dialogs/folder')).toHaveLength(1));
    // The implementation treats a cancelled picker as a normal answer and closes.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(daemon.callsTo('POST', '/api/projects/open')).toHaveLength(0);
    expect(daemon.callsTo('POST', '/api/projects/create')).toHaveLength(0);
    expect(daemon.callsTo('POST', '/api/projects/initialize')).toHaveLength(0);
    expect(daemon.projects()).toHaveLength(1);
  });

  it('offers a typed path on a Linux box with no folder dialog, and sends it', async () => {
    const user = userEvent.setup();
    const daemon = statefulAppDaemon({ projects: [LEFT], folders: [NO_PICKER_FOLDER] });
    renderMultiProjectApp(daemon);

    await screen.findByRole('heading', { name: 'Your research projects' });
    await user.click(screen.getByRole('button', { name: 'Open folder' }));

    const typed = await screen.findByLabelText('Folder path');
    expect(screen.getByText(/no folder dialog available/)).toBeInTheDocument();
    await user.type(typed, '/home/lee/reef-survey');
    await user.click(screen.getByRole('button', { name: 'Open project' }));

    await waitFor(() =>
      expect(daemon.callsTo('POST', '/api/projects/open')[0]?.body).toEqual({
        path: '/home/lee/reef-survey',
      }),
    );
    await waitFor(() => expect(daemon.projects()).toHaveLength(2));
  });
});

describe('the launch bootstrap', () => {
  it('exchanges the nonce once, keeps the token for the tab, and writes the nonce nowhere', async () => {
    const daemon = statefulAppDaemon({ projects: [LEFT], token: 'app-token-42' });
    renderMultiProjectApp(daemon, { bootstrap: 'single-use-nonce' });

    await screen.findByRole('heading', { name: 'Your research projects' });

    // The nonce is worthless once spent, so it leaves the address bar and is never stored.
    expect(window.location.search).toBe('');
    expect(window.location.href).not.toContain('single-use-nonce');
    expect(storedValues()).not.toContain('single-use-nonce');
    // The token is the tab's, not the browser's: `sessionStorage`, never `localStorage`.
    expect(window.sessionStorage.getItem(APP_TOKEN_KEY)).toBe('app-token-42');
    expect(window.localStorage.getItem(APP_TOKEN_KEY)).toBeNull();
    expect(daemon.callsTo('POST', '/api/app/session')[0]?.body).toEqual({
      bootstrap: 'single-use-nonce',
    });
    expect(daemon.callsTo('GET', '/api/projects')[0]?.headers?.Authorization).toBe(
      'Bearer app-token-42',
    );
  });

  it('reports a replayed launch link rather than falling back to the legacy cockpit', async () => {
    const daemon = statefulAppDaemon({ projects: [LEFT], sessionStatus: 401 });
    renderMultiProjectApp(daemon, { bootstrap: 'already-used' });

    expect(await screen.findByText(BOOTSTRAP_EXPIRED_EXPLANATION)).toBeInTheDocument();
    expect(BOOTSTRAP_EXPIRED_EXPLANATION).toContain('research app');
    // Neither route tree: not Project Home, and emphatically not one workspace's cockpit.
    expect(screen.queryByRole('heading', { name: 'Your research projects' })).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Project navigation' })).toBeNull();
    expect(window.sessionStorage.getItem(APP_TOKEN_KEY)).toBeNull();
    expect(daemon.callsTo('GET', '/api/projects')).toHaveLength(0);
  });
});

describe('a legacy single-workspace daemon', () => {
  it('serves the cockpit it always served, with nothing to switch between', async () => {
    // `research serve` has no `/api/app/health`; the 404 is the whole of the detection.
    const daemon = fakeDaemon();
    vi.stubGlobal('fetch', daemon.fetch);
    renderMultiProjectApp(daemon, { route: '/', bootstrap: null });

    await screen.findByRole('navigation', { name: 'Project navigation' });
    expect(screen.getByText(FIXTURES.overview.project)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Switch project/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Project actions' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add project' })).toBeNull();
    expect(screen.getByRole('link', { name: /Review inbox/ })).toHaveAttribute('href', '/review');
    expect(daemon.calls.some((call) => call.path.startsWith('/api/projects'))).toBe(false);
    expect(window.sessionStorage.getItem(APP_TOKEN_KEY)).toBeNull();
  });
});

describe('accessibility', () => {
  it('has no automatically detectable violation on Project Home', async () => {
    const { container } = renderMultiProjectApp(
      statefulAppDaemon({ projects: [LEFT, RIGHT, MOVED] }),
    );

    await screen.findByRole('heading', { name: 'Your research projects' });
    await expectNoAxeViolations(container);
  });

  it('has no automatically detectable violation on a project workspace page', async () => {
    const { container } = renderMultiProjectApp(statefulAppDaemon({ projects: [LEFT, RIGHT] }), {
      route: '/projects/prj_left/claims',
    });

    await screen.findByText('left claim');
    await expectNoAxeViolations(container);
  });
});

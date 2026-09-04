/**
 * Task 10.6: two route trees, one set of workspace screens.
 *
 * The property being defended is that the workspace views did not change. The same
 * `/claims/:claimId` route renders the same page in both hosts; all that differs is the
 * base URL the client underneath is pinned to. So the assertions come in pairs — the legacy
 * daemon must still see `/objects/C0001`, and the multi-project host must see
 * `/api/projects/prj_abc/objects/C0001` — because a prefix applied twice, or in the view
 * layer, would break exactly one of them.
 *
 * The rest is the shell's own judgement: an id that is not in the registry is a notice on
 * Project Home rather than a client aimed at a project that does not exist, and the
 * remembered project is resumed once, on the way in, for a bare `/` only (spec §4.2).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { AppClient } from '../api/projects';
import type { ProjectView } from '../api/projects';
import { App } from './App';
import { LAST_PROJECT_KEY } from './projectPaths';
import {
  FIXTURES,
  fakeAppDaemon,
  fakeDaemon,
  projectView,
  renderWithHost,
} from '../test/harness';

const CLAIM = 'C0001';
const AVAILABLE = projectView();

/** What the claim detail page reads, whichever host it is talking to. */
const WORKSPACE = {
  gets: { '/overview': FIXTURES.overview, [`/objects/${CLAIM}`]: FIXTURES.claim },
  capabilities: {
    'claim.find_support': FIXTURES.claimSupport,
    'decision.list': { count: 0, decisions: [] },
    'anchor.list': { count: 0, anchors: [] },
  },
};

function renderMulti(route: string, projects: readonly ProjectView[] = [AVAILABLE]) {
  const daemon = fakeAppDaemon({ projects, workspace: WORKSPACE });
  const appClient = new AppClient({
    baseUrl: 'http://app.test',
    token: 'app-token',
    fetchImpl: daemon.fetch,
  });
  const view = renderWithHost(<App />, {
    route,
    path: '*',
    host: { mode: 'multi', projects, appClient },
  });
  return { ...view, daemon };
}

function renderLegacy(route: string) {
  const daemon = fakeDaemon(WORKSPACE);
  vi.stubGlobal('fetch', daemon.fetch);
  const view = renderWithHost(<App />, {
    route,
    path: '*',
    host: { mode: 'legacy', appClient: null, projects: [] },
  });
  return { ...view, daemon };
}

beforeEach(() => {
  window.localStorage.removeItem(LAST_PROJECT_KEY);
});

describe('the legacy route tree', () => {
  it('keeps the workspace at the paths it has always had', async () => {
    const { daemon } = renderLegacy(`/claims/${CLAIM}`);

    await waitFor(() => expect(screen.getByText('Requested strength')).toBeInTheDocument());
    expect(daemon.calls.map((call) => call.path)).toContain(`/objects/${CLAIM}`);
    expect(daemon.calls.every((call) => !call.path.startsWith('/api/projects'))).toBe(true);
  });
});

describe('the multi-project route tree', () => {
  it('puts Project Home at the root', async () => {
    renderMulti('/');

    expect(
      await screen.findByRole('heading', { name: 'Your research projects' }),
    ).toBeInTheDocument();
  });

  it('renders a deep link through the project-scoped client', async () => {
    const { daemon } = renderMulti(`/projects/prj_abc/claims/${CLAIM}`);

    await waitFor(() => expect(screen.getByText('Requested strength')).toBeInTheDocument());
    expect(daemon.calls.map((call) => call.path)).toContain(
      `/api/projects/prj_abc/objects/${CLAIM}`,
    );
    expect(daemon.calls.map((call) => call.path)).toContain('/api/projects/prj_abc/overview');
  });

  it('sends an unknown project id to Project Home with a notice, and opens no client', async () => {
    const { daemon } = renderMulti('/projects/prj_gone/claims/C0001');

    expect(
      await screen.findByText(/No registered project has the id prj_gone/),
    ).toBeInTheDocument();
    expect(daemon.calls.every((call) => !call.path.includes('prj_gone'))).toBe(true);
  });

  it('sends an unknown path back to Project Home', async () => {
    renderMulti('/review');

    expect(
      await screen.findByRole('heading', { name: 'Your research projects' }),
    ).toBeInTheDocument();
  });

  it('remembers the project a workspace was opened in', async () => {
    renderMulti('/projects/prj_abc/');

    await waitFor(() => expect(window.localStorage.getItem(LAST_PROJECT_KEY)).toBe('prj_abc'));
  });
});

describe('resuming the last project', () => {
  it('reopens the most recently used available project on a bare root', async () => {
    window.localStorage.setItem(LAST_PROJECT_KEY, 'prj_abc');
    const { daemon } = renderMulti('/');

    await waitFor(() =>
      expect(daemon.calls.map((call) => call.path)).toContain('/api/projects/prj_abc/overview'),
    );
  });

  it('stays on Project Home when the remembered project cannot be opened', async () => {
    window.localStorage.setItem(LAST_PROJECT_KEY, 'prj_abc');
    renderMulti('/', [projectView({ availability: 'unavailable' })]);

    expect(
      await screen.findByRole('heading', { name: 'Your research projects' }),
    ).toBeInTheDocument();
  });

  it('stays on Project Home when the remembered project is no longer registered', async () => {
    window.localStorage.setItem(LAST_PROJECT_KEY, 'prj_gone');
    renderMulti('/');

    expect(
      await screen.findByRole('heading', { name: 'Your research projects' }),
    ).toBeInTheDocument();
  });

  it('does not resume a URL that named something else', async () => {
    window.localStorage.setItem(LAST_PROJECT_KEY, 'prj_abc');
    renderMulti('/?bootstrap=stripped');

    expect(
      await screen.findByRole('heading', { name: 'Your research projects' }),
    ).toBeInTheDocument();
  });
});

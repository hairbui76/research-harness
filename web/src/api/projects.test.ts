/**
 * Task 9.1: the control-plane client shapes each request the multi-project host's closed
 * request models expect, carries the app token on every one of them, and turns a refusal
 * into the host's own stable code.
 *
 * The one assertion that matters most is the last group: a project-scoped `HarnessClient`
 * puts the opaque id in the path and nothing else, because a workspace root must never
 * reach a capability, byte, run or manuscript request (design §6).
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { runEventsUrl } from './sse';
import { AppClient, ControlError } from './projects';
import { readBootstrap, storeAppToken, storedAppToken } from './session';
import { fakeAppDaemon, FIXTURES, projectView } from '../test/harness';

function appClient(daemon = fakeAppDaemon(), token: string | null = 'app-token') {
  return new AppClient({ baseUrl: 'http://app.test', token, fetchImpl: daemon.fetch });
}

/** A `Location` for a URL the test names, without navigating the jsdom window. */
function locationAt(href: string): Location {
  return { href } as Location;
}

describe('the project control plane', () => {
  it('reports a multi-project host by kind, not by the status alone', async () => {
    const health = await appClient().health();
    expect(health).toEqual({ ok: true, kind: 'multi_project', version: '0.3.0' });
  });

  it('refuses to read the legacy daemon’s SPA fallback as a multi-project host', async () => {
    const daemon = fakeAppDaemon({ health: '<!doctype html><title>cockpit</title>' });
    await expect(appClient(daemon).health()).rejects.toMatchObject({
      code: 'not_multi_project',
    });
  });

  it('lists the registry in the order the host sent it', async () => {
    const rows = [projectView(), projectView({ project_id: 'prj_two', display_name: 'Second' })];
    const daemon = fakeAppDaemon({ projects: rows });

    expect(await appClient(daemon).projects()).toEqual(rows);
    expect(daemon.calls[0]).toMatchObject({
      method: 'GET',
      path: '/api/projects',
      headers: { Authorization: 'Bearer app-token' },
    });
  });

  it('sends each lifecycle body the host’s closed models declare', async () => {
    const daemon = fakeAppDaemon({ projects: [projectView()] });
    const app = appClient(daemon);

    await app.createProject('D:\\research', 'Latency study');
    await app.openProject('/research/latency-study');
    await app.initializeProject('/research/plain-folder', 'Plain folder');
    await app.locateProject('prj_abc', '/moved/latency-study');
    await app.renameProject('prj_abc', 'Latency study II');
    await app.revealProject('prj_abc');
    await app.forgetProject('prj_abc');

    expect(daemon.calls).toEqual([
      {
        method: 'POST',
        path: '/api/projects/create',
        body: { parent: 'D:\\research', name: 'Latency study', policy: 'strict' },
        headers: { Authorization: 'Bearer app-token', 'Content-Type': 'application/json' },
      },
      {
        method: 'POST',
        path: '/api/projects/open',
        body: { path: '/research/latency-study' },
        headers: { Authorization: 'Bearer app-token', 'Content-Type': 'application/json' },
      },
      {
        method: 'POST',
        path: '/api/projects/initialize',
        body: { path: '/research/plain-folder', name: 'Plain folder', policy: 'strict' },
        headers: { Authorization: 'Bearer app-token', 'Content-Type': 'application/json' },
      },
      {
        method: 'POST',
        path: '/api/projects/prj_abc/locate',
        body: { path: '/moved/latency-study' },
        headers: { Authorization: 'Bearer app-token', 'Content-Type': 'application/json' },
      },
      {
        method: 'PATCH',
        path: '/api/projects/prj_abc',
        body: { display_name: 'Latency study II' },
        headers: { Authorization: 'Bearer app-token', 'Content-Type': 'application/json' },
      },
      {
        method: 'POST',
        path: '/api/projects/prj_abc/reveal',
        body: null,
        headers: { Authorization: 'Bearer app-token' },
      },
      {
        method: 'DELETE',
        path: '/api/projects/prj_abc',
        body: null,
        headers: { Authorization: 'Bearer app-token' },
      },
    ]);
  });

  it('asks the host to run the folder dialog and reads cancellation as a normal result', async () => {
    const daemon = fakeAppDaemon({
      folder: { path: null, method: null, cancelled: true, fallback_required: false },
    });
    const selection = await appClient(daemon).chooseFolder('Choose a parent folder');

    expect(daemon.calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/dialogs/folder',
      body: { title: 'Choose a parent folder' },
    });
    expect(selection.cancelled).toBe(true);
  });

  it('reads a Linux box with no picker as a typed-path fallback, not as an error', async () => {
    const daemon = fakeAppDaemon({
      folder: { path: null, method: null, cancelled: false, fallback_required: true },
    });
    expect(await appClient(daemon).chooseFolder('Choose')).toMatchObject({
      fallback_required: true,
    });
  });

  it('sends no Authorization header before the bootstrap has been exchanged', async () => {
    const daemon = fakeAppDaemon();
    await appClient(daemon, null).health();
    expect(daemon.calls[0]!.headers).toEqual({});
  });

  it('carries the token a `withToken` copy was given', async () => {
    const daemon = fakeAppDaemon();
    await appClient(daemon, null).withToken('fresh').projects();
    expect(daemon.calls[0]!.headers).toEqual({ Authorization: 'Bearer fresh' });
  });
});

describe('control-plane refusals', () => {
  it('carries the host’s code out of a FastAPI `detail` envelope', async () => {
    const daemon = fakeAppDaemon({ sessionStatus: 401 });
    const failure = await appClient(daemon)
      .session('replayed')
      .catch((cause: unknown) => cause);

    expect(failure).toBeInstanceOf(ControlError);
    expect(failure).toMatchObject({
      status: 401,
      code: 'control_permission_denied',
      message: 'bootstrap already used',
    });
  });

  it('carries the host’s code out of a top-level envelope just as well', async () => {
    const fetchImpl = (async () =>
      new Response(
        JSON.stringify({ code: 'project_needs_initialization', message: 'no research.yaml' }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      )) as unknown as typeof fetch;
    const app = new AppClient({ baseUrl: 'http://app.test', token: 'app-token', fetchImpl });

    await expect(app.openProject('/research/plain-folder')).rejects.toMatchObject({
      status: 409,
      code: 'project_needs_initialization',
      message: 'no research.yaml',
    });
  });
});

describe('the project-scoped workspace client', () => {
  it('scopes a workspace client beneath the opaque project id', async () => {
    const daemon = fakeAppDaemon({ workspace: { gets: { '/overview': FIXTURES.overview } } });

    await appClient(daemon).workspaceClient('prj_abc').overview();

    expect(daemon.calls[0]?.path).toBe('/api/projects/prj_abc/overview');
    expect(daemon.workspace.calls[0]?.path).toBe('/overview');
  });

  it('never puts a workspace root in a capability request', async () => {
    const daemon = fakeAppDaemon({
      workspace: { capabilities: { 'state.index': FIXTURES.index } },
    });

    await appClient(daemon).workspaceClient('prj abc/../other').index();

    expect(daemon.calls[0]?.path).toBe('/api/projects/prj%20abc%2F..%2Fother/capabilities/state.index');
    expect(daemon.workspace.capabilityCalls()).toEqual([{ name: 'state.index', request: {} }]);
  });

  it('puts every byte and stream URL beneath the same prefix', () => {
    const workspace = appClient().workspaceClient('prj_abc');

    expect(workspace.artifactBytesUrl('A0001-1')).toBe(
      'http://app.test/api/projects/prj_abc/artifacts/A0001-1/bytes?token=app-token',
    );
    expect(workspace.manuscriptBuildPdfUrl('latest')).toBe(
      'http://app.test/api/projects/prj_abc/manuscript/builds/latest/pdf?token=app-token',
    );
    expect(runEventsUrl(workspace.stream.baseUrl, 'run_1')).toBe(
      'http://app.test/api/projects/prj_abc/runs/run_1/events',
    );
  });
});

describe('the application session token', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('reads and strips the one-time bootstrap without persisting it', () => {
    const bootstrap = readBootstrap(locationAt('http://localhost/?bootstrap=once'));

    expect(bootstrap).toBe('once');
    expect(window.sessionStorage.getItem('research-harness.bootstrap')).toBeNull();
    expect(window.location.search).not.toContain('bootstrap');
  });

  it('leaves an ordinary URL alone and reports no bootstrap', () => {
    expect(readBootstrap(locationAt('http://localhost/projects/prj_abc/'))).toBeNull();
  });

  it('keeps the app token in sessionStorage, which dies with the tab', () => {
    storeAppToken('app-token');

    expect(storedAppToken()).toBe('app-token');
    expect(window.sessionStorage.getItem('research-harness.app-token')).toBe('app-token');
    expect(window.localStorage.getItem('research-harness.app-token')).toBeNull();

    storeAppToken(null);
    expect(storedAppToken()).toBeNull();
  });

  it('exchanges the nonce for a token and sends the nonce nowhere else', async () => {
    const daemon = fakeAppDaemon({ token: 'app-token' });

    expect(await appClient(daemon, null).session('once')).toBe('app-token');
    expect(daemon.calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/app/session',
      body: { bootstrap: 'once' },
      headers: { 'Content-Type': 'application/json' },
    });
  });
});

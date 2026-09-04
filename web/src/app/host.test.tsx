/**
 * Task 9.2: the bundle asks once which host it is inside, and everything else follows.
 *
 * The two failure classifications carry the security weight. A 404 is the legacy daemon and
 * must keep working exactly as it did; a network failure is *not* the legacy daemon, and
 * misreading it as one would silently point the whole cockpit at whatever single workspace
 * happened to answer next. A replayed bootstrap is an authentication error, never a quiet
 * downgrade to an unauthenticated read.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AppClient } from '../api/projects';
import { HostProvider, useHost } from './host';
import { fakeAppDaemon, projectView } from '../test/harness';

/** Everything a test needs to read off the host, as text. */
function HostReport() {
  const host = useHost();
  return (
    <dl>
      <dt>mode</dt>
      <dd data-testid="mode">{host.mode}</dd>
      <dt>projects</dt>
      <dd data-testid="projects">{host.projects.map((project) => project.project_id).join(',')}</dd>
      <dt>auth</dt>
      <dd data-testid="auth">{host.authRequired ? 'required' : 'held'}</dd>
      <dt>error</dt>
      <dd data-testid="error">{host.error ?? ''}</dd>
    </dl>
  );
}

function locationAt(href: string): Location {
  return { href } as Location;
}

function renderHost(options: {
  fetchImpl: typeof fetch;
  href?: string;
}) {
  const appClient = new AppClient({
    baseUrl: 'http://app.test',
    token: null,
    fetchImpl: options.fetchImpl,
  });
  return render(
    <HostProvider appClient={appClient} location={locationAt(options.href ?? 'http://app.test/')}>
      <HostReport />
    </HostProvider>,
  );
}

async function settledMode(): Promise<string> {
  await waitFor(() => expect(screen.getByTestId('mode')).not.toHaveTextContent('loading'));
  return screen.getByTestId('mode').textContent ?? '';
}

describe('host detection', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('starts in loading before the health probe has answered', () => {
    renderHost({ fetchImpl: (() => new Promise(() => {})) as unknown as typeof fetch });
    expect(screen.getByTestId('mode')).toHaveTextContent('loading');
  });

  it('selects the multi-project host and lists its registry', async () => {
    window.sessionStorage.setItem('research-harness.app-token', 'app-token');
    const daemon = fakeAppDaemon({
      projects: [projectView(), projectView({ project_id: 'prj_two' })],
    });
    renderHost({ fetchImpl: daemon.fetch });

    expect(await settledMode()).toBe('multi');
    expect(screen.getByTestId('projects')).toHaveTextContent('prj_abc,prj_two');
    expect(screen.getByTestId('auth')).toHaveTextContent('held');
  });

  it('selects legacy when the app health route does not exist', async () => {
    const daemon = fakeAppDaemon({ health: null });
    renderHost({ fetchImpl: daemon.fetch });

    expect(await settledMode()).toBe('legacy');
    expect(daemon.calls.map((call) => call.path)).toEqual(['/api/app/health']);
  });

  it('selects legacy when the daemon answers its SPA fallback rather than a health body', async () => {
    const daemon = fakeAppDaemon({ health: '<!doctype html><title>cockpit</title>' });
    renderHost({ fetchImpl: daemon.fetch });

    expect(await settledMode()).toBe('legacy');
  });

  it('never mistakes an unreachable host for the legacy daemon', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;
    renderHost({ fetchImpl });

    expect(await settledMode()).toBe('error');
    expect(screen.getByTestId('error')).toHaveTextContent('Failed to fetch');
  });

  it('reports a registry the host could not read as an error, not as an empty registry', async () => {
    window.sessionStorage.setItem('research-harness.app-token', 'app-token');
    const daemon = fakeAppDaemon();
    const failing = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/api/projects')) {
        return new Response(JSON.stringify({ detail: { code: 'project_invalid', message: 'bad registry' } }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return daemon.fetch(input, init);
    }) as unknown as typeof fetch;
    renderHost({ fetchImpl: failing });

    expect(await settledMode()).toBe('error');
    expect(screen.getByTestId('error')).toHaveTextContent('bad registry');
  });
});

describe('the bootstrap exchange', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('exchanges the launch nonce, keeps the token, and keeps the nonce nowhere', async () => {
    const daemon = fakeAppDaemon({ token: 'app-token', projects: [projectView()] });
    renderHost({ fetchImpl: daemon.fetch, href: 'http://app.test/?bootstrap=once' });

    expect(await settledMode()).toBe('multi');
    expect(window.sessionStorage.getItem('research-harness.app-token')).toBe('app-token');
    expect(JSON.stringify(window.sessionStorage)).not.toContain('once');
    expect(JSON.stringify(window.localStorage)).not.toContain('once');
    expect(window.location.search).not.toContain('bootstrap');
  });

  it('reads the registry with the token the exchange returned', async () => {
    const daemon = fakeAppDaemon({ token: 'app-token', projects: [projectView()] });
    renderHost({ fetchImpl: daemon.fetch, href: 'http://app.test/?bootstrap=once' });

    await settledMode();
    const listing = daemon.calls.find(
      (call) => call.path === '/api/projects' && call.method === 'GET',
    );
    expect(listing?.headers).toEqual({ Authorization: 'Bearer app-token' });
  });

  it('renders an authentication error when the bootstrap has already been used', async () => {
    const daemon = fakeAppDaemon({ sessionStatus: 401 });
    renderHost({ fetchImpl: daemon.fetch, href: 'http://app.test/?bootstrap=replayed' });

    expect(await settledMode()).toBe('error');
    expect(screen.getByTestId('error')).toHaveTextContent(/already been used or has expired/i);
    expect(window.sessionStorage.getItem('research-harness.app-token')).toBeNull();
  });

  it('stays a multi-project host with no authority when the tab holds no token', async () => {
    const daemon = fakeAppDaemon({ projects: [projectView()] });
    renderHost({ fetchImpl: daemon.fetch });

    expect(await settledMode()).toBe('multi');
    expect(screen.getByTestId('auth')).toHaveTextContent('required');
    expect(screen.getByTestId('projects')).toHaveTextContent('');
    expect(daemon.calls.map((call) => call.path)).toEqual(['/api/app/health']);
  });
});

describe('the host context', () => {
  it('refuses to be read outside its provider', () => {
    const noise = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<HostReport />)).toThrow(/HostProvider/);
    noise.mockRestore();
  });
});

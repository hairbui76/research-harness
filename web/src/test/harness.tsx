/**
 * Test scaffolding: a fake daemon, and the cockpit rendered against it.
 *
 * The fixtures under `fixtures/` are real responses, exported from a real workspace by
 * `uv run python web/scripts/export_backend_json.py`. A test that hand-wrote its payloads
 * would pass against an API that no longer exists.
 */
import type { ReactElement } from 'react';
import axe from 'axe-core';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { HarnessClient } from '../api/client';
import type { FolderSelection, ProjectView } from '../api/projects';
import { AppClient } from '../api/projects';
import { App } from '../app/App';
import { HostProvider } from '../app/host';
import type { Host, HostMode } from '../app/host';
import { SessionProvider } from '../app/session';

import blocks from './fixtures/blocks.json';
import candidate from './fixtures/candidate.json';
import claim from './fixtures/claim.json';
import claimSupport from './fixtures/claim-support.json';
import index from './fixtures/index.json';
import manuscriptAnchors from './fixtures/manuscript-anchors.json';
import manuscriptAudit from './fixtures/manuscript-audit.json';
import manuscriptTrace from './fixtures/manuscript-trace.json';
import overview from './fixtures/overview.json';
import reviewInbox from './fixtures/review-inbox.json';

export const FIXTURES = {
  blocks,
  candidate,
  claim,
  claimSupport,
  index,
  manuscriptAnchors,
  manuscriptAudit,
  manuscriptTrace,
  overview,
  reviewInbox,
};

export interface RecordedCall {
  method: string;
  path: string;
  body: unknown;
  /** The request headers, for the tests that care that the token rode along. */
  headers?: Record<string, string>;
}

export interface FakeDaemon {
  fetch: typeof fetch;
  calls: RecordedCall[];
  /** Every `POST /capabilities/<name>` made so far, in order. */
  capabilityCalls(): { name: string; request: any }[];
}

/**
 * A fake daemon.
 *
 * `gets` maps a path to its JSON body; `capabilities` maps a capability name to the
 * `result` it answers with, or to a full envelope when a test needs a refusal.
 */
export function fakeDaemon(options: {
  gets?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
} = {}): FakeDaemon {
  const calls: RecordedCall[] = [];
  const gets: Record<string, unknown> = {
    '/overview': FIXTURES.overview,
    '/index': FIXTURES.index,
    ...options.gets,
  };

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://daemon.test');
    const path = url.pathname;
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, path, body });

    if (method === 'POST' && path.startsWith('/capabilities/')) {
      const name = path.slice('/capabilities/'.length);
      const answer = options.capabilities?.[name];
      if (answer === undefined) {
        return jsonResponse({
          capability: name,
          ok: false,
          error: { code: 'capability_not_found', message: `no fake answer for ${name}` },
        });
      }
      if (isEnvelope(answer)) return jsonResponse(answer);
      return jsonResponse({ capability: name, ok: true, result: answer });
    }

    if (path in gets) return jsonResponse(gets[path]);
    return new Response('not found', { status: 404 });
  });

  return {
    fetch: fetchImpl as unknown as typeof fetch,
    calls,
    capabilityCalls: () =>
      calls
        .filter((call) => call.method === 'POST' && call.path.startsWith('/capabilities/'))
        .map((call) => ({ name: call.path.slice('/capabilities/'.length), request: call.body })),
  };
}

/**
 * A whole `CapabilityResponse`, rather than the `result` a caller wrote out bare.
 *
 * `ok` alone cannot tell the two apart: `provider.cli.test` answers a report whose own
 * verdict field is `ok`, and reading that as an envelope would find no `result` and turn a
 * success into a refusal. The daemon names the capability on every envelope it sends and
 * on nothing else, so that is the discriminator.
 */
function isEnvelope(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  return 'ok' in (value as object) && 'capability' in (value as object);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export interface RenderOptions {
  daemon: FakeDaemon;
  token?: string | null;
  route?: string;
  path?: string;
}

/**
 * Render one view inside the session and the router, against a fake daemon.
 *
 * The two Design System providers are the same ones `main.tsx` mounts: `ThemeProvider`
 * (with `storageKey={null}`, so a test never writes an appearance preference into the
 * shared jsdom `localStorage`) and `ToastProvider`, which every mutation surface reports
 * through.
 */
export function renderView(ui: ReactElement, options: RenderOptions) {
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: options.token ?? 'local-token',
    fetchImpl: options.daemon.fetch,
  });
  const route = options.route ?? '/';
  const path = options.path ?? route;
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={[route]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <SessionProvider client={client}>
            <Routes>
              <Route path={path} element={ui} />
            </Routes>
          </SessionProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

/**
 * The accessibility gate every migrated view runs (DS spec §6, §12.5).
 *
 * The rules that need a layout engine or a whole document are off: jsdom computes no
 * geometry, so `color-contrast` cannot run here — the Design System verifies contrast
 * against the token values instead (`design/scripts/check-contrast.mjs`) — and page-level
 * landmark rules do not apply to a view rendered without its shell.
 */
const DISABLED_RULES = [
  'color-contrast',
  'region',
  'page-has-heading-one',
  'landmark-one-main',
  'html-has-lang',
  'document-title',
  'bypass',
];

/** Fails with the offending rule ids and target selectors when anything is violated. */
export async function expectNoAxeViolations(
  target: Element | Document = document.body,
  extraDisabledRules: readonly string[] = [],
): Promise<void> {
  const rules: axe.RuleObject = {};
  for (const rule of [...DISABLED_RULES, ...extraDisabledRules]) rules[rule] = { enabled: false };
  const results = await axe.run(target as axe.ElementContext, { rules });
  if (results.violations.length > 0) {
    const summary = results.violations
      .map(
        (violation) =>
          `${violation.id}: ${violation.help} -> ${violation.nodes
            .map((node) => node.target.join(' '))
            .join(', ')}`,
      )
      .join('\n');
    throw new Error(`Expected no accessibility violations, found:\n${summary}`);
  }
}

/** The headers a recorded call carried, normalised out of whatever shape `init` used. */
function headersOf(init?: RequestInit): Record<string, string> {
  const headers = init?.headers;
  if (!headers) return {};
  if (headers instanceof Headers) return Object.fromEntries(headers.entries());
  if (Array.isArray(headers)) return Object.fromEntries(headers);
  return { ...(headers as Record<string, string>) };
}

// -- the multi-project host ---------------------------------------------------

/** The health body a multi-project host answers with (`AppClient.health`). */
export const APP_HEALTH = { ok: true, kind: 'multi_project', version: '0.3.0' };

/** One available project, for the tests that need a row rather than a registry. */
export function projectView(overrides: Partial<ProjectView> = {}): ProjectView {
  return {
    project_id: 'prj_abc',
    display_name: 'Latency study',
    path: '/research/latency-study',
    availability: 'available',
    detail: null,
    active_runs: 0,
    last_opened_at: '2026-09-01T10:00:00Z',
    ...overrides,
  };
}

export interface FakeAppDaemonOptions {
  /** The `/api/app/health` body. `null` answers 404, as the legacy daemon does. */
  health?: unknown;
  healthStatus?: number;
  /** The registry `/api/projects` answers with. */
  projects?: readonly ProjectView[];
  /** What `/api/app/session` returns for a nonce; a `sessionStatus` makes it refuse. */
  token?: string;
  sessionStatus?: number;
  folder?: FolderSelection;
  /** The project a lifecycle route answers with; defaults to the first registered one. */
  lifecycleResult?: ProjectView;
  /** Workspace routes served beneath `/api/projects/{project_id}`. */
  workspace?: { gets?: Record<string, unknown>; capabilities?: Record<string, unknown> };
}

export interface FakeAppDaemon {
  fetch: typeof fetch;
  calls: RecordedCall[];
  /** The fake workspace daemon the project-scoped routes are delegated to. */
  workspace: FakeDaemon;
}

/** The control-plane paths that are operations rather than project ids. */
const LIFECYCLE_PATHS = new Set(['/create', '/open', '/initialize']);

/**
 * A fake multi-project host: the control plane, plus every workspace route beneath a
 * project id delegated to an ordinary `fakeDaemon`.
 *
 * That delegation is the point. A view tested through `AppClient.workspaceClient('prj_abc')`
 * makes exactly the calls it makes against the legacy daemon, and this fake answers them
 * from the same fixtures — so a test proves the prefix is applied without restating the API.
 */
export function fakeAppDaemon(options: FakeAppDaemonOptions = {}): FakeAppDaemon {
  const calls: RecordedCall[] = [];
  const workspace = fakeDaemon(options.workspace ?? {});
  const projects = options.projects ?? [];
  const health = 'health' in options ? options.health : APP_HEALTH;

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://app.test');
    const path = url.pathname;
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, path, body, headers: headersOf(init) });

    if (path === '/api/app/health') {
      if (health === null || health === undefined) return new Response('not found', { status: 404 });
      return jsonResponse(health, options.healthStatus ?? 200);
    }
    if (path === '/api/app/session') {
      const status = options.sessionStatus ?? 200;
      if (status !== 200) {
        return jsonResponse(
          { detail: { code: 'control_permission_denied', message: 'bootstrap already used' } },
          status,
        );
      }
      return jsonResponse({ token: options.token ?? 'app-token' });
    }
    if (path === '/api/dialogs/folder') {
      return jsonResponse(
        options.folder ?? { path: null, method: null, cancelled: true, fallback_required: false },
      );
    }
    if (path === '/api/projects' && method === 'GET') return jsonResponse({ projects });

    const scoped = /^\/api\/projects(\/[^/]+)(\/.*)?$/.exec(path);
    if (scoped) {
      const [, first, rest] = scoped as unknown as [string, string, string | undefined];
      const result = options.lifecycleResult ?? projects[0] ?? projectView();
      if (LIFECYCLE_PATHS.has(first) && !rest) return jsonResponse(result);
      if (!rest || rest === '/locate' || rest === '/reveal') {
        if (method === 'DELETE') return new Response(null, { status: 204 });
        return jsonResponse(result);
      }
      return workspace.fetch(`${url.origin}${rest}${url.search}`, init);
    }
    return new Response('not found', { status: 404 });
  });

  return { fetch: fetchImpl as unknown as typeof fetch, calls, workspace };
}

export interface HostOptions {
  mode?: HostMode;
  projects?: readonly ProjectView[];
  appClient?: AppClient | null;
  error?: string | null;
  authRequired?: boolean;
  refreshProjects?: () => Promise<void>;
  setProjects?: (projects: ProjectView[]) => void;
}

/** A ready-made `Host`, so a view test states the host it wants instead of faking detection. */
export function hostValue(options: HostOptions = {}): Host {
  const mode = options.mode ?? 'multi';
  return {
    mode,
    error: options.error ?? null,
    appClient:
      options.appClient === undefined
        ? mode === 'multi'
          ? new AppClient({ baseUrl: 'http://app.test', token: 'app-token' })
          : null
        : options.appClient,
    projects: [...(options.projects ?? [])],
    authRequired: options.authRequired ?? false,
    refreshProjects: options.refreshProjects ?? (async () => {}),
    setProjects: options.setProjects ?? (() => {}),
  };
}

export interface RenderWithHostOptions {
  host?: HostOptions;
  route?: string;
  path?: string;
}

/** Render one surface inside the providers `main.tsx` mounts, against a chosen host state. */
export function renderWithHost(ui: ReactElement, options: RenderWithHostOptions = {}) {
  const host = hostValue(options.host);
  const route = options.route ?? '/';
  const path = options.path ?? route;
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={[route]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <HostProvider value={host}>
            <Routes>
              <Route path={path} element={ui} />
            </Routes>
          </HostProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

// -- a stateful multi-project host ---------------------------------------------------

/**
 * The seed for one project in `statefulAppDaemon`: a registry row, plus the workspace
 * behind it.
 *
 * `claim` is the whole point of the per-project workspace. Every project answers the same
 * routes with the same fixtures except for one statement, so a test that finds the wrong
 * sentence on screen has found the cockpit reading the wrong project — which is the failure
 * this fake exists to catch (spec §13.4).
 */
export interface ProjectSeed extends Partial<ProjectView> {
  /** The statement this project's `GET /objects/C0001` answers with. */
  claim?: string;
  /** What the fake says this project's folder holds. Nothing ever removes one. */
  files?: readonly string[];
}

/** What a folder picker answers when the researcher pressed Cancel (design §7). */
export const CANCELLED_FOLDER: FolderSelection = {
  path: null,
  method: null,
  cancelled: true,
  fallback_required: false,
};

/** A Linux box with neither `zenity` nor `kdialog`: no dialog appeared, and none will. */
export const NO_PICKER_FOLDER: FolderSelection = {
  path: null,
  method: null,
  cancelled: false,
  fallback_required: true,
};

/** A folder a human chose in a native dialog. */
export function nativeFolder(path: string, method = 'zenity'): FolderSelection {
  return { path, method, cancelled: false, fallback_required: false };
}

export interface StatefulAppDaemonOptions {
  /** The registry this host starts with, in the order it lists them. */
  projects?: readonly ProjectSeed[];
  /** The `/api/app/health` body. `null` answers 404, as the legacy daemon does. */
  health?: unknown;
  /** The token `/api/app/session` hands back for a bootstrap nonce. */
  token?: string;
  /** Anything but 200 makes the exchange refuse, as a replayed nonce does. */
  sessionStatus?: number;
  /** The answers `POST /api/dialogs/folder` gives, in order; the last one repeats. */
  folders?: readonly FolderSelection[];
  /** Paths `open` refuses with `project_needs_initialization`. */
  needsInitialization?: readonly string[];
}

export interface StatefulAppDaemon {
  fetch: typeof fetch;
  calls: RecordedCall[];
  /** The registry as it stands now, in the order the host would list it. */
  projects(): ProjectView[];
  /** One registry row, or null once it has been forgotten. */
  project(projectId: string): ProjectView | null;
  /** The files the fake holds for a project, whether or not it is still registered. */
  files(projectId: string): string[];
  /** True only if something removed a file. Nothing in this fake ever does. */
  filesRemoved: boolean;
  /** Script one more picker answer, after the ones given at construction. */
  queueFolder(selection: FolderSelection): void;
  /** Every path requested, in order. */
  paths(): string[];
  /** The recorded calls for one method and path. */
  callsTo(method: string, path: string): RecordedCall[];
}

/** What a newly registered project's folder is said to hold. Forget must not change it. */
const PROJECT_FILES = ['research.yaml', 'corpus/', 'claims/', 'events/'] as const;

/** The control-plane paths beneath `/api/projects` that are operations, not project ids. */
const STATEFUL_LIFECYCLE = new Set(['/create', '/open', '/initialize']);

/**
 * A multi-project host that remembers what was done to it.
 *
 * `fakeAppDaemon` answers a script; this one keeps a registry. Create, open, initialize,
 * locate, rename and forget change the list that `GET /api/projects` returns next, so a
 * whole-app test can press a button and then assert on what the *host* now holds rather
 * than on the call it received. Forget is the case that matters most: it removes the
 * registry entry and leaves `files()` exactly as it was, because no project lifecycle
 * action deletes a researcher's work (spec §4.2, §10).
 *
 * Every project's workspace answers the same routes from the same fixtures, differing only
 * in one claim statement and in the name and path `GET /overview` reports. That is what
 * makes "the left project's sentence is on screen while the right project's is not" a real
 * assertion about which client the cockpit built.
 */
export function statefulAppDaemon(options: StatefulAppDaemonOptions = {}): StatefulAppDaemon {
  const calls: RecordedCall[] = [];
  const registry: ProjectView[] = [];
  const claims = new Map<string, string>();
  const files = new Map<string, string[]>();
  const folders: FolderSelection[] = [...(options.folders ?? [])];
  const needsInitialization = new Set(options.needsInitialization ?? []);
  const health = 'health' in options ? options.health : APP_HEALTH;
  // Nothing here ever removes a file; the flag exists so a test can say so out loud.
  const filesRemoved = false;
  let lastFolder: FolderSelection = CANCELLED_FOLDER;
  let issued = 0;

  function register(seed: ProjectSeed, front: boolean): ProjectView {
    const { claim, files: seeded, ...overrides } = seed;
    issued += 1;
    const view = projectView({
      project_id: `prj_${issued.toString(16).padStart(16, '0')}`,
      ...overrides,
    });
    claims.set(view.project_id, claim ?? `${view.display_name} claim`);
    files.set(view.project_id, [...(seeded ?? PROJECT_FILES)]);
    if (front) registry.unshift(view);
    else registry.push(view);
    return view;
  }

  for (const seed of options.projects ?? []) register(seed, false);

  function indexOf(projectId: string): number {
    return registry.findIndex((candidate) => candidate.project_id === projectId);
  }

  function replace(at: number, changes: Partial<ProjectView>): ProjectView {
    const next = { ...(registry[at] as ProjectView), ...changes };
    registry[at] = next;
    return next;
  }

  function nextFolder(): FolderSelection {
    const next = folders.shift();
    if (next) lastFolder = next;
    return next ?? lastFolder;
  }

  /** One project's workspace, answered by the same fake the legacy daemon is tested with. */
  function workspace(view: ProjectView): FakeDaemon {
    const statement = claims.get(view.project_id) ?? view.display_name;
    const summaries = FIXTURES.index.claims.map((summary) => ({ ...summary, statement }));
    return fakeDaemon({
      gets: {
        '/overview': { ...FIXTURES.overview, project: view.display_name, workspace: view.path },
        '/index': { ...FIXTURES.index, claims: summaries },
        '/objects/C0001': {
          ...FIXTURES.claim,
          object: { ...FIXTURES.claim.object, statement },
        },
      },
      capabilities: {
        'claim.list': { count: summaries.length, claims: summaries },
        'claim.find_support': { ...FIXTURES.claimSupport, statement },
        'decision.list': { count: 0, decisions: [] },
        'anchor.list': { count: 0, anchors: [] },
      },
    });
  }

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://app.test');
    const path = url.pathname;
    const method = init?.method ?? 'GET';
    const body = (init?.body ? JSON.parse(String(init.body)) : null) as Record<
      string,
      string
    > | null;
    calls.push({ method, path, body, headers: headersOf(init) });

    if (path === '/api/app/health') {
      if (health === null || health === undefined) return new Response('not found', { status: 404 });
      return jsonResponse(health);
    }
    if (path === '/api/app/session') {
      const status = options.sessionStatus ?? 200;
      if (status !== 200) return refusal(status, 'control_permission_denied', 'bootstrap used');
      return jsonResponse({ token: options.token ?? 'app-token' });
    }
    if (path === '/api/dialogs/folder') return jsonResponse(nextFolder());
    if (path === '/api/projects' && method === 'GET') return jsonResponse({ projects: registry });

    const scoped = /^\/api\/projects(\/[^/]+)(\/.*)?$/.exec(path);
    if (!scoped) return new Response('not found', { status: 404 });
    const [, first, rest] = scoped as unknown as [string, string, string | undefined];

    if (STATEFUL_LIFECYCLE.has(first) && !rest) {
      return lifecycle(first, body ?? {});
    }

    const projectId = first.slice(1);
    const at = indexOf(projectId);
    if (at < 0) return refusal(404, 'project_not_found', `no project ${projectId}`);
    const view = registry[at] as ProjectView;

    if (!rest) {
      if (method === 'DELETE') {
        // Forget removes the entry. The folder is not touched, so `files` is left alone.
        registry.splice(at, 1);
        return new Response(null, { status: 204 });
      }
      if (method === 'PATCH') {
        return jsonResponse(replace(at, { display_name: String(body?.display_name ?? '') }));
      }
      return jsonResponse(view);
    }
    if (rest === '/reveal') return jsonResponse(view);
    if (rest === '/locate') {
      const located = String(body?.path ?? '');
      if (!located) return refusal(422, 'project_invalid', 'no folder was given');
      return jsonResponse(
        replace(at, { path: located, availability: 'available', detail: null }),
      );
    }
    return workspace(view).fetch(`${url.origin}${rest}${url.search}`, init);
  });

  function lifecycle(operation: string, body: Record<string, string>): Response {
    if (operation === '/create') {
      const parent = String(body.parent ?? '');
      const name = String(body.name ?? '');
      return jsonResponse(
        register({ display_name: name, path: `${parent}/${slug(name)}` }, true),
      );
    }
    const path = String(body.path ?? '');
    if (operation === '/open') {
      if (needsInitialization.has(path)) {
        return refusal(409, 'project_needs_initialization', `${path} has no research.yaml.`);
      }
      const existing = registry.find((candidate) => candidate.path === path);
      // A path already registered opens the existing project rather than duplicating it.
      if (existing) return jsonResponse(existing);
      return jsonResponse(register({ display_name: basenameOf(path), path }, true));
    }
    return jsonResponse(register({ display_name: String(body.name ?? ''), path }, true));
  }

  return {
    fetch: fetchImpl as unknown as typeof fetch,
    calls,
    projects: () => [...registry],
    project: (projectId) => registry.find((row) => row.project_id === projectId) ?? null,
    files: (projectId) => [...(files.get(projectId) ?? [])],
    get filesRemoved() {
      return filesRemoved;
    },
    queueFolder: (selection) => folders.push(selection),
    paths: () => calls.map((call) => call.path),
    callsTo: (method, path) =>
      calls.filter((call) => call.method === method && call.path === path),
  };
}

/** The host's own refusal envelope, in the shape FastAPI wraps a raised error in. */
function refusal(status: number, code: string, message: string): Response {
  return jsonResponse({ detail: { code, message } }, status);
}

function slug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function basenameOf(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

export interface RenderMultiProjectAppOptions {
  /** Where this browser is: the router's initial entry. */
  route?: string;
  /**
   * The launch nonce in the address bar. `null` is a tab opened without one — a reload, or
   * a bookmark — which is exactly the case that must fall back to the stored app token.
   */
  bootstrap?: string | null;
}

/**
 * The whole cockpit, against a fake host: the real providers, the real detection, real
 * routes.
 *
 * Nothing is stubbed above `fetch`. `HostProvider` runs its own `GET /api/app/health`,
 * exchanges the nonce it finds in the address bar for the app token, stores it and lists
 * the registry — so the bootstrap handling of design §8.1 is exercised rather than assumed,
 * and so is the branch in `App` that turns that answer into a route tree.
 *
 * The nonce travels in `window.location` because that is the only place a real one can
 * arrive; the router is a `MemoryRouter` so a test can start anywhere without a page load.
 */
export function renderMultiProjectApp(
  daemon: { fetch: typeof fetch },
  options: RenderMultiProjectAppOptions = {},
) {
  const bootstrap = options.bootstrap === undefined ? 'once' : options.bootstrap;
  window.history.replaceState({}, '', bootstrap ? `/?bootstrap=${bootstrap}` : '/');
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={[options.route ?? '/']}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <HostProvider fetchImpl={daemon.fetch} location={window.location}>
            <App />
          </HostProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

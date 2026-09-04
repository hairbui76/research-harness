/**
 * The cockpit's client for the multi-project host's control plane.
 *
 * `HarnessClient` speaks to one workspace and knows nothing about projects; this client
 * speaks only about projects and knows nothing about research. The two meet in exactly one
 * place — `workspaceClient(projectId)` — which hands back an ordinary `HarnessClient`
 * pinned beneath `/api/projects/{project_id}`, so every existing view keeps calling the
 * routes it already calls and never learns that a project id exists (design §11).
 *
 * Authority is the app token (design §8.1): one random secret the host writes beside its
 * application data, delivered to the browser once through a bootstrap nonce and kept for
 * this browser session only. Every request here carries it as `Authorization: Bearer`.
 * The browser adds the same-origin `Origin` header the host insists on for mutations by
 * itself; setting it from script is both forbidden and pointless, so nothing here tries.
 *
 * No method takes a workspace root. Folder paths reach the host only through the three
 * lifecycle calls a human selection produced (`create`, `open`, `initialize`) and through
 * `locate`; a project-scoped request names an opaque id and nothing else.
 */
import { defaultBaseUrl, HarnessClient } from './client';

/** What the host says about a registered folder right now (design §4.2). */
export type ProjectAvailability = 'available' | 'unavailable' | 'invalid' | 'incompatible' | 'busy';

/** One row of Project Home, exactly as the control plane serialises it. */
export interface ProjectView {
  project_id: string;
  display_name: string;
  path: string;
  availability: ProjectAvailability;
  /** Why it is not simply available, in the host's words; null when there is nothing to say. */
  detail: string | null;
  active_runs: number;
  last_opened_at: string | null;
}

/**
 * The result of asking the host to open a native folder dialog.
 *
 * Cancellation is a normal result, not an error (design §7). `fallback_required` is the
 * Linux box with neither `zenity` nor `kdialog`: the UI then offers an authenticated typed
 * path instead of pretending a dialog appeared.
 */
export interface FolderSelection {
  path: string | null;
  /** How the path was chosen: `native`, `zenity`, `kdialog`, `fallback`, ... */
  method: string | null;
  cancelled: boolean;
  fallback_required: boolean;
}

/** `GET /api/app/health` on a multi-project host. The legacy daemon has no such route. */
export interface AppHealth {
  ok: boolean;
  kind: string;
  version: string;
}

/** The kind the multi-project host reports; anything else is not a host we can drive. */
export const MULTI_PROJECT_KIND = 'multi_project';

/**
 * A control-plane refusal, carrying the host's stable code.
 *
 * The codes are the ones the dialogs branch on: `project_not_found`,
 * `project_needs_initialization`, `project_active_runs`, `project_invalid`,
 * `picker_unavailable`, `control_permission_denied`. `not_multi_project` is ours: it means
 * the route answered, but not as a multi-project host would.
 */
export class ControlError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ControlError';
  }
}

export interface AppClientOptions {
  baseUrl?: string;
  token: string | null;
  fetchImpl?: typeof fetch;
}

type RequestBody = Record<string, unknown>;

export class AppClient {
  readonly baseUrl: string;
  readonly token: string | null;
  private readonly http: typeof fetch;

  constructor(options: AppClientOptions) {
    this.baseUrl = (options.baseUrl ?? defaultBaseUrl()).replace(/\/$/, '');
    this.token = options.token ?? null;
    this.http = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  /** True once the bootstrap has been exchanged and the app token is in hand. */
  get authenticated(): boolean {
    return Boolean(this.token);
  }

  /** A copy carrying a different app token; used the moment the exchange returns one. */
  withToken(token: string | null): AppClient {
    return new AppClient({ baseUrl: this.baseUrl, token, fetchImpl: this.http });
  }

  /**
   * A workspace client for one project.
   *
   * The project id is opaque and goes in the path, never in a request body: the host
   * resolves it through the registry, and no capability call can name a root (design §6).
   */
  workspaceClient(projectId: string): HarnessClient {
    return new HarnessClient({
      baseUrl: `${this.baseUrl}/api/projects/${encodeURIComponent(projectId)}`,
      token: this.token,
      fetchImpl: this.http,
    });
  }

  // -- host identity and authentication ---------------------------------------

  /**
   * Which host answered.
   *
   * Throws `ControlError` with code `not_multi_project` when the route answered with
   * anything but `{ok: true, kind: "multi_project"}` — the legacy daemon serves the SPA's
   * `index.html` for paths it does not know, so a 200 alone proves nothing.
   */
  async health(): Promise<AppHealth> {
    const body = await this.request<Partial<AppHealth>>('GET', '/api/app/health');
    if (body?.ok !== true || body.kind !== MULTI_PROJECT_KIND) {
      throw new ControlError(200, 'not_multi_project', 'This host is not a multi-project host.');
    }
    return { ok: true, kind: body.kind, version: body.version ?? '' };
  }

  /**
   * Exchange the one-time launch nonce for the app token.
   *
   * The nonce is single-use and short-lived; a replay answers 401, which the caller renders
   * as "start the app again" rather than retrying (design §8.1).
   */
  async session(bootstrap: string): Promise<string> {
    const body = await this.request<{ token?: string }>('POST', '/api/app/session', { bootstrap });
    if (!body?.token) {
      throw new ControlError(200, 'invalid_response', 'The host returned no application token.');
    }
    return body.token;
  }

  // -- the project registry ----------------------------------------------------

  /** Every registered project, in the host's most-recently-opened-first order. */
  async projects(): Promise<ProjectView[]> {
    const body = await this.request<{ projects?: ProjectView[] }>('GET', '/api/projects');
    return body?.projects ?? [];
  }

  /** Ask the host to run a native folder dialog on this machine. */
  chooseFolder(title: string): Promise<FolderSelection> {
    return this.request<FolderSelection>('POST', '/api/dialogs/folder', { title });
  }

  // -- project lifecycle -------------------------------------------------------

  createProject(parent: string, name: string, policy = 'strict'): Promise<ProjectView> {
    return this.request<ProjectView>('POST', '/api/projects/create', { parent, name, policy });
  }

  openProject(path: string): Promise<ProjectView> {
    return this.request<ProjectView>('POST', '/api/projects/open', { path });
  }

  /** Only ever after the researcher confirmed it: `open` never initializes by itself. */
  initializeProject(path: string, name: string, policy = 'strict'): Promise<ProjectView> {
    return this.request<ProjectView>('POST', '/api/projects/initialize', { path, name, policy });
  }

  /** Point an existing registry entry at the folder the researcher moved it to. */
  locateProject(projectId: string, path: string): Promise<ProjectView> {
    return this.request<ProjectView>('POST', `${this.projectPath(projectId)}/locate`, { path });
  }

  renameProject(projectId: string, displayName: string): Promise<ProjectView> {
    return this.request<ProjectView>('PATCH', this.projectPath(projectId), {
      display_name: displayName,
    });
  }

  /** Removes the registry entry only. The folder and its files are untouched. */
  async forgetProject(projectId: string): Promise<void> {
    await this.request<void>('DELETE', this.projectPath(projectId));
  }

  /** Opens the registered root in Explorer or the Linux file manager. Takes no path. */
  revealProject(projectId: string): Promise<ProjectView> {
    return this.request<ProjectView>('POST', `${this.projectPath(projectId)}/reveal`);
  }

  // -- plumbing ----------------------------------------------------------------

  private projectPath(projectId: string): string {
    return `/api/projects/${encodeURIComponent(projectId)}`;
  }

  private async request<T>(method: string, path: string, body?: RequestBody): Promise<T> {
    const headers: Record<string, string> = this.token
      ? { Authorization: `Bearer ${this.token}` }
      : {};
    const init: RequestInit = { method, headers };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const response = await this.http(`${this.baseUrl}${path}`, init);
    if (!response.ok) throw await controlError(response, path);
    if (response.status === 204) return undefined as T;
    const text = await response.text().catch(() => '');
    if (!text) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ControlError(response.status, 'not_multi_project', `${path} did not answer JSON.`);
    }
  }
}

/**
 * The host's own words for a refusal.
 *
 * FastAPI wraps a raised `HTTPException` in `detail`, while a handler that returns the
 * envelope itself puts `code`/`message` at the top level. Both shapes are accepted, so a
 * dialog reads one message and branches on one code whichever way the route answered.
 */
async function controlError(response: Response, path: string): Promise<ControlError> {
  const fallback = `${response.status} on ${path}`;
  const text = await response.text().catch(() => '');
  if (!text) return new ControlError(response.status, 'control_error', fallback);
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    const envelope = readEnvelope(parsed.detail) ?? readEnvelope(parsed);
    if (envelope) {
      return new ControlError(response.status, envelope.code, envelope.message || fallback);
    }
    if (typeof parsed.detail === 'string') {
      return new ControlError(response.status, 'control_error', parsed.detail);
    }
  } catch {
    /* not JSON: the body itself is the message */
  }
  return new ControlError(response.status, 'control_error', text || fallback);
}

function readEnvelope(value: unknown): { code: string; message: string } | null {
  if (typeof value !== 'object' || value === null) return null;
  const record = value as { code?: unknown; message?: unknown };
  if (typeof record.code !== 'string') return null;
  return { code: record.code, message: typeof record.message === 'string' ? record.message : '' };
}

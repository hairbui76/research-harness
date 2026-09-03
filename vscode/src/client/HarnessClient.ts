/**
 * The extension's whole view of the Research Harness: named capabilities over HTTP.
 *
 * This is the TypeScript twin of `research_harness/protocol/http.py::HarnessHttpClient`, and
 * it deliberately knows the same three things and no more - the routes, the envelopes, and
 * how to present a refusal. It holds no scientific rule, writes no file, and has no idea
 * what a Claim means: per ADR-004 the capability layer is the only place those live, and an
 * editor that reimplemented any of them would be the fifth copy the product exists to
 * prevent.
 *
 * Authority comes from the workspace's `.research/daemon-token`. Without it the daemon
 * treats the extension as an agent host: reads work, `manuscript.attach_claim` and
 * `claim.create` come back refused (Product 29). That refusal is the contract, so it is
 * surfaced as a `HarnessError` the commands explain, not swallowed.
 *
 * There is one read route left here (`GET /objects/{id}`, to validate a Claim id somebody
 * typed) and no other. Every list the extension shows is a named capability, so an MCP host
 * gets the same answers from the same names.
 */

import { HarnessError } from "./errors";
import type {
  CapabilityCatalog,
  CapabilityDescriptor,
  CapabilityResponse,
  HealthReport,
  ObjectView,
} from "./types";

/** Where the daemon is and who we are to it. */
export interface HarnessClientOptions {
  /** Base URL of `research serve`; loopback in every supported deployment. */
  baseUrl: string;
  /** Reads the local daemon token, or returns undefined when there is none. */
  readToken: () => Promise<string | undefined>;
  /** Injected for tests; defaults to the runtime's global `fetch`. */
  fetchImpl?: typeof fetch;
  /** Per-request timeout in milliseconds. */
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 30_000;

export class HarnessClient {
  private readonly baseUrl: string;
  private readonly readToken: () => Promise<string | undefined>;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  private catalogCache: CapabilityCatalog | undefined;
  private tokenCache: string | undefined;

  constructor(options: HarnessClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.readToken = options.readToken;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  /** Forget the cached catalog and token; call after the settings or the workspace change. */
  reset(): void {
    this.catalogCache = undefined;
    this.tokenCache = undefined;
  }

  // -- reads -----------------------------------------------------------------

  /** Whether the daemon can serve its workspace, and which workspace that is. */
  async health(): Promise<HealthReport> {
    return this.json<HealthReport>("GET", "/health");
  }

  /**
   * Every named capability with its permission and both JSON schemas.
   *
   * Cached: the catalog only changes when the daemon restarts, and the hover path asks
   * "does this build have that capability?" often enough for a round trip to be felt.
   */
  async capabilities(): Promise<CapabilityCatalog> {
    if (this.catalogCache === undefined) {
      this.catalogCache = await this.json<CapabilityCatalog>("GET", "/capabilities");
    }
    return this.catalogCache;
  }

  /** The descriptor for one capability, or undefined when this build does not carry it. */
  async describe(name: string): Promise<CapabilityDescriptor | undefined> {
    const catalog = await this.capabilities();
    return catalog.capabilities.find((item) => item.name === name);
  }

  /** True when this build implements `name`; false when it is planned or absent. */
  async has(name: string): Promise<boolean> {
    return (await this.describe(name)) !== undefined;
  }

  /** Why a Product 22 name is not callable here, when the daemon says it is planned. */
  async plannedReason(name: string): Promise<string | undefined> {
    const catalog = await this.capabilities();
    return catalog.planned.find((item) => item.name === name)?.reason;
  }

  /** One canonical object by research id. Throws `object_not_found` when there is none. */
  async object(objectId: string): Promise<ObjectView> {
    return this.json<ObjectView>("GET", `/objects/${encodeURIComponent(objectId)}`);
  }

  /** True when `objectId` names an object this workspace holds. */
  async objectExists(objectId: string): Promise<boolean> {
    try {
      await this.object(objectId);
      return true;
    } catch (error) {
      if (error instanceof HarnessError && error.code === "object_not_found") {
        return false;
      }
      throw error;
    }
  }

  // -- calls -----------------------------------------------------------------

  /**
   * Invoke one capability and return its typed result.
   *
   * A refusal arrives as `ok: false` with a stable code and is raised as a `HarnessError`,
   * so a caller never has to remember to check a flag before trusting a result.
   */
  async invoke<TResult, TRequest = unknown>(name: string, request?: TRequest): Promise<TResult> {
    const envelope = await this.request<CapabilityResponse<TResult>>(
      "POST",
      `/capabilities/${encodeURIComponent(name)}`,
      request ?? {},
    );
    if (!envelope.ok || envelope.error) {
      throw envelope.error
        ? HarnessError.fromBody(envelope.error, name)
        : new HarnessError("capability_error", "the daemon refused without saying why", name);
    }
    return envelope.result as TResult;
  }

  // -- plumbing --------------------------------------------------------------

  private async json<T>(method: string, path: string): Promise<T> {
    return this.request<T>(method, path);
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = await this.token();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method,
        headers,
        signal: controller.signal,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (error) {
      throw HarnessError.fromTransport(error, url);
    } finally {
      clearTimeout(timer);
    }

    const payload = await readJson(response, url);
    // `POST /capabilities/{name}` answers a refusal with the mapped status *and* the
    // envelope, so a non-2xx that carries one is handed back for `invoke` to raise; only a
    // status with no envelope is turned into an error here.
    if (!response.ok && !isCapabilityEnvelope(payload)) {
      throw errorFromStatus(response.status, payload, url);
    }
    return payload as T;
  }

  private async token(): Promise<string | undefined> {
    if (this.tokenCache === undefined) {
      this.tokenCache = (await this.readToken()) ?? "";
    }
    return this.tokenCache || undefined;
  }
}

async function readJson(response: Response, url: string): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new HarnessError(
      "invalid_response",
      `${url} answered ${response.status} with a body that is not JSON`,
    );
  }
}

function isCapabilityEnvelope(payload: unknown): boolean {
  return typeof payload === "object" && payload !== null && "ok" in payload && "capability" in payload;
}

/** A plain FastAPI error (`{"detail": ...}`) or an unrecognised status. */
function errorFromStatus(status: number, payload: unknown, url: string): HarnessError {
  const detail = detailOf(payload) ?? `${url} answered ${status}`;
  if (status === 401 || status === 403) {
    return new HarnessError("permission_denied", detail);
  }
  if (status === 404) {
    return new HarnessError("object_not_found", detail);
  }
  if (status === 503) {
    return new HarnessError("workspace_error", detail);
  }
  return new HarnessError("capability_error", detail);
}

function detailOf(payload: unknown): string | undefined {
  if (typeof payload !== "object" || payload === null) {
    return undefined;
  }
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    return typeof message === "string" ? message : undefined;
  }
  return undefined;
}

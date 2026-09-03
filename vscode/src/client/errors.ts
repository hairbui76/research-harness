/**
 * Turning a daemon refusal into something a researcher can act on.
 *
 * The daemon answers a refused capability with `ok: false` and a stable `code`
 * (`protocol/dto.py::_ERROR_CODES`); the message beside it is prose and is not part of the
 * contract. So the extension branches on `code` only, and adds the one sentence that says
 * what to do about it - which for `permission_denied` is the sentence that matters most,
 * because a missing token is the difference between "read-only editor" and "broken".
 */

import type { ErrorBody } from "./types";

/** Any failure that came back from, or on the way to, the daemon. */
export class HarnessError extends Error {
  readonly code: string;
  readonly capability: string | undefined;
  readonly detail: string;

  constructor(code: string, detail: string, capability?: string) {
    super(friendlyMessage(code, detail, capability));
    this.name = "HarnessError";
    this.code = code;
    this.capability = capability;
    this.detail = detail;
  }

  /** True when the call was refused for lack of researcher authority, not for being wrong. */
  get isPermissionDenied(): boolean {
    return this.code === "permission_denied" || this.code === "authority_error";
  }

  /** Build from a wire error body. */
  static fromBody(body: ErrorBody, capability?: string): HarnessError {
    return new HarnessError(body.code, body.message, body.capability ?? capability);
  }

  /** Build from a transport failure (no daemon, DNS, socket, abort). */
  static fromTransport(cause: unknown, url: string): HarnessError {
    const detail = cause instanceof Error ? cause.message : String(cause);
    return new HarnessError("daemon_unreachable", `${url}: ${detail}`);
  }
}

/** What to tell the researcher, per stable error code. */
function friendlyMessage(code: string, detail: string, capability?: string): string {
  const what = capability ? `${capability}: ` : "";
  switch (code) {
    case "permission_denied":
    case "authority_error":
      return (
        `${what}the daemon refused this as an agent host, which may read and stage but never ` +
        "accept. Point the `researchHarness.tokenPath` setting at the workspace's " +
        "`.research/daemon-token` (print it with `research token`) and try again. " +
        `Daemon said: ${detail}`
      );
    case "capability_not_found":
      return (
        `${what}this build of the harness does not expose that capability. ` +
        `Run \`research capabilities\` to see what it does. Daemon said: ${detail}`
      );
    case "invalid_request":
      return `${what}the daemon rejected the request body: ${detail}`;
    case "object_not_found":
      return `${what}no such object in this workspace: ${detail}`;
    case "transition_error":
      return `${what}the research state does not allow that change: ${detail}`;
    case "projection_error":
      return (
        `${what}the deletable projection under \`.research/\` is missing or out of date; ` +
        `run \`research rebuild\` and try again. Daemon said: ${detail}`
      );
    case "workspace_error":
      return `${what}the workspace refused the operation: ${detail}`;
    case "daemon_unreachable":
      return (
        "cannot reach the Research Harness daemon. Start it with `research serve` in the " +
        `workspace, or correct the \`researchHarness.daemonUrl\` setting. ${detail}`
      );
    default:
      return `${what}${detail}`;
  }
}

/**
 * Settings, the workspace, and the two paths everything else is expressed in.
 *
 * Two path questions run through the whole extension and are answered only here:
 *
 * - *where is the manuscript project?* - the daemon defaults to the workspace's canonical
 *   `manuscript/` directory, so `researchHarness.manuscriptRoot` is empty by default and
 *   `manuscript.audit` is called with no `project_root` at all;
 * - *what does the harness call this file?* - an anchor's `file` is POSIX-relative to that
 *   root, so a `TextDocument` outside it simply has no manuscript identity and every
 *   manuscript feature stays quiet rather than guessing.
 */

import { readFile } from "node:fs/promises";
import * as path from "node:path";
import * as vscode from "vscode";

export const CONFIG_SECTION = "researchHarness";

/** Everything the extension reads from settings, resolved once per call. */
export interface Settings {
  daemonUrl: string;
  tokenPath: string;
  webUrl: string;
  manuscriptRoot: string;
  mainTex: string;
  auditOnSave: boolean;
  auditDebounceMs: number;
}

export function readSettings(): Settings {
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
  return {
    daemonUrl: config.get<string>("daemonUrl") ?? "http://127.0.0.1:8765",
    tokenPath: config.get<string>("tokenPath") ?? ".research/daemon-token",
    webUrl: config.get<string>("webUrl") ?? "http://127.0.0.1:8765",
    manuscriptRoot: config.get<string>("manuscriptRoot") ?? "",
    mainTex: config.get<string>("mainTex") ?? "main.tex",
    auditOnSave: config.get<boolean>("auditOnSave") ?? true,
    auditDebounceMs: config.get<number>("auditDebounceMs") ?? 750,
  };
}

/** The workspace folder the harness lives in, or undefined when there is no folder open. */
export function workspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

/**
 * The local daemon token, or undefined when there is none.
 *
 * Absent is a normal state, not an error: the daemon then treats the extension as an agent
 * host, which may read everything the researcher can see and accept nothing (Product 29).
 */
export async function readToken(settings: Settings): Promise<string | undefined> {
  const root = workspaceRoot();
  const configured = settings.tokenPath || ".research/daemon-token";
  const file = path.isAbsolute(configured)
    ? configured
    : root
      ? path.join(root, configured)
      : undefined;
  if (!file) {
    return undefined;
  }
  try {
    const text = await readFile(file, "utf8");
    return text.trim() || undefined;
  } catch {
    return undefined;
  }
}

/** Absolute path of the manuscript project root, or undefined for the daemon's default. */
export function manuscriptRoot(settings: Settings): string | undefined {
  if (!settings.manuscriptRoot) {
    return undefined;
  }
  if (path.isAbsolute(settings.manuscriptRoot)) {
    return settings.manuscriptRoot;
  }
  const root = workspaceRoot();
  return root ? path.join(root, settings.manuscriptRoot) : undefined;
}

/** The directory a manuscript file's path is relative to, for local path arithmetic. */
export function manuscriptBase(settings: Settings): string | undefined {
  const configured = manuscriptRoot(settings);
  if (configured) {
    return configured;
  }
  const root = workspaceRoot();
  return root ? path.join(root, "manuscript") : undefined;
}

/**
 * What the harness calls `file`: POSIX-relative to the manuscript root.
 *
 * Undefined means the file is not part of this manuscript, which is the answer for every
 * other `.tex` file a researcher happens to have open.
 */
export function manuscriptRelativePath(settings: Settings, fsPath: string): string | undefined {
  const base = manuscriptBase(settings);
  if (!base) {
    return undefined;
  }
  const relative = path.relative(base, fsPath);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    return undefined;
  }
  return relative.split(path.sep).join("/");
}

/** The absolute path of a manuscript-relative file, for mapping findings back to editors. */
export function manuscriptFilePath(settings: Settings, relative: string): string | undefined {
  const base = manuscriptBase(settings);
  return base ? path.join(base, ...relative.split("/")) : undefined;
}

/** The Web cockpit page for one research object; ids are already URL-safe. */
export function webObjectUrl(settings: Settings, kind: string, id: string): string {
  const base = settings.webUrl.replace(/\/+$/, "");
  return `${base}/${kind}/${encodeURIComponent(id)}`;
}

/** The Web cockpit page for one Claim - the `[Open Claim]` link of Product 28. */
export function claimUrl(settings: Settings, claimId: string): string {
  return webObjectUrl(settings, "claims", claimId);
}

/** The Web cockpit page for one Evidence object - the `[Open Evidence]` link. */
export function evidenceUrl(settings: Settings, evidenceId: string): string {
  return webObjectUrl(settings, "evidence", evidenceId);
}

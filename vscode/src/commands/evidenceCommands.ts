/**
 * `Research: Open Evidence` - Product 28's "open exact evidence in Web/PDF view".
 *
 * The chain the researcher is standing on is Product 30.1: the sentence under the cursor
 * carries an anchor, the anchor names a Claim, the Claim records evidence relations, and
 * each accepted Evidence object opens at an exact artifact, page, and span (Product 42.D).
 * This command walks it with `manuscript.trace` - one sentence, by file and line, rather
 * than a whole-project audit for one cursor - and `retrieval.resolve_source`, prints the
 * resolved location so provenance is legible without leaving the editor, and hands the
 * viewing itself to the Web cockpit, which owns the source pane.
 */

import * as vscode from "vscode";

import { resolveSource } from "../client/requests";
import type { SourceRef, TraceView } from "../client/types";
import { evidenceUrl } from "../config";
import { type CommandContext, report, resolveTarget, withErrors } from "./context";

export async function openEvidence(context: CommandContext): Promise<void> {
  const resolved = resolveTarget();
  if (!resolved) {
    return;
  }
  // Wrapped so a daemon failure (already reported) is not announced as "no Claim here".
  const found = await withErrors(context, "open evidence", async () => ({
    entry: await context.manuscript.claimUnderCursor(resolved.editor.document, resolved.position),
  }));
  if (!found) {
    return;
  }
  const entry = found.entry;
  if (!entry) {
    void vscode.window.showInformationMessage(
      "Research Harness: no Claim is attached to this sentence, so there is no Evidence to open.",
    );
    return;
  }

  const trace: TraceView | undefined = await context.manuscript.trace(
    entry.anchor.file,
    resolved.position.line + 1,
  );
  const fromTrace = trace?.link?.evidence ?? [];
  const fromSupport = (entry.support?.supporting ?? []).map((item) => item.evidence);
  const evidence = [...new Set([...fromTrace, ...fromSupport])];

  if (evidence.length === 0) {
    void vscode.window.showWarningMessage(
      `Research Harness: ${entry.claimId} records no supporting Evidence yet.`,
    );
    return;
  }

  const chosen =
    evidence.length === 1
      ? evidence[0]
      : await vscode.window.showQuickPick(evidence, {
          title: `Evidence supporting ${entry.claimId}`,
        });
  if (!chosen) {
    return;
  }

  const source = await withErrors(context, "resolve source", () =>
    resolveSource(context.client, chosen),
  );
  if (!source) {
    // `retrieval.resolve_source` reads the deletable projection; when it is missing the
    // error already told the researcher to run `research rebuild`. The Web cockpit can
    // still show the Evidence object, so offer that rather than stopping here.
    await offerWebPage(context, chosen);
    return;
  }

  report(context, `evidence ${chosen}`, describe(source));
  await offerWebPage(context, chosen, source);
}

function describe(source: SourceRef): string[] {
  return [
    `work          ${source.work} / ${source.version} / ${source.artifact}`,
    `block         ${source.block}`,
    `page          ${source.page ?? "-"}`,
    `bbox          ${source.bbox ? source.bbox.join(", ") : "-"}`,
    `span          ${source.char_start ?? "-"}..${source.char_end ?? "-"}`,
    `section       ${(source.section_path ?? []).join(" › ") || "-"}`,
    `text          ${source.text}`,
  ];
}

async function offerWebPage(
  context: CommandContext,
  evidence: string,
  source?: SourceRef,
): Promise<void> {
  const url = evidenceUrl(context.manuscript.settings(), evidence);
  const where = source?.page ? ` (page ${source.page})` : "";
  const choice = await vscode.window.showInformationMessage(
    `Research Harness: ${evidence}${where}`,
    "Open in Web cockpit",
    "Show location",
  );
  if (choice === "Open in Web cockpit") {
    await vscode.env.openExternal(vscode.Uri.parse(url));
  } else if (choice === "Show location") {
    context.output.show(true);
  }
}

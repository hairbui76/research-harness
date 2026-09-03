/**
 * Claim status on hover (Roadmap Task 16.2).
 *
 * Hovering a substantive sentence answers the question the researcher actually has while
 * writing: *may I say this?* The tooltip shows the Claim, what the evidence lets it say,
 * how much of that evidence there is, and whether anything has gone stale underneath - and
 * over a substantive sentence with no Claim at all it says so, because unlinked prose being
 * visible is the point of Product 28.
 */

import * as vscode from "vscode";

import { claimUrl } from "../config";
import { hoverMarkdown, unattachedMarkdown } from "./hover";
import type { ManuscriptService } from "./service";

/** Encodes a command link a `MarkdownString` can invoke. */
function commandLink(command: string): string {
  return `command:${command}`;
}

export class ClaimHoverProvider implements vscode.HoverProvider {
  constructor(private readonly manuscript: ManuscriptService) {}

  async provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    token: vscode.CancellationToken,
  ): Promise<vscode.Hover | undefined> {
    const sentence = this.manuscript.sentenceAt(document, position);
    if (!sentence) {
      return undefined;
    }
    const range = new vscode.Range(
      new vscode.Position(Math.max(0, sentence.lineStart - 1), 0),
      new vscode.Position(Math.max(0, sentence.lineEnd - 1), Number.MAX_SAFE_INTEGER),
    );

    let entry;
    try {
      entry = await this.manuscript.claimUnderCursor(document, position);
    } catch {
      // A hover is not the place to raise a daemon outage: the commands report it, and a
      // tooltip that fails silently is better than one that interrupts typing.
      return undefined;
    }
    if (token.isCancellationRequested) {
      return undefined;
    }

    const markdown = new vscode.MarkdownString(
      entry === undefined
        ? unattachedMarkdown(commandLink("researchHarness.attachClaim"))
        : hoverMarkdown(entry, {
            claimUrl: claimUrl(this.manuscript.settings(), entry.claimId),
            openEvidenceCommand: commandLink("researchHarness.openEvidence"),
            auditCommand: commandLink("researchHarness.auditSelection"),
          }),
    );
    markdown.isTrusted = true;
    return new vscode.Hover(markdown, range);
  }
}

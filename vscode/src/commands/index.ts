/** The seven `Research: …` commands of Roadmap Task 16.3, wired to the extension host. */

import * as vscode from "vscode";

import type { CommandContext, InvocationTarget } from "./context";
import { openEvidence } from "./evidenceCommands";
import {
  attachClaim,
  auditSelection,
  createClaimFromSelection,
  revalidateAnchors,
  showClaimUnderCursor,
} from "./manuscriptCommands";
import { addResearchNote } from "./noteCommands";

export type { CommandContext, InvocationTarget } from "./context";

/** Command ids, in one place so `package.json` and the code cannot drift apart. */
export const COMMAND_IDS = {
  auditSelection: "researchHarness.auditSelection",
  attachClaim: "researchHarness.attachClaim",
  createClaimFromSelection: "researchHarness.createClaimFromSelection",
  addNote: "researchHarness.addNote",
  openEvidence: "researchHarness.openEvidence",
  revalidateAnchors: "researchHarness.revalidateAnchors",
  showClaimUnderCursor: "researchHarness.showClaimUnderCursor",
} as const;

export function registerCommands(context: CommandContext): vscode.Disposable[] {
  return [
    vscode.commands.registerCommand(COMMAND_IDS.auditSelection, () => auditSelection(context)),
    vscode.commands.registerCommand(COMMAND_IDS.attachClaim, (target?: InvocationTarget) =>
      attachClaim(context, target),
    ),
    vscode.commands.registerCommand(COMMAND_IDS.createClaimFromSelection, () =>
      createClaimFromSelection(context),
    ),
    vscode.commands.registerCommand(COMMAND_IDS.addNote, () => addResearchNote(context)),
    vscode.commands.registerCommand(COMMAND_IDS.openEvidence, () => openEvidence(context)),
    vscode.commands.registerCommand(COMMAND_IDS.revalidateAnchors, () =>
      revalidateAnchors(context),
    ),
    vscode.commands.registerCommand(COMMAND_IDS.showClaimUnderCursor, () =>
      showClaimUnderCursor(context),
    ),
  ];
}

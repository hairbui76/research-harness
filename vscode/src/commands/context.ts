/**
 * What every command is handed, and the few things they all do the same way.
 *
 * The commands are thin: they gather what the researcher meant, call one capability, and
 * report what came back. Anything they share - finding the sentence under the cursor,
 * refusing politely when the file is not part of the manuscript, turning a `HarnessError`
 * into one actionable message - lives here so it reads the same in all seven.
 */

import * as vscode from "vscode";

import { HarnessError } from "../client/errors";
import type { HarnessClient } from "../client/HarnessClient";
import type { LocalSentence } from "../manuscript/latex";
import type { ManuscriptService } from "../manuscript/service";

/** Everything a command needs; assembled once at activation. */
export interface CommandContext {
  client: HarnessClient;
  manuscript: ManuscriptService;
  output: vscode.OutputChannel;
  /** Re-runs the audit and repaints the problem list; commands call it after a mutation. */
  refreshDiagnostics: (options?: { force?: boolean }) => Promise<void>;
}

/** A position a command was invoked at: the cursor, or the one a code action named. */
export interface InvocationTarget {
  uri: vscode.Uri;
  line: number;
}

/** The active editor when it holds a LaTeX file, else undefined. */
export function activeTexEditor(): vscode.TextEditor | undefined {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return undefined;
  }
  const language = editor.document.languageId;
  const isTex =
    language === "latex" || language === "tex" || editor.document.uri.fsPath.endsWith(".tex");
  return isTex ? editor : undefined;
}

/** The editor and position a command should act on, complaining once when there is none. */
export function resolveTarget(
  target?: InvocationTarget,
): { editor: vscode.TextEditor; position: vscode.Position } | undefined {
  const editor = activeTexEditor();
  if (!editor) {
    void vscode.window.showWarningMessage(
      "Research Harness: open the LaTeX file you want to work on first.",
    );
    return undefined;
  }
  const named = target !== undefined && target.uri.fsPath === editor.document.uri.fsPath;
  const line = named ? (target as InvocationTarget).line : editor.selection.active.line;
  return { editor, position: new vscode.Position(line, 0) };
}

/**
 * The sentence at `position`, or undefined with the reason already shown.
 *
 * "Not a sentence" is a real answer here: the harness refuses to anchor a Claim to a
 * heading, a caption, or a float, because a Claim attaches to prose that asserts something
 * about the world (Product 30.1).
 */
export function requireSentence(
  context: CommandContext,
  editor: vscode.TextEditor,
  position: vscode.Position,
): LocalSentence | undefined {
  if (!context.manuscript.relativePath(editor.document)) {
    void vscode.window.showWarningMessage(
      "Research Harness: this file is not inside the manuscript project. Set " +
        "`researchHarness.manuscriptRoot` if the manuscript lives outside `manuscript/`.",
    );
    return undefined;
  }
  const sentence = context.manuscript.sentenceAt(editor.document, position);
  if (!sentence) {
    void vscode.window.showWarningMessage(
      `Research Harness: line ${position.line + 1} carries no manuscript sentence ` +
        "(a heading, a float, or a blank line is not one).",
    );
    return undefined;
  }
  return sentence;
}

/** Run `work`, reporting a refusal as one message the researcher can act on. */
export async function withErrors<T>(
  context: CommandContext,
  label: string,
  work: () => Promise<T>,
): Promise<T | undefined> {
  try {
    return await work();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    context.output.appendLine(`[${label}] ${message}`);
    if (error instanceof HarnessError && error.isPermissionDenied) {
      const choice = await vscode.window.showErrorMessage(
        `Research Harness: ${message}`,
        "Open Settings",
      );
      if (choice === "Open Settings") {
        await vscode.commands.executeCommand(
          "workbench.action.openSettings",
          "researchHarness.tokenPath",
        );
      }
    } else {
      void vscode.window.showErrorMessage(`Research Harness: ${message}`);
    }
    return undefined;
  }
}

/** Write a titled block to the output channel and reveal it. */
export function report(context: CommandContext, title: string, lines: readonly string[]): void {
  context.output.appendLine(`— ${title} —`);
  for (const line of lines) {
    context.output.appendLine(`  ${line}`);
  }
  context.output.appendLine("");
}

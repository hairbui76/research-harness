/**
 * `Research: Add Research Note` - quick capture that does not become knowledge (Product 31).
 *
 * A note is deliberately low authority: it can never be cited as support until a human
 * promotes it into a Claim, a Question, or a Decision. Capturing one from the editor is
 * therefore safe in a way that "remember this" in a chat window is not - it lands in the
 * workspace as a `ResearchNote`, visible from the CLI and the Web cockpit, and nothing
 * downstream moves.
 *
 * Where the note was taken goes in `AddNoteRequest.source`, which the handler records as
 * provenance (`Provenance.note`) rather than as note text. That distinction is the reason
 * the editor does not write `main.tex:23` into the note itself: the scientific record says
 * what was captured, not which window it was typed into.
 */

import * as vscode from "vscode";

import { addNote } from "../client/requests";
import { type CommandContext, activeTexEditor, report, withErrors } from "./context";

/** How this extension names itself in a note's provenance. */
export const SOURCE_NAME = "vscode";

export async function addResearchNote(context: CommandContext): Promise<void> {
  const text = await vscode.window.showInputBox({
    title: "Research note",
    prompt:
      "Captured as a low-authority note; it can never be cited as support until it is promoted.",
    placeHolder: "What did you just notice?",
    validateInput: (value) => (value.trim() ? undefined : "A note needs some text."),
  });
  if (!text) {
    return;
  }

  const source = noteSource(context);
  const mutation = await withErrors(context, "add note", () =>
    addNote(context.client, { text: text.trim(), source }),
  );
  if (!mutation) {
    return;
  }
  report(context, "captured research note", [
    text.trim(),
    `source        ${source}`,
    `event         ${mutation.event.event}`,
    `summary       ${mutation.event.summary}`,
  ]);
  void vscode.window.showInformationMessage(`Research Harness: ${mutation.event.summary}`);
}

/**
 * What to record as the capture host: this editor, and the manuscript location when there
 * is one. `vscode main.tex:23` reads as "captured via vscode main.tex:23" in the note's
 * provenance, which is where a reader looks for where something came from.
 */
export function noteSource(context: CommandContext): string {
  const editor = activeTexEditor();
  if (!editor) {
    return SOURCE_NAME;
  }
  const file = context.manuscript.relativePath(editor.document);
  return file ? `${SOURCE_NAME} ${file}:${editor.selection.active.line + 1}` : SOURCE_NAME;
}

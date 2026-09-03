/**
 * Manuscript audit findings as editor diagnostics (Roadmap Task 16.4).
 *
 * The severities are the ones Task 16.4 names, in one table so the mapping is a fact rather
 * than an argument spread over the code:
 *
 * | finding                   | shown as    | why |
 * | ------------------------- | ----------- | --- |
 * | `unregistered_claim`      | Information | unlinked substantive prose is visible, not broken |
 * | `over_strong_wording`     | Warning     | the sentence outruns its Claim (Product 42.G) |
 * | `citation_mismatch`       | Error       | a citation that does not support is 42.J |
 * | `unsupported_numeric`     | Error       | a number with no source-observed evidence |
 * | `stale_claim`             | Warning     | the research state moved under the sentence |
 * | `invalid_evidence_anchor` | Error       | provenance no longer opens (Product 42.D) |
 *
 * One rule bends the table, and only upward: a finding the auditor itself marked `error` is
 * always shown as an Error. That is what keeps an anchor naming a Claim that is not in the
 * graph - reported as an `unregistered_claim` at error severity - out of the Information
 * bucket. Nothing is ever demoted, because the auditor is the authority on severity and the
 * editor is a display (ADR-004).
 *
 * The extension never invents a finding, never suppresses one, and never repairs anything:
 * a diagnostic here is exactly one line of `manuscript.audit` output, placed on a range.
 */

import * as vscode from "vscode";

import type {
  FindingSeverity,
  ManuscriptAuditFinding,
  ManuscriptAuditReport,
  ManuscriptFindingKind,
} from "../client/types";
import { findingLocation, findingMessage } from "./report";

/** Marks every diagnostic this extension owns, so refreshing replaces only its own. */
export const DIAGNOSTIC_SOURCE = "research-harness";

/** The comment the harness's own drafts use for unresolved support (`manuscript/draft.py`). */
export const NEEDS_SOURCE = "NEEDS SOURCE";

/** Task 16.4: how each Product 30.3 finding kind is shown. */
export const SEVERITY_BY_KIND: Record<ManuscriptFindingKind, vscode.DiagnosticSeverity> = {
  unregistered_claim: vscode.DiagnosticSeverity.Information,
  over_strong_wording: vscode.DiagnosticSeverity.Warning,
  citation_mismatch: vscode.DiagnosticSeverity.Error,
  unsupported_numeric: vscode.DiagnosticSeverity.Error,
  stale_claim: vscode.DiagnosticSeverity.Warning,
  invalid_evidence_anchor: vscode.DiagnosticSeverity.Error,
};

/** The kinds a researcher can act on from the lightbulb. */
const ATTACHABLE: ReadonlySet<ManuscriptFindingKind> = new Set<ManuscriptFindingKind>([
  "unregistered_claim",
]);

const NEEDS_SOURCE_KINDS: ReadonlySet<ManuscriptFindingKind> = new Set<ManuscriptFindingKind>([
  "unregistered_claim",
  "citation_mismatch",
  "unsupported_numeric",
]);

/** The table value, escalated (never demoted) when the auditor called it an error. */
export function severityFor(
  kind: ManuscriptFindingKind,
  reported: FindingSeverity,
): vscode.DiagnosticSeverity {
  const fromTable = SEVERITY_BY_KIND[kind];
  return reported === "error" ? vscode.DiagnosticSeverity.Error : fromTable;
}

/** Resolves a manuscript-relative path to a file on disk; see `config.manuscriptFilePath`. */
export type ResolveFile = (relativePath: string) => string | undefined;

/** One finding as a diagnostic, or undefined when it names no location the editor can use. */
export function toDiagnostic(
  finding: ManuscriptAuditFinding,
  document?: vscode.TextDocument,
): vscode.Diagnostic | undefined {
  const location = findingLocation(finding);
  if (!location) {
    return undefined;
  }
  const diagnostic = new vscode.Diagnostic(
    rangeOf(location.lineStart, location.lineEnd, location.charStart, location.charEnd, document),
    findingMessage(finding),
    severityFor(finding.kind, finding.severity),
  );
  diagnostic.source = DIAGNOSTIC_SOURCE;
  diagnostic.code = finding.kind;
  const related = finding.related ?? [];
  if (related.length > 0) {
    diagnostic.message = `${diagnostic.message} [${related.join(", ")}]`;
  }
  return diagnostic;
}

/**
 * Every finding, grouped by the absolute file it belongs to.
 *
 * `resolveFile` turns the harness's manuscript-relative path into a path on disk; a finding
 * whose file does not resolve is dropped rather than attached to the wrong editor.
 */
export function diagnosticsByFile(
  report: ManuscriptAuditReport,
  resolveFile: ResolveFile,
  documents: readonly vscode.TextDocument[] = [],
): Map<string, vscode.Diagnostic[]> {
  const byFile = new Map<string, vscode.Diagnostic[]>();
  for (const finding of report.findings) {
    const location = findingLocation(finding);
    if (!location) {
      continue;
    }
    const fsPath = resolveFile(location.file);
    if (!fsPath) {
      continue;
    }
    const document = documents.find((item) => item.uri.fsPath === fsPath);
    const diagnostic = toDiagnostic(finding, document);
    if (!diagnostic) {
      continue;
    }
    const existing = byFile.get(fsPath);
    if (existing) {
      existing.push(diagnostic);
    } else {
      byFile.set(fsPath, [diagnostic]);
    }
  }
  return byFile;
}

/**
 * The span to underline.
 *
 * Character offsets are preferred because they mark the sentence rather than the lines it
 * happens to occupy, but they index the file as the daemon last read it: an unsaved edit
 * makes them wrong, and `positionAt` clamps into the buffer, so the whole-line range is the
 * fallback whenever offsets are absent or out of range.
 */
function rangeOf(
  lineStart: number,
  lineEnd: number,
  charStart: number | undefined,
  charEnd: number | undefined,
  document?: vscode.TextDocument,
): vscode.Range {
  if (
    document &&
    typeof charStart === "number" &&
    typeof charEnd === "number" &&
    charEnd > charStart &&
    charEnd <= document.getText().length
  ) {
    return new vscode.Range(document.positionAt(charStart), document.positionAt(charEnd));
  }
  const first = Math.max(0, lineStart - 1);
  const last = Math.max(first, lineEnd - 1);
  if (document) {
    const line = document.lineAt(Math.min(last, Math.max(0, document.lineCount - 1)));
    return new vscode.Range(new vscode.Position(first, 0), line.range.end);
  }
  return new vscode.Range(new vscode.Position(first, 0), new vscode.Position(last, Number.MAX_SAFE_INTEGER));
}

/** Owns the collection so a refresh replaces the extension's findings and nothing else. */
export class ManuscriptDiagnostics {
  private readonly collection: vscode.DiagnosticCollection;

  constructor(collection?: vscode.DiagnosticCollection) {
    this.collection =
      collection ?? vscode.languages.createDiagnosticCollection(DIAGNOSTIC_SOURCE);
  }

  /** Replace every diagnostic with the ones this report produced. */
  refresh(report: ManuscriptAuditReport, resolveFile: ResolveFile): number {
    const byFile = diagnosticsByFile(report, resolveFile, vscode.workspace.textDocuments);
    this.collection.clear();
    let total = 0;
    for (const [fsPath, diagnostics] of byFile) {
      this.collection.set(vscode.Uri.file(fsPath), diagnostics);
      total += diagnostics.length;
    }
    return total;
  }

  clear(): void {
    this.collection.clear();
  }

  dispose(): void {
    this.collection.dispose();
  }
}

/**
 * The two lightbulb actions of Task 16.4.
 *
 * "Attach Claim…" runs the command, because attaching prose to a Claim is a scientific
 * judgement and belongs in the same quick pick as every other attachment. "Add NEEDS
 * SOURCE note" is a pure text edit: it writes the harness's own marker into the manuscript
 * so the gap is visible in the file itself rather than only in the editor's problem list
 * (Product 30.2 - unresolved support becomes a visible warning, never a fabricated citation).
 */
export class ManuscriptCodeActions implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    for (const diagnostic of context.diagnostics) {
      if (diagnostic.source !== DIAGNOSTIC_SOURCE) {
        continue;
      }
      const kind = diagnostic.code as ManuscriptFindingKind;
      if (ATTACHABLE.has(kind)) {
        const attach = new vscode.CodeAction("Attach Claim…", vscode.CodeActionKind.QuickFix);
        attach.command = {
          command: "researchHarness.attachClaim",
          title: "Attach Claim…",
          arguments: [{ uri: document.uri, line: diagnostic.range.start.line }],
        };
        attach.diagnostics = [diagnostic];
        actions.push(attach);
      }
      if (NEEDS_SOURCE_KINDS.has(kind)) {
        actions.push(needsSourceAction(document, diagnostic));
      }
    }
    return actions;
  }
}

function needsSourceAction(
  document: vscode.TextDocument,
  diagnostic: vscode.Diagnostic,
): vscode.CodeAction {
  const action = new vscode.CodeAction(
    `Add ${NEEDS_SOURCE} note`,
    vscode.CodeActionKind.QuickFix,
  );
  const line = diagnostic.range.start.line;
  const indent = /^\s*/.exec(document.lineAt(line).text)?.[0] ?? "";
  const edit = new vscode.WorkspaceEdit();
  edit.insert(
    document.uri,
    new vscode.Position(line, 0),
    `${indent}% ${NEEDS_SOURCE}: ${diagnostic.message}\n`,
  );
  action.edit = edit;
  action.diagnostics = [diagnostic];
  return action;
}

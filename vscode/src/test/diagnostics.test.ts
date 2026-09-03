/**
 * Audit findings onto editor ranges (Roadmap Task 16.4).
 *
 * `fixtures/audit-report.json` is a real `manuscript.audit` response, exported by
 * `scripts/export_fixtures.py`, so the shapes exercised here - including the finding that
 * carries no anchor at all - are the shapes the daemon actually sends.
 */

import { describe, expect, it } from "vitest";
import type * as vscode from "vscode";
import { DiagnosticSeverity } from "vscode";

import { FakeTextDocument } from "./vscode-mock";

import type { ManuscriptAuditFinding, ManuscriptAuditReport } from "../client/types";
import {
  DIAGNOSTIC_SOURCE,
  diagnosticsByFile,
  ManuscriptCodeActions,
  NEEDS_SOURCE,
  severityFor,
  toDiagnostic,
} from "../manuscript/diagnostics";
import { findingLocation, findingMessage } from "../manuscript/report";
import auditReport from "./fixtures/audit-report.json";
import manuscript from "./fixtures/manuscript.json";

const report = auditReport as unknown as ManuscriptAuditReport;
const document = new FakeTextDocument(
  "/w/manuscript/main.tex",
  manuscript.source,
) as unknown as vscode.TextDocument;
const resolveFile = (relative: string) => `/w/manuscript/${relative}`;

function findingOf(kind: string): ManuscriptAuditFinding {
  const found = report.findings.find((item) => item.kind === kind);
  if (!found) {
    throw new Error(`the fixture carries no ${kind} finding; re-run export_fixtures.py`);
  }
  return found;
}

describe("the fixture is the report the audit produced", () => {
  it("covers five of the six Product 30.3 finding kinds", () => {
    expect(new Set(report.findings.map((item) => item.kind))).toEqual(
      new Set([
        "over_strong_wording",
        "citation_mismatch",
        "unsupported_numeric",
        "stale_claim",
        "unregistered_claim",
      ]),
    );
  });

  it("includes a finding with no anchor, which only its `location` can place", () => {
    const unregistered = findingOf("unregistered_claim");
    expect(unregistered.anchor ?? null).toBeNull();
    expect(unregistered.location).toBeDefined();
  });

  it("carries a structured location on every finding", () => {
    for (const finding of report.findings) {
      expect(finding.location?.file).toBe("main.tex");
      expect(finding.location?.line_start).toBeTypeOf("number");
      expect(finding.location?.line_end).toBeGreaterThanOrEqual(finding.location!.line_start);
    }
  });
});

describe("severity", () => {
  it("uses the Task 16.4 table", () => {
    expect(severityFor("unregistered_claim", "warning")).toBe(DiagnosticSeverity.Information);
    expect(severityFor("over_strong_wording", "warning")).toBe(DiagnosticSeverity.Warning);
    expect(severityFor("stale_claim", "warning")).toBe(DiagnosticSeverity.Warning);
    expect(severityFor("citation_mismatch", "error")).toBe(DiagnosticSeverity.Error);
    expect(severityFor("invalid_evidence_anchor", "error")).toBe(DiagnosticSeverity.Error);
  });

  it("promotes a warning-severity unsupported numeric, which Task 16.4 calls an error", () => {
    expect(findingOf("unsupported_numeric").severity).toBe("warning");
    expect(severityFor("unsupported_numeric", "warning")).toBe(DiagnosticSeverity.Error);
  });

  it("never demotes what the auditor called an error", () => {
    // `_orphan_claim` reports `unregistered_claim` at error severity: an anchor naming a
    // Claim the graph does not hold is not an informational hint.
    expect(severityFor("unregistered_claim", "error")).toBe(DiagnosticSeverity.Error);
  });
});

describe("placement", () => {
  it("reads the finding's own location, including for a finding with no anchor", () => {
    const location = findingLocation(findingOf("unregistered_claim"));
    expect(location).toEqual({
      file: "main.tex",
      lineStart: 23,
      lineEnd: 23,
      charStart: 636,
      charEnd: 710,
    });
  });

  it("takes the span from `location`, which carries the sentence's character offsets", () => {
    const finding = findingOf("over_strong_wording");
    const location = findingLocation(finding);
    expect(location?.file).toBe("main.tex");
    expect(location?.lineStart).toBe(finding.location?.line_start);
    expect(location?.lineEnd).toBe(finding.location?.line_end);
    expect(location?.charStart).toBe(finding.location?.char_start);
  });

  it("falls back to the message prefix for a daemon that reports no location", () => {
    const finding = { ...findingOf("unregistered_claim"), location: null, anchor: null };
    expect(findingLocation(finding)).toEqual({ file: "main.tex", lineStart: 23, lineEnd: 23 });
  });

  it("falls back to the anchor when there is neither a location nor a prefix", () => {
    const anchored = findingOf("over_strong_wording");
    const finding = { ...anchored, location: null, message: "no prefix here" };
    expect(findingLocation(finding)?.lineStart).toBe(anchored.anchor?.line_start);
  });

  it("says nothing rather than guessing when no field places the finding", () => {
    expect(
      findingLocation({
        kind: "stale_claim",
        severity: "warning",
        message: "nothing places this",
      }),
    ).toBeUndefined();
  });

  it("strips the location prefix so the diagnostic does not repeat its own range", () => {
    const finding = findingOf("stale_claim");
    expect(finding.message.startsWith("main.tex:20: ")).toBe(true);
    expect(findingMessage(finding).startsWith("main.tex")).toBe(false);
  });

  it("underlines the sentence, not the line, when the buffer matches the daemon's read", () => {
    const diagnostic = toDiagnostic(findingOf("over_strong_wording"), document);
    expect(diagnostic).toBeDefined();
    expect(diagnostic?.range.start.line).toBe(13);
    expect(diagnostic?.range.end.line).toBe(14);
    expect(document.getText(diagnostic!.range)).toBe(
      "Every encrypted traffic classifier fails under sustained load, and no prior work\n" +
        "reports the size of the gap \\citep{traffic2024}.",
    );
  });

  it("falls back to whole lines when there is no open document", () => {
    const diagnostic = toDiagnostic(findingOf("unregistered_claim"));
    expect(diagnostic?.range.start.line).toBe(22);
    expect(diagnostic?.range.start.character).toBe(0);
  });
});

describe("diagnosticsByFile", () => {
  const byFile = diagnosticsByFile(report, resolveFile, [document]);

  it("places every finding the report carries", () => {
    expect([...byFile.keys()]).toEqual(["/w/manuscript/main.tex"]);
    expect(byFile.get("/w/manuscript/main.tex")).toHaveLength(report.findings.length);
  });

  it("marks each diagnostic as this extension's, with the finding kind as its code", () => {
    for (const diagnostic of byFile.get("/w/manuscript/main.tex") ?? []) {
      expect(diagnostic.source).toBe(DIAGNOSTIC_SOURCE);
      expect(typeof diagnostic.code).toBe("string");
    }
  });

  it("names the related research objects in the message", () => {
    const stale = (byFile.get("/w/manuscript/main.tex") ?? []).find(
      (item) => item.code === "stale_claim",
    );
    expect(stale?.message).toContain("[C0002]");
  });

  it("drops a finding whose file does not resolve, rather than guessing an editor", () => {
    expect(diagnosticsByFile(report, () => undefined, [document]).size).toBe(0);
  });
});

describe("code actions", () => {
  const provider = new ManuscriptCodeActions();
  const diagnostics = diagnosticsByFile(report, resolveFile, [document]).get(
    "/w/manuscript/main.tex",
  ) as Array<ReturnType<typeof toDiagnostic>>;

  function actionsFor(code: string) {
    const diagnostic = diagnostics.find((item) => item?.code === code);
    if (!diagnostic) {
      throw new Error(`no ${code} diagnostic in the fixture`);
    }
    return provider.provideCodeActions(document, diagnostic.range, {
      diagnostics: [diagnostic],
    } as unknown as vscode.CodeActionContext);
  }

  it("offers Attach Claim… on unlinked substantive prose", () => {
    const actions = actionsFor("unregistered_claim");
    const attach = actions.find((action) => action.title === "Attach Claim…");
    expect(attach?.command?.command).toBe("researchHarness.attachClaim");
    expect(attach?.command?.arguments?.[0]).toMatchObject({ line: 22 });
  });

  it("offers the harness's own NEEDS SOURCE marker for unresolved support", () => {
    const actions = actionsFor("citation_mismatch");
    const note = actions.find((action) => action.title === `Add ${NEEDS_SOURCE} note`);
    expect(note?.edit).toBeDefined();
    const inserted = (note?.edit as unknown as { inserts: Array<{ text: string }> }).inserts[0];
    expect(inserted?.text.startsWith(`% ${NEEDS_SOURCE}: `)).toBe(true);
  });

  it("ignores diagnostics another extension published", () => {
    const foreign = { ...diagnostics[0], source: "chktex" };
    expect(
      provider.provideCodeActions(document, foreign.range as vscode.Range, {
        diagnostics: [foreign],
      } as unknown as vscode.CodeActionContext),
    ).toEqual([]);
  });
});

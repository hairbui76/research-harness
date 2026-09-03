/**
 * Building an anchor, and refusing to pretend one landed when it did not.
 *
 * `manuscript.attach_claim` takes a whole anchor, so the editor computes the fingerprint the
 * harness will match on. `verifyAttachment` is the safety net for that: the next audit has
 * to report the new anchor as `valid`, or the researcher hears about it.
 */

import { describe, expect, it } from "vitest";

import type { ManuscriptAuditReport } from "../client/types";
import { buildAnchor, verifyAttachment, VSCODE_WORKFLOW } from "../manuscript/anchor";
import { sentencesOf } from "../manuscript/latex";
import { anchorKey } from "../manuscript/report";
import auditReport from "./fixtures/audit-report.json";
import manuscript from "./fixtures/manuscript.json";

const report = auditReport as unknown as ManuscriptAuditReport;
const sentences = sentencesOf("main.tex", manuscript.source);

describe("buildAnchor", () => {
  const sentence = sentences[0];
  if (!sentence) {
    throw new Error("the fixture manuscript has no sentences");
  }
  const anchor = buildAnchor(sentence, "C0001");

  it("records the normalized sentence, not the LaTeX source", () => {
    expect(anchor.sentence).toBe(sentence.normalizedText);
    expect(anchor.sentence).not.toContain("\\citep");
  });

  it("carries the fingerprint the harness keys the anchor on", () => {
    const stored = report.revalidations[0]?.anchor;
    expect(anchor.sentence_fingerprint).toBe(stored?.sentence_fingerprint);
    expect(anchorKey(anchor)).toBe(anchorKey(stored!));
  });

  it("records human provenance naming this editor, since note.add cannot", () => {
    expect(anchor.provenance).toEqual({
      source: "human",
      actor: "human",
      workflow: VSCODE_WORKFLOW,
    });
  });

  it("starts valid and fresh, as manuscript/anchors.py::build_anchor does", () => {
    expect(anchor.status).toBe("valid");
    expect(anchor.stale).toBe("fresh");
    expect(anchor.citation_keys).toEqual(["traffic2024"]);
  });
});

describe("verifyAttachment", () => {
  it("accepts an anchor the audit reports as valid", () => {
    const stored = report.revalidations[0]?.anchor;
    expect(verifyAttachment(report, stored!).ok).toBe(true);
  });

  it("refuses when the audit knows no such anchor, and says why", () => {
    const stranger = { ...report.revalidations[0]!.anchor, sentence_fingerprint: "sha256:nope" };
    const check = verifyAttachment(report, stranger);
    expect(check.ok).toBe(false);
    expect(check.reason).toContain("manuscriptRoot");
  });

  it("refuses a stale verdict and points at the CLI that can fix it", () => {
    const stale: ManuscriptAuditReport = {
      ...report,
      revalidations: [
        {
          status: "stale",
          anchor: report.revalidations[0]!.anchor,
          reason: "sentence was reworded",
        },
      ],
    };
    const check = verifyAttachment(stale, report.revalidations[0]!.anchor);
    expect(check.ok).toBe(false);
    expect(check.reason).toContain("research manuscript attach main.tex:14 C0001");
  });
});

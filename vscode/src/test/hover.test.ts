/**
 * The Product 28 hover: Claim id, status, scope, evidence count, qualifiers, stale state.
 *
 * The specification's own example is
 *
 *     C0041 - QUALIFIED
 *     7 supporting works - 1 qualifying work
 *     [Open Claim] [Open Evidence] [Audit]
 *
 * so that is the shape asserted here, counts and all.
 */

import { describe, expect, it } from "vitest";

import type {
  AnchorRevalidation,
  ClaimSupport,
  EvidenceRelationView,
  ManuscriptAnchor,
} from "../client/types";
import {
  evidenceCount,
  hoverMarkdown,
  isStale,
  summaryLine,
  unattachedMarkdown,
  type ClaimUnderCursor,
} from "../manuscript/hover";
import { anchorsOf, claimsIn, findingsInRange } from "../manuscript/report";
import type { ManuscriptAuditReport } from "../client/types";
import auditReport from "./fixtures/audit-report.json";

const report = auditReport as unknown as ManuscriptAuditReport;

const anchor: ManuscriptAnchor = {
  provenance: { source: "human", actor: "human", workflow: "vscode" },
  file: "main.tex",
  line_start: 41,
  line_end: 42,
  sentence: "Byte-level tokenization improves recall on short encrypted flows.",
  sentence_fingerprint: "sha256:abc",
  claim: "C0041",
  citation_keys: ["traffic2024"],
  status: "valid",
  stale: "fresh",
};

function relations(works: Array<string | null>): EvidenceRelationView[] {
  return works.map((work, index) => ({
    evidence: `E00${index + 1}`,
    relation: "supports",
    resolved: work !== null,
    work,
  }));
}

const support: ClaimSupport = {
  claim: "C0041",
  statement: "Byte-level tokenization improves recall in the reviewed corpus",
  status: "qualified",
  requested_strength: "field_generalization",
  allowed_strength: "corpus_pattern",
  supporting: relations(["W0001", "W0002", "W0003", "W0004", "W0005", "W0006", "W0007"]),
  qualifying: relations(["W0008"]),
  contradicting: [],
};

const links = {
  claimUrl: "http://127.0.0.1:5173/claims/C0041",
  openEvidenceCommand: "command:researchHarness.openEvidence",
  auditCommand: "command:researchHarness.auditSelection",
};

describe("evidence counting", () => {
  it("counts distinct works when every relation resolved to one", () => {
    expect(evidenceCount(relations(["W0001", "W0002", "W0001"]))).toEqual({
      count: 2,
      unit: "work",
    });
  });

  it("counts evidence objects when a relation did not resolve", () => {
    expect(evidenceCount(relations(["W0001", null]))).toEqual({
      count: 2,
      unit: "evidence object",
    });
  });

  it("reports zero rather than throwing for a group the daemon omitted", () => {
    expect(evidenceCount(undefined)).toEqual({ count: 0, unit: "evidence object" });
  });
});

describe("summaryLine", () => {
  it("reads like the Product 28 example", () => {
    expect(summaryLine({ claimId: "C0041", anchor, support })).toBe(
      "C0041 — QUALIFIED · 7 supporting works · 1 qualifying work",
    );
  });

  it("names contradicting evidence when there is any", () => {
    const contested: ClaimSupport = {
      ...support,
      status: "contested",
      contradicting: relations(["W0009"]),
    };
    expect(summaryLine({ claimId: "C0041", anchor, support: contested })).toContain(
      "1 contradicting work",
    );
  });

  it("says STALE when the anchor or the audit says so", () => {
    const verdict: AnchorRevalidation = {
      status: "stale",
      anchor,
      similarity: 0.8,
      reason: "sentence was reworded",
    };
    expect(summaryLine({ claimId: "C0041", anchor, support, verdict })).toContain("STALE");
  });

  it("still answers when claim.find_support is unavailable", () => {
    expect(summaryLine({ claimId: "C0041", anchor })).toBe("C0041 — UNKNOWN");
  });
});

describe("isStale", () => {
  it("is false for a fresh anchor over a valid verdict", () => {
    const verdict: AnchorRevalidation = { status: "valid", anchor, reason: "unchanged" };
    expect(isStale({ claimId: "C0041", anchor, verdict })).toBe(false);
  });

  it("is true when the stored anchor is marked stale", () => {
    expect(isStale({ claimId: "C0041", anchor: { ...anchor, stale: "stale" } })).toBe(true);
  });

  it("is true when the sentence has gone missing", () => {
    expect(isStale({ claimId: "C0041", anchor: { ...anchor, status: "missing" } })).toBe(true);
  });
});

describe("hoverMarkdown", () => {
  const entry: ClaimUnderCursor = { claimId: "C0041", anchor, support };
  const markdown = hoverMarkdown(entry, links);

  it("leads with the Claim and its status", () => {
    expect(markdown.split("\n")[0]).toBe("**C0041** — QUALIFIED");
  });

  it("shows what the evidence allows against what was asked for", () => {
    expect(markdown).toContain(
      "scope requested `field_generalization` → allowed `corpus_pattern`",
    );
  });

  it("shows the counts and the citation keys the anchor recorded", () => {
    expect(markdown).toContain("7 supporting works · 1 qualifying work · 0 contradicting");
    expect(markdown).toContain("cites `traffic2024`");
  });

  it("offers the three Product 28 actions", () => {
    expect(markdown).toContain("[Open Claim](http://127.0.0.1:5173/claims/C0041)");
    expect(markdown).toContain("[Open Evidence](command:researchHarness.openEvidence)");
    expect(markdown).toContain("[Audit](command:researchHarness.auditSelection)");
  });

  it("reports a stale anchor's reason rather than presenting the Claim as current", () => {
    const verdict: AnchorRevalidation = {
      status: "stale",
      anchor,
      similarity: 0.81,
      reason: "sentence was reworded (similarity 0.81 at lines 41-42)",
    };
    const stale = hoverMarkdown({ ...entry, verdict }, links);
    expect(stale).toContain("· **stale**");
    expect(stale).toContain("anchor stale: sentence was reworded");
  });

  it("says so plainly when there is no support view", () => {
    expect(hoverMarkdown({ claimId: "C0041", anchor }, links)).toContain(
      "no support view for this Claim",
    );
  });
});

describe("unattached prose", () => {
  it("flags unlinked substantive text and offers the attach command", () => {
    const markdown = unattachedMarkdown("command:researchHarness.attachClaim");
    expect(markdown).toContain("No Claim is attached");
    expect(markdown).toContain("[Attach Claim…](command:researchHarness.attachClaim)");
  });
});

describe("reading the audit report", () => {
  it("lists the Claims this manuscript already anchors, for the attach quick pick", () => {
    expect(claimsIn(report)).toEqual(["C0001", "C0002"]);
  });

  it("returns every stored anchor with its verdict", () => {
    expect(anchorsOf(report).map((item) => item.line_start)).toEqual([14, 17, 20]);
  });

  it("narrows findings to a selection, which is how Audit Selection is scoped", () => {
    const inRange = findingsInRange(report, "main.tex", 17, 17);
    expect(inRange.map((item) => item.kind)).toEqual([
      "citation_mismatch",
      "unsupported_numeric",
    ]);
    expect(findingsInRange(report, "main.tex", 1, 5)).toEqual([]);
  });
});

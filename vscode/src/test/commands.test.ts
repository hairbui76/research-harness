/**
 * The two decisions the commands still make for themselves, and nothing more.
 *
 * Which Claims the Attach Claim picker offers and in what order is a presentation choice —
 * the Claims this manuscript already anchors are the ones a researcher is writing around —
 * over a list `claim.list` produced. Whether a typed id is even shaped like a Claim id is a
 * check worth making before it costs a round trip. Everything else on these commands is a
 * capability call, which `client.test.ts` and the Python contract test cover.
 */

import { describe, expect, it } from "vitest";

import type { ClaimSummary } from "../client/types";
import { isClaimId, quickPickItems } from "../commands/manuscriptCommands";

const CLAIMS: ClaimSummary[] = [
  {
    id: "C0001",
    statement: "Byte-level tokenization improves recall",
    type: "descriptive",
    status: "supported",
    requested_strength: "corpus_pattern",
    allowed_strength: "corpus_pattern",
    stale: "fresh",
  },
  {
    id: "C0002",
    statement: "Prior surveys report no comparable figure",
    type: "descriptive",
    status: "contested",
    requested_strength: "individual",
    allowed_strength: "individual",
    stale: "stale",
  },
];

describe("the Attach Claim picker", () => {
  it("lists every Claim `claim.list` returned, this manuscript's own first", () => {
    const items = quickPickItems(CLAIMS, ["C0002"]);
    expect(items.map((item) => item.claim)).toEqual(["C0002", "C0001", undefined]);
  });

  it("shows what each Claim may say, which is the thing being chosen between", () => {
    const [contested] = quickPickItems(CLAIMS, ["C0002"]);
    expect(contested?.description).toBe("contested · stale · allowed individual");
    expect(contested?.detail).toBe("Prior surveys report no comparable figure");
  });

  it("still offers a typed id, for a Claim the list does not show", () => {
    const items = quickPickItems([], []);
    expect(items).toHaveLength(1);
    expect(items[0]?.claim).toBeUndefined();
    expect(items[0]?.label).toContain("Enter a Claim ID");
  });
});

describe("a Claim id typed by hand", () => {
  it("is recognised by the shape `domain/ids.py` writes", () => {
    expect(isClaimId("C0001")).toBe(true);
    expect(isClaimId("C12345")).toBe(true);
    expect(isClaimId("C001")).toBe(false);
    expect(isClaimId("RQ0001")).toBe(false);
  });
});

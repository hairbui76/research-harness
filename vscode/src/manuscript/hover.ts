/**
 * What the Claim under the cursor says, as text.
 *
 * Product 28 asks for the Claim id, its status, its scope, its evidence count, its
 * qualifiers, and whether it is stale - the example in the specification being
 *
 *     C0041 - QUALIFIED
 *     7 supporting works - 1 qualifying work
 *     [Open Claim] [Open Evidence] [Audit]
 *
 * Every number here is read from `claim.find_support` and `manuscript.audit`; the editor
 * counts what the harness returned and never derives a status of its own. The functions are
 * pure so the wording is unit-tested rather than eyeballed in a tooltip.
 */

import type {
  AnchorRevalidation,
  ClaimSupport,
  EvidenceRelationView,
  ManuscriptAnchor,
  TraceLink,
} from "../client/types";

/** Everything the hover knows about one anchored sentence. */
export interface ClaimUnderCursor {
  claimId: string;
  anchor: ManuscriptAnchor;
  support?: ClaimSupport | undefined;
  verdict?: AnchorRevalidation | undefined;
  trace?: TraceLink | undefined;
}

/** Links the hover offers; the caller supplies the URLs so this module stays pure. */
export interface HoverLinks {
  claimUrl: string;
  openEvidenceCommand: string;
  auditCommand: string;
}

/** How many works, or how much evidence, one relation group covers. */
export function evidenceCount(views: readonly EvidenceRelationView[] | undefined): {
  count: number;
  unit: "work" | "evidence object";
} {
  const items = views ?? [];
  const works = items.map((item) => item.work).filter((work): work is string => Boolean(work));
  if (items.length > 0 && works.length === items.length) {
    return { count: new Set(works).size, unit: "work" };
  }
  return { count: items.length, unit: "evidence object" };
}

function phrase(label: string, views: readonly EvidenceRelationView[] | undefined): string {
  const { count, unit } = evidenceCount(views);
  const plural = count === 1 ? unit : `${unit}s`;
  return `${count} ${label} ${plural}`;
}

/** True when the Claim or its anchor needs a human before the sentence ships (ADR-008). */
export function isStale(entry: ClaimUnderCursor): boolean {
  return (
    entry.anchor.stale === "stale" ||
    entry.anchor.status === "stale" ||
    entry.anchor.status === "missing" ||
    (entry.verdict !== undefined && entry.verdict.status !== "valid")
  );
}

/** The Product 28 one-liner: id, status, counts, and the stale flag when it applies. */
export function summaryLine(entry: ClaimUnderCursor): string {
  const status = (entry.support?.status ?? "unknown").toUpperCase();
  const parts = [`${entry.claimId} — ${status}`];
  if (entry.support) {
    parts.push(phrase("supporting", entry.support.supporting));
    parts.push(phrase("qualifying", entry.support.qualifying));
    const contradicting = evidenceCount(entry.support.contradicting);
    if (contradicting.count > 0) {
      parts.push(phrase("contradicting", entry.support.contradicting));
    }
  }
  if (isStale(entry)) {
    parts.push("STALE");
  }
  return parts.join(" · ");
}

/**
 * The hover body, as Markdown.
 *
 * The links are rendered last so the counts stay readable when a theme wraps the tooltip,
 * and the anchor's own verdict is reported verbatim: a reworded sentence must say so rather
 * than quietly presenting the Claim as if it still described the text (ADR-008).
 */
export function hoverMarkdown(entry: ClaimUnderCursor, links: HoverLinks): string {
  const lines: string[] = [];
  const status = (entry.support?.status ?? "unknown").toUpperCase();
  lines.push(`**${entry.claimId}** — ${status}${isStale(entry) ? " · **stale**" : ""}`);

  if (entry.support) {
    lines.push("");
    lines.push(entry.support.statement);
    lines.push("");
    const counts = [
      phrase("supporting", entry.support.supporting),
      phrase("qualifying", entry.support.qualifying),
      phrase("contradicting", entry.support.contradicting),
    ];
    lines.push(counts.join(" · "));
    lines.push("");
    lines.push(
      `scope requested \`${entry.support.requested_strength}\` → ` +
        `allowed \`${entry.support.allowed_strength}\``,
    );
  } else {
    lines.push("");
    lines.push("_the daemon returned no support view for this Claim_");
  }

  if (entry.anchor.citation_keys && entry.anchor.citation_keys.length > 0) {
    lines.push("");
    lines.push(`cites ${entry.anchor.citation_keys.map((key) => `\`${key}\``).join(", ")}`);
  }

  if (entry.verdict && entry.verdict.status !== "valid") {
    lines.push("");
    lines.push(`anchor ${entry.verdict.status}: ${entry.verdict.reason}`);
  }

  const spans = entry.trace?.spans ?? [];
  if (spans.length > 0) {
    lines.push("");
    lines.push(
      spans
        .map((span) => `source page ${span.page}${span.bbox ? "" : " (no geometry)"}`)
        .join(" · "),
    );
  }

  lines.push("");
  lines.push(
    `[Open Claim](${links.claimUrl}) · ` +
      `[Open Evidence](${links.openEvidenceCommand}) · ` +
      `[Audit](${links.auditCommand})`,
  );
  return lines.join("\n");
}

/** What to say over a substantive sentence the research graph does not account for. */
export function unattachedMarkdown(attachCommand: string): string {
  return [
    "**No Claim is attached to this sentence.**",
    "",
    "Unlinked substantive prose is not traceable to accepted evidence (Product 30.1).",
    "",
    `[Attach Claim…](${attachCommand})`,
  ].join("\n");
}

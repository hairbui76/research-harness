/**
 * Building the anchor `manuscript.attach_claim` writes.
 *
 * The capability takes a whole `ManuscriptAnchor`, so an HTTP client has to assemble one -
 * including the fingerprint, which is `sha256(normalize_sentence(text))` and is what the
 * harness later matches the sentence by. The CLI does not have this problem: it calls
 * `ManuscriptService.attach(("main.tex", 16), claim)` and the server both finds the sentence
 * and builds the anchor.
 *
 * GAP: there is no `manuscript.attach_claim` request that takes `file` and `line`, and no
 * read capability that returns the project's sentence stream, so the editor has to
 * reproduce the segmentation (see `latex.ts`). `verifyAttachment` closes the loop: after
 * attaching, the next audit must report the new anchor as `valid`, and if it does not, the
 * researcher is told the editor and the harness disagreed rather than being left with an
 * anchor that silently matches nothing. See `docs/architecture/vscode.md`.
 */

import type { ManuscriptAnchor, ManuscriptAuditReport } from "../client/types";
import type { LocalSentence } from "./latex";
import { anchorKey, verdictOf } from "./report";

/** The actor the daemon records for a token-bearing caller (`Principal.human()`). */
export const HUMAN_ACTOR = "human";

/** Names this extension in the anchor's provenance, since `note.add` has no source field. */
export const VSCODE_WORKFLOW = "vscode";

/**
 * Anchor `sentence` to `claim`: location, normalized text, fingerprint, citations.
 *
 * The normalized sentence is stored rather than the raw source, so whitespace, comments,
 * and citation-command churn do not present as content changes - the same rule as
 * `manuscript/anchors.py::build_anchor`.
 */
export function buildAnchor(
  sentence: LocalSentence,
  claim: string,
  actor: string = HUMAN_ACTOR,
): ManuscriptAnchor {
  return {
    provenance: { source: "human", actor, workflow: VSCODE_WORKFLOW },
    file: sentence.file,
    line_start: sentence.lineStart,
    line_end: sentence.lineEnd,
    char_start: sentence.charStart,
    char_end: sentence.charEnd,
    sentence: sentence.normalizedText,
    sentence_fingerprint: sentence.fingerprint,
    claim,
    citation_keys: sentence.citationKeys,
    status: "valid",
    stale: "fresh",
  };
}

/** What a post-attach audit says about the anchor that was just written. */
export interface AttachmentCheck {
  ok: boolean;
  reason: string;
}

/**
 * Whether the harness recognises the anchor the editor just wrote.
 *
 * A `valid` verdict means the editor's sentence boundaries and the harness's agree. Anything
 * else means the port in `latex.ts` cut the sentence somewhere the harness did not, and the
 * anchor now names text the manuscript does not contain - which the researcher must hear
 * about immediately, because an unmatched anchor audits as a missing one forever.
 */
export function verifyAttachment(
  report: ManuscriptAuditReport,
  anchor: ManuscriptAnchor,
): AttachmentCheck {
  const key = anchorKey(anchor);
  const verdict = verdictOf(report, key);
  if (!verdict) {
    return {
      ok: false,
      reason:
        `the audit does not know an anchor at ${key}; the daemon may be reading a different ` +
        "manuscript project than this editor (check `researchHarness.manuscriptRoot`)",
    };
  }
  if (verdict.status === "valid") {
    return { ok: true, reason: verdict.reason };
  }
  return {
    ok: false,
    reason:
      `the harness reports the new anchor as ${verdict.status}: ${verdict.reason}. ` +
      "The editor's sentence boundary differs from the harness's; re-attach with " +
      `\`research manuscript attach ${anchor.file}:${anchor.line_start} ${anchor.claim}\`.`,
  };
}

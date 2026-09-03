/**
 * Reading a `manuscript.audit` report: where a finding is, and what the graph says there.
 *
 * One audit answers every manuscript question the editor asks. `findings` carries what is
 * wrong, `revalidations` carries every stored anchor with its current verdict, and `trace`
 * carries the resolved Product 30.1 chain for each anchored sentence - so the hover, the
 * diagnostics, and `Open Evidence` all read the same report rather than three views that
 * can disagree.
 *
 * A finding says where it is: `ManuscriptAuditFinding.location` carries the file, the line
 * range, and the character span. `findingLocation` reads that field. The auditor still
 * writes the `"<file>:<line>: "` prefix into the message
 * (`manuscript/audit.py::_Auditor._add`), and parsing it is kept only as a fallback for a
 * daemon built before the field existed - prose is not a location, and an editor that had to
 * read prose to place a diagnostic would be guessing.
 */

import type {
  AnchorRevalidation,
  ManuscriptAnchor,
  ManuscriptAuditFinding,
  ManuscriptAuditReport,
  TraceLink,
} from "../client/types";

/** Where a finding sits in the manuscript, in the harness's 1-based line numbering. */
export interface FindingLocation {
  file: string;
  lineStart: number;
  lineEnd: number;
  /** Half-open offsets into the raw file text, when the finding carries an anchor. */
  charStart?: number;
  charEnd?: number;
}

const MESSAGE_LOCATION = /^(.+?):(\d+):\s/;

/** The `"<file>:<line>: "` prefix stripped, so a diagnostic does not repeat the range. */
export function findingMessage(finding: ManuscriptAuditFinding): string {
  return finding.message.replace(MESSAGE_LOCATION, "");
}

/**
 * Where a finding is.
 *
 * The finding's own `location` is the answer whenever the daemon supplies one. The message
 * prefix and the anchor's span are the fallback, and only that: they are what an older
 * daemon leaves behind, and they cannot place a finding about a sentence with no anchor and
 * no prefix. `undefined` means nothing said where this happened.
 */
export function findingLocation(finding: ManuscriptAuditFinding): FindingLocation | undefined {
  const reported = finding.location;
  if (reported) {
    const location: FindingLocation = {
      file: reported.file,
      lineStart: reported.line_start,
      lineEnd: Math.max(reported.line_start, reported.line_end),
    };
    if (typeof reported.char_start === "number" && typeof reported.char_end === "number") {
      location.charStart = reported.char_start;
      location.charEnd = reported.char_end;
    }
    return location;
  }
  const anchor = finding.anchor ?? undefined;
  const match = MESSAGE_LOCATION.exec(finding.message);
  if (match) {
    const file = match[1] as string;
    const lineStart = Number.parseInt(match[2] as string, 10);
    if (anchor && anchor.file === file && anchor.line_start === lineStart) {
      return locationOfAnchor(anchor);
    }
    return { file, lineStart, lineEnd: lineStart };
  }
  return anchor ? locationOfAnchor(anchor) : undefined;
}

/** The span an anchor records; `char_start`/`char_end` index the raw file text. */
export function locationOfAnchor(anchor: ManuscriptAnchor): FindingLocation {
  const location: FindingLocation = {
    file: anchor.file,
    lineStart: anchor.line_start,
    lineEnd: Math.max(anchor.line_start, anchor.line_end),
  };
  if (typeof anchor.char_start === "number" && typeof anchor.char_end === "number") {
    location.charStart = anchor.char_start;
    location.charEnd = anchor.char_end;
  }
  return location;
}

/** `<file>#<sentence fingerprint>` - the workspace's key for a stored anchor. */
export function anchorKey(anchor: ManuscriptAnchor): string {
  return `${anchor.file}#${anchor.sentence_fingerprint}`;
}

/** Every stored anchor the audit saw, newest verdict per key. */
export function anchorsOf(report: ManuscriptAuditReport): ManuscriptAnchor[] {
  return report.revalidations.map((result) => result.anchor);
}

/** The revalidation verdict for one anchor key, when the audit produced one. */
export function verdictOf(
  report: ManuscriptAuditReport,
  key: string,
): AnchorRevalidation | undefined {
  return report.revalidations.find((result) => anchorKey(result.anchor) === key);
}

/** The resolved trace chain for one anchor key. */
export function traceFor(report: ManuscriptAuditReport, key: string): TraceLink | undefined {
  return report.trace.find((link) => link.anchor_key === key);
}

/**
 * The anchor covering a location, matched on the fingerprint first and the line second.
 *
 * The fingerprint is the anchor's identity, so an exact match is authoritative even when
 * the sentence has moved. Falling back to the line range keeps the hover working while the
 * buffer is dirty and the daemon is still reading the file as it was last saved.
 */
export function anchorAt(
  report: ManuscriptAuditReport,
  file: string,
  line: number,
  fingerprint?: string,
): ManuscriptAnchor | undefined {
  const anchors = anchorsOf(report);
  if (fingerprint) {
    const exact = anchors.find(
      (anchor) => anchor.file === file && anchor.sentence_fingerprint === fingerprint,
    );
    if (exact) {
      return exact;
    }
  }
  return anchors.find(
    (anchor) =>
      anchor.file === file &&
      anchor.line_start <= line &&
      line <= Math.max(anchor.line_start, anchor.line_end),
  );
}

/** Distinct Claim ids this manuscript already attaches, in first-seen order. */
export function claimsIn(report: ManuscriptAuditReport): string[] {
  const seen: string[] = [];
  for (const anchor of anchorsOf(report)) {
    if (!seen.includes(anchor.claim)) {
      seen.push(anchor.claim);
    }
  }
  for (const link of report.trace) {
    if (!seen.includes(link.claim)) {
      seen.push(link.claim);
    }
  }
  return seen;
}

/**
 * Findings whose location falls inside `[lineStart, lineEnd]` of one file.
 *
 * For a report already in hand. `Research: Audit Selection` does not use it: it asks
 * `manuscript.audit` for the range, which narrows the report *and* the re-parsing, and
 * applies the same rule server-side (`manuscript/audit.py::narrow_report`).
 */
export function findingsInRange(
  report: ManuscriptAuditReport,
  file: string,
  lineStart: number,
  lineEnd: number,
): ManuscriptAuditFinding[] {
  return report.findings.filter((finding) => {
    const location = findingLocation(finding);
    return (
      location !== undefined &&
      location.file === file &&
      location.lineEnd >= lineStart &&
      location.lineStart <= lineEnd
    );
  });
}

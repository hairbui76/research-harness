/**
 * One place that turns "the cursor is here" into "this is the Claim, and this is its state".
 *
 * Everything the editor shows comes from two capability calls - `manuscript.audit` for the
 * manuscript's whole picture, and `claim.find_support` for one Claim's evidence - so the
 * hover, the diagnostics, `Open Evidence`, and `Audit Selection` cannot disagree with each
 * other. The audit is cached for a moment because a hover fires on mouse move and an audit
 * re-parses source PDFs; every command that changes state invalidates the cache instead.
 */

import * as vscode from "vscode";

import type { HarnessClient } from "../client/HarnessClient";
import { auditManuscript, findSupport, manuscriptAnchors, traceSentence } from "../client/requests";
import type {
  ClaimSupport,
  ManuscriptAnchors,
  ManuscriptAuditReport,
  ManuscriptProjectRequest,
  TraceView,
} from "../client/types";
import { manuscriptRelativePath, manuscriptRoot, readSettings, type Settings } from "../config";
import { sentenceAtLine, sentencesOf, type LocalSentence } from "./latex";
import { anchorAt, anchorKey, traceFor, verdictOf } from "./report";
import type { ClaimUnderCursor } from "./hover";

/** How long an audit report is reused before the next hover pays for a fresh one. */
const AUDIT_TTL_MS = 4_000;

export class ManuscriptService {
  private cached: { report: ManuscriptAuditReport; at: number } | undefined;
  private supportCache = new Map<string, { support: ClaimSupport; at: number }>();

  constructor(private client: HarnessClient) {}

  /** Point at a rebuilt client after a settings change; every cached read is dropped. */
  setClient(client: HarnessClient): void {
    this.client = client;
    this.invalidate();
  }

  /** Current settings; read fresh so a changed daemon URL takes effect without a reload. */
  settings(): Settings {
    return readSettings();
  }

  /** Drop every cached read. Called after any mutation and on a settings change. */
  invalidate(): void {
    this.cached = undefined;
    this.supportCache.clear();
  }

  /** The request that names this workspace's manuscript project to the daemon. */
  projectRequest(): ManuscriptProjectRequest {
    const settings = this.settings();
    const root = manuscriptRoot(settings);
    return root
      ? { project_root: root, main_tex: settings.mainTex }
      : { main_tex: settings.mainTex };
  }

  /** The manuscript audit, from cache when it is fresh enough for a hover. */
  async audit(options: { force?: boolean } = {}): Promise<ManuscriptAuditReport> {
    const now = Date.now();
    if (!options.force && this.cached && now - this.cached.at < AUDIT_TTL_MS) {
      return this.cached.report;
    }
    const report = await auditManuscript(this.client, this.projectRequest());
    this.cached = { report, at: now };
    return report;
  }

  /**
   * The audit of one line range, asked of the daemon rather than filtered here.
   *
   * Never cached: it is a different question from the whole-project audit the hover reads,
   * and caching it under the same key would answer that question with this one's counts.
   */
  async auditRange(file: string, lineStart: number, lineEnd: number): Promise<ManuscriptAuditReport> {
    return auditManuscript(this.client, {
      ...this.projectRequest(),
      file,
      line_start: lineStart,
      line_end: lineEnd,
    });
  }

  /** Every stored anchor with its current verdict, without auditing the whole manuscript. */
  async anchors(): Promise<ManuscriptAnchors> {
    return manuscriptAnchors(this.client, this.projectRequest());
  }

  /**
   * One sentence down to the Claim and source spans behind it (`manuscript.trace`).
   *
   * `undefined` when the daemon refused - the caller already has the sentence and the
   * anchor, and a failed trace must not turn a working hover into an error.
   */
  async trace(file: string, line: number): Promise<TraceView | undefined> {
    return traceSentence(this.client, { ...this.projectRequest(), file, line }).catch(
      () => undefined,
    );
  }

  /** What a Claim rests on, cached for the life of one audit window. */
  async support(claimId: string): Promise<ClaimSupport | undefined> {
    const now = Date.now();
    const hit = this.supportCache.get(claimId);
    if (hit && now - hit.at < AUDIT_TTL_MS) {
      return hit.support;
    }
    const support = await findSupport(this.client, claimId);
    this.supportCache.set(claimId, { support, at: now });
    return support;
  }

  /** The harness's name for a document, or undefined when it is not in this manuscript. */
  relativePath(document: vscode.TextDocument): string | undefined {
    return manuscriptRelativePath(this.settings(), document.uri.fsPath);
  }

  /**
   * The sentence the cursor is in, computed from the buffer.
   *
   * Local rather than remote on purpose: the daemon reads the file from disk, so it cannot
   * answer for an unsaved edit, and a hover must not wait on a round trip.
   */
  sentenceAt(document: vscode.TextDocument, position: vscode.Position): LocalSentence | undefined {
    const file = this.relativePath(document);
    if (!file) {
      return undefined;
    }
    const sentences = sentencesOf(file, document.getText());
    return sentenceAtLine(sentences, position.line + 1);
  }

  /**
   * The Claim attached to the sentence under the cursor, with everything the hover shows.
   *
   * `undefined` means no Claim is attached here, which is a different answer from "the
   * chain is broken" and is shown as such.
   */
  async claimUnderCursor(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<ClaimUnderCursor | undefined> {
    const file = this.relativePath(document);
    if (!file) {
      return undefined;
    }
    const sentence = this.sentenceAt(document, position);
    const report = await this.audit();
    const anchor = anchorAt(report, file, position.line + 1, sentence?.fingerprint);
    if (!anchor) {
      return undefined;
    }
    const key = anchorKey(anchor);
    return {
      claimId: anchor.claim,
      anchor,
      support: await this.support(anchor.claim).catch(() => undefined),
      verdict: verdictOf(report, key),
      trace: traceFor(report, key),
    };
  }
}

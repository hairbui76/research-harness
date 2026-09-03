/**
 * `Research: Audit Selection`, `Attach Claim`, `Create Claim from Selection`,
 * `Revalidate Anchors`, and `Show Claim Under Cursor` (Roadmap Tasks 16.2 and 16.3).
 *
 * Each command is one capability call plus the interaction that decides its arguments. What
 * they never do is decide anything scientific: `claim.create` fixes a new Claim at L0
 * whatever scope was asked for, `manuscript.attach_claim` refuses a Claim the workspace does
 * not hold, and the audit reports rather than repairs. The editor's job is to make those
 * answers reachable from the line the researcher is looking at.
 */

import * as vscode from "vscode";

import {
  CLAIM_SCOPES,
  attachClaim as attachClaimCapability,
  createClaim,
  listClaims,
  revalidateAnchors as revalidateAnchorsCapability,
} from "../client/requests";
import type {
  ClaimScope,
  ClaimSummary,
  ClaimSupport,
  ClaimType,
  ManuscriptAuditFinding,
  ManuscriptAuditReport,
  NewClaim,
} from "../client/types";
import { claimUrl } from "../config";
import { buildAnchor, HUMAN_ACTOR, verifyAttachment } from "../manuscript/anchor";
import { severityFor } from "../manuscript/diagnostics";
import { summaryLine } from "../manuscript/hover";
import type { LocalSentence } from "../manuscript/latex";
import { anchorKey, claimsIn, findingMessage, verdictOf } from "../manuscript/report";
import {
  type CommandContext,
  type InvocationTarget,
  report,
  requireSentence,
  resolveTarget,
  withErrors,
} from "./context";

/** `domain/enums.py::ClaimType`, in the order the specification lists them. */
const CLAIM_TYPES: readonly ClaimType[] = [
  "descriptive",
  "comparative",
  "prevalence",
  "absence",
  "causal",
  "taxonomic",
  "methodological",
  "synthesis",
  "recommendation",
];

/** `claims/service.py::INITIAL_ALLOWED_STRENGTH`: a new Claim has earned nothing yet. */
const INITIAL_ALLOWED_STRENGTH: ClaimScope = "individual";

/**
 * `C` plus at least four digits - `domain/ids.py::ResearchId.make`.
 *
 * The only thing left of the client-side id allocation this extension used to carry:
 * `claim.create` names a new Claim itself, so nothing here computes an id. This validates
 * one a researcher typed, before it costs a round trip.
 */
export function isClaimId(value: string): boolean {
  return /^C\d{4,}$/.test(value.trim());
}

// -- Research: Audit Selection ----------------------------------------------

/**
 * Audit the lines the researcher selected.
 *
 * The range goes to `manuscript.audit`, which narrows both the report and the re-parsing:
 * only the artifacts the anchors in those lines rest on are read back. The rules are
 * identical either way - narrowing changes what is asked about, never what counts as a
 * finding - and nothing is filtered here, so the editor cannot disagree with the auditor.
 */
export async function auditSelection(context: CommandContext): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    void vscode.window.showWarningMessage("Research Harness: open a LaTeX file to audit.");
    return;
  }
  const file = context.manuscript.relativePath(editor.document);
  if (!file) {
    void vscode.window.showWarningMessage(
      "Research Harness: this file is not inside the manuscript project.",
    );
    return;
  }

  const selection = editor.selection;
  const lineStart = selection.start.line + 1;
  const lineEnd = selection.end.line + 1;

  const result = await withErrors(context, "audit selection", () =>
    context.manuscript.auditRange(file, lineStart, lineEnd),
  );
  if (!result) {
    return;
  }

  await context.refreshDiagnostics({ force: false });
  showFindings(context, result, result.findings, `${file}:${lineStart}-${lineEnd}`);
}

function showFindings(
  context: CommandContext,
  audit: ManuscriptAuditReport,
  findings: readonly ManuscriptAuditFinding[],
  where: string,
): void {
  report(context, `manuscript audit — ${where}`, [
    `${audit.sentences_checked} substantive sentences: ${audit.anchored_sentences} anchored, ` +
      `${audit.unanchored_substantive} unregistered`,
    ...findings.map(
      (finding) => `[${finding.severity}] ${finding.kind}: ${findingMessage(finding)}`,
    ),
  ]);

  if (findings.length === 0) {
    void vscode.window.showInformationMessage(
      `Research Harness: nothing to report for ${where}.`,
    );
    return;
  }
  void vscode.window.showQuickPick(
    findings.map((finding) => ({
      label: `$(${iconFor(finding)}) ${finding.kind}`,
      description: (finding.related ?? []).join(", "),
      detail: findingMessage(finding),
    })),
    { title: `Manuscript findings — ${where}`, matchOnDetail: true },
  );
}

function iconFor(finding: ManuscriptAuditFinding): string {
  const severity = severityFor(finding.kind, finding.severity);
  if (severity === vscode.DiagnosticSeverity.Error) {
    return "error";
  }
  return severity === vscode.DiagnosticSeverity.Warning ? "warning" : "info";
}

// -- Research: Attach Claim --------------------------------------------------

/** Bind the sentence at the cursor to an existing Claim (`manuscript.attach_claim`). */
export async function attachClaim(
  context: CommandContext,
  target?: InvocationTarget,
): Promise<void> {
  const resolved = resolveTarget(target);
  if (!resolved) {
    return;
  }
  const sentence = requireSentence(context, resolved.editor, resolved.position);
  if (!sentence) {
    return;
  }
  const claim = await pickClaim(context, sentence);
  if (!claim) {
    return;
  }
  await attachSentence(context, sentence, claim);
}

/** Attach one already-chosen Claim, then check the harness recognised the anchor. */
export async function attachSentence(
  context: CommandContext,
  sentence: LocalSentence,
  claim: string,
): Promise<void> {
  const anchor = buildAnchor(sentence, claim, HUMAN_ACTOR);
  const done = await withErrors(context, "attach claim", async () => {
    const mutation = await attachClaimCapability(context.client, anchor);
    context.manuscript.invalidate();
    const audit = await context.manuscript.audit({ force: true });
    return { mutation, check: verifyAttachment(audit, anchor) };
  });
  if (!done) {
    return;
  }

  report(context, `attached ${claim}`, [
    `${anchor.file}:${anchor.line_start}-${anchor.line_end}`,
    `sentence      ${anchor.sentence}`,
    `fingerprint   ${anchor.sentence_fingerprint}`,
    `citations     ${(anchor.citation_keys ?? []).join(", ") || "-"}`,
    `event         ${done.mutation.event.event}`,
    `verified      ${done.check.ok ? "yes" : "NO"} — ${done.check.reason}`,
  ]);

  await context.refreshDiagnostics({ force: false });

  if (done.check.ok) {
    void vscode.window.showInformationMessage(
      `Research Harness: attached ${claim} to ${anchor.file}:${anchor.line_start}.`,
    );
  } else {
    const choice = await vscode.window.showWarningMessage(
      `Research Harness: attached ${claim}, but ${done.check.reason}`,
      "Show details",
    );
    if (choice === "Show details") {
      context.output.show(true);
    }
  }
}

/**
 * Which Claim to attach.
 *
 * `claim.list` answers this for every transport, so the picker lists the whole workspace and
 * an MCP host gets the same answer from the same name. The Claims this manuscript already
 * anchors come first, because they are the ones a researcher is writing around. A typed id
 * stays available for a Claim the list does not show, validated with `GET /objects/{id}`.
 */
async function pickClaim(
  context: CommandContext,
  sentence: LocalSentence,
): Promise<string | undefined> {
  const listed = await withErrors(context, "list claims", () => listClaims(context.client));
  const anchored = await withErrors(context, "read anchors", async () =>
    claimsIn(await context.manuscript.audit()),
  );
  const items = quickPickItems(listed ?? [], anchored ?? []);

  const picked = await vscode.window.showQuickPick(items, {
    title: `Attach a Claim to “${truncate(sentence.normalizedText, 70)}”`,
    matchOnDetail: true,
  });
  if (!picked) {
    return undefined;
  }
  if (picked.claim) {
    return picked.claim;
  }
  return promptForClaimId(context);
}

export type ClaimPickItem = vscode.QuickPickItem & { claim?: string };

/** The picker's rows: this manuscript's Claims first, then the rest, then free text. */
export function quickPickItems(
  listed: readonly ClaimSummary[],
  anchored: readonly string[],
): ClaimPickItem[] {
  const ordered = [
    ...listed.filter((claim) => anchored.includes(claim.id)),
    ...listed.filter((claim) => !anchored.includes(claim.id)),
  ];
  return [
    ...ordered.map((claim) => ({
      label: claim.id,
      description:
        `${claim.status}${claim.stale === "stale" ? " · stale" : ""} · ` +
        `allowed ${claim.allowed_strength}`,
      detail: claim.statement,
      claim: claim.id,
    })),
    { label: "$(edit) Enter a Claim ID…", detail: "For a Claim this list does not show." },
  ];
}

async function promptForClaimId(context: CommandContext): Promise<string | undefined> {
  const typed = await vscode.window.showInputBox({
    title: "Claim ID",
    prompt: "The Claim to attach, as the harness writes it.",
    placeHolder: "C0001",
    validateInput: (value) =>
      isClaimId(value) ? undefined : "A Claim id looks like C0001 (`C` plus four digits).",
  });
  if (!typed) {
    return undefined;
  }
  const id = typed.trim();
  const exists = await withErrors(context, "check claim", () => context.client.objectExists(id));
  if (exists === undefined) {
    return undefined;
  }
  if (!exists) {
    void vscode.window.showErrorMessage(`Research Harness: this workspace holds no ${id}.`);
    return undefined;
  }
  return id;
}

// -- Research: Create Claim from Selection -----------------------------------

/**
 * Register a Claim from the selected prose and attach it to the sentence at the cursor.
 *
 * The Claim is created at L0 whatever scope is asked for: `requested_strength` records the
 * ask and `allowed_strength` is what `claim.audit` later earns (Product 42.G). The
 * defaults for the proposition mirror `research claim create`, which uses the statement for
 * subject and object and `asserts` for the predicate when the researcher gives no better
 * decomposition.
 */
export async function createClaimFromSelection(context: CommandContext): Promise<void> {
  const resolved = resolveTarget();
  if (!resolved) {
    return;
  }
  const { editor } = resolved;
  const selected = editor.document.getText(editor.selection).trim();
  const sentence = requireSentence(context, editor, editor.selection.active);
  if (!sentence) {
    return;
  }

  const statement = await vscode.window.showInputBox({
    title: "New Claim — statement",
    prompt: "The claim as it would be written, not the sentence's LaTeX.",
    value: selected || sentence.normalizedText,
    validateInput: (value) => (value.trim() ? undefined : "A Claim needs a statement."),
  });
  if (!statement) {
    return;
  }

  const type = await vscode.window.showQuickPick([...CLAIM_TYPES], {
    title: "New Claim — type",
    placeHolder: "descriptive",
  });
  if (!type) {
    return;
  }

  const scope = await vscode.window.showQuickPick(
    CLAIM_SCOPES.map((level, index) => ({
      label: `L${index} ${level}`,
      description: index === 0 ? "the ask a new Claim starts from" : undefined,
      level,
    })),
    { title: "New Claim — requested scope (the ask, not what evidence allows)" },
  );
  if (!scope) {
    return;
  }

  // No id: `claim.create` allocates the next free `ClaimId` under the workspace lock and
  // returns it, so the editor neither guesses one nor races another client for it.
  const claim: NewClaim = {
    statement: statement.trim(),
    type: type as ClaimType,
    semantics: { subject: statement.trim(), predicate: "asserts", object: statement.trim() },
    scope: { level: scope.level },
    assessment: {
      requested_strength: scope.level,
      allowed_strength: INITIAL_ALLOWED_STRENGTH,
      status: "unverified",
    },
    provenance: { source: "human", actor: HUMAN_ACTOR, workflow: "vscode" },
  };

  const created = await withErrors(context, "create claim", async () => {
    const mutation = await createClaim(context.client, claim);
    context.manuscript.invalidate();
    return mutation;
  });
  if (!created) {
    return;
  }
  const claimId = created.objects[0];
  if (!claimId) {
    void vscode.window.showErrorMessage(
      "Research Harness: claim.create wrote a Claim but named no id; nothing was attached.",
    );
    return;
  }
  report(context, `created ${claimId}`, [
    `statement     ${claim.statement}`,
    `type          ${claim.type}`,
    `requested     ${claim.scope.level}`,
    `allowed       ${INITIAL_ALLOWED_STRENGTH} (an audit earns anything more)`,
    `id            ${claimId} (allocated by the harness)`,
    `event         ${created.event.event}`,
  ]);

  await attachSentence(context, sentence, claimId);
}

// -- Research: Revalidate Anchors --------------------------------------------

/**
 * Re-find every stored anchor and record what the manuscript now says.
 *
 * `manuscript.revalidate` does the recording, which is why this is a mutation and needs the
 * local token: a sentence that moved keeps its anchor and adopts its new lines, and one that
 * was reworded or deleted is written back stale or missing rather than being reattached to
 * text nobody chose (ADR-008). The editor reports the verdicts; the rule stays in one place.
 */
export async function revalidateAnchors(context: CommandContext): Promise<void> {
  const result = await withErrors(context, "revalidate anchors", async () => {
    const view = await revalidateAnchorsCapability(
      context.client,
      context.manuscript.projectRequest(),
    );
    context.manuscript.invalidate();
    return view;
  });
  if (!result) {
    return;
  }
  await context.refreshDiagnostics({ force: false });

  report(
    context,
    `anchor revalidation (${result.applied.length} recorded)`,
    result.results.length === 0
      ? ["no manuscript anchors yet"]
      : result.results.map(
          (item) =>
            `${item.status.padEnd(7)} ${item.file}:${item.line_start} ${item.claim}  ` +
            `${item.reason ?? ""}` +
            (item.relocated_to ? ` → ${item.relocated_to[0]}-${item.relocated_to[1]}` : ""),
        ),
  );

  if (result.checked === 0) {
    void vscode.window.showInformationMessage("Research Harness: this manuscript has no anchors.");
    return;
  }
  const message =
    `Research Harness: ${result.checked} anchors — ${result.valid} valid, ` +
    `${result.relocated} relocated, ${result.stale} stale, ${result.missing} missing. ` +
    `${result.applied.length} recorded.`;
  const choice = await vscode.window.showInformationMessage(message, "Show details");
  if (choice === "Show details") {
    context.output.show(true);
  }
}

// -- Research: Show Claim Under Cursor ---------------------------------------

/** The Product 28 one-liner for the sentence at the cursor, with its actions. */
export async function showClaimUnderCursor(context: CommandContext): Promise<void> {
  const resolved = resolveTarget();
  if (!resolved) {
    return;
  }
  // Wrapped so "the daemon failed" (already reported by `withErrors`) stays distinguishable
  // from "this sentence carries no Claim", which is a real answer and not an error.
  const found = await withErrors(context, "claim under cursor", async () => ({
    entry: await context.manuscript.claimUnderCursor(resolved.editor.document, resolved.position),
  }));
  if (!found) {
    return;
  }
  const entry = found.entry;
  if (!entry) {
    void vscode.window.showInformationMessage(
      "Research Harness: no Claim is attached to this sentence.",
    );
    return;
  }

  const key = anchorKey(entry.anchor);
  // `manuscript.trace` answers for one sentence, so the one-liner no longer costs a
  // whole-project audit. The verdict comes from the cached report the hover already read.
  const trace = await context.manuscript.trace(
    entry.anchor.file,
    resolved.position.line + 1,
  );
  const verdict = entry.verdict ?? verdictOf(await context.manuscript.audit(), key);
  report(context, summaryLine(entry), [
    `sentence      ${entry.anchor.sentence}`,
    `anchor        ${trace?.anchor ?? key} (${verdict?.status ?? entry.anchor.status ?? "unknown"})`,
    `evidence      ${(trace?.link?.evidence ?? []).join(", ") || "-"}`,
    ...describeSupport(entry.support),
    ...(trace?.link?.spans ?? []).map(
      (span) => `span          page ${span.page} ${span.bbox ? span.bbox.join(", ") : "no geometry"}`,
    ),
  ]);

  const choice = await vscode.window.showInformationMessage(
    summaryLine(entry),
    "Open Claim",
    "Open Evidence",
    "Audit Selection",
  );
  if (choice === "Open Claim") {
    await vscode.env.openExternal(
      vscode.Uri.parse(claimUrl(context.manuscript.settings(), entry.claimId)),
    );
  } else if (choice === "Open Evidence") {
    await vscode.commands.executeCommand("researchHarness.openEvidence");
  } else if (choice === "Audit Selection") {
    await vscode.commands.executeCommand("researchHarness.auditSelection");
  }
}

function describeSupport(support: ClaimSupport | undefined): string[] {
  if (!support) {
    return ["support       (claim.find_support returned nothing)"];
  }
  return [
    `statement     ${support.statement}`,
    `status        ${support.status}`,
    `scope         requested ${support.requested_strength} → allowed ${support.allowed_strength}`,
    `supporting    ${(support.supporting ?? []).map((item) => item.evidence).join(", ") || "-"}`,
    `qualifying    ${(support.qualifying ?? []).map((item) => item.evidence).join(", ") || "-"}`,
    `contradicting ${(support.contradicting ?? []).map((item) => item.evidence).join(", ") || "-"}`,
  ];
}

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

/**
 * The exact capability calls this extension makes, in one place.
 *
 * Every function here is one named capability with its request object spelled out. Keeping
 * them together makes the extension's whole write surface auditable at a glance, and gives
 * `tests/contract/protocol/test_vscode_contract.py` a single list to call against a real
 * daemon: if a request shape drifts from `capabilities/dto.py`, that test fails rather than
 * a researcher's hover.
 *
 * Nothing here decides anything. A function that needed a rule would belong in the
 * capability layer instead (ADR-004).
 */

import type { HarnessClient } from "./HarnessClient";
import { CAPABILITIES } from "./types";
import type {
  AddNoteRequest,
  AuditClaimRequest,
  AuditManuscriptRequest,
  ClaimList,
  ClaimScope,
  ClaimStatus,
  ClaimSummary,
  ClaimSupport,
  CreateClaimRequest,
  ListClaimsRequest,
  ManuscriptAnchor,
  ManuscriptAnchors,
  ManuscriptAuditReport,
  ManuscriptProjectRequest,
  MutationResponse,
  NewClaim,
  RevalidateManuscriptRequest,
  RevalidationView,
  SourceRef,
  TraceManuscriptRequest,
  TraceView,
} from "./types";

/**
 * `manuscript.audit`: the manuscript against the accepted research graph.
 *
 * With `file` (and optionally `line_start`/`line_end`) the audit covers only those lines and
 * re-parses only the artifacts they depend on, which is what makes `Research: Audit
 * Selection` cheap enough to run on a selection. Narrowing changes what is asked about,
 * never what counts as a finding.
 */
export async function auditManuscript(
  client: HarnessClient,
  request: AuditManuscriptRequest = {},
): Promise<ManuscriptAuditReport> {
  return client.invoke<ManuscriptAuditReport, AuditManuscriptRequest>(
    CAPABILITIES.manuscriptAudit,
    { main_tex: request.main_tex ?? "main.tex", ...request },
  );
}

/** `manuscript.anchors`: every stored anchor with its verdict against the file on disk. */
export async function manuscriptAnchors(
  client: HarnessClient,
  request: ManuscriptProjectRequest = {},
): Promise<ManuscriptAnchors> {
  return client.invoke<ManuscriptAnchors, ManuscriptProjectRequest>(
    CAPABILITIES.manuscriptAnchors,
    { main_tex: request.main_tex ?? "main.tex", ...request },
  );
}

/**
 * `manuscript.revalidate`: re-find every stored anchor and record what the manuscript says.
 *
 * A mutation, and human-only. The editor no longer reproduces ADR-008's moved-versus-reworded
 * rule and no longer has to offer a terminal command: the harness records the verdicts.
 */
export async function revalidateAnchors(
  client: HarnessClient,
  request: RevalidateManuscriptRequest = {},
): Promise<RevalidationView> {
  return client.invoke<RevalidationView, RevalidateManuscriptRequest>(
    CAPABILITIES.manuscriptRevalidate,
    { main_tex: request.main_tex ?? "main.tex", dry_run: false, ...request },
  );
}

/** `manuscript.trace`: one sentence, by file and line, down to its Claim and source spans. */
export async function traceSentence(
  client: HarnessClient,
  request: TraceManuscriptRequest,
): Promise<TraceView> {
  return client.invoke<TraceView, TraceManuscriptRequest>(CAPABILITIES.manuscriptTrace, {
    main_tex: request.main_tex ?? "main.tex",
    ...request,
  });
}

/** `manuscript.attach_claim`: bind one manuscript sentence to an existing Claim. */
export async function attachClaim(
  client: HarnessClient,
  anchor: ManuscriptAnchor,
): Promise<MutationResponse> {
  return client.invoke<MutationResponse, { anchor: ManuscriptAnchor }>(
    CAPABILITIES.manuscriptAttachClaim,
    { anchor },
  );
}

/** `claim.list`: every Claim a filter selects, as the Attach Claim picker lists them. */
export async function listClaims(
  client: HarnessClient,
  request: ListClaimsRequest = {},
): Promise<ClaimSummary[]> {
  const list = await client.invoke<ClaimList, ListClaimsRequest>(CAPABILITIES.claimList, request);
  return list.claims ?? [];
}

/** `claim.find_support`: what a Claim rests on, grouped by relation. */
export async function findSupport(client: HarnessClient, claimId: string): Promise<ClaimSupport> {
  return client.invoke<ClaimSupport, { claim_id: string }>(CAPABILITIES.claimFindSupport, {
    claim_id: claimId,
  });
}

/**
 * `claim.create`: register a structured Claim at its requested strength.
 *
 * The request carries no `id`: the daemon allocates the next free `ClaimId` under the
 * workspace lock and returns it in `objects[0]`, which is the id to show the researcher.
 */
export async function createClaim(
  client: HarnessClient,
  claim: NewClaim,
): Promise<MutationResponse> {
  return client.invoke<MutationResponse, CreateClaimRequest>(CAPABILITIES.claimCreate, { claim });
}

/** `claim.audit`: record what the evidence allows the Claim to say. */
export async function auditClaim(
  client: HarnessClient,
  request: AuditClaimRequest,
): Promise<MutationResponse> {
  return client.invoke<MutationResponse, AuditClaimRequest>(CAPABILITIES.claimAudit, request);
}

/**
 * `note.add`: capture a low-authority research note (Product 31).
 *
 * `source` names the capture host; the handler records it as provenance rather than as note
 * text, so where a note was taken never becomes part of what it says.
 */
export async function addNote(
  client: HarnessClient,
  request: AddNoteRequest,
): Promise<MutationResponse> {
  return client.invoke<MutationResponse, AddNoteRequest>(CAPABILITIES.noteAdd, request);
}

/** `retrieval.resolve_source`: reopen a reference at its exact page, span, and geometry. */
export async function resolveSource(client: HarnessClient, ref: string): Promise<SourceRef> {
  return client.invoke<SourceRef, { ref: string }>(CAPABILITIES.resolveSource, { ref });
}

/** The scope ladder of Product 10.2, weakest first. */
export const CLAIM_SCOPES: readonly ClaimScope[] = [
  "individual",
  "observed_subset",
  "corpus_pattern",
  "field_generalization",
  "universal_or_absence",
];

/** Claim statuses, in the order a researcher meets them. */
export const CLAIM_STATUSES: readonly ClaimStatus[] = [
  "unverified",
  "supported",
  "qualified",
  "contested",
  "unsupported",
  "superseded",
];

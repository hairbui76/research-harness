/**
 * Hand-maintained TypeScript mirrors of the daemon's wire DTOs.
 *
 * These are declarations, not logic: every type here corresponds to a Pydantic model on the
 * Python side, and the field names are the JSON names that model serializes. The extension
 * is a transport client (ADR-004), so it must not add, rename, or reinterpret a field -
 * the capability layer owns what these objects mean.
 *
 * | this file                  | Python source                                              |
 * | -------------------------- | ---------------------------------------------------------- |
 * | `CapabilityCatalog`, ...   | `research_harness/protocol/dto.py`                          |
 * | `ManuscriptAnchor`, ...    | `research_harness/domain/manuscript.py`, `domain/base.py`   |
 * | `ManuscriptAuditReport`    | `research_harness/manuscript/audit.py`                      |
 * | `AnchorRevalidation`       | `research_harness/manuscript/anchors.py`                    |
 * | `Sentence`                 | `research_harness/manuscript/latex.py`                      |
 * | `ClaimSupport`, `SourceRef`| `research_harness/capabilities/extra_handlers.py`, `retrieval/structured.py` |
 * | request bodies             | `research_harness/capabilities/dto.py`, `extra_handlers.py` |
 *
 * `tests/contract/protocol/test_vscode_contract.py` calls the daemon with exactly the
 * requests below and asserts these field names appear in the responses, so a rename on
 * either side fails a test rather than a hover.
 */

// -- envelopes ---------------------------------------------------------------

/** `protocol/dto.py::ErrorBody`. `code` is the stable contract; `message` is not. */
export interface ErrorBody {
  code: string;
  message: string;
  capability?: string | null;
}

/** `protocol/dto.py::CapabilityResponse`. A refusal is `ok: false`, never a thrown error. */
export interface CapabilityResponse<T = unknown> {
  capability: string;
  ok: boolean;
  result?: T | null;
  error?: ErrorBody | null;
  run_id?: string | null;
}

/** `protocol/dto.py::CapabilityDescriptor`. */
export interface CapabilityDescriptor {
  name: string;
  summary: string;
  permission: string;
  scientific_semantics: string;
  request_schema: Record<string, unknown>;
  response_schema: Record<string, unknown>;
  human_only: boolean;
  long_running: boolean;
}

/** `protocol/dto.py::PlannedCapability`: a Product 22 name this build does not implement. */
export interface PlannedCapability {
  name: string;
  reason: string;
}

/** `protocol/dto.py::CapabilityCatalog`. */
export interface CapabilityCatalog {
  capabilities: CapabilityDescriptor[];
  planned: PlannedCapability[];
}

/** `protocol/dto.py::HealthReport`. */
export interface HealthReport {
  ok: boolean;
  workspace: string;
  project: string;
  review_policy: string;
  capabilities: number;
  version: string;
}

/** `protocol/dto.py::ObjectView`: one canonical object read through `GET /objects/{id}`. */
export interface ObjectView {
  id: string;
  kind: string;
  object: Record<string, unknown>;
}

// -- domain fragments --------------------------------------------------------

/** `domain/base.py::Provenance`. `actor` is opaque to the domain. */
export interface Provenance {
  source: "human" | "model" | "system" | "external_metadata";
  actor: string;
  workflow?: string | null;
  run_id?: string | null;
  template_version?: string | null;
  note?: string | null;
}

/** `domain/enums.py::ManuscriptAnchorStatus`. */
export type ManuscriptAnchorStatus = "valid" | "stale" | "missing";

/** `domain/enums.py::StaleState`. */
export type StaleState = "fresh" | "stale";

/** `domain/enums.py::FindingSeverity`. */
export type FindingSeverity = "info" | "warning" | "error";

/** `domain/enums.py::ManuscriptFindingKind` - the Product 30.3 list, in report order. */
export type ManuscriptFindingKind =
  | "unregistered_claim"
  | "over_strong_wording"
  | "citation_mismatch"
  | "unsupported_numeric"
  | "stale_claim"
  | "invalid_evidence_anchor";

/** `domain/enums.py::ClaimStatus`. */
export type ClaimStatus =
  | "unverified"
  | "supported"
  | "qualified"
  | "contested"
  | "unsupported"
  | "superseded";

/** `domain/enums.py::ClaimScope` - L0..L4, the strength ladder of Product 10.2. */
export type ClaimScope =
  | "individual"
  | "observed_subset"
  | "corpus_pattern"
  | "field_generalization"
  | "universal_or_absence";

/** `domain/enums.py::ClaimType`. */
export type ClaimType =
  | "descriptive"
  | "comparative"
  | "prevalence"
  | "absence"
  | "causal"
  | "taxonomic"
  | "methodological"
  | "synthesis"
  | "recommendation";

/** `domain/manuscript.py::ManuscriptAnchor` - the first link of the Product 30.1 chain. */
export interface ManuscriptAnchor {
  schema_version?: number;
  created_at?: string;
  updated_at?: string;
  provenance: Provenance;
  file: string;
  line_start: number;
  line_end: number;
  char_start?: number;
  char_end?: number;
  sentence: string;
  sentence_fingerprint: string;
  claim: string;
  citation_keys?: string[];
  status?: ManuscriptAnchorStatus;
  stale?: StaleState;
}

/** `manuscript/latex.py::Sentence`; offsets index the raw file text. */
export interface Sentence {
  file: string;
  line_start: number;
  line_end: number;
  char_start: number;
  char_end: number;
  text: string;
  normalized_text: string;
  fingerprint: string;
  citation_keys?: string[];
  section_path?: string[];
  in_environment?: string | null;
}

/**
 * `domain/manuscript.py::FindingLocation` - where a finding was raised, structurally.
 *
 * The auditor still prefixes the message with `"<file>:<line>: "`, but that prefix is prose
 * and this is not: a finding about an unattached sentence carries no anchor, and before this
 * field the prefix was the only record of where it happened (`report.ts::findingLocation`).
 */
export interface FindingLocation {
  file: string;
  line_start: number;
  line_end: number;
  char_start?: number;
  char_end?: number;
}

/** `domain/manuscript.py::ManuscriptAuditFinding`. */
export interface ManuscriptAuditFinding {
  kind: ManuscriptFindingKind;
  severity: FindingSeverity;
  /** Still prefixed `"<file>:<line_start>: "` by the auditor; `location` is authoritative. */
  message: string;
  anchor?: ManuscriptAnchor | null;
  related?: string[];
  /** Absent only for a finding no sentence produced. */
  location?: FindingLocation | null;
}

/** `manuscript/anchors.py::AnchorRevalidation`. */
export interface AnchorRevalidation {
  status: ManuscriptAnchorStatus;
  anchor: ManuscriptAnchor;
  relocated?: Sentence | null;
  similarity?: number | null;
  reason: string;
}

/** `parsing/anchors.py::ResolvedSpan`. */
export interface ResolvedSpan {
  block: string;
  page: number;
  bbox?: [number, number, number, number] | null;
  text: string;
}

/** `manuscript/audit.py::TraceLink` - sentence to Claim to Evidence to page span. */
export interface TraceLink {
  sentence: Sentence;
  anchor_key: string;
  claim: string;
  evidence?: string[];
  spans?: ResolvedSpan[];
}

/** `manuscript/audit.py::ManuscriptAuditReport`. */
export interface ManuscriptAuditReport {
  findings: ManuscriptAuditFinding[];
  sentences_checked: number;
  anchored_sentences: number;
  unanchored_substantive: number;
  revalidations: AnchorRevalidation[];
  trace: TraceLink[];
}

/** `capabilities/extra_handlers.py::EvidenceRelationView`. */
export interface EvidenceRelationView {
  evidence: string;
  relation: string;
  aspect?: string | null;
  note?: string | null;
  resolved?: boolean;
  work?: string | null;
  status?: string | null;
  exact_text?: string | null;
}

/** `capabilities/extra_handlers.py::ClaimSupport` - what a Claim actually rests on. */
export interface ClaimSupport {
  claim: string;
  statement: string;
  status: string;
  requested_strength: string;
  allowed_strength: string;
  supporting?: EvidenceRelationView[];
  qualifying?: EvidenceRelationView[];
  contradicting?: EvidenceRelationView[];
  other?: EvidenceRelationView[];
}

/** `retrieval/structured.py::SourceRef` - the exact location behind a reference. */
export interface SourceRef {
  ref: string;
  kind: "evidence" | "block";
  work: string;
  version: string;
  artifact: string;
  block: string;
  file_hash?: string | null;
  page?: number | null;
  section_path?: string[];
  char_start?: number | null;
  char_end?: number | null;
  bbox?: number[] | null;
  text: string;
}

/**
 * `capabilities/reads.py::ClaimSummary` - one Claim as a list view names it.
 *
 * Read from `claim.list`, a capability every transport shares, so the Claim picker no longer
 * depends on `GET /index` - a Web-cockpit route the capability contract does not promise.
 * `GET /index` composes these with the same function, so the objects are identical.
 */
export interface ClaimSummary {
  id: string;
  statement: string;
  type: string;
  status: string;
  requested_strength: string;
  allowed_strength: string;
  maximum_defensible_wording?: string | null;
  stale: string;
  supporting?: number;
  qualifying?: number;
  contradicting?: number;
}

/** `capabilities/reads.py::ClaimList` - what `claim.list` answers. */
export interface ClaimList {
  count: number;
  claims: ClaimSummary[];
}

/** `capabilities/reads.py::AnchorSummary` - one manuscript sentence bound to a Claim. */
export interface AnchorSummary {
  file: string;
  line_start: number;
  sentence: string;
  claim: string;
  citation_keys?: string[];
  status: ManuscriptAnchorStatus;
  stale: StaleState;
}

/** `capabilities/extra_handlers.py::AnchorVerdict` - one anchor against the file on disk. */
export interface AnchorVerdict {
  anchor: string;
  claim: string;
  file: string;
  line_start: number;
  line_end: number;
  status: ManuscriptAnchorStatus;
  similarity?: number | null;
  reason?: string | null;
  relocated_to?: [number, number] | null;
}

/** `capabilities/extra_handlers.py::ManuscriptAnchors` - the `manuscript.anchors` read. */
export interface ManuscriptAnchors {
  count: number;
  anchors: AnchorSummary[];
  verdicts: AnchorVerdict[];
}

/**
 * `capabilities/extra_handlers.py::RevalidationView` - what `manuscript.revalidate` recorded.
 *
 * `applied` names the anchors that were written back. A moved sentence keeps its anchor and
 * adopts its new lines; a reworded or deleted one is recorded `stale`/`missing` rather than
 * being reattached to text the researcher did not choose (ADR-008).
 */
export interface RevalidationView {
  dry_run: boolean;
  checked: number;
  valid: number;
  relocated: number;
  stale: number;
  missing: number;
  applied: string[];
  results: AnchorVerdict[];
  mutations: MutationResponse[];
}

/**
 * `capabilities/extra_handlers.py::TraceView` - one sentence down to its source spans.
 *
 * `link` is absent when the sentence carries no anchor. That is a different answer from a
 * broken chain, and the sentence is still reported so the editor can offer to attach one.
 */
export interface TraceView {
  file: string;
  line: number;
  sentence: string;
  anchor?: string | null;
  claim?: string | null;
  link?: TraceLink | null;
}

/** `capabilities/registry.py::ValidationBody`. */
export interface ValidationBody {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

/** `domain/research.py::ResearchEvent`, as far as the extension reads it. */
export interface ResearchEvent {
  event: string;
  actor: string;
  summary: string;
  subjects?: string[];
  occurred_at?: string;
}

/** `capabilities/registry.py::StaleBody`. */
export interface StaleBody {
  object_id: string;
  reason: string;
  priority: number;
  source_change: string;
}

/** `capabilities/registry.py::MutationResponse` - the Product 36 result of one mutation. */
export interface MutationResponse {
  capability: string;
  objects: string[];
  event: ResearchEvent;
  diff: Record<string, unknown>;
  stale: StaleBody[];
  validation: ValidationBody;
}

// -- request bodies ----------------------------------------------------------

/** `capabilities/extra_handlers.py::ManuscriptProjectRequest`: which LaTeX project to read. */
export interface ManuscriptProjectRequest {
  project_root?: string | null;
  main_tex?: string;
}

/**
 * `capabilities/extra_handlers.py::AuditManuscriptRequest` for `manuscript.audit`.
 *
 * A line range needs the file it is a range in; the daemon refuses one without it. Narrowing
 * changes what is *asked about*, never what counts as a finding, and it re-parses only the
 * artifacts the anchors in that range rest on.
 */
export interface AuditManuscriptRequest extends ManuscriptProjectRequest {
  file?: string;
  line_start?: number;
  line_end?: number;
}

/** `capabilities/extra_handlers.py::RevalidateManuscriptRequest` for `manuscript.revalidate`. */
export interface RevalidateManuscriptRequest extends ManuscriptProjectRequest {
  /** Report the verdicts and record none of them; nothing canonical is written. */
  dry_run?: boolean;
}

/** `capabilities/extra_handlers.py::TraceManuscriptRequest` for `manuscript.trace`. */
export interface TraceManuscriptRequest extends ManuscriptProjectRequest {
  file: string;
  line: number;
}

/** `capabilities/reads.py::ListClaimsRequest` for `claim.list`. */
export interface ListClaimsRequest {
  status?: ClaimStatus | null;
  stale?: StaleState | null;
  type?: ClaimType | null;
}

/** `capabilities/dto.py::AttachManuscriptAnchorRequest` for `manuscript.attach_claim`. */
export interface AttachManuscriptAnchorRequest {
  anchor: ManuscriptAnchor;
}

/** `capabilities/extra_handlers.py::FindSupportRequest` for `claim.find_support`. */
export interface FindSupportRequest {
  claim_id: string;
}

/** `capabilities/extra_handlers.py::ResolveSourceRequest` for `retrieval.resolve_source`. */
export interface ResolveSourceRequest {
  ref: string;
}

/**
 * `capabilities/dto.py::AddNoteRequest` for `note.add`.
 *
 * `source` names the capture host and is recorded as provenance (`Provenance.note`), never
 * as note text: the scientific record says what was captured, not which window it was typed
 * into (`handlers.add_note`).
 */
export interface AddNoteRequest {
  text: string;
  key?: string | null;
  source?: string | null;
}

/** `domain/claim.py::ClaimSemantics`. */
export interface ClaimSemantics {
  subject: string;
  predicate: string;
  object: string;
  qualifier?: Record<string, unknown>;
}

/** `domain/claim.py::ClaimScopeSpec`. */
export interface ClaimScopeSpec {
  level: ClaimScope;
  corpus?: string | null;
  publication_until?: string | null;
}

/** `domain/claim.py::ClaimAssessment`. */
export interface ClaimAssessment {
  requested_strength: ClaimScope;
  allowed_strength: ClaimScope;
  status?: ClaimStatus;
  maximum_defensible_wording?: string | null;
  audited_at?: string | null;
}

/**
 * `domain/claim.py::Claim`, restricted to what a new Claim needs.
 *
 * `id` is omitted: `claim.create` allocates the next free `ClaimId` under the workspace
 * lock and returns it as `objects[0]`, so no client has to guess one and no two clients can
 * race for the same number.
 */
export interface NewClaim {
  statement: string;
  type: ClaimType;
  semantics: ClaimSemantics;
  scope: ClaimScopeSpec;
  assessment: ClaimAssessment;
  provenance: Provenance;
}

/** `capabilities/dto.py::CreateClaimRequest` for `claim.create`. */
export interface CreateClaimRequest {
  claim: NewClaim;
}

/** `capabilities/dto.py::AuditClaimRequest` for `claim.audit`. */
export interface AuditClaimRequest {
  claim_id: string;
  status: ClaimStatus;
  allowed_strength: ClaimScope;
  maximum_defensible_wording?: string | null;
}

// -- capability names --------------------------------------------------------

/**
 * Every capability this extension calls. Names are a Product 22 commitment, so they live
 * in one place and are asserted by the Python contract test.
 */
export const CAPABILITIES = {
  manuscriptAudit: "manuscript.audit",
  manuscriptAnchors: "manuscript.anchors",
  manuscriptRevalidate: "manuscript.revalidate",
  manuscriptTrace: "manuscript.trace",
  manuscriptAttachClaim: "manuscript.attach_claim",
  claimCreate: "claim.create",
  claimList: "claim.list",
  claimAudit: "claim.audit",
  claimFindSupport: "claim.find_support",
  noteAdd: "note.add",
  resolveSource: "retrieval.resolve_source",
} as const;

export type CapabilityName = (typeof CAPABILITIES)[keyof typeof CAPABILITIES];

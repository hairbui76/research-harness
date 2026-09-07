/**
 * The daemon's DTOs, named. Every type here is the generated one — the cockpit has no
 * shape of its own for a research object, because a client that redefines the API's types
 * is a client that can disagree with it (ROADMAP Task 11.1).
 */
import type { components } from './types.gen';

type Schemas = components['schemas'];

export type ArtifactBlocks = Schemas['ArtifactBlocks'];
export type AttentionGroup = Schemas['AttentionGroup'];
export type AttentionItem = Schemas['AttentionItem'];
export type BlockView = Schemas['BlockView'];
export type CandidateView = Schemas['CandidateView'];
export type CapabilityCatalog = Schemas['CapabilityCatalog'];
export type CapabilityDescriptor = Schemas['CapabilityDescriptor'];
export type CapabilityResponse = Schemas['CapabilityResponse'];
export type ConflictPosition = Schemas['ConflictPosition'];
export type ConflictView = Schemas['ConflictView'];
export type CountEntry = Schemas['CountEntry'];
export type ErrorBody = Schemas['ErrorBody'];
export type HealthReport = Schemas['HealthReport'];
export type ObjectView = Schemas['ObjectView'];
export type OverviewCounts = Schemas['OverviewCounts'];
export type OverviewReport = Schemas['OverviewReport'];
export type WorkspaceIndex = Schemas['WorkspaceIndex'];
export type WorkSummary = Schemas['WorkSummary'];
export type ClaimSummary = Schemas['ClaimSummary'];
export type QuestionSummary = Schemas['QuestionSummary'];
export type DecisionSummary = Schemas['DecisionSummary'];
export type MatrixSummary = Schemas['MatrixSummary'];
export type TaxonomySummary = Schemas['TaxonomySummary'];
export type AnchorSummary = Schemas['AnchorSummary'];
export type ArtifactSummary = Schemas['ArtifactSummary'];
export type RunStatus = Schemas['RunStatus'];

/** A JSON value, for the payloads the daemon types as free-form objects. */
export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

/**
 * One Review Inbox item. `review.inbox` types its items as free-form objects on the wire
 * (the queue is built in `evidence/review.py`, not in a Pydantic response model), so this
 * is the one place the cockpit spells a shape out. Everything in it is rendered, never
 * recomputed: `category`, `priority`, and `reasons` are the server's judgement.
 */
export interface ReviewItem {
  candidate_id: string;
  work: string;
  artifact: string;
  field: string;
  category: 'conflict' | 'high_risk' | 'stale' | 'ambiguous' | 'routine';
  priority: number;
  reasons: string[];
  tier: number;
  origin: string;
  evidence_type: string;
  verdict: string | null;
  anchor_status: string;
  exact_text: string;
  numeric: JsonObject | null;
  negative_state: string | null;
  review_action: string | null;
  competing: string[];
  previously_rejected: boolean;
  accepted_conflict: string | null;
  provider_conflict: JsonObject | null;
  conflicts: ConflictView[];
  proposed_changes: JsonObject[];
  source_context: SourceContext;
}

/** The exact source beside the decision (Product 25). */
export interface SourceContext {
  page: number | null;
  section_path: string[];
  block_text: string;
  exact_text: string;
  bbox: [number, number, number, number] | null;
  neighbors: string[];
}

export interface ReviewInbox {
  count: number;
  counts: Record<string, number>;
  items: ReviewItem[];
}

/** `state.stale`: what is out of date, highest scientific impact first. */
export interface StaleReport {
  count: number;
  marks: { object_id: string; reason: string; priority: number; source_change: string }[];
}

/**
 * `state.rebuild`: what the rebuild read, wrote and refused.
 *
 * Written out here rather than taken from `types.gen.ts` for the same reason `StaleReport`
 * above is: `state.rebuild` has no route of its own, so its response model never reaches
 * the daemon's OpenAPI document and the generator never sees it.
 */
export interface StateRebuildReport {
  ok: boolean;
  objects: number;
  objects_by_type: Record<string, number>;
  stale_marks: number;
  fts_rows: number;
  canonical_digest: string;
  duration_ms: number;
  invalid_files: { path: string; error: string }[];
  summary: string;
}

/** `claim.find_support`: every claim-evidence edge, grouped by what it does. */
export interface ClaimSupport {
  claim: string;
  statement: string;
  status: string;
  requested_strength: string;
  allowed_strength: string;
  supporting: EvidenceRelationView[];
  qualifying: EvidenceRelationView[];
  contradicting: EvidenceRelationView[];
  other: EvidenceRelationView[];
}

export interface EvidenceRelationView {
  evidence: string;
  relation: string;
  aspect: string | null;
  note: string | null;
  resolved: boolean;
  work: string | null;
  status: string | null;
  exact_text: string | null;
}

/** `synthesis.compare`: one field across the corpus. */
export interface ComparisonView {
  matrix: string;
  field: string;
  taxonomy: string | null;
  label_counts: Record<string, number>;
  unclassified: string[];
  rows: JsonObject[];
}

/** `work.get`: one Work with its revisions and files. */
export interface WorkView {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  screening: string;
  identifiers: JsonObject;
  versions: { id: string; kind: string; label: string | null }[];
  artifacts: {
    id: string;
    version: string;
    kind: string;
    file_hash: string;
    size_bytes: number;
    original_filename: string | null;
  }[];
  blocks: number;
  evidence: number;
}

/**
 * `domain/manuscript.py::FindingLocation` — where a finding was raised, structurally.
 *
 * The auditor also writes `"<file>:<line>: "` into the message, but a client that had to
 * parse prose to place a finding would be recomputing something the daemon already knows.
 */
export interface FindingLocation {
  file: string;
  line_start: number;
  line_end: number;
  char_start?: number;
  char_end?: number;
}

/**
 * `domain/manuscript.py::ManuscriptAnchor` — one sentence bound to the Claim it asserts.
 *
 * A `TrackedObject`, so it carries no stable id of its own; `file:line_start` is the key
 * the anchor store and `AnchorImpact.anchor_key` both use, and the one this client shows.
 */
export interface ManuscriptAnchorRecord {
  file: string;
  line_start: number;
  line_end: number;
  char_start?: number;
  char_end?: number;
  sentence: string;
  sentence_fingerprint: string;
  claim: string;
  citation_keys?: string[];
  status: string;
  stale: string;
}

/** `domain/manuscript.py::ManuscriptAuditFinding`. */
export interface ManuscriptAuditFinding {
  kind: string;
  severity: string;
  message: string;
  anchor?: ManuscriptAnchorRecord | null;
  related?: string[];
  location?: FindingLocation | null;
}

/** `manuscript.audit`: findings, coverage, and the trace behind each anchored sentence. */
export interface ManuscriptAuditReport {
  findings: ManuscriptAuditFinding[];
  sentences_checked: number;
  anchored_sentences: number;
  unanchored_substantive: number;
  revalidations: JsonObject[];
  trace: JsonObject[];
}

/** `extra_handlers.py::AnchorVerdict` — one stored anchor against the file on disk. */
export interface AnchorVerdict {
  anchor: string;
  claim: string;
  file: string;
  line_start: number;
  line_end: number;
  status: string;
  similarity?: number | null;
  reason?: string | null;
  relocated_to?: [number, number] | null;
}

/** `manuscript.anchors`: every stored anchor with the verdict it currently earns. */
export interface ManuscriptAnchors {
  count: number;
  anchors: AnchorSummary[];
  verdicts: AnchorVerdict[];
}

/** `manuscript.revalidate`: what re-finding every anchor produced, and what it recorded. */
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

/** `manuscript.trace`: one sentence, by file and line, down to its source spans. */
export interface TraceView {
  file: string;
  line: number;
  sentence: string;
  anchor?: string | null;
  claim?: string | null;
  link?: JsonObject | null;
}

/** `review.*`: what one candidate-keyed review action did (`extra_handlers.py`). */
export interface ReviewOutcome {
  candidate_id: string;
  action: string;
  /** The staged candidate's status afterwards, as `review.inbox` will read it. */
  status: string;
  /** The `EvidenceId` the acceptance wrote, when the action created one. */
  evidence: string | null;
  mutation: MutationResponse | null;
}

/**
 * `review.accept_batch`: what the policy batch accepted, and why it left the rest alone.
 *
 * Which candidates meet the Product 24.4 conditions is the daemon's judgement, checked per
 * candidate at the moment of the call; `skipped` carries its own sentence for each one it
 * refused, and the cockpit renders both lists rather than counting or explaining anything
 * itself. A `dry_run` answers the same shape with no mutation behind it.
 */
export interface BatchAcceptResponse {
  dry_run: boolean;
  accepted: string[];
  skipped: Record<string, string>;
  mutations: MutationResponse[];
}

/**
 * The one-list reads of `capabilities/reads.py`.
 *
 * `state.index` answers all of them at once and is what the navigation uses; a view that
 * needs a single list asks for that list, because the capability surface is the one every
 * host shares. The summaries inside are the generated ones — the same objects `GET /index`
 * returns, composed by the same functions.
 */
/**
 * One line the Claims page groups by: the concern the daemon named, in its words.
 *
 * `label` already carries the count inside the sentence ("2 claims ask for more than their
 * evidence allows"), and `claims` is the daemon's own order. A client that re-derived
 * either would be deciding what needs work, which is the daemon's judgement (principle
 * P10).
 */
export interface ClaimGroup {
  kind: string;
  label: string;
  count: number;
  claims: string[];
}

export interface ClaimList {
  count: number;
  claims: ClaimSummary[];
  groups: ClaimGroup[];
  summary: string;
}

export interface WorkList {
  count: number;
  works: WorkSummary[];
}

/**
 * One line the Questions page groups by, and whether that group is still work.
 *
 * `surface` is `waiting` or `settled`: an open question and a blocked one are both work,
 * an answered one is the record of work already done. `questions` is oldest first, so the
 * longest unanswered is read first.
 */
export interface QuestionGroup {
  kind: string;
  label: string;
  count: number;
  surface: string;
  questions: string[];
}

export interface QuestionList {
  count: number;
  questions: QuestionSummary[];
  groups: QuestionGroup[];
  summary: string;
}

export interface DecisionList {
  count: number;
  decisions: DecisionSummary[];
}

export interface AnchorList {
  count: number;
  anchors: AnchorSummary[];
}

/**
 * `reads.py::EvidenceSummary` — one accepted Evidence object as a list shows it.
 *
 * Hand-declared because no HTTP route returns it, so it is not in the OpenAPI snapshot;
 * `tests/contract/protocol/test_web_routes.py` asserts these names against the daemon.
 */
export interface EvidenceSummary {
  id: string;
  work: string;
  artifact: string;
  field: string | null;
  status: string;
  origin: string;
  evidence_type: string;
  strength: string;
  review_tier: number;
  verdict: string | null;
  exact_text: string;
  qualification: string | null;
  stale: string;
}

export interface EvidenceList {
  count: number;
  evidence: EvidenceSummary[];
}

/** `claim.list`'s filters; every one of them is optional. */
export interface ClaimFilters {
  status?: string;
  stale?: string;
  type?: string;
}

/** `review.resolve_conflict`: the mutation the researcher's answer produced, if any. */
export interface ConflictResolution {
  candidate_id: string;
  choice: string;
  mutation: MutationResponse | null;
}

/** What one accepted-state mutation did (Product 36). */
export interface MutationResponse {
  capability: string;
  objects: string[];
  event: JsonObject;
  diff: JsonObject;
  stale: { object_id: string; reason: string; priority: number; source_change: string }[];
  validation: { ok: boolean; errors: string[]; warnings: string[] };
}

// ---------------------------------------------------------------------------------------
// manuscript workspace (P21)
//
// Hand-declared, mirroring the Python model named above each block. None of these reaches
// the cockpit through an HTTP route, so none of them is in the OpenAPI snapshot, and
// `tests/contract/protocol/test_web_routes.py` is what checks these field names against the
// schemas the daemon publishes. Read `src/research_harness/manuscript/` before changing one.
// ---------------------------------------------------------------------------------------

/**
 * The eight Phase 21 capability names.
 *
 * `capabilities.gen.ts` is regenerated from the daemon snapshot after the backend wave, so
 * `CapabilityName` does not carry them yet. `HarnessClient` narrows its manuscript calls to
 * this union and casts in exactly one place, which is what keeps a typo a compile error
 * here too.
 */
export type ManuscriptWorkspaceCapability =
  | 'manuscript.files'
  | 'manuscript.read_file'
  | 'manuscript.write_file'
  | 'manuscript.compile'
  | 'manuscript.build'
  | 'manuscript.synctex'
  | 'manuscript.suggest'
  | 'manuscript.apply_suggestion';

/** `manuscript/files.py::ManuscriptFileKind`. There is no `dir`: the tree arrives flat. */
export type ManuscriptFileKind = 'tex' | 'bib' | 'image' | 'other';

/** `manuscript/files.py::ManuscriptFile` — one row of the tree. */
export interface ManuscriptFile {
  path: string;
  kind: ManuscriptFileKind;
  size_bytes: number;
  modified_at: string;
}

/** `manuscript/workspace.py::ManuscriptTree` — every file, and where a compile starts. */
export interface ManuscriptTree {
  root: string;
  entry_file: string;
  files: ManuscriptFile[];
}

/** `manuscript/files.py::FileSnapshot` — the text, and the hash a later save must present. */
export interface FileSnapshot {
  path: string;
  kind: ManuscriptFileKind;
  content: string;
  content_hash: string;
  size_bytes: number;
  modified_at: string;
}

/** `manuscript/compile.py::CompileStatus`. A failure is a result, not a harness error. */
export type CompileStatus = 'succeeded' | 'failed' | 'timed_out';

/** `manuscript/compile.py::CompileDiagnostic` — one message from the engine. */
export interface CompileDiagnostic {
  severity: 'error' | 'warning' | 'info';
  message: string;
  file?: string | null;
  line?: number | null;
  code?: string | null;
}

/** `manuscript/compile.py::LastGoodBuild` — the newest build that really produced a PDF. */
export interface LastGoodBuild {
  build_id: string;
  engine: string;
  pdf: string;
  compiled_at: string;
  inputs_fingerprint: string;
  stale: boolean;
}

/** `manuscript/compile.py::CompileResult` — everything one build produced. */
export interface CompileResult {
  build_id: string;
  status: CompileStatus;
  engine: string;
  executable: string;
  args: string[];
  entry_file: string;
  inputs_fingerprint: string;
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  timeout_seconds: number;
  exit_status?: number | null;
  timed_out: boolean;
  build_dir: string;
  pdf?: string | null;
  log?: string | null;
  synctex?: string | null;
  diagnostics: CompileDiagnostic[];
  stdout_tail: string;
  stderr_tail: string;
  last_good?: LastGoodBuild | null;
}

/** `manuscript/toolchain.py::DiscoveredEngine` — an engine on `PATH`, and its binary. */
export interface DiscoveredEngine {
  engine: string;
  executable: string;
}

/** `manuscript/toolchain.py::ManuscriptSettings` — the `manuscript:` block of research.yaml. */
export interface ManuscriptSettings {
  engine?: string | null;
  entry_file: string;
  timeout_seconds: number;
  extra_args: string[];
  synctex: boolean;
}

/** `manuscript/toolchain.py::ToolchainReport` — what is installed, and what to do about it. */
export interface ToolchainReport {
  settings: ManuscriptSettings;
  installed: DiscoveredEngine[];
  configured?: string | null;
  selected?: DiscoveredEngine | null;
  guidance: string[];
}

/** `manuscript/synctex.py::SynctexUnavailableReason`. */
export type SynctexUnavailableReason =
  | 'not_requested'
  | 'missing_file'
  | 'unreadable'
  | 'unsupported_format'
  | 'no_records';

/**
 * `manuscript/synctex.py::PdfLocation` — a rectangle on one page, in PDF points measured
 * from the page's **top left**.
 *
 * `PdfPage` draws and reports in PDF *user* space, whose origin is the bottom left, so the
 * preview flips these about the page height it reads back from pdf.js rather than assuming
 * a paper size.
 */
export interface PdfLocation {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** `manuscript/synctex.py::SourceLocation`. */
export interface SourceLocation {
  file: string;
  line: number;
  column?: number | null;
}

/** `manuscript/workspace.py::SynctexView` — a lookup, or why there is no mapping. */
export interface SynctexView {
  build_id?: string | null;
  available: boolean;
  reason?: SynctexUnavailableReason | null;
  detail?: string | null;
  pdf_locations: PdfLocation[];
  source_location?: SourceLocation | null;
}

/**
 * `manuscript/workspace.py::BuildView` — one build as the workspace shows it.
 *
 * `diagnostics` and `audit_findings` are two lists that are never merged and never summed:
 * a document may compile while failing its audit, and pass its audit while failing to
 * compile (LaTeX spec §7). `error_count` counts compiler errors and `audit_error_count`
 * counts scientific ones.
 */
export interface BuildView {
  build_id?: string | null;
  status?: CompileStatus | null;
  result?: CompileResult | null;
  diagnostics: CompileDiagnostic[];
  error_count: number;
  warning_count: number;
  audit_findings: ManuscriptAuditFinding[];
  audit_error_count: number;
  audit_ran: boolean;
  audit_unavailable_reason?: string | null;
  pdf_available: boolean;
  pdf?: string | null;
  pdf_stale: boolean;
  last_good?: LastGoodBuild | null;
  synctex_available: boolean;
  synctex_reason?: SynctexUnavailableReason | null;
  synctex_detail?: string | null;
  toolchain: ToolchainReport;
  guidance: string[];
}

/** `manuscript/protected.py::ProtectedSpanKind`. */
export type ProtectedSpanKind =
  | 'citation'
  | 'reference'
  | 'math'
  | 'number_with_unit'
  | 'quotation'
  | 'identifier'
  | 'code'
  | 'url';

/** `manuscript/protected.py::ProtectedSpan` — an immutable region of the passage. */
export interface ProtectedSpan {
  kind: ProtectedSpanKind;
  char_start: number;
  char_end: number;
  text: string;
}

/** `manuscript/style.py::ProtectedViolation` — a protected span the rewrite moved. */
export interface ProtectedViolation {
  kind: ProtectedSpanKind;
  before?: string | null;
  after?: string | null;
}

/** `manuscript/style.py::Proposition` — one sentence reduced to what may not change. */
export interface Proposition {
  text: string;
  scope_level?: string | null;
  numbers: string[];
  citations: string[];
  qualifiers: string[];
  negations: string[];
}

/** `manuscript/style.py::PropositionChange` — an aligned pair whose meaning moved. */
export interface PropositionChange {
  before: Proposition;
  after: Proposition;
  direction: string;
  reasons: string[];
}

/** `manuscript/style.py::SemanticDiff` — what a rewrite did to the meaning of a passage. */
export interface SemanticDiff {
  added: Proposition[];
  removed: Proposition[];
  strengthened: PropositionChange[];
  weakened: PropositionChange[];
  protected_violations: ProtectedViolation[];
  unchanged: number;
}

/** `manuscript/style.py::TextSpan`. */
export interface StyleTextSpan {
  char_start: number;
  char_end: number;
  text: string;
}

/** `manuscript/style.py::StyleFinding` — one place a prose rule fired. */
export interface StyleFinding {
  rule_id: string;
  span: StyleTextSpan;
  message: string;
  suggestion: string;
  severity: 'error' | 'warning';
}

/** `manuscript/style.py::StyleReport`. */
export interface StyleReport {
  policy: string;
  findings: StyleFinding[];
}

/** `manuscript/suggest.py::DiffLine`. */
export interface SuggestionDiffLine {
  kind: 'context' | 'added' | 'removed';
  text: string;
  old_line?: number | null;
  new_line?: number | null;
}

/** `manuscript/suggest.py::DiffHunk`. Its `@@` header is a Python property, so it is built here. */
export interface SuggestionDiffHunk {
  old_start: number;
  old_count: number;
  new_start: number;
  new_count: number;
  lines: SuggestionDiffLine[];
}

/** `manuscript/suggest.py::AnchorImpact` — what a rewrite does to an anchored Claim. */
export interface AnchorImpact {
  anchor_key: string;
  claim: string;
  file: string;
  line_start: number;
  line_end: number;
  status: string;
  similarity?: number | null;
  reason: string;
}

/** `manuscript/suggest.py::SuggestionProvenance` — the model, and the conversation. */
export interface SuggestionProvenance {
  provenance: JsonObject;
  session_id?: string | null;
  message_id?: string | null;
  context_pack_id?: string | null;
}

/**
 * `manuscript/suggest.py::SuggestionCandidate` — a staged edit and everything judging it.
 *
 * `changed`, `protected_preserved` and `applicable` are Python *properties*: they are in the
 * candidate's staged JSON file and in `--json` output, but not in the capability's response
 * model. So the cockpit reads `audit_status`, `blocked_reason` and `protected_violations`
 * and never re-derives the verdict itself.
 */
export interface SuggestionCandidate {
  candidate_id: string;
  created_at: string;
  file: string;
  line_start: number;
  line_end: number;
  instruction?: string | null;
  style?: string | null;
  policy: string;
  source_hash: string;
  original_text: string;
  proposed_text: string;
  proposed_content: string;
  hunks: SuggestionDiffHunk[];
  protected_spans: ProtectedSpan[];
  protected_violations: ProtectedViolation[];
  semantic_diff: SemanticDiff;
  style_report: StyleReport;
  audit_findings: ManuscriptAuditFinding[];
  anchor_impacts: AnchorImpact[];
  audit_status: 'pending' | 'passed' | 'failed';
  blocked_reason?: string | null;
  provenance: SuggestionProvenance;
  applied: boolean;
  applied_at?: string | null;
  path?: string | null;
}

/** `manuscript/suggest.py::AppliedSuggestion` — what applying a candidate wrote. */
export interface AppliedSuggestion {
  candidate: SuggestionCandidate;
  snapshot: FileSnapshot;
  event: JsonObject;
  anchors_to_revalidate: string[];
}

/** `manuscript.suggest`'s request, as the suggest dialog assembles it. */
export interface SuggestionRequest {
  file: string;
  line_start: number;
  line_end: number;
  provider: string;
  instruction?: string;
  style?: string;
  session_id?: string;
  message_id?: string;
  context_pack_id?: string;
}

// ---------------------------------------------------------------------------
// conversation workspace (P18)
// ---------------------------------------------------------------------------
//
// Hand-declared, like the manuscript section above: no HTTP route returns a `session.*`
// or `context.*` response, so none of these shapes is in `web/openapi.json`. They mirror
// `capabilities/conversation.py` and the domain models it embeds
// (`domain/conversation.py`) field for field — the capability response models embed the
// domain objects rather than restating them, so what arrives on the wire is the record on
// disk.

/** `domain/conversation.py::Visibility`. `private` never leaves the machine. */
export type SessionVisibility = 'private' | 'project';

/** `domain/conversation.py::MessageRole`. */
export type MessageRoleName = 'user' | 'assistant' | 'system' | 'tool';

/** `domain/conversation.py::AuthorityLabel`. Identical to the Design System's vocabulary. */
export type AuthorityLabelName =
  | 'accepted'
  | 'candidate'
  | 'qualified'
  | 'contested'
  | 'stale'
  | 'private';

/** `domain/conversation.py::AttemptStatus`. */
export type AttemptStatusName = 'complete' | 'interrupted' | 'failed';

/** `domain/conversation.py::ContextClass`, in packing order. */
export type ContextClassName =
  | 'policy'
  | 'accepted_state'
  | 'current_session'
  | 'prior_sessions'
  | 'attachments'
  | 'corpus_blocks'
  | 'discovery';

/** `domain/conversation.py::OmissionReason`. */
export type OmissionReasonName =
  | 'token_budget'
  | 'privacy_policy'
  | 'egress_blocked'
  | 'unsupported_media'
  | 'stale'
  | 'low_relevance'
  | 'unresolved_reference'
  | 'conflicts_with_accepted';

/** `domain/conversation.py::EgressClass`. `none` is an unsent `context.preview`. */
export type PackEgressClass = 'none' | 'local' | 'external';

/** `domain/conversation.py::PromotionTarget`. Evidence is deliberately absent. */
export type PromotionTargetName = 'note' | 'question' | 'claim_candidate' | 'decision_candidate';

/** `domain/conversation.py::AttachmentState`. */
export type SessionAttachmentState =
  | 'selected'
  | 'validating'
  | 'ready'
  | 'sending'
  | 'session_only'
  | 'promoting'
  | 'in_corpus'
  | 'failed';

/** `domain/conversation.py::ModelIdentity` — opaque adapter and model labels. */
export interface ModelIdentity {
  provider: string;
  model: string;
  request_fingerprint?: string | null;
}

/** `domain/conversation.py::SessionDefaults`. */
export interface SessionDefaults {
  model?: ModelIdentity | null;
  mode?: string | null;
  token_budget?: number | null;
  /** The runtime's own effort name for a runtime binding; absent otherwise. */
  reasoning?: string | null;
}

/**
 * `session.configure`: exactly one of `runtime`, `entry`, `clear`.
 *
 * `model` is required with `runtime`, and `reasoning` is allowed only with `runtime`. The
 * daemon enforces all three and refuses in its own sentence; nothing here re-decides them.
 * `research.yaml` is never touched — the binding lives on the session record.
 */
export interface ConfigureSessionRequest {
  session: string;
  runtime?: string;
  model?: string;
  reasoning?: string;
  entry?: string;
  clear?: boolean;
}

/** `domain/conversation.py::ConversationSession` — the durable session record. */
export interface ConversationSession {
  schema_version: number;
  id: string;
  created_at: string;
  updated_at: string;
  provenance: JsonObject;
  title: string;
  visibility: SessionVisibility;
  defaults: SessionDefaults;
  message_count: number;
  last_message?: string | null;
  last_message_at?: string | null;
  summarized_through?: string | null;
  summary_updated_at?: string | null;
  reserved_messages?: string[];
}

/** `domain/conversation.py::TextBlock`. Mathematics stays inside the text, unnormalised. */
export interface TextBlock {
  kind: 'text';
  text: string;
}

/** `domain/conversation.py::ReferenceBlock` — a resolved `@` token, not the typed string. */
export interface ReferenceBlock {
  kind: 'reference';
  target: string;
  label?: string | null;
  locator?: string | null;
  authority?: AuthorityLabelName | null;
}

/** `domain/conversation.py::AttachmentBlock`. */
export interface AttachmentBlock {
  kind: 'attachment';
  attachment: string;
  caption?: string | null;
}

export type ContentBlock = TextBlock | ReferenceBlock | AttachmentBlock;

/** `domain/conversation.py::MessageAttempt` — a retry keeps the attempt it retried. */
export interface MessageAttempt {
  number: number;
  status: AttemptStatusName;
  retry_of?: string | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

/** `domain/conversation.py::Message`. Named for the DTO so the DS `Message` keeps its name. */
export interface ConversationMessage {
  schema_version: number;
  id: string;
  created_at: string;
  updated_at: string;
  provenance: JsonObject;
  session: string;
  role: MessageRoleName;
  blocks: ContentBlock[];
  authority: AuthorityLabelName;
  visibility: SessionVisibility;
  attachments?: string[];
  context_pack?: string | null;
  model?: ModelIdentity | null;
  attempt: MessageAttempt;
}

/** `domain/conversation.py::SessionAttachment` — working material, never corpus state. */
export interface SessionAttachmentRecord {
  schema_version: number;
  id: string;
  created_at: string;
  updated_at: string;
  provenance: JsonObject;
  session: string;
  state: SessionAttachmentState;
  filename: string;
  media_type: string;
  size_bytes: number;
  content_hash?: string | null;
  page_count?: number | null;
  description?: string | null;
  visibility: SessionVisibility;
  failure_reason?: string | null;
  work?: string | null;
  version?: string | null;
  artifact?: string | null;
}

/** `session.create` / `session.rename`. */
export interface SessionView {
  session: ConversationSession;
}

/** `session.list`. */
export interface SessionListView {
  count: number;
  sessions: ConversationSession[];
}

/** `session.get`: one page of a transcript, plus what is needed to resume the session. */
export interface SessionTranscript {
  session: ConversationSession;
  messages: ConversationMessage[];
  attachments: SessionAttachmentRecord[];
  context_packs: string[];
  total: number;
  offset: number;
  next_offset?: number | null;
  summary?: string | null;
}

/** One `session.search` hit. */
export interface SessionMatch {
  session: string;
  title: string;
  title_matched: boolean;
  messages: string[];
  snippet?: string | null;
  updated_at: string;
}

export interface SessionSearchResults {
  count: number;
  matches: SessionMatch[];
}

/** `session.summarize`: the derived summary and how far it covers the transcript. */
export interface SessionSummaryView {
  session: string;
  summary: string;
  summarized_through?: string | null;
}

/** `domain/conversation.py::ContextItem` — one piece of material that reached the model. */
export interface ContextItemView {
  context_class: ContextClassName;
  source: string;
  id?: string | null;
  authority: AuthorityLabelName;
  label?: string | null;
  tokens: number;
}

/** `domain/conversation.py::OmittedContextItem` — and why it did not. */
export interface OmittedContextItemView extends ContextItemView {
  reason: OmissionReasonName;
  detail?: string | null;
}

/**
 * `domain/conversation.py::ContextReceipt`.
 *
 * `discrepancies` and `unresolved` are recorded on the receipt as well as returned at the
 * top of `ContextPackView`, so a pack read back a week later still explains itself without
 * being reassembled.
 */
export interface ContextReceipt {
  included: ContextItemView[];
  omitted: OmittedContextItemView[];
  discrepancies?: DiscrepancyView[];
  unresolved?: string[];
}

/** `domain/conversation.py::ClassBudget`. */
export interface ClassBudget {
  context_class: ContextClassName;
  tokens: number;
}

/** `domain/conversation.py::ContextPack` — assembled whether or not the call was made. */
export interface ContextPack {
  schema_version: number;
  id: string;
  created_at: string;
  updated_at: string;
  provenance: JsonObject;
  session: string;
  receipt: ContextReceipt;
  message?: string | null;
  model?: ModelIdentity | null;
  egress: PackEgressClass;
  token_budget?: number | null;
  budgets?: ClassBudget[];
}

/** `capabilities/conversation.py::OmissionView` — the receipt's "why not" line. */
export interface OmissionView {
  source: string;
  context_class: ContextClassName;
  reason: OmissionReasonName;
  tokens: number;
  label?: string | null;
  detail?: string | null;
}

/** `capabilities/conversation.py::DiscrepancyView` — chat disagreed, accepted state won. */
export interface DiscrepancyView {
  accepted: string;
  message: string;
  detail: string;
}

/** `context.preview` and `context.get`: one `Context used` receipt. */
export interface ContextPackView {
  pack: ContextPack;
  tokens: number;
  tokens_by_class: Record<string, number>;
  omissions: OmissionView[];
  discrepancies: DiscrepancyView[];
  unresolved: string[];
}

/** `session.send` / `session.retry`: durable ids, before a byte is streamed. */
export interface SendStarted {
  run_id: string;
  session: string;
  assistant_message: string;
  context_pack: string;
  attempt: number;
  user_message?: string | null;
  unresolved: string[];
  events: string;
}

/** `session.stop`: the state a cancelled run reached. */
export interface SessionStopped {
  run_id: string;
  state: string;
}

/** `session.promote`: what a promotion produced, and what still has to review it. */
export interface PromotionView {
  target: PromotionTargetName;
  session: string;
  message: string;
  object_id?: string | null;
  note_key?: string | null;
  accepted: boolean;
  review: string;
  decision?: JsonObject | null;
}

/**
 * One entry of `provider.list`'s `ProviderCatalog` (v1.1 plan §0.4).
 *
 * Derived server-side from the router configuration and the egress report, so the client
 * offers a model selector without knowing a single provider rule: `egress_class` says
 * whether a request would leave the machine, and an unavailable model stays in the list
 * with the daemon's own reason attached.
 */
export interface ProviderModel {
  id: string;
  label: string;
  provider: string;
  egress_class: 'local' | 'external';
  input_media: string[];
  context_tokens: number;
  vision: boolean;
  available: boolean;
  unavailable_reason?: string | null;
  default?: boolean;
}

/** `provider.list`: every routable model in this project, best priority first. */
export interface ProviderCatalog {
  count?: number;
  models: ProviderModel[];
}

/** `session.send`'s request, exactly as the composer assembles it. */
export interface SendMessageRequest {
  session: string;
  text: string;
  references?: string[];
  attachments?: string[];
  model?: string | null;
  token_budget?: number | null;
}

/** `session.promote`'s request. `target` also accepts `evidence`, so the refusal explains. */
export interface PromoteMessageRequest {
  session: string;
  message: string;
  target: PromotionTargetName | 'evidence';
  excerpt?: string;
  rationale?: string | null;
  question?: string | null;
  claim?: string | null;
  subject?: string | null;
  predicate?: string | null;
  object?: string | null;
  claim_type?: string;
  scope?: string;
  corpus?: string | null;
  decision_type?: string;
  title?: string | null;
}

/** `context.preview`'s request; `persist: false` is the draft preview. */
export interface ContextPreviewRequest {
  session: string;
  text?: string;
  references?: string[];
  model?: string | null;
  token_budget?: number | null;
  persist?: boolean;
}

/**
 * The two P18 reads that are not yet in `capabilities.gen.ts`.
 *
 * `context.get` and `provider.list` are being added by the backend parity task; the
 * generated capability-name union predates them. Narrowing to this alias keeps a typo a
 * compile error and puts the cast in one place, exactly as
 * `ManuscriptWorkspaceCapability` did for P21.
 */
export type ConversationReadCapability = 'context.get' | 'provider.list';

// ---------------------------------------------------------------------------
// attachments (P19)
// ---------------------------------------------------------------------------
//
// Hand-declared, like the two sections above: `attachment.*` answers through
// `POST /capabilities/<name>`, so none of these shapes is in `web/openapi.json`. They
// mirror `capabilities/attachments.py` field for field — the response models there are
// flat projections rather than embedded domain objects, which is why `AttachmentView` is
// not `SessionAttachmentRecord`: it carries no `schema_version` and no `provenance`.
//
// The one non-capability write in the whole product is the byte route these types serve
// (`POST /sessions/{id}/attachments`, v1.1 plan §0.4). It writes session-only bytes and
// creates no Work, Version, Artifact or Evidence; `attachment.save_to_corpus` is the only
// thing that gives an attachment a corpus identity, and it is an explicit, separate act.

/** `conversation/attachments.py::SendDisposition` — what happens to one file on a send. */
export type AttachmentDisposition = 'sent' | 'converted' | 'omitted';

/** `conversation/promotion_corpus.py::IdentityChoice`. `undecided` needs the researcher. */
export type AttachmentIdentityChoice =
  | 'existing_artifact'
  | 'existing_version'
  | 'existing_work'
  | 'new_work'
  | 'undecided';

/** `domain/enums.py::IdentityResolutionOutcome`. */
export type IdentityResolutionOutcomeName =
  | 'same_artifact'
  | 'same_version'
  | 'same_work'
  | 'distinct_work'
  | 'unresolved';

/** `ingest/service.py::CreatedKind`. `nothing` is the idempotent re-save. */
export type AttachmentCreatedKind = 'nothing' | 'artifact' | 'version' | 'work';

/**
 * `capabilities/attachments.py::AttachmentView` — one session attachment, flat.
 *
 * Returned by the byte route and by every `attachment.*` capability that touches one file.
 * `SessionAttachmentRecord` (the domain object the transcript embeds) is a superset of it,
 * so a transcript record is usable anywhere this type is expected.
 */
export interface AttachmentView {
  id: string;
  session: string;
  state: SessionAttachmentState;
  filename: string;
  media_type: string;
  size_bytes: number;
  content_hash?: string | null;
  page_count?: number | null;
  description?: string | null;
  visibility: SessionVisibility;
  failure_reason?: string | null;
  work?: string | null;
  version?: string | null;
  artifact?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** `attachment.remove`: what was deleted. Session-only bytes; the corpus is untouched. */
export interface AttachmentRemoved {
  session: string;
  attachment: string;
  removed: boolean;
}

/**
 * One attachment's verdict for one model.
 *
 * `ok` answers "does this item let the send proceed", which is not "does it travel": a
 * `failed` attachment is omitted and still `ok` because it was never ready, while a
 * *ready* attachment the model cannot take is omitted and **not** ok — dropping that one
 * silently is the failure the attachments design §5 forbids.
 */
export interface AttachmentSendItem {
  attachment: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  state: SessionAttachmentState;
  disposition: AttachmentDisposition;
  ok: boolean;
  reason?: string | null;
  omission?: OmissionReasonName | null;
  suggested_model?: string | null;
  page_count?: number | null;
}

/** `attachment.check_send`: the per-item verdict, and whether the send may proceed. */
export interface AttachmentSendCheck {
  session: string;
  /** The configured entry the check is about — its name in `research.yaml`. */
  provider: string;
  /** The model that entry serves. */
  model: string;
  ok: boolean;
  /** One line naming every blocked item, in the daemon's own words. */
  refusal?: string | null;
  items: AttachmentSendItem[];
}

/** `attachment.resolve_identity`: the corpus identity a save would use. A read. */
export interface AttachmentIdentityView {
  attachment: string;
  choice: AttachmentIdentityChoice;
  outcome: IdentityResolutionOutcomeName;
  content_hash: string;
  /** True when saving needs an explicit `as_new` or `attach_to` from the researcher. */
  requires_confirmation: boolean;
  /** True when these exact bytes are already an Artifact of this corpus. */
  duplicate: boolean;
  parsable: boolean;
  reasons: string[];
  work?: string | null;
  version?: string | null;
  artifact?: string | null;
  title?: string | null;
  doi?: string | null;
  arxiv?: string | null;
  year?: number | null;
}

/**
 * `attachment.save_to_corpus`: what the promotion linked, and what it created.
 *
 * `evidence_created` is always false and is stated rather than assumed: corpus identity is
 * not evidence, and the receipt says so where a researcher reads it (attachments design
 * §7). `linked_existing` is true when the same bytes were already registered.
 */
export interface AttachmentPromotionView {
  attachment: AttachmentView;
  work: string;
  version: string;
  artifact: string;
  created: AttachmentCreatedKind;
  outcome: IdentityResolutionOutcomeName;
  parsed: boolean;
  linked_existing: boolean;
  evidence_created: boolean;
  reasons: string[];
  mutation?: MutationResponse | null;
}

/** `attachment.check_send`'s request. Empty `attachments` means the whole session. */
export interface CheckAttachmentSendRequest {
  session: string;
  /** The configured entry: its name, its `<entry>/<model>` label, or the served model. */
  provider?: string | null;
  model?: string | null;
  attachments?: string[];
}

/** `attachment.save_to_corpus`'s request; `as_new`/`attach_to` are the confirmation. */
export interface SaveAttachmentToCorpusRequest {
  session: string;
  attachment: string;
  as_new?: boolean;
  attach_to?: string | null;
  parse?: boolean;
}

// ---------------------------------------------------------------------------
// research graph (P20)
// ---------------------------------------------------------------------------
//
// Hand-declared like the two sections above: the six `graph.*` reads answer over
// `POST /capabilities/graph.*` and no HTTP route returns their shapes, so none of them is
// in `web/openapi.json`. They mirror `capabilities/graph.py` field for field, and the
// vocabularies mirror `domain/graph.py`.
//
// Two fields appear on *every* node and edge on purpose, and this client never derives
// either of them: `authority` says what scientific standing the projected row has, and
// `visibility` says whether it may leave the machine. A candidate edge is a proposal until
// a review says otherwise (ADR-003), and a walk the daemon pruned for privacy comes back
// pruned — the cockpit renders what it is given and infers nothing (graph spec §8).

/** `domain/graph.py::NodeKind` — every namespace the projection may hold. */
export type GraphNodeKind =
  | 'project'
  | 'session'
  | 'message'
  | 'attachment'
  | 'work'
  | 'version'
  | 'artifact'
  | 'section'
  | 'paragraph'
  | 'table'
  | 'figure'
  | 'equation'
  | 'reference'
  | 'evidence'
  | 'claim'
  | 'question'
  | 'decision'
  | 'synthesis'
  | 'manuscript_file'
  | 'manuscript_anchor'
  | 'citation';

/** `domain/graph.py::EdgeKind` — deterministic relations first, then scientific ones. */
export type GraphEdgeKind =
  | 'contains'
  | 'version_of'
  | 'artifact_of'
  | 'cites'
  | 'attached_to'
  | 'anchored_at'
  | 'mentioned_in'
  | 'supports'
  | 'contradicts'
  | 'qualifies'
  | 'derived_from'
  | 'depends_on';

/** `domain/graph.py::SCIENTIFIC_EDGE_KINDS`: the relations that assert something. */
export const SCIENTIFIC_EDGE_KINDS: readonly GraphEdgeKind[] = [
  'supports',
  'contradicts',
  'qualifies',
  'derived_from',
  'depends_on',
];

/** `domain/graph.py::EdgeOrigin`. `model_proposed` can never carry accepted authority. */
export type GraphEdgeOrigin = 'structural' | 'accepted' | 'model_proposed' | 'researcher';

/** `domain/graph.py::GraphAuthority`. The same six words as `AuthorityLabelName`. */
export type GraphAuthorityName = AuthorityLabelName;

/** `domain/graph.py::GraphVisibility`. The same two words as `SessionVisibility`. */
export type GraphVisibilityName = SessionVisibility;

/** `graph/queries.py::Direction` — which way a traversal followed an edge. */
export type GraphDirection = 'out' | 'in' | 'both';

/** `domain/graph.py::GraphMetadata` — scalar only, so a row is a diff-free echo. */
export type GraphMetadata = Record<string, string | number | boolean | null>;

/** `capabilities/graph.py::GraphNodeView` — one projected node and its labels. */
export interface GraphNodeView {
  id: string;
  kind: GraphNodeKind;
  authority: GraphAuthorityName;
  visibility: GraphVisibilityName;
  label: string;
  text: string;
  source?: string | null;
  fingerprint?: string | null;
  metadata: GraphMetadata;
}

/** `capabilities/graph.py::GraphEdgeView` — origin and authority keep a proposal a proposal. */
export interface GraphEdgeView {
  from_id: string;
  to_id: string;
  kind: GraphEdgeKind;
  origin: GraphEdgeOrigin;
  authority: GraphAuthorityName;
  status: string;
  source?: string | null;
  metadata: GraphMetadata;
}

/** `capabilities/graph.py::NeighbourView` — a node, the edge that reached it, and how far. */
export interface GraphNeighbourView {
  node: GraphNodeView;
  edge: GraphEdgeView;
  direction: GraphDirection;
  hops: number;
}

/** `graph.neighbors`: one node and what the graph says is around it. */
export interface GraphNeighbourhoodView {
  origin?: GraphNodeView | null;
  neighbours: GraphNeighbourView[];
}

/**
 * `graph.resolve`: what a reference resolves to, and every reason it may not be followed.
 *
 * `exists`, `authority` and `fresh` are decided against the canonical (or, for a session,
 * durable) record, never against the projected row — so a stale index degrades navigation
 * and can never mislabel authority. `node` is the row, offered so a label can be shown
 * without a second call, and `problems` is the daemon's own sentence for a refusal.
 */
export interface GraphResolvedView {
  reference: string;
  project: string;
  exists: boolean;
  authority: GraphAuthorityName;
  visibility: GraphVisibilityName;
  fresh: boolean;
  link?: string | null;
  node?: GraphNodeView | null;
  problems: string[];
}

/** `graph.autocomplete`: completion candidates, identity matches first. */
export interface GraphAutocompleteResult {
  prefix: string;
  matches: GraphNodeView[];
}

/** `graph.query`: nodes matching a structured filter, ordered by identity. */
export interface GraphQueryResult {
  nodes: GraphNodeView[];
}

/** `capabilities/graph.py::ProvenanceStepView` — one hop of a provenance path. */
export interface GraphProvenanceStepView {
  edge: GraphEdgeView;
  node: GraphNodeView;
  direction: GraphDirection;
}

/** `graph.provenance`: Claim → Evidence → the exact Artifact anchor, or why there is none. */
export interface GraphProvenanceView {
  found: boolean;
  origin?: GraphNodeView | null;
  target?: GraphNodeView | null;
  steps: GraphProvenanceStepView[];
  identities: string[];
  /** The exact source location the last hop recorded: page, block, char span. */
  anchor: GraphMetadata;
}

/** `graph.status`: what the projection says about itself. */
export interface GraphStatusView {
  /** True when a database exists and was built by the schema version this build reads. */
  available: boolean;
  exists: boolean;
  database: string;
  schema_version?: number | null;
  built_at?: string | null;
  canonical_digest?: string | null;
  event_cursor?: string | null;
  nodes: number;
  edges: number;
  sources: number;
  /** A rebuild is writing its replacement database beside this one right now. */
  rebuilding: boolean;
}

/** `graph.autocomplete`'s request. `visibility` restricts the egress class completed over. */
export interface GraphAutocompleteRequest {
  prefix: string;
  kinds?: GraphNodeKind[];
  visibility?: GraphVisibilityName[];
  limit?: number;
}

/** `graph.neighbors`' request. An excluded node is never traversed *through*. */
export interface GraphNeighborsRequest {
  id: string;
  hops?: number;
  direction?: GraphDirection;
  edge_kinds?: GraphEdgeKind[];
  origins?: GraphEdgeOrigin[];
  kinds?: GraphNodeKind[];
  authority?: GraphAuthorityName[];
  visibility?: GraphVisibilityName[];
  limit?: number;
}

/** `graph.query`'s request: the structured filter of `graph/queries.py::GraphFilter`. */
export interface GraphQueryRequest {
  kinds?: GraphNodeKind[];
  authorities?: GraphAuthorityName[];
  visibility?: GraphVisibilityName[];
  edge_kinds?: GraphEdgeKind[];
  origins?: GraphEdgeOrigin[];
  linked_to?: string | null;
  direction?: GraphDirection;
  text?: string | null;
  identities?: string[];
  limit?: number;
}

/** `graph.provenance`'s request; `to_kind` defaults to `artifact` on the daemon. */
export interface GraphProvenanceRequest {
  id: string;
  to_kind?: GraphNodeKind;
  visibility?: GraphVisibilityName[];
}

// ---------------------------------------------------------------------------
// subscription-backed CLI providers (provider.cli.*)
// ---------------------------------------------------------------------------
//
// Hand-declared like the sections above: `provider.cli.*` answers through
// `POST /capabilities/<name>`. They mirror `capabilities/cli_providers.py` and
// `providers/cli/types.py` field for field; the contract test pins every field name to
// the schema the daemon publishes.

export type CliAuthStatus = 'ok' | 'missing' | 'unknown';
export type CliBoundedMode = 'safe' | 'unsupported' | 'unknown';
export type CliCompatibility = 'verified' | 'warning' | 'blocked' | 'unknown';
export type CliEgressKind = 'external' | 'unknown_external';

export interface CliModelView {
  id: string;
  label: string;
  reasoning?: string[];
  context_tokens?: number | null;
}

/** One runtime as `provider.cli.scan` found it. Never carries a secret. */
export interface CliRuntimeStatus {
  runtime: string;
  name: string;
  available: boolean;
  executable: string | null;
  version: string | null;
  auth_status: CliAuthStatus;
  auth_guidance: string;
  bounded_mode: CliBoundedMode;
  compatibility: CliCompatibility;
  models: CliModelView[];
  model_source: 'live' | 'fallback';
  reasoning_choices: string[];
  egress_kind: CliEgressKind;
  egress_host: string;
  diagnostics: string[];
  scanned_at: string;
  /**
   * The daemon's own verdict, serialized: `types.py::CliRuntimeStatus` publishes both as
   * computed fields, so the cockpit renders the gates rather than re-deriving them.
   * `routable` is installed and logged in and provably bounded and not a blocked version;
   * `unavailable_reason` names the first failing gate, and is `null` when routable.
   */
  routable: boolean;
  unavailable_reason: string | null;
}

export interface ConfiguredCliProviderView {
  name: string;
  runtime: string;
  model: string;
  priority: number;
  enabled: boolean;
  reasoning?: string | null;
  timeout_seconds?: number | null;
  roles?: string[] | null;
  available: boolean;
  unavailable_reason?: string | null;
}

export interface CliScanReport {
  scanned_at: string;
  count: number;
  runtimes: CliRuntimeStatus[];
  configured: ConfiguredCliProviderView[];
  notice: string;
}

/** `provider.cli.configure`'s request, exactly as the settings screen posts it. */
export interface CliProviderConfigureRequest {
  name: string;
  runtime: string;
  model?: string;
  priority?: number;
  reasoning?: string | null;
  timeout_seconds?: number | null;
  roles?: string[] | null;
  enabled?: boolean;
}

export interface CliProviderConfigured {
  entry: ConfiguredCliProviderView;
  created: boolean;
  file: string;
}

export interface CliProviderRemoved {
  name: string;
  file: string;
}

export interface CliProviderTestReport {
  name: string;
  runtime: string;
  model: string;
  version: string | null;
  egress_host: string;
  egress_kind: CliEgressKind;
  ok: boolean;
  latency_ms?: number | null;
  message: string;
  diagnostic?: string | null;
}

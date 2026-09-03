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

/** `domain/manuscript.py::ManuscriptAuditFinding`. */
export interface ManuscriptAuditFinding {
  kind: string;
  severity: string;
  message: string;
  anchor?: JsonObject | null;
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
 * The one-list reads of `capabilities/reads.py`.
 *
 * `state.index` answers all of them at once and is what the navigation uses; a view that
 * needs a single list asks for that list, because the capability surface is the one every
 * host shares. The summaries inside are the generated ones — the same objects `GET /index`
 * returns, composed by the same functions.
 */
export interface ClaimList {
  count: number;
  claims: ClaimSummary[];
}

export interface WorkList {
  count: number;
  works: WorkSummary[];
}

export interface QuestionList {
  count: number;
  questions: QuestionSummary[];
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

/**
 * The cockpit's client for the local daemon: the TypeScript twin of
 * `research_harness.protocol.http.HarnessHttpClient`.
 *
 * It knows the routes and the envelopes and nothing else. Every mutation goes through
 * `POST /capabilities/<name>`, because that is the only supported write surface (ADR-004);
 * there is deliberately no method here that patches an object or writes a file.
 *
 * A caller with no token is an `agent_host` to the daemon: reads succeed, and accepting
 * evidence comes back as `ok: false` with `code: "permission_denied"`. That refusal is the
 * contract, not a bug — the UI renders it and disables the control (Product 29).
 */
import type { CapabilityName } from './capabilities.gen';
import type {
  AnchorList,
  AnchorSummary,
  ArtifactBlocks,
  CandidateView,
  CapabilityCatalog,
  CapabilityResponse,
  ClaimFilters,
  ClaimList,
  ClaimSummary,
  ClaimSupport,
  ComparisonView,
  ConflictResolution,
  DecisionList,
  DecisionSummary,
  EvidenceList,
  EvidenceSummary,
  HealthReport,
  Json,
  ManuscriptAnchors,
  ManuscriptAuditReport,
  MutationResponse,
  ObjectView,
  OverviewReport,
  QuestionList,
  QuestionSummary,
  ReviewInbox,
  ReviewOutcome,
  RevalidationView,
  RunStatus,
  StaleReport,
  TraceView,
  WorkList,
  WorkSummary,
  WorkspaceIndex,
  WorkView,
} from './dto';

/** Loopback only. The daemon is a single-user local workstation service (Product 4). */
export const DEV_BASE_URL = 'http://127.0.0.1:8765';

export interface ClientOptions {
  baseUrl?: string;
  token?: string | null;
  fetchImpl?: typeof fetch;
}

/** A refusal that came back with an HTTP status rather than a capability envelope. */
export class HarnessRequestError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = 'HarnessRequestError';
  }
}

/**
 * A capability that answered `ok: false`. Thrown by the typed helpers so a view can render
 * one error path; `invoke` returns the envelope untouched for callers that want both.
 */
export class CapabilityError extends Error {
  constructor(
    readonly capability: string,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'CapabilityError';
  }
}

/** Base URL: the daemon serves the built bundle itself, so same origin is the default. */
export function defaultBaseUrl(): string {
  const configured = import.meta.env?.VITE_API_BASE;
  if (typeof configured === 'string' && configured) return configured.replace(/\/$/, '');
  return import.meta.env?.DEV ? DEV_BASE_URL : '';
}

export class HarnessClient {
  private readonly baseUrl: string;
  private readonly token: string | null;
  private readonly http: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? defaultBaseUrl()).replace(/\/$/, '');
    this.token = options.token ?? null;
    this.http = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  /** True when this client holds the local token and may therefore ask to mutate. */
  get authenticated(): boolean {
    return Boolean(this.token);
  }

  /** A copy of this client carrying a different token; used when the researcher pastes one. */
  withToken(token: string | null): HarnessClient {
    return new HarnessClient({ baseUrl: this.baseUrl, token, fetchImpl: this.http });
  }

  // -- reads -----------------------------------------------------------------

  health(): Promise<HealthReport> {
    return this.get<HealthReport>('/health');
  }

  capabilities(): Promise<CapabilityCatalog> {
    return this.get<CapabilityCatalog>('/capabilities');
  }

  overview(): Promise<OverviewReport> {
    return this.get<OverviewReport>('/overview');
  }

  object(objectId: string): Promise<ObjectView> {
    return this.get<ObjectView>(`/objects/${encodeURIComponent(objectId)}`);
  }

  candidate(candidateId: string): Promise<CandidateView> {
    return this.get<CandidateView>(`/candidates/${encodeURIComponent(candidateId)}`);
  }

  blocks(artifactId: string): Promise<ArtifactBlocks> {
    return this.get<ArtifactBlocks>(`/blocks/${encodeURIComponent(artifactId)}`);
  }

  run(runId: string): Promise<RunStatus> {
    return this.get<RunStatus>(`/runs/${encodeURIComponent(runId)}`);
  }

  /** Where the source pane reads the immutable bytes from; the token rides as a query. */
  artifactBytesUrl(artifactId: string): string {
    const path = `${this.baseUrl}/artifacts/${encodeURIComponent(artifactId)}/bytes`;
    return this.token ? `${path}?token=${encodeURIComponent(this.token)}` : path;
  }

  /** The artifact bytes themselves, for a reader that cannot send an Authorization header. */
  async artifactBytes(artifactId: string): Promise<ArrayBuffer> {
    const path = `/artifacts/${encodeURIComponent(artifactId)}/bytes`;
    const response = await this.http(`${this.baseUrl}${path}`, { headers: this.headers() });
    if (!response.ok) {
      throw new HarnessRequestError(response.status, path, `${response.status} on ${path}`);
    }
    return response.arrayBuffer();
  }

  // -- calls -----------------------------------------------------------------

  /** Invoke one capability. A refusal comes back as `ok: false`, not as a thrown error. */
  async invoke(name: CapabilityName, request: Json = {}): Promise<CapabilityResponse> {
    const path = `/capabilities/${name}`;
    const response = await this.http(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(request ?? {}),
    });
    return (await response.json()) as CapabilityResponse;
  }

  /** Invoke one capability and insist that it worked, for the callers that only have one path. */
  async call<T>(name: CapabilityName, request: Json = {}): Promise<T> {
    const body = await this.invoke(name, request);
    if (!body.ok || !body.result) {
      const error = body.error;
      throw new CapabilityError(name, error?.code ?? 'internal_error', error?.message ?? name);
    }
    return body.result as T;
  }

  // -- the capabilities the cockpit calls by name ----------------------------

  reviewInbox(work?: string | null): Promise<ReviewInbox> {
    return this.call<ReviewInbox>('review.inbox', work ? { work } : {});
  }

  stale(limit = 200): Promise<StaleReport> {
    return this.call<StaleReport>('state.stale', { limit });
  }

  /** Everything the navigation lists, summarised, in one read (`GET /index`'s twin). */
  index(): Promise<WorkspaceIndex> {
    return this.call<WorkspaceIndex>('state.index', {});
  }

  /** The claims a filter selects. One list, so the Claims view does not read the rest. */
  async claims(filters: ClaimFilters = {}): Promise<ClaimSummary[]> {
    const request: Record<string, Json> = {};
    if (filters.status) request.status = filters.status;
    if (filters.stale) request.stale = filters.stale;
    if (filters.type) request.type = filters.type;
    return (await this.call<ClaimList>('claim.list', request)).claims;
  }

  /** The corpus, optionally narrowed to one screening state. */
  async works(screening?: string | null): Promise<WorkSummary[]> {
    const request: Record<string, Json> = screening ? { screening } : {};
    return (await this.call<WorkList>('work.list', request)).works;
  }

  /** The research questions, optionally narrowed to one status. */
  async questions(status?: string | null): Promise<QuestionSummary[]> {
    const request: Record<string, Json> = status ? { status } : {};
    return (await this.call<QuestionList>('question.list', request)).questions;
  }

  /** The recorded researcher decisions, optionally for one Claim. */
  async decisions(claim?: string | null): Promise<DecisionSummary[]> {
    const request: Record<string, Json> = claim ? { claim } : {};
    return (await this.call<DecisionList>('decision.list', request)).decisions;
  }

  /** Every manuscript sentence bound to a Claim, optionally narrowed to one file. */
  async anchors(file?: string | null): Promise<AnchorSummary[]> {
    const request: Record<string, Json> = file ? { file } : {};
    return (await this.call<AnchorList>('anchor.list', request)).anchors;
  }

  /** Accepted evidence, by work and lifecycle status; staged proposals are not listed. */
  async evidence(work?: string | null, status?: string | null): Promise<EvidenceSummary[]> {
    const request: Record<string, Json> = {};
    if (work) request.work = work;
    if (status) request.status = status;
    return (await this.call<EvidenceList>('evidence.list', request)).evidence;
  }

  // -- the six review actions of Product 24.3 --------------------------------
  //
  // Each takes the staging id and nothing else the researcher did not type. The handler
  // allocates the `EvidenceId`, marks the candidate reviewed so it leaves the queue, and
  // reports both back; the cockpit never posts an Evidence object it was just handed.

  /** Accept one staged candidate as it stands. */
  acceptCandidate(candidateId: string): Promise<ReviewOutcome> {
    return this.call<ReviewOutcome>('review.accept', { candidate_id: candidateId });
  }

  /** Accept one candidate with the condition it holds under (Product 24.3). */
  qualifyCandidate(candidateId: string, qualification: string): Promise<ReviewOutcome> {
    return this.call<ReviewOutcome>('review.qualify', {
      candidate_id: candidateId,
      qualification,
    });
  }

  /** Accept the researcher's corrected Evidence. The source anchor may never move. */
  editCandidate(candidateId: string, edited: Json): Promise<ReviewOutcome> {
    return this.call<ReviewOutcome>('review.edit', { candidate_id: candidateId, edited });
  }

  /** Refuse one candidate; the reason is recorded beside the corpus. */
  rejectCandidate(candidateId: string, reason: string): Promise<ReviewOutcome> {
    return this.call<ReviewOutcome>('review.reject', { candidate_id: candidateId, reason });
  }

  /** Put one candidate aside. It stays in the queue, with the note attached. */
  deferCandidate(candidateId: string, note: string): Promise<ReviewOutcome> {
    return this.call<ReviewOutcome>('review.defer', { candidate_id: candidateId, note });
  }

  /** Ask for more evidence: staging forgets, and the note the handler writes does not. */
  requestMoreEvidence(candidateId: string, note: string): Promise<ReviewOutcome> {
    return this.call<ReviewOutcome>('review.request_more', { candidate_id: candidateId, note });
  }

  /**
   * Resolve a *conflict record* the researcher's way.
   *
   * The six actions above are the review screen's path. This one stays because closing a
   * conflict is a different act: it takes the same three choices and additionally resolves
   * the conflict with the reason given.
   */
  resolveCandidate(
    candidateId: string,
    choice: 'accept' | 'reject' | 'defer',
    reason: string,
  ): Promise<ConflictResolution> {
    return this.call<ConflictResolution>('review.resolve_conflict', {
      candidate_id: candidateId,
      choice,
      reason,
    });
  }

  /**
   * Register a Claim, letting the daemon name it.
   *
   * `claim.id` is omitted on purpose: the handler allocates the next free `ClaimId` under
   * the workspace lock, so no client has to guess one and then race another. The id it
   * chose comes back as `objects[0]`.
   */
  async createClaim(claim: Json): Promise<{ id: string; mutation: MutationResponse }> {
    const mutation = await this.call<MutationResponse>('claim.create', { claim });
    return { id: mutation.objects[0] ?? '', mutation };
  }

  /** Register a research question; the daemon allocates the `RQ####` the same way. */
  async createQuestion(question: Json): Promise<{ id: string; mutation: MutationResponse }> {
    const mutation = await this.call<MutationResponse>('question.create', { question });
    return { id: mutation.objects[0] ?? '', mutation };
  }

  claimSupport(claimId: string): Promise<ClaimSupport> {
    return this.call<ClaimSupport>('claim.find_support', { claim_id: claimId });
  }

  relateEvidence(claimId: string, evidence: string, relation: string): Promise<MutationResponse> {
    return this.call<MutationResponse>('claim.relate', {
      claim_id: claimId,
      relation: { evidence, relation },
    });
  }

  auditClaim(claimId: string, audit: ClaimAudit): Promise<MutationResponse> {
    const request: Record<string, Json> = {
      claim_id: claimId,
      status: audit.status,
      allowed_strength: audit.allowedStrength,
    };
    if (audit.wording) request.maximum_defensible_wording = audit.wording;
    return this.call<MutationResponse>('claim.audit', request);
  }

  /**
   * Overrule the auditor's ceiling, visibly (Product 38).
   *
   * An override is a Decision before it is a claim edit, so this is two calls: accept the
   * `epistemic_override` Decision, then apply it. The Decision is posted without an id —
   * the daemon allocates the next free `DecisionId` under the lock and returns it, so the
   * cockpit no longer has to read `next_decision_id` and hope nothing else wrote first.
   */
  async overrideClaimStrength(claimId: string, override: ClaimOverride): Promise<MutationResponse> {
    const accepted = await this.call<MutationResponse>('decision.accept', {
      decision: {
        type: 'epistemic_override',
        status: 'proposed',
        title: `epistemic override on ${claimId}`,
        rationale: override.rationale,
        claim: claimId,
        auditor_recommendation: override.auditorRecommendation,
        researcher_selected: override.selected,
        provenance: { source: 'human', actor: override.actor || 'human' },
      },
    });
    const decisionId = accepted.objects[0];
    if (!decisionId) {
      throw new CapabilityError(
        'decision.accept',
        'internal_error',
        'the daemon accepted the override but named no Decision to apply',
      );
    }
    return this.call<MutationResponse>('claim.override_strength', {
      claim_id: claimId,
      decision_id: decisionId,
    });
  }

  work(workId: string): Promise<WorkView> {
    return this.call<WorkView>('work.get', { work: workId });
  }

  compareField(field: string, matrixId?: string | null): Promise<ComparisonView> {
    return this.call<ComparisonView>('synthesis.compare', {
      field,
      matrix_id: matrixId ?? null,
    });
  }

  auditManuscript(
    projectRoot?: string | null,
    mainTex = 'main.tex',
    scope: ManuscriptScope = {},
  ): Promise<ManuscriptAuditReport> {
    const request: Record<string, Json> = {
      project_root: projectRoot ?? null,
      main_tex: mainTex,
    };
    // A line range needs the file it is a range in; the daemon refuses one without it.
    if (scope.file) {
      request.file = scope.file;
      if (scope.lineStart !== undefined) request.line_start = scope.lineStart;
      if (scope.lineEnd !== undefined) request.line_end = scope.lineEnd;
    }
    return this.call<ManuscriptAuditReport>('manuscript.audit', request);
  }

  /** Every stored anchor with the verdict it earns against the manuscript on disk. */
  manuscriptAnchors(projectRoot?: string | null, mainTex = 'main.tex'): Promise<ManuscriptAnchors> {
    return this.call<ManuscriptAnchors>('manuscript.anchors', {
      project_root: projectRoot ?? null,
      main_tex: mainTex,
    });
  }

  /**
   * Re-find every stored anchor and record what the manuscript now says.
   *
   * A mutation, and human-only: a moved sentence adopts its new lines, and a reworded one
   * goes stale rather than being silently reattached (ADR-008). `dryRun` reports the same
   * verdicts and writes none of them.
   */
  revalidateManuscript(
    projectRoot?: string | null,
    mainTex = 'main.tex',
    dryRun = false,
  ): Promise<RevalidationView> {
    return this.call<RevalidationView>('manuscript.revalidate', {
      project_root: projectRoot ?? null,
      main_tex: mainTex,
      dry_run: dryRun,
    });
  }

  /** One sentence, by file and line, down to the Claim and source spans behind it. */
  traceManuscript(
    file: string,
    line: number,
    projectRoot?: string | null,
    mainTex = 'main.tex',
  ): Promise<TraceView> {
    return this.call<TraceView>('manuscript.trace', {
      project_root: projectRoot ?? null,
      main_tex: mainTex,
      file,
      line,
    });
  }

  // -- plumbing --------------------------------------------------------------

  private headers(): Record<string, string> {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
  }

  private async get<T>(path: string): Promise<T> {
    const response = await this.http(`${this.baseUrl}${path}`, { headers: this.headers() });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new HarnessRequestError(response.status, path, detail || `${response.status} on ${path}`);
    }
    return (await response.json()) as T;
  }
}

/** The part of the manuscript an audit is asked about; blank means the whole project. */
export interface ManuscriptScope {
  file?: string;
  lineStart?: number;
  lineEnd?: number;
}

export interface ClaimAudit {
  status: string;
  allowedStrength: string;
  wording?: string;
}

export interface ClaimOverride {
  selected: string;
  auditorRecommendation: string;
  rationale: string;
  /** Who the daemon says we are, from `GET /overview`; it records the Decision's actor. */
  actor?: string;
}

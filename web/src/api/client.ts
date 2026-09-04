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
  AppliedSuggestion,
  ArtifactBlocks,
  AttachmentIdentityView,
  AttachmentPromotionView,
  AttachmentRemoved,
  AttachmentSendCheck,
  AttachmentView,
  BuildView,
  CandidateView,
  CapabilityCatalog,
  CapabilityResponse,
  CheckAttachmentSendRequest,
  ClaimFilters,
  ClaimList,
  ClaimSummary,
  ClaimSupport,
  CliProviderConfigureRequest,
  CliProviderConfigured,
  CliProviderRemoved,
  CliProviderTestReport,
  CliScanReport,
  ComparisonView,
  ConfigureSessionRequest,
  ConflictResolution,
  ContextPackView,
  ContextPreviewRequest,
  ConversationReadCapability,
  ConversationSession,
  DecisionList,
  DecisionSummary,
  EvidenceList,
  EvidenceSummary,
  FileSnapshot,
  GraphAutocompleteRequest,
  GraphAutocompleteResult,
  GraphNeighborsRequest,
  GraphNeighbourhoodView,
  GraphProvenanceRequest,
  GraphProvenanceView,
  GraphQueryRequest,
  GraphQueryResult,
  GraphResolvedView,
  GraphStatusView,
  HealthReport,
  Json,
  ManuscriptAnchors,
  ManuscriptAuditReport,
  ManuscriptTree,
  ManuscriptWorkspaceCapability,
  MutationResponse,
  ObjectView,
  OverviewReport,
  PromoteMessageRequest,
  PromotionView,
  ProviderCatalog,
  QuestionList,
  QuestionSummary,
  ReviewInbox,
  ReviewOutcome,
  RevalidationView,
  RunStatus,
  SaveAttachmentToCorpusRequest,
  SendMessageRequest,
  SendStarted,
  SessionListView,
  SessionSearchResults,
  SessionStopped,
  SessionSummaryView,
  SessionTranscript,
  SessionView,
  StaleReport,
  StateRebuildReport,
  SuggestionCandidate,
  SuggestionRequest,
  SynctexView,
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
  /** Where this client's routes hang; a project-scoped client carries the project prefix. */
  readonly baseUrl: string;
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

  /**
   * A copy of this client rooted somewhere else, keeping the token and the transport.
   *
   * The multi-project host serves every workspace route below
   * `/api/projects/{project_id}`; re-basing one client is the whole of what the views need
   * to know about that, because the paths beneath the prefix did not change (design §6).
   */
  withBaseUrl(baseUrl: string): HarnessClient {
    return new HarnessClient({ baseUrl, token: this.token, fetchImpl: this.http });
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

  /**
   * Rebuild the deletable projection from the canonical files — `research rebuild`'s twin.
   *
   * `admin` and human-only, so an agent host is refused by the daemon and the callers do
   * not offer it; the projection and the research graph it carries are regenerable, and no
   * canonical file is written. It answers when the rebuild is done, not when it starts.
   */
  rebuildState(): Promise<StateRebuildReport> {
    return this.call<StateRebuildReport>('state.rebuild', {});
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

  // -- manuscript workspace (P21) --------------------------------------------
  //
  // The eight capabilities of the LaTeX workspace, plus the one byte route a PDF cannot be
  // assembled from JSON without. The permission split is the daemon's, not this client's:
  // files/read/build/synctex are reads, `suggest` stages, and write/compile/apply are
  // human-only mutations that come back as `permission_denied` for an agent host.

  /** Every source file of the manuscript, flat, with the entry file a compile would run. */
  manuscriptFiles(): Promise<ManuscriptTree> {
    return this.manuscriptCall<ManuscriptTree>('manuscript.files', {});
  }

  /** One file's text and the `content_hash` a later save has to present. */
  manuscriptReadFile(path: string): Promise<FileSnapshot> {
    return this.manuscriptCall<FileSnapshot>('manuscript.read_file', { path });
  }

  /**
   * Save one file, proving which version was edited.
   *
   * A hash that no longer matches the bytes on disk is refused rather than merged; the
   * refusal names both hashes in its message, and the cockpit answers it by re-reading the
   * file, never by parsing the prose (LaTeX spec §4).
   */
  manuscriptWriteFile(path: string, content: string, expectedHash: string): Promise<FileSnapshot> {
    return this.manuscriptCall<FileSnapshot>('manuscript.write_file', {
      path,
      content,
      expected_hash: expectedHash,
    });
  }

  /** Run the configured local engine once. Refuses outright when none is installed. */
  manuscriptCompile(entryFile?: string | null, timeoutSeconds?: number): Promise<BuildView> {
    const request: Record<string, Json> = {};
    if (entryFile) request.entry_file = entryFile;
    if (timeoutSeconds !== undefined) request.timeout_seconds = timeoutSeconds;
    return this.manuscriptCall<BuildView>('manuscript.compile', request);
  }

  /**
   * One build's compiler diagnostics beside the current scientific audit.
   *
   * A read, so it answers for an agent host too, and it answers for a workspace with no
   * engine at all — which is how the cockpit learns that the toolchain is missing without
   * starting a compile it knows will be refused.
   */
  manuscriptBuild(buildId?: string | null, audit = true, parseSources = false): Promise<BuildView> {
    const request: Record<string, Json> = { audit, parse_sources: parseSources };
    if (buildId) request.build_id = buildId;
    return this.manuscriptCall<BuildView>('manuscript.build', request);
  }

  /** Source to PDF: where `file`:`line` landed, or why that cannot be answered. */
  manuscriptSynctexForward(file: string, line: number, buildId?: string | null): Promise<SynctexView> {
    const request: Record<string, Json> = { file, line };
    if (buildId) request.build_id = buildId;
    return this.manuscriptCall<SynctexView>('manuscript.synctex', request);
  }

  /**
   * PDF to source: the line behind a point on a page.
   *
   * `x` and `y` are PDF points measured from the page's **top left**, which is the space
   * `PdfLocation` answers in; the caller converts from pdf.js's user space.
   */
  manuscriptSynctexInverse(
    page: number,
    x: number,
    y: number,
    buildId?: string | null,
  ): Promise<SynctexView> {
    const request: Record<string, Json> = { page, x, y };
    if (buildId) request.build_id = buildId;
    return this.manuscriptCall<SynctexView>('manuscript.synctex', request);
  }

  /** Stage a model rewrite of one span as a reviewable candidate. Writes no source file. */
  manuscriptSuggest(request: SuggestionRequest): Promise<SuggestionCandidate> {
    const body: Record<string, Json> = {
      file: request.file,
      line_start: request.line_start,
      line_end: request.line_end,
      provider: request.provider,
    };
    if (request.instruction) body.instruction = request.instruction;
    if (request.style) body.style = request.style;
    if (request.session_id) body.session_id = request.session_id;
    if (request.message_id) body.message_id = request.message_id;
    if (request.context_pack_id) body.context_pack_id = request.context_pack_id;
    return this.manuscriptCall<SuggestionCandidate>('manuscript.suggest', body);
  }

  /**
   * Write a reviewed candidate into the source.
   *
   * `expected_hash` defaults server-side to the hash the candidate was produced against, so
   * the cockpit passes the hash of the snapshot the reviewer actually has open: a candidate
   * reviewed against text somebody has since changed is refused, not merged.
   */
  manuscriptApplySuggestion(
    candidateId: string,
    expectedHash?: string | null,
  ): Promise<AppliedSuggestion> {
    const request: Record<string, Json> = { candidate_id: candidateId };
    if (expectedHash) request.expected_hash = expectedHash;
    return this.manuscriptCall<AppliedSuggestion>('manuscript.apply_suggestion', request);
  }

  /**
   * The compiled PDF's bytes, for `usePdfDocument`.
   *
   * `latest` and `last-good` are accepted where a build id is expected, because "show me
   * what I just compiled" and "show me the last thing that worked" are exactly the two
   * questions a failed build makes different. A workspace that has never compiled answers
   * 404, which surfaces as `HarnessRequestError`.
   */
  async manuscriptBuildPdf(buildId: string): Promise<ArrayBuffer> {
    const path = `/manuscript/builds/${encodeURIComponent(buildId)}/pdf`;
    const response = await this.http(`${this.baseUrl}${path}`, { headers: this.headers() });
    if (!response.ok) {
      throw new HarnessRequestError(response.status, path, `${response.status} on ${path}`);
    }
    return response.arrayBuffer();
  }

  /** The same PDF as a link a browser can open; the token rides as a query, as for artifacts. */
  manuscriptBuildPdfUrl(buildId: string): string {
    const path = `${this.baseUrl}/manuscript/builds/${encodeURIComponent(buildId)}/pdf`;
    return this.token ? `${path}?token=${encodeURIComponent(this.token)}` : path;
  }

  /**
   * The one seam over the stale capability-name union.
   *
   * `capabilities.gen.ts` is regenerated from the daemon snapshot after the P21 backend
   * wave; until then the eight manuscript-workspace names are absent from `CapabilityName`.
   * Narrowing to `ManuscriptWorkspaceCapability` keeps a typo a compile error, and the cast
   * lives here rather than at nine call sites.
   */
  private manuscriptCall<T>(name: ManuscriptWorkspaceCapability, request: Json = {}): Promise<T> {
    return this.call<T>(name as CapabilityName, request);
  }

  // -- conversation workspace (P18) ------------------------------------------
  //
  // The permission split is the daemon's: the five reads answer for an agent host, and
  // every write — create, rename, send, stop, retry, promote, summarize — is `MUTATE` and
  // therefore researcher-only, so a host may be shown a transcript and may not append to
  // one (`capabilities/conversation.py`). `session.send` is the *only* way a message is
  // written; the run's events are a read stream, not a second write surface.

  /** Open a durable session. Private by default; the daemon allocates the `CS####`. */
  async createSession(input: {
    title: string;
    visibility?: 'private' | 'project';
    model?: string | null;
    mode?: string | null;
    tokenBudget?: number | null;
  }): Promise<ConversationSession> {
    const request: Record<string, Json> = { title: input.title };
    if (input.visibility) request.visibility = input.visibility;
    if (input.model) request.model = input.model;
    if (input.mode) request.mode = input.mode;
    if (input.tokenBudget !== undefined && input.tokenBudget !== null) {
      request.token_budget = input.tokenBudget;
    }
    return (await this.call<SessionView>('session.create', request)).session;
  }

  /** Retitle a session. Its id and transcript are untouched. */
  async renameSession(session: string, title: string): Promise<ConversationSession> {
    return (await this.call<SessionView>('session.rename', { session, title })).session;
  }

  /**
   * Bind a session to a runtime and model, to an entry, or clear it.
   *
   * `research.yaml` is untouched: the binding lives on the session record, and the daemon
   * resolves it through the same validator and gates a configured entry passes. Exactly
   * one of `runtime`, `entry` and `clear` is sent, and the daemon refuses anything else in
   * its own words.
   */
  async configureSession(input: ConfigureSessionRequest): Promise<ConversationSession> {
    const request: Record<string, Json> = { session: input.session };
    if (input.runtime !== undefined) request.runtime = input.runtime;
    if (input.model !== undefined) request.model = input.model;
    if (input.reasoning !== undefined) request.reasoning = input.reasoning;
    if (input.entry !== undefined) request.entry = input.entry;
    if (input.clear !== undefined) request.clear = input.clear;
    return (await this.call<SessionView>('session.configure', request)).session;
  }

  /** Every conversation session in this project, ordered by id. */
  async sessions(): Promise<ConversationSession[]> {
    return (await this.call<SessionListView>('session.list', {})).sessions;
  }

  /**
   * One session's transcript, oldest first.
   *
   * This is also the reconciliation read: the daemon persists every streamed delta into
   * the message before emitting it, so re-reading here is how a client recovers from a
   * dropped stream, a reload, or a stop (v1.1 plan §0.4).
   */
  sessionTranscript(
    session: string,
    page: { offset?: number; limit?: number } = {},
  ): Promise<SessionTranscript> {
    const request: Record<string, Json> = { session };
    if (page.offset !== undefined) request.offset = page.offset;
    if (page.limit !== undefined) request.limit = page.limit;
    return this.call<SessionTranscript>('session.get', request);
  }

  /** Sessions whose title or messages contain a query. A direct transcript read. */
  searchSessions(query: string, limit?: number): Promise<SessionSearchResults> {
    const request: Record<string, Json> = { query };
    if (limit !== undefined) request.limit = limit;
    return this.call<SessionSearchResults>('session.search', request);
  }

  /** Regenerate the derived `summary.md`. A summary never outranks the transcript. */
  summarizeSession(session: string): Promise<SessionSummaryView> {
    return this.call<SessionSummaryView>('session.summarize', { session });
  }

  /**
   * Append a message and start the answer.
   *
   * It returns as soon as the user message, the `ContextPack` and the run are durable, so
   * every id it hands back can already be read; the answer is followed on
   * `GET /runs/{run_id}/events` through `subscribeRunEvents`.
   */
  sendMessage(input: SendMessageRequest): Promise<SendStarted> {
    const request: Record<string, Json> = { session: input.session, text: input.text };
    if (input.references?.length) request.references = input.references;
    if (input.attachments?.length) request.attachments = input.attachments;
    if (input.model) request.model = input.model;
    if (input.token_budget) request.token_budget = input.token_budget;
    return this.call<SendStarted>('session.send', request);
  }

  /** Cancel a run. The partial answer is kept on disk and marked incomplete. */
  stopSend(runId: string): Promise<SessionStopped> {
    return this.call<SessionStopped>('session.stop', { run_id: runId });
  }

  /** Answer again as a new attempt. Nothing about the failed attempt is deleted. */
  retryMessage(message: string, options: { session?: string; model?: string } = {}): Promise<SendStarted> {
    const request: Record<string, Json> = { message };
    if (options.session) request.session = options.session;
    if (options.model) request.model = options.model;
    return this.call<SendStarted>('session.retry', request);
  }

  /**
   * Copy an excerpt into reviewable state.
   *
   * `target: 'evidence'` is accepted by the request schema on purpose: the daemon refuses
   * it with the anchor requirement rather than with "not a valid enum value" (§42 M), and
   * the dialog renders that refusal instead of hiding the option silently.
   */
  promoteMessage(input: PromoteMessageRequest): Promise<PromotionView> {
    const request: Record<string, Json> = {
      session: input.session,
      message: input.message,
      target: input.target,
    };
    if (input.excerpt) request.excerpt = input.excerpt;
    if (input.rationale) request.rationale = input.rationale;
    if (input.question) request.question = input.question;
    if (input.claim) request.claim = input.claim;
    if (input.subject) request.subject = input.subject;
    if (input.predicate) request.predicate = input.predicate;
    if (input.object) request.object = input.object;
    if (input.claim_type) request.claim_type = input.claim_type;
    if (input.scope) request.scope = input.scope;
    if (input.corpus) request.corpus = input.corpus;
    if (input.decision_type) request.decision_type = input.decision_type;
    if (input.title) request.title = input.title;
    return this.call<PromotionView>('session.promote', request);
  }

  /** What a message *would* send. `persist: false` is the draft preview; it sends nothing. */
  previewContext(input: ContextPreviewRequest): Promise<ContextPackView> {
    const request: Record<string, Json> = { session: input.session };
    if (input.text !== undefined) request.text = input.text;
    if (input.references?.length) request.references = input.references;
    if (input.model) request.model = input.model;
    if (input.token_budget) request.token_budget = input.token_budget;
    if (input.persist !== undefined) request.persist = input.persist;
    return this.call<ContextPackView>('context.preview', request);
  }

  /** The receipt recorded on a past message: the same view `context.preview` returns. */
  getContext(session: string, pack: string): Promise<ContextPackView> {
    return this.conversationCall<ContextPackView>('context.get', { session, pack });
  }

  /**
   * The models this project may send to, with the egress class each one implies.
   *
   * Derived server-side from the router configuration and the egress report, so the model
   * selector offers what the daemon says exists and never works out a provider rule for
   * itself; an unavailable model comes back with the daemon's own reason.
   */
  providers(): Promise<ProviderCatalog> {
    return this.conversationCall<ProviderCatalog>('provider.list', {});
  }

  // -- subscription-backed CLI providers (provider.cli.*) ----------------------

  /** Detect the supported local CLIs. A read; `rescan` bypasses the daemon's short cache. */
  providerCliScan(rescan = false): Promise<CliScanReport> {
    return this.call<CliScanReport>('provider.cli.scan', { rescan });
  }

  /** Add or update one `local_cli` entry in research.yaml. Researcher-only. */
  providerCliConfigure(request: CliProviderConfigureRequest): Promise<CliProviderConfigured> {
    return this.call<CliProviderConfigured>('provider.cli.configure', request as unknown as Json);
  }

  /** Remove one `local_cli` entry. Researcher-only. */
  providerCliRemove(name: string): Promise<CliProviderRemoved> {
    return this.call<CliProviderRemoved>('provider.cli.remove', { name });
  }

  /** One minimal validated request through a configured entry; external egress, researcher-only. */
  providerCliTest(name: string): Promise<CliProviderTestReport> {
    return this.call<CliProviderTestReport>('provider.cli.test', { name });
  }

  /** One session attachment's bytes, read with the token header like artifact bytes. */
  sessionAttachmentBytes(session: string, attachment: string): Promise<ArrayBuffer> {
    return this.bytes(
      `/sessions/${encodeURIComponent(session)}/attachments/${encodeURIComponent(attachment)}/bytes`,
    );
  }

  /** A rendered page preview of a session attachment, same authority, same route family. */
  sessionAttachmentPreview(session: string, attachment: string, page?: number): Promise<ArrayBuffer> {
    const base = `/sessions/${encodeURIComponent(session)}/attachments/${encodeURIComponent(attachment)}/preview`;
    return this.bytes(page === undefined ? base : `${base}?page=${page}`);
  }

  // -- attachments (P19) -----------------------------------------------------
  //
  // Four capabilities and one byte route. The route is the single documented write that is
  // not a capability call (v1.1 plan §0.4) and it is deliberately narrow: it writes bytes
  // into `conversations/<session>/attachments/` through the same service `attachment.add`
  // uses, under the same `mutate`, researcher-only authorisation, and it can create no
  // Work, Version, Artifact or Evidence. Corpus identity comes from one place only, and it
  // is `attachment.save_to_corpus` below.

  /**
   * Attach one file to a session. Session-only working material; no corpus object.
   *
   * The body is the raw file and `Content-Type` is its media type, because base64-ing a
   * 30 MB PDF through a JSON capability request buys nothing — the same bytes reach the
   * same service either way. `?filename=` is display metadata: the daemon keeps only its
   * basename and never treats it as a path (attachments design §8).
   *
   * A file the daemon refuses on validation comes back as a `failed` attachment carrying
   * its reason, not as an error: an item that disappears is the failure mode the design
   * forbids. Only a refusal of the *request* — no bytes, too large, no such session, a
   * caller that may not write — throws.
   */
  async addSessionAttachment(
    session: string,
    file: Blob,
    options: { filename?: string; description?: string } = {},
  ): Promise<AttachmentView> {
    const name = options.filename ?? (file instanceof File ? file.name : 'attachment');
    const query = new URLSearchParams({ filename: name });
    if (options.description) query.set('description', options.description);
    const path = `/sessions/${encodeURIComponent(session)}/attachments?${query.toString()}`;
    const response = await this.http(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: {
        ...this.headers(),
        // The daemon records what we declare and narrows it to its own allowlist before
        // ever serving the bytes back, so a browser that guessed nothing is still safe.
        'Content-Type': file.type || 'application/octet-stream',
      },
      body: file,
    });
    if (!response.ok) {
      throw new HarnessRequestError(response.status, path, await refusalText(response, path));
    }
    return (await response.json()) as AttachmentView;
  }

  /** Delete one session attachment, its bytes and its previews. The corpus is untouched. */
  removeSessionAttachment(session: string, attachment: string): Promise<AttachmentRemoved> {
    return this.call<AttachmentRemoved>('attachment.remove', { session, attachment });
  }

  /**
   * Whether each attachment may go to the selected model, and why not. A read.
   *
   * `provider` takes the configured entry's name — which is exactly `ProviderModel.id`,
   * the same string `session.send` takes as `model`. (`ProviderModel.provider` is the
   * adapter kind and is not what the daemon matches on.) The answer names the entry and
   * the model it serves, so a client never has to work out which one was checked.
   */
  checkAttachmentSend(input: CheckAttachmentSendRequest): Promise<AttachmentSendCheck> {
    const request: Record<string, Json> = { session: input.session };
    if (input.provider) request.provider = input.provider;
    if (input.model) request.model = input.model;
    if (input.attachments?.length) request.attachments = input.attachments;
    return this.call<AttachmentSendCheck>('attachment.check_send', request);
  }

  /** What this attachment would become in the corpus. Writes nothing, saves nothing. */
  resolveAttachmentIdentity(session: string, attachment: string): Promise<AttachmentIdentityView> {
    return this.call<AttachmentIdentityView>('attachment.resolve_identity', {
      session,
      attachment,
    });
  }

  /**
   * The explicit promotion: copy the bytes into the corpus under a resolved identity.
   *
   * `as_new` and `attach_to` are the researcher's answer for an identity the resolver could
   * not decide; an ambiguous file with neither is refused rather than guessed (PRODUCT §13).
   * It creates or links Work/Version/Artifact identity and parses the file — and accepts no
   * Evidence and no Claim, which is what `evidence_created: false` on the result says.
   */
  saveAttachmentToCorpus(input: SaveAttachmentToCorpusRequest): Promise<AttachmentPromotionView> {
    const request: Record<string, Json> = {
      session: input.session,
      attachment: input.attachment,
    };
    if (input.as_new) request.as_new = true;
    if (input.attach_to) request.attach_to = input.attach_to;
    if (input.parse !== undefined) request.parse = input.parse;
    return this.call<AttachmentPromotionView>('attachment.save_to_corpus', request);
  }

  // -- research graph (P20) --------------------------------------------------
  //
  // All six are `READ`, so they answer for an agent host as well as for the researcher,
  // and none of them changes a canonical object: the graph is a disposable projection and
  // rebuilding it is `state.rebuild`'s job. Nothing here interprets a result — `authority`
  // and `visibility` arrive on every node and edge, and the cockpit renders them.

  /**
   * Resolve `@E0482`, `E0482`, or `rh://artifact/A0017-3?page=6&block=B0081`.
   *
   * The one `graph.*` read that does not answer from the index: existence, authority,
   * privacy and anchor freshness are checked against the canonical (or, for a session,
   * durable) record, so a rebuilding graph degrades navigation and never mislabels
   * authority (graph spec §5, ADR-001).
   */
  resolveReference(reference: string): Promise<GraphResolvedView> {
    return this.call<GraphResolvedView>('graph.resolve', { reference });
  }

  /** Complete a partially typed `@` reference. Identity matches come before text matches. */
  autocompleteReferences(input: GraphAutocompleteRequest): Promise<GraphAutocompleteResult> {
    const request: Record<string, Json> = { prefix: input.prefix };
    if (input.kinds?.length) request.kinds = input.kinds;
    if (input.visibility?.length) request.visibility = input.visibility;
    if (input.limit !== undefined) request.limit = input.limit;
    return this.call<GraphAutocompleteResult>('graph.autocomplete', request);
  }

  /** One or two hops around a node, in either direction, filtered as asked. */
  graphNeighbors(input: GraphNeighborsRequest): Promise<GraphNeighbourhoodView> {
    const request: Record<string, Json> = { id: input.id };
    if (input.hops !== undefined) request.hops = input.hops;
    if (input.direction) request.direction = input.direction;
    if (input.edge_kinds?.length) request.edge_kinds = input.edge_kinds;
    if (input.origins?.length) request.origins = input.origins;
    if (input.kinds?.length) request.kinds = input.kinds;
    if (input.authority?.length) request.authority = input.authority;
    if (input.visibility?.length) request.visibility = input.visibility;
    if (input.limit !== undefined) request.limit = input.limit;
    return this.call<GraphNeighbourhoodView>('graph.neighbors', request);
  }

  /** Nodes matching a structured kind/authority/visibility/link filter. */
  graphQuery(input: GraphQueryRequest = {}): Promise<GraphQueryResult> {
    const request: Record<string, Json> = {};
    if (input.kinds?.length) request.kinds = input.kinds;
    if (input.authorities?.length) request.authorities = input.authorities;
    if (input.visibility?.length) request.visibility = input.visibility;
    if (input.edge_kinds?.length) request.edge_kinds = input.edge_kinds;
    if (input.origins?.length) request.origins = input.origins;
    if (input.linked_to) request.linked_to = input.linked_to;
    if (input.direction) request.direction = input.direction;
    if (input.text) request.text = input.text;
    if (input.identities?.length) request.identities = input.identities;
    if (input.limit !== undefined) request.limit = input.limit;
    return this.call<GraphQueryResult>('graph.query', request);
  }

  /** The shortest path from a node to its source, e.g. Claim to the exact Artifact anchor. */
  graphProvenance(input: GraphProvenanceRequest): Promise<GraphProvenanceView> {
    const request: Record<string, Json> = { id: input.id };
    if (input.to_kind) request.to_kind = input.to_kind;
    if (input.visibility?.length) request.visibility = input.visibility;
    return this.call<GraphProvenanceView>('graph.provenance', request);
  }

  /** Whether the index is there, how big it is, and whether a rebuild is in flight. */
  graphStatus(): Promise<GraphStatusView> {
    return this.call<GraphStatusView>('graph.status', {});
  }

  /**
   * What `subscribeRunEvents` needs, and nothing more.
   *
   * The event stream is read with `fetch` rather than `EventSource` so the token can ride
   * in the `Authorization` header (see `sse.ts`); it therefore needs this client's origin,
   * token and `fetch` — one accessor rather than three, and no method here opens a stream,
   * because the run's events belong to the caller's lifecycle, not to the client's.
   */
  get stream(): { baseUrl: string; token: string | null; fetchImpl: typeof fetch } {
    return { baseUrl: this.baseUrl, token: this.token, fetchImpl: this.http };
  }

  /**
   * The seam over the stale capability-name union, for P18's two newest reads.
   *
   * `context.get` and `provider.list` are not yet in `capabilities.gen.ts`. Same shape as
   * `manuscriptCall` above, and it disappears the same way: when the snapshot is
   * regenerated, `ConversationReadCapability` becomes a subset of `CapabilityName` and the
   * cast can go.
   */
  private conversationCall<T>(name: ConversationReadCapability, request: Json = {}): Promise<T> {
    return this.call<T>(name as CapabilityName, request);
  }

  // -- plumbing --------------------------------------------------------------

  private headers(): Record<string, string> {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
  }

  /** One byte route, read with the token header. The caller makes the object URL. */
  private async bytes(path: string): Promise<ArrayBuffer> {
    const response = await this.http(`${this.baseUrl}${path}`, { headers: this.headers() });
    if (!response.ok) {
      throw new HarnessRequestError(response.status, path, `${response.status} on ${path}`);
    }
    return response.arrayBuffer();
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

/**
 * The daemon's own words for a route refusal.
 *
 * A route raises `HTTPException(detail=...)`, and `detail` is a string for a plain refusal
 * but the whole capability error body — `{status, error: {code, message}, ...}` — when the
 * refusal came from `Principal.authorize`, so that a byte route and
 * `POST /capabilities/attachment.add` disagree about nothing (ADR-009). Both are unwrapped
 * to the sentence a researcher should read; an unreadable body falls back to the status.
 */
async function refusalText(response: Response, path: string): Promise<string> {
  const fallback = `${response.status} on ${path}`;
  const body = await response.text().catch(() => '');
  if (!body) return fallback;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === 'string') return detail;
    if (detail !== null && typeof detail === 'object') {
      const error = (detail as { error?: { message?: unknown } }).error;
      if (error && typeof error.message === 'string') return error.message;
    }
  } catch {
    /* not JSON: the text itself is the message */
  }
  return body || fallback;
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

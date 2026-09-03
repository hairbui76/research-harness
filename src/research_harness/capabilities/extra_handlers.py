"""The Product 22 capabilities the Phase 1 handler table does not cover yet.

Two kinds of thing live here, and nothing else:

1. **Read capabilities.** Product 22 names reads (`work.get`, `review.inbox`, `state.stale`,
   `retrieval.search`, ...) that hosts need as much as they need mutations. A read has no
   handler in `handlers.py` because it changes nothing; it belongs to the registry all the
   same, so a host discovers one surface rather than two.
2. **Missing mutations,** each delegating to a service that already owns the rule. Where a
   service implements a capability (`NoteService.discard`, `EvidenceReviewService`,
   `SynthesisService`, `screen`), the adapter here is a DTO translation and nothing more:
   ADR-004 forbids a second business-logic layer, so the rule stays where it is.

Every service import is deferred into the handler, so importing the capability layer still
pulls in no parser, no projection engine, and no model provider (Gate P1). A service that
is not installed is not registered with a stub: :func:`register_into` records the name as
planned, and `describe()` says so.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.attachments import (
    ATTACHMENT_CAPABILITIES,
    ATTACHMENT_CAPABILITY_HANDLERS,
    attachment_specs,
)
from research_harness.capabilities.context import CapabilityContext, actor_provenance
from research_harness.capabilities.conversation import (
    CONVERSATION_CAPABILITIES,
    CONVERSATION_CAPABILITY_HANDLERS,
    conversation_specs,
)
from research_harness.capabilities.dto import (
    CapabilityRequest,
    IngestLocalPdfRequest,
    MutationResult,
    ParseWorkRequest,
)
from research_harness.capabilities.graph import (
    GRAPH_CAPABILITIES,
    GRAPH_CAPABILITY_HANDLERS,
    graph_specs,
)
from research_harness.capabilities.manuscript_workspace import (
    MANUSCRIPT_WORKSPACE_CAPABILITIES,
    MANUSCRIPT_WORKSPACE_HANDLERS,
    manuscript_workspace_specs,
)
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.providers import (
    PROVIDER_CAPABILITIES,
    PROVIDER_CAPABILITY_HANDLERS,
    provider_specs,
)
from research_harness.capabilities.reads import (
    READ_CAPABILITY_HANDLERS,
    AnchorSummary,
    anchor_summary,
    read_specs,
)
from research_harness.capabilities.registry import (
    CapabilityRegistry,
    CapabilitySpec,
    MutationResponse,
    StaleBody,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    DecisionStatus,
    EvidenceOrigin,
    ResearchEventType,
    ReviewAction,
    ScreeningState,
)
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    DecisionId,
    InterpretationId,
    QuestionId,
    SearchRunId,
    SynthesisId,
    WorkId,
)
from research_harness.domain.transitions import transition_decision
from research_harness.domain.work import IdentifierField, Work, WorkIdentifiers

if TYPE_CHECKING:  # imported lazily at runtime so this layer stays parser- and provider-free
    from research_harness.evidence.service import EvidenceReviewService
    from research_harness.manuscript.attach import ManuscriptService, RevalidationReport
    from research_harness.manuscript.audit import ManuscriptAuditReport

__all__ = [
    "EXTRA_CAPABILITY_HANDLERS",
    "AcceptBatchRequest",
    "BatchAcceptResponse",
    "CancelRunRequest",
    "ClaimSupport",
    "CompareFieldRequest",
    "ComparisonView",
    "CounterEvidenceReport",
    "DiscardNoteRequest",
    "DiscoverCorpusRequest",
    "DraftSectionRequest",
    "EvidenceRelationView",
    "FindCounterEvidenceRequest",
    "FindSupportRequest",
    "GetWorkRequest",
    "IngestResponse",
    "InterrogateWorkRequest",
    "ManuscriptProjectRequest",
    "ParseResponse",
    "RebuildResponse",
    "RebuildStateRequest",
    "ResolveConflictRequest",
    "ResolveQuestionRequest",
    "ResolveSourceRequest",
    "ReviewInbox",
    "ReviewInboxRequest",
    "RunStarted",
    "RunStatus",
    "RunStatusRequest",
    "ScreenCandidateRequest",
    "SearchCorpusRequest",
    "SplitCandidateRequest",
    "SplitOutcome",
    "StaleReport",
    "StaleStateRequest",
    "SupersedeDecisionRequest",
    "VerifyEvidenceRequest",
    "WorkView",
    "discard_note",
    "discard_note_mutation",
    "discover_corpus",
    "get_state_stale",
    "register_into",
    "run_status",
    "supersede_decision",
]

logger = logging.getLogger(__name__)

DISCARD_CAPABILITY = "note.discard"
SUPERSEDE_DECISION_CAPABILITY = "decision.supersede"
DISCOVER_CAPABILITY = "corpus.search"
UPDATE_METADATA_CAPABILITY = "work.update_metadata"

DEFAULT_DISCOVERY_PAGES = 3
"""Pages walked per source when a caller names no budget; mirrors the CLI default."""


# -- requests ----------------------------------------------------------------


class GetWorkRequest(CapabilityRequest):
    """`work.get`: read one Work with its versions, artifacts, and counts."""

    work: WorkId


class ScreenCandidateRequest(CapabilityRequest):
    """`corpus.screen`: record a screening decision for one discovery candidate."""

    search_run: SearchRunId
    key: str
    state: ScreeningState
    reason: str | None = None


class DiscoverCorpusRequest(CapabilityRequest):
    """`corpus.search`: run one reproducible external discovery search (Product 18).

    Discovery reads external catalogues and writes nothing to them; what it writes locally
    is the `SearchRun` that makes the operation reproducible, persisted through
    `search_run.record` by the service, exactly as `research discover` does.
    """

    question: str
    query: str
    sources: tuple[str, ...] = ()
    max_pages: int = Field(default=DEFAULT_DISCOVERY_PAGES, ge=1, le=100)
    year_from: int | None = None
    cutoff: str | None = None
    research_question: QuestionId | None = None
    reproduces: SearchRunId | None = None


class SearchCorpusRequest(CapabilityRequest):
    """`retrieval.search`: search accepted state and the corpus, accepted state first."""

    query: str
    k: int = Field(default=10, ge=1, le=200)
    modes: tuple[str, ...] = ()
    intent: str | None = None


class ResolveSourceRequest(CapabilityRequest):
    """`retrieval.resolve_source`: the exact source location behind a reference."""

    ref: str


class InterrogateWorkRequest(CapabilityRequest):
    """`work.interrogate` / `evidence.extract`: ask a Work the schema's questions.

    The run stages candidates under `.research/staging`; nothing it produces is accepted
    Evidence until a researcher reviews it (ADR-003, ADR-007).
    """

    work: WorkId
    provider: str
    """Name or tag of a provider entry in `research.yaml`; models are configuration."""

    fields: tuple[str, ...] = ()
    artifact: ArtifactId | None = None


class VerifyEvidenceRequest(CapabilityRequest):
    """`evidence.verify`: re-read the source for staged candidates and record a verdict."""

    work: WorkId
    provider: str
    candidates: tuple[str, ...] = ()
    force: bool = False


class ReviewInboxRequest(CapabilityRequest):
    """`review.inbox`: the review queue in Product 24.2 priority order."""

    work: WorkId | None = None


class AcceptBatchRequest(CapabilityRequest):
    """`review.accept_batch`: accept every candidate that meets the Product 24.4 conditions."""

    work: WorkId | None = None
    dry_run: bool = False


class ResolveConflictRequest(CapabilityRequest):
    """`review.resolve_conflict`: the researcher's answer to a conflict, with its reason."""

    candidate_id: str
    choice: Literal["accept", "reject", "defer"]
    reason: str


class FindSupportRequest(CapabilityRequest):
    """`claim.find_support`: the evidence a Claim already records, resolved."""

    claim_id: ClaimId


class FindCounterEvidenceRequest(CapabilityRequest):
    """`claim.find_counterevidence`: retrieval proposals that might bear against a Claim."""

    claim_id: ClaimId
    limit: int = Field(default=10, ge=1, le=100)


class ResolveQuestionRequest(CapabilityRequest):
    """`question.resolve`: answer a research question and capture the answer as a note."""

    question_id: QuestionId
    answer: str


class DiscardNoteRequest(CapabilityRequest):
    """`note.discard`: retire a captured note; discarded is terminal.

    ``reason`` is optional because a note carries no authority to withdraw: discarding one
    is housekeeping, not a retraction. When it is given it is recorded in the event, so the
    log says why the researcher stopped tracking the thought.
    """

    note_key: str
    reason: str | None = None


class SupersedeDecisionRequest(CapabilityRequest):
    """`decision.supersede`: retire an accepted Decision, optionally naming its replacement."""

    decision_id: DecisionId
    reason: str
    superseded_by: DecisionId | None = None


class CandidateReviewRequest(CapabilityRequest):
    """`review.accept`: accept one staged candidate, named by its staging id."""

    candidate_id: str


class QualifyCandidateRequest(CapabilityRequest):
    """`review.qualify`: accept one candidate with the condition it holds under."""

    candidate_id: str
    qualification: str


class EditCandidateRequest(CapabilityRequest):
    """`review.edit`: accept the researcher's corrected Evidence for one candidate.

    An edit may correct what the evidence says; it may never move the source anchor, which
    `evidence.accept` refuses (ADR-002). The corrected object's own id is ignored: the real
    `EvidenceId` is allocated at acceptance, as it is for every other review action.
    """

    candidate_id: str
    edited: Evidence


class RejectCandidateRequest(CapabilityRequest):
    """`review.reject`: refuse one candidate, with the reason that is recorded with it."""

    candidate_id: str
    reason: str


class DeferCandidateRequest(CapabilityRequest):
    """`review.defer`: put one candidate aside; it stays in the queue (Product 24.3)."""

    candidate_id: str
    note: str


class RequestMoreEvidenceRequest(CapabilityRequest):
    """`review.request_more`: ask for more evidence and capture the question durably."""

    candidate_id: str
    note: str


class SplitCandidateRequest(CapabilityRequest):
    """`review.split`: accept the source fact and deal with its interpretation separately.

    `fact` is the Evidence to accept; omitting it accepts the candidate's own evidence
    unchanged, which is the common case. Exactly one of `interpretation` and
    `reject_interpretation_reason` must be given: the interpretation is either staged as its
    own Tier-2 candidate under a distinct field, or refused with a reason that is recorded
    like any other refusal (Product 24.3, ADR-007).
    """

    candidate_id: str
    fact: Evidence | None = None
    interpretation: str | None = None
    interpretation_origin: EvidenceOrigin = EvidenceOrigin.AUTHOR_INTERPRETED
    """Origin of the split-out reading; never `source_observed`, which is not interpretive."""

    reject_interpretation_reason: str | None = None


class UpdateWorkMetadataRequest(CapabilityRequest):
    """`work.update_metadata`: fill a Work's empty or undecodable bibliographic fields.

    Every value carries its own provenance, because identity resolution must never erase
    where a conflicting value came from (Product 13). The default policy only *fills*: a
    field that already holds a decodable value is reported as a conflict and left alone,
    so better metadata found later is neither discarded (dogfood F5) nor written over the
    researcher's record without being asked.
    """

    work: WorkId
    title: IdentifierField | None = None
    authors: tuple[IdentifierField, ...] | None = None
    year: IdentifierField | None = None
    venue: IdentifierField | None = None
    identifiers: WorkIdentifiers | None = None
    overwrite: bool = False
    """Replace a decodable existing value too. The conflict is still recorded."""


class CompareFieldRequest(CapabilityRequest):
    """`synthesis.compare`: one field across the corpus, as a comparison table."""

    field: str
    matrix_id: SynthesisId | None = None


class ManuscriptProjectRequest(CapabilityRequest):
    """`manuscript.audit` / `citation.verify`: which LaTeX project to read."""

    project_root: Path | None = None
    main_tex: str = "main.tex"


class AuditManuscriptRequest(ManuscriptProjectRequest):
    """`manuscript.audit`: the project, optionally narrowed to one file and line range.

    An editor auditing the lines on screen should not pay for a whole-project run: with a
    range the audit re-parses only the artifacts the anchors in that range rest on, and
    reports only those sentences. The rules applied are identical either way - narrowing
    changes what is *asked about*, never what counts as a finding (Product 28, 30.3).
    """

    file: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    def scope(self) -> Any:
        """The `AuditScope` this request names, or ``None`` for the whole project."""
        from research_harness.manuscript.audit import AuditScope

        if self.file is None:
            if self.line_start is not None or self.line_end is not None:
                raise CapabilityError(
                    "manuscript.audit: a line range needs the file it is a range in; "
                    "pass `file` beside `line_start`/`line_end`"
                )
            return None
        return AuditScope(file=self.file, line_start=self.line_start, line_end=self.line_end)


class RevalidateManuscriptRequest(ManuscriptProjectRequest):
    """`manuscript.revalidate`: re-find every stored anchor and record the verdict."""

    dry_run: bool = False
    """Report the verdicts and record none of them; nothing canonical is written."""


class TraceManuscriptRequest(ManuscriptProjectRequest):
    """`manuscript.trace`: one sentence, by file and line, down to its source spans."""

    file: str
    line: int = Field(ge=1)


class DraftSectionRequest(CapabilityRequest):
    """`manuscript.draft`: draft a section from named accepted Claims, into staging."""

    purpose: str
    claims: tuple[ClaimId, ...]
    provider: str
    style: str | None = None


class RebuildStateRequest(CapabilityRequest):
    """`state.rebuild`: rebuild the deletable projection from canonical files."""


class StaleStateRequest(CapabilityRequest):
    """`state.stale`: what is out of date, highest scientific impact first."""

    limit: int = Field(default=200, ge=1, le=5000)


class RunStatusRequest(CapabilityRequest):
    """`run.status`: the durable record of one long-running workflow."""

    run_id: str


class CancelRunRequest(CapabilityRequest):
    """`run.cancel`: ask a running workflow to stop before its next stage."""

    run_id: str


# -- responses ---------------------------------------------------------------


class _Response(BaseModel):
    """Frozen, closed response envelope; every transport sees the same JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class VersionView(_Response):
    """One Version of a Work."""

    id: str
    kind: str
    label: str | None = None


class ArtifactView(_Response):
    """One immutable Artifact of a Work."""

    id: str
    version: str
    kind: str
    file_hash: str
    size_bytes: int
    original_filename: str | None = None


class WorkView(_Response):
    """`work.get`: one Work as a host reads it."""

    id: str
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    screening: str
    identifiers: dict[str, Any] = Field(default_factory=dict)
    versions: tuple[VersionView, ...] = ()
    artifacts: tuple[ArtifactView, ...] = ()
    blocks: int = 0
    evidence: int = 0


class IngestResponse(_Response):
    """`corpus.ingest`: what one local file resolved to, and what that created."""

    work: str
    version: str
    artifact: str
    created: str
    resolution: str
    reasons: tuple[str, ...] = ()
    mutation: MutationResponse | None = None


class ParseResponse(_Response):
    """`work.parse`: the stored parse and the mutation that stored it."""

    work: str
    artifact: str
    parser: str
    pages: int
    blocks: int
    mutation: MutationResponse


class EvidenceRelationView(_Response):
    """One claim-evidence edge, with the evidence resolved where it exists."""

    evidence: str
    relation: str
    aspect: str | None = None
    note: str | None = None
    resolved: bool = False
    work: str | None = None
    status: str | None = None
    exact_text: str | None = None


class ClaimSupport(_Response):
    """`claim.find_support`: every edge a Claim records, grouped by what it does."""

    claim: str
    statement: str
    status: str
    requested_strength: str
    allowed_strength: str
    supporting: tuple[EvidenceRelationView, ...] = ()
    qualifying: tuple[EvidenceRelationView, ...] = ()
    contradicting: tuple[EvidenceRelationView, ...] = ()
    other: tuple[EvidenceRelationView, ...] = ()


class CounterCandidate(_Response):
    """One retrieval proposal that might bear against a claim. Never Evidence."""

    ref: str
    work: str | None = None
    text: str = ""
    score: float = 0.0
    source: str = ""
    location: str = ""


class CounterEvidenceReport(_Response):
    """`claim.find_counterevidence`: proposals to look at, not findings."""

    claim: str
    candidates: tuple[CounterCandidate, ...] = ()


class ReviewInbox(_Response):
    """`review.inbox`: the queue, its category counts, and the items in priority order."""

    count: int
    counts: dict[str, int] = Field(default_factory=dict)
    items: tuple[dict[str, Any], ...] = ()


class BatchAcceptResponse(_Response):
    """`review.accept_batch`: what the policy batch accepted, and why it skipped the rest."""

    dry_run: bool
    accepted: tuple[str, ...] = ()
    skipped: dict[str, str] = Field(default_factory=dict)
    mutations: tuple[MutationResponse, ...] = ()


class ConflictResolution(_Response):
    """`review.resolve_conflict`: the mutation the researcher's answer produced, if any."""

    candidate_id: str
    choice: str
    mutation: MutationResponse | None = None


class ReviewOutcome(_Response):
    """What one candidate-keyed review action did, on every transport identically.

    ``mutation`` is absent for the two actions that change no accepted state: deferring is
    a note to the researcher's future self, and requesting more evidence writes its
    question as a low-authority note, which is reported as ``note`` instead.
    """

    candidate_id: str
    action: str
    status: str
    """The staged candidate's status after the action, as `review.inbox` will read it."""

    evidence: str | None = None
    """The `EvidenceId` the acceptance wrote, when the action created one."""

    mutation: MutationResponse | None = None


class SplitOutcome(_Response):
    """What one partial acceptance did: one accepted fact, its interpretation elsewhere.

    Exactly one accepted Evidence results, whichever half of the split was taken, so
    ``evidence`` is never absent and ``interpretation_candidate``/``rejected`` are the two
    mutually exclusive fates of the interpretation.
    """

    candidate_id: str
    action: str
    status: str
    evidence: str
    interpretation_candidate: str | None = None
    """Staging id of the interpretation, when it was staged for its own Tier-2 review."""

    mutation: MutationResponse
    rejected: MutationResponse | None = None
    """The `evidence.reject` mutation, when the interpretation was refused instead."""


class AnchorVerdict(_Response):
    """One stored anchor re-found in the manuscript as it is now (ADR-008)."""

    anchor: str
    claim: str
    file: str
    line_start: int
    line_end: int
    status: str
    similarity: float | None = None
    reason: str | None = None
    relocated_to: tuple[int, int] | None = None


class ManuscriptAnchors(_Response):
    """`manuscript.anchors`: every stored anchor with its verdict against the file on disk."""

    count: int = 0
    anchors: tuple[AnchorSummary, ...] = ()
    verdicts: tuple[AnchorVerdict, ...] = ()


class RevalidationView(_Response):
    """`manuscript.revalidate`: what re-finding every anchor produced, and what it recorded."""

    dry_run: bool = False
    checked: int = 0
    valid: int = 0
    relocated: int = 0
    stale: int = 0
    missing: int = 0
    applied: tuple[str, ...] = ()
    results: tuple[AnchorVerdict, ...] = ()
    mutations: tuple[MutationResponse, ...] = ()


class TraceView(_Response):
    """`manuscript.trace`: sentence -> Claim -> Evidence -> exact source span (Product 30.1).

    ``link`` is absent when the sentence carries no anchor. That is a different answer from
    a broken chain, and the sentence is still reported so a client can offer to attach one.
    """

    file: str
    line: int
    sentence: str
    anchor: str | None = None
    claim: str | None = None
    link: dict[str, Any] | None = None


class MetadataConflict(_Response):
    """One field a metadata update did not silently take over."""

    field: str
    current: str
    proposed: str
    source: str
    applied: bool = False
    """True when `overwrite` was asked for: the conflict is recorded, not hidden."""


class WorkMetadataUpdate(_Response):
    """`work.update_metadata`: which fields were filled, and which disagreed."""

    work: str
    updated: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    conflicts: tuple[MetadataConflict, ...] = ()
    mutation: MutationResponse | None = None


class ComparisonView(_Response):
    """`synthesis.compare`: one field across the corpus."""

    matrix: str
    field: str
    taxonomy: str | None = None
    label_counts: dict[str, int] = Field(default_factory=dict)
    unclassified: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()


class RebuildResponse(_Response):
    """`state.rebuild`: what the rebuild read, wrote, and refused."""

    ok: bool
    objects: int
    objects_by_type: dict[str, int] = Field(default_factory=dict)
    stale_marks: int = 0
    fts_rows: int = 0
    canonical_digest: str
    duration_ms: int = 0
    invalid_files: tuple[dict[str, str], ...] = ()
    summary: str


class StaleReport(_Response):
    """`state.stale`: objects marked stale, highest scientific impact first."""

    count: int
    marks: tuple[StaleBody, ...] = ()


class StageView(_Response):
    """One stage of a durable workflow run."""

    name: str
    status: str
    attempts: int = 0


class RunStatus(_Response):
    """A durable workflow run: the answer to "is it done yet?" without an open connection."""

    run_id: str
    workflow: str
    workflow_version: str
    status: str
    cancel_requested: bool = False
    created_at: str
    updated_at: str
    error: str | None = None
    stages: tuple[StageView, ...] = ()


class RunStarted(_Response):
    """What a long-running capability returns immediately: a durable run id."""

    run_id: str
    capability: str
    workflow: str
    status: str


# -- read handlers -----------------------------------------------------------


def get_work(ctx: CapabilityContext, request: GetWorkRequest) -> WorkView:
    """`work.get`: one Work, its revisions, its files, and how much is derived from it."""
    repo = ctx.repo
    work = repo.get_work(request.work)
    artifacts = repo.list_artifacts(work.id)
    blocks = sum(1 for artifact in artifacts for _ in repo.iter_blocks(artifact.id, work=work.id))
    return WorkView(
        id=str(work.id),
        title=work.title,
        authors=tuple(work.authors),
        year=work.year,
        venue=work.venue,
        screening=work.screening.value,
        identifiers=work.identifiers.model_dump(mode="json", exclude_none=True),
        versions=tuple(
            VersionView(id=str(version.id), kind=version.kind.value, label=version.label)
            for version in repo.list_versions(work.id)
        ),
        artifacts=tuple(
            ArtifactView(
                id=str(artifact.id),
                version=str(artifact.version),
                kind=artifact.kind.value,
                file_hash=artifact.file_hash,
                size_bytes=artifact.size_bytes,
                original_filename=artifact.original_filename,
            )
            for artifact in artifacts
        ),
        blocks=blocks,
        evidence=sum(1 for _ in repo.iter_evidence(work.id)),
    )


def search_corpus(ctx: CapabilityContext, request: SearchCorpusRequest) -> BaseModel:
    """`retrieval.search`: ranked hits over the deletable indexes, accepted state first."""
    from research_harness.retrieval.planner import Intent, QueryHints, RetrievalMode
    from research_harness.retrieval.service import RetrievalService

    hints = QueryHints(
        modes=tuple(RetrievalMode(mode) for mode in request.modes),
        intent=Intent(request.intent) if request.intent else None,
    )
    with _projection(ctx) as engine:
        service = RetrievalService(engine, ctx.repo)
        return service.search(request.query, k=request.k, hints=hints)


def resolve_source(ctx: CapabilityContext, request: ResolveSourceRequest) -> BaseModel:
    """`retrieval.resolve_source`: reopen a reference at its exact source location."""
    from research_harness.retrieval.service import RetrievalService

    with _projection(ctx) as engine:
        return RetrievalService(engine, ctx.repo).resolve_source(request.ref)


def find_support(ctx: CapabilityContext, request: FindSupportRequest) -> ClaimSupport:
    """`claim.find_support`: what a Claim actually rests on, with unresolvable ids flagged."""
    claim = ctx.repo.get_claim(request.claim_id)
    accepted = {
        item.id: item for work in ctx.repo.list_works() for item in ctx.repo.iter_evidence(work.id)
    }
    grouped: dict[str, list[EvidenceRelationView]] = {
        "supporting": [],
        "qualifying": [],
        "contradicting": [],
        "other": [],
    }
    for link in claim.relations:
        evidence = accepted.get(link.evidence)
        view = EvidenceRelationView(
            evidence=str(link.evidence),
            relation=link.relation.value,
            aspect=link.aspect,
            note=link.note,
            resolved=evidence is not None,
            work=None if evidence is None else str(evidence.source.work),
            status=None if evidence is None else evidence.status.value,
            exact_text=None if evidence is None else evidence.content.exact_text,
        )
        grouped[_relation_group(link.relation)].append(view)
    return ClaimSupport(
        claim=str(claim.id),
        statement=claim.statement,
        status=claim.assessment.status.value,
        requested_strength=claim.assessment.requested_strength.value,
        allowed_strength=claim.assessment.allowed_strength.value,
        supporting=tuple(grouped["supporting"]),
        qualifying=tuple(grouped["qualifying"]),
        contradicting=tuple(grouped["contradicting"]),
        other=tuple(grouped["other"]),
    )


def find_counter_evidence(
    ctx: CapabilityContext, request: FindCounterEvidenceRequest
) -> CounterEvidenceReport:
    """`claim.find_counterevidence`: places to look for what would break a claim."""
    from research_harness.retrieval.counter import RetrievalCounterEvidenceFinder
    from research_harness.retrieval.service import RetrievalService

    claim = ctx.repo.get_claim(request.claim_id)
    with _projection(ctx) as engine:
        finder = RetrievalCounterEvidenceFinder(RetrievalService(engine, ctx.repo))
        candidates = finder.find_counter_evidence(claim, limit=request.limit)
    return CounterEvidenceReport(
        claim=str(claim.id),
        candidates=tuple(
            CounterCandidate(
                ref=candidate.ref,
                work=None if candidate.work is None else str(candidate.work),
                text=candidate.text,
                score=candidate.score,
                source=candidate.source,
                location=candidate.location,
            )
            for candidate in candidates
        ),
    )


def review_inbox(ctx: CapabilityContext, request: ReviewInboxRequest) -> ReviewInbox:
    """`review.inbox`: the queue a researcher works down, in Product 24.2 order."""
    from research_harness.evidence.review import build_inbox, stored_documents
    from research_harness.evidence.staging import StagingStore

    staging = StagingStore(ctx.repo.layout.research_dir)
    works = (
        [request.work] if request.work is not None else [work.id for work in ctx.repo.list_works()]
    )
    queue = build_inbox(
        staging, ctx.repo, work=request.work, parsed=stored_documents(ctx.repo, works)
    )
    payload = queue.as_dict()
    return ReviewInbox(
        count=int(payload["count"]),
        counts=dict(payload["counts"]),
        items=tuple(payload["items"]),
    )


def compare_field(ctx: CapabilityContext, request: CompareFieldRequest) -> ComparisonView:
    """`synthesis.compare`: one field across the corpus, read off an existing matrix."""
    from research_harness.synthesis.service import SynthesisService

    table = SynthesisService(ctx).compare(request.field, matrix_id=request.matrix_id)
    payload = table.as_dict()
    return ComparisonView(
        matrix=str(table.matrix),
        field=table.field,
        taxonomy=table.taxonomy,
        label_counts=table.label_counts(),
        unclassified=tuple(str(work) for work in table.unclassified),
        rows=tuple(payload.get("rows", ())),
    )


def audit_manuscript_capability(
    ctx: CapabilityContext, request: AuditManuscriptRequest
) -> ManuscriptAuditReport:
    """`manuscript.audit`: audit the manuscript against the accepted graph. Writes nothing.

    With `file` (and optionally a line range) the report covers only that part of the
    manuscript, and only the source artifacts those lines actually depend on are re-parsed.
    """
    return _manuscript(ctx, request).audit(scope=request.scope())


def manuscript_anchors(
    ctx: CapabilityContext, request: ManuscriptProjectRequest
) -> ManuscriptAnchors:
    """`manuscript.anchors`: every stored anchor, with its verdict against the file on disk.

    A read: the verdicts are computed and reported, never recorded. Recording them is
    `manuscript.revalidate`, which is a researcher act because a reworded sentence going
    stale is a change to accepted state (ADR-008).
    """
    service = _manuscript(ctx, request)
    report = service.revalidate(apply=False)
    stored = service.anchors()
    return ManuscriptAnchors(
        count=len(stored),
        anchors=tuple(anchor_summary(anchor) for anchor in stored),
        verdicts=tuple(_anchor_verdict(result) for result in report.results),
    )


def revalidate_manuscript(
    ctx: CapabilityContext, request: RevalidateManuscriptRequest
) -> RevalidationView:
    """`manuscript.revalidate`: re-find every stored anchor and record what it found.

    A moved sentence keeps its anchor and adopts its new lines; a reworded or deleted one
    is written back `stale`/`missing`. Nothing is ever reattached to a sentence the
    researcher did not choose, and nothing is left recorded as `valid` over changed text.
    """
    report = _manuscript(ctx, request).revalidate(apply=not request.dry_run)
    return _revalidation_view(report, dry_run=request.dry_run)


def trace_manuscript(ctx: CapabilityContext, request: TraceManuscriptRequest) -> TraceView:
    """`manuscript.trace`: one sentence down to the exact source spans behind it."""
    from research_harness.manuscript.anchors import anchor_key

    service = _manuscript(ctx, request)
    sentence = service.find_sentence(request.file, request.line)
    anchor = service.anchor_for(sentence)
    if anchor is None:
        return TraceView(
            file=sentence.file, line=sentence.line_start, sentence=sentence.normalized_text
        )
    link = service.trace(request.file, request.line)
    return TraceView(
        file=sentence.file,
        line=sentence.line_start,
        sentence=sentence.normalized_text,
        anchor=anchor_key(anchor),
        claim=str(anchor.claim),
        link=None if link is None else link.model_dump(mode="json"),
    )


def _anchor_verdict(result: Any) -> AnchorVerdict:
    """One `AnchorRevalidation` as the wire sees it."""
    return AnchorVerdict(
        anchor=_anchor_key(result.anchor),
        claim=str(result.anchor.claim),
        file=result.anchor.file,
        line_start=result.anchor.line_start,
        line_end=result.anchor.line_end,
        status=result.status.value,
        similarity=result.similarity,
        reason=result.reason,
        relocated_to=(
            None
            if result.relocated is None
            else (result.relocated.line_start, result.relocated.line_end)
        ),
    )


def _anchor_key(anchor: Any) -> str:
    from research_harness.manuscript.anchors import anchor_key

    return anchor_key(anchor)


def _revalidation_view(report: RevalidationReport, *, dry_run: bool) -> RevalidationView:
    """One `RevalidationReport` as the wire sees it."""
    return RevalidationView(
        dry_run=dry_run,
        checked=len(report.results),
        valid=len(report.valid),
        relocated=len(report.relocated),
        stale=len(report.stale),
        missing=len(report.missing),
        applied=report.applied_keys,
        results=tuple(_anchor_verdict(result) for result in report.results),
        mutations=tuple(MutationResponse.of(item) for item in report.mutations),
    )


def verify_citations(ctx: CapabilityContext, request: ManuscriptProjectRequest) -> BaseModel:
    """`citation.verify`: every `\\cite` key in the manuscript against its bibliography."""
    from research_harness.manuscript.citations import citation_closure

    service = _manuscript(ctx, request)
    bib = service.bibliography()
    if bib is None:
        raise CapabilityError(
            f"citation.verify: no bibliography beside {service.main_path}; "
            "a citation cannot be checked against a file that is not there"
        )
    return citation_closure(service.load_project(), bib)


def get_state_stale(ctx: CapabilityContext, request: StaleStateRequest) -> StaleReport:
    """`state.stale`: the stale set recorded by the last rebuild or mutation (Product 37)."""
    from research_harness.projection.dependencies import load_stale_marks
    from research_harness.projection.schema import create_engine_for

    database = ctx.repo.layout.database_file
    if not database.is_file():
        return StaleReport(count=0, marks=())
    engine = create_engine_for(database)
    try:
        with engine.connect() as connection:
            marks = list(load_stale_marks(connection))
    finally:
        engine.dispose()
    limited = marks[: request.limit]
    return StaleReport(
        count=len(marks),
        marks=tuple(
            StaleBody(
                object_id=mark.object_id,
                reason=mark.reason,
                priority=int(mark.priority),
                source_change=mark.source_change,
            )
            for mark in limited
        ),
    )


def run_status(ctx: CapabilityContext, request: RunStatusRequest) -> RunStatus:
    """`run.status`: the durable record of one workflow run, however long it takes."""
    from research_harness.workspace.repository import ObjectNotFoundError
    from research_harness.workspace.runs import RunNotFoundError, RunStore

    store = RunStore(ctx.repo.layout.research_dir)
    try:
        return _run_view(store.load(request.run_id))
    except RunNotFoundError as exc:
        raise ObjectNotFoundError(f"run.status: {exc}") from exc


def cancel_run(ctx: CapabilityContext, request: CancelRunRequest) -> RunStatus:
    """`run.cancel`: set the durable cancel flag; the engine stops before its next stage."""
    from research_harness.workspace.repository import ObjectNotFoundError
    from research_harness.workspace.runs import RunNotFoundError, RunStore

    store = RunStore(ctx.repo.layout.research_dir)
    try:
        return _run_view(store.request_cancel(request.run_id))
    except RunNotFoundError as exc:
        raise ObjectNotFoundError(f"run.cancel: {exc}") from exc


# -- mutation adapters -------------------------------------------------------


def ingest(ctx: CapabilityContext, request: IngestLocalPdfRequest) -> IngestResponse:
    """`corpus.ingest`: hash, inspect, resolve, and register one local file."""
    from research_harness.capabilities.handlers import ingest_local_pdf

    result = ingest_local_pdf(ctx, request)
    return IngestResponse(
        work=str(result.work),
        version=str(result.version),
        artifact=str(result.artifact),
        created=result.created,
        resolution=result.resolution.outcome.value,
        reasons=tuple(result.resolution.reasons),
        mutation=None if result.mutation is None else MutationResponse.of(result.mutation),
    )


def parse(ctx: CapabilityContext, request: ParseWorkRequest) -> ParseResponse:
    """`work.parse`: parse a Work's artifact into blocks and store them."""
    from research_harness.capabilities.handlers import parse_work

    result = parse_work(ctx, request)
    return ParseResponse(
        work=str(result.work),
        artifact=str(result.artifact),
        parser=f"{result.document.parser_name}@{result.document.parser_version}",
        pages=result.page_count,
        blocks=len(result.blocks),
        mutation=MutationResponse.of(result.mutation),
    )


def discover_corpus(ctx: CapabilityContext, request: DiscoverCorpusRequest) -> MutationResponse:
    """`corpus.search`: search the configured external sources and record the run.

    The provider registry is built here from the process environment, never from a
    workspace file (Product 34), and under the project's privacy policy, so a source this
    project forbids is refused during selection rather than called. Nothing external is
    written; the local write is the `SearchRun` the service records through
    `search_run.record`, which is what makes the operation reproducible.
    """
    import os

    from research_harness.discovery.search_runs import DiscoveryService
    from research_harness.privacy.policy import load_policy
    from research_harness.providers.search import build_search_registry
    from research_harness.providers.search.base import SearchQuery

    registry = build_search_registry(os.environ, policy=load_policy(ctx.repo))
    service = DiscoveryService(ctx, registry)
    _, mutation = service.run_search(
        request.question,
        SearchQuery(text=request.query, year_from=request.year_from),
        sources=list(request.sources) or None,
        max_pages=request.max_pages,
        cutoff=request.cutoff,
        research_question=request.research_question,
        reproduces=request.reproduces,
    )
    return MutationResponse.of(mutation)


def update_work_metadata(
    ctx: CapabilityContext, request: UpdateWorkMetadataRequest
) -> WorkMetadataUpdate:
    """`work.update_metadata`: fill a Work's empty or undecodable bibliographic fields.

    Discovery routinely finds better metadata than the corpus holds - the right authors,
    the right venue, the right year - and the harness used to throw it away on a
    `same_work` resolution (dogfood F5). Filling is safe and silent discarding is not, so
    the rule here is: fill what is empty or unreadable, *record* what disagrees, and change
    a decodable existing value only when the caller asked for it. Every conflict reaches
    both the response and the event payload, so a value that was overwritten is never
    overwritten quietly (Product 13, ADR-008).
    """
    from research_harness.capabilities.diff import semantic_diff
    from research_harness.capabilities.dto import ValidationReport
    from research_harness.capabilities.handlers import _apply, _event, _require
    from research_harness.workspace.repository import WorkspaceTransaction

    capability = UPDATE_METADATA_CAPABILITY
    if not ctx.is_human:
        # Refused in the handler, not only in the registry: `discovery.apply_enrichments`
        # calls this by name out of `CAPABILITY_HANDLERS`, so the check has to sit where
        # every caller passes through it (ADR-007).
        raise AuthorityError(
            f"{capability}: only a human actor may change a Work's bibliographic record; "
            f"{ctx.actor!r} is not one"
        )
    work = _require(lambda: ctx.repo.get_work(request.work), capability)
    updates, unchanged, conflicts = _metadata_decision(work, request)
    if not updates:
        return WorkMetadataUpdate(
            work=str(work.id), unchanged=tuple(unchanged), conflicts=tuple(conflicts)
        )

    updated = work.touch(**updates)
    event = _event(
        ctx,
        ResearchEventType.WORK_METADATA_UPDATED,
        subjects=(work.id,),
        summary=f"updated metadata of {work.id}: {', '.join(sorted(updates))}",
        payload={
            "fields": ", ".join(sorted(updates)),
            "overwrite": request.overwrite,
            "conflicts": ", ".join(
                f"{item.field}({item.current!r} vs {item.proposed!r})" for item in conflicts
            )
            or None,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(updated)
        return (str(updated.id),)

    mutation = _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(work, updated),
        validation=ValidationReport.of(
            warnings=tuple(
                f"{item.field}: {item.current!r} disagrees with {item.proposed!r} from "
                f"{item.source}" + ("; overwritten as asked" if item.applied else "; kept")
                for item in conflicts
            )
        ),
        changed_ids=(str(updated.id),),
        write=write,
    )
    return WorkMetadataUpdate(
        work=str(updated.id),
        updated=tuple(sorted(updates)),
        unchanged=tuple(unchanged),
        conflicts=tuple(conflicts),
        mutation=MutationResponse.of(mutation),
    )


def _metadata_decision(
    work: Work, request: UpdateWorkMetadataRequest
) -> tuple[dict[str, Any], list[str], list[MetadataConflict]]:
    """Which fields this update writes, which it leaves, and which of them disagreed."""
    updates: dict[str, Any] = {}
    unchanged: list[str] = []
    conflicts: list[MetadataConflict] = []

    def decide(field: str, current: Any, proposed: IdentifierField | None, value: Any) -> None:
        if proposed is None:
            return
        if _is_absent(current) or not _is_decodable(current):
            updates[field] = value
            return
        if _same_metadata(current, value):
            unchanged.append(field)
            return
        conflicts.append(
            MetadataConflict(
                field=field,
                current=_render(current),
                proposed=proposed.value,
                source=proposed.source.value,
                applied=request.overwrite,
            )
        )
        if request.overwrite:
            updates[field] = value
        else:
            unchanged.append(field)

    decide("title", work.title, request.title, request.title.value if request.title else None)
    decide(
        "authors",
        work.authors,
        request.authors[0] if request.authors else None,
        tuple(item.value for item in request.authors or ()),
    )
    decide("year", work.year, request.year, _year_of(request.year))
    decide("venue", work.venue, request.venue, request.venue.value if request.venue else None)
    if request.identifiers is not None:
        merged, id_conflicts = _merge_identifiers(
            work.identifiers, request.identifiers, overwrite=request.overwrite
        )
        conflicts.extend(id_conflicts)
        if merged != work.identifiers:
            updates["identifiers"] = merged
        else:
            unchanged.append("identifiers")
    return updates, unchanged, conflicts


def _merge_identifiers(
    current: WorkIdentifiers, proposed: WorkIdentifiers, *, overwrite: bool
) -> tuple[WorkIdentifiers, list[MetadataConflict]]:
    """External identifiers merged field by field; an existing one is never dropped."""
    merged: dict[str, IdentifierField | None] = {}
    conflicts: list[MetadataConflict] = []
    for name in WorkIdentifiers.model_fields:
        here: IdentifierField | None = getattr(current, name)
        there: IdentifierField | None = getattr(proposed, name)
        if there is None or (here is not None and here.value == there.value):
            merged[name] = here
            continue
        if here is None:
            merged[name] = there
            continue
        conflicts.append(
            MetadataConflict(
                field=f"identifiers.{name}",
                current=here.value,
                proposed=there.value,
                source=there.source.value,
                applied=overwrite,
            )
        )
        merged[name] = there if overwrite else here
    return WorkIdentifiers(**merged), conflicts


def _is_absent(value: Any) -> bool:
    """True when a field holds nothing: None, an empty string, or an empty tuple."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, tuple):
        return not value
    return False


def _is_decodable(value: Any) -> bool:
    """True when text is readable enough to be worth keeping over a candidate's value.

    A `Work` whose authors read ``ORVH\x10GRPDLQ`` holds a font artefact, not a record: the
    parser's own quality judgement decides, so "undecodable" means one thing across the
    product. Non-text fields are always decodable - a year is a number or it is absent.
    """
    from research_harness.parsing.quality import assess_text

    texts = [value] if isinstance(value, str) else list(value) if isinstance(value, tuple) else []
    if not texts:
        return True
    return all(assess_text(str(text)).decodable for text in texts)


def _same_metadata(current: Any, proposed: Any) -> bool:
    """True when the proposed value says the same thing the Work already records."""
    if isinstance(current, tuple) and isinstance(proposed, tuple):
        return tuple(str(item).strip() for item in current) == tuple(
            str(item).strip() for item in proposed
        )
    if isinstance(current, str) and isinstance(proposed, str):
        return current.strip().casefold() == proposed.strip().casefold()
    return bool(current == proposed)


def _render(value: Any) -> str:
    """One metadata value as the conflict record shows it."""
    if isinstance(value, tuple):
        return "; ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _year_of(field: IdentifierField | None) -> int | None:
    """A candidate year as an integer, or a refusal naming what could not be read."""
    if field is None:
        return None
    try:
        return int(field.value.strip())
    except ValueError as exc:
        raise CapabilityError(
            f"{UPDATE_METADATA_CAPABILITY}: {field.value!r} is not a publication year"
        ) from exc


def screen_candidate(ctx: CapabilityContext, request: ScreenCandidateRequest) -> MutationResponse:
    """`corpus.screen`: include or exclude one discovery candidate, with its reason."""
    from research_harness.discovery.screening import screen

    _, mutation = screen(ctx, request.search_run, request.key, request.state, reason=request.reason)
    return MutationResponse.of(mutation)


def resolve_question(ctx: CapabilityContext, request: ResolveQuestionRequest) -> MutationResponse:
    """`question.resolve`: mark a question answered and capture the answer as a note."""
    from research_harness.research.questions import QuestionService

    _, mutation = QuestionService(ctx).resolve(request.question_id, request.answer)
    return MutationResponse.of(mutation)


def discard_note_mutation(ctx: CapabilityContext, request: DiscardNoteRequest) -> MutationResult:
    """The `note.discard` mutation itself, so `research/` never opens its own transaction.

    A note has no accepted authority to withdraw, so the only rule is the domain's:
    `transitions.discard_note` refuses anything that is not still captured, and
    `discarded` is terminal. `NoteService.discard` calls this and adds nothing.
    """
    from research_harness.capabilities.diff import semantic_diff
    from research_harness.capabilities.dto import ValidationReport
    from research_harness.capabilities.handlers import _apply, _event
    from research_harness.domain.transitions import discard_note as discard_note_transition
    from research_harness.workspace.events import digest_key
    from research_harness.workspace.repository import WorkspaceTransaction

    capability = DISCARD_CAPABILITY
    note = next(
        (item for item in ctx.repo.iter_notes() if item.key == request.note_key),
        None,
    )
    if note is None:
        raise CapabilityError(f"{capability}: no note {request.note_key!r} in {ctx.root}")
    discarded = discard_note_transition(note, actor=ctx.actor)
    key = digest_key(discarded)
    event = _event(
        ctx,
        ResearchEventType.NOTE_DISCARDED,
        subjects=(),
        summary=f"discarded research note {note.key}",
        payload={"note": request.note_key, "reason": request.reason},
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put_note(discarded)
        return (key,)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(note, discarded, object_id=key),
        validation=ValidationReport(),
        changed_ids=(),
        write=write,
    )


def discard_note(ctx: CapabilityContext, request: DiscardNoteRequest) -> MutationResponse:
    """`note.discard`: retire a captured note; discarded is terminal."""
    return MutationResponse.of(discard_note_mutation(ctx, request))


def supersede_decision(
    ctx: CapabilityContext, request: SupersedeDecisionRequest
) -> MutationResponse:
    """`decision.supersede`: retire an accepted Decision; superseded is terminal.

    Every kind of decision is logged as `decision.superseded`, the taxonomy kind included:
    `taxonomy.revised` names a change to the classification vocabulary itself, which is
    what `taxonomy.put` writes, and retiring the decision behind it is a different fact.
    The transition itself is the domain's (`transition_decision`); nothing about the rule
    lives here.
    """
    from research_harness.capabilities.diff import semantic_diff
    from research_harness.capabilities.dto import ValidationReport
    from research_harness.capabilities.handlers import _apply, _event, _require
    from research_harness.workspace.repository import WorkspaceTransaction

    capability = SUPERSEDE_DECISION_CAPABILITY
    decision = _require(lambda: ctx.repo.get_decision(request.decision_id), capability)
    errors: list[str] = []
    if not request.reason.strip():
        errors.append("superseding a decision requires a reason")
    if request.superseded_by is not None:
        if request.superseded_by == decision.id:
            errors.append(f"{decision.id} cannot supersede itself")
        elif not any(item.id == request.superseded_by for item in ctx.repo.list_decisions()):
            errors.append(f"no decision {request.superseded_by} in this workspace")
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)

    superseded = transition_decision(decision, DecisionStatus.SUPERSEDED, actor=ctx.actor)
    event = _event(
        ctx,
        ResearchEventType.DECISION_SUPERSEDED,
        subjects=(decision.id,),
        summary=f"superseded decision {decision.id}",
        payload={
            "transition": "superseded",
            "reason": request.reason,
            "superseded_by": None if request.superseded_by is None else str(request.superseded_by),
            "decision_type": decision.type.value,
            "previous_status": decision.status.value,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(superseded)
        return (str(superseded.id),)

    result: MutationResult = _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(decision, superseded),
        validation=validation,
        changed_ids=(str(superseded.id),),
        write=write,
    )
    return MutationResponse.of(result)


def accept_batch(ctx: CapabilityContext, request: AcceptBatchRequest) -> BatchAcceptResponse:
    """`review.accept_batch`: the Product 24.4 policy batch, refused under strict policy."""
    result = _review_service(ctx).accept_batch(work=request.work, dry_run=request.dry_run)
    return BatchAcceptResponse(
        dry_run=result.dry_run,
        accepted=tuple(result.accepted),
        skipped=dict(result.skipped),
        mutations=tuple(MutationResponse.of(item) for item in result.mutations),
    )


def resolve_conflict(ctx: CapabilityContext, request: ResolveConflictRequest) -> ConflictResolution:
    """`review.resolve_conflict`: a person's answer to a conflict, never a heuristic's.

    The three choices are the same three review actions `review.accept`, `review.reject`,
    and `review.defer` take, reached through the same `EvidenceReviewService` methods; the
    only thing this capability adds is closing the materialized conflict record with the
    researcher's reason. Two names for one path, never two paths.
    """
    mutation = _review_service(ctx).resolve_conflict(
        request.candidate_id, request.choice, request.reason
    )
    return ConflictResolution(
        candidate_id=request.candidate_id,
        choice=request.choice,
        mutation=None if mutation is None else MutationResponse.of(mutation),
    )


# -- the candidate-keyed review actions --------------------------------------


def review_accept(ctx: CapabilityContext, request: CandidateReviewRequest) -> ReviewOutcome:
    """`review.accept`: accept one staged candidate as canonical Evidence."""
    service = _review_service(ctx)
    return _review_outcome(
        service, request.candidate_id, ReviewAction.ACCEPT, service.accept(request.candidate_id)
    )


def review_qualify(ctx: CapabilityContext, request: QualifyCandidateRequest) -> ReviewOutcome:
    """`review.qualify`: accept one candidate with the condition it holds under (24.3)."""
    service = _review_service(ctx)
    action = ReviewAction.ACCEPT_WITH_QUALIFICATION
    result = service.accept(
        request.candidate_id, action=action, qualification=request.qualification
    )
    return _review_outcome(service, request.candidate_id, action, result)


def review_edit(ctx: CapabilityContext, request: EditCandidateRequest) -> ReviewOutcome:
    """`review.edit`: accept the researcher's corrected Evidence for one candidate."""
    service = _review_service(ctx)
    result = service.accept(request.candidate_id, action=ReviewAction.EDIT, edited=request.edited)
    return _review_outcome(service, request.candidate_id, ReviewAction.EDIT, result)


def review_reject(ctx: CapabilityContext, request: RejectCandidateRequest) -> ReviewOutcome:
    """`review.reject`: refuse one candidate; the refusal is canonical, the Evidence is not."""
    service = _review_service(ctx)
    result = service.reject(request.candidate_id, request.reason)
    return _review_outcome(service, request.candidate_id, ReviewAction.REJECT, result)


def review_defer(ctx: CapabilityContext, request: DeferCandidateRequest) -> ReviewOutcome:
    """`review.defer`: put one candidate aside without deciding it; staging only."""
    service = _review_service(ctx)
    candidate = service.defer(request.candidate_id, request.note)
    return ReviewOutcome(
        candidate_id=request.candidate_id,
        action=ReviewAction.DEFER.value,
        status=candidate.status.value,
    )


def review_request_more(
    ctx: CapabilityContext, request: RequestMoreEvidenceRequest
) -> ReviewOutcome:
    """`review.request_more`: ask for more evidence; the question becomes a durable note."""
    service = _review_service(ctx)
    mutation = service.request_more_evidence(request.candidate_id, request.note)
    return ReviewOutcome(
        candidate_id=request.candidate_id,
        action=ReviewAction.REQUEST_MORE_EVIDENCE.value,
        status=service.staging.get(request.candidate_id).status.value,
        mutation=MutationResponse.of(mutation),
    )


def review_split(ctx: CapabilityContext, request: SplitCandidateRequest) -> SplitOutcome:
    """`review.split`: accept the source fact and route its interpretation separately."""
    from research_harness.domain.evidence import Interpretation
    from research_harness.evidence.staging import PROVISIONAL_EVIDENCE_ID

    service = _review_service(ctx)
    candidate = service.staging.get(request.candidate_id)
    interpretation = (
        None
        if request.interpretation is None
        else Interpretation(
            id=InterpretationId.make(0),
            evidence=(PROVISIONAL_EVIDENCE_ID,),
            text=request.interpretation,
            origin=request.interpretation_origin,
            provenance=actor_provenance(ctx.actor, workflow="review"),
        )
    )
    outcome = service.split_accept(
        request.candidate_id,
        fact=request.fact if request.fact is not None else candidate.evidence,
        interpretation=interpretation,
        reject_interpretation_reason=request.reject_interpretation_reason,
    )
    reviewed = service.staging.get(request.candidate_id)
    return SplitOutcome(
        candidate_id=request.candidate_id,
        action=(reviewed.review_action or ReviewAction.ACCEPT).value,
        status=reviewed.status.value,
        evidence=str(outcome.evidence),
        interpretation_candidate=outcome.interpretation_candidate,
        mutation=MutationResponse.of(outcome.accepted),
        rejected=None if outcome.rejected is None else MutationResponse.of(outcome.rejected),
    )


def _review_outcome(
    service: EvidenceReviewService,
    candidate_id: str,
    action: ReviewAction,
    result: MutationResult,
) -> ReviewOutcome:
    """One review action's answer, read back off staging so the queue state is not guessed."""
    evidence = result.objects[0] if result.objects else None
    return ReviewOutcome(
        candidate_id=candidate_id,
        action=action.value,
        status=service.staging.get(candidate_id).status.value,
        evidence=evidence if action is not ReviewAction.REJECT else None,
        mutation=MutationResponse.of(result),
    )


def draft_section_capability(ctx: CapabilityContext, request: DraftSectionRequest) -> BaseModel:
    """`manuscript.draft`: draft a section from accepted Claims into `.research/staging`."""
    from research_harness.manuscript.draft import draft_section

    return draft_section(
        ctx,
        request.purpose,
        claims=list(request.claims),
        provider=_model_provider(ctx, request.provider),
        style=request.style,
    )


def rebuild_state(ctx: CapabilityContext, request: RebuildStateRequest) -> RebuildResponse:
    """`state.rebuild`: rebuild `.research/research.db`; never writes canonical state."""
    del request
    from research_harness.projection.rebuild import rebuild_workspace

    report = rebuild_workspace(ctx.repo)
    return RebuildResponse(
        ok=report.ok,
        objects=report.objects,
        objects_by_type=dict(report.objects_by_type),
        stale_marks=report.stale_marks,
        fts_rows=report.fts_rows,
        canonical_digest=str(report.canonical_digest),
        duration_ms=report.duration_ms,
        invalid_files=tuple(
            {"path": invalid.path, "error": invalid.error} for invalid in report.invalid_files
        ),
        summary=report.summary(),
    )


# -- long-running capabilities -----------------------------------------------


def interrogate_work(ctx: CapabilityContext, request: InterrogateWorkRequest) -> RunStarted:
    """`work.interrogate` / `evidence.extract`: start an interrogation, return its run id.

    The run record is durable before this returns, so the caller never has to hold a
    connection open (ADR-009); the stages execute on a worker thread and their answers land
    in staging, where the Review Inbox picks them up.
    """
    from research_harness.evidence.interrogation import DEFAULT_SCHEMA
    from research_harness.evidence.staging import StagingStore
    from research_harness.workflows.interrogate import DocumentSource, build_interrogate_workflow

    staging = StagingStore(ctx.repo.layout.research_dir)
    provider = _router(ctx, request.provider)
    fields = list(request.fields) or None
    workflow = build_interrogate_workflow(
        DEFAULT_SCHEMA,
        fields,
        document=DocumentSource(ctx.repo, request.work, request.artifact),
        provider=provider,
        staging=staging,
    )
    selected = [item.name for item in DEFAULT_SCHEMA.select(fields)]
    inputs: dict[str, Any] = {
        "work": str(request.work),
        "artifact": None if request.artifact is None else str(request.artifact),
        "schema": f"{DEFAULT_SCHEMA.name}@{DEFAULT_SCHEMA.version}",
        "schema_fingerprint": DEFAULT_SCHEMA.fingerprint(),
        "fields": selected,
    }
    return _start_in_background(ctx, "work.interrogate", workflow, inputs)


def verify_evidence(ctx: CapabilityContext, request: VerifyEvidenceRequest) -> RunStarted:
    """`evidence.verify`: start verification of staged candidates, return its run id."""
    from research_harness.evidence.staging import StagingStore
    from research_harness.workflows.interrogate import DocumentSource
    from research_harness.workflows.verify import build_verify_workflow

    staging = StagingStore(ctx.repo.layout.research_dir)
    wanted = set(request.candidates)
    pending = [
        candidate
        for candidate in staging.list(work=request.work)
        if (not wanted or candidate.candidate_id in wanted)
        and (candidate.verification is None or request.force)
    ]
    workflow = build_verify_workflow(
        pending,
        document=DocumentSource(ctx.repo, request.work, None),
        provider=_router(ctx, request.provider),
        staging=staging,
    )
    inputs: dict[str, Any] = {
        "work": str(request.work),
        "artifact": None,
        "candidates": [candidate.candidate_id for candidate in pending],
        "neighbors": 1,
    }
    return _start_in_background(ctx, "evidence.verify", workflow, inputs)


def _start_in_background(
    ctx: CapabilityContext, capability: str, workflow: Any, inputs: dict[str, Any]
) -> RunStarted:
    """Persist the run, hand back its id, and execute the stages on a worker thread."""
    from research_harness.workflows.engine import WorkflowEngine
    from research_harness.workspace.runs import RunStore

    engine = WorkflowEngine(RunStore(ctx.repo.layout.research_dir))
    run = engine.start(workflow, inputs)

    def execute() -> None:
        try:
            engine.execute(run.run_id, workflow, inputs)
        except Exception:
            # The engine has already written the failure onto the durable run record, which
            # is what `run.status` reports; letting the exception escape a daemon thread
            # would lose the log line and tell nobody anything.
            logger.exception("%s run %s failed", capability, run.run_id)

    thread = threading.Thread(target=execute, name=f"{capability}:{run.run_id}", daemon=True)
    thread.start()
    return RunStarted(
        run_id=run.run_id,
        capability=capability,
        workflow=run.workflow,
        status=run.status.value,
    )


# -- registration ------------------------------------------------------------


#: Every capability this module implements, name -> handler, declared rather than derived.
#: `capabilities.handlers.CAPABILITY_HANDLERS` merges it, and a contract test checks it
#: against the registry in both directions, so a spec added without a row here (or the
#: other way round) fails rather than quietly leaving the two tables disagreeing.
EXTRA_CAPABILITY_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], Any]] = MappingProxyType(
    {
        "work.get": get_work,
        "claim.find_support": find_support,
        SUPERSEDE_DECISION_CAPABILITY: supersede_decision,
        "run.status": run_status,
        "run.cancel": cancel_run,
        "corpus.ingest": ingest,
        "work.parse": parse,
        UPDATE_METADATA_CAPABILITY: update_work_metadata,
        DISCOVER_CAPABILITY: discover_corpus,
        "corpus.screen": screen_candidate,
        "retrieval.search": search_corpus,
        "retrieval.resolve_source": resolve_source,
        "claim.find_counterevidence": find_counter_evidence,
        "work.interrogate": interrogate_work,
        "evidence.extract": interrogate_work,
        "evidence.verify": verify_evidence,
        "review.inbox": review_inbox,
        "review.accept_batch": accept_batch,
        "review.resolve_conflict": resolve_conflict,
        "review.accept": review_accept,
        "review.qualify": review_qualify,
        "review.edit": review_edit,
        "review.reject": review_reject,
        "review.split": review_split,
        "review.defer": review_defer,
        "review.request_more": review_request_more,
        "question.resolve": resolve_question,
        DISCARD_CAPABILITY: discard_note,
        "synthesis.compare": compare_field,
        "manuscript.draft": draft_section_capability,
        "manuscript.audit": audit_manuscript_capability,
        "manuscript.anchors": manuscript_anchors,
        "manuscript.revalidate": revalidate_manuscript,
        "manuscript.trace": trace_manuscript,
        "citation.verify": verify_citations,
        "state.rebuild": rebuild_state,
        "state.stale": get_state_stale,
        **MANUSCRIPT_WORKSPACE_HANDLERS,
        **CONVERSATION_CAPABILITY_HANDLERS,
        **PROVIDER_CAPABILITY_HANDLERS,
        **ATTACHMENT_CAPABILITY_HANDLERS,
        **GRAPH_CAPABILITY_HANDLERS,
        **READ_CAPABILITY_HANDLERS,
    }
)


def register_into(registry: CapabilityRegistry) -> None:
    """Register every capability whose service is part of this build; plan the rest.

    A section whose module cannot be imported contributes nothing rather than a stub, and
    each of its names is recorded as planned with the import error that explains it.
    """
    for names, build in _SECTIONS:
        try:
            specs = build()
        except ImportError as exc:  # pragma: no cover - only when a package is absent
            logger.warning("capabilities %s unavailable: %s", ", ".join(names), exc)
            for name in names:
                registry.plan(name, f"unavailable in this build: {exc}")
            continue
        registry.register_all(specs)


def _spec(
    name: str,
    *,
    summary: str,
    semantics: str,
    permission: Permission,
    request_model: type[BaseModel],
    response_model: type[BaseModel],
    handler: Callable[[CapabilityContext, Any], BaseModel],
    human_only: bool = False,
    long_running: bool = False,
) -> CapabilitySpec:
    """One capability spec, spelled out so the table below reads as a table."""
    return CapabilitySpec(
        name=name,
        summary=summary,
        permission=permission,
        scientific_semantics=semantics,
        request_model=request_model,
        response_model=response_model,
        handler=handler,
        human_only=human_only,
        long_running=long_running,
    )


def _workspace_specs() -> list[CapabilitySpec]:
    """Capabilities that need nothing but the workspace repository."""
    return [
        _spec(
            "work.get",
            summary="Read one Work with its versions, artifacts, and derived counts.",
            semantics="reads corpus state; changes nothing",
            permission=Permission.READ,
            request_model=GetWorkRequest,
            response_model=WorkView,
            handler=get_work,
        ),
        _spec(
            "claim.find_support",
            summary="The evidence a Claim records, resolved, grouped by relation.",
            semantics="reads claim-evidence relations; changes nothing",
            permission=Permission.READ,
            request_model=FindSupportRequest,
            response_model=ClaimSupport,
            handler=find_support,
        ),
        _spec(
            SUPERSEDE_DECISION_CAPABILITY,
            summary="Retire an accepted Decision, optionally naming its replacement.",
            semantics="moves a Decision to superseded; the record of the choice stays",
            permission=Permission.MUTATE,
            request_model=SupersedeDecisionRequest,
            response_model=MutationResponse,
            handler=supersede_decision,
            human_only=True,
        ),
        _spec(
            "run.status",
            summary="The durable record of one long-running workflow run.",
            semantics="reads regenerable run state; changes nothing",
            permission=Permission.READ,
            request_model=RunStatusRequest,
            response_model=RunStatus,
            handler=run_status,
        ),
        _spec(
            "run.cancel",
            summary="Ask a running workflow to stop before its next stage.",
            semantics="sets a durable cancel flag on regenerable run state",
            permission=Permission.STAGE,
            request_model=CancelRunRequest,
            response_model=RunStatus,
            handler=cancel_run,
        ),
    ]


def _ingest_specs() -> list[CapabilitySpec]:
    """Corpus capabilities; the ingest service pulls in a PDF parser."""
    import research_harness.ingest.service  # noqa: F401 - probes the optional dependency

    return [
        _spec(
            "corpus.ingest",
            summary="Register a local file as an immutable Artifact of a Work.",
            semantics="creates Work/Version/Artifact identity from a file; proposes no evidence",
            permission=Permission.MUTATE,
            request_model=IngestLocalPdfRequest,
            response_model=IngestResponse,
            handler=ingest,
        ),
        _spec(
            "work.parse",
            summary="Parse a Work's artifact into structural blocks and store them.",
            semantics="stores a derived parse so anchors resolve; changes no evidence",
            permission=Permission.MUTATE,
            request_model=ParseWorkRequest,
            response_model=ParseResponse,
            handler=parse,
        ),
        _spec(
            UPDATE_METADATA_CAPABILITY,
            summary="Fill a Work's empty or undecodable bibliographic fields, with provenance.",
            semantics=(
                "fills missing corpus metadata and records every disagreement; a decodable "
                "existing value is never overwritten unless the researcher asks"
            ),
            permission=Permission.MUTATE,
            request_model=UpdateWorkMetadataRequest,
            response_model=WorkMetadataUpdate,
            handler=update_work_metadata,
            human_only=True,
        ),
    ]


def _discovery_specs() -> list[CapabilitySpec]:
    """External discovery and the screening decision that follows it."""
    import research_harness.discovery.screening
    import research_harness.discovery.search_runs
    import research_harness.providers.search  # noqa: F401 - probes the optional dependency

    return [
        _spec(
            DISCOVER_CAPABILITY,
            summary="Search the configured external sources and record the run.",
            semantics=(
                "reads external catalogues and writes nothing to them; records the SearchRun "
                "that makes the operation reproducible, and adds nothing to the corpus"
            ),
            permission=Permission.MUTATE,
            request_model=DiscoverCorpusRequest,
            response_model=MutationResponse,
            handler=discover_corpus,
        ),
        _spec(
            "corpus.screen",
            summary="Include or exclude one discovery candidate, with its reason.",
            semantics="records a screening decision on a SearchRun; acquires no source",
            permission=Permission.MUTATE,
            request_model=ScreenCandidateRequest,
            response_model=MutationResponse,
            handler=screen_candidate,
        ),
    ]


def _retrieval_specs() -> list[CapabilitySpec]:
    """Retrieval reads over the deletable indexes (ADR-006)."""
    from research_harness.retrieval.planner import RetrievalResponse
    from research_harness.retrieval.structured import SourceRef

    return [
        _spec(
            "retrieval.search",
            summary="Search the corpus and accepted state, accepted state first.",
            semantics="reads the deletable indexes; changes nothing",
            permission=Permission.READ,
            request_model=SearchCorpusRequest,
            response_model=RetrievalResponse,
            handler=search_corpus,
        ),
        _spec(
            "retrieval.resolve_source",
            summary="Reopen a reference at its exact source location.",
            semantics="reads a source anchor; changes nothing",
            permission=Permission.READ,
            request_model=ResolveSourceRequest,
            response_model=SourceRef,
            handler=resolve_source,
        ),
        _spec(
            "claim.find_counterevidence",
            summary="Retrieval proposals that might bear against a Claim.",
            semantics="proposes places to look; creates no Evidence and no relation",
            permission=Permission.READ,
            request_model=FindCounterEvidenceRequest,
            response_model=CounterEvidenceReport,
            handler=find_counter_evidence,
        ),
    ]


def _workflow_specs() -> list[CapabilitySpec]:
    """The long-running capabilities: they return a durable run id, never a held connection."""
    import research_harness.workflows.interrogate
    import research_harness.workflows.verify  # noqa: F401 - probes the optional dependency

    staged = "stages evidence candidates under .research/staging; accepts nothing"
    return [
        _spec(
            "work.interrogate",
            summary="Ask a Work the interrogation schema's questions; returns a run id.",
            semantics=staged,
            permission=Permission.STAGE,
            request_model=InterrogateWorkRequest,
            response_model=RunStarted,
            handler=interrogate_work,
            long_running=True,
        ),
        _spec(
            "evidence.extract",
            summary="Extract evidence for a Work's fields; the interrogation run, by field.",
            semantics=staged,
            permission=Permission.STAGE,
            request_model=InterrogateWorkRequest,
            response_model=RunStarted,
            handler=interrogate_work,
            long_running=True,
        ),
        _spec(
            "evidence.verify",
            summary="Re-read the source for staged candidates; returns a run id.",
            semantics="writes verification verdicts onto staged candidates; accepts nothing",
            permission=Permission.STAGE,
            request_model=VerifyEvidenceRequest,
            response_model=RunStarted,
            handler=verify_evidence,
            long_running=True,
        ),
    ]


def _review_specs() -> list[CapabilitySpec]:
    """The Review Inbox and the two batch/conflict actions a researcher takes from it."""
    import research_harness.evidence.service  # noqa: F401 - probes the optional dependency

    return [
        _spec(
            "review.inbox",
            summary="The review queue, in Product 24.2 priority order.",
            semantics="reads staged candidates and their conflicts; accepts nothing",
            permission=Permission.READ,
            request_model=ReviewInboxRequest,
            response_model=ReviewInbox,
            handler=review_inbox,
        ),
        _spec(
            "review.accept_batch",
            summary="Accept every candidate meeting the Product 24.4 batch conditions.",
            semantics=(
                "creates accepted Evidence for candidates meeting deterministic conditions; "
                "requires a human actor and a permitting policy"
            ),
            permission=Permission.MUTATE,
            request_model=AcceptBatchRequest,
            response_model=BatchAcceptResponse,
            handler=accept_batch,
            human_only=True,
        ),
        _spec(
            "review.resolve_conflict",
            summary="Resolve a conflicting proposal the researcher's way.",
            semantics="accepts, rejects, or defers one candidate; the reason is recorded",
            permission=Permission.MUTATE,
            request_model=ResolveConflictRequest,
            response_model=ConflictResolution,
            handler=resolve_conflict,
            human_only=True,
        ),
        _spec(
            "review.accept",
            summary="Accept one staged candidate, named by its staging id.",
            semantics=(
                "creates accepted Evidence from a staged candidate and marks the candidate "
                "reviewed; requires a human actor"
            ),
            permission=Permission.MUTATE,
            request_model=CandidateReviewRequest,
            response_model=ReviewOutcome,
            handler=review_accept,
            human_only=True,
        ),
        _spec(
            "review.qualify",
            summary="Accept one candidate with the condition it holds under.",
            semantics=(
                "creates accepted Evidence carrying a qualification; requires a human actor"
            ),
            permission=Permission.MUTATE,
            request_model=QualifyCandidateRequest,
            response_model=ReviewOutcome,
            handler=review_qualify,
            human_only=True,
        ),
        _spec(
            "review.edit",
            summary="Accept the researcher's corrected Evidence for one candidate.",
            semantics=(
                "creates accepted Evidence from corrected content; the source anchor may "
                "never move, and it requires a human actor"
            ),
            permission=Permission.MUTATE,
            request_model=EditCandidateRequest,
            response_model=ReviewOutcome,
            handler=review_edit,
            human_only=True,
        ),
        _spec(
            "review.reject",
            summary="Refuse one candidate, with the reason recorded beside the corpus.",
            semantics=(
                "records a refusal so the same proposal is recognised again; creates no "
                "Evidence and requires a human actor"
            ),
            permission=Permission.MUTATE,
            request_model=RejectCandidateRequest,
            response_model=ReviewOutcome,
            handler=review_reject,
            human_only=True,
        ),
        _spec(
            "review.defer",
            summary="Put one candidate aside; it stays in the queue.",
            semantics="records the researcher's note on a staged candidate; accepts nothing",
            permission=Permission.STAGE,
            request_model=DeferCandidateRequest,
            response_model=ReviewOutcome,
            handler=review_defer,
            human_only=True,
        ),
        _spec(
            "review.split",
            summary="Accept the source fact and deal with its interpretation separately.",
            semantics=(
                "creates exactly one accepted Evidence for the source half of a candidate "
                "and stages or refuses the interpretation half; requires a human actor"
            ),
            permission=Permission.MUTATE,
            request_model=SplitCandidateRequest,
            response_model=SplitOutcome,
            handler=review_split,
            human_only=True,
        ),
        _spec(
            "review.request_more",
            summary="Ask for more evidence; the question is captured as a durable note.",
            semantics=(
                "records the request on the staged candidate and captures it as a "
                "low-authority note; accepts nothing"
            ),
            permission=Permission.STAGE,
            request_model=RequestMoreEvidenceRequest,
            response_model=ReviewOutcome,
            handler=review_request_more,
            human_only=True,
        ),
    ]


def _research_specs() -> list[CapabilitySpec]:
    """Questions and notes, delegating to the services that own their rules."""
    import research_harness.research.notes
    import research_harness.research.questions  # noqa: F401 - probes the optional dependency

    return [
        _spec(
            "question.resolve",
            summary="Answer a research question and capture the answer as a note.",
            semantics="moves a ResearchQuestion to answered; writes no evidence",
            permission=Permission.MUTATE,
            request_model=ResolveQuestionRequest,
            response_model=MutationResponse,
            handler=resolve_question,
        ),
        _spec(
            DISCARD_CAPABILITY,
            summary="Retire a captured note; discarded is terminal.",
            semantics="ends a note's life; nothing downstream moves",
            permission=Permission.MUTATE,
            request_model=DiscardNoteRequest,
            response_model=MutationResponse,
            handler=discard_note,
            human_only=True,
        ),
    ]


def _synthesis_specs() -> list[CapabilitySpec]:
    """Reading a synthesis matrix back out; writing one is `synthesis.build_matrix`."""
    import research_harness.synthesis.service  # noqa: F401 - probes the optional dependency

    return [
        _spec(
            "synthesis.compare",
            summary="One field across the corpus, as a comparison table.",
            semantics="reads an existing synthesis matrix; proposes no classification",
            permission=Permission.READ,
            request_model=CompareFieldRequest,
            response_model=ComparisonView,
            handler=compare_field,
        )
    ]


def _manuscript_specs() -> list[CapabilitySpec]:
    """Manuscript reads and the drafting capability, which writes only into staging."""
    from research_harness.manuscript.audit import ManuscriptAuditReport
    from research_harness.manuscript.citations import CitationClosureReport
    from research_harness.manuscript.draft import DraftCandidate

    return [
        _spec(
            "manuscript.draft",
            summary="Draft a section from named accepted Claims, into staging.",
            semantics=(
                "writes a draft candidate under .research/staging; the manuscript is untouched"
            ),
            permission=Permission.STAGE,
            request_model=DraftSectionRequest,
            response_model=DraftCandidate,
            handler=draft_section_capability,
        ),
        _spec(
            "manuscript.audit",
            summary="Audit the manuscript against the accepted research graph.",
            semantics="reports findings; repairs nothing and writes nothing",
            permission=Permission.READ,
            request_model=AuditManuscriptRequest,
            response_model=ManuscriptAuditReport,
            handler=audit_manuscript_capability,
        ),
        _spec(
            "manuscript.anchors",
            summary="Every stored anchor, with its verdict against the manuscript on disk.",
            semantics="reads anchors and computes their verdicts; records none of them",
            permission=Permission.READ,
            request_model=ManuscriptProjectRequest,
            response_model=ManuscriptAnchors,
            handler=manuscript_anchors,
        ),
        _spec(
            "manuscript.revalidate",
            summary="Re-find every stored anchor and record what the manuscript now says.",
            semantics=(
                "records anchor relocation and staleness; a reworded sentence goes stale "
                "rather than being reattached, and it requires a human actor"
            ),
            permission=Permission.MUTATE,
            request_model=RevalidateManuscriptRequest,
            response_model=RevalidationView,
            handler=revalidate_manuscript,
            human_only=True,
        ),
        _spec(
            "manuscript.trace",
            summary="One sentence, by file and line, down to its Claim and source spans.",
            semantics="reads the traceability chain; changes nothing",
            permission=Permission.READ,
            request_model=TraceManuscriptRequest,
            response_model=TraceView,
            handler=trace_manuscript,
        ),
        _spec(
            "citation.verify",
            summary="Check every manuscript citation key against the bibliography.",
            semantics="reports missing or unused citation keys; changes nothing",
            permission=Permission.READ,
            request_model=ManuscriptProjectRequest,
            response_model=CitationClosureReport,
            handler=verify_citations,
        ),
    ]


def _state_specs() -> list[CapabilitySpec]:
    """Rebuild and staleness: regenerable state only, never canonical files (ADR-001)."""
    import research_harness.projection.rebuild  # noqa: F401 - probes the optional dependency

    return [
        _spec(
            "state.rebuild",
            summary="Rebuild the deletable projection from canonical files.",
            semantics="rebuilds regenerable state only; canonical files are never written",
            permission=Permission.ADMIN,
            request_model=RebuildStateRequest,
            response_model=RebuildResponse,
            handler=rebuild_state,
        ),
        _spec(
            "state.stale",
            summary="What is out of date, highest scientific impact first.",
            semantics="reads recorded stale marks; recomputes and rewrites nothing",
            permission=Permission.READ,
            request_model=StaleStateRequest,
            response_model=StaleReport,
            handler=get_state_stale,
        ),
    ]


def _claim_relation_specs() -> list[CapabilitySpec]:
    """The claim relation and supersession handlers, when this build carries them."""
    from research_harness.capabilities import claims_ext
    from research_harness.capabilities.registry import mutation_spec

    handlers = claims_ext.CLAIM_EXTENSION_HANDLERS
    return [
        mutation_spec(
            claims_ext.RELATE_CAPABILITY,
            summary="Link one evidence object to a Claim under a relation and aspect.",
            semantics="adds one claim-evidence edge; never rewrites the claim's assessment",
            request_model=claims_ext.RelateClaimEvidenceRequest,
            handlers=handlers,
        ),
        mutation_spec(
            claims_ext.UNRELATE_CAPABILITY,
            summary="Remove exactly one claim-evidence edge.",
            semantics="drops one claim-evidence edge; the assessment is left as it was",
            request_model=claims_ext.UnrelateClaimEvidenceRequest,
            handlers=handlers,
        ),
        mutation_spec(
            claims_ext.SUPERSEDE_CAPABILITY,
            summary="Retire a Claim, optionally naming the claim that replaces it.",
            semantics="moves a Claim to superseded, which is terminal; human-only",
            request_model=claims_ext.SupersedeClaimRequest,
            human_only=True,
            handlers=handlers,
        ),
        mutation_spec(
            claims_ext.UPDATE_COVERAGE_CAPABILITY,
            summary="Record the search coverage a Claim's scope rests on.",
            semantics=(
                "writes the deterministic discovery funnel onto a Claim; the audit reads it "
                "and no model contributes to it"
            ),
            request_model=claims_ext.UpdateClaimCoverageRequest,
            handlers=handlers,
        ),
    ]


def _attachment_specs() -> list[CapabilitySpec]:
    """The `attachment.*` capabilities; the service reads PDFs and images (design §2, §6)."""
    return attachment_specs()


#: Each section names the capabilities it contributes, so a missing package turns into
#: planned names rather than an import error at daemon start.
_SECTIONS: tuple[tuple[tuple[str, ...], Callable[[], list[CapabilitySpec]]], ...] = (
    (GRAPH_CAPABILITIES, graph_specs),
    (ATTACHMENT_CAPABILITIES, _attachment_specs),
    (
        (
            "work.get",
            "claim.find_support",
            SUPERSEDE_DECISION_CAPABILITY,
            "run.status",
            "run.cancel",
        ),
        _workspace_specs,
    ),
    (("corpus.ingest", "work.parse", UPDATE_METADATA_CAPABILITY), _ingest_specs),
    ((DISCOVER_CAPABILITY, "corpus.screen"), _discovery_specs),
    (
        ("retrieval.search", "retrieval.resolve_source", "claim.find_counterevidence"),
        _retrieval_specs,
    ),
    (("work.interrogate", "evidence.extract", "evidence.verify"), _workflow_specs),
    (
        (
            "review.inbox",
            "review.accept_batch",
            "review.resolve_conflict",
            "review.accept",
            "review.qualify",
            "review.edit",
            "review.reject",
            "review.split",
            "review.defer",
            "review.request_more",
        ),
        _review_specs,
    ),
    (("question.resolve", DISCARD_CAPABILITY), _research_specs),
    (("synthesis.compare",), _synthesis_specs),
    (
        (
            "manuscript.draft",
            "manuscript.audit",
            "manuscript.anchors",
            "manuscript.revalidate",
            "manuscript.trace",
            "citation.verify",
        ),
        _manuscript_specs,
    ),
    (MANUSCRIPT_WORKSPACE_CAPABILITIES, manuscript_workspace_specs),
    (CONVERSATION_CAPABILITIES, conversation_specs),
    (PROVIDER_CAPABILITIES, provider_specs),
    (("state.rebuild", "state.stale"), _state_specs),
    (
        ("claim.relate", "claim.unrelate", "claim.supersede", "claim.update_coverage"),
        _claim_relation_specs,
    ),
    (tuple(READ_CAPABILITY_HANDLERS), read_specs),
)


# -- helpers -----------------------------------------------------------------


_RELATION_GROUPS: dict[ClaimEvidenceRelationType, str] = {
    ClaimEvidenceRelationType.SUPPORTS: "supporting",
    ClaimEvidenceRelationType.EXEMPLIFIES: "supporting",
    ClaimEvidenceRelationType.QUALIFIES: "qualifying",
    ClaimEvidenceRelationType.CONTEXTUALIZES: "qualifying",
    ClaimEvidenceRelationType.CONTRADICTS: "contradicting",
}


def _relation_group(relation: ClaimEvidenceRelationType) -> str:
    """Which bucket of `claim.find_support` an edge belongs in."""
    return _RELATION_GROUPS.get(relation, "other")


def _run_view(run: Any) -> RunStatus:
    """One `WorkflowRun` as the wire sees it."""
    return RunStatus(
        run_id=run.run_id,
        workflow=run.workflow,
        workflow_version=run.workflow_version,
        status=run.status.value,
        cancel_requested=run.cancel_requested,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        error=run.error,
        stages=tuple(
            StageView(name=stage.name, status=stage.status.value, attempts=len(stage.attempts))
            for stage in run.stages
        ),
    )


def _review_service(ctx: CapabilityContext) -> EvidenceReviewService:
    """The evidence review service over this workspace's staging tree."""
    from research_harness.evidence.service import EvidenceReviewService
    from research_harness.evidence.staging import StagingStore

    return EvidenceReviewService(ctx, StagingStore(ctx.repo.layout.research_dir))


def _manuscript(ctx: CapabilityContext, request: ManuscriptProjectRequest) -> ManuscriptService:
    """The manuscript service for the requested LaTeX project."""
    from research_harness.manuscript.attach import ManuscriptService

    return ManuscriptService(ctx, project_root=request.project_root, main_tex=request.main_tex)


class _Projection:
    """Open the projection engine for a read, or refuse clearly that there is none."""

    def __init__(self, ctx: CapabilityContext) -> None:
        self._ctx = ctx
        self._engine: Any = None

    def __enter__(self) -> Any:
        from research_harness.domain.errors import ProjectionError
        from research_harness.projection.schema import create_engine_for

        path = self._ctx.repo.layout.database_file
        if not path.is_file():
            raise ProjectionError(
                f"no projection at {path}; call `state.rebuild` to build it from canonical state"
            )
        self._engine = create_engine_for(path)
        return self._engine

    def __exit__(self, *exc: object) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


def _projection(ctx: CapabilityContext) -> _Projection:
    """Context manager yielding the deletable SQLite projection engine."""
    return _Projection(ctx)


def _router(ctx: CapabilityContext, provider: str) -> Any:
    """The configured model entries a run may use, narrowed to ``provider``, and traced.

    Providers are configuration, never code (Product 20.2): the entry comes from the
    `providers:` list in `research.yaml`, and the API key comes from the environment.

    Two properties the CLI had and this path did not. The workspace **egress policy** rides
    on the router, so a project that forbids external models refuses here, during selection,
    before any request leaves the workstation (Product 34, ADR-018). And the router is
    wrapped in a :class:`~research_harness.privacy.traces.TracingRouter`, so a run started
    over HTTP or MCP writes the same `.research/traces/` records a `research interrogate`
    writes - redacted exactly as the project's policy says (Product 19.3).
    """
    from research_harness.privacy.policy import load_policy
    from research_harness.privacy.traces import traced
    from research_harness.providers.models.router import ModelRouter, RouterConfig, build_router

    config = RouterConfig.model_validate({"providers": list(ctx.repo.config.providers)})
    if not config.providers:
        raise CapabilityError(
            "no model providers configured: add a `providers:` list to research.yaml"
        )
    # The workspace egress policy applies on every transport (Product 34): a disabled
    # external-model policy refuses here, before any request leaves the workstation.
    policy = load_policy(ctx.repo)
    router = build_router(config, policy=policy)
    entries = [
        entry
        for entry in router.entries
        if provider in entry.tags or entry.provider.name == provider
    ]
    if not entries:
        known = ", ".join(sorted({tag for entry in router.entries for tag in entry.tags})) or "none"
        raise CapabilityError(f"no provider named {provider!r} in research.yaml (have: {known})")
    narrowed = ModelRouter(entries, policy=policy)
    # Ask now rather than on the worker thread. `work.interrogate` answers with a run id and
    # executes in the background, so a refusal `select` would have raised later reaches the
    # caller as a failed run record instead of as the policy that stopped it.
    refusal = narrowed.egress_refusal()
    if refusal is not None:
        raise refusal
    return traced(narrowed, ctx.repo)


def _model_provider(ctx: CapabilityContext, provider: str) -> Any:
    """One `ModelProvider` for a capability that takes an adapter rather than a router."""
    entries: Sequence[Any] = _router(ctx, provider).entries
    return entries[0].provider

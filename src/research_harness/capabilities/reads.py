"""The list and read capabilities every host needs to find anything (Product 22, 28, 29).

A host that cannot list Claims cannot offer a Claim picker, and a host that cannot read one
staged candidate cannot show a reviewer what it is being asked about. The Web cockpit had
both because the daemon publishes `GET /index` and `GET /candidates/{id}`; an MCP host had
neither, because those are routes rather than named capabilities (ADR-009 says the two
surfaces answer identically, so a route with no capability behind it is a gap).

This module is the shared answer. Every function here is a pure read over canonical state,
the summaries are exactly what the navigation lists, and `GET /index` is composed from the
same functions the capabilities call - so the route and the capability cannot drift.

Nothing here derives a judgement about what a Claim may say - that is `claim.audit`'s job -
and deciding what needs attention across the workspace is `GET /overview`'s. A summary
counts what a canonical file already records.

Two lists also carry the grouping they are read in - `ClaimList.groups` and
`QuestionList.groups`. That is not a new judgement: the line between a claim whose evidence
carries it and one whose evidence does not is `allowed_strength` against
`requested_strength`, both of which the claim file already records, and the line between an
open question and an answered one is its own status. Composing it once, here, is what stops
each host drawing it again in its own words (Product 5 P10).

The one judgement made here is the corpus's own: which sources cannot yet be read from, and
why. It lives beside `work.list` because it is answered from the same read and the cockpit
must never re-derive it from `screening` and `parsed` in React (Product 5 P10) - the same
reason `GET /overview` composes the attention surfaces of Product 26 rather than shipping
React the raw lists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilitySpec
from research_harness.domain.base import utc_now
from research_harness.domain.claim import Claim
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceStatus,
    ManuscriptAnchorStatus,
    QuestionStatus,
    StaleState,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ClaimId, QuestionId, SearchRunId, WorkId
from research_harness.domain.research import SearchRun
from research_harness.domain.work import Work
from research_harness.workspace.repository import ObjectNotFoundError, WorkspaceRepository

__all__ = [
    "CORPUS_MONTHS",
    "CORPUS_QUESTIONS",
    "CORPUS_RECENT_WINDOW",
    "READ_CAPABILITY_HANDLERS",
    "AnchorList",
    "AnchorSummary",
    "ArtifactSummary",
    "CandidateView",
    "ClaimGroup",
    "ClaimList",
    "ClaimRef",
    "ClaimSummary",
    "CorpusAttentionGroup",
    "CorpusAttentionItem",
    "CorpusQuestion",
    "CorpusQuestionKind",
    "DecisionList",
    "DecisionSummary",
    "EvidenceList",
    "EvidenceSummary",
    "ListAnchorsRequest",
    "ListClaimsRequest",
    "ListDecisionsRequest",
    "ListEvidenceRequest",
    "ListQuestionsRequest",
    "ListSearchRunsRequest",
    "ListWorksRequest",
    "MatrixSummary",
    "QuestionGroup",
    "QuestionList",
    "QuestionSummary",
    "ReadCandidateRequest",
    "ReadSearchRunRequest",
    "SearchRunList",
    "SearchRunSummary",
    "SearchRunView",
    "TaxonomySummary",
    "WorkList",
    "WorkSummary",
    "WorkspaceIndex",
    "WorkspaceIndexRequest",
    "answers_question",
    "claim_concern",
    "claim_groups",
    "claim_titles",
    "corpus_attention",
    "corpus_questions",
    "evidence_citations",
    "list_anchors",
    "list_claims",
    "list_decisions",
    "list_evidence",
    "list_questions",
    "list_search_runs",
    "list_works",
    "question_groups",
    "question_summary",
    "read_candidate",
    "read_search_run",
    "read_specs",
    "search_run_summary",
    "search_run_view",
    "workspace_index",
]


# -- summaries ---------------------------------------------------------------


class _Summary(BaseModel):
    """Frozen, closed read model; every transport sees the same JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ArtifactSummary(_Summary):
    """One immutable file of a Work, and whether a parse of it is stored."""

    id: str
    version: str
    kind: str
    mime_type: str
    original_filename: str
    size_bytes: int
    parsed: bool


class WorkSummary(_Summary):
    """One Work as the Corpus list shows it, and what a researcher asks of it.

    Identity is the first half. The second half is the four facts a corpus is read for -
    whether this source can be read from at all, what has been accepted from it, whether
    any Claim rests on it, and when it arrived - and every one of them is a judgement over
    canonical state that belongs here rather than in a client (Product 5 P10). A cockpit
    that decided for itself that "no file of this Work has a stored parse" means "cannot be
    read from" would be a second, disagreeing copy of Product 16 living in React.
    """

    id: str
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    screening: str
    versions: int = 0
    evidence: int = 0
    artifacts: tuple[ArtifactSummary, ...] = ()
    readable: bool = False
    """Whether any file of this Work has a stored parse.

    A span can only be anchored in a file the project has parsed (Product 16, 42 D), so
    this is the line between a source that can be read from and one that cannot - and it
    is one answer over every file, which is the answer the corpus list needs per row.
    """

    claims: int = 0
    """How many Claims cite Evidence accepted from this Work.

    Accepted evidence that no Claim rests on is work that has not landed anywhere, and a
    thousand-row corpus cannot be asked that question one Work at a time.
    """

    added: str = ""
    """When this Work entered the corpus, in the words a person reads."""

    added_at: str = ""
    """The same instant, ISO-8601, so a client can sort or compare without parsing prose."""


class CorpusAttentionItem(_Summary):
    """One Work that needs a researcher, and what is specific to it."""

    id: str
    label: str
    """The Work's own title, or its id when it has no title yet."""

    detail: str = ""
    """What is true of this Work and not of the rest of its group; empty when there is
    nothing to add, because three copies of the group's own sentence teach nothing."""

    route: str = ""
    """Where the cockpit shows this one Work. Empty means the cockpit has no screen for it
    and the item is text, never a link back to the list it is already in."""


class CorpusAttentionGroup(_Summary):
    """One reason a source is not yet something this project can read from."""

    kind: str
    label: str
    """The whole line, as a sentence: "4 works have no readable text yet". The count is
    inside it because a corpus reads its own size everywhere else on the page."""

    count: int
    items: tuple[CorpusAttentionItem, ...] = ()
    more: str = ""
    """What the item cap left out, in words; empty when nothing was left out."""


#: Every question `work.list` will narrow the corpus by.
#:
#: Closed, so an unknown one is refused by the request model with the six that exist rather
#: than answered with an empty corpus, and so a host reads them off the published schema.
#: `CORPUS_QUESTIONS` below carries the same kinds with the words for each; the contract
#: test holds the two together.
CorpusQuestionKind = Literal[
    "screening",
    "no_file",
    "unparsed",
    "unread",
    "uncited",
    "recent",
]


class CorpusQuestion(_Summary):
    """One question a researcher brings to the corpus, as a filter over the works.

    A corpus is not read record by record. It is asked things - which of these thousand
    works has nothing accepted from it, which cannot be read from yet, which no Claim rests
    on, which arrived while I was away - and each of those is a line the daemon draws over
    canonical state. The line and the words for it are one decision, so both are here: a
    client renders `label` on the control and `summary` beside the narrowed list, and never
    works out for itself which works answer the question (Product 5 P10).

    `count` is over the whole corpus, not over what the answer carries, so the control says
    the same number whether or not it is the one currently chosen.
    """

    kind: str
    label: str
    """The words on the control: short, because it sits beside five others."""

    count: int
    summary: str
    """The whole sentence the narrowed list is read under: "4 of 1000 works have no
    readable text yet." The count is inside it, because a corpus reads its own size in
    sentences everywhere else on the page."""


class ClaimSummary(_Summary):
    """One Claim as the Claim explorer lists it: what it asks, and what it may say."""

    id: str
    statement: str
    type: str
    status: str
    requested_strength: str
    allowed_strength: str
    maximum_defensible_wording: str | None = None
    stale: str
    supporting: int = 0
    qualifying: int = 0
    contradicting: int = 0


class ClaimRef(_Summary):
    """One Claim as another object refers to it: its id, and the statement it makes.

    A question carries the claims that bear on it as ids, and an id is not something a
    researcher reads. The statement is the Claim's own name — it is what the Claims page
    shows — so it is carried here rather than re-fetched by whichever surface needs it
    (Product 5 P10).
    """

    id: str
    title: str


class QuestionSummary(_Summary):
    """One ResearchQuestion and what currently bears on it."""

    id: str
    question: str
    status: str
    claims: tuple[str, ...] = ()
    bearing: tuple[ClaimRef, ...] = ()
    """The same claims as `claims`, each with the statement a person reads it by.

    `claims` stays a tuple of ids, because every reader written against it still wants
    ids. This is the additive sibling a page renders: "Bearing on it: C0001" tells a
    researcher nothing, and the Claims page already calls C0001 by its statement.
    """

    remaining_uncertainty: str | None = None
    stale: str
    opened: str = ""
    """The day this question was registered, as `YYYY-MM-DD`.

    A question stays open until a researcher resolves it (Product 31), so how long it has
    been open is the fact that separates two open questions. The order of `QuestionGroup`
    already carries it; this is what lets a row say it in words.
    """


class DecisionSummary(_Summary):
    """One researcher Decision: the visible record an override or revision leaves."""

    id: str
    type: str
    status: str
    title: str | None = None
    rationale: str
    claim: str | None = None
    auditor_recommendation: str | None = None
    researcher_selected: str | None = None


class MatrixSummary(_Summary):
    """One synthesis matrix: its rows, its fields, and whether it has gone stale."""

    id: str
    name: str
    taxonomy: str | None = None
    works: int = 0
    fields: tuple[str, ...] = ()
    cells: int = 0
    stale: str


class TaxonomySummary(_Summary):
    """One project taxonomy and the Decisions that approved its terms."""

    name: str
    terms: tuple[dict[str, Any], ...] = ()
    decisions: tuple[str, ...] = ()


class AnchorSummary(_Summary):
    """One manuscript sentence bound to a Claim (Product 30.1)."""

    file: str
    line_start: int
    sentence: str
    claim: str
    citation_keys: tuple[str, ...] = ()
    status: str
    stale: str


class EvidenceSummary(_Summary):
    """One accepted Evidence object as a list shows it, without its whole anchor."""

    id: str
    work: str
    artifact: str
    field: str | None = None
    status: str
    origin: str
    evidence_type: str
    strength: str
    review_tier: int
    verdict: str | None = None
    exact_text: str
    qualification: str | None = None
    stale: str


class CandidateView(_Summary):
    """One staged candidate, verbatim, as `evidence.accept` takes it.

    The Review Inbox summarises a candidate; a review action has to send the object itself,
    so a client reads it here and posts `evidence` back unchanged. Staging carries no
    authority (ADR-003), which is why this is the only shape in this module that is not a
    canonical object.
    """

    candidate_id: str
    work: str
    artifact: str
    field: str
    status: str
    anchor_status: str
    review_action: str | None = None
    verdict: str | None = None
    verifier: str | None = None
    verification: dict[str, Any] | None = None
    extraction: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    """The `Evidence` object to post back to `evidence.accept` / `evidence.reject`."""


class SearchRunSummary(_Summary):
    """One recorded discovery run as a host lists it: what it asked, and what it found.

    The three funnel counts are the run's own (`SearchRun` validates them against the
    candidates it records), so a host shows PRISMA numbers without recomputing them.
    """

    id: str
    question: str
    research_question: str | None = None
    sources: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    executed_at: str
    discovered: int = 0
    screened: int = 0
    included: int = 0
    candidates: int = 0
    failures: int = 0
    unresolved_keys: int = 0
    reproduces: str | None = None


class SearchRunView(_Summary):
    """One `SearchRun` verbatim, with the metadata proposals its candidates carry.

    `run` is the whole canonical object, candidates included, because a host that shows a
    screening queue needs the `WorkCandidate` each source reported, not a summary of it.

    `enrichments` is what dogfood F5 was about: a candidate that resolved to a Work the
    corpus already holds may carry a better title, author list, venue, or year, and until
    now only the CLI could see it. Each entry is a
    `discovery.search_runs.MetadataEnrichment` — the fields on offer with the source that
    reported each one, and every disagreement recorded beside them. It is a *proposal*:
    applying one is `work.update_metadata`, which is human-only, so this read shows the host
    what to offer and changes nothing (ADR-003).
    """

    summary: SearchRunSummary
    run: dict[str, Any] = Field(default_factory=dict)
    enrichments: tuple[dict[str, Any], ...] = ()
    enrichments_derived: bool = True
    """Whether this response actually walked the corpus for proposals.

    `False` for the two reasons an empty `enrichments` might not mean "none on offer": the
    caller passed `enrichments=false`, or this build has no discovery package to derive
    them with. With `True`, an empty list means the run proposes nothing."""

    apply_capability: str = "work.update_metadata"
    """The capability that writes an enrichment; naming it saves every host a lookup."""


class WorkspaceIndex(_Summary):
    """Everything a navigation lists, summarised, in one read (`GET /index`).

    Summaries, not objects: a list view needs identity and status, and the full object is
    one `GET /objects/<id>` away. Nothing here is derived beyond counting what the canonical
    files already record.
    """

    works: tuple[WorkSummary, ...] = ()
    claims: tuple[ClaimSummary, ...] = ()
    questions: tuple[QuestionSummary, ...] = ()
    decisions: tuple[DecisionSummary, ...] = ()
    matrices: tuple[MatrixSummary, ...] = ()
    taxonomies: tuple[TaxonomySummary, ...] = ()
    anchors: tuple[AnchorSummary, ...] = ()


# -- list envelopes ----------------------------------------------------------


class WorkList(_Summary):
    """`work.list`: the corpus, summarised, what in it needs a researcher, and what it
    can be asked."""

    count: int = 0
    """How many works this answer carries: the whole corpus, or the ones the question
    named."""

    total: int = 0
    """How many works the corpus holds, whatever this answer was narrowed to. A narrowed
    list still has to be able to say what it is a part of."""

    question: str = ""
    """The question this answer was narrowed by, echoed back; empty for the whole corpus.

    The client asked it, so it already knows - but a sentence describing the rows on screen
    has to be composed from the answer that produced them, not from the request that is
    still in flight.
    """

    works: tuple[WorkSummary, ...] = ()
    attention: tuple[CorpusAttentionGroup, ...] = ()
    """The sources that cannot yet be read from, in the order a researcher meets them.

    Always over the whole corpus: this is the page's lead, and a lead that changed every
    time the list beneath it was narrowed would be describing the filter rather than the
    corpus. Only the groups with something in them are here: a corpus every source of which
    is readable answers with none, and the page says so in one sentence rather than in four
    lines of zero.
    """

    questions: tuple[CorpusQuestion, ...] = ()
    """What this corpus can be asked, counted over the whole of it.

    Only the questions at least one work answers: an empty result is not a filter, which is
    the rule the review queue's own filters already keep.
    """


class ClaimGroup(_Summary):
    """One line the Claims page groups by: the concern, in words, and whose it is."""

    kind: str
    label: str
    """`2 claims ask for more than their evidence allows` - the count inside the sentence."""

    count: int = 0
    claims: tuple[str, ...] = ()
    """The claims in this group, in the order the page reads them."""


class ClaimList(_Summary):
    """`claim.list`: the claims a filter selected, summarised."""

    count: int = 0
    claims: tuple[ClaimSummary, ...] = ()
    groups: tuple[ClaimGroup, ...] = ()
    """The claims whose evidence cannot carry them, grouped by what is wrong with each.

    Only claims with something wrong appear here; a claim standing where its evidence puts
    it belongs to no group. The groups are ordered by Product 42 G's own priority: asking
    for more than the evidence allows first, then contested, unsupported, and stale.
    """

    summary: str = ""
    """One line naming the work on this list, for the Claims page's own description."""


class QuestionGroup(_Summary):
    """One line the Questions page groups by: what this group is waiting on."""

    kind: str
    label: str
    count: int = 0
    surface: str = "waiting"
    """Whether this group is still work (`waiting`) or is finished (`settled`).

    A blocked question and an open one are both work; an answered one is the record of work
    already done. The distinction is the researcher's, so the daemon draws it rather than
    a page deciding from `kind` which of its two panels a group belongs in.
    """

    status: str = ""
    """The one status this group's own line already states, when it states one.

    "1 question is still open" says `open` about every row under it, so a badge repeating
    it beside each question is the group's name said again. A question whose status the
    line does not state — a partially answered one, which is still unanswered work — is
    the row that has something to add, and the page badges that. Which status a group
    states is part of composing the grouping, so it is decided here (Product 5 P10).
    """

    questions: tuple[str, ...] = ()
    """The questions in this group, oldest first: the longest unanswered is read first."""


class QuestionList(_Summary):
    """`question.list`: the research questions, summarised."""

    count: int = 0
    questions: tuple[QuestionSummary, ...] = ()
    groups: tuple[QuestionGroup, ...] = ()
    summary: str = ""
    """One line naming what is still open, for the Questions page's own description."""


class DecisionList(_Summary):
    """`decision.list`: the recorded researcher decisions, summarised."""

    count: int = 0
    decisions: tuple[DecisionSummary, ...] = ()


class EvidenceList(_Summary):
    """`evidence.list`: accepted evidence, summarised, by work or status."""

    count: int = 0
    evidence: tuple[EvidenceSummary, ...] = ()


class AnchorList(_Summary):
    """`anchor.list`: every manuscript sentence bound to a Claim."""

    count: int = 0
    anchors: tuple[AnchorSummary, ...] = ()


class SearchRunList(_Summary):
    """`search_run.list`: the discovery runs this workspace recorded, newest first."""

    count: int = 0
    search_runs: tuple[SearchRunSummary, ...] = ()


# -- requests ----------------------------------------------------------------


class ListWorksRequest(CapabilityRequest):
    """`work.list`: the corpus, optionally narrowed to one screening state or one question."""

    screening: str | None = None
    question: CorpusQuestionKind | None = None
    """One of `CORPUS_QUESTIONS`: the narrowing is the daemon's, so the vocabulary is too.

    Typed as a closed set rather than a string, so an unknown question is refused with the
    ones that exist rather than answered with an empty corpus, and so every host reads the
    list of them off the published request schema.
    """


class ListClaimsRequest(CapabilityRequest):
    """`claim.list`: claim summaries, filtered by status, staleness, and type."""

    status: ClaimStatus | None = None
    stale: StaleState | None = None
    # `type` shadows the builtin on purpose: it is the field name in Product 10.1, and a
    # filter that does not match the field it filters is worse than a shadowed builtin.
    type: ClaimType | None = None


class ListQuestionsRequest(CapabilityRequest):
    """`question.list`: research questions, optionally narrowed to one status."""

    status: QuestionStatus | None = None


class ListDecisionsRequest(CapabilityRequest):
    """`decision.list`: researcher decisions, optionally narrowed to one claim."""

    claim: ClaimId | None = None


class ListEvidenceRequest(CapabilityRequest):
    """`evidence.list`: accepted evidence, by work and by lifecycle status."""

    work: WorkId | None = None
    status: EvidenceStatus | None = None


class ListAnchorsRequest(CapabilityRequest):
    """`anchor.list`: manuscript anchors, optionally narrowed to one file or status."""

    file: str | None = None
    status: ManuscriptAnchorStatus | None = None


class ReadCandidateRequest(CapabilityRequest):
    """`review.candidate`: one staged candidate, verbatim."""

    candidate_id: str


class ListSearchRunsRequest(CapabilityRequest):
    """`search_run.list`: discovery runs, optionally narrowed to one research question."""

    research_question: QuestionId | None = None
    source: str | None = None


class ReadSearchRunRequest(CapabilityRequest):
    """`search_run.get`: one run with its candidates and the metadata it offers."""

    search_run: SearchRunId
    enrichments: bool = True
    """Derive the `work.update_metadata` proposals; `False` skips the walk over the corpus."""

    only_empty_or_undecodable: bool = True
    """Propose only what the Work is missing or cannot read; `False` lists disputed fields too."""


class WorkspaceIndexRequest(CapabilityRequest):
    """`state.index`: every navigation list in one read."""


# -- handlers ----------------------------------------------------------------


def list_works(ctx: CapabilityContext, request: ListWorksRequest) -> WorkList:
    """`work.list`: the corpus, what needs a reader, and the questions it can be asked.

    The corpus is answered whole - the daemon imposes no page size - and then narrowed, in
    that order: the lead and the question counts are facts about the corpus, so they are
    computed over all of it and stay still while a researcher moves between questions.
    Only `works` is narrowed, and `question` says by what.

    The citation index is built once for the whole read rather than per Work: asking "does
    any Claim rest on this?" a thousand times would walk the claims a thousand times.
    """
    works = [
        work
        for work in ctx.repo.list_works()
        if request.screening is None or work.screening.value == request.screening
    ]
    citations = evidence_citations(ctx.repo)
    summaries = tuple(work_summary(ctx.repo, work, citations=citations) for work in works)
    now = utc_now()
    shown = (
        summaries
        if request.question is None
        else tuple(work for work in summaries if answers_question(work, request.question, now=now))
    )
    return WorkList(
        count=len(shown),
        total=len(summaries),
        question=request.question or "",
        works=shown,
        attention=corpus_attention(summaries),
        questions=corpus_questions(summaries, now=now),
    )


def list_claims(ctx: CapabilityContext, request: ListClaimsRequest) -> ClaimList:
    """`claim.list`: claim summaries a host can put in a picker, filtered server-side."""
    claims = [
        claim
        for claim in ctx.repo.list_claims()
        if (request.status is None or claim.assessment.status is request.status)
        and (request.stale is None or claim.stale is request.stale)
        and (request.type is None or claim.type is request.type)
    ]
    summaries = tuple(claim_summary(claim) for claim in claims)
    groups = claim_groups(summaries)
    return ClaimList(
        count=len(claims),
        claims=summaries,
        groups=groups,
        summary=_claim_summary_line(summaries, groups),
    )


def list_questions(ctx: CapabilityContext, request: ListQuestionsRequest) -> QuestionList:
    """`question.list`: the open work of the project (Product 31)."""
    questions = [
        question
        for question in ctx.repo.list_questions()
        if request.status is None or question.status is request.status
    ]
    titles = claim_titles(ctx.repo)
    summaries = tuple(question_summary(question, titles) for question in questions)
    groups = question_groups(summaries)
    return QuestionList(
        count=len(questions),
        questions=summaries,
        groups=groups,
        summary=_question_summary_line(summaries, groups),
    )


def list_decisions(ctx: CapabilityContext, request: ListDecisionsRequest) -> DecisionList:
    """`decision.list`: the record every override and revision leaves (Product 38)."""
    decisions = [
        decision
        for decision in ctx.repo.list_decisions()
        if request.claim is None or decision.claim == request.claim
    ]
    return DecisionList(
        count=len(decisions),
        decisions=tuple(decision_summary(decision) for decision in decisions),
    )


def list_evidence(ctx: CapabilityContext, request: ListEvidenceRequest) -> EvidenceList:
    """`evidence.list`: accepted evidence, by work and status; never staged proposals.

    Staging holds proposals with no authority (ADR-003) and is read through `review.inbox`
    and `review.candidate`; this capability answers only for what the corpus accepted.

    ``work`` is a filter, so naming one the corpus does not hold yields an empty list rather
    than a refusal — the same answer as a Work with no accepted evidence yet.
    """
    works = (
        [request.work] if request.work is not None else [work.id for work in ctx.repo.list_works()]
    )
    found: list[Evidence] = []
    for work in works:
        try:
            records = list(ctx.repo.iter_evidence(work))
        except ObjectNotFoundError:
            continue
        found.extend(
            item
            for item in records
            if request.status is None or item.verification.status is request.status
        )
    return EvidenceList(count=len(found), evidence=tuple(evidence_summary(item) for item in found))


def list_anchors(ctx: CapabilityContext, request: ListAnchorsRequest) -> AnchorList:
    """`anchor.list`: every manuscript sentence bound to a Claim (Product 30.1)."""
    anchors = [
        anchor
        for anchor in ctx.repo.iter_anchors()
        if (request.file is None or anchor.file == request.file)
        and (request.status is None or anchor.status is request.status)
    ]
    return AnchorList(
        count=len(anchors), anchors=tuple(anchor_summary(anchor) for anchor in anchors)
    )


def read_candidate(ctx: CapabilityContext, request: ReadCandidateRequest) -> CandidateView:
    """`review.candidate`: one staged candidate, verbatim, so a review action can post it back.

    Staging is a proposal store with no authority (ADR-003): reading it changes nothing, and
    accepting what it holds still goes through the review gate.
    """
    return candidate_view(ctx.repo, request.candidate_id)


def list_search_runs(ctx: CapabilityContext, request: ListSearchRunsRequest) -> SearchRunList:
    """`search_run.list`: every recorded discovery run, newest first (Product 18).

    A run is a canonical object and reading one changes nothing. Newest first because a
    host's first question about discovery is always "what did I just run".
    """
    runs = [
        run
        for run in ctx.repo.list_search_runs()
        if (request.research_question is None or run.research_question == request.research_question)
        and (request.source is None or request.source in run.sources)
    ]
    runs.sort(key=lambda run: (run.executed_at, str(run.id)), reverse=True)
    return SearchRunList(
        count=len(runs), search_runs=tuple(search_run_summary(run) for run in runs)
    )


def read_search_run(ctx: CapabilityContext, request: ReadSearchRunRequest) -> SearchRunView:
    """`search_run.get`: one run with its candidates and the metadata they offer (F5).

    The proposals are derived, never stored: a `SearchCandidate` keeps the whole
    `WorkCandidate` its source reported, so nothing was lost when a hit resolved to a Work
    the corpus already held — it was simply never read back, and only `research discover`
    could see it. Deriving them here is what lets the Web cockpit, VS Code, and an MCP host
    show the same `work.update_metadata` proposals the CLI does.
    """
    run = ctx.repo.get_search_run(request.search_run)
    return search_run_view(
        ctx,
        run,
        enrichments=request.enrichments,
        only_empty_or_undecodable=request.only_empty_or_undecodable,
    )


def read_index(ctx: CapabilityContext, request: WorkspaceIndexRequest) -> WorkspaceIndex:
    """`state.index`: every navigation list in one read, for a host with one round trip."""
    del request
    return workspace_index(ctx.repo)


# -- the shared builders -----------------------------------------------------


#: How many works one corpus attention group names before it defers to the list itself.
#:
#: Eight, because a group is read as a set of items and its cap sentence is not one: "1 more
#: is in the list below" is neither a work nor a link, and a reader who wants that work has
#: to go and find it. Below this size the group names every work it counts and no sentence
#: stands in for one. Above it the sentence is a genuine cap rather than a dangling pointer
#: — a lead is not a second copy of the corpus — and the count in the group's own line
#: already says how many there are.
CORPUS_ATTENTION_ITEMS = 8

#: Why a source is not yet something this project can read from, in the order a researcher
#: meets them: a screening decision left half-taken keeps a Work out of the corpus proper
#: (Product 14), a file has to be behind it, a stored parse has to exist before any span in
#: it can be anchored (Product 16), and only then can anything be accepted from it.
#:
#: Each entry is the whole line the page reads - for one work, and for several. The count
#: lives inside the sentence because a bare number at heading size is the shape the Overview
#: was rebuilt to leave behind, and this page follows it.
CORPUS_ATTENTION: tuple[tuple[str, str, str], ...] = (
    (
        "screening",
        "1 work was screened and never included or excluded",
        "{count} works were screened and never included or excluded",
    ),
    (
        "no_file",
        "1 work has no file to read from",
        "{count} works have no file to read from",
    ),
    (
        "unparsed",
        "1 work has no readable text yet",
        "{count} works have no readable text yet",
    ),
    (
        "unread",
        "1 work has nothing accepted from it yet",
        "{count} works have nothing accepted from them yet",
    ),
)


def corpus_attention(works: Sequence[WorkSummary]) -> tuple[CorpusAttentionGroup, ...]:
    """Which sources need a researcher, and why, in the order the corpus acquires them.

    This is the judgement the Corpus page opens with, and it is made here so no client
    makes it: a cockpit that read `screening` and `parsed` and decided for itself which
    works were in trouble would be a second, disagreeing copy of Product 14 and 16 living
    in React (Product 5 P10).

    Only the groups with something in them come back. A corpus every source of which can be
    read from answers with none, and the page says that in one sentence rather than in four
    lines of zero.
    """
    members: dict[str, list[WorkSummary]] = {kind: [] for kind, _, _ in CORPUS_ATTENTION}
    for work in works:
        kind = _corpus_group(work)
        if kind:
            members[kind].append(work)
    return tuple(
        _corpus_group_view(kind, singular, plural, members[kind])
        for kind, singular, plural in CORPUS_ATTENTION
        if members[kind]
    )


def _corpus_group(work: WorkSummary) -> str:
    """Which group one Work belongs to, or "" when it needs nothing.

    The first missing thing wins: a half-finished screening decision is a decision whatever
    else is true of the Work, and asking for a parse of a file that was never attached would
    ask for the wrong thing.

    Two screening states ask for nothing. `excluded` is a decision already taken (Product
    14). `discovered` is the state every Work is *ingested* in - it is the field's default
    and nothing in the cockpit moves it - so counting it as an open decision would put the
    whole corpus in a group with no next step in it, forever. `screened` is the one that is
    genuinely unfinished: something judged this Work and left it neither in nor out.
    """
    if work.screening == "screened":
        return "screening"
    if work.screening == "excluded":
        return ""
    if not work.artifacts:
        return "no_file"
    if not any(artifact.parsed for artifact in work.artifacts):
        return "unparsed"
    if work.evidence == 0:
        return "unread"
    return ""


def _corpus_detail(kind: str, work: WorkSummary) -> str:
    """What is true of this Work and not of every other Work in its group.

    Empty where there is nothing to add: three copies of the group's own sentence teach a
    reader nothing the line above them did not already say.
    """
    if kind == "unparsed" and len(work.artifacts) > 1:
        # Only the plural is news. "Its one file has no stored parse" under a line that
        # already said "4 works have no readable text yet" is the same sentence three times.
        return f"none of its {len(work.artifacts)} files has a stored parse"
    return ""


def _corpus_group_view(
    kind: str, singular: str, plural: str, works: Sequence[WorkSummary]
) -> CorpusAttentionGroup:
    """One group: its sentence, the first few works in it, and what the cap left out."""
    shown = tuple(works[:CORPUS_ATTENTION_ITEMS])
    rest = len(works) - len(shown)
    if rest == 0:
        more = ""
    elif rest == 1:
        more = "1 more is in the list below."
    else:
        more = f"{rest} more are in the list below."
    return CorpusAttentionGroup(
        kind=kind,
        label=singular if len(works) == 1 else plural.format(count=len(works)),
        count=len(works),
        items=tuple(
            CorpusAttentionItem(
                id=work.id,
                label=work.title or work.id,
                detail=_corpus_detail(kind, work),
                # The cockpit's own path for one Work, as `GET /overview` writes it for a
                # stale object: the daemon says where an item lives, never the client.
                route=f"/corpus/{work.id}",
            )
            for work in shown
        ),
        more=more,
    )


#: How recently a Work has to have arrived to count as new to a returning researcher.
#:
#: A week, stated in the question's own sentence rather than left to be guessed at. The
#: Overview answers the neighbouring question - what *changed* while you were away - from
#: the conversation sessions, because a change has to be measured against a sitting. A
#: corpus does not: "what came in lately" is a fact about the corpus, it has to mean the
#: same thing in a project with no conversation in it, and a window a page can state in
#: words is worth more here than one it would have to explain.
CORPUS_RECENT_WINDOW = timedelta(days=7)

#: What a researcher asks the corpus, in the order the work arrives in.
#:
#: The first four are the attention groups themselves - the same line `_corpus_group` draws,
#: so the lead's "4 works have no readable text yet" and the control that narrows the list
#: to those four can never disagree about which works they are or how many. The last two are
#: questions that are not about readiness: evidence accepted that no Claim rests on, and
#: what arrived lately.
#:
#: Each entry is the kind, the words on the control, and the sentence the narrowed list is
#: read under, singular and plural.
CORPUS_QUESTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "screening",
        "Screened, not decided",
        "1 of {total} works was screened and never included or excluded.",
        "{count} of {total} works were screened and never included or excluded.",
    ),
    (
        "no_file",
        "No file",
        "1 of {total} works has no file to read from.",
        "{count} of {total} works have no file to read from.",
    ),
    (
        "unparsed",
        "No readable text",
        "1 of {total} works has no readable text yet.",
        "{count} of {total} works have no readable text yet.",
    ),
    (
        "unread",
        "Nothing accepted",
        "1 of {total} works has nothing accepted from it yet.",
        "{count} of {total} works have nothing accepted from them yet.",
    ),
    (
        "uncited",
        "Cited by no claim",
        "1 of {total} works has accepted evidence that no claim cites.",
        "{count} of {total} works have accepted evidence that no claim cites.",
    ),
    (
        "recent",
        "Came in this week",
        "1 of {total} works came into the corpus in the last 7 days.",
        "{count} of {total} works came into the corpus in the last 7 days.",
    ),
)


def answers_question(work: WorkSummary, kind: str, *, now: datetime) -> bool:
    """Whether one Work is one of the works a question is asking about.

    The four readiness questions defer to `_corpus_group`, which is the corpus's own
    grouping and takes the first missing thing: a Work with no file has nothing accepted
    from it either, and answering both would be counting the same absence twice and
    offering two controls that lead to the same row.

    The other two stand on their own. "Cited by no claim" is about accepted evidence that
    no Claim rests on, so a Work nothing has been accepted from is not in it - that Work's
    question is the one above. "Came in this week" is the Work's own arrival.
    """
    if kind == "uncited":
        return work.evidence > 0 and work.claims == 0
    if kind == "recent":
        return bool(work.added_at) and datetime.fromisoformat(work.added_at) >= now - (
            CORPUS_RECENT_WINDOW
        )
    return _corpus_group(work) == kind


def corpus_questions(
    works: Sequence[WorkSummary], *, now: datetime | None = None
) -> tuple[CorpusQuestion, ...]:
    """What this corpus can be asked, counted over the whole of it.

    Only the questions at least one Work answers. A control that narrows a list to nothing
    is not a filter, it is a dead end wearing a count of zero - the same rule the review
    queue's own filters keep - and a corpus in good order should offer few of these, not
    six greyed ones.
    """
    moment = now or utc_now()
    found: list[CorpusQuestion] = []
    for kind, label, singular, plural in CORPUS_QUESTIONS:
        count = sum(1 for work in works if answers_question(work, kind, now=moment))
        if count == 0:
            continue
        template = singular if count == 1 else plural
        found.append(
            CorpusQuestion(
                kind=kind,
                label=label,
                count=count,
                summary=template.format(count=count, total=len(works)),
            )
        )
    return tuple(found)


def evidence_citations(repo: WorkspaceRepository) -> Mapping[str, frozenset[str]]:
    """Which Claims cite each accepted Evidence object, read once for the whole corpus.

    A Claim records the Evidence it rests on; nothing on the Evidence side records the
    Claims that rest on it. So the direction a corpus is read in - "does anything rest on
    this source?" - has to be inverted here, once, rather than by walking every Claim again
    for every Work.
    """
    found: dict[str, set[str]] = {}
    for claim in repo.list_claims():
        for link in claim.relations:
            found.setdefault(str(link.evidence), set()).add(str(claim.id))
    return {evidence: frozenset(claims) for evidence, claims in found.items()}


def _human_arrival(moment: datetime) -> str:
    """One arrival in the words a person reads, in the time zone the daemon runs in.

    The day, not the minute: a corpus row is read against the row under it, and a column of
    clock times would compare two sources by an accident of when someone was at the desk.
    """
    local = moment.astimezone()
    return f"{local.day} {CORPUS_MONTHS[local.month - 1]} {local.year}"


#: Month names for an arrival date. The cockpit's locale is the reader's; this is the
#: daemon's own sentence, and it is written the way every other sentence it composes is.
CORPUS_MONTHS: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def work_summary(
    repo: WorkspaceRepository,
    work: Work,
    *,
    citations: Mapping[str, frozenset[str]] | None = None,
) -> WorkSummary:
    """One Work with its files, what has been accepted from it, and what rests on that.

    `citations` is the inverted index `evidence_citations` builds for a whole read. Passing
    it is an optimisation, never a difference in the answer: a caller with one Work to
    summarise leaves it out and this reads the Claims itself.
    """
    cited = evidence_citations(repo) if citations is None else citations
    accepted = tuple(str(item.id) for item in repo.iter_evidence(work.id))
    artifacts = tuple(
        ArtifactSummary(
            id=str(artifact.id),
            version=str(artifact.version),
            kind=artifact.kind.value,
            mime_type=artifact.mime_type,
            original_filename=artifact.original_filename,
            size_bytes=artifact.size_bytes,
            parsed=any(True for _ in repo.iter_blocks(artifact.id, work=work.id)),
        )
        for artifact in repo.list_artifacts(work.id)
    )
    return WorkSummary(
        id=str(work.id),
        title=work.title,
        authors=work.authors,
        year=work.year,
        venue=work.venue,
        screening=work.screening.value,
        versions=len(work.versions),
        evidence=len(accepted),
        artifacts=artifacts,
        readable=any(artifact.parsed for artifact in artifacts),
        claims=len({claim for item in accepted for claim in cited.get(item, frozenset())}),
        added=_human_arrival(work.created_at),
        added_at=work.created_at.isoformat(),
    )


def claim_summary(claim: Claim) -> ClaimSummary:
    """One Claim as every list of claims shows it."""
    return ClaimSummary(
        id=str(claim.id),
        statement=claim.statement,
        type=claim.type.value,
        status=claim.status.value,
        requested_strength=claim.requested_strength.value,
        allowed_strength=claim.allowed_strength.value,
        maximum_defensible_wording=claim.assessment.maximum_defensible_wording,
        stale=claim.stale.value,
        supporting=len(claim.supporting),
        qualifying=len(claim.qualifying),
        contradicting=len(claim.contradicting),
    )


#: What can be wrong with a claim, in Product 42 G's own order of seriousness, with the
#: verb each concern reads with in the singular and in the plural. A claim belongs to the
#: first of these that describes it, so one claim is never counted twice.
CLAIM_CONCERNS: tuple[tuple[str, str, str], ...] = (
    (
        "overreaching",
        "asks for more than its evidence allows",
        "ask for more than their evidence allows",
    ),
    ("contested", "is contested", "are contested"),
    ("unsupported", "is unsupported", "are unsupported"),
    ("stale", "has gone stale", "have gone stale"),
)

#: The three states a question can be read in, the sentence each group reads with, and the
#: one status that sentence already states. The first two groups are still work; the third
#: is the record of work already finished.
QUESTION_CONCERNS: tuple[tuple[str, str, str, str, str], ...] = (
    ("unanswered", "waiting", "is still open", "are still open", QuestionStatus.OPEN.value),
    ("blocked", "waiting", "is blocked", "are blocked", QuestionStatus.BLOCKED.value),
    (
        "answered",
        "settled",
        "has been answered",
        "have been answered",
        QuestionStatus.ANSWERED.value,
    ),
)

#: Which group a question's own status puts it in.
QUESTION_SURFACES: dict[QuestionStatus, str] = {
    QuestionStatus.OPEN: "unanswered",
    QuestionStatus.PARTIALLY_ANSWERED: "unanswered",
    QuestionStatus.BLOCKED: "blocked",
    QuestionStatus.ANSWERED: "answered",
}


def claim_concern(claim: ClaimSummary) -> str | None:
    """What is wrong with one claim, or `None` when its evidence carries it.

    The first line is the one this product exists to hold: a claim may not say more than
    the audit allows (Product 10.2, 42 G), so a requested strength above the allowed one is
    the concern that outranks the rest. Nothing here is computed about the claim - every
    comparison is between two fields the claim file already records.
    """
    if ClaimScope(claim.allowed_strength) < ClaimScope(claim.requested_strength):
        return "overreaching"
    if claim.status == ClaimStatus.CONTESTED:
        return "contested"
    if claim.status == ClaimStatus.UNSUPPORTED:
        return "unsupported"
    if claim.stale == StaleState.STALE:
        return "stale"
    return None


def claim_groups(claims: tuple[ClaimSummary, ...]) -> tuple[ClaimGroup, ...]:
    """The claims whose evidence cannot carry them, grouped and ordered for reading."""
    found: dict[str, list[str]] = {}
    for claim in claims:
        concern = claim_concern(claim)
        if concern is not None:
            found.setdefault(concern, []).append(claim.id)
    return tuple(
        ClaimGroup(
            kind=kind,
            label=_counted("claim", len(found[kind]), singular, plural),
            count=len(found[kind]),
            claims=tuple(found[kind]),
        )
        for kind, singular, plural in CLAIM_CONCERNS
        if kind in found
    )


def question_groups(questions: tuple[QuestionSummary, ...]) -> tuple[QuestionGroup, ...]:
    """Every question, grouped by what it is waiting on, longest unanswered first."""
    found: dict[str, list[QuestionSummary]] = {}
    for question in questions:
        kind = QUESTION_SURFACES[QuestionStatus(question.status)]
        found.setdefault(kind, []).append(question)
    return tuple(
        QuestionGroup(
            kind=kind,
            label=_counted("question", len(found[kind]), singular, plural),
            count=len(found[kind]),
            surface=surface,
            status=status,
            questions=tuple(
                entry.id
                for entry in sorted(found[kind], key=lambda entry: (entry.opened, entry.id))
            ),
        )
        for kind, surface, singular, plural, status in QUESTION_CONCERNS
        if kind in found
    )


def _claim_summary_line(claims: tuple[ClaimSummary, ...], groups: tuple[ClaimGroup, ...]) -> str:
    """The Claims page's first sentence: the work first, and the size of the list never."""
    if not claims:
        return "This project has registered no claims yet."
    if not groups:
        return "Every registered claim stands where its evidence puts it."
    return f"{_joined(tuple(group.label for group in groups))}."


def _question_summary_line(
    questions: tuple[QuestionSummary, ...], groups: tuple[QuestionGroup, ...]
) -> str:
    """The Questions page's first sentence, naming what is still open (Product 31)."""
    if not questions:
        return "This project has registered no questions yet."
    waiting = tuple(group.label for group in groups if group.surface == "waiting")
    if not waiting:
        return "Every question this project registered has been answered."
    return f"{_joined(waiting)}."


def _counted(noun: str, count: int, singular: str, plural: str) -> str:
    """`1 claim is contested` / `3 claims are contested`: the count inside its sentence."""
    return f"{count} {noun} {singular}" if count == 1 else f"{count} {noun}s {plural}"


def _joined(phrases: tuple[str, ...]) -> str:
    """`a`, `a and b`, `a, b and c` - several phrases read as one sentence."""
    if len(phrases) <= 1:
        return "".join(phrases)
    return f"{', '.join(phrases[:-1])} and {phrases[-1]}"


def question_summary(question: Any, titles: Mapping[str, str] | None = None) -> QuestionSummary:
    """One ResearchQuestion as every list of questions shows it.

    `titles` maps a Claim id to its statement. Without it the claims are still reported as
    ids and `bearing` names each of them by its id, which is what a caller that has not
    opened the claims can honestly say.
    """
    known = titles or {}
    claims = tuple(str(claim) for claim in question.claims)
    return QuestionSummary(
        id=str(question.id),
        question=question.question,
        status=question.status.value,
        claims=claims,
        bearing=tuple(ClaimRef(id=claim, title=known.get(claim, claim)) for claim in claims),
        remaining_uncertainty=question.remaining_uncertainty,
        stale=question.stale.value,
        opened=question.created_at.date().isoformat(),
    )


def claim_titles(repo: Any) -> dict[str, str]:
    """Every Claim's own statement, by id: what another object calls it when it names one."""
    return {str(claim.id): claim.statement for claim in repo.list_claims()}


def decision_summary(decision: Any) -> DecisionSummary:
    """One Decision as every list of decisions shows it."""
    return DecisionSummary(
        id=str(decision.id),
        type=decision.type.value,
        status=decision.status.value,
        title=decision.title,
        rationale=decision.rationale,
        claim=None if decision.claim is None else str(decision.claim),
        auditor_recommendation=(
            None
            if decision.auditor_recommendation is None
            else decision.auditor_recommendation.value
        ),
        researcher_selected=(
            None if decision.researcher_selected is None else decision.researcher_selected.value
        ),
    )


def evidence_summary(item: Evidence) -> EvidenceSummary:
    """One Evidence object without its anchor; the anchor is one `/objects/<id>` away."""
    return EvidenceSummary(
        id=str(item.id),
        work=str(item.source.work),
        artifact=str(item.source.artifact),
        field=item.content.field,
        status=item.verification.status.value,
        origin=item.origin.value,
        evidence_type=item.evidence_type.value,
        strength=item.strength.value,
        review_tier=int(item.review_tier),
        verdict=None if item.verification.verdict is None else item.verification.verdict.value,
        exact_text=item.content.exact_text,
        qualification=item.qualification,
        stale=item.stale.value,
    )


def anchor_summary(anchor: Any) -> AnchorSummary:
    """One manuscript anchor as every list of anchors shows it."""
    return AnchorSummary(
        file=anchor.file,
        line_start=anchor.line_start,
        sentence=anchor.sentence,
        claim=str(anchor.claim),
        citation_keys=anchor.citation_keys,
        status=anchor.status.value,
        stale=anchor.stale.value,
    )


def search_run_summary(run: SearchRun) -> SearchRunSummary:
    """One SearchRun as every list of runs shows it; nothing is recomputed."""
    return SearchRunSummary(
        id=str(run.id),
        question=run.question,
        research_question=None if run.research_question is None else str(run.research_question),
        sources=run.sources,
        queries=run.queries,
        executed_at=run.executed_at.isoformat(),
        discovered=run.results.discovered,
        screened=run.results.screened,
        included=run.results.included,
        candidates=len(run.candidates),
        failures=len(run.failures),
        unresolved_keys=len(run.unresolved_keys),
        reproduces=None if run.reproduces is None else str(run.reproduces),
    )


def search_run_view(
    ctx: CapabilityContext,
    run: SearchRun,
    *,
    enrichments: bool = True,
    only_empty_or_undecodable: bool = True,
) -> SearchRunView:
    """The run verbatim plus its metadata proposals, or the run alone when asked.

    `discovery/` imports `capabilities/`, so the derivation is imported inside the function
    the way every other reach across that cycle is (conventions.md). A build without the
    discovery package answers with the run and says the proposals are unavailable, rather
    than failing a read that is mostly about the run.
    """
    view = SearchRunView(summary=search_run_summary(run), run=run.model_dump(mode="json"))
    if not enrichments:
        return view.model_copy(update={"enrichments_derived": False})
    try:
        from research_harness.discovery.search_runs import enrichments_for
    except ImportError:  # pragma: no cover - only when the discovery package is absent
        return view.model_copy(update={"enrichments_derived": False})
    found = enrichments_for(ctx, run, only_empty_or_undecodable=only_empty_or_undecodable)
    return view.model_copy(
        update={"enrichments": tuple(item.model_dump(mode="json") for item in found)}
    )


def candidate_view(repo: WorkspaceRepository, candidate_id: str) -> CandidateView:
    """One staged candidate by id; a candidate that is not there is not found, not empty."""
    from research_harness.evidence.staging import StagingStore

    try:
        found = StagingStore(repo.layout.research_dir).get(candidate_id)
    except ResearchHarnessError as exc:
        raise ObjectNotFoundError(f"no staged candidate {candidate_id!r}: {exc}") from exc
    return CandidateView(
        candidate_id=found.candidate_id,
        work=str(found.work),
        artifact=str(found.artifact),
        field=found.field,
        status=found.status.value,
        anchor_status=found.anchor_status.value,
        review_action=None if found.review_action is None else found.review_action.value,
        verdict=found.verdict,
        verifier=found.verifier,
        verification=(
            None if found.verification is None else found.verification.model_dump(mode="json")
        ),
        extraction=found.extraction.model_dump(mode="json"),
        evidence=found.evidence.model_dump(mode="json"),
    )


def workspace_index(repo: WorkspaceRepository) -> WorkspaceIndex:
    """Summaries of every canonical object a navigation lists, counted, never derived."""
    return WorkspaceIndex(
        works=tuple(work_summary(repo, work) for work in repo.list_works()),
        claims=tuple(claim_summary(claim) for claim in repo.list_claims()),
        questions=tuple(
            question_summary(question, claim_titles(repo)) for question in repo.list_questions()
        ),
        decisions=tuple(decision_summary(decision) for decision in repo.list_decisions()),
        matrices=tuple(
            MatrixSummary(
                id=str(matrix.id),
                name=matrix.name,
                taxonomy=matrix.taxonomy,
                works=len(matrix.works),
                fields=matrix.fields,
                cells=len(matrix.cells),
                stale=matrix.stale.value,
            )
            for matrix in repo.list_matrices()
        ),
        taxonomies=tuple(
            TaxonomySummary(
                name=taxonomy.name,
                terms=tuple(term.model_dump(mode="json") for term in taxonomy.terms),
                decisions=tuple(
                    sorted(
                        {str(term.decision) for term in taxonomy.terms if term.decision is not None}
                    )
                ),
            )
            for taxonomy in repo.list_taxonomies()
        ),
        anchors=tuple(anchor_summary(anchor) for anchor in repo.iter_anchors()),
    )


# -- registration ------------------------------------------------------------


#: Name -> handler for every capability this module implements.
READ_CAPABILITY_HANDLERS: dict[str, Any] = {
    "work.list": list_works,
    "claim.list": list_claims,
    "question.list": list_questions,
    "decision.list": list_decisions,
    "evidence.list": list_evidence,
    "anchor.list": list_anchors,
    "review.candidate": read_candidate,
    "search_run.list": list_search_runs,
    "search_run.get": read_search_run,
    "state.index": read_index,
}

_READS = "reads canonical state; changes nothing"


def read_specs() -> list[CapabilitySpec]:
    """The list and read capabilities, all `read`, in one table."""
    return [
        _read(
            "work.list",
            summary="Every Work in the corpus, with its files and evidence counts.",
            request_model=ListWorksRequest,
            response_model=WorkList,
            handler=list_works,
        ),
        _read(
            "claim.list",
            summary="Claim summaries, filtered by status, staleness, and type.",
            request_model=ListClaimsRequest,
            response_model=ClaimList,
            handler=list_claims,
        ),
        _read(
            "question.list",
            summary="Research questions and what currently bears on them.",
            request_model=ListQuestionsRequest,
            response_model=QuestionList,
            handler=list_questions,
        ),
        _read(
            "decision.list",
            summary="Recorded researcher decisions, optionally for one Claim.",
            request_model=ListDecisionsRequest,
            response_model=DecisionList,
            handler=list_decisions,
        ),
        _read(
            "evidence.list",
            summary="Accepted evidence by work and status; staged proposals are not listed.",
            request_model=ListEvidenceRequest,
            response_model=EvidenceList,
            handler=list_evidence,
        ),
        _read(
            "anchor.list",
            summary="Every manuscript sentence bound to a Claim.",
            request_model=ListAnchorsRequest,
            response_model=AnchorList,
            handler=list_anchors,
        ),
        _read(
            "review.candidate",
            summary="One staged candidate, verbatim, as a review action posts it back.",
            semantics="reads a staged proposal; accepts nothing and changes nothing",
            request_model=ReadCandidateRequest,
            response_model=CandidateView,
            handler=read_candidate,
        ),
        _read(
            "search_run.list",
            summary="Recorded discovery runs with their funnel counts, newest first.",
            request_model=ListSearchRunsRequest,
            response_model=SearchRunList,
            handler=list_search_runs,
        ),
        _read(
            "search_run.get",
            summary="One discovery run with its candidates and the metadata they propose.",
            semantics=(
                "reads a recorded SearchRun and derives the metadata its candidates offer; "
                "proposes nothing to the corpus and changes nothing"
            ),
            request_model=ReadSearchRunRequest,
            response_model=SearchRunView,
            handler=read_search_run,
        ),
        _read(
            "state.index",
            summary="Every navigation list - works, claims, questions, decisions - in one read.",
            request_model=WorkspaceIndexRequest,
            response_model=WorkspaceIndex,
            handler=read_index,
        ),
    ]


def _read(
    name: str,
    *,
    summary: str,
    request_model: type[BaseModel],
    response_model: type[BaseModel],
    handler: Any,
    semantics: str = _READS,
) -> CapabilitySpec:
    """One read capability, spelled out so the table above reads as a table."""
    return CapabilitySpec(
        name=name,
        summary=summary,
        permission=Permission.READ,
        scientific_semantics=semantics,
        request_model=request_model,
        response_model=response_model,
        handler=handler,
    )

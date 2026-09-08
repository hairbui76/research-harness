"""The list and read capabilities a host needs to find anything (Product 22, 28, 29).

The gap these close is stated in `docs/architecture/vscode.md`: the daemon published
`GET /index`, so the Web cockpit could list Claims and an MCP host could not, and a route
with no capability behind it is exactly the per-host divergence ADR-009 forbids. So the
rules asserted here are about *sameness*: every list is a `read`, every filter is applied
server-side, and `GET /index` composes the same summaries the capabilities return.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    AddNoteRequest,
    CreateClaimRequest,
    CreateQuestionRequest,
)
from research_harness.capabilities.handlers import (
    PROVISIONAL_EVIDENCE_ID,
    accept_evidence,
    add_note,
    create_claim,
    create_question,
)
from research_harness.capabilities.permissions import Permission, Principal
from research_harness.capabilities.reads import (
    CORPUS_MONTHS,
    CORPUS_ORDERS,
    CORPUS_QUESTIONS,
    CorpusOrderKind,
    CorpusQuestionKind,
    WorkSummary,
    order_works,
    workspace_index,
)
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceStatus,
    QuestionStatus,
    ScreeningState,
    StaleState,
    VerificationVerdict,
)
from research_harness.domain.ids import ClaimId, QuestionId
from research_harness.domain.research import ResearchQuestion

from .conftest import Registered, make_evidence

#: Every name this task added as a host read. All of them are `read` and none is human-only.
LIST_CAPABILITIES: tuple[str, ...] = (
    "anchor.list",
    "claim.list",
    "decision.list",
    "evidence.list",
    "question.list",
    "review.candidate",
    "state.index",
    "work.list",
)


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


def claim_of(
    statement: str,
    *,
    kind: ClaimType = ClaimType.DESCRIPTIVE,
    claim_id: str | None = None,
) -> Claim:
    """One Claim, spelled out, so a list test does not depend on the claim service."""
    return Claim(
        id=ClaimId(claim_id or "C0001"),
        statement=statement,
        type=kind,
        semantics=ClaimSemantics(subject="a", predicate="asserts", object="b"),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.INDIVIDUAL,
            allowed_strength=ClaimScope.INDIVIDUAL,
            status=ClaimStatus.UNVERIFIED,
        ),
        provenance=Provenance.human(),
    )


@pytest.fixture
def populated(project: CapabilityContext, registered: Registered) -> CapabilityContext:
    """A workspace holding one accepted Evidence, two Claims, a Question, and a note."""
    accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=make_evidence(registered).touch(id=PROVISIONAL_EVIDENCE_ID),
            verdict=VerificationVerdict.SUPPORTED,
        ),
    )
    create_claim(project, CreateClaimRequest(claim=claim_of("first", claim_id="C0001")))
    create_claim(
        project,
        CreateClaimRequest(claim=claim_of("second", kind=ClaimType.COMPARATIVE, claim_id="C0002")),
    )
    create_question(
        project,
        CreateQuestionRequest(
            question=ResearchQuestion(
                id=QuestionId("RQ0001"),
                question="Does tokenization matter?",
                provenance=Provenance.human(),
            )
        ),
    )
    add_note(project, AddNoteRequest(text="worth a second look"))
    return project


# -- permissions -------------------------------------------------------------


@pytest.mark.parametrize("name", LIST_CAPABILITIES)
def test_every_host_read_is_a_read(name: str, registry: CapabilityRegistry) -> None:
    """A list changes nothing, so an agent host may call it (Product 29, ADR-009)."""
    spec = registry.get(name)
    assert spec.permission is Permission.READ
    assert not spec.human_only
    assert not spec.descriptor().human_only


def test_an_agent_host_may_list_claims(populated: CapabilityContext) -> None:
    """The gap this closes: an MCP host had no way to answer "which claims are there?"."""
    registry = build_default_registry()
    answer = registry.invoke(
        "claim.list", populated, {}, principal=Principal.agent_host("some-host")
    )
    assert [claim.id for claim in answer.claims] == ["C0001", "C0002"]  # type: ignore[attr-defined]


# -- filters are applied server-side -----------------------------------------


def test_claim_list_filters_by_type(populated: CapabilityContext) -> None:
    registry = build_default_registry()
    answer = registry.invoke(
        "claim.list", populated, {"type": "comparative"}, principal=Principal.human()
    )
    assert [claim.id for claim in answer.claims] == ["C0002"]  # type: ignore[attr-defined]
    assert answer.count == 1  # type: ignore[attr-defined]


def test_claim_list_filters_by_status_and_staleness(populated: CapabilityContext) -> None:
    registry = build_default_registry()
    unverified = registry.invoke(
        "claim.list",
        populated,
        {"status": ClaimStatus.UNVERIFIED.value, "stale": StaleState.FRESH.value},
        principal=Principal.human(),
    )
    supported = registry.invoke(
        "claim.list",
        populated,
        {"status": ClaimStatus.SUPPORTED.value},
        principal=Principal.human(),
    )
    assert unverified.count == 2  # type: ignore[attr-defined]
    assert supported.count == 0  # type: ignore[attr-defined]


def test_evidence_list_answers_only_for_accepted_state(
    populated: CapabilityContext, registered: Registered
) -> None:
    """Staging holds proposals with no authority; this capability never reports them."""
    registry = build_default_registry()
    answer = registry.invoke(
        "evidence.list", populated, {"work": str(registered.work)}, principal=Principal.human()
    )
    assert [item.id for item in answer.evidence] == ["E0001"]  # type: ignore[attr-defined]
    assert {item.status for item in answer.evidence} == {  # type: ignore[attr-defined]
        EvidenceStatus.ACCEPTED.value
    }


def test_evidence_list_filters_by_status(populated: CapabilityContext) -> None:
    registry = build_default_registry()
    answer = registry.invoke(
        "evidence.list",
        populated,
        {"status": EvidenceStatus.PROPOSED.value},
        principal=Principal.human(),
    )
    assert answer.count == 0  # type: ignore[attr-defined]


def test_question_and_decision_lists_answer_from_canonical_state(
    populated: CapabilityContext,
) -> None:
    registry = build_default_registry()
    questions = registry.invoke("question.list", populated, {}, principal=Principal.human())
    decisions = registry.invoke("decision.list", populated, {}, principal=Principal.human())
    assert [item.id for item in questions.questions] == ["RQ0001"]  # type: ignore[attr-defined]
    assert questions.questions[0].status == QuestionStatus.OPEN.value  # type: ignore[attr-defined]
    assert decisions.count == 0  # type: ignore[attr-defined]


def test_work_list_carries_the_artifacts_and_counts_the_corpus_view_shows(
    populated: CapabilityContext, registered: Registered
) -> None:
    registry = build_default_registry()
    answer = registry.invoke("work.list", populated, {}, principal=Principal.human())
    work = answer.works[0]  # type: ignore[attr-defined]
    assert work.id == str(registered.work)
    assert [item.id for item in work.artifacts] == [str(registered.artifact)]
    assert work.evidence == 1


# -- the questions a researcher brings to the corpus -------------------------


def _works(context: CapabilityContext, request: dict[str, object] | None = None) -> object:
    registry = build_default_registry()
    return registry.invoke("work.list", context, request or {}, principal=Principal.human())


def test_the_question_vocabulary_is_the_one_the_request_accepts() -> None:
    """One list of questions, not two: the words and the closed type cannot drift."""
    assert [kind for kind, *_ in CORPUS_QUESTIONS] == list(get_args(CorpusQuestionKind))


def test_a_work_carries_what_the_corpus_is_asked_about_it(
    populated: CapabilityContext, registered: Registered
) -> None:
    """Readable, cited and arrived are the daemon's answers, not a client's inference."""
    work = _works(populated).works[0]  # type: ignore[attr-defined]

    assert work.id == str(registered.work)
    # Nothing has parsed the registered artifact, so no span in it can be anchored yet.
    assert work.readable is False
    assert work.evidence == 1
    # Two claims exist in this workspace and neither of them rests on that evidence.
    assert work.claims == 0
    assert work.added_at.startswith(str(datetime.now(UTC).year))
    # The same instant in words, as a day rather than a clock time: two sources are read
    # against each other, and a column of minutes would compare when someone was at a desk.
    assert work.added.endswith(str(datetime.now().astimezone().year))
    assert CORPUS_MONTHS[datetime.now().astimezone().month - 1] in work.added


def test_the_corpus_offers_only_the_questions_something_answers(
    populated: CapabilityContext,
) -> None:
    """A control that narrows a list to nothing is a dead end, not a filter."""
    answer = _works(populated)
    asked = {question.kind: question for question in answer.questions}  # type: ignore[attr-defined]

    # The one work has a file, no parse of it, one accepted evidence and no claim on it.
    assert set(asked) == {"unparsed", "uncited", "recent"}
    assert asked["unparsed"].count == 1
    assert asked["unparsed"].label == "No readable text"
    assert asked["unparsed"].summary == "1 of 1 works has no readable text yet."
    # "Nothing accepted" is not offered: this work's first missing thing is its parse, and
    # counting the same absence twice would give two controls that lead to the same row.
    assert "unread" not in asked
    assert "no_file" not in asked


def test_a_question_narrows_the_works_and_leaves_the_corpus_whole(
    populated: CapabilityContext,
) -> None:
    """The lead and the counts describe the corpus; only the rows are narrowed."""
    whole = _works(populated)
    narrowed = _works(populated, {"question": "unparsed"})
    empty = _works(populated, {"question": "screening"})

    assert narrowed.count == 1  # type: ignore[attr-defined]
    assert narrowed.total == whole.total == 1  # type: ignore[attr-defined]
    assert narrowed.question == "unparsed"  # type: ignore[attr-defined]
    assert narrowed.attention == whole.attention  # type: ignore[attr-defined]
    assert narrowed.questions == whole.questions  # type: ignore[attr-defined]

    # A question no work answers is an empty list of works, never an empty corpus.
    assert empty.count == 0  # type: ignore[attr-defined]
    assert empty.works == ()  # type: ignore[attr-defined]
    assert empty.total == 1  # type: ignore[attr-defined]


def test_an_unknown_question_is_refused_rather_than_answered_with_nothing(
    populated: CapabilityContext,
) -> None:
    """A typo must not read as "no works match": the vocabulary is closed."""
    registry = build_default_registry()
    with pytest.raises(Exception) as refusal:
        registry.invoke(
            "work.list", populated, {"question": "unreadable"}, principal=Principal.human()
        )
    assert "unreadable" in str(refusal.value) or "question" in str(refusal.value)


def test_a_claim_that_rests_on_a_work_takes_it_out_of_the_uncited_question(
    populated: CapabilityContext,
) -> None:
    """`claims` is the inverted edge: a Claim records its evidence, evidence records none."""
    evidence = _works(populated).works[0]  # type: ignore[attr-defined]
    assert evidence.claims == 0

    registry = build_default_registry()
    accepted = registry.invoke(
        "evidence.list", populated, {}, principal=Principal.human()
    ).evidence[0]  # type: ignore[attr-defined]
    registry.invoke(
        "claim.relate",
        populated,
        {
            "claim_id": "C0001",
            "relation": {"evidence": accepted.id, "relation": "supports"},
        },
        principal=Principal.human(),
    )

    after = _works(populated)
    assert after.works[0].claims == 1  # type: ignore[attr-defined]
    assert "uncited" not in {question.kind for question in after.questions}  # type: ignore[attr-defined]


# -- the orders a corpus may be read in --------------------------------------


def _corpus_of(*rows: tuple[str, str, int | None, int, int, str]) -> tuple[WorkSummary, ...]:
    """A corpus in the daemon's own order - by id - with the facts an order reads.

    Built by hand rather than through the repository because what is under test is the
    ordering itself: five works with the same title spelling would need five ingested PDFs
    to say anything about ties, and the summaries are what `order_works` is given.
    """
    return tuple(
        WorkSummary(
            id=work_id,
            title=title,
            screening=ScreeningState.INCLUDED.value,
            year=year,
            evidence=evidence,
            claims=claims,
            added=added[:10],
            added_at=added,
        )
        for work_id, title, year, evidence, claims, added in rows
    )


#: One corpus, read five different ways by the tests below.
#:
#: Deliberately disagreeing: the alphabetical first work is the newest, the most cited work
#: has the least accepted evidence, so an assertion can only pass by reading the fact its
#: order names.
ORDERED_CORPUS = _corpus_of(
    ("W0001", "Beta flows", 2021, 3, 0, "2026-03-01T09:00:00+00:00"),
    ("W0002", "alpha traffic", 2024, 1, 9, "2026-09-01T09:00:00+00:00"),
    ("W0003", "Gamma captures", 2019, 7, 4, "2026-01-01T09:00:00+00:00"),
)


def test_the_order_vocabulary_is_the_one_the_request_accepts() -> None:
    """One list of orders, not two: the words and the closed type cannot drift."""
    assert [kind for kind, _fact in CORPUS_ORDERS] == list(get_args(CorpusOrderKind))


@pytest.mark.parametrize(
    ("kind", "ascending"),
    [
        ("title", ["W0002", "W0001", "W0003"]),
        ("year", ["W0003", "W0001", "W0002"]),
        ("evidence", ["W0002", "W0001", "W0003"]),
        ("claims", ["W0001", "W0003", "W0002"]),
        ("added", ["W0003", "W0001", "W0002"]),
    ],
)
def test_each_order_reads_the_corpus_by_the_fact_it_names(
    kind: str, ascending: list[str]
) -> None:
    """Each order reads one fact of the row, and reverses whole when it is reversed.

    Title is compared with case folded, because a corpus sorted by capitalisation is a
    corpus sorted by nothing a researcher can see.
    """
    ordered = order_works(ORDERED_CORPUS, kind)
    assert [work.id for work in ordered] == ascending
    assert [work.id for work in order_works(ORDERED_CORPUS, kind, descending=True)] == list(
        reversed(ascending)
    )


def test_a_work_the_order_cannot_read_stays_at_the_end_either_way() -> None:
    """A missing year is not the smallest year: it is no year at all.

    Sorting it as a zero would put a work nobody has recorded a year for at the head of the
    ascending list, which is a claim about the paper. So the works the order cannot read
    trail the ones it can, in the daemon's own order, whichever way the rest is read.
    """
    corpus = ORDERED_CORPUS + _corpus_of(
        ("W0004", "Undated notes", None, 0, 0, ""),
        ("W0005", "Also undated", None, 0, 0, ""),
    )

    for descending in (False, True):
        by_year = order_works(corpus, "year", descending=descending)
        assert [work.id for work in by_year][-2:] == ["W0004", "W0005"]
        by_arrival = order_works(corpus, "added", descending=descending)
        assert [work.id for work in by_arrival][-2:] == ["W0004", "W0005"]


def test_works_an_order_cannot_tell_apart_keep_the_daemon_s_own_order() -> None:
    """A tie is not a licence to shuffle: equal rows stay in the order they arrived in."""
    corpus = _corpus_of(
        ("W0001", "One", 2024, 0, 0, "2026-01-01T09:00:00+00:00"),
        ("W0002", "Two", 2024, 0, 0, "2026-01-01T09:00:00+00:00"),
        ("W0003", "Three", 2024, 0, 0, "2026-01-01T09:00:00+00:00"),
    )

    assert [work.id for work in order_works(corpus, "evidence")] == ["W0001", "W0002", "W0003"]
    assert [work.id for work in order_works(corpus, "evidence", descending=True)] == [
        "W0001",
        "W0002",
        "W0003",
    ]


def test_the_corpus_keeps_the_daemon_s_order_when_nothing_asks_for_one(
    populated: CapabilityContext,
) -> None:
    """The default is the daemon's own order, and the answer says so by saying nothing."""
    answer = _works(populated)

    assert answer.order == ""  # type: ignore[attr-defined]
    assert answer.descending is False  # type: ignore[attr-defined]
    assert answer.works == workspace_index(populated.repo).works  # type: ignore[attr-defined]


def test_an_order_is_echoed_back_and_narrows_nothing(populated: CapabilityContext) -> None:
    """An order says how the rows are read, never which rows there are.

    The sentence beside the list has to be composed from the answer that produced the rows
    on screen rather than from a request still in flight, which is why the order is echoed
    the way the question already is.
    """
    answer = _works(populated, {"order": "evidence", "descending": True})
    whole = _works(populated)

    assert answer.order == "evidence"  # type: ignore[attr-defined]
    assert answer.descending is True  # type: ignore[attr-defined]
    assert answer.count == whole.count  # type: ignore[attr-defined]
    assert answer.total == whole.total  # type: ignore[attr-defined]
    assert answer.attention == whole.attention  # type: ignore[attr-defined]
    assert answer.questions == whole.questions  # type: ignore[attr-defined]


def test_an_order_composes_with_the_question_it_is_read_under(
    populated: CapabilityContext,
) -> None:
    """Asking the corpus something and reading the answer in an order are two decisions."""
    answer = _works(populated, {"question": "unparsed", "order": "title"})

    assert answer.question == "unparsed"  # type: ignore[attr-defined]
    assert answer.order == "title"  # type: ignore[attr-defined]
    assert [work.id for work in answer.works] == [  # type: ignore[attr-defined]
        work.id
        for work in _works(populated, {"question": "unparsed"}).works  # type: ignore[attr-defined]
    ]


def test_an_unknown_order_is_refused_rather_than_read_in_the_default_one(
    populated: CapabilityContext,
) -> None:
    """A typo must not read as "the corpus's own order": the vocabulary is closed."""
    registry = build_default_registry()
    with pytest.raises(Exception) as refusal:
        registry.invoke(
            "work.list", populated, {"order": "relevance"}, principal=Principal.human()
        )
    assert "relevance" in str(refusal.value) or "order" in str(refusal.value)


def test_the_index_and_work_list_still_return_identical_work_summaries(
    populated: CapabilityContext,
) -> None:
    """The optimisation `work.list` uses may never change the answer it gives."""
    listed = _works(populated)
    assert listed.works == workspace_index(populated.repo).works  # type: ignore[attr-defined]


def test_anchor_list_is_empty_rather_than_an_error_without_a_manuscript(
    populated: CapabilityContext,
) -> None:
    """A project with no manuscript has no anchors; that is an answer, not a failure."""
    registry = build_default_registry()
    answer = registry.invoke("anchor.list", populated, {}, principal=Principal.human())
    assert answer.count == 0  # type: ignore[attr-defined]


# -- the index and the capabilities are one answer ---------------------------


def test_state_index_composes_exactly_what_the_index_route_composes(
    populated: CapabilityContext,
) -> None:
    """`GET /index` and `state.index` are the same function, so they cannot drift."""
    registry = build_default_registry()
    through_capability = registry.invoke("state.index", populated, {}, principal=Principal.human())
    assert through_capability == workspace_index(populated.repo)


def test_the_index_and_claim_list_return_identical_claim_summaries(
    populated: CapabilityContext,
) -> None:
    registry = build_default_registry()
    listed = registry.invoke("claim.list", populated, {}, principal=Principal.human())
    index = workspace_index(populated.repo)
    assert listed.claims == index.claims  # type: ignore[attr-defined]


# -- reading one staged candidate --------------------------------------------


def test_review_candidate_reports_a_missing_candidate_as_not_found(
    populated: CapabilityContext,
) -> None:
    """A staging id that is not there is `object_not_found`, never an empty candidate."""
    from research_harness.workspace.repository import ObjectNotFoundError

    registry = build_default_registry()
    with pytest.raises(ObjectNotFoundError):
        registry.invoke(
            "review.candidate",
            populated,
            {"candidate_id": "cand_0000000000000000"},
            principal=Principal.human(),
        )


def test_review_candidate_returns_the_evidence_object_accept_takes(
    project: CapabilityContext, registered: Registered, tmp_path: Path
) -> None:
    """The point of the capability: read the candidate, post `evidence` back unchanged."""
    from research_harness.evidence.staging import (
        EvidenceCandidate,
        ExtractionProvenance,
        StagingStore,
    )

    del tmp_path
    staging = StagingStore(project.repo.layout.research_dir)
    candidate = EvidenceCandidate(
        candidate_id="cand_00000000000000ab",
        work=registered.work,
        artifact=registered.artifact,
        field="dataset",
        evidence=make_evidence(registered).touch(id=PROVISIONAL_EVIDENCE_ID),
        extraction=ExtractionProvenance(
            run_id="run-1",
            provider="scripted",
            model="scripted",
            template_version="v1",
            request_fingerprint="sha256:req",
            response_schema_fingerprint="sha256:schema",
        ),
    )
    staging.put(candidate)

    registry = build_default_registry()
    view = registry.invoke(
        "review.candidate",
        project,
        {"candidate_id": candidate.candidate_id},
        principal=Principal.human(),
    )
    assert view.candidate_id == candidate.candidate_id  # type: ignore[attr-defined]
    assert view.evidence["content"]["exact_text"]  # type: ignore[attr-defined]
    assert view.field == "dataset"  # type: ignore[attr-defined]

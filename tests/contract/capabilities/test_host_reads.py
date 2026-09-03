"""The list and read capabilities a host needs to find anything (Product 22, 28, 29).

The gap these close is stated in `docs/architecture/vscode.md`: the daemon published
`GET /index`, so the Web cockpit could list Claims and an MCP host could not, and a route
with no capability behind it is exactly the per-host divergence ADR-009 forbids. So the
rules asserted here are about *sameness*: every list is a `read`, every filter is applied
server-side, and `GET /index` composes the same summaries the capabilities return.
"""

from __future__ import annotations

from pathlib import Path

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
from research_harness.capabilities.reads import workspace_index
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

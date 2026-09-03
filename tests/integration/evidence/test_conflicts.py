"""ROADMAP Task 13.2: a disagreement becomes an object; agreement stays an opinion.

Two acceptance requirements drive this file. *Provider disagreement becomes a Review Inbox
conflict object* — one `ConflictRecord` holding both positions, ordered first in the queue,
with the first provider's verdict still on the candidate. And *agreement does not
auto-accept a Tier-2 scientific judgement under strict policy* — two providers that agree
write nothing at all, and the candidate is exactly where it was.

The extractor-versus-verifier conflict of Product §25 is materialized here too, and every
resolution goes through the human path: `ConflictStore.resolve` refuses a model actor, and
so does the review service that drives it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    EvidenceStatus,
    ReviewAction,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import AuthorityError
from research_harness.domain.evidence import Evidence, VerificationRecord
from research_harness.domain.ids import EvidenceId
from research_harness.evidence.conflicts import (
    ConflictKind,
    ConflictNotFoundError,
    ConflictRecord,
    ConflictStore,
    materialize_candidate_vs_accepted_conflict,
    materialize_extractor_verifier_conflict,
    materialize_provider_conflict,
)
from research_harness.evidence.extraction import extract_candidates
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.evidence.review import ReviewCategory, build_inbox
from research_harness.evidence.service import EvidenceReviewService
from research_harness.evidence.staging import (
    CandidateStatus,
    EvidenceCandidate,
    StagingStore,
)
from research_harness.providers.models.cross_verify import (
    CrossVerification,
    CrossVerificationGate,
    CrossVerifyPolicy,
    ProviderConflict,
    ProviderPosition,
)
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.roles.schemas import VerificationOutput
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.verify import run_verification
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.evidence.conftest import (
    ACTOR,
    DATASET_SENTENCE,
    WORK,
    canonical_digest,
    dataset_candidate,
    extraction_dict,
    metric_candidate,
)

RUN_ID = "run_20260101T000000Z_deadbeef"
MODEL_ACTOR = "vendor-a/model-x"

MEASURED = "94.32"
TABLE_QUOTE = "TrafficLM | CICIDS2017 | 94.32 | 93.10"

FIRST_RATIONALE = "The table cell states the value."
SECOND_RATIONALE = "The row belongs to another split."

NO_GATE_POLICY = CrossVerifyPolicy()
"""No gate enabled: verification stays single-provider unless a test asks for more."""


# -- fixtures and helpers ----------------------------------------------------


@pytest.fixture
def ctx(workspace: WorkspaceRepository) -> CapabilityContext:
    return CapabilityContext(repo=workspace, actor=ACTOR)


@pytest.fixture
def conflicts(staging: StagingStore) -> ConflictStore:
    return ConflictStore(staging.research_dir)


@pytest.fixture
def service(ctx: CapabilityContext, staging: StagingStore) -> EvidenceReviewService:
    return EvidenceReviewService(ctx, staging)


def verdict_dict(
    verdict: VerificationVerdict,
    *,
    quoted_support: str = TABLE_QUOTE,
    rationale: str = FIRST_RATIONALE,
    discrepancies: Sequence[str] = (),
) -> dict[str, Any]:
    """One `VerificationOutput` payload as a verifier would emit it."""
    return {
        "verdict": verdict.value,
        "rationale": rationale,
        "quoted_support": quoted_support,
        "discrepancies": list(discrepancies),
    }


def stage(
    doc: ParsedDocument,
    staging: StagingStore,
    builder: Callable[..., dict[str, Any]],
    field: str,
) -> EvidenceCandidate:
    """One candidate produced by the real extraction path, staged and unverified."""
    provider = ScriptedProvider(
        [extraction_dict([builder(doc)])], name="scripted-x", model="model-x"
    )
    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=[field], staging=staging
    )
    (candidate,) = result.candidates
    return candidate


def verifiers(second: VerificationVerdict) -> tuple[ScriptedProvider, ScriptedProvider]:
    """Two independent verifiers: the first answers twice (it also runs the cross-check).

    The first provider is the one whose verdict is staged; the second is only ever a second
    opinion, so a test can tell an overwrite from a conflict by reading the candidate back.
    """
    first = ScriptedProvider(
        [verdict_dict(VerificationVerdict.SUPPORTED)] * 2, name="scripted-a", model="model-a"
    )
    other = ScriptedProvider(
        [verdict_dict(second, rationale=SECOND_RATIONALE)], name="scripted-b", model="model-b"
    )
    return first, other


def numeric_run(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    second: VerificationVerdict,
) -> tuple[EvidenceCandidate, ScriptedProvider, ScriptedProvider, Any]:
    """Stage the numeric candidate and verify it with two providers cross-checking."""
    candidate = stage(doc, staging, metric_candidate, "metric_result")
    first, other = verifiers(second)
    report = run_verification(
        engine,
        staging,
        workspace,
        WORK,
        first,
        cross_verify_providers=[first, other],
    )
    return candidate, first, other, report


def accepted_evidence(repo: WorkspaceRepository) -> list[Evidence]:
    return [
        record for record in repo.iter_evidence(WORK) if record.status is EvidenceStatus.ACCEPTED
    ]


SUBJECT = "cand_0123456789abcdef"


def a_verification() -> CrossVerification:
    """One cross-verification whose two providers read the same span differently."""
    left = ProviderPosition(
        provider="vendor-a", model="model-x", fingerprint="fp-a", decision={"verdict": "supported"}
    )
    right = ProviderPosition(
        provider="vendor-b",
        model="model-y",
        fingerprint="fp-b",
        decision={"verdict": "contradicted"},
    )
    return CrossVerification(
        gate=CrossVerificationGate.NUMERIC_HIGH_IMPACT,
        eligible=True,
        positions=(left, right),
        conflict=ProviderConflict(
            subject=SUBJECT,
            gate=CrossVerificationGate.NUMERIC_HIGH_IMPACT,
            positions=(left, right),
            differing_fields=("verdict",),
            summary="vendor-a and vendor-b read the same span differently",
        ),
    )


def a_record() -> ConflictRecord:
    """The materialized form of :func:`a_verification`, for store-level tests."""
    record = materialize_provider_conflict(
        a_verification(), subject=SUBJECT, run_id=RUN_ID, current={"verdict": "supported"}
    )
    assert record is not None
    return record


# -- the store ---------------------------------------------------------------


def test_a_conflict_record_round_trips_through_the_store(conflicts: ConflictStore) -> None:
    record = a_record()

    path = conflicts.put(record)

    assert path == conflicts.root / record.subject / f"{record.conflict_id}.json"
    assert path.is_file()
    assert conflicts.get(record.conflict_id) == record
    assert conflicts.list() == [record]
    assert conflicts.list(subject=record.subject, status="open") == [record]
    assert conflicts.open_for(record.subject) == [record]
    assert conflicts.subjects() == [record.subject]
    assert conflicts.list(subject="cand_ffffffffffffffff") == []


def test_an_unknown_conflict_is_an_error_rather_than_a_silent_empty(
    conflicts: ConflictStore,
) -> None:
    with pytest.raises(ConflictNotFoundError):
        conflicts.get("conf_0000000000000000")


def test_the_same_disagreement_recorded_twice_is_one_conflict(conflicts: ConflictStore) -> None:
    """Conflict ids are content-addressed, so a re-run cannot pile up duplicates."""
    record = a_record()
    conflicts.open_or_put(record)
    resolved = conflicts.resolve(record.conflict_id, "reject", "the table row was misread", ACTOR)

    rederived = a_record()
    again = conflicts.open_or_put(rederived)

    assert rederived.conflict_id == record.conflict_id, "the same disagreement, the same id"
    assert again == resolved, "a re-run must not reopen a conflict a researcher answered"
    assert conflicts.list() == [resolved]


# -- provider A versus provider B --------------------------------------------


def test_two_providers_that_disagree_produce_exactly_one_conflict_object(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
) -> None:
    candidate, _, _, report = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.CONTRADICTED
    )

    stored = conflicts.list()
    assert len(stored) == 1, "one disagreement is one conflict, never two"
    (record,) = stored
    assert report.conflicts == stored
    assert record.kind is ConflictKind.PROVIDER_DISAGREEMENT
    assert record.subject == candidate.candidate_id
    assert record.gate is CrossVerificationGate.NUMERIC_HIGH_IMPACT
    assert record.differing_fields == ("verdict",)
    assert record.labels == ("scripted-a/model-a", "scripted-b/model-b")
    assert record.tier is ReviewTier.TIER_2
    assert record.is_open and record.resolution is None
    assert record.run_id == report.run.run_id
    assert [change["to"] for change in record.proposed_changes] == ["supported", "contradicted"]
    assert {change["from"] for change in record.proposed_changes} == {"supported"}


def test_the_second_provider_never_overwrites_the_first_ones_verdict(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    """Gate P13: one explicit conflict rather than one provider silently overwriting another."""
    candidate, _, _, _ = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.CONTRADICTED
    )

    staged = staging.get(candidate.candidate_id)
    assert staged.verification is not None
    assert staged.verification.verdict is VerificationVerdict.SUPPORTED
    assert staged.verification.rationale == FIRST_RATIONALE
    assert staged.verifier == "scripted-a/model-a"
    assert staged.status is CandidateStatus.VERIFIED
    assert staged.review_action is None


def test_provider_agreement_materializes_nothing_and_leaves_the_candidate_alone(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
) -> None:
    before = canonical_digest(workspace.root)
    candidate, _, _, report = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.SUPPORTED
    )

    verification = report.cross_verifications[candidate.candidate_id]
    assert verification.agreement is True
    assert verification.conflict is None
    assert report.conflicts == []
    assert conflicts.list() == []
    assert not conflicts.root.exists(), "agreement writes nothing at all"

    staged = staging.get(candidate.candidate_id)
    assert staged.verification == report.candidates[0].verification
    assert staged.verification is not None
    assert staged.verification.rationale == FIRST_RATIONALE
    assert staged.evidence.status is EvidenceStatus.VERIFIED
    assert canonical_digest(workspace.root) == before


def test_agreement_does_not_auto_accept_a_tier_2_judgement_under_strict_policy(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    candidate, _, _, _ = numeric_run(doc, engine, staging, workspace, VerificationVerdict.SUPPORTED)

    staged = staging.get(candidate.candidate_id)
    assert staged.review_tier == int(ReviewTier.TIER_2)
    assert staged.status is CandidateStatus.VERIFIED
    assert accepted_evidence(workspace) == []

    model_service = EvidenceReviewService(
        CapabilityContext(repo=workspace, actor=MODEL_ACTOR), staging
    )
    with pytest.raises(AuthorityError):
        model_service.accept(candidate.candidate_id)
    assert accepted_evidence(workspace) == []


def test_a_routine_candidate_is_never_cross_verified(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
) -> None:
    """Product §20.4: a non-numeric, uncontradicted candidate does not buy a second call."""
    stage(doc, staging, dataset_candidate, "dataset")
    first = ScriptedProvider(
        [verdict_dict(VerificationVerdict.SUPPORTED, quoted_support=DATASET_SENTENCE)],
        name="scripted-a",
        model="model-a",
    )
    other = ScriptedProvider([], name="scripted-b", model="model-b")

    report = run_verification(
        engine, staging, workspace, WORK, first, cross_verify_providers=[first, other]
    )

    assert report.cross_verifications == {}
    assert report.conflicts == []
    assert conflicts.list() == []
    assert other.requests == [], "the second provider was never called"


def test_a_disabled_gate_buys_no_second_opinion_even_for_a_number(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
) -> None:
    stage(doc, staging, metric_candidate, "metric_result")
    first = ScriptedProvider(
        [verdict_dict(VerificationVerdict.SUPPORTED)], name="scripted-a", model="model-a"
    )
    other = ScriptedProvider([], name="scripted-b", model="model-b")

    run_verification(
        engine,
        staging,
        workspace,
        WORK,
        first,
        cross_verify_providers=[first, other],
        policy=NO_GATE_POLICY,
    )

    assert other.requests == []
    assert conflicts.list() == []


# -- extractor versus verifier -----------------------------------------------


def test_the_extractor_and_the_verifier_disagreeing_is_a_conflict(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    contradicted = staging.mark_verified(
        candidate.candidate_id,
        VerificationOutput(
            verdict=VerificationVerdict.CONTRADICTED,
            rationale="The span describes the training corpus, not the evaluation one.",
            quoted_support=DATASET_SENTENCE,
            discrepancies=["the sentence is about training data"],
        ),
        "scripted-v/model-v",
    )

    record = materialize_extractor_verifier_conflict(contradicted, run_id=RUN_ID)

    assert record is not None
    assert record.kind is ConflictKind.EXTRACTOR_VERIFIER
    assert record.subject == candidate.candidate_id
    assert record.gate is None
    assert record.differing_fields == ("verdict",)
    assert record.labels == ("scripted-x/model-x", "scripted-v/model-v")
    assert [position.decision["verdict"] for position in record.positions] == [
        "asserted",
        "contradicted",
    ]
    assert "the sentence is about training data" in record.summary
    assert record.as_provider_conflict() is None, "it is not a provider disagreement"


def test_a_candidate_that_reads_an_accepted_span_differently_is_a_conflict(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    accepted = candidate.evidence.touch(
        id=EvidenceId.make(1),
        content=candidate.evidence.content.touch(exact_text="All experiments use UNSW-NB15"),
        verification=VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by=ACTOR),
    )

    record = materialize_candidate_vs_accepted_conflict(candidate, accepted, run_id=RUN_ID)

    assert record is not None
    assert record.kind is ConflictKind.CANDIDATE_VS_ACCEPTED
    assert record.subject == candidate.candidate_id
    assert record.differing_fields == ("exact_text",)
    assert record.labels == ("scripted-x/model-x", f"accepted/{accepted.id}")
    assert [change["from"] for change in record.proposed_changes] == [
        "All experiments use UNSW-NB15"
    ]
    assert [change["to"] for change in record.proposed_changes] == [DATASET_SENTENCE]


def test_a_candidate_that_agrees_with_accepted_state_is_no_conflict(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    same = candidate.evidence.touch(
        id=EvidenceId.make(1),
        verification=VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by=ACTOR),
    )
    elsewhere = same.touch(source=same.source.touch(char_start=0, char_end=5))

    assert materialize_candidate_vs_accepted_conflict(candidate, same) is None
    assert materialize_candidate_vs_accepted_conflict(candidate, elsewhere) is None


def test_a_supported_candidate_is_no_extractor_verifier_conflict(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    supported = staging.mark_verified(
        candidate.candidate_id,
        VerificationOutput(
            verdict=VerificationVerdict.SUPPORTED,
            rationale="The span states the candidate.",
            quoted_support=DATASET_SENTENCE,
        ),
        "scripted-v/model-v",
    )

    assert materialize_extractor_verifier_conflict(supported) is None
    assert materialize_extractor_verifier_conflict(candidate) is None


# -- the inbox ---------------------------------------------------------------


def test_the_inbox_puts_a_materialized_conflict_first(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    routine = stage(doc, staging, dataset_candidate, "dataset")
    staging.mark_verified(
        routine.candidate_id,
        VerificationOutput(
            verdict=VerificationVerdict.SUPPORTED,
            rationale="The span states the candidate.",
            quoted_support=DATASET_SENTENCE,
        ),
        "scripted-v/model-v",
    )
    disputed, _, _, _ = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.CONTRADICTED
    )

    queue = build_inbox(staging, workspace)

    first = queue.next()
    assert first is not None
    assert first.candidate_id == disputed.candidate_id
    assert first.category is ReviewCategory.CONFLICT
    assert first.priority == 0
    assert any("providers disagree on verdict" in reason for reason in first.reasons)
    assert first.provider_conflict is not None
    assert [position.label for position in first.provider_conflict.positions] == [
        "scripted-a/model-a",
        "scripted-b/model-b",
    ]
    assert [record.kind for record in first.conflict_records] == [
        ConflictKind.PROVIDER_DISAGREEMENT
    ]
    assert len(first.proposed_changes) == 2
    assert queue.counts[ReviewCategory.CONFLICT] == 1
    assert len(queue.conflicts) == 1
    assert first.as_dict()["conflicts"][0]["conflict_id"] == queue.conflicts[0].conflict_id
    assert queue.items[1].candidate_id == routine.candidate_id


def test_a_resolved_conflict_leaves_the_queue(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
    service: EvidenceReviewService,
) -> None:
    candidate, _, _, _ = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.CONTRADICTED
    )
    (record,) = conflicts.list()

    service.resolve_conflict(candidate.candidate_id, "defer", "ask the authors first")

    queue = build_inbox(staging, workspace)
    item = queue.by_id(candidate.candidate_id)
    assert queue.conflicts == ()
    assert item is not None and item.conflict_records == ()
    assert conflicts.get(record.conflict_id).status == "resolved"


# -- resolution is a human act -----------------------------------------------


def test_a_model_actor_cannot_resolve_a_conflict(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
) -> None:
    candidate, _, _, _ = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.CONTRADICTED
    )
    (record,) = conflicts.list()
    model_service = EvidenceReviewService(
        CapabilityContext(repo=workspace, actor=MODEL_ACTOR), staging
    )

    with pytest.raises(AuthorityError):
        conflicts.resolve(record.conflict_id, "accept", "the numbers match", MODEL_ACTOR)
    with pytest.raises(AuthorityError):
        model_service.resolve_conflict(candidate.candidate_id, "accept", "the numbers match")

    assert conflicts.get(record.conflict_id).is_open
    assert accepted_evidence(workspace) == []


def test_resolving_a_conflict_accepts_through_the_human_path_and_closes_the_record(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
    service: EvidenceReviewService,
) -> None:
    candidate, _, _, _ = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.CONTRADICTED
    )
    (record,) = conflicts.list()

    result = service.resolve_conflict(
        candidate.candidate_id, "accept", "I read the table; the row is the held-out split"
    )

    assert result is not None and result.event.event.value == "evidence.accepted"
    assert [item.content.exact_text for item in accepted_evidence(workspace)] == [MEASURED]
    resolved = conflicts.get(record.conflict_id)
    assert resolved.status == "resolved"
    assert resolved.resolution is not None
    assert resolved.resolution.choice == "accept"
    assert resolved.resolution.actor == ACTOR
    assert resolved.resolution.reason.startswith("I read the table")
    assert staging.get(candidate.candidate_id).review_action is ReviewAction.ACCEPT


def test_resolving_a_conflict_can_reject_instead_and_still_closes_the_record(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
    service: EvidenceReviewService,
) -> None:
    candidate, _, _, _ = numeric_run(
        doc, engine, staging, workspace, VerificationVerdict.CONTRADICTED
    )
    (record,) = conflicts.list()

    result = service.resolve_conflict(
        candidate.candidate_id, "reject", "the second reader is right; the row is another split"
    )

    assert result is not None and result.event.event.value == "evidence.rejected"
    assert accepted_evidence(workspace) == []
    assert len(list(workspace.iter_rejections(WORK))) == 1
    assert conflicts.get(record.conflict_id).status == "resolved"


def test_naming_another_candidates_conflict_is_refused(
    doc: ParsedDocument,
    staging: StagingStore,
    conflicts: ConflictStore,
    service: EvidenceReviewService,
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    record = conflicts.open_or_put(a_record())

    with pytest.raises(Exception) as failure:
        service.resolve_conflict(
            candidate.candidate_id, "defer", "not mine", conflict_id=record.conflict_id
        )

    assert "is about" in str(failure.value)
    assert conflicts.get(record.conflict_id).is_open

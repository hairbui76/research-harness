"""ROADMAP Task 6.3 acceptance: the strict review gate, against a real parsed document.

The three acceptance requirements are the three sections below. Partial acceptance splits a
source fact from the interpretation attached to it and produces exactly one accepted
Evidence; model confidence never appears as an input, and no confidence field is even
reachable from this path; batch acceptance happens only under explicit deterministic
conditions, and every skip names the condition it failed.

Underneath all three sits Product §42 H: a model actor cannot walk through this gate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStatus,
    NoteStatus,
    ReviewAction,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.domain.evidence import Evidence, EvidenceContent, Interpretation
from research_harness.domain.ids import EvidenceId, InterpretationId
from research_harness.domain.transitions import BatchPolicyConditions
from research_harness.evidence.extraction import extract_candidates
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.evidence.review import ReviewCategory, build_inbox, stored_documents
from research_harness.evidence.service import EvidenceReviewService
from research_harness.evidence.staging import (
    PROVISIONAL_EVIDENCE_ID,
    CandidateStatus,
    EvidenceCandidate,
    StagingStore,
)
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.roles.schemas import VerificationOutput
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.evidence.conftest import (
    ACTOR,
    DATASET_SENTENCE,
    WORK,
    canonical_digest,
    dataset_candidate,
    extraction_dict,
    limitation_candidate,
    method_candidate,
    metric_candidate,
)

RUN_ID = "run_20260101T000000Z_deadbeef"
MODEL_ACTOR = "vendor-a/model-x"

LIMITATION_QUOTE = "We do not claim transfer to other networks"
METHOD_QUOTE = "The encoder is a twelve layer transformer"


# -- fixtures ----------------------------------------------------------------


@pytest.fixture
def ctx(workspace: WorkspaceRepository) -> CapabilityContext:
    """The researcher's capability context over the fixture workspace."""
    return CapabilityContext(repo=workspace, actor=ACTOR)


@pytest.fixture
def service(ctx: CapabilityContext, staging: StagingStore) -> EvidenceReviewService:
    return EvidenceReviewService(ctx, staging)


def stage(
    doc: ParsedDocument,
    staging: StagingStore,
    builder: Callable[..., dict[str, Any]],
    field: str,
    **overrides: Any,
) -> EvidenceCandidate:
    """One candidate produced by the real extraction path, staged and unverified."""
    provider = ScriptedProvider(
        [extraction_dict([builder(doc, **overrides)])], name="scripted-a", model="model-a"
    )
    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=[field], staging=staging
    )
    (candidate,) = result.candidates
    return candidate


def verified(
    staging: StagingStore,
    candidate: EvidenceCandidate,
    verdict: VerificationVerdict,
    quote: str,
) -> EvidenceCandidate:
    """Attach an independent verification result the way the verify workflow does."""
    output = VerificationOutput(
        verdict=verdict, rationale="an independent reading", quoted_support=quote
    )
    return staging.mark_verified(candidate.candidate_id, output, "scripted-v/model-v")


def accepted_evidence(repo: WorkspaceRepository) -> list[Evidence]:
    return [
        record for record in repo.iter_evidence(WORK) if record.status is EvidenceStatus.ACCEPTED
    ]


# -- Product §42 H: a model cannot walk through the gate ---------------------


def test_a_model_actor_cannot_accept_a_candidate(
    workspace: WorkspaceRepository, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    before = canonical_digest(workspace.root)
    model_service = EvidenceReviewService(
        CapabilityContext(repo=workspace, actor=MODEL_ACTOR), staging
    )

    with pytest.raises(AuthorityError) as failure:
        model_service.accept(candidate.candidate_id)

    assert "human actor" in str(failure.value)
    assert accepted_evidence(workspace) == []
    assert canonical_digest(workspace.root) == before
    assert staging.get(candidate.candidate_id).status is CandidateStatus.VERIFIED


def test_a_model_actor_cannot_run_a_batch_either(
    workspace: WorkspaceRepository, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    model_service = EvidenceReviewService(
        CapabilityContext(repo=workspace, actor=MODEL_ACTOR), staging
    )

    with pytest.raises(AuthorityError):
        model_service.accept_batch(conditions=_all_conditions())

    assert accepted_evidence(workspace) == []


# -- Product §24.4: batch acceptance needs deterministic conditions ----------


def test_batch_under_strict_policy_without_conditions_is_refused(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    before = canonical_digest(service.ctx.root)

    with pytest.raises(AuthorityError) as failure:
        service.accept_batch()

    assert "strict" in str(failure.value)
    assert canonical_digest(service.ctx.root) == before


def test_batch_refuses_conditions_that_are_not_all_declared(
    service: EvidenceReviewService,
) -> None:
    with pytest.raises(AuthorityError) as failure:
        service.accept_batch(conditions=BatchPolicyConditions(verifier_supported=True))

    assert "anchor_valid" in str(failure.value)


def test_batch_with_conditions_accepts_only_qualifying_candidates_and_reports_skips(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    routine = stage(doc, staging, dataset_candidate, "dataset")
    numeric = stage(doc, staging, metric_candidate, "metric_result")
    unclear = stage(doc, staging, method_candidate, "method_summary")
    verified(staging, routine, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    verified(staging, numeric, VerificationVerdict.SUPPORTED, "94.32")
    verified(staging, unclear, VerificationVerdict.PARTIALLY_SUPPORTED, METHOD_QUOTE)

    result = service.accept_batch(conditions=_all_conditions())

    assert result.accepted == (routine.candidate_id,)
    assert set(result.skipped) == {numeric.candidate_id, unclear.candidate_id}
    assert "numeric evidence is never low risk" in result.skipped[numeric.candidate_id]
    assert "tier 2" in result.skipped[numeric.candidate_id]
    assert "not supported" in result.skipped[unclear.candidate_id]

    records = accepted_evidence(service.ctx.repo)
    assert [record.content.field for record in records] == ["dataset"]
    assert records[0].verification.accepted_by == ACTOR
    assert staging.get(routine.candidate_id).review_action is ReviewAction.ACCEPT


def test_a_dry_run_reports_what_it_would_accept_and_writes_nothing(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    routine = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, routine, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    before = canonical_digest(service.ctx.root)

    result = service.accept_batch(conditions=_all_conditions(), dry_run=True)

    assert result.accepted == (routine.candidate_id,)
    assert result.mutations == ()
    assert canonical_digest(service.ctx.root) == before
    assert staging.get(routine.candidate_id).status is CandidateStatus.VERIFIED


def test_a_competing_candidate_blocks_a_batch(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    first = stage(doc, staging, dataset_candidate, "dataset")
    second = stage(
        doc,
        staging,
        dataset_candidate,
        "dataset",
        exact_text="All experiments use",
        char_start=0,
        char_end=19,
    )
    verified(staging, first, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    verified(staging, second, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)

    result = service.accept_batch(conditions=_all_conditions())

    assert result.accepted == ()
    assert all("competing candidate" in reason for reason in result.skipped.values())


def test_a_previously_rejected_span_is_never_batch_accepted(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    """A recorded researcher refusal outranks any policy that would re-accept it."""
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    service.reject(candidate.candidate_id, "the span names the corpus, not the eval split")
    reproposed = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, reproposed, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)

    result = service.accept_batch(conditions=_all_conditions())

    assert result.accepted == ()
    assert "previously rejected" in result.skipped[reproposed.candidate_id]
    assert accepted_evidence(service.ctx.repo) == []


# -- Product §24.3: partial acceptance ---------------------------------------


def test_split_acceptance_accepts_the_fact_and_stages_the_interpretation(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, limitation_candidate, "author_limitation")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, LIMITATION_QUOTE)

    outcome = service.split_accept(
        candidate.candidate_id,
        fact=candidate.evidence,
        interpretation=_interpretation("The method therefore does not generalise."),
    )

    records = accepted_evidence(service.ctx.repo)
    assert len(records) == 1
    assert records[0].id == outcome.evidence
    assert records[0].origin is EvidenceOrigin.AUTHOR_CLAIMED
    assert records[0].content.exact_text == LIMITATION_QUOTE

    assert outcome.interpretation_candidate is not None
    staged = staging.get(outcome.interpretation_candidate)
    assert staged.evidence.review_tier is ReviewTier.TIER_2
    assert staged.evidence.origin is EvidenceOrigin.AUTHOR_INTERPRETED
    assert staged.evidence.id == PROVISIONAL_EVIDENCE_ID
    assert staged.field == "author_limitation:interpretation"
    assert staged.evidence.source == candidate.evidence.source
    assert str(outcome.evidence) in (staged.evidence.provenance.note or "")


def test_split_acceptance_can_reject_the_interpretation_instead(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, limitation_candidate, "author_limitation")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, LIMITATION_QUOTE)
    fact = candidate.evidence.touch(
        content=EvidenceContent(exact_text=LIMITATION_QUOTE, field="author_limitation")
    )

    outcome = service.split_accept(
        candidate.candidate_id,
        fact=fact,
        reject_interpretation_reason="the source does not say the method fails elsewhere",
    )

    assert len(accepted_evidence(service.ctx.repo)) == 1
    assert outcome.interpretation_candidate is None
    assert outcome.rejected is not None
    (record,) = list(service.ctx.repo.iter_rejections(WORK))
    assert record.field == "author_limitation:interpretation"
    assert record.reason.startswith("the source does not say")


def test_a_split_refuses_an_interpretive_fact_and_an_unanchored_one(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    interpretive = candidate.evidence.touch(origin=EvidenceOrigin.MODEL_PROPOSED)

    with pytest.raises(CapabilityError) as failure:
        service.split_accept(
            candidate.candidate_id,
            fact=interpretive,
            interpretation=_interpretation("A reading of the span."),
        )
    assert "source fact" in str(failure.value)

    with pytest.raises(CapabilityError) as both:
        service.split_accept(
            candidate.candidate_id,
            fact=candidate.evidence,
            interpretation=_interpretation("A reading."),
            reject_interpretation_reason="and also rejected",
        )
    assert "exactly one" in str(both.value)
    assert accepted_evidence(service.ctx.repo) == []


# -- rejection is durable ----------------------------------------------------


def test_a_previously_rejected_span_is_flagged_when_it_is_proposed_again(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    service.reject(candidate.candidate_id, "the sentence names a corpus, not the eval split")

    assert staging.get(candidate.candidate_id).status is CandidateStatus.REVIEWED
    assert staging.get(candidate.candidate_id).review_action is ReviewAction.REJECT
    assert len(build_inbox(staging, service.ctx.repo)) == 0

    # A later interrogation run proposes the identical span again.
    reproposed = stage(doc, staging, dataset_candidate, "dataset")
    queue = build_inbox(
        staging, service.ctx.repo, parsed=stored_documents(service.ctx.repo, [WORK])
    )

    item = queue.by_id(reproposed.candidate_id)
    assert item is not None
    assert item.previously_rejected is True
    assert "previously rejected" in " ".join(item.reasons)
    assert accepted_evidence(service.ctx.repo) == []


def test_a_rejection_survives_a_deleted_staging_tree(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    service.reject(candidate.candidate_id, "not what the span says")
    _delete_tree(service.ctx.repo.layout.research_dir)

    reopened = WorkspaceRepository.open(service.ctx.root)
    (record,) = list(reopened.iter_rejections(WORK))

    assert record.candidate_id == candidate.candidate_id
    assert record.anchor == candidate.evidence.source
    assert reopened.consistency.consistent, reopened.consistency.summary()


# -- the non-deciding actions ------------------------------------------------


def test_a_deferred_candidate_keeps_its_note_and_stays_in_the_queue(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    before = canonical_digest(service.ctx.root)

    updated = service.defer(candidate.candidate_id, "check against the v2 preprint first")

    assert updated.review_action is ReviewAction.DEFER
    assert updated.status is CandidateStatus.VERIFIED
    assert updated.evidence.verification.rationale == "check against the v2 preprint first"
    assert canonical_digest(service.ctx.root) == before
    assert build_inbox(staging, service.ctx.repo).by_id(candidate.candidate_id) is not None


def test_requesting_more_evidence_captures_a_durable_note(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")

    result = service.request_more_evidence(candidate.candidate_id, "need the split sizes")

    assert result.event.event.value == "note.captured"
    notes = list(service.ctx.repo.iter_notes())
    assert len(notes) == 1
    assert notes[0].status is NoteStatus.CAPTURED
    assert candidate.candidate_id in notes[0].text
    assert staging.get(candidate.candidate_id).review_action is ReviewAction.REQUEST_MORE_EVIDENCE
    assert accepted_evidence(service.ctx.repo) == []


def test_a_candidate_cannot_be_accepted_twice(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    service.accept(candidate.candidate_id)

    with pytest.raises(CapabilityError) as failure:
        service.accept(candidate.candidate_id)

    assert "already accepted" in str(failure.value)
    assert len(accepted_evidence(service.ctx.repo)) == 1


def test_acceptance_allocates_the_evidence_id_and_leaves_staging_without_authority(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    first = stage(doc, staging, dataset_candidate, "dataset")
    second = stage(doc, staging, limitation_candidate, "author_limitation")
    verified(staging, first, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    verified(staging, second, VerificationVerdict.SUPPORTED, LIMITATION_QUOTE)

    service.accept(first.candidate_id)
    service.accept(
        second.candidate_id,
        action=ReviewAction.ACCEPT_WITH_QUALIFICATION,
        qualification="holds for the studied capture only",
    )

    records = accepted_evidence(service.ctx.repo)
    assert [record.id for record in records] == [EvidenceId("E0001"), EvidenceId("E0002")]
    assert records[1].qualification == "holds for the studied capture only"
    assert staging.get(first.candidate_id).evidence.id == PROVISIONAL_EVIDENCE_ID


def test_an_edit_accepts_the_researcher_text_and_never_moves_the_anchor(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    corrected = candidate.evidence.touch(
        content=EvidenceContent(exact_text="All experiments use CICIDS2017.", field="dataset")
    )

    result = service.accept(candidate.candidate_id, action=ReviewAction.EDIT, edited=corrected)

    (record,) = accepted_evidence(service.ctx.repo)
    assert record.content.exact_text == "All experiments use CICIDS2017."
    assert record.source == candidate.evidence.source
    assert record.verification.review_action is ReviewAction.ACCEPT
    assert "researcher's edit" in " ".join(result.validation.warnings)
    assert staging.get(candidate.candidate_id).review_action is ReviewAction.EDIT


def test_an_edit_that_moves_the_anchor_is_refused(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    elsewhere = candidate.evidence.touch(
        source=candidate.evidence.source.touch(char_start=0, char_end=5)
    )

    with pytest.raises(CapabilityError) as failure:
        service.accept(candidate.candidate_id, action=ReviewAction.EDIT, edited=elsewhere)

    assert "never the source anchor" in str(failure.value)
    assert accepted_evidence(service.ctx.repo) == []


def test_a_conflict_can_also_be_accepted_or_deferred_by_the_researcher(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    kept = stage(doc, staging, dataset_candidate, "dataset")
    deferred = stage(doc, staging, limitation_candidate, "author_limitation")
    verified(staging, kept, VerificationVerdict.CONTRADICTED, DATASET_SENTENCE)
    verified(staging, deferred, VerificationVerdict.CONTRADICTED, LIMITATION_QUOTE)

    accepted = service.resolve_conflict(
        kept.candidate_id, "accept", "I read the span; the verifier misread the tense"
    )
    later = service.resolve_conflict(
        deferred.candidate_id, "defer", "ask the authors before deciding"
    )

    assert accepted is not None and accepted.event.event.value == "evidence.accepted"
    assert later is None
    assert [record.content.field for record in accepted_evidence(service.ctx.repo)] == ["dataset"]
    assert staging.get(deferred.candidate_id).review_action is ReviewAction.DEFER
    with pytest.raises(CapabilityError):
        service.resolve_conflict(deferred.candidate_id, "reject", "   ")


def test_a_conflict_is_resolved_by_the_researcher_and_never_by_a_verdict(
    service: EvidenceReviewService, staging: StagingStore, doc: ParsedDocument
) -> None:
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.CONTRADICTED, DATASET_SENTENCE)
    queue = build_inbox(staging, service.ctx.repo)
    item = queue.by_id(candidate.candidate_id)
    assert item is not None and item.category is ReviewCategory.CONFLICT

    result = service.resolve_conflict(
        candidate.candidate_id, "reject", "the verifier is right; the span is about training"
    )

    assert result is not None and result.event.event.value == "evidence.rejected"
    assert accepted_evidence(service.ctx.repo) == []
    assert len(list(service.ctx.repo.iter_rejections(WORK))) == 1


# -- helpers -----------------------------------------------------------------


def _all_conditions() -> BatchPolicyConditions:
    return BatchPolicyConditions(
        verifier_supported=True,
        anchor_valid=True,
        no_competing_candidate=True,
        low_risk_field=True,
        no_accepted_state_conflict=True,
    )


def _interpretation(text: str) -> Interpretation:
    from research_harness.domain.base import Provenance

    return Interpretation(
        id=InterpretationId("I0001"),
        evidence=(PROVISIONAL_EVIDENCE_ID,),
        text=text,
        origin=EvidenceOrigin.AUTHOR_INTERPRETED,
        provenance=Provenance.human(ACTOR),
    )


def _delete_tree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)

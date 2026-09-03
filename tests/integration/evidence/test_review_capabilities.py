"""The candidate-keyed review capabilities: one queue, one gate, one set of paths.

`docs/architecture/web.md` recorded the gap these close: `evidence.accept` takes an
`Evidence` object rather than a staging id and does not mark the candidate reviewed, so
Accept-with-qualification and Edit wrote canonical Evidence correctly and left the item
sitting in the queue. Only `EvidenceReviewService` marks staging, and its only transport
was `review.resolve_conflict`, which offers accept/reject/defer and nothing else.

So the rules asserted here are:

* every review action a researcher can take has a capability that takes the *candidate id*;
* each one goes through `EvidenceReviewService`, so the canonical write, the review gate,
  and the staging mark stay one path (ADR-004) - `review.accept` and
  `review.resolve_conflict` with ``choice="accept"`` produce the same canonical result;
* an agent host cannot take any of them, deferring included (ADR-007);
* `evidence.accept` closes the queue item too when the caller names the candidate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.permissions import Permission, PermissionDenied, Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStatus,
    NoteStatus,
    ReviewAction,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.evidence import Evidence
from research_harness.evidence.staging import CandidateStatus, EvidenceCandidate, StagingStore
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.evidence.conftest import (
    ACTOR,
    DATASET_SENTENCE,
    WORK,
    canonical_digest,
    dataset_candidate,
    metric_candidate,
)
from tests.integration.evidence.test_review_gate import stage, verified

#: The review actions of Product 24.3, and the permission each one holds. Partial
#: acceptance (`review.split`) is the seventh: it was reachable only from Python until the
#: dogfood session asked for it at the queue.
REVIEW_CAPABILITIES: dict[str, Permission] = {
    "review.accept": Permission.MUTATE,
    "review.qualify": Permission.MUTATE,
    "review.edit": Permission.MUTATE,
    "review.reject": Permission.MUTATE,
    "review.split": Permission.MUTATE,
    "review.defer": Permission.STAGE,
    "review.request_more": Permission.STAGE,
}


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def ctx(workspace: WorkspaceRepository) -> CapabilityContext:
    return CapabilityContext(repo=workspace, actor=ACTOR)


@pytest.fixture
def dataset(staging: StagingStore, doc: Any) -> EvidenceCandidate:
    """One verified candidate waiting in the queue."""
    candidate = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, candidate, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    return candidate


def call(
    registry: CapabilityRegistry, ctx: CapabilityContext, name: str, request: dict[str, Any]
) -> Any:
    """One capability call as the researcher, through the one path every transport uses."""
    return registry.invoke(name, ctx, request, principal=Principal.human())


def accepted(repo: WorkspaceRepository) -> list[Evidence]:
    return [item for item in repo.iter_evidence(WORK) if item.status is EvidenceStatus.ACCEPTED]


# -- permissions -------------------------------------------------------------


@pytest.mark.parametrize(("name", "permission"), sorted(REVIEW_CAPABILITIES.items()))
def test_every_review_action_is_a_researcher_act(
    name: str, permission: Permission, registry: CapabilityRegistry
) -> None:
    """Deferring changes no accepted state and is still not a host's call (ADR-007)."""
    spec = registry.get(name)
    assert spec.permission is permission
    assert spec.human_only
    assert spec.descriptor().human_only


@pytest.mark.parametrize("name", sorted(REVIEW_CAPABILITIES))
def test_an_agent_host_may_not_take_any_review_action(
    name: str, ctx: CapabilityContext, dataset: EvidenceCandidate, registry: CapabilityRegistry
) -> None:
    request = {
        "candidate_id": dataset.candidate_id,
        "qualification": "x",
        "reason": "x",
        "note": "x",
        "edited": dataset.evidence.model_dump(mode="json"),
    }
    fields = set(registry.get(name).request_model.model_fields)
    with pytest.raises(PermissionDenied):
        registry.invoke(
            name,
            ctx,
            {key: value for key, value in request.items() if key in fields},
            principal=Principal.agent_host("some-host"),
        )


# -- the queue actually drains ----------------------------------------------


def test_accept_writes_evidence_and_marks_the_candidate_reviewed(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    outcome = call(registry, ctx, "review.accept", {"candidate_id": dataset.candidate_id})

    assert outcome.evidence == "E0001"
    assert outcome.action == ReviewAction.ACCEPT.value
    assert outcome.status == CandidateStatus.REVIEWED.value
    assert staging.get(dataset.candidate_id).status is CandidateStatus.REVIEWED
    assert [str(item.id) for item in accepted(ctx.repo)] == ["E0001"]


def test_qualify_records_the_condition_and_leaves_the_queue(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    """The half of the Web gap that wrote Evidence and left the item in the queue."""
    outcome = call(
        registry,
        ctx,
        "review.qualify",
        {
            "candidate_id": dataset.candidate_id,
            "qualification": "holds for the CICIDS2017 capture only",
        },
    )

    stored = accepted(ctx.repo)[0]
    assert outcome.action == ReviewAction.ACCEPT_WITH_QUALIFICATION.value
    assert stored.qualification == "holds for the CICIDS2017 capture only"
    assert staging.get(dataset.candidate_id).status is CandidateStatus.REVIEWED


def test_edit_accepts_the_corrected_text_and_leaves_the_queue(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    corrected = dataset.evidence.model_dump(mode="json")
    corrected["content"]["exact_text"] = "All experiments use"

    outcome = call(
        registry,
        ctx,
        "review.edit",
        {"candidate_id": dataset.candidate_id, "edited": corrected},
    )

    stored = accepted(ctx.repo)[0]
    assert outcome.action == ReviewAction.EDIT.value
    assert stored.content.exact_text == "All experiments use"
    assert staging.get(dataset.candidate_id).status is CandidateStatus.REVIEWED


def test_split_accepts_the_fact_and_stages_the_interpretation_for_its_own_review(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    """Product 24.3: one accepted Evidence, and the reading queued as its own Tier-2 item."""
    outcome = call(
        registry,
        ctx,
        "review.split",
        {
            "candidate_id": dataset.candidate_id,
            "interpretation": "The corpus is therefore representative of enterprise traffic.",
        },
    )

    assert outcome.evidence == "E0001"
    assert outcome.rejected is None
    assert [str(item.id) for item in accepted(ctx.repo)] == ["E0001"]
    assert staging.get(dataset.candidate_id).status is CandidateStatus.REVIEWED

    staged = staging.get(outcome.interpretation_candidate)
    assert staged.field == "dataset:interpretation"
    assert staged.evidence.review_tier is ReviewTier.TIER_2
    assert staged.evidence.source == dataset.evidence.source
    assert staged.evidence.origin is EvidenceOrigin.AUTHOR_INTERPRETED


def test_split_can_refuse_the_interpretation_and_record_the_refusal(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    outcome = call(
        registry,
        ctx,
        "review.split",
        {
            "candidate_id": dataset.candidate_id,
            "reject_interpretation_reason": "the sentence names the corpus and claims no more",
        },
    )

    assert outcome.interpretation_candidate is None
    assert outcome.rejected is not None
    assert [str(item.id) for item in accepted(ctx.repo)] == ["E0001"]
    (record,) = list(ctx.repo.iter_rejections(WORK))
    assert record.field == "dataset:interpretation"


def test_split_refuses_to_decide_neither_half_or_both(
    ctx: CapabilityContext, dataset: EvidenceCandidate, registry: CapabilityRegistry
) -> None:
    """A split that decides nothing about the interpretation is not a split (ADR-007)."""
    for request in (
        {"candidate_id": dataset.candidate_id},
        {
            "candidate_id": dataset.candidate_id,
            "interpretation": "a reading",
            "reject_interpretation_reason": "and also refused",
        },
    ):
        with pytest.raises(CapabilityError, match="exactly one"):
            call(registry, ctx, "review.split", request)
    assert accepted(ctx.repo) == []


def test_an_edit_may_not_move_the_source_anchor(
    ctx: CapabilityContext, dataset: EvidenceCandidate, registry: CapabilityRegistry
) -> None:
    """ADR-002: correcting what a span says is review; re-pointing it is not."""
    moved = dataset.evidence.model_dump(mode="json")
    moved["source"]["page"] = (moved["source"]["page"] or 1) + 1

    with pytest.raises(CapabilityError, match="never the source anchor"):
        call(registry, ctx, "review.edit", {"candidate_id": dataset.candidate_id, "edited": moved})


def test_reject_records_the_refusal_and_creates_no_evidence(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    outcome = call(
        registry,
        ctx,
        "review.reject",
        {"candidate_id": dataset.candidate_id, "reason": "the span does not say this"},
    )

    refusals = list(ctx.repo.iter_rejections(WORK))
    assert outcome.evidence is None
    assert accepted(ctx.repo) == []
    assert [item.reason for item in refusals] == ["the span does not say this"]
    assert staging.get(dataset.candidate_id).status is CandidateStatus.REVIEWED


def test_defer_changes_no_accepted_state_and_keeps_the_item_in_the_queue(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    """Product 24.3: deferring is a note to the researcher's future self, not a decision."""
    before = canonical_digest(ctx.repo.root)

    outcome = call(
        registry,
        ctx,
        "review.defer",
        {"candidate_id": dataset.candidate_id, "note": "waiting for the appendix"},
    )

    assert outcome.mutation is None
    assert outcome.status == CandidateStatus.VERIFIED.value
    assert staging.get(dataset.candidate_id).review_action is ReviewAction.DEFER
    assert canonical_digest(ctx.repo.root) == before


def test_request_more_evidence_outlives_the_next_research_deletion(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    """Product 31: a question worth asking becomes a note, not a staging-only scribble."""
    outcome = call(
        registry,
        ctx,
        "review.request_more",
        {"candidate_id": dataset.candidate_id, "note": "does the appendix name the window?"},
    )

    notes = list(ctx.repo.iter_notes())
    assert outcome.mutation is not None
    assert outcome.mutation.event.event.value == "note.captured"
    assert len(notes) == 1
    assert notes[0].status is NoteStatus.CAPTURED
    assert dataset.candidate_id in notes[0].text


# -- one path, two names -----------------------------------------------------


def test_review_accept_and_resolve_conflict_take_the_same_path(
    workspace: WorkspaceRepository, staging: StagingStore, doc: Any, tmp_path: Path
) -> None:
    """Two capabilities, one `EvidenceReviewService` method, one canonical outcome."""
    del tmp_path
    registry = build_default_registry()
    ctx = CapabilityContext(repo=workspace, actor=ACTOR)
    first = stage(doc, staging, dataset_candidate, "dataset")
    verified(staging, first, VerificationVerdict.SUPPORTED, DATASET_SENTENCE)
    second = stage(doc, staging, metric_candidate, "metric_result")
    verified(staging, second, VerificationVerdict.SUPPORTED, "94.32")

    direct = call(registry, ctx, "review.accept", {"candidate_id": first.candidate_id})
    through_conflict = call(
        registry,
        ctx,
        "review.resolve_conflict",
        {
            "candidate_id": second.candidate_id,
            "choice": "accept",
            "reason": "read the table on page 4",
        },
    )

    assert direct.mutation.capability == through_conflict.mutation.capability == "evidence.accept"
    assert direct.mutation.event.event is through_conflict.mutation.event.event
    assert staging.get(first.candidate_id).status is CandidateStatus.REVIEWED
    assert staging.get(second.candidate_id).status is CandidateStatus.REVIEWED
    assert [str(item.id) for item in accepted(workspace)] == ["E0001", "E0002"]


# -- `evidence.accept` closes the queue item when it is told which one -------


def test_evidence_accept_with_a_candidate_id_marks_the_candidate_reviewed(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    """The Web posts the staged `Evidence` verbatim; naming the candidate drains the queue."""
    response = call(
        registry,
        ctx,
        "evidence.accept",
        {
            "candidate": json.loads(dataset.evidence.model_dump_json()),
            "candidate_id": dataset.candidate_id,
            "verdict": VerificationVerdict.SUPPORTED.value,
        },
    )

    assert response.objects == ("E0001",)
    assert staging.get(dataset.candidate_id).status is CandidateStatus.REVIEWED


def test_evidence_accept_without_a_candidate_id_touches_no_staging(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    """A hand-built acceptance has no queue entry to close, and must not invent one."""
    call(
        registry,
        ctx,
        "evidence.accept",
        {
            "candidate": json.loads(dataset.evidence.model_dump_json()),
            "verdict": VerificationVerdict.SUPPORTED.value,
        },
    )

    assert staging.get(dataset.candidate_id).status is CandidateStatus.VERIFIED


def test_marking_an_unknown_candidate_is_not_an_error(
    ctx: CapabilityContext,
    staging: StagingStore,
    dataset: EvidenceCandidate,
    registry: CapabilityRegistry,
) -> None:
    """Staging is regenerable: a candidate that is gone is not a reason to refuse a write."""
    payload = json.loads(dataset.evidence.model_dump_json())
    staging.delete(dataset.candidate_id)

    response = call(
        registry,
        ctx,
        "evidence.accept",
        {
            "candidate": payload,
            "candidate_id": dataset.candidate_id,
            "verdict": VerificationVerdict.SUPPORTED.value,
        },
    )

    assert response.objects == ("E0001",)

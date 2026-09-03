"""Interrupting a review acceptance, on both sides of the canonical commit.

Accepting a candidate is two writes in two stores: the canonical `evidence.accept`
mutation, and the staging record that remembers the researcher answered. Only the first is
transactional, so the order matters and `EvidenceReviewService.accept` fixes it:

    result = accept_evidence(ctx, request)      # canonical, journalled, atomic
    self._staging.mark_reviewed(candidate_id, action)   # regenerable, best effort

**Canonical first, staging second.** A crash between them leaves accepted Evidence with a
candidate that still looks unreviewed - staging is disposable and says something stale,
which is the failure mode `.research/` is *allowed* to have (ADR-001, ADR-003). The
reverse order would leave a candidate marked accepted with no Evidence behind it: a
regenerable file claiming a scientific fact that does not exist, and one the review service
then refuses to retry. This file interrupts both orders and shows the difference.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Never

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import AcceptEvidenceRequest
from research_harness.capabilities.handlers import accept_evidence
from research_harness.domain.enums import EvidenceStatus, ReviewAction
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import EvidenceId
from research_harness.evidence.service import EvidenceReviewService
from research_harness.evidence.staging import CandidateStatus, StagingStore
from research_harness.parsing.anchors import anchor_fingerprint
from research_harness.workspace.repository import WorkspaceRepository
from tests.e2e.crash.interrupts import PowerCutError, crash_at, reopen
from tests.e2e.invariants.workstation import (
    HUMAN,
    WORK,
    canonical_bytes_digest,
    interrogate_and_verify,
)


def die(*_args: Any, **_kwargs: Any) -> Never:
    raise PowerCutError("power cut between the two stores")


@pytest.fixture
def staged(project: CapabilityContext) -> Iterator[dict[str, str]]:
    """Two verified candidates, unreviewed, ready for an acceptance to be cut in half."""
    yield interrogate_and_verify(project)


@pytest.fixture
def service(project: CapabilityContext) -> EvidenceReviewService:
    return EvidenceReviewService(project, StagingStore(project.repo.layout.research_dir))


def accepted_ids(root: Path) -> list[str]:
    repo = WorkspaceRepository.open(root)
    return [
        str(record.id)
        for record in repo.iter_evidence(WORK)
        if record.status is EvidenceStatus.ACCEPTED
    ]


# ------------------------------------------- crash after the commit, before the staging mark


def test_a_crash_before_the_staging_mark_keeps_the_accepted_evidence(
    project: CapabilityContext,
    service: EvidenceReviewService,
    staged: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical half committed, so the scientific fact stands (Product §8.2)."""
    monkeypatch.setattr(StagingStore, "mark_reviewed", die)

    with pytest.raises(PowerCutError):
        service.accept(staged["dataset"])
    monkeypatch.undo()

    recovered = reopen(project.root)
    assert accepted_ids(project.root) == ["E0001"]
    assert recovered.summaries("evidence.accepted")
    assert recovered.consistency.consistent
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()


def test_the_staging_record_is_the_half_that_is_allowed_to_be_stale(
    project: CapabilityContext,
    service: EvidenceReviewService,
    staged: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.research/` may be behind; it may never be ahead of canonical state."""
    monkeypatch.setattr(StagingStore, "mark_reviewed", die)
    with pytest.raises(PowerCutError):
        service.accept(staged["dataset"])
    monkeypatch.undo()

    candidate = StagingStore(project.repo.layout.research_dir).get(staged["dataset"])

    assert candidate.status is CandidateStatus.VERIFIED
    assert candidate.review_action is None
    assert accepted_ids(project.root) == ["E0001"]


def test_re_accepting_after_the_crash_must_not_create_a_second_evidence_object(
    project: CapabilityContext,
    service: EvidenceReviewService,
    staged: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No duplicate ids: one span accepted once is one Evidence object, whatever crashed."""
    monkeypatch.setattr(StagingStore, "mark_reviewed", die)
    with pytest.raises(PowerCutError):
        service.accept(staged["dataset"])
    monkeypatch.undo()

    retry = EvidenceReviewService(
        open_context(project.root, HUMAN), StagingStore(project.repo.layout.research_dir)
    )
    retry.accept(staged["dataset"])

    repo = WorkspaceRepository.open(project.root)
    anchors = [anchor_fingerprint(record.source) for record in repo.iter_evidence(WORK)]
    assert len(anchors) == len(set(anchors))
    assert accepted_ids(project.root) == ["E0001"]


def test_the_repeat_answers_with_the_evidence_that_already_exists(
    project: CapabilityContext,
    service: EvidenceReviewService,
    staged: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry is idempotent, and says so rather than pretending it wrote something.

    One span accepted once is one Evidence object. The repeat names that object, journals
    no second `evidence.accepted`, and closes the staged candidate the crash left open, so
    the queue settles without a duplicate behind it.
    """
    monkeypatch.setattr(StagingStore, "mark_reviewed", die)
    with pytest.raises(PowerCutError):
        service.accept(staged["dataset"])
    monkeypatch.undo()
    before = len(list(reopen(project.root).repo.iter_events()))

    repeat = EvidenceReviewService(
        open_context(project.root, HUMAN), StagingStore(project.repo.layout.research_dir)
    ).accept(staged["dataset"])

    recovered = reopen(project.root)
    records = list(recovered.repo.iter_evidence(WORK))

    assert repeat.objects == ("E0001",)
    assert repeat.validation.warnings, "an idempotent acceptance says it wrote nothing"
    assert [str(record.id) for record in records] == ["E0001"]
    assert len({anchor_fingerprint(record.source) for record in records}) == 1
    assert len(list(recovered.repo.iter_events())) == before
    assert recovered.consistency.consistent


def test_a_repeat_carrying_a_different_qualification_is_refused_by_name(
    project: CapabilityContext,
    service: EvidenceReviewService,
    staged: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same span, different judgement: not a retry, so it is neither dropped nor doubled."""
    monkeypatch.setattr(StagingStore, "mark_reviewed", die)
    with pytest.raises(PowerCutError):
        service.accept(staged["dataset"])
    monkeypatch.undo()

    repeat = EvidenceReviewService(
        open_context(project.root, HUMAN), StagingStore(project.repo.layout.research_dir)
    )
    with pytest.raises(CapabilityError, match="already accepted as E0001"):
        repeat.accept(
            staged["dataset"],
            action=ReviewAction.ACCEPT_WITH_QUALIFICATION,
            qualification="holds for this capture only",
        )
    assert accepted_ids(project.root) == ["E0001"]


# --------------------------------------- crash after the staging mark, before the commit


def test_marking_staging_first_loses_the_acceptance_entirely(
    project: CapabilityContext, staged: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The order the service does *not* use, driven by hand to show what it costs.

    Staging says the researcher accepted; canonical state has no Evidence; and the review
    service now refuses to retry, because the candidate looks answered.
    """
    store = StagingStore(project.repo.layout.research_dir)
    candidate_id = staged["dataset"]
    store.mark_reviewed(candidate_id, ReviewAction.ACCEPT)
    candidate = store.get(candidate_id)

    crash_at(monkeypatch, "_commit_record")
    with pytest.raises(PowerCutError):
        accept_evidence(
            project,
            AcceptEvidenceRequest(
                candidate=candidate.evidence.touch(id=EvidenceId("E0001")),
                review_action=ReviewAction.ACCEPT,
            ),
        )
    monkeypatch.undo()

    recovered = reopen(project.root)
    retry = EvidenceReviewService(open_context(project.root, HUMAN), store)

    assert store.get(candidate_id).status is CandidateStatus.REVIEWED
    with pytest.raises(CapabilityError, match="cannot be accepted twice"):
        retry.accept(candidate_id)
    assert recovered.consistency.consistent


def test_the_canonical_first_order_is_the_one_the_service_uses(
    project: CapabilityContext, service: EvidenceReviewService, staged: dict[str, str]
) -> None:
    """Stated as a test so a reordering of the two writes fails here rather than silently."""
    calls: list[str] = []
    store = service.staging
    original = StagingStore.mark_reviewed

    def recording(self: StagingStore, candidate_id: str, action: ReviewAction) -> Any:
        calls.append(f"staging:{candidate_id}")
        return original(self, candidate_id, action)

    StagingStore.mark_reviewed = recording  # type: ignore[method-assign]
    try:
        result = service.accept(staged["dataset"])
    finally:
        StagingStore.mark_reviewed = original  # type: ignore[method-assign]

    assert result.objects == ("E0001",)
    assert calls == [f"staging:{staged['dataset']}"]
    assert store.get(staged["dataset"]).status is CandidateStatus.REVIEWED


# --------------------------------------------------------------------- rejection too


def test_a_crash_during_a_rejection_leaves_one_consistent_outcome(
    project: CapabilityContext,
    service: EvidenceReviewService,
    staged: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal is canonical too, so it gets the same all-or-nothing treatment."""
    before = canonical_bytes_digest(project.root)
    crash_at(monkeypatch, "_write_record")

    with pytest.raises(PowerCutError):
        service.reject(staged["dataset"], "the span does not say this")
    monkeypatch.undo()

    recovered = reopen(project.root)

    assert canonical_bytes_digest(project.root) == before
    assert recovered.summaries("evidence.rejected") == []
    assert list(recovered.repo.iter_rejections(WORK)) == []
    assert recovered.consistency.consistent


def test_the_rejection_can_simply_be_retried(
    project: CapabilityContext,
    service: EvidenceReviewService,
    staged: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crash_at(monkeypatch, "_write_record")
    with pytest.raises(PowerCutError):
        service.reject(staged["dataset"], "the span does not say this")
    monkeypatch.undo()

    service.reject(staged["dataset"], "the span does not say this")

    recovered = reopen(project.root)
    rejections = list(recovered.repo.iter_rejections(WORK))
    assert len(rejections) == 1
    assert rejections[0].reason == "the span does not say this"
    assert accepted_ids(project.root) == []
    assert recovered.consistency.consistent

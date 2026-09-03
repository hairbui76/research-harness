"""An interrupted capability mutation leaves either the prior state or the complete new one.

The journal's commit point is the rename in `Transaction._commit_record`; crashing on
either side of it is the whole question Product 8.2 asks, so both sides are simulated here
against a real capability handler rather than against the journal directly.
"""

from __future__ import annotations

from typing import Any, Never

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CreateClaimRequest, RejectEvidenceRequest
from research_harness.capabilities.handlers import create_claim, reject_evidence
from research_harness.domain.ids import ClaimId
from research_harness.workspace.events import verify_consistency
from research_harness.workspace.journal import Transaction
from research_harness.workspace.repository import (
    ObjectNotFoundError,
    WorkspaceRepository,
)
from tests.contract.capabilities.conftest import Registered, make_evidence
from tests.contract.capabilities.test_core_mutations import make_claim

CLAIM = ClaimId("C0001")


def _crash(*_args: Any, **_kwargs: Any) -> Never:
    raise RuntimeError("power cut")


def _events(repo: WorkspaceRepository, kind: str) -> list[str]:
    return [event.summary for event in repo.iter_events() if event.event.value == kind]


def test_a_crash_at_the_commit_point_recovers_the_complete_mutation(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_commit_record` is private on purpose: it is the durability boundary, and the only
    # place a crash can leave a prepared-but-uncommitted unit behind.
    monkeypatch.setattr(Transaction, "_commit_record", _crash)
    with pytest.raises(RuntimeError, match="power cut"):
        create_claim(project, CreateClaimRequest(claim=make_claim()))
    monkeypatch.undo()

    reopened = WorkspaceRepository.open(project.root)
    assert reopened.recovery.completed
    assert reopened.get_claim(CLAIM).statement == make_claim().statement
    assert _events(reopened, "claim.created") == [f"created claim {CLAIM}"]
    assert verify_consistency(reopened.layout).consistent
    assert reopened.consistency.consistent


def test_a_crash_before_the_record_lands_leaves_the_prior_state(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Transaction, "_write_record", _crash)
    with pytest.raises(RuntimeError, match="power cut"):
        create_claim(project, CreateClaimRequest(claim=make_claim()))
    monkeypatch.undo()

    reopened = WorkspaceRepository.open(project.root)
    with pytest.raises(ObjectNotFoundError):
        reopened.get_claim(CLAIM)
    assert _events(reopened, "claim.created") == []
    assert verify_consistency(reopened.layout).consistent


def test_recovery_never_duplicates_an_appended_event(
    project: CapabilityContext, registered: Registered, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An append is redone by truncating first, so the event log gains exactly one line."""
    before = len(list(project.repo.iter_events()))
    monkeypatch.setattr(Transaction, "_commit_record", _crash)
    with pytest.raises(RuntimeError, match="power cut"):
        reject_evidence(
            project,
            RejectEvidenceRequest(
                candidate=make_evidence(registered), reason="the span does not say this"
            ),
        )
    monkeypatch.undo()

    reopened = WorkspaceRepository.open(project.root)
    assert len(list(reopened.iter_events())) == before + 1
    assert _events(reopened, "evidence.rejected") == ["rejected evidence candidate E0001"]
    assert list(reopened.iter_evidence(registered.work)) == []
    assert verify_consistency(reopened.layout).consistent

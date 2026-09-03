"""Interrupting a canonical mutation, including by killing the process outright.

`tests/e2e/invariants/test_k_atomic_mutation.py` covers the Product §42.K sentence at every
journal phase in-process. This file is the harder version of the same question: a real
`os._exit` in a child process, with no `finally`, no in-process recovery, and no chance to
tidy anything up - which is what a power cut actually looks like.

After each one the same four checks run: the workspace opens, the event log agrees with
canonical state, no id was handed out twice, and a rebuild verifies clean.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CreateClaimRequest
from research_harness.capabilities.handlers import create_claim
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import ClaimScope, ClaimType
from research_harness.domain.ids import ClaimId
from research_harness.workspace.journal import (
    COMMITTED_SUFFIX,
    RECORD_SUFFIX,
    Transaction,
    recover,
)
from research_harness.workspace.repository import ObjectNotFoundError, WorkspaceRepository
from tests.e2e.crash.interrupts import PowerCutError, crash_at, leftover_journal, reopen
from tests.e2e.invariants.workstation import HUMAN, WORK, canonical_bytes_digest

CLAIM = ClaimId("C0001")
STATEMENT = "The evaluation protocol fixes one held-out split."

#: Exit code the child process uses, so a crash cannot be confused with a normal failure.
KILLED = 70


def a_claim(statement: str = STATEMENT, claim_id: ClaimId = CLAIM) -> Claim:
    return Claim(
        id=claim_id,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="protocol", predicate="fixes", object="one split"),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL, corpus="structured-traffic"),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.INDIVIDUAL, allowed_strength=ClaimScope.INDIVIDUAL
        ),
        provenance=Provenance.human(HUMAN),
    )


CHILD = textwrap.dedent(
    """
    import os, sys
    from research_harness.capabilities.context import open_context
    from research_harness.capabilities.dto import CreateClaimRequest
    from research_harness.capabilities.handlers import create_claim
    from research_harness.workspace.journal import Transaction

    sys.path.insert(0, {repo!r})
    from tests.e2e.crash.test_canonical_mutation import KILLED, a_claim

    original = getattr(Transaction, {phase!r})

    def die(*args, **kwargs):
        # No exception, no unwinding, no in-process recovery: the process simply stops,
        # exactly the way a power cut stops it.
        os._exit(KILLED)

    Transaction.{phase} = die
    ctx = open_context({root!r}, "human:alice")
    create_claim(ctx, CreateClaimRequest(claim=a_claim()))
    os._exit(0)
    """
)


def kill_during(root: Path, phase: str) -> subprocess.CompletedProcess[str]:
    """Run a `claim.create` in a child process that dies inside ``phase``."""
    repo_root = str(Path(__file__).resolve().parents[3])
    script = CHILD.format(repo=repo_root, root=str(root), phase=phase)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )


# --------------------------------------------------------------- a real process death


@pytest.mark.parametrize("phase", ["_apply", "_commit_record"])
def test_a_process_killed_mid_mutation_recovers_on_the_next_open(
    project: CapabilityContext, phase: str
) -> None:
    """No `finally` ran, so only the on-open recovery can finish or undo the unit."""
    killed = kill_during(project.root, phase)
    assert killed.returncode == KILLED, killed.stderr

    recovered = reopen(project.root)
    landed = _claim_exists(recovered.repo, CLAIM)

    assert landed == bool(recovered.summaries("claim.created"))
    assert recovered.consistency.consistent, recovered.consistency.summary()
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()
    assert recovered.journal == ()


def test_a_process_killed_before_the_record_lands_leaves_the_prior_state(
    project: CapabilityContext,
) -> None:
    killed = kill_during(project.root, "_write_record")
    assert killed.returncode == KILLED, killed.stderr

    recovered = reopen(project.root)

    with pytest.raises(ObjectNotFoundError):
        recovered.repo.get_claim(CLAIM)
    assert recovered.summaries("claim.created") == []
    assert recovered.consistency.consistent
    assert recovered.journal == ()


def test_a_process_killed_at_the_commit_point_completes_the_unit(
    project: CapabilityContext,
) -> None:
    """The record landed and the writes are on disk, so recovery rolls forward."""
    killed = kill_during(project.root, "_commit_record")
    assert killed.returncode == KILLED, killed.stderr

    repo = WorkspaceRepository.open(project.root)

    assert repo.recovery.completed
    assert repo.get_claim(CLAIM).statement == STATEMENT
    assert [
        event.summary for event in repo.iter_events() if event.event.value == "claim.created"
    ] == [f"created claim {CLAIM}"]
    assert repo.consistency.consistent


def test_the_killed_process_wrote_no_second_claim(project: CapabilityContext) -> None:
    """Recovery finishes the unit; it never replays it, so the id is used once."""
    kill_during(project.root, "_commit_record")
    repo = WorkspaceRepository.open(project.root)

    ids = [str(claim.id) for claim in repo.list_claims()]
    events = [event.summary for event in repo.iter_events() if event.event.value == "claim.created"]

    assert ids == [str(CLAIM)]
    assert len(events) == 1
    assert len(list((project.root / "claims").glob("*.yaml"))) == 1


def test_the_workspace_is_usable_again_after_the_kill(project: CapabilityContext) -> None:
    """Recovery is not a museum piece: the next mutation works normally."""
    kill_during(project.root, "_commit_record")
    from research_harness.capabilities.context import open_context

    ctx = open_context(project.root, HUMAN)
    result = create_claim(
        ctx, CreateClaimRequest(claim=a_claim("A second statement.", ClaimId("C0002")))
    )

    assert result.objects == ("C0002",)
    assert reopen(project.root).consistency.consistent


# -------------------------------------------------------------- a torn journal record


def test_a_torn_journal_record_is_rolled_back(project: CapabilityContext) -> None:
    """Half a record means the apply phase never began, so the pre-images are restored."""
    layout = project.repo.layout
    before = canonical_bytes_digest(project.root)
    transaction = Transaction(layout)
    transaction.write(layout.claim_file(CLAIM), b"claim: not yet valid\n")
    record = transaction._prepare()
    path = layout.journal_dir / f"{record.tx_id}{RECORD_SUFFIX}"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) // 2], encoding="utf-8")

    report = recover(layout)

    assert report.rolled_back == (record.tx_id,)
    assert canonical_bytes_digest(project.root) == before
    assert leftover_journal(layout) == []


def test_a_committed_but_uncleaned_transaction_is_only_tidied(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the commit rename the unit is durable; recovery has nothing to decide."""
    monkeypatch.setattr(
        "research_harness.workspace.journal._clean_transaction", lambda layout, tx_id: None
    )
    create_claim(project, CreateClaimRequest(claim=a_claim()))
    monkeypatch.undo()
    layout = project.repo.layout
    assert any(name.endswith(COMMITTED_SUFFIX) for name in leftover_journal(layout))

    recovered = reopen(project.root)

    assert recovered.repo.get_claim(CLAIM).statement == STATEMENT
    assert recovered.journal == ()
    assert recovered.consistency.consistent


# ------------------------------------------------------------- the four standing checks


@pytest.mark.parametrize("phase", ["_prepare", "_write_record", "_apply", "_commit_record"])
def test_every_in_process_interruption_leaves_a_projectable_workspace(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    crash_at(monkeypatch, phase)
    with pytest.raises(PowerCutError):
        create_claim(project, CreateClaimRequest(claim=a_claim()))
    monkeypatch.undo()

    recovered = reopen(project.root)

    assert recovered.consistency.consistent
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()
    assert recovered.journal == ()
    assert len(recovered.events) == len(set(_event_keys(project.root)))


def _event_keys(root: Path) -> list[str]:
    """A key per event line, so a duplicated append would show up as a repeat."""
    path = root / "events" / "research.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.dumps(json.loads(line), sort_keys=True) for line in lines if line.strip()]


def _claim_exists(repo: WorkspaceRepository, claim: ClaimId) -> bool:
    try:
        repo.get_claim(claim)
    except ObjectNotFoundError:
        return False
    return True


def test_the_ingested_work_survives_every_later_crash(project: CapabilityContext) -> None:
    """The state that was already committed is never collateral damage."""
    kill_during(project.root, "_apply")

    repo = WorkspaceRepository.open(project.root)
    work = repo.get_work(WORK)

    assert work.artifacts
    assert repo.read_artifact_bytes(repo.list_artifacts(WORK)[0])
    assert list(repo.iter_blocks(work.artifacts[0], work=WORK))

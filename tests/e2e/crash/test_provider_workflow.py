"""Interrupting a long provider workflow mid-stage, and resuming it.

Product §19.1: a long workflow has a durable run id, stage checkpoints, input
fingerprints, and an explicit terminal state, and restarting resumes from the last valid
checkpoint. The interruption here is the realistic one - the provider raises on call *N* -
and the properties that have to survive it are:

* nothing canonical moved, because extraction and verification only write staging;
* the resume recomputes the failed stage and *only* the failed stage;
* staging ends up with one candidate per field, because candidate ids are content
  addressed rather than allocated (ADR-003).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.evidence.staging import CandidateStatus, StagingStore
from research_harness.providers.models.base import ProviderResponseError
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workflows.engine import WorkflowEngine, WorkflowFailed
from research_harness.workflows.interrogate import extract_stage_name, run_interrogation
from research_harness.workflows.models import RunStatus, StageStatus
from research_harness.workflows.verify import run_verification, verify_stage_name
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore
from tests.e2e.invariants.workstation import (
    WORK,
    canonical_bytes_digest,
    verification_reply,
)
from tests.integration.evidence.conftest import (
    dataset_candidate,
    extraction_dict,
    method_candidate,
    metric_candidate,
    parse_fixture,
)

FIELDS: tuple[str, ...] = ("dataset", "metric_result", "method_summary")


class ProviderDiedError(ProviderResponseError):
    """The provider stopped answering mid-run: a timeout, a 5xx, or a killed local server."""


def extraction_replies() -> dict[str, dict[str, Any]]:
    """One correct extraction reply per field, quoting spans the real parse produced."""
    document = parse_fixture()
    return {
        "dataset": extraction_dict([dataset_candidate(document)]),
        "metric_result": extraction_dict([metric_candidate(document)]),
        "method_summary": extraction_dict([method_candidate(document)]),
    }


def scripted(fields: Sequence[str], *, dies_after: int | None = None) -> ScriptedProvider:
    """A provider that answers ``fields`` in order and dies after ``dies_after`` answers."""
    replies = extraction_replies()
    queue: list[Any] = [replies[name] for name in fields]
    if dies_after is not None:
        queue = [*queue[:dies_after], ProviderDiedError("connection reset", provider="scripted")]
    return ScriptedProvider(queue)


@pytest.fixture
def engine(project: CapabilityContext) -> WorkflowEngine:
    return WorkflowEngine(RunStore(project.repo.layout.research_dir))


@pytest.fixture
def staging(project: CapabilityContext) -> StagingStore:
    return StagingStore(project.repo.layout.research_dir)


@pytest.fixture
def interrupted(
    project: CapabilityContext, engine: WorkflowEngine, staging: StagingStore
) -> Iterator[str]:
    """An interrogation of three fields that died while answering the second one."""
    with pytest.raises(WorkflowFailed) as raised:
        run_interrogation(
            engine, staging, project.repo, WORK, scripted(FIELDS, dies_after=1), fields=FIELDS
        )
    assert raised.value.stage == extract_stage_name("metric_result")
    yield raised.value.run_id


# ------------------------------------------------------------------ nothing canonical moved


def test_a_provider_that_dies_mid_run_changes_no_canonical_state(
    project: CapabilityContext, engine: WorkflowEngine, staging: StagingStore
) -> None:
    """Product §8.3: model work happens outside the transaction, so it cannot half-commit."""
    before = canonical_bytes_digest(project.root)

    with pytest.raises(WorkflowFailed):
        run_interrogation(
            engine, staging, project.repo, WORK, scripted(FIELDS, dies_after=1), fields=FIELDS
        )

    assert canonical_bytes_digest(project.root) == before
    assert list(project.repo.iter_evidence(WORK)) == []
    assert WorkspaceRepository.open(project.root).consistency.consistent


def test_the_failed_run_is_terminal_and_names_the_stage_that_died(
    interrupted: str, engine: WorkflowEngine
) -> None:
    run = engine.store.load(interrupted)

    assert run.status is RunStatus.failed
    assert run.error is not None and "metric_result" in run.error
    assert run.stage(extract_stage_name("dataset")).status is StageStatus.succeeded
    assert run.stage(extract_stage_name("metric_result")).status is StageStatus.failed


def test_the_interrupted_run_staged_nothing_yet(interrupted: str, staging: StagingStore) -> None:
    """`stage_candidates` is the last stage, so a run that died earlier staged nothing."""
    assert staging.list(work=WORK) == []


# ------------------------------------------------------------------------ the resume


def test_resuming_completes_the_run(
    project: CapabilityContext,
    engine: WorkflowEngine,
    staging: StagingStore,
    interrupted: str,
) -> None:
    """Restarting resumes from the last valid checkpoint (Product §19.1)."""
    resumed = run_interrogation(
        engine,
        staging,
        project.repo,
        WORK,
        scripted(FIELDS[1:]),
        fields=FIELDS,
        run_id=interrupted,
    )

    assert resumed.run.run_id == interrupted
    assert resumed.run.status is RunStatus.succeeded
    assert sorted(resumed.candidates_by_field) == sorted(FIELDS)


def test_the_resume_recomputes_only_the_stage_that_died(
    project: CapabilityContext,
    engine: WorkflowEngine,
    staging: StagingStore,
    interrupted: str,
) -> None:
    """A field answered before the crash is not paid for twice (Product §19.1)."""
    provider = scripted(FIELDS[1:])

    run_interrogation(
        engine, staging, project.repo, WORK, provider, fields=FIELDS, run_id=interrupted
    )

    assert len(provider.requests) == len(FIELDS) - 1
    reused = engine.store.load(interrupted).stage(extract_stage_name("dataset"))
    assert reused.status is StageStatus.skipped_cached


def test_the_resume_stages_one_candidate_per_field_and_no_duplicate(
    project: CapabilityContext,
    engine: WorkflowEngine,
    staging: StagingStore,
    interrupted: str,
) -> None:
    """The property that makes a resume safe: candidate ids follow content, not attempts."""
    run_interrogation(
        engine,
        staging,
        project.repo,
        WORK,
        scripted(FIELDS[1:]),
        fields=FIELDS,
        run_id=interrupted,
    )

    staged = staging.list(work=WORK)
    ids = [candidate.candidate_id for candidate in staged]

    assert sorted(candidate.field for candidate in staged) == sorted(FIELDS)
    assert len(ids) == len(set(ids))


def test_running_the_whole_interrogation_again_adds_no_second_copy(
    project: CapabilityContext,
    engine: WorkflowEngine,
    staging: StagingStore,
    interrupted: str,
) -> None:
    """A researcher who reruns the command after a crash gets the same candidates back."""
    run_interrogation(
        engine,
        staging,
        project.repo,
        WORK,
        scripted(FIELDS[1:]),
        fields=FIELDS,
        run_id=interrupted,
    )
    first = {candidate.candidate_id for candidate in staging.list(work=WORK)}

    run_interrogation(engine, staging, project.repo, WORK, scripted(FIELDS), fields=FIELDS)

    assert {candidate.candidate_id for candidate in staging.list(work=WORK)} == first


def test_a_run_whose_process_died_is_flagged_rather_than_left_running(
    project: CapabilityContext, engine: WorkflowEngine, staging: StagingStore
) -> None:
    """A `running` record with no process behind it is a lie the next open corrects."""
    with pytest.raises(WorkflowFailed) as raised:
        run_interrogation(
            engine, staging, project.repo, WORK, scripted(FIELDS, dies_after=1), fields=FIELDS
        )
    run = engine.store.load(raised.value.run_id)
    run.status = RunStatus.running
    engine.store.save(run)

    flagged = engine.mark_interrupted_runs()

    assert [item.run_id for item in flagged] == [raised.value.run_id]
    assert engine.store.load(raised.value.run_id).status is RunStatus.interrupted


# ------------------------------------------------------------------- verification too


@pytest.fixture
def staged(
    project: CapabilityContext, engine: WorkflowEngine, staging: StagingStore
) -> Iterator[list[str]]:
    """Three staged candidates, unverified, ready for a verification run to be cut short."""
    run_interrogation(engine, staging, project.repo, WORK, scripted(FIELDS), fields=FIELDS)
    ordered = [
        candidate.field for candidate in staging.list(work=WORK, status=CandidateStatus.PROPOSED)
    ]
    assert len(ordered) == len(FIELDS)
    yield ordered


def verifier(fields: Sequence[str], *, dies_after: int | None = None) -> ScriptedProvider:
    queue: list[Any] = [verification_reply_for(name) for name in fields]
    if dies_after is not None:
        queue = [*queue[:dies_after], ProviderDiedError("read timeout", provider="scripted")]
    return ScriptedProvider(queue)


def verification_reply_for(field: str) -> dict[str, Any]:
    """A schema-valid verdict; `method_summary` quotes its own span rather than a number."""
    if field == "method_summary":
        return {
            "verdict": "supported",
            "rationale": "the method section states this",
            "quoted_support": "The encoder is a twelve layer transformer",
            "discrepancies": [],
        }
    return verification_reply(field)


def test_an_interrupted_verification_resumes_without_reverifying(
    project: CapabilityContext,
    engine: WorkflowEngine,
    staging: StagingStore,
    staged: list[str],
) -> None:
    """Verification is expensive; buying the same verdict twice buys nothing (Product §20.4)."""
    with pytest.raises(WorkflowFailed) as raised:
        run_verification(engine, staging, project.repo, WORK, verifier(staged, dies_after=1))
    done = staging.list(work=WORK, status=CandidateStatus.VERIFIED)
    assert len(done) == 1
    first, verdict = done[0].candidate_id, done[0].verdict

    provider = verifier(staged[1:])
    report = run_verification(
        engine, staging, project.repo, WORK, provider, run_id=raised.value.run_id
    )

    # A candidate that already carries a verdict is not even selected for the second run,
    # so it costs no call and its recorded verdict is left exactly as it was.
    assert len(provider.requests) == len(staged) - 1
    assert first not in report.verdicts
    assert set(report.verdicts) | {first} == {
        candidate.candidate_id for candidate in staging.list(work=WORK)
    }
    assert staging.get(first).verdict == verdict
    assert verify_stage_name(first) in {
        record.name for record in engine.store.load(raised.value.run_id).stages
    }


def test_a_verification_crash_leaves_one_record_per_candidate(
    project: CapabilityContext,
    engine: WorkflowEngine,
    staging: StagingStore,
    staged: list[str],
) -> None:
    with pytest.raises(WorkflowFailed) as raised:
        run_verification(engine, staging, project.repo, WORK, verifier(staged, dies_after=1))
    run_verification(
        engine,
        staging,
        project.repo,
        WORK,
        verifier(staged[1:]),
        run_id=raised.value.run_id,
    )

    candidates = staging.list(work=WORK)
    assert len(candidates) == len(FIELDS)
    assert all(candidate.verification is not None for candidate in candidates)
    assert all(candidate.status is CandidateStatus.VERIFIED for candidate in candidates)


def test_deleting_the_run_state_loses_no_conclusion(
    project: CapabilityContext,
    engine: WorkflowEngine,
    staging: StagingStore,
    staged: list[str],
) -> None:
    """Runs live under `.research/`; deleting them costs work, never a conclusion."""
    before = canonical_bytes_digest(project.root)
    runs = engine.store.list_runs()
    assert runs

    for run in runs:
        engine.store.delete_run(run.run_id)

    assert canonical_bytes_digest(project.root) == before
    assert WorkspaceRepository.open(project.root).consistency.consistent


def test_the_schema_lists_the_fields_this_file_interrogates() -> None:
    """A field this schema does not ask cannot be interrogated, crash or no crash."""
    assert set(FIELDS) <= set(DEFAULT_SCHEMA.names)

"""Durable workflow runs: resume after failure or process death, cancel, and stay disposable.

Every assertion here defends one rule from PRODUCT.md 19.1: a run has a durable ID, stage
checkpoints, input fingerprints, attempt history, and an explicit terminal state; a restart
resumes from the last valid checkpoint or safely recomputes an idempotent stage; and the
whole run store is regenerable runtime state that no canonical file depends on.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

import pytest

from research_harness.workflows.engine import (
    StageBase,
    StageContext,
    Workflow,
    WorkflowEngine,
    WorkflowFailed,
)
from research_harness.workflows.models import (
    Attempt,
    RunStatus,
    StageStatus,
    WorkflowRun,
    utc_now,
)
from research_harness.workspace.runs import RunNotFoundError, RunStore

INPUTS: dict[str, Any] = {"alpha": 1, "beta": "two"}
STAGE_KEYS: dict[str, tuple[str, ...]] = {"s1": ("alpha",), "s2": ("beta",), "s3": ()}


class RecordingStage(StageBase):
    """Counts its invocations, writes a staging artifact, and returns a deterministic output."""

    def __init__(
        self,
        name: str,
        *,
        keys: tuple[str, ...] = (),
        idempotent: bool = True,
        fail_times: int = 0,
    ) -> None:
        super().__init__(name, version="1", idempotent=idempotent)
        self.keys = keys
        self.fail_times = fail_times
        self.calls = 0

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        return {key: ctx.inputs.get(key) for key in self.keys}

    def run(self, ctx: StageContext) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"{self.name} exploded")
        (ctx.staging_dir / f"{self.name}.txt").write_text(self.name, encoding="utf-8")
        return {
            "stage": self.name,
            "seen": {key: ctx.inputs.get(key) for key in self.keys},
            "upstream": sorted(ctx.previous_outputs),
        }


def build(
    *,
    fail_times: Mapping[str, int] | None = None,
    non_idempotent: Collection[str] = (),
) -> tuple[Workflow, dict[str, RecordingStage]]:
    """A three-stage workflow whose stages depend on different inputs."""
    failures = fail_times or {}
    stages = {
        name: RecordingStage(
            name,
            keys=keys,
            idempotent=name not in non_idempotent,
            fail_times=failures.get(name, 0),
        )
        for name, keys in STAGE_KEYS.items()
    }
    return Workflow(name="demo", version="1", stages=list(stages.values())), stages


def harness(tmp_path: Path) -> tuple[RunStore, WorkflowEngine]:
    store = RunStore(tmp_path / "project" / ".research")
    return store, WorkflowEngine(store)


def run_once(engine: WorkflowEngine, workflow: Workflow, inputs: dict[str, Any]) -> WorkflowRun:
    return engine.execute(engine.start(workflow, inputs).run_id, workflow, inputs)


def simulate_process_death(store: RunStore, run_id: str, stage: str) -> None:
    """Rewrite a finished run as one whose process died inside `stage`.

    The run is left `running` with an open attempt, exactly as a killed process would, and
    every later stage is reset to `pending` with its checkpoint removed.
    """
    run = store.load(run_id)
    run.status = RunStatus.running
    record = run.stage(stage)
    record.status = StageStatus.running
    record.attempts.append(Attempt(number=len(record.attempts) + 1, started_at=utc_now()))
    later = False
    for other in run.stages:
        if other.name == stage:
            later = True
            continue
        if later:
            other.status = StageStatus.pending
            other.input_fingerprint = None
            other.output_fingerprint = None
            other.checkpoint_path = None
            store.checkpoint_path(run_id, other.name).unlink(missing_ok=True)
    store.save(run)


def tree_digest(root: Path, exclude: Path) -> dict[str, str]:
    """Content hashes of every file under `root` outside `exclude`."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or exclude in path.parents or path == exclude:
            continue
        digests[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def test_happy_path_runs_every_stage_once_and_checkpoints_it(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build()

    run = run_once(engine, workflow, INPUTS)

    assert run.status is RunStatus.succeeded
    assert [stage.calls for stage in stages.values()] == [1, 1, 1]
    for name in STAGE_KEYS:
        record = run.stage(name)
        assert record.status is StageStatus.succeeded
        assert [attempt.number for attempt in record.attempts] == [1]
        assert record.attempts[0].status is StageStatus.succeeded
        assert record.attempts[0].finished_at is not None
        assert record.open_attempt is None
        assert record.input_fingerprint is not None
        assert record.output_fingerprint is not None
        assert record.checkpoint_path == f"runs/{run.run_id}/checkpoints/{name}.json"
        assert store.checkpoint_path(run.run_id, name).is_file()
        assert store.load_checkpoint(run.run_id, name) == {
            "stage": name,
            "seen": {key: INPUTS[key] for key in STAGE_KEYS[name]},
            "upstream": sorted(n for n in STAGE_KEYS if n < name),
        }
    assert store.load(run.run_id).status is RunStatus.succeeded


def test_failed_run_resumes_without_rerunning_earlier_stages(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build(fail_times={"s2": 1})
    run = engine.start(workflow, INPUTS)

    with pytest.raises(WorkflowFailed) as failure:
        engine.execute(run.run_id, workflow, INPUTS)

    assert failure.value.run_id == run.run_id
    assert failure.value.stage == "s2"
    failed = store.load(run.run_id)
    assert failed.status is RunStatus.failed
    assert failed.error is not None and "s2 exploded" in failed.error
    assert failed.stage("s1").status is StageStatus.succeeded
    assert failed.stage("s2").status is StageStatus.failed
    assert failed.stage("s3").status is StageStatus.pending
    assert stages["s3"].calls == 0

    resumed = engine.resume(run.run_id, workflow, INPUTS)

    assert resumed.status is RunStatus.succeeded
    assert stages["s1"].calls == 1
    assert resumed.stage("s1").status is StageStatus.skipped_cached
    assert stages["s2"].calls == 2
    attempts = resumed.stage("s2").attempts
    assert [attempt.number for attempt in attempts] == [1, 2]
    assert attempts[0].status is StageStatus.failed
    assert attempts[0].error is not None and "exploded" in attempts[0].error
    assert attempts[1].status is StageStatus.succeeded
    assert stages["s3"].calls == 1


def test_run_left_running_is_detectable_and_reuses_an_idempotent_checkpoint(
    tmp_path: Path,
) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build()
    run = run_once(engine, workflow, INPUTS)
    simulate_process_death(store, run.run_id, "s2")

    crashed = store.load(run.run_id)
    assert crashed.status is RunStatus.running
    assert crashed.stage("s2").open_attempt is not None

    for stage in stages.values():
        stage.calls = 0
    resumed = engine.resume(run.run_id, workflow, INPUTS)

    assert resumed.status is RunStatus.succeeded
    assert stages["s1"].calls == 0
    assert stages["s2"].calls == 0
    assert resumed.stage("s2").status is StageStatus.skipped_cached
    assert stages["s3"].calls == 1
    interrupted = resumed.stage("s2").attempts[-1]  # the attempt the dead process left open
    assert interrupted.status is StageStatus.failed
    assert interrupted.error is not None and "interrupted" in interrupted.error
    assert resumed.stage("s2").open_attempt is None


def test_non_idempotent_stage_is_recomputed_after_process_death(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build(non_idempotent={"s2"})
    run = run_once(engine, workflow, INPUTS)
    simulate_process_death(store, run.run_id, "s2")

    for stage in stages.values():
        stage.calls = 0
    resumed = engine.resume(run.run_id, workflow, INPUTS)

    assert resumed.status is RunStatus.succeeded
    assert stages["s1"].calls == 0
    assert stages["s2"].calls == 1
    assert resumed.stage("s2").status is StageStatus.succeeded
    assert stages["s3"].calls == 1


def test_mark_interrupted_runs_flags_runs_whose_process_died(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build()
    run = run_once(engine, workflow, INPUTS)
    simulate_process_death(store, run.run_id, "s2")

    flagged = engine.mark_interrupted_runs()

    assert [flagged_run.run_id for flagged_run in flagged] == [run.run_id]
    interrupted = store.load(run.run_id)
    assert interrupted.status is RunStatus.interrupted
    assert interrupted.stage("s2").open_attempt is None
    for stage in stages.values():
        stage.calls = 0
    assert engine.resume(run.run_id, workflow, INPUTS).status is RunStatus.succeeded


def test_terminal_run_is_not_reexecuted_without_force(tmp_path: Path) -> None:
    _, engine = harness(tmp_path)
    workflow, stages = build()
    run = run_once(engine, workflow, INPUTS)

    again = engine.execute(run.run_id, workflow, INPUTS | {"beta": "three"})

    assert again.status is RunStatus.succeeded
    assert [stage.calls for stage in stages.values()] == [1, 1, 1]


def test_force_recomputes_only_the_stages_whose_fingerprint_changed(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build()
    run = run_once(engine, workflow, INPUTS)
    changed = INPUTS | {"beta": "three"}

    forced = engine.execute(run.run_id, workflow, changed, force=True)

    assert forced.status is RunStatus.succeeded
    assert stages["s1"].calls == 1  # depends on alpha only
    assert forced.stage("s1").status is StageStatus.skipped_cached
    assert stages["s2"].calls == 2  # beta changed
    assert forced.stage("s2").status is StageStatus.succeeded
    assert stages["s3"].calls == 2  # its upstream output changed
    checkpoint = store.load_checkpoint(run.run_id, "s2")
    assert checkpoint is not None
    assert checkpoint["seen"] == {"beta": "three"}


def test_cancel_requested_before_execute_leaves_every_stage_unrun(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build()
    run = engine.start(workflow, INPUTS)

    store.request_cancel(run.run_id)
    cancelled = engine.execute(run.run_id, workflow, INPUTS)

    assert cancelled.status is RunStatus.cancelled
    assert cancelled.cancel_requested is True
    assert [stage.calls for stage in stages.values()] == [0, 0, 0]
    assert all(record.status is StageStatus.pending for record in cancelled.stages)
    assert store.load(run.run_id).status is RunStatus.cancelled


def test_cancel_requested_during_a_stage_stops_before_the_next_one(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)

    class CancellingStage(RecordingStage):
        def run(self, ctx: StageContext) -> dict[str, Any]:
            output = super().run(ctx)
            store.request_cancel(ctx.run.run_id)  # as another process would
            assert ctx.cancel_requested() is True
            return output

    first = CancellingStage("s1", keys=("alpha",))
    rest = [RecordingStage(name, keys=STAGE_KEYS[name]) for name in ("s2", "s3")]
    workflow = Workflow(name="demo", version="1", stages=[first, *rest])

    cancelled = run_once(engine, workflow, INPUTS)

    assert cancelled.status is RunStatus.cancelled
    assert first.calls == 1
    assert [stage.calls for stage in rest] == [0, 0]
    assert cancelled.stage("s1").status is StageStatus.succeeded
    assert cancelled.stage("s2").status is StageStatus.pending


def test_torn_checkpoint_is_treated_as_missing_and_the_stage_recomputed(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, stages = build(fail_times={"s3": 1})
    run = engine.start(workflow, INPUTS)
    with pytest.raises(WorkflowFailed):
        engine.execute(run.run_id, workflow, INPUTS)

    torn = store.checkpoint_path(run.run_id, "s1")
    torn.write_text('{"stage": "s1", "seen"', encoding="utf-8")  # a half-written file
    assert store.load_checkpoint(run.run_id, "s1") is None
    assert not torn.exists()

    resumed = engine.resume(run.run_id, workflow, INPUTS)

    assert resumed.status is RunStatus.succeeded
    assert stages["s1"].calls == 2  # its checkpoint was unusable
    assert stages["s2"].calls == 1  # upstream output was identical, so it stayed cached
    assert resumed.stage("s2").status is StageStatus.skipped_cached
    assert stages["s3"].calls == 2


def test_partial_temp_file_from_a_crashed_writer_is_ignored_and_removed(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, _ = build()
    run = run_once(engine, workflow, INPUTS)

    leftover = store.run_dir(run.run_id) / ".tmp-run.json.deadbeef"
    leftover.write_text('{"run_id": "run_', encoding="utf-8")

    assert store.load(run.run_id).status is RunStatus.succeeded
    assert not leftover.exists()


def test_deleting_run_state_never_changes_canonical_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "claims").mkdir(parents=True)
    claim = project / "claims" / "C0001.yaml"
    claim.write_text("id: C0001\n", encoding="utf-8")
    store, engine = harness(tmp_path)
    canonical_before = tree_digest(project, exclude=store.research_dir)
    workflow, _ = build()

    run = run_once(engine, workflow, INPUTS)

    assert run.status is RunStatus.succeeded
    assert store.staging_dir(run.run_id) == store.research_dir / "staging" / run.run_id
    assert (store.research_dir / "staging" / run.run_id / "s1.txt").is_file()
    # Nothing the engine wrote landed outside the research directory.
    assert tree_digest(project, exclude=store.research_dir) == canonical_before

    shutil.rmtree(store.research_dir / "runs")

    assert tree_digest(project, exclude=store.research_dir) == canonical_before
    assert claim.read_text(encoding="utf-8") == "id: C0001\n"
    assert store.list_runs() == []
    with pytest.raises(RunNotFoundError):
        store.load(run.run_id)


def test_delete_run_removes_runtime_state_and_staging(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, _ = build()
    run = run_once(engine, workflow, INPUTS)

    store.delete_run(run.run_id)

    assert not store.run_dir(run.run_id).exists()
    assert not (store.research_dir / "staging" / run.run_id).exists()
    assert store.list_runs() == []


def test_list_runs_filters_by_status(tmp_path: Path) -> None:
    store, engine = harness(tmp_path)
    workflow, _ = build()
    succeeded = run_once(engine, workflow, INPUTS)
    broken, _ = build(fail_times={"s2": 99})
    failed = engine.start(broken, INPUTS)
    with pytest.raises(WorkflowFailed):
        engine.execute(failed.run_id, broken, INPUTS)
    pending = engine.start(workflow, INPUTS)

    assert {run.run_id for run in store.list_runs()} == {
        succeeded.run_id,
        failed.run_id,
        pending.run_id,
    }
    assert [run.run_id for run in store.list_runs(RunStatus.succeeded)] == [succeeded.run_id]
    assert [run.run_id for run in store.list_runs(RunStatus.failed)] == [failed.run_id]
    assert [run.run_id for run in store.list_runs(RunStatus.pending)] == [pending.run_id]
    assert store.list_runs(RunStatus.cancelled) == []

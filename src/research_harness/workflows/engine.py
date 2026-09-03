"""Synchronous, resumable workflow engine over durable runs and stage checkpoints.

The engine owns runtime state only. A stage receives its inputs, the outputs of the stages
before it, and a staging directory; it gets no handle to canonical state and no API that
could promote work to accepted authority. Staged artifacts become accepted state only when a
researcher drives a capability handler outside this engine.

Crash safety rests on two rules: an attempt is persisted before the stage runs, and a stage's
checkpoint is persisted before its status flips to `succeeded`. A process that dies between
the two leaves a `running` record whose checkpoint is trusted again only if the input
fingerprint still matches *and* the stage declares itself idempotent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from research_harness.workflows.fingerprints import fingerprint
from research_harness.workflows.models import (
    REUSABLE_STAGE_STATUSES,
    Attempt,
    RunStatus,
    StageRecord,
    StageStatus,
    WorkflowRun,
    new_run_id,
    utc_now,
)
from research_harness.workspace.runs import RunStore, RunStoreError

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]

INTERRUPTED_ERROR = "interrupted: the owning process ended before the stage finished"


class WorkflowError(Exception):
    """A workflow was configured or driven incorrectly."""


class WorkflowFailed(WorkflowError):  # noqa: N818 - public name fixed by the task contract
    """A stage raised. The run is persisted as `failed` and can be resumed."""

    def __init__(self, run_id: str, stage: str, message: str) -> None:
        super().__init__(f"run {run_id} failed in stage {stage!r}: {message}")
        self.run_id = run_id
        self.stage = stage
        self.message = message


@dataclass(frozen=True)
class StageContext:
    """Everything a stage may see.

    Deliberately no handle to canonical state, the workspace, or any mutation capability:
    stages produce staging artifacts and a JSON-serializable output only. Promotion of staged
    work to accepted scientific state happens through capability handlers outside the engine.
    """

    run: WorkflowRun
    stage: str
    staging_dir: Path
    inputs: dict[str, Any]
    previous_outputs: Mapping[str, dict[str, Any]]
    cancel_requested: Callable[[], bool]


class Stage(Protocol):
    """One unit of work. `version` and `fingerprint_inputs` decide when it must be recomputed."""

    name: str
    version: str
    idempotent: bool

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        """The part of the context this stage's output actually depends on."""
        ...

    def run(self, ctx: StageContext) -> dict[str, Any]:
        """Do the work and return a JSON-serializable output, which becomes the checkpoint."""
        ...


class StageBase:
    """Convenience base implementing the default fingerprint (every input)."""

    def __init__(self, name: str, *, version: str = "1", idempotent: bool = True) -> None:
        self.name = name
        self.version = version
        self.idempotent = idempotent

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        return ctx.inputs

    def run(self, ctx: StageContext) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class Workflow:
    """An ordered pipeline of stages; `version` is recorded on every run it produces."""

    name: str
    version: str
    stages: Sequence[Stage]

    def __post_init__(self) -> None:
        names = [stage.name for stage in self.stages]
        if len(set(names)) != len(names):
            raise WorkflowError(f"workflow {self.name!r} has duplicate stage names: {names}")


class WorkflowEngine:
    """Executes workflows stage by stage, checkpointing each one so a run can always resume."""

    def __init__(self, store: RunStore) -> None:
        self._store = store

    @property
    def store(self) -> RunStore:
        return self._store

    def start(
        self, workflow: Workflow, inputs: dict[str, Any], *, clock: Clock | None = None
    ) -> WorkflowRun:
        """Create and persist a pending run with a durable ID and one record per stage."""
        now = clock or utc_now
        moment = now()
        run = WorkflowRun(
            run_id=new_run_id(now),
            workflow=workflow.name,
            workflow_version=workflow.version,
            status=RunStatus.pending,
            created_at=moment,
            updated_at=moment,
            inputs_fingerprint=fingerprint(inputs),
            stages=[
                StageRecord(name=stage.name, version=stage.version, idempotent=stage.idempotent)
                for stage in workflow.stages
            ],
        )
        self._store.create(run)
        return run

    def execute(
        self,
        run_id: str,
        workflow: Workflow,
        inputs: dict[str, Any],
        *,
        clock: Clock | None = None,
        force: bool = False,
    ) -> WorkflowRun:
        """Run the workflow's stages in order, reusing every checkpoint that is still valid."""
        now = clock or utc_now
        run = self._store.load(run_id)
        if run.workflow != workflow.name:
            raise WorkflowError(
                f"run {run_id} belongs to workflow {run.workflow!r}, not {workflow.name!r}"
            )
        if run.status is RunStatus.running:
            # Nothing else can be executing it: the engine is single-process and synchronous.
            self._mark_interrupted(run, now)
        if run.is_terminal and not force:
            logger.info("run %s is already %s; not re-executing", run_id, run.status)
            return run
        return self._execute(run, workflow, inputs, now, force)

    def resume(
        self,
        run_id: str,
        workflow: Workflow,
        inputs: dict[str, Any],
        *,
        clock: Clock | None = None,
        force: bool = False,
    ) -> WorkflowRun:
        """Resume a run. Identical to `execute`: executing is idempotent by construction."""
        return self.execute(run_id, workflow, inputs, clock=clock, force=force)

    def mark_interrupted_runs(self, *, clock: Clock | None = None) -> list[WorkflowRun]:
        """Startup helper: flag runs still marked `running` (their process died) as interrupted."""
        now = clock or utc_now
        return [
            self._mark_interrupted(run, now) for run in self._store.list_runs(RunStatus.running)
        ]

    def _execute(
        self,
        run: WorkflowRun,
        workflow: Workflow,
        inputs: dict[str, Any],
        now: Clock,
        force: bool,
    ) -> WorkflowRun:
        self._sync_records(run, workflow)
        run.inputs_fingerprint = fingerprint(inputs)
        run.workflow_version = workflow.version
        run.error = None
        run.status = RunStatus.running
        self._touch(run, now)

        staging_dir = self._store.staging_dir(run.run_id)
        outputs: dict[str, dict[str, Any]] = {}
        for stage in workflow.stages:
            record = run.stage(stage.name)
            if self._cancel_requested(run):
                run.status = RunStatus.cancelled
                self._touch(run, now)
                logger.info("run %s cancelled before stage %s", run.run_id, stage.name)
                return run
            ctx = StageContext(
                run=run,
                stage=stage.name,
                staging_dir=staging_dir,
                inputs=inputs,
                previous_outputs=MappingProxyType(dict(outputs)),
                cancel_requested=lambda: self._cancel_requested(run),
            )
            try:
                outputs[stage.name] = self._run_stage(run, record, stage, ctx, outputs, now, force)
            except Exception as exc:
                self._fail(run, record, stage.name, exc, now)
                raise WorkflowFailed(run.run_id, stage.name, str(exc)) from exc

        finished = (run.stage(stage.name).status for stage in workflow.stages)
        if all(status in REUSABLE_STAGE_STATUSES for status in finished):
            run.status = RunStatus.succeeded
        self._touch(run, now)
        return run

    def _run_stage(
        self,
        run: WorkflowRun,
        record: StageRecord,
        stage: Stage,
        ctx: StageContext,
        outputs: Mapping[str, dict[str, Any]],
        now: Clock,
        force: bool,
    ) -> dict[str, Any]:
        input_fingerprint = fingerprint(
            {
                "inputs": stage.fingerprint_inputs(ctx),
                "stage_version": stage.version,
                "previous_outputs": dict(outputs),
            }
        )
        cached = self._reusable_checkpoint(run, record, stage, input_fingerprint, force)
        if cached is not None:
            record.status = StageStatus.skipped_cached
            record.output_fingerprint = fingerprint(cached)
            self._touch(run, now)
            logger.debug("run %s reused the checkpoint of stage %s", run.run_id, stage.name)
            return cached

        attempt = Attempt(number=len(record.attempts) + 1, started_at=now())
        record.attempts.append(attempt)
        record.status = StageStatus.running
        record.input_fingerprint = input_fingerprint
        self._touch(run, now)  # the open attempt is durable before the stage does any work

        output = stage.run(ctx)
        if not isinstance(output, dict):
            raise WorkflowError(
                f"stage {stage.name!r} returned {type(output).__name__}, not a dict"
            )
        checkpoint = self._store.save_checkpoint(run.run_id, stage.name, output)

        record.checkpoint_path = self._relative(checkpoint)
        record.output_fingerprint = fingerprint(output)
        record.attempts[-1] = attempt.finished(status=StageStatus.succeeded, at=now())
        record.status = StageStatus.succeeded  # flipped only once the checkpoint is durable
        self._touch(run, now)
        return output

    def _reusable_checkpoint(
        self,
        run: WorkflowRun,
        record: StageRecord,
        stage: Stage,
        input_fingerprint: str,
        force: bool,
    ) -> dict[str, Any] | None:
        """Return the checkpoint this stage may reuse, or None when it must be recomputed."""
        if record.input_fingerprint != input_fingerprint:
            return None
        if record.status is StageStatus.running:
            # Interrupted mid-stage: the checkpoint may be half a story, so only an idempotent
            # stage is allowed to keep it. Anything else is recomputed.
            if not stage.idempotent:
                return None
        elif record.status not in REUSABLE_STAGE_STATUSES:
            return None
        if force and not stage.idempotent:
            return None
        return self._store.load_checkpoint(run.run_id, stage.name)

    def _sync_records(self, run: WorkflowRun, workflow: Workflow) -> None:
        """Give every workflow stage a record; records of removed stages are kept as history."""
        for stage in workflow.stages:
            record = run.find_stage(stage.name)
            if record is None:
                run.stages.append(
                    StageRecord(name=stage.name, version=stage.version, idempotent=stage.idempotent)
                )
                continue
            record.version = stage.version
            record.idempotent = stage.idempotent

    def _fail(
        self, run: WorkflowRun, record: StageRecord, stage: str, exc: Exception, now: Clock
    ) -> None:
        moment = now()
        message = f"{type(exc).__name__}: {exc}"
        open_attempt = record.open_attempt
        if open_attempt is None:
            record.attempts.append(
                Attempt(
                    number=len(record.attempts) + 1,
                    started_at=moment,
                    finished_at=moment,
                    status=StageStatus.failed,
                    error=message,
                )
            )
        else:
            record.attempts[-1] = open_attempt.finished(
                status=StageStatus.failed, at=moment, error=message
            )
        record.status = StageStatus.failed
        run.status = RunStatus.failed
        run.error = f"{stage}: {message}"
        self._touch(run, now)

    def _mark_interrupted(self, run: WorkflowRun, now: Clock) -> WorkflowRun:
        """Close the attempts a dead process left open. Stage records keep their status, so the
        per-stage fingerprint and idempotence rules decide what may still be reused."""
        moment = now()
        for record in run.stages:
            open_attempt = record.open_attempt
            if open_attempt is not None:
                record.attempts[-1] = open_attempt.finished(
                    status=StageStatus.failed, at=moment, error=INTERRUPTED_ERROR
                )
        run.status = RunStatus.interrupted
        self._touch(run, now)
        return run

    def _cancel_requested(self, run: WorkflowRun) -> bool:
        """Cancellation is a durable flag another process may set while this run executes."""
        if run.cancel_requested:
            return True
        try:
            persisted = self._store.load(run.run_id)
        except RunStoreError:  # pragma: no cover - the record was removed mid-run
            return False
        if persisted.cancel_requested:
            run.cancel_requested = True
        return run.cancel_requested

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self._store.research_dir).as_posix()
        except ValueError:  # pragma: no cover - the store only writes inside its research dir
            return str(path)

    def _touch(self, run: WorkflowRun, now: Clock) -> None:
        run.updated_at = now()
        self._store.save(run)

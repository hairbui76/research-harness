"""Durable records for workflow runs: run identity, stage checkpoints, and attempt history.

These objects are *runtime* state. They live under the research directory (`.research/`),
they are regenerable, and they carry no scientific authority: a checkpoint may preserve
proposed or staged work, but it can never promote anything to accepted state. Deleting the
run store loses progress, never canonical conclusions.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

RUN_ID_PREFIX = "run"
RUN_ID_PATTERN = r"^run_\d{8}T\d{6}Z_[0-9a-f]{8}$"
_RUN_ID_TIMESTAMP = "%Y%m%dT%H%M%SZ"


def utc_now() -> datetime:
    """The default clock: timezone-aware UTC."""
    return datetime.now(UTC)


class RunStatus(StrEnum):
    """Lifecycle of a workflow run; `succeeded` and `cancelled` are terminal."""

    pending = "pending"
    running = "running"
    interrupted = "interrupted"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class StageStatus(StrEnum):
    """Lifecycle of one stage within a run."""

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped_cached = "skipped_cached"
    cancelled = "cancelled"


TERMINAL_RUN_STATUSES = frozenset({RunStatus.succeeded, RunStatus.cancelled})
"""Runs that are finished; re-executing one requires an explicit force."""

RESUMABLE_RUN_STATUSES = frozenset(
    {RunStatus.pending, RunStatus.running, RunStatus.interrupted, RunStatus.failed}
)
"""Runs that `WorkflowEngine.resume` will pick up again."""

REUSABLE_STAGE_STATUSES = frozenset({StageStatus.succeeded, StageStatus.skipped_cached})
"""Stage states whose checkpoint may be reused when the input fingerprint still matches."""


def new_run_id(clock: Callable[[], datetime] | None = None) -> str:
    """Return a durable run ID: `run_<utc timestamp>_<8 hex>`, sortable by creation time."""
    moment = (clock or utc_now)().astimezone(UTC)
    return f"{RUN_ID_PREFIX}_{moment.strftime(_RUN_ID_TIMESTAMP)}_{secrets.token_hex(4)}"


class Attempt(BaseModel):
    """One execution attempt of a stage; frozen, because attempt history is append-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int = Field(ge=1)
    started_at: datetime
    finished_at: datetime | None = None
    status: StageStatus = StageStatus.running
    error: str | None = None

    def finished(self, *, status: StageStatus, at: datetime, error: str | None = None) -> Attempt:
        """Return a closed copy of this attempt."""
        return self.model_copy(update={"finished_at": at, "status": status, "error": error})


class StageRecord(BaseModel):
    """Durable state of one stage: fingerprints, checkpoint location, and attempt history."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
    version: str
    idempotent: bool = True
    input_fingerprint: str | None = None
    output_fingerprint: str | None = None
    status: StageStatus = StageStatus.pending
    attempts: list[Attempt] = Field(default_factory=list)
    checkpoint_path: str | None = None
    """Checkpoint location relative to the research directory, so runs stay relocatable."""

    @property
    def open_attempt(self) -> Attempt | None:
        """The last attempt that never finished: the signature of a process that died."""
        if self.attempts and self.attempts[-1].finished_at is None:
            return self.attempts[-1]
        return None


class WorkflowRun(BaseModel):
    """A durable workflow run: identity, terminal state, cancellation flag, and stage records."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    run_id: str = Field(pattern=RUN_ID_PATTERN)
    workflow: str
    workflow_version: str
    status: RunStatus = RunStatus.pending
    created_at: datetime
    updated_at: datetime
    cancel_requested: bool = False
    stages: list[StageRecord] = Field(default_factory=list)
    inputs_fingerprint: str
    error: str | None = None

    @property
    def is_terminal(self) -> bool:
        """True when the run finished and will not be re-executed without an explicit force."""
        return self.status in TERMINAL_RUN_STATUSES

    def find_stage(self, name: str) -> StageRecord | None:
        """Return the record for `name`, or None when the run has never seen that stage."""
        for record in self.stages:
            if record.name == name:
                return record
        return None

    def stage(self, name: str) -> StageRecord:
        """Return the record for `name`; raise KeyError when the run has no such stage."""
        record = self.find_stage(name)
        if record is None:
            raise KeyError(f"run {self.run_id} has no stage {name!r}")
        return record

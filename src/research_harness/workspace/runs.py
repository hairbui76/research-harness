"""Atomic, crash-tolerant storage for workflow runs, checkpoints, and staging directories.

Everything written here lives under the research directory (`.research/`) and is regenerable
runtime state with no scientific authority. Every write is atomic (temp file in the same
directory, fsync, `os.replace`), so a reader never sees a half-written run; a temp file left
behind by a crashed writer is ignored and removed on the next read.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from research_harness.workflows.models import RunStatus, WorkflowRun, utc_now

logger = logging.getLogger(__name__)

RUNS_DIRNAME = "runs"
STAGING_DIRNAME = "staging"
CHECKPOINTS_DIRNAME = "checkpoints"
RUN_FILENAME = "run.json"

_TEMP_PREFIX = ".tmp-"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RunStoreError(Exception):
    """A run or checkpoint could not be read or written."""


class RunNotFoundError(RunStoreError):
    """No run with the given ID exists in this store."""


class RunStore:
    """Durable home for workflow runs under `<research_dir>/runs` and `<research_dir>/staging`."""

    def __init__(self, research_dir: Path) -> None:
        self._research_dir = Path(research_dir)

    @property
    def research_dir(self) -> Path:
        """Root of all regenerable runtime state; nothing is ever written outside it."""
        return self._research_dir

    @property
    def runs_dir(self) -> Path:
        return self._research_dir / RUNS_DIRNAME

    @property
    def staging_root(self) -> Path:
        return self._research_dir / STAGING_DIRNAME

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / _segment(run_id)

    def run_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / RUN_FILENAME

    def checkpoint_path(self, run_id: str, stage: str) -> Path:
        return self.run_dir(run_id) / CHECKPOINTS_DIRNAME / f"{_segment(stage)}.json"

    def staging_dir(self, run_id: str) -> Path:
        """Create and return the run's staging area: the only place stages write artifacts."""
        directory = self.staging_root / _segment(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def create(self, run: WorkflowRun) -> Path:
        """Persist a new run; refuse to overwrite an existing one."""
        if self.run_path(run.run_id).exists():
            raise RunStoreError(f"run {run.run_id} already exists")
        (self.run_dir(run.run_id) / CHECKPOINTS_DIRNAME).mkdir(parents=True, exist_ok=True)
        return self.save(run)

    def save(self, run: WorkflowRun) -> Path:
        """Write the run record atomically, so readers only ever see a complete run."""
        path = self.run_path(run.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, _dump(run.model_dump(mode="json")))
        return path

    def load(self, run_id: str) -> WorkflowRun:
        """Load a run exactly as persisted.

        A run still marked `running` is returned as such, with its last attempt still open:
        that is how a process that died mid-stage is detected. Deciding what to do about it
        is the engine's job, not the store's.
        """
        path = self.run_path(run_id)
        _clean_partials(path.parent)
        if not path.is_file():
            raise RunNotFoundError(f"no run {run_id} under {self.runs_dir}")
        return _parse_run(path)

    def list_runs(self, status: RunStatus | None = None) -> list[WorkflowRun]:
        """Return runs ordered by ID (creation time), optionally filtered by status."""
        runs: list[WorkflowRun] = []
        if not self.runs_dir.is_dir():
            return runs
        for directory in sorted(self.runs_dir.iterdir()):
            if not directory.is_dir():
                continue
            _clean_partials(directory)
            path = directory / RUN_FILENAME
            if not path.is_file():
                continue
            try:
                run = _parse_run(path)
            except RunStoreError:
                logger.warning("ignoring unreadable run record %s", path)
                continue
            if status is None or run.status == status:
                runs.append(run)
        return runs

    def save_checkpoint(self, run_id: str, stage: str, payload: dict[str, Any] | BaseModel) -> Path:
        """Atomically persist a stage's output; the checkpoint is durable before any status flip."""
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        path = self.checkpoint_path(run_id, stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, _dump(data))
        return path

    def load_checkpoint(self, run_id: str, stage: str) -> dict[str, Any] | None:
        """Return a stage checkpoint, or None if it is absent or unreadable (which deletes it)."""
        path = self.checkpoint_path(run_id, stage)
        _clean_partials(path.parent)
        if not path.is_file():
            return None
        payload: Any = None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            logger.warning("discarding unreadable checkpoint %s", path)
            path.unlink(missing_ok=True)
            return None
        return payload

    def request_cancel(self, run_id: str) -> WorkflowRun:
        """Set the durable cancellation flag; a running engine observes it before its next stage."""
        run = self.load(run_id)
        if not run.cancel_requested:
            run.cancel_requested = True
            run.updated_at = utc_now()
            self.save(run)
        return run

    def delete_run(self, run_id: str) -> None:
        """Delete a run's runtime state and staging area. Canonical state is never touched."""
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)
        shutil.rmtree(self.staging_root / _segment(run_id), ignore_errors=True)


def _segment(name: str) -> str:
    """Reject IDs and stage names that would escape the store's directory."""
    if not _SAFE_SEGMENT.match(name):
        raise RunStoreError(f"unsafe path segment {name!r}")
    return name


def _parse_run(path: Path) -> WorkflowRun:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunStoreError(f"cannot read run record {path}: {exc}") from exc
    try:
        return WorkflowRun.model_validate(payload)
    except ValidationError as exc:
        raise RunStoreError(f"invalid run record {path}: {exc}") from exc


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _atomic_write_text(path: Path, text: str) -> None:
    """Write a temp file in the same directory, fsync, rename: a reader sees all or nothing."""
    directory = path.parent
    temp = directory / f"{_TEMP_PREFIX}{path.name}.{uuid4().hex}"
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    _fsync_dir(directory)


def _fsync_dir(directory: Path) -> None:
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platforms without directory descriptors
        return
    try:
        os.fsync(handle)
    except OSError:  # pragma: no cover - filesystems that cannot fsync a directory
        pass
    finally:
        os.close(handle)


def _clean_partials(directory: Path) -> None:
    """Remove temp files a crashed writer left behind; they are never valid state."""
    if not directory.is_dir():
        return
    for leftover in directory.glob(f"{_TEMP_PREFIX}*"):
        with suppress(OSError):
            leftover.unlink()

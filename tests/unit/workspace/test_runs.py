"""`RunStore`'s atomic write rides out a transient lock on the destination file.

The stream checkpoint is rewritten on every streamed delta, so it is the file most likely
to collide with something else that briefly held it open: on Windows a search indexer, a
cloud-sync client (Downloads is backed up to OneDrive by default), or antivirus real-time
scanning turns that collision into a `PermissionError` (WinError 5 or 32) from the rename
itself, not from anything the daemon did. A researcher who hit this saw it surface as the
answer's own error text -- ``[WinError 5] Access is denied: '...tmp-stream.json...' ->
'...stream.json'`` -- which aborted the stream on what was, in fact, a lock that would have
cleared a few milliseconds later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.workflows.models import RunStatus, StageRecord, WorkflowRun, utc_now
from research_harness.workspace import runs as runs_module
from research_harness.workspace.runs import RunStore

RUN_ID = "run_20260909T174738Z_b4b4f587"


def _run() -> WorkflowRun:
    now = utc_now()
    return WorkflowRun(
        run_id=RUN_ID,
        workflow="conversation.send",
        workflow_version="1",
        status=RunStatus.running,
        created_at=now,
        updated_at=now,
        stages=[StageRecord(name="stream", version="1")],
        inputs_fingerprint="deadbeef",
    )


def test_a_lock_that_clears_before_the_retries_run_out_is_invisible_to_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    store.create(_run())

    real_replace = runs_module.os.replace
    calls: list[int] = []

    def flaky(src: object, dst: object) -> None:
        calls.append(1)
        if len(calls) <= 3:
            raise PermissionError(5, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(runs_module.os, "replace", flaky)
    monkeypatch.setattr(runs_module.time, "sleep", lambda _seconds: None)

    path = store.save_checkpoint(RUN_ID, "stream", {"text": "partial answer"})

    assert len(calls) == 4, "the third collision must have been retried, not raised"
    assert store.load_checkpoint(RUN_ID, "stream") == {"text": "partial answer"}
    assert not path.with_name(f".tmp-{path.name}").exists()
    assert list(path.parent.glob(".tmp-*")) == [], "no leftover temp file from the retries"


def test_a_lock_that_never_clears_still_raises_the_real_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path)
    store.create(_run())

    def always_locked(src: object, dst: object) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(runs_module.os, "replace", always_locked)
    monkeypatch.setattr(runs_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        store.save_checkpoint(RUN_ID, "stream", {"text": "partial answer"})

    # The failed attempt's temp file is cleaned up rather than left for the next writer
    # to trip over, exactly as an unrelated crash mid-write already had to be.
    checkpoints = tmp_path / "runs" / RUN_ID / "checkpoints"
    assert list(checkpoints.glob(".tmp-*")) == []

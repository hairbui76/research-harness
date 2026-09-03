"""Interrupting a canonical mutation at a named point, and checking what it left behind.

The journal's phases are the only places a canonical mutation can be cut in half, so they
are the crash points this suite uses (`workspace.journal.Transaction`)::

    _prepare        nothing staged yet
    _write_record   staged, but the record has not landed -> roll back
    _apply          the record landed -> roll forward
    _apply_intent   part of the unit is on disk -> roll forward
    _commit_record  everything is on disk, the commit rename has not happened

`WorkspaceTransaction.commit` runs recovery in-process before re-raising, so a crash point
that keeps failing also fails that attempt; recovery then runs again on the next
`WorkspaceRepository.open`. Both are real, and the assertions in this package hold either
way, which is the point: the caller never has to know which one finished the unit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from research_harness.projection.rebuild import rebuild_workspace, verify_rebuild
from research_harness.projection.schema import create_engine_for
from research_harness.workspace.events import ConsistencyReport, verify_consistency
from research_harness.workspace.journal import Transaction
from research_harness.workspace.layout import WorkspaceLayout
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "JOURNAL_CRASH_POINTS",
    "PowerCutError",
    "RecoveredWorkspace",
    "crash_at",
    "leftover_journal",
    "reopen",
]

#: Every phase of the journal protocol, with the call to fail on. `_apply_intent` is
#: interrupted on its second call so part of the unit is already on disk.
JOURNAL_CRASH_POINTS: tuple[tuple[str, int], ...] = (
    ("_prepare", 1),
    ("_write_record", 1),
    ("_apply", 1),
    ("_apply_intent", 2),
    ("_commit_record", 1),
)


class PowerCutError(RuntimeError):
    """What a crash looks like from inside the process: the phase simply never returns."""


def crash_at(
    monkeypatch: pytest.MonkeyPatch, method: str, *, on_call: int = 1, once: bool = False
) -> None:
    """Make ``Transaction.<method>`` raise, simulating a crash at that journal phase.

    ``once`` models a transient interruption: only the numbered call fails, so the
    in-process recovery `WorkspaceTransaction.commit` runs is allowed to succeed.
    """
    original: Callable[..., Any] = getattr(Transaction, method)
    calls = {"n": 0}

    def failing(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        crashing = calls["n"] == on_call if once else calls["n"] >= on_call
        if not crashing:
            return original(*args, **kwargs)
        raise PowerCutError(f"power cut in {method} call {calls['n']}")

    monkeypatch.setattr(Transaction, method, failing)


def leftover_journal(layout: WorkspaceLayout) -> list[str]:
    """Whatever the journal directory still holds, sorted; empty after a clean recovery."""
    if not layout.journal_dir.is_dir():
        return []
    return sorted(path.name for path in layout.journal_dir.iterdir())


@dataclass(frozen=True)
class RecoveredWorkspace:
    """A workspace reopened after an interruption, with everything the checks need."""

    repo: WorkspaceRepository
    consistency: ConsistencyReport
    rebuild_ok: bool
    rebuild_issues: tuple[str, ...]
    journal: tuple[str, ...]

    @property
    def events(self) -> list[str]:
        """Every recorded event kind, oldest first."""
        return [event.event.value for event in self.repo.iter_events()]

    def summaries(self, kind: str) -> list[str]:
        return [event.summary for event in self.repo.iter_events() if event.event.value == kind]


def reopen(root: Path) -> RecoveredWorkspace:
    """Open the workspace the way the next process would, and rebuild its projection.

    Opening runs journal recovery under the workspace lock and reconciles the event log
    with canonical state; the rebuild then proves the surviving state is projectable. A
    workspace that fails either is not a valid workspace (Product §8.2).
    """
    repo = WorkspaceRepository.open(root)
    report = rebuild_workspace(repo)
    issues: list[str] = [f"{invalid.path}: {invalid.error}" for invalid in report.invalid_files]
    if report.ok:
        engine = create_engine_for(repo.layout.database_file)
        try:
            issues.extend(verify_rebuild(repo, engine))
        finally:
            engine.dispose()
    return RecoveredWorkspace(
        repo=repo,
        consistency=verify_consistency(repo.layout),
        rebuild_ok=report.ok,
        rebuild_issues=tuple(issues),
        journal=tuple(leftover_journal(repo.layout)),
    )

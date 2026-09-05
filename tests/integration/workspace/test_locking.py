"""Concurrent accepted-state mutation is serialized by the workspace lock.

These tests use real OS processes because `flock` is a kernel-level advisory lock: two
threads in one interpreter would not exercise it. Coordination uses `multiprocessing`
events rather than sleeps, so the test blocks on the lock itself and nothing else.
"""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
from typing import Any

import pytest

from research_harness.domain import ResearchEvent, ResearchEventType
from research_harness.domain.errors import WorkspaceError
from research_harness.workspace.layout import WorkspaceLayout
from research_harness.workspace.locking import (
    DEFAULT_LOCK_TIMEOUT,
    WorkspaceLock,
    WorkspaceLockedError,
    lock_holder,
)
from research_harness.workspace.repository import WorkspaceRepository
from tests.unit.domain.strategies import make_claim

JOIN_TIMEOUT = 30.0
CONTEXT = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")


def hold_the_lock(root: str, acquired: EventType, release: EventType, order: Any) -> None:
    """Hold the workspace lock, announce it, and record the ordering while still holding."""
    with WorkspaceLock(WorkspaceLayout(Path(root))):
        acquired.set()
        release.wait(JOIN_TIMEOUT)
        order.put("child-while-holding")


def try_to_lock(root: str, timeout: float, outcome: Any) -> None:
    """Report whether a second process could take the lock within ``timeout``."""
    try:
        with WorkspaceLock(WorkspaceLayout(Path(root)), timeout):
            outcome.put("acquired")
    except WorkspaceLockedError as exc:
        outcome.put(f"blocked: {exc}")


def commit_a_claim(root: str, started: EventType, order: Any) -> None:
    """A full accepted-state mutation from a second process."""
    repo = WorkspaceRepository.open(Path(root))
    started.set()
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED, actor="human:bob", summary="create C0041"
    )
    with repo.transaction(event) as transaction:
        transaction.put(make_claim())
    order.put("child-committed")


def _drain(queue: Any) -> list[str]:
    """Read a finished `SimpleQueue`; its puts are synchronous, so the order is real time."""
    items: list[str] = []
    while not queue.empty():
        items.append(queue.get())
    return items


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository.init(tmp_path / "project", "locking")


# -- basics ------------------------------------------------------------------


def test_the_lock_reports_whether_it_is_held(workspace: WorkspaceRepository) -> None:
    lock = WorkspaceLock(workspace.layout)
    assert not lock.held
    with lock:
        assert lock.held
        assert lock.path == workspace.layout.lock_file
    assert not lock.held


def test_the_lock_is_not_reentrant_within_one_process(
    workspace: WorkspaceRepository,
) -> None:
    lock = WorkspaceLock(workspace.layout)
    with lock, pytest.raises(WorkspaceError, match="not reentrant"):
        lock.acquire()


def test_releasing_an_unheld_lock_is_harmless(workspace: WorkspaceRepository) -> None:
    WorkspaceLock(workspace.layout).release()


def test_the_holder_records_its_pid_for_diagnostics(workspace: WorkspaceRepository) -> None:
    import os

    with WorkspaceLock(workspace.layout):
        holder = lock_holder(workspace.layout)
    assert holder is not None
    assert holder["pid"] == os.getpid()
    assert "acquired_at" in holder


def test_the_default_timeout_is_the_documented_one(workspace: WorkspaceRepository) -> None:
    assert WorkspaceLock(workspace.layout).timeout == DEFAULT_LOCK_TIMEOUT


# -- two processes -----------------------------------------------------------


def test_a_second_process_blocks_until_the_first_releases(
    workspace: WorkspaceRepository,
) -> None:
    acquired = CONTEXT.Event()
    release = CONTEXT.Event()
    order: Any = CONTEXT.SimpleQueue()

    child = CONTEXT.Process(
        target=hold_the_lock, args=(str(workspace.root), acquired, release, order)
    )
    child.start()
    try:
        assert acquired.wait(JOIN_TIMEOUT), "the child never took the lock"
        release.set()
        # The parent can only get here after the child released, so the queue order is
        # proof that the two processes did not hold the lock at the same time.
        with WorkspaceLock(workspace.layout, JOIN_TIMEOUT):
            order.put("parent-after-acquiring")
    finally:
        child.join(JOIN_TIMEOUT)

    assert child.exitcode == 0
    assert _drain(order) == ["child-while-holding", "parent-after-acquiring"]


def test_a_held_lock_makes_a_second_process_time_out(
    workspace: WorkspaceRepository,
) -> None:
    outcome: Any = CONTEXT.SimpleQueue()
    with WorkspaceLock(workspace.layout):
        child = CONTEXT.Process(target=try_to_lock, args=(str(workspace.root), 0.2, outcome))
        child.start()
        child.join(JOIN_TIMEOUT)

    assert child.exitcode == 0
    (result,) = _drain(outcome)
    assert result.startswith("blocked: ")
    assert "is locked" in result
    assert "gave up after 0.2s" in result


def test_a_free_lock_is_taken_immediately_by_a_second_process(
    workspace: WorkspaceRepository,
) -> None:
    outcome: Any = CONTEXT.SimpleQueue()
    child = CONTEXT.Process(target=try_to_lock, args=(str(workspace.root), 0.2, outcome))
    child.start()
    child.join(JOIN_TIMEOUT)
    assert child.exitcode == 0
    assert _drain(outcome) == ["acquired"]


def test_the_timeout_message_names_the_process_holding_the_lock(
    workspace: WorkspaceRepository,
) -> None:
    acquired = CONTEXT.Event()
    release = CONTEXT.Event()
    order: Any = CONTEXT.SimpleQueue()
    child = CONTEXT.Process(
        target=hold_the_lock, args=(str(workspace.root), acquired, release, order)
    )
    child.start()
    try:
        assert acquired.wait(JOIN_TIMEOUT)
        with pytest.raises(WorkspaceLockedError, match=f"pid {child.pid}"):
            WorkspaceLock(workspace.layout, 0.1).acquire()
    finally:
        release.set()
        child.join(JOIN_TIMEOUT)
    assert child.exitcode == 0


def test_accepted_state_mutation_from_two_processes_is_serialized(
    workspace: WorkspaceRepository,
) -> None:
    """The acceptance requirement: a second writer waits for the first to commit."""
    started = CONTEXT.Event()
    order: Any = CONTEXT.SimpleQueue()

    with workspace.lock():
        child = CONTEXT.Process(target=commit_a_claim, args=(str(workspace.root), started, order))
        child.start()
        assert started.wait(JOIN_TIMEOUT), "the child never opened the workspace"
        order.put("parent-holding-the-lock")
        # The child is now blocked inside its transaction, waiting for this lock.
        assert child.is_alive()

    child.join(JOIN_TIMEOUT)
    assert child.exitcode == 0
    assert _drain(order) == ["parent-holding-the-lock", "child-committed"]

    reopened = WorkspaceRepository.open(workspace.root)
    assert reopened.consistency.consistent
    assert len(reopened.list_claims()) == 1
    # `init` opens the log with `project.initialized`; the child added exactly one more.
    assert len(list(reopened.iter_events())) == 2

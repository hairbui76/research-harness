"""Interrupting `research rebuild`: the old projection survives, and no half database lands.

A rebuild is the one operation that is *allowed* to lose its work, because `.research/` is
regenerable (ADR-001, ADR-006). What it is not allowed to do is leave a projection that is
neither the old one nor a complete new one - a researcher who runs `rebuild` and loses
power must still be able to search their corpus. `rebuild_workspace` gets that from
building into `research.db.rebuild-<pid>` and moving it into place with `os.replace`, so
this file interrupts on both sides of that rename.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Never

import pytest
from sqlalchemy.engine import Engine

from research_harness.projection.fts import FtsKind, search_fts
from research_harness.projection.rebuild import (
    REBUILD_SUFFIX,
    rebuild_workspace,
    verify_rebuild,
)
from research_harness.projection.schema import create_engine_for
from research_harness.workspace.repository import WorkspaceRepository
from tests.e2e.invariants.workstation import Workstation, canonical_bytes_digest

DATASET = "CICIDS2017"

#: Points inside `_build_database` and the swap, in the order a rebuild reaches them.
REBUILD_CRASH_POINTS: tuple[str, ...] = (
    "research_harness.projection.rebuild._persist_stale",
    "research_harness.projection.rebuild.build_fts",
    "research_harness.projection.rebuild._replace_database",
)


class PowerCutError(RuntimeError):
    """A rebuild that stops in the middle of writing its temporary database."""


def crash(*_args: Any, **_kwargs: Any) -> Never:
    raise PowerCutError("power cut during the rebuild")


def temp_databases(root: Path) -> list[str]:
    """Any `research.db.rebuild-<pid>` file left behind; there should never be one."""
    research = root / ".research"
    if not research.is_dir():
        return []
    return sorted(path.name for path in research.iterdir() if REBUILD_SUFFIX in path.name)


def fts_hits(root: Path, query: str = DATASET) -> list[str]:
    """Search the projection the way the cockpit would; proves it is usable, not just present."""
    engine: Engine = create_engine_for(WorkspaceRepository.open(root).layout.database_file)
    try:
        return [hit.object_id for hit in search_fts(engine, query)]
    finally:
        engine.dispose()


@pytest.fixture
def built(finished: Workstation) -> Iterator[Workstation]:
    """A workspace whose projection is already built, indexed, and answering."""
    report = rebuild_workspace(WorkspaceRepository.open(finished.root))
    assert report.ok and report.fts_rows > 0
    assert fts_hits(finished.root)
    yield finished


# ------------------------------------------------------- the old projection survives


@pytest.mark.parametrize("target", REBUILD_CRASH_POINTS)
def test_a_crash_mid_rebuild_leaves_the_previous_projection_intact_and_usable(
    built: Workstation, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """The temp database is thrown away; the projection a researcher is using is untouched."""
    before = (built.root / ".research" / "research.db").read_bytes()
    hits = fts_hits(built.root)
    monkeypatch.setattr(target, crash)

    with pytest.raises(PowerCutError):
        rebuild_workspace(WorkspaceRepository.open(built.root))
    monkeypatch.undo()

    assert (built.root / ".research" / "research.db").read_bytes() == before
    assert fts_hits(built.root) == hits
    assert any(kind is FtsKind.BLOCK for kind in _kinds(built.root))
    assert temp_databases(built.root) == []


def test_the_interrupted_projection_still_verifies_against_canonical_state(
    built: Workstation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("research_harness.projection.rebuild.build_fts", crash)
    with pytest.raises(PowerCutError):
        rebuild_workspace(WorkspaceRepository.open(built.root))
    monkeypatch.undo()

    repo = WorkspaceRepository.open(built.root)
    engine = create_engine_for(repo.layout.database_file)
    try:
        assert verify_rebuild(repo, engine) == []
    finally:
        engine.dispose()


def test_a_retry_after_the_crash_rebuilds_normally(
    built: Workstation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing about the failed attempt has to be cleaned up by hand."""
    first = rebuild_workspace(WorkspaceRepository.open(built.root))
    monkeypatch.setattr("research_harness.projection.rebuild._replace_database", crash)
    with pytest.raises(PowerCutError):
        rebuild_workspace(WorkspaceRepository.open(built.root))
    monkeypatch.undo()

    second = rebuild_workspace(WorkspaceRepository.open(built.root))

    assert second.ok
    assert second.canonical_digest == first.canonical_digest
    assert second.objects_by_type == first.objects_by_type
    assert temp_databases(built.root) == []


# ------------------------------------------------------- a fresh workspace gets nothing


@pytest.fixture
def fresh(finished: Workstation) -> Iterator[Workstation]:
    """The same workspace with `.research/` deleted: a rebuild starting from nothing."""
    shutil.rmtree(finished.root / ".research")
    yield finished


@pytest.mark.parametrize("target", REBUILD_CRASH_POINTS)
def test_a_crash_on_a_fresh_workspace_leaves_no_half_database(
    fresh: Workstation, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """Better no projection than a projection that silently omits half the corpus."""
    monkeypatch.setattr(target, crash)

    with pytest.raises(PowerCutError):
        rebuild_workspace(WorkspaceRepository.open(fresh.root))
    monkeypatch.undo()

    assert not (fresh.root / ".research" / "research.db").exists()
    assert temp_databases(fresh.root) == []


def test_a_fresh_workspace_rebuilds_after_the_crash(
    fresh: Workstation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("research_harness.projection.rebuild.build_fts", crash)
    with pytest.raises(PowerCutError):
        rebuild_workspace(WorkspaceRepository.open(fresh.root))
    monkeypatch.undo()

    report = rebuild_workspace(WorkspaceRepository.open(fresh.root))

    assert report.ok
    assert report.fts_rows > 0
    assert fts_hits(fresh.root)


# ---------------------------------------------------------- canonical state is untouched


@pytest.mark.parametrize("target", REBUILD_CRASH_POINTS)
def test_an_interrupted_rebuild_never_writes_a_canonical_file(
    built: Workstation, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """A rebuild reads canonical state; interrupting a read cannot damage it (ADR-001)."""
    before = canonical_bytes_digest(built.root)
    monkeypatch.setattr(target, crash)

    with pytest.raises(PowerCutError):
        rebuild_workspace(WorkspaceRepository.open(built.root))
    monkeypatch.undo()

    assert canonical_bytes_digest(built.root) == before
    assert WorkspaceRepository.open(built.root).consistency.consistent


def _kinds(root: Path) -> list[FtsKind]:
    engine = create_engine_for(WorkspaceRepository.open(root).layout.database_file)
    try:
        return [hit.kind for hit in search_fts(engine, DATASET)]
    finally:
        engine.dispose()

"""Product §42.C - Rebuildability.

"Deleting `.research/` and rebuilding reproduces the same accepted Works, Evidence,
Claims, Decisions, and manuscript links."

The loop of ROADMAP §5 runs to the end, then the whole regenerable tree is deleted and
rebuilt. What has to come back identical is every accepted object, byte for byte, plus the
stale marks the projection derives from canonical timestamps alone (ADR-001, ADR-006).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine

from research_harness.projection.dependencies import load_stale_marks
from research_harness.projection.rebuild import (
    RebuildReport,
    rebuild_workspace,
    verify_rebuild,
)
from research_harness.projection.schema import create_engine_for
from research_harness.workspace.events import digest_key, object_digest
from research_harness.workspace.repository import WorkspaceRepository
from tests.e2e.invariants.workstation import (
    OTHER_WORK,
    Workstation,
    canonical_bytes_digest,
)


def accepted_digests(repo: WorkspaceRepository) -> dict[str, str]:
    """Every accepted object's canonical digest, keyed the way the event log keys it.

    Works, Versions, Artifacts, Evidence, Claims, Decisions, Questions, matrices, search
    runs, taxonomies, notes, and manuscript anchors: everything Product §42.C names, and
    everything else that carries authority.
    """
    objects: list[Any] = [
        *repo.list_works(),
        *repo.list_claims(),
        *repo.list_decisions(),
        *repo.list_questions(),
        *repo.list_matrices(),
        *repo.list_search_runs(),
        *repo.list_taxonomies(),
        *repo.iter_notes(),
        *repo.iter_anchors(),
    ]
    for work in repo.list_works():
        objects.extend(repo.list_versions(work.id))
        objects.extend(repo.list_artifacts(work.id))
        objects.extend(repo.iter_evidence(work.id))
    return {digest_key(obj): object_digest(obj) for obj in objects}


def stale_marks(root: Path) -> set[Any]:
    engine = create_engine_for(WorkspaceRepository.open(root).layout.database_file)
    try:
        with engine.connect() as connection:
            return set(load_stale_marks(connection))
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def rebuilt(workstation: Workstation) -> Iterator[tuple[RebuildReport, RebuildReport]]:
    """Build the projection, delete `.research/`, and rebuild it from canonical files."""
    repo = WorkspaceRepository.open(workstation.root)
    first = rebuild_workspace(repo)
    assert first.ok, first.invalid_files
    shutil.rmtree(repo.layout.research_dir)
    reopened = WorkspaceRepository.open(workstation.root)
    second = rebuild_workspace(reopened)
    yield first, second


def test_the_loop_produced_the_accepted_state_the_gate_is_about(
    workstation: Workstation,
) -> None:
    """The preconditions §42.C is measured against, stated once."""
    repo = WorkspaceRepository.open(workstation.root)

    assert [work.id for work in repo.list_works()] == [workstation.work, OTHER_WORK]
    assert [record.id for record in repo.iter_evidence(workstation.work)] == list(
        workstation.evidence
    )
    assert [claim.id for claim in repo.list_claims()] == list(workstation.claims)
    assert len(list(repo.iter_anchors())) == 3
    assert repo.consistency.consistent


def test_deleting_research_and_rebuilding_reproduces_every_accepted_object(
    workstation: Workstation, rebuilt: tuple[RebuildReport, RebuildReport]
) -> None:
    first, second = rebuilt
    repo = WorkspaceRepository.open(workstation.root)

    assert second.ok, second.invalid_files
    assert second.canonical_digest == first.canonical_digest
    assert second.objects_by_type == first.objects_by_type
    assert accepted_digests(repo)  # the digest map is not vacuously equal
    assert second.objects_by_type["Work"] == 2
    assert second.objects_by_type["Evidence"] == len(workstation.evidence)
    assert second.objects_by_type["Claim"] == len(workstation.claims)
    assert second.objects_by_type["ManuscriptAnchor"] == 3


def test_the_rebuild_writes_no_canonical_file(
    workstation: Workstation, rebuilt: tuple[RebuildReport, RebuildReport]
) -> None:
    """A rebuild reads canonical state and writes only `.research/` (ADR-001)."""
    before = canonical_bytes_digest(workstation.root)
    repo = WorkspaceRepository.open(workstation.root)

    assert rebuild_workspace(repo).ok
    assert canonical_bytes_digest(workstation.root) == before


def test_the_rebuilt_projection_agrees_with_canonical_state(
    workstation: Workstation, rebuilt: tuple[RebuildReport, RebuildReport]
) -> None:
    repo = WorkspaceRepository.open(workstation.root)
    engine: Engine = create_engine_for(repo.layout.database_file)
    try:
        assert verify_rebuild(repo, engine) == []
    finally:
        engine.dispose()


def test_the_stale_set_survives_the_deletion(
    mutable_workstation: Workstation,
) -> None:
    """Staleness is derived from canonical timestamps, so `.research/` cannot hold it."""
    root = mutable_workstation.root
    repo = WorkspaceRepository.open(root)
    assert rebuild_workspace(repo).ok
    before = stale_marks(root)

    shutil.rmtree(repo.layout.research_dir)
    assert rebuild_workspace(WorkspaceRepository.open(root)).ok

    assert stale_marks(root) == before


def test_the_workspace_still_opens_consistent_after_the_deletion(
    workstation: Workstation, rebuilt: tuple[RebuildReport, RebuildReport]
) -> None:
    """The event log and canonical state still agree; nothing was replayed to get there."""
    reopened = WorkspaceRepository.open(workstation.root)

    assert reopened.consistency.consistent, reopened.consistency.summary()
    assert reopened.verify().consistent

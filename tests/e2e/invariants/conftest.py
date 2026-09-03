"""Shared fixtures for the Product §42 acceptance suite.

The workstation is built once per module that asks for it: the loop parses a real PDF and
runs two scripted workflow stages, which is cheap enough to repeat but not free. Tests that
mutate their workspace copy it first, so the shared build stays the state the loop left.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e.invariants.workstation import Workstation, build_workstation


@pytest.fixture(scope="module")
def workstation(tmp_path_factory: pytest.TempPathFactory) -> Workstation:
    """A workspace that has been through the whole ROADMAP §5 loop. Treat as read-only."""
    return build_workstation(tmp_path_factory.mktemp("workstation") / "project")


@pytest.fixture
def mutable_workstation(workstation: Workstation, tmp_path: Path) -> Iterator[Workstation]:
    """A private copy of the shared workstation, for a test that writes to it."""
    root = tmp_path / "project"
    shutil.copytree(workstation.root, root)
    yield Workstation(
        root=root,
        work=workstation.work,
        artifact=workstation.artifact,
        evidence=workstation.evidence,
        claims=workstation.claims,
        candidates=dict(workstation.candidates),
    )

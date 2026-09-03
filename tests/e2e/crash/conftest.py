"""Shared fixtures for the crash/recovery suite (ROADMAP Task 17.2).

Every test here interrupts one real operation and then asks the same four questions:
does the workspace open, is the event log still consistent with canonical state, are there
duplicate ids or half-accepted objects, and does a rebuild come back clean. The fixtures
below build the workspaces those questions are asked about.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext
from tests.e2e.invariants.workstation import (
    Workstation,
    build_workstation,
    init_and_ingest,
)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """An initialized workspace with the synthetic paper ingested and parsed."""
    yield init_and_ingest(tmp_path / "project", name="crash-recovery")


@pytest.fixture
def finished(tmp_path: Path) -> Workstation:
    """A workspace that already went through the whole loop, for interrupting what follows."""
    return build_workstation(tmp_path / "finished")

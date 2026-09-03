"""Opt-in performance suite: one benchmark run per session, shared by every budget test.

These tests build a real workspace and time real work, so they are off unless
``RESEARCH_HARNESS_PERF=1`` is set. They exist to catch a regression against the budgets in
`docs/plans/performance-budgets.md`, not to produce publishable numbers: the budgets are
deliberately loose so that a slower CI machine does not fail the build, while an
order-of-magnitude regression still does.

    RESEARCH_HARNESS_PERF=1 uv run pytest tests/perf -q
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from benchmarks.run_benchmarks import BenchmarkResults

PERF_ENV = "RESEARCH_HARNESS_PERF"
PERF_SCALE_ENV = "RESEARCH_HARNESS_PERF_SCALE"

DEFAULT_SCALE = 0.05
"""50 works, 5,000 blocks, 2,500 evidence, 250 claims - the quick-run corpus."""

CANDIDATES = 500
"""Staged candidates for the inbox measurement; the full benchmark stages 5,000."""

perf_enabled = pytest.mark.skipif(
    os.environ.get(PERF_ENV) != "1",
    reason=f"performance suite is opt-in; set {PERF_ENV}=1 to run it",
)


def perf_scale() -> float:
    """Corpus scale for this session, overridable for a quicker or larger sweep."""
    return float(os.environ.get(PERF_SCALE_ENV, DEFAULT_SCALE))


@pytest.fixture(scope="session")
def perf_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Where the session's synthetic workspace is built; pytest removes it afterwards."""
    return tmp_path_factory.mktemp("perf-workspace") / "workspace"


@pytest.fixture(scope="session")
def perf_results(perf_workspace: Path) -> BenchmarkResults:
    """One full benchmark run at the session scale; every budget test reads this."""
    from benchmarks.run_benchmarks import run_benchmarks

    return run_benchmarks(
        perf_workspace,
        scale=perf_scale(),
        seed=7,
        candidates=CANDIDATES,
    )

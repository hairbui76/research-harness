"""Warm-latency budgets for the ResearchGraph index (graph spec §9, Gate P20).

Same opt-in switch as the rest of `tests/perf`: off unless ``RESEARCH_HARNESS_PERF=1``,
because it builds a real corpus and times real work.

    RESEARCH_HARNESS_PERF=1 uv run pytest tests/perf/test_graph_budgets.py -q

Unlike the ceilings in `test_budgets.py`, the numbers asserted here are the *product*
budgets — 100 ms exact, 250 ms neighbourhood, 100 ms autocomplete — not a loosened version
of them. That is safe because the margin is three orders of magnitude: every one of these
is an indexed SQLite lookup measured in tens of microseconds on the benchmark corpus, so a
slow or loaded machine still passes and a genuine regression does not. If one of these ever
fails, the index has stopped being an index.

The corpus is the graph benchmark's own shape at a reduced scale (`RESEARCH_HARNESS_PERF_SCALE`
applies, default the quick 0.05), so the suite runs in seconds; the full-scale numbers and
what they were measured on are in `docs/plans/performance-budgets.md`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from benchmarks.graph.generate_graph_corpus import generate_graph_workspace

from research_harness.graph.bench import (
    AUTOCOMPLETE_BUDGET_MS,
    EXACT_REFERENCE_BUDGET_MS,
    NEIGHBOURHOOD_BUDGET_MS,
    GraphLatencyReport,
    LatencySample,
    measure_graph_latency,
)
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.repository import WorkspaceRepository
from tests.perf.conftest import perf_enabled, perf_scale

pytestmark = perf_enabled

#: The graph corpus scales with the same knob the rest of the perf suite uses, but its
#: 1.0 is 200 works rather than 1,000 (see `benchmarks/graph/generate_graph_corpus.py`),
#: so the quick run is a proportionally smaller graph, not a different shape.
GRAPH_SCALE_FACTOR = 5.0

BUDGETS: dict[str, float] = {
    "exact reference resolution": EXACT_REFERENCE_BUDGET_MS,
    "one-hop neighbourhood": NEIGHBOURHOOD_BUDGET_MS,
    "two-hop neighbourhood": NEIGHBOURHOOD_BUDGET_MS,
    "two-hop neighbourhood, project-visible only": NEIGHBOURHOOD_BUDGET_MS,
    "autocomplete": AUTOCOMPLETE_BUDGET_MS,
}


@pytest.fixture(scope="session")
def graph_perf_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The graph benchmark corpus at the session scale, built once."""
    root = tmp_path_factory.mktemp("graph-perf") / "workspace"
    generate_graph_workspace(root, scale=perf_scale() * GRAPH_SCALE_FACTOR, seed=7)
    return root


@pytest.fixture(scope="session")
def graph_perf_report(graph_perf_workspace: Path) -> Iterator[GraphLatencyReport]:
    """One warm latency run over that corpus; every budget test reads this."""
    repo = WorkspaceRepository.open(graph_perf_workspace, repair=True)
    graph = ResearchGraph(repo)
    try:
        graph.rebuild()
        yield measure_graph_latency(graph)
    finally:
        graph.close()


def _sample(report: GraphLatencyReport, name: str) -> LatencySample:
    sample = report.by_name(name)
    measured = [item.name for item in report.samples]
    assert sample is not None, f"{name!r} was not measured; ran {measured}"
    return sample


@pytest.mark.parametrize("name", sorted(BUDGETS))
def test_a_budgeted_query_mode_is_warm_inside_its_budget(
    graph_perf_report: GraphLatencyReport, name: str
) -> None:
    """Graph spec §9, measured as the median of several warm runs on a shared machine."""
    sample = _sample(graph_perf_report, name)

    assert sample.median_ms <= BUDGETS[name], (
        f"{name}: median {sample.median_ms:.2f} ms over {sample.runs} warm runs, "
        f"budget {BUDGETS[name]:.0f} ms"
    )


@pytest.mark.parametrize("name", sorted(BUDGETS))
def test_the_p95_of_a_budgeted_mode_is_inside_its_budget_too(
    graph_perf_report: GraphLatencyReport, name: str
) -> None:
    """A researcher feels the slow keystroke, not the median one."""
    sample = _sample(graph_perf_report, name)

    assert sample.p95_ms <= BUDGETS[name], (
        f"{name}: p95 {sample.p95_ms:.2f} ms over {sample.runs} warm runs, "
        f"budget {BUDGETS[name]:.0f} ms"
    )


def test_privacy_filtering_does_not_cost_a_budget(graph_perf_report: GraphLatencyReport) -> None:
    """The filtered walk is the one a provider-bound request makes; it must not be slower."""
    plain = _sample(graph_perf_report, "two-hop neighbourhood")
    filtered = _sample(graph_perf_report, "two-hop neighbourhood, project-visible only")

    assert filtered.median_ms <= NEIGHBOURHOOD_BUDGET_MS
    assert filtered.median_ms <= max(plain.median_ms * 4, 1.0)


def test_context_assembly_stays_inside_the_neighbourhood_budget(
    graph_perf_report: GraphLatencyReport,
) -> None:
    """Assembly is several traversals; it is budgeted as one because a send waits on it."""
    sample = _sample(graph_perf_report, "context fragments, project-visible")

    assert sample.median_ms <= NEIGHBOURHOOD_BUDGET_MS


def test_the_graph_has_the_shape_the_budgets_assume(
    graph_perf_report: GraphLatencyReport,
) -> None:
    """A budget only means something against the graph it was measured on."""
    assert graph_perf_report.nodes > 1_000
    assert graph_perf_report.edges > graph_perf_report.nodes
    assert graph_perf_report.sources > 100


def test_every_measured_mode_met_its_budget(graph_perf_report: GraphLatencyReport) -> None:
    """The Gate P20 latency line, as one assertion."""
    failed = [sample.summary() for sample in graph_perf_report.samples if not sample.within_budget]

    assert not failed, "\n".join(failed)

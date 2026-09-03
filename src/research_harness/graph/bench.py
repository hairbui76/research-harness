"""Warm-latency measurement for the query modes graph spec §9 puts a budget on.

Three budgets, and this module measures exactly them against whatever graph it is handed:

* exact stable-reference resolution — under 100 ms;
* one- and two-hop neighbourhood queries — under 250 ms;
* autocomplete — fast enough to update while a researcher types, taken here as 100 ms.

"Warm" is load-bearing. A cold measurement times opening a SQLite file and faulting its
pages in, which is not what a researcher waits on after the first keystroke, so every
workload runs a discarded warm-up pass and then reports a distribution over repeats. The
reported number is the median: these calls are milliseconds long, the machine they run on
is shared, and a mean would be a report on the noisiest run rather than on the query.

The workload is derived from the graph itself — the identities it actually holds, and
prefixes taken off them — so the same measurement runs against the benchmark corpus, a
test fixture, or a real workspace without a fixture to keep in step.

Nothing here writes, and nothing here is a budget *enforcement*: `tests/perf` compares
these numbers with the ceilings, and `docs/plans/performance-budgets.md` records them.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from research_harness.domain.graph import GraphVisibility, NodeKind
from research_harness.graph.queries import DEFAULT_LIMIT, Direction, GraphFilter
from research_harness.graph.service import ResearchGraph

__all__ = [
    "AUTOCOMPLETE_BUDGET_MS",
    "DEFAULT_REPEATS",
    "EXACT_REFERENCE_BUDGET_MS",
    "NEIGHBOURHOOD_BUDGET_MS",
    "GraphLatencyReport",
    "GraphWorkload",
    "LatencySample",
    "measure_graph_latency",
    "workload_for",
]

EXACT_REFERENCE_BUDGET_MS = 100.0
"""Graph spec §9: resolving `@E0482` warm."""

NEIGHBOURHOOD_BUDGET_MS = 250.0
"""Graph spec §9: a one- or two-hop neighbourhood warm."""

AUTOCOMPLETE_BUDGET_MS = 100.0
"""Graph spec §9 asks for "interactive"; 100 ms is the usual keystroke-response ceiling."""

DEFAULT_REPEATS = 9
"""Odd, so the median is a measured run rather than an interpolation between two."""

_SAMPLE_KINDS: tuple[NodeKind, ...] = (
    NodeKind.CLAIM,
    NodeKind.EVIDENCE,
    NodeKind.WORK,
    NodeKind.ARTIFACT,
    NodeKind.SESSION,
    NodeKind.MESSAGE,
    NodeKind.PARAGRAPH,
)
_PER_KIND = 6
_PREFIX_CHARS = 3


@dataclass(frozen=True, slots=True)
class LatencySample:
    """One timed query mode: its distribution over repeats, and the budget it is held to."""

    group: str
    name: str
    runs: int
    median_ms: float
    p95_ms: float
    max_ms: float
    budget_ms: float
    queries: int
    """How many distinct inputs one run covered; the timing is per input."""

    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def within_budget(self) -> bool:
        """True when the median run met the budget graph spec §9 sets for it."""
        return self.median_ms <= self.budget_ms

    def summary(self) -> str:
        """One line for a terminal, a log, or a report table."""
        verdict = "pass" if self.within_budget else "FAIL"
        return (
            f"{self.name}: median {self.median_ms:.2f} ms, p95 {self.p95_ms:.2f} ms "
            f"(budget {self.budget_ms:.0f} ms, {self.queries} queries x {self.runs} runs) "
            f"[{verdict}]"
        )


@dataclass(frozen=True, slots=True)
class GraphWorkload:
    """The identities and prefixes a measurement runs against, taken from the graph."""

    identities: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    sessions: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when the graph holds nothing to measure against."""
        return not self.identities


@dataclass(frozen=True, slots=True)
class GraphLatencyReport:
    """Everything one latency run measured, plus the size of the graph it ran on."""

    samples: tuple[LatencySample, ...] = ()
    nodes: int = 0
    edges: int = 0
    sources: int = 0

    @property
    def within_budget(self) -> bool:
        """True when every measured mode met its budget."""
        return all(sample.within_budget for sample in self.samples)

    def by_name(self, name: str) -> LatencySample | None:
        """One sample by name, or ``None`` when the workload could not run it."""
        return next((sample for sample in self.samples if sample.name == name), None)

    def summary(self) -> list[str]:
        """The report as lines, size first."""
        return [
            f"graph: {self.nodes} nodes, {self.edges} edges from {self.sources} source(s)",
            *(f"  {sample.summary()}" for sample in self.samples),
        ]


def workload_for(graph: ResearchGraph, *, per_kind: int = _PER_KIND) -> GraphWorkload:
    """Sample identities and completion prefixes out of the graph under measurement."""
    identities: list[str] = []
    claims: list[str] = []
    sessions: list[str] = []
    for kind in _SAMPLE_KINDS:
        found = graph.query(GraphFilter(kinds=(kind,), limit=per_kind))
        identities.extend(record.identity for record in found)
        if kind is NodeKind.CLAIM:
            claims.extend(record.identity for record in found)
        if kind is NodeKind.SESSION:
            sessions.extend(record.identity for record in found)
    prefixes = sorted(
        {
            identity[:_PREFIX_CHARS]
            for identity in identities
            if len(identity) > _PREFIX_CHARS and ":" not in identity[:_PREFIX_CHARS]
        }
    )
    return GraphWorkload(
        identities=tuple(identities),
        prefixes=tuple(prefixes),
        claims=tuple(claims),
        sessions=tuple(sessions),
    )


def measure_graph_latency(
    graph: ResearchGraph,
    *,
    repeats: int = DEFAULT_REPEATS,
    workload: GraphWorkload | None = None,
) -> GraphLatencyReport:
    """Time every budgeted query mode against ``graph``, warm.

    Each mode is run once and discarded, then ``repeats`` times over the same inputs; the
    reported millisecond figures are per *query*, so a corpus with more sample identities
    is not penalised for measuring more of them.
    """
    status = graph.status()
    plan = workload_for(graph) if workload is None else workload
    if plan.is_empty:
        return GraphLatencyReport(nodes=status.nodes, edges=status.edges, sources=status.sources)
    samples = [
        _measure(
            "resolution",
            "exact reference resolution",
            lambda: [graph.resolve(identity) for identity in plan.identities],
            queries=len(plan.identities),
            budget=EXACT_REFERENCE_BUDGET_MS,
            repeats=repeats,
        ),
        _measure(
            "traversal",
            "one-hop neighbourhood",
            lambda: [
                graph.neighbors(identity, hops=1, limit=DEFAULT_LIMIT)
                for identity in plan.identities
            ],
            queries=len(plan.identities),
            budget=NEIGHBOURHOOD_BUDGET_MS,
            repeats=repeats,
        ),
        _measure(
            "traversal",
            "two-hop neighbourhood",
            lambda: [
                graph.neighbors(identity, hops=2, limit=DEFAULT_LIMIT)
                for identity in plan.identities
            ],
            queries=len(plan.identities),
            budget=NEIGHBOURHOOD_BUDGET_MS,
            repeats=repeats,
        ),
        _measure(
            "traversal",
            "two-hop neighbourhood, project-visible only",
            lambda: [
                graph.neighbors(
                    identity,
                    hops=2,
                    direction=Direction.BOTH,
                    visibility=(GraphVisibility.PROJECT,),
                    limit=DEFAULT_LIMIT,
                )
                for identity in plan.identities
            ],
            queries=len(plan.identities),
            budget=NEIGHBOURHOOD_BUDGET_MS,
            repeats=repeats,
        ),
    ]
    if plan.prefixes:
        samples.append(
            _measure(
                "completion",
                "autocomplete",
                lambda: [graph.autocomplete(prefix, limit=10) for prefix in plan.prefixes],
                queries=len(plan.prefixes),
                budget=AUTOCOMPLETE_BUDGET_MS,
                repeats=repeats,
            )
        )
    if plan.claims:
        samples.append(
            _measure(
                "provenance",
                "provenance path to artifact",
                lambda: [graph.provenance(claim) for claim in plan.claims],
                queries=len(plan.claims),
                budget=NEIGHBOURHOOD_BUDGET_MS,
                repeats=repeats,
            )
        )
    samples.append(
        _measure(
            "context",
            "context fragments, project-visible",
            lambda: [
                graph.context_fragments(
                    session=plan.sessions[0] if plan.sessions else None,
                    query="dataset",
                    references=list(plan.claims[:3]),
                    visibility=GraphVisibility.PROJECT.value,
                    limit=40,
                )
            ],
            queries=1,
            budget=NEIGHBOURHOOD_BUDGET_MS,
            repeats=repeats,
        )
    )
    return GraphLatencyReport(
        samples=tuple(samples),
        nodes=status.nodes,
        edges=status.edges,
        sources=status.sources,
    )


def _measure(
    group: str,
    name: str,
    operation: Callable[[], object],
    *,
    queries: int,
    budget: float,
    repeats: int,
) -> LatencySample:
    """Warm up once, then time ``repeats`` runs and report per-query milliseconds."""
    operation()
    runs = max(1, int(repeats))
    per_query: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        operation()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        per_query.append(elapsed_ms / max(1, queries))
    ordered = sorted(per_query)
    return LatencySample(
        group=group,
        name=name,
        runs=runs,
        median_ms=_percentile(ordered, 0.50),
        p95_ms=_percentile(ordered, 0.95),
        max_ms=ordered[-1],
        budget_ms=budget,
        queries=queries,
    )


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile of an already-sorted sample, in the units it was given in."""
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]

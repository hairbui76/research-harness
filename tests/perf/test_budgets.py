"""Regression budgets for the personal-scale paths (ROADMAP Task 17.3).

Every budget here is measured at the quick-run scale (0.05 of the target corpus) and set
several times looser than the number this repository measured, so the suite fails on an
order-of-magnitude regression and not on a slow disk. The budgets a researcher should
actually get -- and the gap between them and today's numbers -- live in
`docs/plans/performance-budgets.md`; the two must be updated together.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from benchmarks.generate_corpus import (
    BLOCKS_PER_WORK,
    EVIDENCE_PER_WORK,
    generate_workspace,
)
from benchmarks.run_benchmarks import BenchmarkResults, Measurement

from tests.perf.conftest import perf_enabled, perf_scale

pytestmark = perf_enabled


@dataclass(frozen=True, slots=True)
class Budget:
    """A ceiling on one measurement, matched by the prefix of its name."""

    prefix: str
    seconds: float | None = None
    p95_ms: float | None = None
    why: str = ""

    def __str__(self) -> str:
        return self.prefix


BUDGETS: tuple[Budget, ...] = (
    Budget(
        "generate_workspace",
        seconds=120.0,
        why="corpus generation is not a researcher-facing path; the ceiling guards the "
        "canonical write path it exercises",
    ),
    Budget(
        "WorkspaceRepository.open (full verification)",
        seconds=10.0,
        why="re-deriving every digest the event log names: linear in objects since "
        "verification indexes each canonical file once instead of rescanning it per id",
    ),
    Budget(
        "WorkspaceRepository.open (verification cached)",
        seconds=5.0,
        why="the open a researcher gets when nothing moved: one stat per canonical file "
        "and one hash of the event log, never a re-derived digest",
    ),
    Budget(
        "rebuild_workspace (after rm -rf",
        seconds=30.0,
        why="a full rebuild from canonical files with no projection to reuse, digesting "
        "each canonical file's bytes rather than re-serializing every record",
    ),
    Budget("search_fts", p95_ms=50.0, why="exact-terminology search must feel instant"),
    Budget("StagingStore.list", seconds=10.0, why="reading the staging tree back"),
    Budget("build_inbox", seconds=10.0, why="the Review Inbox a session opens with"),
    Budget(
        "DependencyGraph.from_objects",
        seconds=30.0,
        why="the graph behind every staleness question",
    ),
    Budget("mark_changed", seconds=5.0, why="invalidation from one hub object"),
    Budget("assess_strength", seconds=30.0, why="a claim audit sweep"),
    Budget("independent_support", seconds=30.0, why="independence accounting per claim"),
    Budget("load_stale_marks", seconds=10.0, why="reading the stale set from the projection"),
    Budget("SemanticIndex.rebuild", seconds=300.0, why="re-embedding the whole corpus"),
    Budget("SemanticIndex.query", p95_ms=100.0, why="vector lookup inside one query plan"),
    Budget("RetrievalService.search", p95_ms=750.0, why="the whole authority-ladder walk"),
)


def _find(results: BenchmarkResults, prefix: str) -> Measurement:
    match = next((item for item in results.measurements if item.name.startswith(prefix)), None)
    names = [item.name for item in results.measurements]
    assert match is not None, f"no measurement starting with {prefix!r}; ran {names}"
    return match


@pytest.mark.parametrize("budget", BUDGETS, ids=str)
def test_measurement_stays_within_its_budget(
    perf_results: BenchmarkResults, budget: Budget
) -> None:
    """Each timed path stays under the ceiling recorded for it."""
    measurement = _find(perf_results, budget.prefix)
    if budget.seconds is not None:
        assert measurement.seconds is not None, f"{budget.prefix} was not measured"
        assert measurement.seconds <= budget.seconds, (
            f"{measurement.name} took {measurement.seconds:.2f}s, budget {budget.seconds:.2f}s "
            f"({budget.why})"
        )
    if budget.p95_ms is not None:
        assert measurement.p95_ms is not None, f"{budget.prefix} recorded no p95"
        assert measurement.p95_ms <= budget.p95_ms, (
            f"{measurement.name} p95 was {measurement.p95_ms:.1f}ms, budget "
            f"{budget.p95_ms:.1f}ms ({budget.why})"
        )


def test_corpus_has_the_shape_the_budgets_assume(perf_results: BenchmarkResults) -> None:
    """A budget only means something against the corpus it was measured on."""
    corpus = perf_results.corpus
    expected_works = max(1, round(1_000 * perf_scale()))
    assert corpus["works"] == expected_works
    assert corpus["blocks"] == expected_works * BLOCKS_PER_WORK
    assert corpus["evidence"] == expected_works * EVIDENCE_PER_WORK
    assert corpus["claims"] == max(1, round(5_000 * perf_scale()))


def test_the_cached_open_is_the_one_that_skipped_verification(
    perf_results: BenchmarkResults,
) -> None:
    """A cached-open budget met by re-running the full check would measure nothing."""
    measurement = _find(perf_results, "WorkspaceRepository.open (verification cached)")
    assert measurement.detail["skipped"] is True


def test_rebuild_projects_every_canonical_object(perf_results: BenchmarkResults) -> None:
    """A rebuild that silently drops objects would make every other budget meaningless."""
    measurement = _find(perf_results, "rebuild_workspace (after rm -rf")
    projected = measurement.detail["objects"]
    corpus = perf_results.corpus
    minimum = corpus["works"] * 3 + corpus["blocks"] + corpus["evidence"] + corpus["claims"]
    assert projected >= minimum, f"rebuild projected {projected} objects, expected >= {minimum}"


def test_fts_queries_actually_match_the_corpus(perf_results: BenchmarkResults) -> None:
    """An FTS budget measured against zero hits would be measuring an empty index."""
    measurement = _find(perf_results, "search_fts")
    assert measurement.detail["hits"] > 0, "the FTS budget was measured against an empty index"


def _canonical_files(root: Path) -> dict[str, bytes]:
    """Canonical bytes by workspace-relative path, minus what `init` stamps with the clock.

    `research.yaml` carries the project's wall-clock ``created_at``, and the first line of
    the event log is the `project.initialized` event the repository writes for itself;
    neither is generated from the seed.
    """
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".research" in path.parts or path.name == "research.yaml":
            continue
        relative = str(path.relative_to(root))
        content = path.read_bytes()
        if relative == "events/research.jsonl":
            content = content.split(b"\n", 1)[1]
        files[relative] = content
    return files


def test_generation_is_deterministic_for_a_seed(tmp_path: Path) -> None:
    """Two runs of one seed produce byte-identical canonical state.

    Determinism is what makes two benchmark runs comparable: if the corpus drifted, so
    would every number measured against it.
    """
    runs = []
    for name in ("a", "b"):
        target = tmp_path / name
        generate_workspace(target, works=3, claims=6, seed=11)
        runs.append(_canonical_files(target))
    assert sorted(runs[0]) == sorted(runs[1])
    differing = [name for name, content in runs[0].items() if runs[1][name] != content]
    assert not differing, f"generation is not deterministic for these files: {differing}"

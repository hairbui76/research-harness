"""Time the ResearchGraph query modes graph spec §9 budgets, on the personal-scale corpus.

Builds (or reuses) the corpus of :mod:`benchmarks.graph.generate_graph_corpus`, projects
the graph twice — a full rebuild, then an incremental update over it — and measures the
warm latency of every budgeted query mode through `research_harness.graph.bench`.

    uv run python -m benchmarks.graph.run_graph_benchmarks --root /tmp/graph --scale 1.0 \\
        --json /tmp/graph.json --markdown /tmp/graph.md
    uv run python -m benchmarks.graph.run_graph_benchmarks --root /tmp/graph --reuse

The build numbers are informational: a rebuild is `research rebuild`'s cost and is already
budgeted by `benchmarks/run_benchmarks.py` for the SQLite projection. What this run exists
to answer is the three §9 questions — exact reference, one/two-hop neighbourhood, and
autocomplete — and it prints the verdict for each against its own budget.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import resource
import shutil
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.graph.generate_graph_corpus import GraphCorpusReport, generate_graph_workspace
from research_harness.graph.bench import (
    DEFAULT_REPEATS,
    GraphLatencyReport,
    measure_graph_latency,
)
from research_harness.graph.schema import graph_dir
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.repository import WorkspaceRepository

__all__ = ["GraphBenchmarkResults", "main", "run_graph_benchmarks"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GraphBenchmarkResults:
    """One graph benchmark run: the corpus, the two builds, and the latency report."""

    started_at: str
    scale: float
    machine: dict[str, Any]
    corpus: dict[str, Any]
    rebuild_ms: int
    update_ms: int
    database_bytes: int
    peak_rss_bytes: int
    latency: GraphLatencyReport

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "started_at": self.started_at,
            "scale": self.scale,
            "machine": self.machine,
            "corpus": self.corpus,
            "rebuild_ms": self.rebuild_ms,
            "update_ms": self.update_ms,
            "database_bytes": self.database_bytes,
            "peak_rss_bytes": self.peak_rss_bytes,
            "graph": {
                "nodes": self.latency.nodes,
                "edges": self.latency.edges,
                "sources": self.latency.sources,
            },
            "measurements": [
                {
                    "group": sample.group,
                    "name": sample.name,
                    "runs": sample.runs,
                    "queries": sample.queries,
                    "median_ms": sample.median_ms,
                    "p95_ms": sample.p95_ms,
                    "max_ms": sample.max_ms,
                    "budget_ms": sample.budget_ms,
                    "within_budget": sample.within_budget,
                }
                for sample in self.latency.samples
            ],
        }

    def markdown(self) -> str:
        """A Markdown report: machine, corpus, builds, and the latency table."""
        lines = [
            f"# ResearchGraph benchmark (scale {self.scale})",
            "",
            f"Run {self.started_at} on {self.machine['platform']}, "
            f"{self.machine['cpu_count']} CPUs, Python {self.machine['python']}.",
            f"Peak RSS {self.peak_rss_bytes / 1e6:.0f} MB.",
            "",
            "## Graph",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
            f"| nodes | {self.latency.nodes:,} |",
            f"| edges | {self.latency.edges:,} |",
            f"| sources | {self.latency.sources:,} |",
            f"| database bytes | {self.database_bytes:,} |",
            f"| full rebuild | {self.rebuild_ms:,} ms |",
            f"| incremental update (nothing changed) | {self.update_ms:,} ms |",
            "",
            "## Warm latency",
            "",
            "| Group | Query mode | Median | p95 | Max | Budget | Verdict |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for sample in self.latency.samples:
            verdict = "pass" if sample.within_budget else "**fail**"
            lines.append(
                f"| {sample.group} | {sample.name} | {sample.median_ms:.2f} ms "
                f"| {sample.p95_ms:.2f} ms | {sample.max_ms:.2f} ms "
                f"| {sample.budget_ms:.0f} ms | {verdict} |"
            )
        lines.extend(["", "## Corpus", "", "| Objects | Count |", "| --- | ---: |"])
        canonical = dict(self.corpus.get("canonical", {}))
        for key in (
            "works",
            "blocks",
            "evidence",
            "claims",
            "claim_relations",
            "manuscript_anchors",
        ):
            lines.append(f"| {key.replace('_', ' ')} | {canonical.get(key, 0):,} |")
        for key in ("sessions", "private_sessions", "messages", "attachments", "references"):
            lines.append(f"| {key.replace('_', ' ')} | {self.corpus.get(key, 0):,} |")
        return "\n".join(lines) + "\n"


def run_graph_benchmarks(
    root: Path,
    *,
    scale: float = 1.0,
    seed: int = 7,
    repeats: int = DEFAULT_REPEATS,
    reuse: bool = False,
) -> GraphBenchmarkResults:
    """Generate (or reuse) the corpus, build the graph twice, and time every query mode."""
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    target = Path(root)
    corpus = _corpus(target, scale=scale, seed=seed, reuse=reuse)
    repo = WorkspaceRepository.open(target, repair=True)
    graph = ResearchGraph(repo)
    try:
        rebuild = graph.rebuild()
        logger.info("%s", rebuild.summary())
        update = graph.update()
        logger.info("%s", update.summary())
        latency = measure_graph_latency(graph, repeats=repeats)
        database_bytes = graph.database.stat().st_size if graph.database.is_file() else 0
    finally:
        graph.close()
    return GraphBenchmarkResults(
        started_at=started_at,
        scale=scale,
        machine=_machine_info(),
        corpus=corpus.as_dict(),
        rebuild_ms=rebuild.duration_ms,
        update_ms=update.duration_ms,
        database_bytes=database_bytes,
        peak_rss_bytes=_peak_rss_bytes(),
        latency=latency,
    )


def _corpus(root: Path, *, scale: float, seed: int, reuse: bool) -> GraphCorpusReport:
    """Build the corpus, or read back the report of the one already at ``root``."""
    marker = graph_dir(root / ".research").parent / "graph-corpus.json"
    if reuse and marker.is_file():
        return GraphCorpusReport(**json.loads(marker.read_text(encoding="utf-8")))
    if root.exists():
        shutil.rmtree(root)
    report = generate_graph_workspace(root, scale=scale, seed=seed)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return report


def _machine_info() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count() or 0,
        "python": platform.python_version(),
    }


def _peak_rss_bytes() -> int:
    """Peak resident set size of this process; ``ru_maxrss`` is KiB on Linux."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage) * (1 if sys.platform == "darwin" else 1024)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: build the corpus, measure the graph, and print or write the report."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, required=True, help="workspace directory")
    parser.add_argument("--scale", type=float, default=1.0, help="fraction of the agreed shape")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--reuse", action="store_true", help="measure the corpus already there")
    parser.add_argument("--json", type=Path, default=None, dest="json_path")
    parser.add_argument("--markdown", type=Path, default=None, dest="markdown_path")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO)
    results = run_graph_benchmarks(
        args.root, scale=args.scale, seed=args.seed, repeats=args.repeats, reuse=args.reuse
    )
    if args.json_path is not None:
        args.json_path.write_text(
            json.dumps(results.as_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
    if args.markdown_path is not None:
        args.markdown_path.write_text(results.markdown(), encoding="utf-8")
    for line in results.latency.summary():
        print(line)
    return 0 if results.latency.within_budget else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())

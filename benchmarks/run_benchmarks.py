"""Measure the paths a researcher waits on, at personal scale (ROADMAP Task 17.3).

Everything here times public entry points against a workspace built by
:mod:`benchmarks.generate_corpus`. Cheap operations are run three times and reported by
their median; expensive ones are run once, because a second run of a five-minute rebuild
buys less than it costs. Wall time comes from :func:`time.perf_counter`, peak memory from
:func:`resource.getrusage`, and sizes from the files themselves.

    uv run python -m benchmarks.run_benchmarks --root /tmp/bench --scale 1.0 --json out.json

Web interaction latency is *not* measured: the Web surface (ROADMAP Phase 16) does not
exist yet, and a placeholder number would be worse than an absent one.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import logging
import os
import platform
import pstats
import resource
import shutil
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from benchmarks.generate_corpus import (
    DATASETS,
    METRICS,
    GenerationReport,
    generate_workspace,
)
from research_harness.citations import CitationEdge, CitationGraph, independent_support
from research_harness.claims import StrengthInput, assess_strength
from research_harness.domain import (
    Evidence,
    EvidenceContent,
    EvidenceId,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    Provenance,
    ReviewTier,
    Work,
    WorkId,
)
from research_harness.evidence import (
    CandidateStatus,
    EvidenceCandidate,
    ExtractionProvenance,
    StagingStore,
    build_inbox,
    candidate_id_for,
    stored_documents,
)
from research_harness.parsing.anchors import build_anchor
from research_harness.projection import (
    DependencyGraph,
    create_engine_for,
    load_stale_marks,
    mark_changed,
    rebuild_workspace,
    search_fts,
)
from research_harness.providers.models.embeddings import HashingEmbeddingProvider
from research_harness.retrieval import (
    RetrievalService,
    SemanticIndex,
    units_from_document,
    units_from_evidence,
)
from research_harness.workspace.events import clear_consistency_marker
from research_harness.workspace.layout import WorkspaceLayout
from research_harness.workspace.repository import WorkspaceConfig, WorkspaceRepository
from research_harness.workspace.serialization import read_yaml

__all__ = [
    "DEFAULT_CANDIDATES",
    "DEFAULT_EMBEDDING_DIMENSION",
    "FTS_QUERIES",
    "QUICK_CANDIDATES",
    "QUICK_SCALE",
    "RETRIEVAL_QUERIES",
    "BenchmarkResults",
    "Measurement",
    "machine_info",
    "main",
    "run_benchmarks",
]

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATES = 5_000
DEFAULT_EMBEDDING_DIMENSION = 256

QUICK_SCALE = 0.05
"""Corpus fraction `--quick` uses: 50 works, 5,000 blocks, 2,500 evidence, 250 claims."""

QUICK_CANDIDATES = 500
"""Inbox candidates `--quick` stages; enough to see the queue, cheap enough to iterate on."""
SEMANTIC_QUERY_COUNT = 20
RETRIEVAL_QUERY_COUNT = 10
STRENGTH_CLAIMS = 1_000
INDEPENDENCE_CLAIMS = 100
CHEAP_REPEATS = 3

FTS_QUERIES: tuple[str, ...] = (
    "CICIDS2017",
    "UNSW-NB15",
    "ImageNet",
    "LibriSpeech",
    "MIMIC-III",
    "perplexity",
    "AUROC",
    "nDCG",
    "ROUGE-L",
    "calibration error",
    '"protocol field semantics"',
    '"distribution shift"',
    '"inference latency"',
    '"held-out split"',
    "tokeniz*",
    "calibrat*",
    "represent*",
    "abla*",
    "CICIDS2017 AND F1",
    "ImageNet OR CIFAR-10",
)

RETRIEVAL_QUERIES: tuple[str, ...] = (
    "which systems report F1 on CICIDS2017",
    "protocol field semantics",
    "what is the reported perplexity on WikiText-103",
    "ablation on distribution shift",
    "baselines compared on ImageNet",
    "evidence about calibration error",
    "inference latency of the graph neural detector",
    "annotation agreement in MIMIC-III",
    "claims about representation granularity",
    "nDCG results on MS-MARCO",
)

SEMANTIC_QUERIES: tuple[str, ...] = tuple(
    f"{dataset} {metric}"
    for dataset, metric in zip(DATASETS, METRICS[: len(DATASETS)], strict=True)
) + tuple(f"results table reporting {metric}" for metric in METRICS[:8])


# --- measurements -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Measurement:
    """One timed operation: its wall time, its per-query distribution, and its context."""

    group: str
    name: str
    seconds: float | None
    runs: int = 1
    p50_ms: float | None = None
    p95_ms: float | None = None
    note: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return asdict(self)

    def value_text(self) -> str:
        """Wall time as a short human string, or why it is absent."""
        if self.seconds is None:
            return "not measured"
        if self.seconds < 1.0:
            return f"{self.seconds * 1000:.1f} ms"
        return f"{self.seconds:.2f} s"


@dataclass(frozen=True, slots=True)
class BenchmarkResults:
    """Everything one benchmark run produced."""

    machine: dict[str, Any]
    corpus: dict[str, Any]
    measurements: list[Measurement]
    sizes: dict[str, int]
    peak_rss_bytes: int
    profiles: dict[str, list[str]]
    scale: float
    started_at: str

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "started_at": self.started_at,
            "scale": self.scale,
            "machine": self.machine,
            "corpus": self.corpus,
            "sizes": self.sizes,
            "peak_rss_bytes": self.peak_rss_bytes,
            "measurements": [item.as_dict() for item in self.measurements],
            "profiles": self.profiles,
        }

    def by_name(self, name: str) -> Measurement | None:
        """One measurement by name, or None when it was not run."""
        return next((item for item in self.measurements if item.name == name), None)

    def markdown(self) -> str:
        """A Markdown report: machine, corpus, and the measurement table."""
        lines = [
            f"# Research Harness benchmark (scale {self.scale})",
            "",
            f"Run {self.started_at} on {self.machine['platform']}, "
            f"{self.machine['cpu_count']} CPUs, Python {self.machine['python']}.",
            f"Peak RSS {self.peak_rss_bytes / 1e6:.0f} MB.",
            "",
            "## Corpus",
            "",
            "| Objects | Count |",
            "| --- | ---: |",
        ]
        for key in (
            "works",
            "blocks",
            "evidence",
            "claims",
            "claim_relations",
            "matrices",
            "matrix_cells",
            "manuscript_anchors",
            "events",
            "transactions",
        ):
            lines.append(f"| {key.replace('_', ' ')} | {self.corpus.get(key, 0):,} |")
        lines.extend(["", "## Sizes", "", "| File or tree | Bytes |", "| --- | ---: |"])
        for key, value in sorted(self.sizes.items()):
            lines.append(f"| {key.replace('_', ' ')} | {value:,} |")
        lines.extend(
            [
                "",
                "## Measurements",
                "",
                "| Group | Measurement | Wall time | p50 | p95 | Runs | Note |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for item in self.measurements:
            p50 = "-" if item.p50_ms is None else f"{item.p50_ms:.1f} ms"
            p95 = "-" if item.p95_ms is None else f"{item.p95_ms:.1f} ms"
            lines.append(
                f"| {item.group} | {item.name} | {item.value_text()} | {p50} | {p95} "
                f"| {item.runs} | {item.note} |"
            )
        for name, rows in self.profiles.items():
            lines.extend(["", f"### cProfile: {name} (top by cumulative time)", "", "```"])
            lines.extend(rows)
            lines.append("```")
        return "\n".join(lines) + "\n"


# --- timing helpers ---------------------------------------------------------


def _time_once[T](operation: Callable[[], T]) -> tuple[float, T]:
    started = time.perf_counter()
    result = operation()
    return time.perf_counter() - started, result


def _time_repeated(operation: Callable[[], object], runs: int) -> list[float]:
    return [_time_once(operation)[0] for _ in range(max(1, runs))]


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile of ``values`` in the units they were given in."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


def _latency_measurement(
    group: str, name: str, samples_ms: Sequence[float], *, note: str = "", **detail: Any
) -> Measurement:
    return Measurement(
        group=group,
        name=name,
        seconds=sum(samples_ms) / 1000.0,
        runs=len(samples_ms),
        p50_ms=_percentile(samples_ms, 0.50),
        p95_ms=_percentile(samples_ms, 0.95),
        note=note,
        detail=detail,
    )


def _peak_rss_bytes() -> int:
    """Peak resident set size of this process; ``ru_maxrss`` is KiB on Linux."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage) * (1 if sys.platform == "darwin" else 1024)


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def machine_info() -> dict[str, Any]:
    """CPU count, platform, and interpreter, recorded with every result set."""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count() or 0,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
    }


def _profile_rows(operation: Callable[[], object], *, limit: int = 15) -> list[str]:
    """Top functions of ``operation`` by cumulative time, as plain report lines."""
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        operation()
    finally:
        profiler.disable()
    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer).sort_stats("cumulative")
    stats.print_stats(limit)
    return [line.rstrip() for line in buffer.getvalue().splitlines() if line.strip()]


# --- workspace access -------------------------------------------------------


def open_unverified(root: Path) -> WorkspaceRepository:
    """A repository handle that skips recovery, migration, and consistency verification.

    `WorkspaceRepository.open` is itself one of the measurements, and every other benchmark
    needs a handle; paying for verification again inside each of them would measure the same
    thing many times over. This composes the same public pieces `open` composes, minus the
    checks it is timed for.
    """
    layout = WorkspaceLayout(root)
    config = read_yaml(layout.research_file, WorkspaceConfig)
    return WorkspaceRepository(layout, config)


# --- individual benchmarks --------------------------------------------------


def _measure_open(root: Path, corpus: GenerationReport) -> list[Measurement]:
    """Both opens a researcher actually gets: the full check, and the cached one.

    `WorkspaceRepository.open` verifies the event log against canonical state, and that
    check is the whole cost. It runs in full whenever anything under the workspace moved
    since the last successful one, and is skipped when `.research/consistency-check.json`
    proves every canonical file and the event log byte-identical to what that check ran
    against — so the two numbers below are the two answers, not a best and a worst case.
    """
    clear_consistency_marker(WorkspaceLayout(root))
    runs = CHEAP_REPEATS if corpus.evidence <= 600 else 1
    cold, full = _repeat_open(partial(WorkspaceRepository.open, root, verify="full"), runs)
    warm, cached = _repeat_open(partial(WorkspaceRepository.open, root), CHEAP_REPEATS)
    return [
        Measurement(
            group="project open",
            name="WorkspaceRepository.open (full verification)",
            seconds=statistics.median(cold),
            runs=runs,
            note=(
                f"consistency: {full.consistency.summary()}; page cache is warm "
                "(dropping it needs root)"
            ),
            detail={"samples_s": cold, "consistent": full.consistency.consistent},
        ),
        Measurement(
            group="project open",
            name="WorkspaceRepository.open (verification cached)",
            seconds=statistics.median(warm),
            runs=CHEAP_REPEATS,
            note=f"consistency: {cached.consistency.summary()}",
            detail={"samples_s": warm, "skipped": cached.consistency.skipped},
        ),
    ]


def _repeat_open(
    opener: Callable[[], WorkspaceRepository], runs: int
) -> tuple[list[float], WorkspaceRepository]:
    """Time ``runs`` opens and keep the last repository, so nothing is opened twice."""
    samples: list[float] = []
    repo: WorkspaceRepository | None = None
    for _ in range(max(1, runs)):
        elapsed, repo = _time_once(opener)
        samples.append(elapsed)
    if repo is None:  # pragma: no cover - the loop above runs at least once
        raise RuntimeError("no open was timed")
    return samples, repo


def _measure_rebuild(
    repo: WorkspaceRepository, *, profile: bool
) -> tuple[list[Measurement], list[str]]:
    """Rebuild over an existing projection, then after deleting `.research/` entirely."""
    warm, report = _time_once(lambda: rebuild_workspace(repo))
    research_dir = repo.layout.research_dir
    shutil.rmtree(research_dir, ignore_errors=True)
    cold, cold_report = _time_once(lambda: rebuild_workspace(repo))
    rows = _profile_rows(lambda: rebuild_workspace(repo)) if profile else []
    return (
        [
            Measurement(
                group="rebuild",
                name="rebuild_workspace (existing .research/)",
                seconds=warm,
                note=report.summary(),
                detail={"objects_by_type": report.objects_by_type, "fts_rows": report.fts_rows},
            ),
            Measurement(
                group="rebuild",
                name="rebuild_workspace (after rm -rf .research/)",
                seconds=cold,
                note=cold_report.summary(),
                detail={
                    "objects": cold_report.objects,
                    "stale_marks": cold_report.stale_marks,
                    "canonical_digest": cold_report.canonical_digest,
                },
            ),
        ],
        rows,
    )


def _measure_fts(database: Path) -> list[Measurement]:
    """Twenty exact-term, phrase, prefix, and boolean queries through `search_fts`."""
    engine = create_engine_for(database)
    try:
        samples: list[float] = []
        hits = 0
        for query in FTS_QUERIES:
            durations = _time_repeated(partial(search_fts, engine, query, limit=20), CHEAP_REPEATS)
            samples.append(statistics.median(durations) * 1000.0)
            hits += len(search_fts(engine, query, limit=20))
    finally:
        engine.dispose()
    return [
        _latency_measurement(
            "fts",
            "search_fts (20 queries)",
            samples,
            note=f"{hits} hits over {len(FTS_QUERIES)} queries, median of {CHEAP_REPEATS} each",
            queries=list(FTS_QUERIES),
            hits=hits,
        )
    ]


def _candidate(work: WorkId, index: int, blocks: Sequence[Any], document: Any) -> EvidenceCandidate:
    """One staged candidate anchored in a real block of ``work``."""
    block = blocks[index % len(blocks)]
    end = min(len(block.text), 160)
    anchor = build_anchor(document, block, 0, end)
    evidence = Evidence(
        id=EvidenceId.make(0),
        source=anchor,
        content=EvidenceContent(exact_text=block.text[:end], field="method_summary"),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.METHOD_DESCRIPTION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        provenance=Provenance.model("vendor-a/model-x"),
    )
    return EvidenceCandidate(
        candidate_id=candidate_id_for(work, block.id, "method_summary", index),
        work=work,
        artifact=block.artifact,
        field="method_summary",
        evidence=evidence,
        extraction=ExtractionProvenance(
            run_id=f"run-{index // 500:04d}",
            provider="vendor-a",
            model="model-x",
            template_version="1",
            request_fingerprint=f"sha256:{index:064x}",
            response_schema_fingerprint=f"sha256:{index + 1:064x}",
            rationale="synthetic candidate for benchmarking the review inbox",
        ),
        status=CandidateStatus.PROPOSED,
    )


def _stage_candidates(
    repo: WorkspaceRepository, staging: StagingStore, *, count: int
) -> tuple[int, float]:
    """Write ``count`` candidates across the corpus; returns what was staged and how long."""
    works = [work.id for work in repo.list_works()]
    if not works:
        return 0, 0.0
    documents = stored_documents(repo, works[: max(1, min(len(works), count // 25 + 1))])
    by_work: dict[WorkId, list[Any]] = {}
    for document in documents.values():
        by_work.setdefault(document.work, []).extend(document.blocks)
    if not by_work:
        return 0, 0.0
    ordered = sorted(by_work)
    started = time.perf_counter()
    staged = 0
    for index in range(count):
        work = ordered[index % len(ordered)]
        document = next(doc for doc in documents.values() if doc.work == work)
        staging.put(_candidate(work, index, by_work[work], document))
        staged += 1
    return staged, time.perf_counter() - started


def _measure_inbox(
    repo: WorkspaceRepository, *, candidates: int, profile: bool
) -> tuple[list[Measurement], list[str]]:
    """Stage candidates, then time the Review Inbox the researcher actually opens."""
    staging = StagingStore(repo.layout.research_dir)
    staged, stage_seconds = _stage_candidates(repo, staging, count=candidates)
    list_seconds, listed = _time_once(staging.list)
    inbox_seconds, queue = _time_once(lambda: build_inbox(staging, repo))
    rows = _profile_rows(lambda: build_inbox(staging, repo)) if profile else []
    return (
        [
            Measurement(
                group="review inbox",
                name="StagingStore.put (staging setup)",
                seconds=stage_seconds,
                note=f"{staged:,} candidates written; setup, not a researcher-facing path",
            ),
            Measurement(
                group="review inbox",
                name="StagingStore.list",
                seconds=list_seconds,
                note=f"{len(listed):,} candidates read back",
            ),
            Measurement(
                group="review inbox",
                name="build_inbox",
                seconds=inbox_seconds,
                note=f"{len(queue):,} queue items, {len(queue.counts)} categories",
                detail={
                    "counts": {key.value: value for key, value in queue.counts.items()},
                    "candidates": staged,
                },
            ),
        ],
        rows,
    )


def _measure_claim_graph(repo: WorkspaceRepository) -> list[Measurement]:
    """Dependency graph build, invalidation from a hub, strength audit, and independence."""
    works = repo.list_works()
    claims = repo.list_claims()
    decisions = repo.list_decisions()
    evidence: dict[EvidenceId, Evidence] = {}
    for work in works:
        for record in repo.iter_evidence(work.id):
            evidence[record.id] = record

    objects: list[object] = [*works, *claims, *decisions, *evidence.values()]
    objects.extend(repo.list_matrices())
    objects.extend(repo.list_taxonomies())
    objects.extend(repo.list_questions())
    objects.extend(repo.iter_anchors())

    build_seconds, graph = _time_once(lambda: DependencyGraph.from_objects(objects))
    hub = str(decisions[0].id) if decisions else str(claims[0].id)
    hub_samples = _time_repeated(lambda: mark_changed(graph, hub), CHEAP_REPEATS)
    stale = mark_changed(graph, hub)

    audited = list(claims[:STRENGTH_CLAIMS])
    strength_seconds, _ = _time_once(
        lambda: [assess_strength(StrengthInput.from_claim(claim, evidence)) for claim in audited]
    )

    citation_graph = _synthetic_citation_graph(works)
    work_map = {work.id: work for work in works}
    independence_claims = list(claims[:INDEPENDENCE_CLAIMS])
    independence_seconds, _ = _time_once(
        lambda: [
            independent_support(claim, evidence, work_map, citation_graph)
            for claim in independence_claims
        ]
    )
    return [
        Measurement(
            group="claim graph",
            name="DependencyGraph.from_objects",
            seconds=build_seconds,
            note=(
                f"{len(objects):,} objects, {len(graph.edges()):,} edges, "
                f"{len(graph.nodes()):,} nodes"
            ),
        ),
        Measurement(
            group="claim graph",
            name="mark_changed (hub decision)",
            seconds=statistics.median(hub_samples),
            runs=len(hub_samples),
            note=f"{len(stale):,} objects marked stale from {hub}",
        ),
        Measurement(
            group="claim graph",
            name=f"assess_strength x{len(audited)}",
            seconds=strength_seconds,
            note=(
                f"{strength_seconds / max(1, len(audited)) * 1000:.2f} ms per claim over "
                f"{len(evidence):,} accepted evidence records"
            ),
        ),
        Measurement(
            group="claim graph",
            name=f"independent_support x{len(independence_claims)}",
            seconds=independence_seconds,
            note=(
                f"{independence_seconds / max(1, len(independence_claims)) * 1000:.2f} ms per "
                f"claim against a {len(citation_graph.edges()):,}-edge citation graph"
            ),
        ),
    ]


def _synthetic_citation_graph(works: Sequence[Work]) -> CitationGraph:
    """A deterministic `cites` graph over the corpus: each work cites four earlier ones."""
    graph = CitationGraph()
    ids = [str(work.id) for work in works]
    for position, citing in enumerate(ids):
        for step in (1, 3, 7, 13):
            if position - step >= 0:
                graph.add_edge(
                    CitationEdge(citing=citing, cited=ids[position - step], source="benchmark")
                )
    return graph


def _measure_semantic(
    repo: WorkspaceRepository, *, dimension: int
) -> tuple[list[Measurement], SemanticIndex]:
    """Rebuild the vector index over every block unit, then time twenty queries."""
    provider = HashingEmbeddingProvider(dimension)
    index = SemanticIndex.open(repo.layout.index_dir, provider)
    units = []
    documents = stored_documents(repo, [work.id for work in repo.list_works()])
    for document in documents.values():
        units.extend(units_from_document(document))
    for work in repo.list_works():
        for record in repo.iter_evidence(work.id):
            units.extend(units_from_evidence(record))
    build_seconds, embedded = _time_once(lambda: index.rebuild(units))
    samples = [
        statistics.median(_time_repeated(partial(index.query, query, k=10), CHEAP_REPEATS)) * 1000.0
        for query in SEMANTIC_QUERIES[:SEMANTIC_QUERY_COUNT]
    ]
    return (
        [
            Measurement(
                group="vector index",
                name="SemanticIndex.rebuild",
                seconds=build_seconds,
                note=(
                    f"{embedded:,} units embedded at dimension {dimension} with "
                    "HashingEmbeddingProvider (in-process, no network)"
                ),
                detail={"units": embedded, "dimension": dimension},
            ),
            _latency_measurement(
                "vector index",
                "SemanticIndex.query (20 queries)",
                samples,
                note=f"median of {CHEAP_REPEATS} runs per query, k=10",
            ),
        ],
        index,
    )


def _measure_retrieval(
    repo: WorkspaceRepository, database: Path, index: SemanticIndex
) -> list[Measurement]:
    """Ten mixed queries through the full authority-ladder walk."""
    engine = create_engine_for(database)
    try:
        service = RetrievalService(engine, repo, semantic=index)
        samples = [
            statistics.median(_time_repeated(partial(service.search, query, k=10), CHEAP_REPEATS))
            * 1000.0
            for query in RETRIEVAL_QUERIES[:RETRIEVAL_QUERY_COUNT]
        ]
        total = sum(len(service.search(query, k=10).hits) for query in RETRIEVAL_QUERIES)
    finally:
        engine.dispose()
    return [
        _latency_measurement(
            "retrieval",
            "RetrievalService.search (10 queries)",
            samples,
            note=f"{total} hits over {len(RETRIEVAL_QUERIES)} mixed queries, k=10",
        )
    ]


def _stale_marks_measurement(database: Path) -> Measurement:
    engine = create_engine_for(database)
    try:
        with engine.connect() as connection:
            elapsed, marks = _time_once(lambda: load_stale_marks(connection))
    finally:
        engine.dispose()
    return Measurement(
        group="claim graph",
        name="load_stale_marks",
        seconds=elapsed,
        note=f"{len(marks):,} marks read from the projection",
    )


# --- orchestration ----------------------------------------------------------


def run_benchmarks(
    root: Path,
    *,
    scale: float = 1.0,
    seed: int = 7,
    candidates: int = DEFAULT_CANDIDATES,
    dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    reuse: bool = False,
    profile: bool = False,
) -> BenchmarkResults:
    """Generate (or reuse) a corpus at ``scale`` and run every benchmark against it."""
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    target = Path(root)
    if reuse and (target / "research.yaml").is_file():
        corpus = _reused_corpus_report(target, scale=scale, seed=seed)
        generation = Measurement(
            group="generation",
            name="generate_workspace",
            seconds=None,
            note="reused an existing workspace; generation was not timed",
        )
    else:
        if target.exists():
            shutil.rmtree(target)
        corpus = generate_workspace(target, scale=scale, seed=seed)
        generation = Measurement(
            group="generation",
            name="generate_workspace",
            seconds=corpus.duration_s,
            note=(
                f"{corpus.summary()}; {corpus.works_per_transaction} works and "
                f"{corpus.claims_per_transaction} claims per journalled transaction"
            ),
            detail=corpus.as_dict(),
        )

    measurements: list[Measurement] = [generation]
    profiles: dict[str, list[str]] = {}

    measurements.extend(_measure_open(target, corpus))
    if profile:
        profiles["WorkspaceRepository.open"] = _profile_rows(
            lambda: WorkspaceRepository.open(target, verify="full")
        )

    repo = open_unverified(target)
    rebuild_measurements, rebuild_profile = _measure_rebuild(repo, profile=profile)
    measurements.extend(rebuild_measurements)
    if rebuild_profile:
        profiles["rebuild_workspace"] = rebuild_profile

    database = repo.layout.database_file
    measurements.extend(_measure_fts(database))

    inbox_measurements, inbox_profile = _measure_inbox(repo, candidates=candidates, profile=profile)
    measurements.extend(inbox_measurements)
    if inbox_profile:
        profiles["build_inbox"] = inbox_profile

    measurements.extend(_measure_claim_graph(repo))
    measurements.append(_stale_marks_measurement(database))

    semantic_measurements, index = _measure_semantic(repo, dimension=dimension)
    measurements.extend(semantic_measurements)
    measurements.extend(_measure_retrieval(repo, database, index))

    sizes = {
        "canonical_tree_bytes": corpus.canonical_bytes,
        "event_log_bytes": corpus.event_log_bytes,
        "research_db_bytes": database.stat().st_size if database.is_file() else 0,
        "index_dir_bytes": _tree_bytes(repo.layout.index_dir),
        "staging_dir_bytes": _tree_bytes(repo.layout.staging_dir),
        "research_dir_bytes": _tree_bytes(repo.layout.research_dir),
    }
    return BenchmarkResults(
        machine=machine_info(),
        corpus=corpus.as_dict(),
        measurements=measurements,
        sizes=sizes,
        peak_rss_bytes=_peak_rss_bytes(),
        profiles=profiles,
        scale=scale,
        started_at=started_at,
    )


def _reused_corpus_report(root: Path, *, scale: float, seed: int) -> GenerationReport:
    """Describe a workspace this run did not build, by counting what is on disk."""
    repo = open_unverified(root)
    layout = repo.layout
    works = repo.list_works()
    blocks = sum(
        sum(1 for _ in path.open(encoding="utf-8"))
        for path in layout.works_dir.glob("*/parsed/*.blocks.jsonl")
    )
    evidence = sum(len(list(repo.iter_evidence(work.id))) for work in works)
    claims = repo.list_claims()
    events_file = layout.events_file
    return GenerationReport(
        root=str(root),
        seed=seed,
        scale=scale,
        works=len(works),
        versions=sum(len(repo.list_versions(work.id)) for work in works),
        artifacts=sum(len(repo.list_artifacts(work.id)) for work in works),
        blocks=blocks,
        evidence=evidence,
        claims=len(claims),
        claim_relations=sum(len(claim.relations) for claim in claims),
        decisions=len(repo.list_decisions()),
        taxonomies=len(repo.list_taxonomies()),
        matrices=len(repo.list_matrices()),
        matrix_cells=sum(len(matrix.cells) for matrix in repo.list_matrices()),
        questions=len(repo.list_questions()),
        search_runs=len(repo.list_search_runs()),
        manuscript_anchors=len(list(repo.iter_anchors())),
        events=sum(1 for _ in repo.iter_events()),
        transactions=0,
        works_per_transaction=0,
        claims_per_transaction=0,
        duration_s=0.0,
        canonical_bytes=sum(
            path.stat().st_size
            for path in root.rglob("*")
            if path.is_file() and ".research" not in path.parts
        ),
        event_log_bytes=events_file.stat().st_size if events_file.is_file() else 0,
    )


def _write_outputs(
    results: BenchmarkResults, *, json_path: Path | None, md_path: Path | None
) -> None:
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(results.as_dict(), indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
    if md_path is not None:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(results.markdown(), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; writes JSON and Markdown and prints the table."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, required=True, help="workspace directory to use")
    parser.add_argument("--scale", type=float, default=None, help="fraction of the target corpus")
    parser.add_argument(
        "--quick",
        action="store_true",
        help=(f"iteration profile: scale {QUICK_SCALE} and {QUICK_CANDIDATES} inbox candidates"),
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", type=Path, default=None, dest="json_path")
    parser.add_argument("--markdown", type=Path, default=None, dest="md_path")
    parser.add_argument("--candidates", type=int, default=None)
    parser.add_argument("--dimension", type=int, default=DEFAULT_EMBEDDING_DIMENSION)
    parser.add_argument("--reuse", action="store_true", help="do not regenerate an existing root")
    parser.add_argument("--profile", action="store_true", help="cProfile rebuild, inbox, and open")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    default_scale = QUICK_SCALE if args.quick else 1.0
    default_candidates = QUICK_CANDIDATES if args.quick else DEFAULT_CANDIDATES

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s"
    )
    results = run_benchmarks(
        args.root,
        scale=default_scale if args.scale is None else args.scale,
        seed=args.seed,
        candidates=default_candidates if args.candidates is None else args.candidates,
        dimension=args.dimension,
        reuse=args.reuse,
        profile=args.profile,
    )
    _write_outputs(results, json_path=args.json_path, md_path=args.md_path)
    print(results.markdown())
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())

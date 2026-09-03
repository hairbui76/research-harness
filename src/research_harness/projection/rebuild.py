"""Deterministic rebuild of the whole projection from canonical files (ROADMAP Task 3.2).

`.research/` is regenerable machine state, so deleting it and running ``research rebuild``
must reconstruct the index without changing a single accepted conclusion (PRODUCT 8.2,
§42 C, ADR-001, ADR-006). Three properties make that true here:

**Read-only.** Nothing in this module opens a canonical file for writing, and it never
takes a :meth:`~research_harness.workspace.repository.WorkspaceRepository.transaction`.
Rebuilding is a read of canonical state and a write of the projection, never the reverse.

**Fail closed.** Every canonical object is read and validated *before* the database is
touched. One unparseable file means the whole rebuild reports
:class:`InvalidFile` and leaves the existing projection exactly as it was, because a
projection that silently omits a corrupted Claim is worse than no projection at all.

**Atomic.** The new projection is built in ``research.db.rebuild-<pid>`` beside the target
and moved over it with :func:`os.replace`, so a crash mid-rebuild leaves the previous
projection intact rather than a half-written database.

Determinism: rows are inserted in containment order from a sorted file walk, dependency
edges come from :meth:`DependencyGraph.from_objects`, and stale marks are recomputed from
canonical timestamps rather than from anything stored under `.research/`, so two rebuilds
of an unchanged workspace produce identical tables (see :func:`dump_projection`) and an
identical :func:`canonical_digest`.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Connection, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError

from research_harness.domain import (
    Artifact,
    Claim,
    Decision,
    DocumentBlock,
    Evidence,
    ManuscriptAnchor,
    ResearchEvent,
    ResearchNote,
    ResearchQuestion,
    SearchRun,
    StaleState,
    SynthesisMatrix,
    Taxonomy,
    Version,
    Work,
    WorkId,
)
from research_harness.domain.base import Sha256, utc_now
from research_harness.domain.errors import ResearchHarnessError
from research_harness.projection.dependencies import (
    DependencyGraph,
    StaleMark,
    StaleSet,
    mark_changed_many,
    persist_stale_marks,
    priority_for,
)
from research_harness.projection.fts import FTS_VERSION, build_fts
from research_harness.projection.rows import (
    RowSpec,
    event_id,
    manuscript_anchor_key,
    matrix_cell_node_id,
    node_id_for,
    note_key,
    rows_for,
    upsert_rows,
)
from research_harness.projection.schema import (
    ARTIFACTS,
    BLOCKS,
    CLAIMS,
    DECISIONS,
    EVENTS,
    EVIDENCE,
    MANUSCRIPT_ANCHORS,
    MATRICES,
    METADATA,
    NOTES,
    PROJECTION_META,
    PROJECTION_META_ID,
    PROJECTION_SCHEMA_VERSION,
    QUESTIONS,
    SEARCH_RUNS,
    TAXONOMIES,
    VERSIONS,
    WORKS,
    create_all,
    create_engine_for,
)
from research_harness.workspace.events import (
    content_digest,
    file_digest,
    iter_canonical_entries,
    iter_canonical_files,
)
from research_harness.workspace.layout import BLOCKS_SUFFIX, WORK_FILENAME, WorkspaceLayout
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.serialization import iter_jsonl, read_yaml

__all__ = [
    "CANONICAL_STALE_REASON",
    "OBJECT_TYPES",
    "UPSTREAM_UPDATED_REASON",
    "InvalidFile",
    "RebuildReport",
    "canonical_digest",
    "dump_projection",
    "iter_canonical_files",
    "rebuild_workspace",
    "verify_rebuild",
]

logger = logging.getLogger(__name__)

OBJECT_TYPES: tuple[str, ...] = (
    "Work",
    "Version",
    "Artifact",
    "DocumentBlock",
    "Evidence",
    "Claim",
    "Decision",
    "ResearchQuestion",
    "Taxonomy",
    "SearchRun",
    "SynthesisMatrix",
    "ResearchNote",
    "ManuscriptAnchor",
    "ResearchEvent",
)
"""Every canonical type a rebuild reads, in containment order; the keys of the report."""

CANONICAL_STALE_REASON = "canonical stale flag"
"""Reason recorded for an object whose own canonical ``stale`` field says ``stale``."""

UPSTREAM_UPDATED_REASON = "upstream updated after object"
"""Reason recorded when a dependency's ``updated_at`` is newer than the downstream object."""

REBUILD_SUFFIX = ".rebuild-"
"""Temporary database name: ``research.db.rebuild-<pid>``, beside the real one."""

SIDECAR_SUFFIXES: tuple[str, ...] = ("-wal", "-shm")
MAX_ERROR_CHARS = 240


@dataclass(frozen=True, slots=True)
class InvalidFile:
    """One canonical file that could not be read, and why."""

    path: str
    """Workspace-relative POSIX path, so the message points at a file a human can open."""

    error: str


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """What one rebuild read, wrote, and refused."""

    objects_by_type: dict[str, int]
    invalid_files: tuple[InvalidFile, ...]
    stale_marks: int
    canonical_digest: Sha256
    fts_rows: int
    duration_ms: int
    ok: bool
    graph_nodes: int = 0
    graph_edges: int = 0
    """Rows the ResearchGraph projection wrote alongside this rebuild; 0 when it was skipped."""

    @property
    def objects(self) -> int:
        """Total canonical objects projected."""
        return sum(self.objects_by_type.values())

    def summary(self) -> str:
        """One line for a terminal or a log."""
        if not self.ok:
            return (
                f"rebuild refused: {len(self.invalid_files)} invalid canonical file(s); "
                "the existing projection was left untouched"
            )
        graph = (
            f", graph {self.graph_nodes} nodes / {self.graph_edges} edges"
            if self.graph_nodes or self.graph_edges
            else ""
        )
        return (
            f"rebuilt {self.objects} objects, {self.fts_rows} indexed rows, "
            f"{self.stale_marks} stale marks{graph} in {self.duration_ms} ms"
        )


class _RebuildRefusedError(Exception):
    """Internal: a canonical file was refused by the database, so the rebuild stops."""

    def __init__(self, invalid: InvalidFile) -> None:
        self.invalid = invalid
        super().__init__(f"{invalid.path}: {invalid.error}")


class _UnattributedRefusalError(Exception):
    """Internal: a batched write was refused and no single file can yet be blamed."""


# --- reading canonical state ------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Record:
    """One canonical object and the workspace-relative file it was read from."""

    path: str
    obj: object


class _CanonicalScan:
    """Every canonical object of one workspace, with per-file error attribution.

    Reading happens before anything is written, and one bad file never hides the next: the
    scan collects them all so a researcher fixes the workspace once rather than once per
    rebuild.
    """

    def __init__(self, layout: WorkspaceLayout) -> None:
        self._layout = layout
        self.records: list[_Record] = []
        self.counts: dict[str, int] = dict.fromkeys(OBJECT_TYPES, 0)
        self.invalid: list[InvalidFile] = []

    def yaml_file[T: BaseModel](self, path: Path, model_type: type[T]) -> None:
        """Read one canonical YAML object, recording an :class:`InvalidFile` on failure."""
        if not path.is_file():
            return
        try:
            obj = read_yaml(path, model_type)
        except (ResearchHarnessError, OSError, ValueError) as error:
            self.reject(path, error)
            return
        self._keep(self._relative(path), obj)

    def jsonl_file[T: BaseModel](
        self, path: Path, model_type: type[T], *, key: Callable[[T], str] | None = None
    ) -> None:
        """Read one append-only collection; ``key`` collapses it to the newest per record."""
        if not path.is_file():
            return
        try:
            records = list(iter_jsonl(path, model_type))
        except (ResearchHarnessError, OSError, ValueError) as error:
            self.reject(path, error)
            return
        if key is not None:
            records = _latest_by(records, key)
        relative = self._relative(path)
        for record in records:
            self._keep(relative, record)

    def reject(self, path: Path, error: Exception) -> None:
        """Record that ``path`` cannot be read; the rebuild will refuse to touch the db."""
        self.invalid.append(InvalidFile(path=self._relative(path), error=_reason(error)))

    def _keep(self, relative: str, obj: BaseModel) -> None:
        self.records.append(_Record(relative, obj))
        name = type(obj).__name__
        self.counts[name] = self.counts.get(name, 0) + 1

    def _relative(self, path: Path) -> str:
        try:
            return str(self._layout.relative(path))
        except ResearchHarnessError:  # pragma: no cover - every path here is inside the root
            return str(path)


def _scan_workspace(layout: WorkspaceLayout) -> _CanonicalScan:
    """Read every canonical object in containment order: Works first, events last."""
    scan = _CanonicalScan(layout)
    for work_file in sorted(layout.works_dir.glob(f"*/{WORK_FILENAME}")):
        work = _work_id(work_file)
        if work is None:
            scan.reject(work_file, ValueError(f"{work_file.parent.name!r} is not a Work id"))
            continue
        scan.yaml_file(work_file, Work)
        for path in sorted(layout.versions_dir(work).glob("*.yaml")):
            scan.yaml_file(path, Version)
        for path in sorted(layout.artifacts_dir(work).glob("*.yaml")):
            scan.yaml_file(path, Artifact)
        for path in sorted(layout.parsed_dir(work).glob(f"*{BLOCKS_SUFFIX}")):
            scan.jsonl_file(path, DocumentBlock)
        scan.jsonl_file(layout.evidence_file(work), Evidence, key=lambda record: str(record.id))
    for path in sorted(layout.claims_dir.glob("*.yaml")):
        scan.yaml_file(path, Claim)
    for path in sorted(layout.decisions_dir.glob("*.yaml")):
        scan.yaml_file(path, Decision)
    for path in sorted(layout.questions_dir.glob("*.yaml")):
        scan.yaml_file(path, ResearchQuestion)
    for path in sorted(layout.taxonomy_dir.glob("*.yaml")):
        scan.yaml_file(path, Taxonomy)
    for path in sorted(layout.searches_dir.glob("*.yaml")):
        scan.yaml_file(path, SearchRun)
    for path in sorted(layout.matrices_dir.glob("*.yaml")):
        scan.yaml_file(path, SynthesisMatrix)
    for path in sorted(layout.notes_dir.glob("*.yaml")):
        scan.yaml_file(path, ResearchNote)
    scan.jsonl_file(layout.anchors_file, ManuscriptAnchor, key=_anchor_key)
    scan.jsonl_file(layout.events_file, ResearchEvent)
    return scan


def _work_id(work_file: Path) -> WorkId | None:
    try:
        return WorkId(work_file.parent.name)
    except ResearchHarnessError:
        return None


def _anchor_key(anchor: ManuscriptAnchor) -> str:
    return manuscript_anchor_key(anchor.file, anchor.sentence_fingerprint)


def _latest_by[T](records: Sequence[T], key: Callable[[T], str]) -> list[T]:
    """Collapse an append-only stream to the newest record per key, in first-seen order."""
    latest: dict[str, T] = {}
    for record in records:
        latest[key(record)] = record
    return list(latest.values())


def _reason(error: Exception) -> str:
    collapsed = " ".join(str(error).split())
    if len(collapsed) <= MAX_ERROR_CHARS:
        return collapsed
    return f"{collapsed[: MAX_ERROR_CHARS - 1]}…"


# --- the canonical digest ---------------------------------------------------


def canonical_digest(repo: WorkspaceRepository) -> Sha256:
    """Digest of the workspace's canonical state, as recorded in ``projection_meta``.

    Covers ``(relative path, sha256 of the file's bytes)`` for every file
    :func:`~research_harness.workspace.events.iter_canonical_files` yields, sorted by path.

    The bytes, not the objects. Digesting each object's canonical YAML instead meant
    re-serializing all 150,000 records of an append-only collection on every rebuild — 27 s
    of a 67 s rebuild at the ROADMAP corpus size — to buy a property nothing needs here: a
    hand-reformatted YAML file kept the same digest. That property still holds where it
    matters, in `workspace/events.py`, whose per-object digests are what the event log
    records and what :func:`~research_harness.workspace.events.verify_consistency` compares;
    those are unchanged. This digest is a witness that `projection_meta` describes the
    canonical tree it was built from, and the tree is regenerable state's only input, so
    reading it byte for byte is both cheaper and stricter.
    """
    return _canonical_digest(repo.layout)


def _canonical_digest(layout: WorkspaceLayout) -> Sha256:
    entries = [
        f"{relative}\t{file_digest(path)}" for relative, path in iter_canonical_entries(layout)
    ]
    return content_digest("\n".join(sorted(entries)).encode("utf-8"))


# --- staleness recomputed from canonical facts ------------------------------


def _updated_at_by_node(records: Iterable[_Record]) -> dict[str, datetime]:
    """``node id -> updated_at`` for every object that carries one.

    Matrix cells have no object of their own, so they inherit their matrix's timestamp:
    without it a cell could never be compared against the taxonomy Decision above it.
    """
    stamps: dict[str, datetime] = {}
    for record in records:
        moment = getattr(record.obj, "updated_at", None)
        if not isinstance(moment, datetime):
            continue
        stamps[node_id_for(record.obj)] = moment
        if isinstance(record.obj, SynthesisMatrix):
            for cell in record.obj.cells:
                node = matrix_cell_node_id(str(record.obj.id), str(cell.work), cell.field)
                stamps[node] = moment
    return stamps


def _recompute_stale(
    records: Sequence[_Record], graph: DependencyGraph, stamps: Mapping[str, datetime]
) -> StaleSet:
    """Derive the stale set from canonical state alone, so it survives deleting `.research/`.

    Two independent sources, both canonical (ADR-008): an object whose own ``stale`` field
    says so, and an object older than something it depends on. The second walks the
    dependency graph with :func:`mark_changed_many` and then keeps only the marks a
    timestamp actually justifies, so a downstream object that was reviewed *after* its
    upstream changed does not come back stale on every rebuild.
    """
    marks: set[StaleMark] = set()
    for record in records:
        if getattr(record.obj, "stale", None) is not StaleState.STALE:
            continue
        node = node_id_for(record.obj)
        marks.add(
            StaleMark(
                object_id=node,
                reason=CANONICAL_STALE_REASON,
                priority=priority_for(node),
                source_change=node,
            )
        )
    changed = sorted(node for node in graph.nodes() if graph.downstream(node) and node in stamps)
    for mark in mark_changed_many(graph, changed, reason=UPSTREAM_UPDATED_REASON):
        downstream = stamps.get(mark.object_id)
        upstream = stamps.get(mark.source_change)
        if downstream is None or upstream is None or downstream >= upstream:
            continue
        marks.add(mark)
    return StaleSet(marks)


def _persist_stale(
    connection: Connection,
    stale: StaleSet,
    *,
    stamps: Mapping[str, datetime],
    built_at: datetime,
) -> None:
    """Write the stale set, dating each mark by the change that caused it, not by now.

    A wall-clock ``since`` would make two rebuilds of the same workspace differ, and the
    honest answer to "stale since when?" is the upstream object's ``updated_at``.
    """
    grouped: dict[str, list[StaleMark]] = {}
    for mark in stale:
        grouped.setdefault(mark.source_change, []).append(mark)
    for source in sorted(grouped):
        persist_stale_marks(connection, StaleSet(grouped[source]), stamps.get(source, built_at))


# --- building ---------------------------------------------------------------


def rebuild_workspace(
    repo: WorkspaceRepository, *, research_dir: Path | None = None
) -> RebuildReport:
    """Rebuild the whole projection from canonical files; never writes canonical state.

    Reads and validates everything first: if any canonical file is invalid the report comes
    back with ``ok=False`` and the existing ``research.db`` is not opened, let alone
    modified. Otherwise the projection is built in a temporary database beside the target
    and moved into place atomically.
    """
    started = time.perf_counter()
    built_at = utc_now()
    layout = repo.layout
    scan = _scan_workspace(layout)
    digest = _canonical_digest(layout)
    stale_marks = 0
    fts_rows = 0
    graph_nodes = 0
    graph_edges = 0
    if not scan.invalid:
        directory = layout.research_dir if research_dir is None else Path(research_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / layout.database_file.name
        temporary = target.with_name(f"{target.name}{REBUILD_SUFFIX}{os.getpid()}")
        _remove_database(temporary)
        try:
            stale_marks, fts_rows = _build_database(
                temporary, scan, digest=digest, built_at=built_at
            )
        except _RebuildRefusedError as failure:
            logger.warning("rebuild refused: %s", failure)
            scan.invalid.append(failure.invalid)
        else:
            _replace_database(temporary, target)
            graph_nodes, graph_edges = _rebuild_graph(repo, directory)
        finally:
            _remove_database(temporary)
    return RebuildReport(
        objects_by_type=dict(scan.counts),
        invalid_files=tuple(scan.invalid),
        stale_marks=stale_marks,
        canonical_digest=digest,
        fts_rows=fts_rows,
        duration_ms=int((time.perf_counter() - started) * 1000),
        ok=not scan.invalid,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


def _rebuild_graph(repo: WorkspaceRepository, directory: Path) -> tuple[int, int]:
    """Rebuild the ResearchGraph beside the projection; returns ``(nodes, edges)``.

    Imported here rather than at module scope because `graph/` reads this module's
    `canonical_digest`. A graph failure is logged and reported as zero rows rather than
    failing the rebuild: the graph is a navigation index, and a workspace whose canonical
    files projected cleanly is not broken because its adjacency tables are missing
    (ADR-006; graph spec §8 keeps direct canonical reads available).
    """
    from research_harness.graph.rebuild import rebuild_graph

    try:
        report = rebuild_graph(repo, research_dir=directory)
    except (ResearchHarnessError, DatabaseError, OSError) as error:
        logger.warning("the research graph was not rebuilt: %s", _reason(error))
        return 0, 0
    return report.nodes, report.edges


def _build_database(
    path: Path, scan: _CanonicalScan, *, digest: str, built_at: datetime
) -> tuple[int, int]:
    """Build a complete projection at ``path``; returns ``(stale marks, indexed rows)``.

    The rows of every record are written as one stream so that
    :func:`~research_harness.projection.rows.upsert_rows` can batch the long runs a sorted
    canonical walk produces; a refusal is then attributed by rebuilding once more one
    record at a time, which costs nothing on the path that succeeds and gives the
    researcher the same "which file" answer on the path that does not.
    """
    try:
        return _write_database(path, scan, digest=digest, built_at=built_at, batched=True)
    except _UnattributedRefusalError:
        logger.debug("a batched projection write was refused; rebuilding to name the file")
        _remove_database(path)
        return _write_database(path, scan, digest=digest, built_at=built_at, batched=False)


def _write_database(
    path: Path, scan: _CanonicalScan, *, digest: str, built_at: datetime, batched: bool
) -> tuple[int, int]:
    engine = create_engine_for(path)
    try:
        create_all(engine)
        graph = DependencyGraph.from_objects(record.obj for record in scan.records)
        stamps = _updated_at_by_node(scan.records)
        stale = _recompute_stale(scan.records, graph, stamps)
        with engine.begin() as connection:
            _write_records(connection, scan.records, batched=batched)
            upsert_rows(connection, graph.rows())
            _persist_stale(connection, stale, stamps=stamps, built_at=built_at)
        fts_rows = build_fts(engine)
        with engine.begin() as connection:
            upsert_rows(connection, [_meta_row(digest=digest, built_at=built_at)])
        _checkpoint(engine)
    finally:
        engine.dispose()
    return len(stale), fts_rows


def _write_records(connection: Connection, records: Sequence[_Record], *, batched: bool) -> None:
    """Project every record, batched for speed or one at a time to attribute a refusal."""
    if batched:
        try:
            upsert_rows(connection, (row for record in records for row in rows_for(record.obj)))
        except DatabaseError as error:
            raise _UnattributedRefusalError(_reason(error)) from error
        return
    for record in records:
        try:
            upsert_rows(connection, rows_for(record.obj))
        except DatabaseError as error:
            raise _RebuildRefusedError(InvalidFile(record.path, _reason(error))) from error


def _meta_row(*, digest: str, built_at: datetime) -> RowSpec:
    return RowSpec(
        PROJECTION_META.name,
        {
            "id": PROJECTION_META_ID,
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "built_at": built_at.isoformat(),
            "canonical_digest": digest,
            "fts_version": FTS_VERSION,
        },
    )


def _checkpoint(engine: Engine) -> None:
    """Fold the write-ahead log back into the database file before it is moved."""
    with engine.connect() as connection:
        connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        connection.rollback()


def _replace_database(temporary: Path, target: Path) -> None:
    """Swap the finished projection in atomically, then drop the old journal files.

    Until the replace lands, a crash leaves the previous projection whole. Afterwards the
    previous database's `-wal`/`-shm` files no longer describe the file they sit beside, so
    they are removed; a crash in that window is repaired by running the rebuild again,
    which is always safe because nothing here is authoritative (ADR-001).
    """
    os.replace(temporary, target)
    for suffix in SIDECAR_SUFFIXES:
        Path(f"{target}{suffix}").unlink(missing_ok=True)


def _remove_database(path: Path) -> None:
    path.unlink(missing_ok=True)
    for suffix in SIDECAR_SUFFIXES:
        Path(f"{path}{suffix}").unlink(missing_ok=True)


# --- verification -----------------------------------------------------------


def verify_rebuild(repo: WorkspaceRepository, engine: Engine) -> list[str]:
    """Discrepancies between canonical objects and projection rows; empty when they agree.

    Compares the id set of every canonical collection with the primary keys the projection
    holds for it, in both directions: a canonical object missing from the projection means
    the index is stale, and a projected id with no canonical object means the projection
    kept something the workspace no longer says (which would make it an authority - the one
    thing a projection may never be).
    """
    issues: list[str] = []
    with engine.connect() as connection:
        for label, canonical, column in _identity_checks(repo):
            projected = {str(value) for value in connection.execute(select(column)).scalars()}
            issues.extend(_difference(label, canonical, projected))
        stored = connection.execute(select(PROJECTION_META.c.schema_version)).scalars().first()
    if stored is None:
        issues.append("projection_meta: no row; this database was not built by a rebuild")
    elif int(stored) != PROJECTION_SCHEMA_VERSION:
        issues.append(
            f"projection_meta: schema version {stored} != {PROJECTION_SCHEMA_VERSION}; "
            "the projection must be rebuilt"
        )
    return issues


def _identity_checks(repo: WorkspaceRepository) -> list[tuple[str, set[str], Any]]:
    works = repo.list_works()
    versions = {str(version.id) for work in works for version in repo.list_versions(work.id)}
    artifacts = [artifact for work in works for artifact in repo.list_artifacts(work.id)]
    blocks = {
        str(block.id)
        for artifact in artifacts
        for block in repo.iter_blocks(artifact.id, work=artifact.work)
    }
    evidence = {str(record.id) for work in works for record in repo.iter_evidence(work.id)}
    return [
        ("works", {str(work.id) for work in works}, WORKS.c.id),
        ("versions", versions, VERSIONS.c.id),
        ("artifacts", {str(artifact.id) for artifact in artifacts}, ARTIFACTS.c.id),
        ("blocks", blocks, BLOCKS.c.id),
        ("evidence", evidence, EVIDENCE.c.id),
        ("claims", {str(claim.id) for claim in repo.list_claims()}, CLAIMS.c.id),
        ("decisions", {str(item.id) for item in repo.list_decisions()}, DECISIONS.c.id),
        ("questions", {str(item.id) for item in repo.list_questions()}, QUESTIONS.c.id),
        ("taxonomies", {item.name for item in repo.list_taxonomies()}, TAXONOMIES.c.name),
        ("search_runs", {str(item.id) for item in repo.list_search_runs()}, SEARCH_RUNS.c.id),
        ("matrices", {str(item.id) for item in repo.list_matrices()}, MATRICES.c.id),
        ("notes", {note_key(note) for note in repo.iter_notes()}, NOTES.c.note_key),
        (
            "manuscript_anchors",
            {_anchor_key(anchor) for anchor in repo.iter_anchors()},
            MANUSCRIPT_ANCHORS.c.anchor_id,
        ),
        ("events", {event_id(event) for event in repo.iter_events()}, EVENTS.c.event_id),
    ]


def _difference(label: str, canonical: set[str], projected: set[str]) -> list[str]:
    issues = []
    missing = sorted(canonical - projected)
    extra = sorted(projected - canonical)
    if missing:
        issues.append(f"{label}: {len(missing)} canonical object(s) not projected: {_few(missing)}")
    if extra:
        issues.append(
            f"{label}: {len(extra)} projected id(s) with no canonical object: {_few(extra)}"
        )
    return issues


def _few(values: Sequence[str], limit: int = 5) -> str:
    shown = ", ".join(values[:limit])
    return shown if len(values) <= limit else f"{shown}, ..."


# --- inspection -------------------------------------------------------------


def dump_projection(engine: Engine, *, exclude: Collection[str] = (PROJECTION_META.name,)) -> str:
    """Every projection row as deterministic text, ordered by table then primary key.

    Two rebuilds of an unchanged workspace produce identical dumps. ``projection_meta`` is
    excluded by default because it records wall-clock build time, which is the one value in
    the projection that is allowed to differ between two rebuilds.
    """
    lines: list[str] = []
    with engine.connect() as connection:
        for name in sorted(METADATA.tables):
            if name in exclude:
                continue
            table = METADATA.tables[name]
            columns = [column.name for column in table.columns]
            statement = select(table).order_by(*table.primary_key.columns)
            for row in connection.execute(statement).mappings():
                values = "\t".join(f"{column}={row[column]!r}" for column in columns)
                lines.append(f"{name}\t{values}")
    return "\n".join(lines)

"""Deterministic full rebuild and fingerprint-driven incremental update of the graph.

Two writers, one guarantee: after either of them the database holds exactly the projection
of the durable files on disk. :func:`rebuild_graph` builds a fresh database beside the
target and moves it into place, so a crash leaves the previous graph whole.
:func:`update_graph` replaces only what changed, in one transaction, and
:func:`dump_graph` is how a test proves the two agree (graph spec §4, §11.6).

The unit of change is a durable file. Every :class:`~research_harness.graph.projectors.
ProjectionUnit` carries the file's workspace-relative path as its source key and the file's
digest as its fingerprint, so an update is:

1. re-project (a read of canonical state, exactly what a rebuild does);
2. compare fingerprints, and note which sources are new, changed, or gone;
3. in one transaction, delete every row those sources own, insert the current projection,
   restore the rows an *unchanged* source still owns but the delete caught in passing
   (a citation node named by both a bibliography and a parse), re-index FTS, and advance
   the checkpoint.

Step 4 is what makes "no obsolete adjacency" testable: an update and a full rebuild of the
same workspace produce byte-identical dumps.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, delete, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from research_harness.domain.base import utc_now
from research_harness.domain.graph import GraphEdge, GraphNode
from research_harness.graph.projectors import (
    ProjectionContext,
    ProjectionUnit,
    Projector,
    project_all,
)
from research_harness.graph.schema import (
    CHECKPOINT_BUILT_AT,
    CHECKPOINT_CANONICAL_DIGEST,
    CHECKPOINT_EVENT_CURSOR,
    CHECKPOINT_SCHEMA_VERSION,
    CHECKPOINTS,
    EDGES,
    FINGERPRINTS,
    GRAPH_SCHEMA_VERSION,
    NODES,
    create_all,
    create_engine_for,
    graph_database_path,
    refresh_nodes_fts,
)
from research_harness.workspace.events import file_digest
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "GraphReport",
    "GraphStatus",
    "dump_graph",
    "event_cursor",
    "graph_status",
    "rebuild_graph",
    "update_graph",
]

logger = logging.getLogger(__name__)

REBUILD_SUFFIX = ".rebuild-"
SIDECAR_SUFFIXES: tuple[str, ...] = ("-wal", "-shm")

EdgeKey = tuple[str, str, str, str]


@dataclass(frozen=True, slots=True)
class GraphReport:
    """What one graph build wrote."""

    nodes: int
    edges: int
    sources: int
    changed_sources: tuple[str, ...]
    removed_sources: tuple[str, ...]
    duration_ms: int
    incremental: bool

    def summary(self) -> str:
        """One line for a terminal or a log."""
        how = "updated" if self.incremental else "rebuilt"
        changed = (
            f", {len(self.changed_sources)} changed / {len(self.removed_sources)} removed source(s)"
            if self.incremental
            else ""
        )
        return (
            f"{how} the research graph: {self.nodes} nodes, {self.edges} edges "
            f"from {self.sources} sources{changed} in {self.duration_ms} ms"
        )


@dataclass(frozen=True, slots=True)
class GraphStatus:
    """What the graph database says about itself (`graph.status`)."""

    database: Path
    exists: bool
    schema_version: int | None
    built_at: str | None
    canonical_digest: str | None
    event_cursor: str | None
    nodes: int
    edges: int
    sources: int

    @property
    def current(self) -> bool:
        """True when the database exists and was built by this schema version."""
        return self.exists and self.schema_version == GRAPH_SCHEMA_VERSION


# --- writing ----------------------------------------------------------------


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _node_row(node: GraphNode, source_key: str) -> dict[str, Any]:
    return {
        "identity": node.identity,
        "kind": node.kind.value,
        "authority": node.authority.value,
        "visibility": node.visibility.value,
        "label": node.label,
        "text": node.text,
        "source": node.source,
        "fingerprint": node.fingerprint,
        "meta": _json(node.metadata),
        "source_key": source_key,
    }


def _edge_row(edge: GraphEdge, source_key: str) -> dict[str, Any]:
    return {
        "from_id": edge.from_id,
        "to_id": edge.to_id,
        "kind": edge.kind.value,
        "origin": edge.origin.value,
        "authority": edge.authority.value,
        "status": edge.status,
        "source": edge.source,
        "meta": _json(edge.metadata),
        "source_key": source_key,
    }


def _upsert(connection: Connection, table: Any, rows: Sequence[Mapping[str, Any]]) -> None:
    """Insert or replace ``rows``; re-projecting an unchanged object is a no-op."""
    if not rows:
        return
    keys = [column.name for column in table.primary_key.columns]
    statement = sqlite_insert(table)
    updates = {
        column.name: statement.excluded[column.name]
        for column in table.columns
        if column.name not in keys
    }
    statement = statement.on_conflict_do_update(index_elements=keys, set_=updates)
    connection.execute(statement, [dict(row) for row in rows])


def _write_units(
    connection: Connection, units: Sequence[ProjectionUnit], *, stamp: datetime
) -> tuple[int, int]:
    """Insert every unit's nodes and edges plus its fingerprint; returns the counts."""
    moment = stamp.isoformat()
    nodes = [_node_row(node, unit.source_key) for unit in units for node in unit.nodes]
    edges = [_edge_row(edge, unit.source_key) for unit in units for edge in unit.edges]
    _upsert(connection, NODES, nodes)
    _upsert(connection, EDGES, edges)
    _upsert(
        connection,
        FINGERPRINTS,
        [
            {
                "source_key": unit.source_key,
                "fingerprint": unit.fingerprint,
                "updated_at": moment,
            }
            for unit in units
        ],
    )
    return len(nodes), len(edges)


def _write_checkpoints(
    connection: Connection, values: Mapping[str, str], *, stamp: datetime
) -> None:
    moment = stamp.isoformat()
    _upsert(
        connection,
        CHECKPOINTS,
        [
            {"name": name, "value": value, "updated_at": moment}
            for name, value in sorted(values.items())
        ],
    )


def event_cursor(repo: WorkspaceRepository) -> str:
    """Digest of `events/research.jsonl`, the semantic events an update has consumed.

    An update that finds no changed fingerprint *and* the same cursor knows nothing has
    happened since the last one, and does no work.
    """
    path = repo.layout.events_file
    return file_digest(path) if path.is_file() else ""


# --- full rebuild -----------------------------------------------------------


def rebuild_graph(
    repo: WorkspaceRepository,
    *,
    research_dir: Path | str | None = None,
    projectors: Iterable[Projector] | None = None,
) -> GraphReport:
    """Rebuild the whole graph from durable sources; never writes canonical state.

    The projection is built in `research-graph.db.rebuild-<pid>` beside the target and
    moved over it, so an interrupted rebuild leaves the previous graph intact.
    """
    started = time.perf_counter()
    stamp = utc_now()
    directory = repo.layout.research_dir if research_dir is None else Path(research_dir)
    ctx = ProjectionContext.open(repo, research_dir=directory)
    units = project_all(ctx, projectors)
    target = graph_database_path(directory)
    temporary = target.with_name(f"{target.name}{REBUILD_SUFFIX}{os.getpid()}")
    _remove_database(temporary)
    engine = create_engine_for(temporary)
    try:
        create_all(engine)
        with engine.begin() as connection:
            _write_units(connection, units, stamp=stamp)
            _write_checkpoints(
                connection,
                {
                    CHECKPOINT_SCHEMA_VERSION: str(GRAPH_SCHEMA_VERSION),
                    CHECKPOINT_BUILT_AT: stamp.isoformat(),
                    CHECKPOINT_CANONICAL_DIGEST: _canonical_digest(repo),
                    CHECKPOINT_EVENT_CURSOR: event_cursor(repo),
                },
                stamp=stamp,
            )
            refresh_nodes_fts(connection)
            nodes, edges = _counts(connection)
        _checkpoint_wal(engine)
    finally:
        engine.dispose()
    _replace_database(temporary, target)
    return GraphReport(
        nodes=nodes,
        edges=edges,
        sources=len(units),
        changed_sources=(),
        removed_sources=(),
        duration_ms=int((time.perf_counter() - started) * 1000),
        incremental=False,
    )


def _canonical_digest(repo: WorkspaceRepository) -> str:
    from research_harness.projection.rebuild import canonical_digest

    return str(canonical_digest(repo))


# --- incremental update -----------------------------------------------------


def update_graph(
    repo: WorkspaceRepository,
    *,
    research_dir: Path | str | None = None,
    projectors: Iterable[Projector] | None = None,
) -> GraphReport:
    """Re-project only the sources whose fingerprint changed, atomically.

    Falls back to a full rebuild when there is no database yet or its schema version does
    not match: a projection is disposable, so rebuilding is always the safe answer.
    """
    started = time.perf_counter()
    directory = repo.layout.research_dir if research_dir is None else Path(research_dir)
    target = graph_database_path(directory)
    if not target.is_file():
        return rebuild_graph(repo, research_dir=directory, projectors=projectors)
    engine = create_engine_for(target)
    try:
        status = graph_status(engine, database=target)
        if not status.current:
            engine.dispose()
            return rebuild_graph(repo, research_dir=directory, projectors=projectors)
        return _update(repo, engine, directory, projectors, started=started)
    finally:
        engine.dispose()


def _update(
    repo: WorkspaceRepository,
    engine: Engine,
    directory: Path,
    projectors: Iterable[Projector] | None,
    *,
    started: float,
) -> GraphReport:
    stamp = utc_now()
    ctx = ProjectionContext.open(repo, research_dir=directory)
    units = project_all(ctx, projectors)
    by_key = {unit.source_key: unit for unit in units}
    cursor = event_cursor(repo)
    with engine.connect() as connection:
        stored = _load_fingerprints(connection)
        stored_cursor = _load_checkpoints(connection).get(CHECKPOINT_EVENT_CURSOR, "")
    changed = tuple(
        sorted(key for key, unit in by_key.items() if stored.get(key) != unit.fingerprint)
    )
    removed = tuple(sorted(set(stored) - set(by_key)))
    if not changed and not removed and stored_cursor == cursor:
        with engine.connect() as connection:
            counts = _counts(connection)
        return GraphReport(
            nodes=counts[0],
            edges=counts[1],
            sources=len(units),
            changed_sources=(),
            removed_sources=(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            incremental=True,
        )
    stale_keys = set(changed) | set(removed)
    with engine.begin() as connection:
        node_victims, edge_victims = _owned_rows(connection, stale_keys)
        connection.execute(delete(NODES).where(NODES.c.source_key.in_(sorted(stale_keys))))
        connection.execute(delete(EDGES).where(EDGES.c.source_key.in_(sorted(stale_keys))))
        connection.execute(
            delete(FINGERPRINTS).where(FINGERPRINTS.c.source_key.in_(sorted(stale_keys)))
        )
        rewritten = [by_key[key] for key in changed]
        _write_units(connection, rewritten, stamp=stamp)
        _restore_shared(
            connection,
            units=[unit for unit in units if unit.source_key not in stale_keys],
            written=rewritten,
            node_victims=node_victims,
            edge_victims=edge_victims,
        )
        _write_checkpoints(
            connection,
            {
                CHECKPOINT_SCHEMA_VERSION: str(GRAPH_SCHEMA_VERSION),
                CHECKPOINT_BUILT_AT: stamp.isoformat(),
                CHECKPOINT_CANONICAL_DIGEST: _canonical_digest(repo),
                CHECKPOINT_EVENT_CURSOR: cursor,
            },
            stamp=stamp,
        )
        refresh_nodes_fts(connection)
        nodes, edges = _counts(connection)
    return GraphReport(
        nodes=nodes,
        edges=edges,
        sources=len(units),
        changed_sources=changed,
        removed_sources=removed,
        duration_ms=int((time.perf_counter() - started) * 1000),
        incremental=True,
    )


def _restore_shared(
    connection: Connection,
    *,
    units: Sequence[ProjectionUnit],
    written: Sequence[ProjectionUnit],
    node_victims: set[str],
    edge_victims: set[EdgeKey],
) -> None:
    """Re-insert rows an unchanged source still produces but the delete removed.

    A node or edge can legitimately be projected by two files — a `cite:` node named by
    both `manuscript/references.bib` and a parsed reference block — and the database stores
    one row owned by whichever wrote last. Deleting by source key would otherwise leave the
    other file's projection missing until the next full rebuild, which is exactly the
    "obsolete adjacency" an update must not produce.
    """
    kept_nodes = {node.identity for unit in written for node in unit.nodes}
    kept_edges = {edge.key for unit in written for edge in unit.edges}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for unit in units:
        for node in unit.nodes:
            if node.identity in node_victims and node.identity not in kept_nodes:
                kept_nodes.add(node.identity)
                nodes.append(_node_row(node, unit.source_key))
        for edge in unit.edges:
            if edge.key in edge_victims and edge.key not in kept_edges:
                kept_edges.add(edge.key)
                edges.append(_edge_row(edge, unit.source_key))
    _upsert(connection, NODES, nodes)
    _upsert(connection, EDGES, edges)


def _owned_rows(
    connection: Connection, source_keys: Collection[str]
) -> tuple[set[str], set[EdgeKey]]:
    """Identities and edge keys currently owned by ``source_keys``, read before deleting."""
    if not source_keys:
        return set(), set()
    keys = sorted(source_keys)
    nodes = {
        str(value)
        for value in connection.execute(
            select(NODES.c.identity).where(NODES.c.source_key.in_(keys))
        ).scalars()
    }
    edges = {
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in connection.execute(
            select(EDGES.c.from_id, EDGES.c.to_id, EDGES.c.kind, EDGES.c.origin).where(
                EDGES.c.source_key.in_(keys)
            )
        )
    }
    return nodes, edges


def _load_fingerprints(connection: Connection) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in connection.execute(select(FINGERPRINTS.c.source_key, FINGERPRINTS.c.fingerprint))
    }


def _load_checkpoints(connection: Connection) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in connection.execute(select(CHECKPOINTS.c.name, CHECKPOINTS.c.value))
    }


def _counts(connection: Connection) -> tuple[int, int]:
    nodes = connection.execute(text('SELECT count(*) FROM "nodes"')).scalar_one()
    edges = connection.execute(text('SELECT count(*) FROM "edges"')).scalar_one()
    return int(nodes), int(edges)


# --- status and inspection --------------------------------------------------


def graph_status(engine: Engine, *, database: Path) -> GraphStatus:
    """Read the checkpoints and row counts back out of a graph database."""
    try:
        with engine.connect() as connection:
            checkpoints = _load_checkpoints(connection)
            nodes, edges = _counts(connection)
            sources = int(
                connection.execute(text('SELECT count(*) FROM "fingerprints"')).scalar_one()
            )
    except Exception:
        # A missing, empty, or foreign database is "not current", never a crash.
        logger.debug("graph database %s could not be read as a graph", database)
        return GraphStatus(
            database=database,
            exists=Path(database).is_file(),
            schema_version=None,
            built_at=None,
            canonical_digest=None,
            event_cursor=None,
            nodes=0,
            edges=0,
            sources=0,
        )
    version = checkpoints.get(CHECKPOINT_SCHEMA_VERSION)
    return GraphStatus(
        database=database,
        exists=True,
        schema_version=int(version) if version and version.isdigit() else None,
        built_at=checkpoints.get(CHECKPOINT_BUILT_AT),
        canonical_digest=checkpoints.get(CHECKPOINT_CANONICAL_DIGEST),
        event_cursor=checkpoints.get(CHECKPOINT_EVENT_CURSOR),
        nodes=nodes,
        edges=edges,
        sources=sources,
    )


def dump_graph(engine: Engine, *, include_sources: bool = False) -> str:
    """Every node and edge as deterministic text, ordered by primary key.

    Two builds of the same workspace produce identical dumps, which is how §11.1 and §11.6
    are asserted. ``source_key`` is excluded by default: which of two files last wrote a
    shared row is an implementation detail of the writer, not part of the projection's
    meaning, and an update and a rebuild may legitimately disagree about it.
    """
    lines: list[str] = []
    with engine.connect() as connection:
        for table in (NODES, EDGES):
            columns = [
                column.name
                for column in table.columns
                if include_sources or column.name != "source_key"
            ]
            statement = select(table).order_by(*table.primary_key.columns)
            for row in connection.execute(statement).mappings():
                values = "\t".join(f"{column}={row[column]!r}" for column in columns)
                lines.append(f"{table.name}\t{values}")
    return "\n".join(lines)


# --- files ------------------------------------------------------------------


def _checkpoint_wal(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        connection.rollback()


def _replace_database(temporary: Path, target: Path) -> None:
    os.replace(temporary, target)
    for suffix in SIDECAR_SUFFIXES:
        Path(f"{target}{suffix}").unlink(missing_ok=True)


def _remove_database(path: Path) -> None:
    path.unlink(missing_ok=True)
    for suffix in SIDECAR_SUFFIXES:
        Path(f"{path}{suffix}").unlink(missing_ok=True)

"""SQLite tables for the ResearchGraph projection: nodes, edges, adjacency, FTS, checkpoints.

The graph lives at `.research/graph/research-graph.db` and is disposable exactly like the
rest of `.research/` (ADR-001, ADR-006): deleting it costs navigation speed, never a
conclusion. Its primary keys are the *stable external identities* of
:class:`~research_harness.domain.graph.GraphNode`, so a rebuild reproduces the same rows
and `@E0482` keeps meaning the same object (graph spec §5).

Shape
-----

* ``nodes`` — one row per projected identity, with its authority, visibility, source
  pointer, fingerprint, and scalar metadata.
* ``edges`` — one row per ``(from, to, kind, origin)``, with authority, status, and a
  source pointer. There are no foreign keys: a projection that is mid-rebuild, or one
  whose citation node comes from a bibliography the parse has not seen, must be able to
  hold an edge whose endpoint is not yet a row. A dangling edge is an audit finding, never
  an insert failure.
* forward and reverse adjacency indexes — ``(from_id, kind)`` and ``(to_id, kind)`` — so a
  one- or two-hop traversal in either direction is an index lookup.
* ``nodes_fts`` — an external-content FTS5 index over ``label`` and ``text``, so search can
  be constrained to a graph neighbourhood.
* ``fingerprints`` — ``source key -> digest`` for every durable file the graph was built
  from; the unit an incremental update replaces.
* ``checkpoints`` — named scalars describing the build: schema version, build time,
  canonical digest, and the event-log cursor the last update consumed.

Both source-key columns are indexed because they are what an incremental update deletes by.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Index,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL

from research_harness.projection.schema import assert_fts5_available

__all__ = [
    "CHECKPOINTS",
    "CHECKPOINT_BUILT_AT",
    "CHECKPOINT_CANONICAL_DIGEST",
    "CHECKPOINT_EVENT_CURSOR",
    "CHECKPOINT_SCHEMA_VERSION",
    "EDGES",
    "FINGERPRINTS",
    "GRAPH_DATABASE_FILENAME",
    "GRAPH_DIRNAME",
    "GRAPH_METADATA",
    "GRAPH_SCHEMA_VERSION",
    "NODES",
    "NODES_FTS",
    "NODES_FTS_PREFIX",
    "NODES_FTS_TOKENIZER",
    "build_nodes_fts",
    "create_all",
    "create_engine_for",
    "drop_all",
    "graph_database_path",
    "graph_dir",
    "refresh_nodes_fts",
]

GRAPH_SCHEMA_VERSION = 1
"""Bumped when these tables change shape; a mismatch forces a full graph rebuild."""

GRAPH_DIRNAME = "graph"
GRAPH_DATABASE_FILENAME = "research-graph.db"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

GRAPH_METADATA = MetaData(naming_convention=NAMING_CONVENTION)
"""Its own metadata: the graph is a second database, never a table in `research.db`."""

NODES = Table(
    "nodes",
    GRAPH_METADATA,
    Column("identity", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("authority", String, nullable=False),
    Column("visibility", String, nullable=False),
    Column("label", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("source", String),
    Column("fingerprint", String),
    # `meta`, not `metadata`: `Table.metadata` is SQLAlchemy's own attribute.
    Column("meta", Text, nullable=False),
    Column("source_key", String, nullable=False),
)

EDGES = Table(
    "edges",
    GRAPH_METADATA,
    Column("from_id", String, primary_key=True),
    Column("to_id", String, primary_key=True),
    Column("kind", String, primary_key=True),
    Column("origin", String, primary_key=True),
    Column("authority", String, nullable=False),
    Column("status", Text, nullable=False),
    Column("source", String),
    Column("meta", Text, nullable=False),
    Column("source_key", String, nullable=False),
)

FINGERPRINTS = Table(
    "fingerprints",
    GRAPH_METADATA,
    Column("source_key", String, primary_key=True),
    Column("fingerprint", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

CHECKPOINTS = Table(
    "checkpoints",
    GRAPH_METADATA,
    Column("name", String, primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", String, nullable=False),
)

CHECKPOINT_SCHEMA_VERSION = "schema_version"
CHECKPOINT_BUILT_AT = "built_at"
CHECKPOINT_CANONICAL_DIGEST = "canonical_digest"
CHECKPOINT_EVENT_CURSOR = "event_cursor"

Index("ix_nodes_kind", NODES.c.kind)
Index("ix_nodes_authority", NODES.c.authority)
Index("ix_nodes_source_key", NODES.c.source_key)
#: Forward adjacency: "what does this node point at, under this relation?"
Index("ix_edges_from_id_kind", EDGES.c.from_id, EDGES.c.kind)
#: Reverse adjacency: "what points at this node, under this relation?"
Index("ix_edges_to_id_kind", EDGES.c.to_id, EDGES.c.kind)
Index("ix_edges_kind", EDGES.c.kind)
Index("ix_edges_origin", EDGES.c.origin)
Index("ix_edges_source_key", EDGES.c.source_key)

NODES_FTS = "nodes_fts"
NODES_FTS_TOKENIZER = "unicode61 remove_diacritics 2"
"""Case- and diacritic-folding; digits stay inside their token, so `CICIDS2017` is one term."""

NODES_FTS_PREFIX = "2 3"
"""Prefix index widths, so composer autocomplete on `CIC*` is a lookup, not a scan."""

_NODES_FTS_CREATE = (
    f'CREATE VIRTUAL TABLE IF NOT EXISTS "{NODES_FTS}" USING fts5('
    '"label", "text", "identity" UNINDEXED, "kind" UNINDEXED, '
    f"content='{NODES.name}', "
    f"tokenize='{NODES_FTS_TOKENIZER}', "
    f"prefix='{NODES_FTS_PREFIX}')"
)


def graph_dir(research_dir: Path | str) -> Path:
    """`<research_dir>/graph/` — where the projection's database lives."""
    return Path(research_dir) / GRAPH_DIRNAME


def graph_database_path(research_dir: Path | str) -> Path:
    """`<research_dir>/graph/research-graph.db`."""
    return graph_dir(research_dir) / GRAPH_DATABASE_FILENAME


def create_engine_for(db_path: Path) -> Engine:
    """SQLite engine for ``db_path`` with WAL journalling; creates the directory."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(path)))

    @event.listens_for(engine, "connect")
    def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine


def create_all(engine: Engine) -> None:
    """Create every graph table plus the FTS5 index over ``nodes``."""
    assert_fts5_available(engine)
    GRAPH_METADATA.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(_NODES_FTS_CREATE))


def drop_all(engine: Engine) -> None:
    """Drop the FTS index first, then every graph table (ADR-006: all of it is disposable)."""
    with engine.begin() as connection:
        connection.execute(text(f'DROP TABLE IF EXISTS "{NODES_FTS}"'))
    GRAPH_METADATA.drop_all(engine)


def build_nodes_fts(engine: Engine) -> None:
    """Create the FTS table if missing and index every node row."""
    assert_fts5_available(engine)
    with engine.begin() as connection:
        connection.execute(text(_NODES_FTS_CREATE))
        refresh_nodes_fts(connection)


def refresh_nodes_fts(connection: Any) -> None:
    """Re-index ``nodes_fts`` from its content table, inside the caller's transaction.

    External-content FTS5 does not follow writes to its content table, so every path that
    changes ``nodes`` ends with this. Rebuilding the whole index rather than tracking
    per-row deltas keeps an incremental update as correct as a full rebuild, which is the
    property graph spec §4 asks for; at personal-scale corpora it costs milliseconds.
    """
    connection.execute(text(f'INSERT INTO "{NODES_FTS}"("{NODES_FTS}") VALUES(\'rebuild\')'))

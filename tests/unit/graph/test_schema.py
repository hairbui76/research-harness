"""The graph database's shape: where it lives, what it creates, and that it is disposable."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from research_harness.graph.schema import (
    EDGES,
    GRAPH_SCHEMA_VERSION,
    NODES,
    NODES_FTS,
    create_all,
    create_engine_for,
    drop_all,
    graph_database_path,
    graph_dir,
)


def test_the_graph_lives_under_the_research_directory(tmp_path: Path) -> None:
    research = tmp_path / ".research"

    assert graph_dir(research) == research / "graph"
    assert graph_database_path(research) == research / "graph" / "research-graph.db"


def test_create_all_makes_the_tables_indexes_and_fts(tmp_path: Path) -> None:
    engine = create_engine_for(graph_database_path(tmp_path / ".research"))
    try:
        create_all(engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        indexes = {index["name"] for index in inspector.get_indexes(NODES.name)} | {
            index["name"] for index in inspector.get_indexes(EDGES.name)
        }
    finally:
        engine.dispose()

    assert {"nodes", "edges", "fingerprints", "checkpoints", NODES_FTS} <= tables
    assert {"ix_edges_from_id_kind", "ix_edges_to_id_kind"} <= indexes
    assert {"ix_nodes_source_key", "ix_edges_source_key"} <= indexes


def test_the_edge_primary_key_is_from_to_kind_origin(tmp_path: Path) -> None:
    """One evidence may both contradict a claim and be proposed as supporting it."""
    assert [column.name for column in EDGES.primary_key.columns] == [
        "from_id",
        "to_id",
        "kind",
        "origin",
    ]
    assert [column.name for column in NODES.primary_key.columns] == ["identity"]
    assert GRAPH_SCHEMA_VERSION >= 1
    assert tmp_path.is_dir()


def test_create_all_is_idempotent_and_drop_all_removes_everything(tmp_path: Path) -> None:
    engine = create_engine_for(graph_database_path(tmp_path / ".research"))
    try:
        create_all(engine)
        create_all(engine)
        drop_all(engine)
        remaining = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert not remaining & {"nodes", "edges", "fingerprints", "checkpoints", NODES_FTS}


def test_the_database_runs_in_wal_mode(tmp_path: Path) -> None:
    engine = create_engine_for(graph_database_path(tmp_path / ".research"))
    try:
        create_all(engine)
        with engine.connect() as connection:
            mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
    finally:
        engine.dispose()

    assert str(mode).lower() == "wal"

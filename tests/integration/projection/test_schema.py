"""The SQLite projection: creatable, deletable, idempotent, and ID-faithful."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, insert, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from research_harness.domain import (
    ClaimId,
    DecisionId,
    DocumentBlockKind,
    EvidenceContent,
    EvidenceId,
    EvidenceOrigin,
    Interpretation,
    InterpretationId,
    ManuscriptAnchor,
    MatrixCell,
    ProjectionError,
    ResearchEvent,
    ResearchEventType,
    SynthesisId,
    SynthesisMatrix,
    TableCell,
    Taxonomy,
    TaxonomyTerm,
    WorkId,
)
from research_harness.projection import (
    METADATA,
    PROJECTION_META,
    PROJECTION_META_ID,
    PROJECTION_SCHEMA_VERSION,
    TABLES,
    assert_fts5_available,
    create_all,
    create_engine_for,
    drop_all,
    rows_for,
    table_for,
    upsert_rows,
)
from research_harness.projection.fts import INDEXES, build_fts
from tests.unit.domain import strategies as sty

ANCHOR_FILE = "manuscript/main.tex"


def canonical_objects() -> list[object]:
    """One of every projected canonical type, in insertion (foreign-key) order."""
    work = sty.make_work(versions=("V0017-2",), artifacts=("A0017-3",))
    version = sty.make_version()
    artifact = sty.make_artifact()
    paragraph = sty.make_block()
    table_block = sty.make_block(
        id="B0082",
        kind=DocumentBlockKind.TABLE,
        order=13,
        cells=(
            TableCell(row=0, col=0, text="model"),
            TableCell(row=0, col=1, text="F1"),
        ),
    )
    evidence = sty.make_evidence(
        content=EvidenceContent(exact_text="F1 is 94.32.", numeric=sty.make_numeric())
    )
    interpretation = Interpretation(
        id=InterpretationId("I0009"),
        evidence=(EvidenceId("E0482"),),
        text="The two systems are not directly comparable.",
        origin=EvidenceOrigin.RESEARCHER_INFERRED,
        provenance=sty.HUMAN,
    )
    claim = sty.make_claim(decisions=(DecisionId("D0027"),))
    decision = sty.make_override_decision()
    question = sty.make_question(
        claims=(ClaimId("C0041"),),
        search_runs=("SR0019",),
        supporting_evidence=(EvidenceId("E0482"),),
    )
    taxonomy = Taxonomy(
        name="representation",
        terms=(TaxonomyTerm(term="byte_level", decision=DecisionId("D0012")),),
        provenance=sty.HUMAN,
    )
    search_run = sty.make_search_run()
    matrix = SynthesisMatrix(
        id=SynthesisId("S0007"),
        name="representation matrix",
        taxonomy="representation",
        works=(WorkId("W0017"),),
        fields=("tokenization",),
        cells=(
            MatrixCell(
                work=WorkId("W0017"),
                field="tokenization",
                labels=("byte_level",),
                evidence=(EvidenceId("E0482"),),
            ),
        ),
        provenance=sty.HUMAN,
    )
    note = sty.make_note()
    anchor = ManuscriptAnchor(
        file=ANCHOR_FILE,
        line_start=41,
        line_end=41,
        sentence="Representations differ in tokenization granularity.",
        sentence_fingerprint=sty.HASH_C,
        claim=ClaimId("C0041"),
        provenance=sty.HUMAN,
    )
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED,
        subjects=(ClaimId("C0041"),),
        actor="human",
        summary="claim C0041 created",
    )
    return [
        work,
        version,
        artifact,
        paragraph,
        table_block,
        evidence,
        interpretation,
        claim,
        decision,
        question,
        taxonomy,
        search_run,
        matrix,
        note,
        anchor,
        event,
    ]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    built = create_engine_for(tmp_path / ".research" / "research.db")
    create_all(built)
    yield built
    built.dispose()


def _project(built: Engine, objects: list[object]) -> None:
    with built.begin() as connection:
        for obj in objects:
            upsert_rows(connection, rows_for(obj))


def _project_everything(built: Engine) -> None:
    _project(built, canonical_objects())


def _row_counts(built: Engine) -> dict[str, int]:
    with built.connect() as connection:
        return {
            name: connection.execute(select(func.count()).select_from(table)).scalar_one()
            for name, table in TABLES.items()
        }


# --- creation ---------------------------------------------------------------


def test_create_all_builds_every_declared_table(engine: Engine) -> None:
    present = set(inspect(engine).get_table_names())

    assert set(METADATA.tables) <= present
    assert {"works", "evidence", "claims", "dependencies", "stale_marks"} <= present


def test_engine_enables_foreign_keys_and_wal(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert str(connection.execute(text("PRAGMA journal_mode")).scalar_one()) == "wal"


def test_fts5_is_available_and_the_probe_leaves_no_table_behind(engine: Engine) -> None:
    assert_fts5_available(engine)

    assert "blocks_fts" not in set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        leftovers = connection.execute(text("SELECT name FROM temp.sqlite_master")).all()
    assert leftovers == []


def test_table_for_rejects_unknown_tables() -> None:
    with pytest.raises(ProjectionError):
        table_for("no_such_table")


# --- projecting canonical objects -------------------------------------------


def test_every_canonical_object_projects_into_its_table(engine: Engine) -> None:
    _project_everything(engine)

    counts = _row_counts(engine)
    assert counts["works"] == 1
    assert counts["versions"] == 1
    assert counts["artifacts"] == 1
    assert counts["blocks"] == 2
    assert counts["table_cells"] == 2
    assert counts["evidence"] == 1
    assert counts["interpretations"] == 1
    assert counts["claims"] == 1
    assert counts["claim_evidence"] == 2
    assert counts["claim_decisions"] == 1
    assert counts["decisions"] == 1
    assert counts["questions"] == 1
    assert counts["question_links"] == 3
    assert counts["taxonomies"] == 1
    assert counts["taxonomy_terms"] == 1
    assert counts["search_runs"] == 1
    assert counts["matrices"] == 1
    assert counts["matrix_cells"] == 1
    assert counts["notes"] == 1
    assert counts["manuscript_anchors"] == 1
    assert counts["events"] == 1


def test_projection_ids_are_the_canonical_ids(engine: Engine) -> None:
    _project_everything(engine)

    with engine.connect() as connection:
        assert connection.execute(select(table_for("works").c.id)).scalar_one() == "W0017"
        assert connection.execute(select(table_for("versions").c.id)).scalar_one() == "V0017-2"
        assert connection.execute(select(table_for("artifacts").c.id)).scalar_one() == "A0017-3"
        assert connection.execute(select(table_for("evidence").c.id)).scalar_one() == "E0482"
        assert connection.execute(select(table_for("claims").c.id)).scalar_one() == "C0041"
        assert connection.execute(select(table_for("questions").c.id)).scalar_one() == "RQ0003"
        assert connection.execute(select(table_for("matrices").c.id)).scalar_one() == "S0007"
        anchors = table_for("manuscript_anchors")
        assert connection.execute(select(anchors.c.claim)).scalar_one() == "C0041"


def test_upserting_twice_is_idempotent(engine: Engine) -> None:
    objects = canonical_objects()
    _project(engine, objects)
    first = _row_counts(engine)

    _project(engine, objects)

    assert _row_counts(engine) == first


def test_projection_meta_records_the_schema_version(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(PROJECTION_META).values(
                id=PROJECTION_META_ID,
                schema_version=PROJECTION_SCHEMA_VERSION,
                built_at=datetime(2026, 9, 3, tzinfo=UTC).isoformat(),
                canonical_digest="sha256:" + "a" * 64,
            )
        )

    with engine.connect() as connection:
        stored = connection.execute(select(PROJECTION_META.c.schema_version)).scalar_one()
    assert stored == PROJECTION_SCHEMA_VERSION


# --- constraints ------------------------------------------------------------


def test_declared_foreign_keys_are_enforced(engine: Engine) -> None:
    orphan = sty.make_version(id="V9999-1", work="W9999")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        upsert_rows(connection, rows_for(orphan))


def test_table_cells_require_their_block(engine: Engine) -> None:
    _project_everything(engine)
    cells = table_for("table_cells")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(cells).values(artifact="A0017-3", block="B9999", row=0, col=0, text="x")
        )


# --- deletability -----------------------------------------------------------


def test_drop_all_then_create_all_yields_an_empty_schema(engine: Engine) -> None:
    _project_everything(engine)
    assert _row_counts(engine)["works"] == 1

    drop_all(engine)
    assert not set(inspect(engine).get_table_names()) & set(METADATA.tables)

    create_all(engine)
    assert set(METADATA.tables) <= set(inspect(engine).get_table_names())
    assert set(_row_counts(engine).values()) == {0}


def test_drop_all_takes_the_fts_tables_with_it(engine: Engine) -> None:
    """A "deletable" projection that left its lexical indexes behind was not deleted.

    The FTS5 tables are external-content indexes over these rows. Dropping the content
    tables and leaving the shadow tables would leave a deleted projection still answering
    queries out of tables whose content is gone (ADR-001, ADR-006).
    """
    _project_everything(engine)
    build_fts(engine)
    fts_names = {index.name for index in INDEXES}
    assert fts_names <= set(inspect(engine).get_table_names())

    drop_all(engine)

    present = set(inspect(engine).get_table_names())
    assert not fts_names & present
    assert not {name for name in present if "_fts" in name}
    assert not set(METADATA.tables) & present


def test_the_projection_can_be_rebuilt_whole_after_a_drop(engine: Engine) -> None:
    """Deletable means deletable *and* rebuildable, indexes included."""
    _project_everything(engine)
    build_fts(engine)
    drop_all(engine)

    create_all(engine)
    _project_everything(engine)
    indexed = build_fts(engine)

    assert indexed > 0
    assert {index.name for index in INDEXES} <= set(inspect(engine).get_table_names())

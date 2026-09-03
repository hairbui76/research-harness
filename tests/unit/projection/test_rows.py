"""Canonical object -> row mapping: stable ids, determinism, and recoverability."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given

from research_harness.domain import (
    Artifact,
    BoundingBox,
    CandidateMetadata,
    Claim,
    Decision,
    DocumentBlockKind,
    Evidence,
    EvidenceContent,
    EvidenceOrigin,
    IdentifierField,
    IdentityResolutionOutcome,
    Interpretation,
    InterpretationId,
    ManuscriptAnchor,
    ManuscriptAnchorStatus,
    MatrixCell,
    ParsedDocument,
    ProjectionError,
    ProvenanceSource,
    ResearchEvent,
    ResearchEventType,
    ScreeningState,
    SearchCandidate,
    SearchResultCounts,
    SearchRunId,
    SynthesisId,
    SynthesisMatrix,
    TableCell,
    Taxonomy,
    TaxonomyTerm,
    Version,
    Work,
    WorkCandidate,
    WorkId,
    WorkIdentifiers,
)
from research_harness.projection import (
    event_id,
    manuscript_anchor_key,
    matrix_cell_node_id,
    node_id_for,
    note_key,
    rows_for,
    taxonomy_node_id,
)
from tests.unit.domain import strategies as sty

# --- stable ids and determinism ---------------------------------------------


@given(sty.works())
def test_work_row_key_is_the_canonical_id_and_mapping_is_deterministic(work: Work) -> None:
    rows = rows_for(work)
    assert rows[0].table == "works"
    assert rows[0].values["id"] == str(work.id)
    assert rows == rows_for(work)


@given(sty.versions())
def test_version_row_key_is_the_canonical_id(version: Version) -> None:
    rows = rows_for(version)
    assert rows[0].table == "versions"
    assert rows[0].values["id"] == str(version.id)
    assert rows == rows_for(version)


@given(sty.artifacts())
def test_artifact_row_key_is_the_canonical_id(artifact: Artifact) -> None:
    rows = rows_for(artifact)
    assert rows[0].table == "artifacts"
    assert rows[0].values["id"] == str(artifact.id)
    assert rows == rows_for(artifact)


@given(sty.evidence_objects())
def test_evidence_row_key_is_the_canonical_id(evidence: Evidence) -> None:
    rows = rows_for(evidence)
    assert rows[0].table == "evidence"
    assert rows[0].values["id"] == str(evidence.id)
    assert rows == rows_for(evidence)


@given(sty.claims())
def test_claim_row_key_is_the_canonical_id_and_owns_its_link_rows(claim: Claim) -> None:
    rows = rows_for(claim)
    assert rows[0].table == "claims"
    assert rows[0].values["id"] == str(claim.id)
    assert all(row.values["claim"] == str(claim.id) for row in rows[1:])
    assert rows == rows_for(claim)


@given(sty.decisions())
def test_decision_row_key_is_the_canonical_id(decision: Decision) -> None:
    rows = rows_for(decision)
    assert rows[0].table == "decisions"
    assert rows[0].values["id"] == str(decision.id)
    assert rows == rows_for(decision)


@given(sty.works())
def test_work_collections_round_trip_through_json_columns(work: Work) -> None:
    values = rows_for(work)[0].values
    assert json.loads(str(values["authors"])) == list(work.authors)
    assert json.loads(str(values["versions"])) == [str(version) for version in work.versions]
    assert json.loads(str(values["artifacts"])) == [str(a) for a in work.artifacts]


# --- recoverability ---------------------------------------------------------


def test_evidence_row_flattens_the_anchor_and_the_numeric_value() -> None:
    evidence = sty.make_evidence(
        content=EvidenceContent(exact_text="F1 is 94.32 on CICIDS2017.", numeric=sty.make_numeric())
    )

    values = rows_for(evidence)[0].values

    assert values["id"] == "E0482"
    assert values["work"] == "W0017"
    assert values["artifact"] == "A0017-3"
    assert values["block"] == "B0081"
    assert values["page"] == 8
    assert values["char_start"] == 284
    assert values["metric"] == "F1"
    assert values["dataset"] == "CICIDS2017"
    assert values["unit"] == "percent"
    assert values["numeric_value"] == pytest.approx(94.32)
    assert json.loads(str(values["numeric_condition"])) == {"split": "test"}
    assert values["status"] == "proposed"


def test_claim_rows_include_one_link_row_per_evidence_relation() -> None:
    rows = rows_for(sty.make_claim())

    links = [row for row in rows if row.table == "claim_evidence"]
    assert [row.values["evidence"] for row in links] == ["E0132", "E0180"]
    assert [row.values["ordinal"] for row in links] == [0, 1]
    assert links[1].values["aspect"] == "tokenizer granularity"
    assert rows[0].values["requested_strength"] == "field_generalization"
    assert rows[0].values["allowed_strength"] == "individual"


def test_claim_rows_record_the_matrices_the_claim_was_derived_from() -> None:
    claim = sty.make_claim(derived_from=(SynthesisId("S0007"),))

    values = rows_for(claim)[0].values

    assert json.loads(str(values["derived_from"])) == ["S0007"]
    assert json.loads(str(rows_for(sty.make_claim())[0].values["derived_from"])) == []


def test_table_block_projects_one_row_per_cell() -> None:
    block = sty.make_block(
        kind=DocumentBlockKind.TABLE,
        cells=(
            TableCell(row=0, col=0, text="model"),
            TableCell(row=0, col=1, text="F1", bbox=BoundingBox(x0=1, y0=2, x1=3, y1=4)),
        ),
    )

    rows = rows_for(block)

    assert rows[0].table == "blocks"
    assert rows[0].values["id"] == "B0081"
    assert rows[0].values["artifact"] == "A0017-3"
    cells = [row for row in rows if row.table == "table_cells"]
    assert [(row.values["row"], row.values["col"]) for row in cells] == [(0, 0), (0, 1)]
    assert json.loads(str(cells[1].values["bbox"]))["x1"] == 3.0


def test_blocks_projected_through_their_document_carry_its_artifact_hash() -> None:
    """The bytes an anchor replays against are queryable without re-reading the parse."""
    block = sty.make_block()
    document = ParsedDocument(
        work=block.work,
        version=block.version,
        artifact=block.artifact,
        file_hash=sty.HASH_A,
        parser_name="pymupdf",
        parser_version="1.0",
        page_count=block.page,
        blocks=(block,),
        provenance=sty.SYSTEM,
    )

    through_document = rows_for(document)[0]
    alone = rows_for(block)[0]

    assert through_document.table == "blocks"
    assert through_document.values["file_hash"] == sty.HASH_A
    assert alone.values["file_hash"] is None


def test_question_links_are_typed_by_what_they_point_at() -> None:
    question = sty.make_question(
        claims=("C0041",), search_runs=("SR0019",), supporting_evidence=("E0482",)
    )

    links = [row for row in rows_for(question) if row.table == "question_links"]

    assert {(row.values["kind"], row.values["target"]) for row in links} == {
        ("claim", "C0041"),
        ("search_run", "SR0019"),
        ("supporting_evidence", "E0482"),
    }


def test_matrix_cell_rows_carry_a_stable_cell_node_id() -> None:
    matrix = SynthesisMatrix(
        id=SynthesisId("S0007"),
        name="representation",
        taxonomy="representation",
        works=(WorkId("W0017"),),
        fields=("tokenization",),
        cells=(MatrixCell(work=WorkId("W0017"), field="tokenization", labels=("byte_level",)),),
        provenance=sty.HUMAN,
    )

    rows = rows_for(matrix)

    assert rows[0].values["id"] == "S0007"
    assert rows[1].values["cell_id"] == matrix_cell_node_id("S0007", "W0017", "tokenization")


def test_search_candidate_rows_are_keyed_by_run_and_node_key() -> None:
    """One row per discovery record: two candidates for one Work stay two rows (ADR-002)."""
    entries = (
        SearchCandidate(
            key="doi:10.1000/a",
            candidate=WorkCandidate(
                provenance=sty.SYSTEM,
                metadata=CandidateMetadata(
                    title=IdentifierField(value="Alpha", source=ProvenanceSource.EXTERNAL_METADATA),
                    year=IdentifierField(value="2024", source=ProvenanceSource.EXTERNAL_METADATA),
                    identifiers=WorkIdentifiers(
                        doi=IdentifierField(
                            value="10.1000/a", source=ProvenanceSource.EXTERNAL_METADATA
                        )
                    ),
                ),
            ),
            sources=("openalex", "crossref"),
            ranks={"openalex": 1, "crossref": 4},
            identity=IdentityResolutionOutcome.SAME_WORK,
            matched_work=WorkId("W0017"),
            full_text_available=True,
        ),
        SearchCandidate(
            key="arxiv:2101.00001",
            candidate=WorkCandidate(provenance=sty.SYSTEM),
            sources=("openalex",),
            ranks={"openalex": 2},
            screening=ScreeningState.EXCLUDED,
            exclusion_reason="not about network traffic",
            screened_by="human",
            screened_at=datetime(2026, 8, 1, tzinfo=UTC),
            identity=IdentityResolutionOutcome.SAME_WORK,
            matched_work=WorkId("W0017"),
            full_text_available=False,
        ),
    )
    run = sty.make_search_run(
        candidates=entries,
        results=SearchResultCounts(discovered=2, screened=1),
        unresolved_keys=(),
        full_text_unavailable_keys=("arxiv:2101.00001",),
        reproduces=SearchRunId("SR0018"),
    )

    rows = rows_for(run)

    assert rows[0].table == "search_runs"
    assert rows[0].values["reproduces"] == "SR0018"
    assert json.loads(str(rows[0].values["full_text_unavailable_keys"])) == ["arxiv:2101.00001"]
    candidates = [row for row in rows if row.table == "search_candidates"]
    assert [(row.values["run"], row.values["key"]) for row in candidates] == [
        ("SR0019", "doi:10.1000/a"),
        ("SR0019", "arxiv:2101.00001"),
    ]
    first, second = (row.values for row in candidates)
    assert json.loads(str(first["ranks"])) == {"openalex": 1, "crossref": 4}
    assert first["title"] == "Alpha" and first["year"] == 2024
    assert first["doi"] == "10.1000/a"
    assert first["full_text_available"] == 1
    assert second["full_text_available"] == 0
    assert second["exclusion_reason"] == "not about network traffic"
    assert second["screened_by"] == "human"
    assert {row.values["matched_work"] for row in candidates} == {"W0017"}
    assert rows == rows_for(run)


def test_a_search_run_without_candidates_projects_only_its_own_row() -> None:
    rows = rows_for(sty.make_search_run())

    assert [row.table for row in rows] == ["search_runs"]
    assert rows[0].values["reproduces"] is None


def test_interpretation_rows_keep_their_evidence_list() -> None:
    interpretation = Interpretation(
        id=InterpretationId("I0009"),
        evidence=("E0482",),
        text="The two systems are not directly comparable.",
        origin=EvidenceOrigin.RESEARCHER_INFERRED,
        provenance=sty.HUMAN,
    )

    values = rows_for(interpretation)[0].values

    assert values["id"] == "I0009"
    assert json.loads(str(values["evidence"])) == ["E0482"]


# --- surrogate keys ---------------------------------------------------------


def test_surrogate_keys_are_stable_for_objects_without_a_research_id() -> None:
    anchor = ManuscriptAnchor(
        file="manuscript/main.tex",
        line_start=12,
        line_end=12,
        sentence="Existing systems tokenize traffic heterogeneously.",
        sentence_fingerprint=sty.HASH_C,
        claim="C0041",
        status=ManuscriptAnchorStatus.VALID,
        provenance=sty.HUMAN,
    )
    taxonomy = Taxonomy(
        name="representation", terms=(TaxonomyTerm(term="byte_level"),), provenance=sty.HUMAN
    )
    note = sty.make_note()
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED,
        subjects=("C0041",),
        actor="human",
        summary="claim created",
    )

    assert node_id_for(anchor) == manuscript_anchor_key("manuscript/main.tex", sty.HASH_C)
    assert node_id_for(taxonomy) == taxonomy_node_id("representation")
    assert node_id_for(note) == note_key(note)
    assert node_id_for(event) == event_id(event)
    assert rows_for(anchor)[0].values["anchor_id"] == node_id_for(anchor)
    assert rows_for(note)[0].values["note_key"] == note_key(note)
    assert rows_for(event)[0].values["event_id"] == event_id(event)


def test_note_key_prefers_an_explicit_key_and_is_otherwise_content_derived() -> None:
    keyed = sty.make_note(key="tokenization-terminology")
    unkeyed = sty.make_note()

    assert note_key(keyed) == "tokenization-terminology"
    assert note_key(unkeyed).startswith("note:")
    assert note_key(unkeyed) == note_key(unkeyed)


def test_staged_candidates_are_deliberately_not_projected() -> None:
    with pytest.raises(ProjectionError):
        rows_for(WorkCandidate(provenance=sty.SYSTEM))


# -- batching writes changes speed, not the tables it writes --------------------


def test_rows_are_batched_into_runs_of_one_table_and_one_column_shape() -> None:
    """One compiled statement per shape, one execute per run: the order stays the order."""
    from research_harness.projection.rows import RowSpec, _batched

    rows = [
        RowSpec("works", {"id": "W0001", "title": "a"}),
        RowSpec("works", {"id": "W0002", "title": "b"}),
        RowSpec("versions", {"id": "V0001-1", "work": "W0001"}),
        RowSpec("works", {"id": "W0003", "title": "c"}),
        RowSpec("works", {"id": "W0004"}),
    ]
    batches = [(statement.table.name, params) for statement, params in _batched(rows)]

    assert [(name, len(params)) for name, params in batches] == [
        ("works", 2),
        ("versions", 1),
        ("works", 1),
        ("works", 1),
    ]
    assert [row["id"] for _, params in batches for row in params] == [
        "W0001",
        "W0002",
        "V0001-1",
        "W0003",
        "W0004",
    ]


def test_one_statement_is_compiled_per_table_and_column_shape() -> None:
    from research_harness.projection.rows import _upsert_statement

    first = _upsert_statement(("works", ("id", "title")))
    again = _upsert_statement(("works", ("id", "title")))
    other = _upsert_statement(("works", ("id",)))

    assert first is again
    assert first is not other


def test_a_row_written_twice_in_one_batch_leaves_the_last_value(tmp_path: Path) -> None:
    """Batching must not turn last-write-wins into first-write-wins."""
    from sqlalchemy import select

    from research_harness.projection.rows import upsert_rows
    from research_harness.projection.schema import WORKS, create_all, create_engine_for

    engine = create_engine_for(tmp_path / "batch.db")
    create_all(engine)
    first = rows_for(sty.make_work(title="first"))[0]
    second = rows_for(sty.make_work(title="second"))[0]
    with engine.begin() as connection:
        upsert_rows(connection, [first, second])
    with engine.connect() as connection:
        titles = list(connection.execute(select(WORKS.c.title)).scalars())
    engine.dispose()

    assert titles == ["second"]

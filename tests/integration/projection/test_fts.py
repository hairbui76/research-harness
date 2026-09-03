"""The FTS5 lexical index: exact terminology search with no embeddings and no services."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from research_harness.domain import (
    DocumentBlockKind,
    EvidenceContent,
    ProjectionError,
    WorkId,
)
from research_harness.projection import create_all, create_engine_for, rows_for, upsert_rows
from research_harness.projection.fts import (
    INDEXES,
    FtsHit,
    FtsKind,
    build_fts,
    drop_fts,
    fts_query,
    refresh_fts,
    search_fts,
)
from tests.unit.domain import strategies as sty

DATASET = "CICIDS2017"
OTHER_WORK = WorkId("W0018")


def corpus() -> list[object]:
    """Two works, three blocks, one evidence object, one claim, one note."""
    work = sty.make_work()
    other = sty.make_work(id=OTHER_WORK, title="Résumé of encrypted traffic analysis", year=2025)
    version = sty.make_version()
    artifact = sty.make_artifact()
    twice = sty.make_block(
        id="B0081",
        order=1,
        text=f"We evaluate on {DATASET}. The {DATASET} split is the standard one.",
        section_path=("Experiments", "Dataset"),
    )
    once = sty.make_block(
        id="B0082",
        order=2,
        page=9,
        text=f"A single mention of {DATASET} appears in the discussion.",
        section_path=("Discussion", "Limitations"),
    )
    unrelated = sty.make_block(
        id="B0083",
        order=3,
        kind=DocumentBlockKind.PARAGRAPH,
        text="Nothing here concerns the evaluation corpus at all.",
        section_path=("Introduction",),
    )
    evidence = sty.make_evidence(content=EvidenceContent(exact_text=f"We evaluate on {DATASET}."))
    claim = sty.make_claim()
    note = sty.make_note(text=f"Compare the {DATASET} preprocessing between both systems.")
    return [work, other, version, artifact, twice, once, unrelated, evidence, claim, note]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    built = create_engine_for(tmp_path / ".research" / "research.db")
    create_all(built)
    with built.begin() as connection:
        for obj in corpus():
            upsert_rows(connection, rows_for(obj))
    build_fts(built)
    yield built
    built.dispose()


def _ids(hits: list[FtsHit]) -> list[str]:
    return [hit.object_id for hit in hits]


# --- the index --------------------------------------------------------------


def test_build_fts_indexes_every_projected_text_row(engine: Engine) -> None:
    assert build_fts(engine) == 8  # 3 blocks + 1 evidence + 1 claim + 2 works + 1 note


def test_the_index_is_external_content_so_no_text_is_duplicated(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())

    assert {index.name for index in INDEXES} <= tables
    # An external-content table has no `_content` shadow table of its own.
    assert not any(name.endswith("_fts_content") for name in tables)


def test_refresh_and_drop_leave_a_working_index(engine: Engine) -> None:
    drop_fts(engine)
    assert not any(name.endswith("_fts") for name in inspect(engine).get_table_names())

    assert refresh_fts(engine) == 8
    assert _ids(search_fts(engine, DATASET, kinds=[FtsKind.EVIDENCE])) == ["E0482"]


def test_the_index_uses_the_declared_tokenizer_and_prefix_configuration(engine: Engine) -> None:
    with engine.connect() as connection:
        sql = str(
            connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name = 'blocks_fts'")
            ).scalar_one()
        )

    assert "unicode61 remove_diacritics 2" in sql
    assert "prefix='2 3'" in sql


# --- searching --------------------------------------------------------------


def test_an_exact_identifier_is_searchable_without_embeddings(engine: Engine) -> None:
    hits = search_fts(engine, DATASET)

    assert {"B0081", "B0082", "E0482"} <= set(_ids(hits))
    assert all(isinstance(hit.kind, FtsKind) for hit in hits)


def test_a_phrase_query_matches_only_adjacent_terms(engine: Engine) -> None:
    hits = search_fts(engine, f'"single mention of {DATASET}"')

    assert _ids(hits) == ["B0082"]


def test_a_prefix_query_matches_the_full_identifier(engine: Engine) -> None:
    hits = search_fts(engine, "CICI*", kinds=[FtsKind.BLOCK])

    assert set(_ids(hits)) == {"B0081", "B0082"}


def test_diacritics_are_folded_so_resume_finds_resume(engine: Engine) -> None:
    hits = search_fts(engine, "resume", kinds=[FtsKind.WORK])

    assert _ids(hits) == [str(OTHER_WORK)]


def test_the_kind_filter_selects_which_index_answers(engine: Engine) -> None:
    notes = search_fts(engine, DATASET, kinds=[FtsKind.NOTE])

    assert [hit.kind for hit in notes] == [FtsKind.NOTE]
    assert _ids(search_fts(engine, DATASET, kinds=["evidence"])) == ["E0482"]
    assert search_fts(engine, DATASET, kinds=[FtsKind.CLAIM]) == []


def test_the_work_filter_keeps_only_that_works_hits(engine: Engine) -> None:
    hits = search_fts(engine, "traffic", work=OTHER_WORK)

    assert _ids(hits) == [str(OTHER_WORK)]
    assert all(hit.work == str(OTHER_WORK) for hit in hits)


def test_the_work_filter_drops_indexes_that_have_no_work(engine: Engine) -> None:
    assert search_fts(engine, DATASET, work=WorkId("W0017"), kinds=[FtsKind.NOTE]) == []
    assert _ids(search_fts(engine, DATASET, work=WorkId("W0017"))) == ["B0081", "B0082", "E0482"]


def test_the_section_prefix_filter_restricts_a_query_to_one_part_of_the_paper(
    engine: Engine,
) -> None:
    assert _ids(search_fts(engine, DATASET, section_prefix="Discussion")) == ["B0082"]
    assert set(_ids(search_fts(engine, DATASET, section_prefix="Experiments/Dataset"))) == {
        "B0081",
        "E0482",
    }
    assert search_fts(engine, DATASET, section_prefix="Experiments/Baselines") == []
    # A partial segment is not a path prefix: "Experiment" is not the section "Experiments".
    assert search_fts(engine, DATASET, section_prefix="Experiment") == []


def test_a_section_name_with_like_wildcards_is_matched_literally(engine: Engine) -> None:
    with engine.begin() as connection:
        upsert_rows(
            connection,
            rows_for(
                sty.make_block(
                    id="B0084",
                    order=4,
                    text=f"{DATASET} in a section whose name looks like a LIKE pattern.",
                    section_path=("Related_Work",),
                )
            ),
        )
    build_fts(engine)

    assert _ids(search_fts(engine, DATASET, section_prefix="Related_Work")) == ["B0084"]
    assert search_fts(engine, DATASET, section_prefix="RelatedXWork") == []


def test_a_block_mentioning_the_term_twice_outranks_one_mentioning_it_once(
    engine: Engine,
) -> None:
    hits = search_fts(engine, DATASET, kinds=[FtsKind.BLOCK])

    assert _ids(hits) == ["B0081", "B0082"]
    assert hits[0].rank < hits[1].rank


def test_a_hit_carries_its_snippet_and_structural_location(engine: Engine) -> None:
    (hit,) = search_fts(engine, DATASET, kinds=[FtsKind.BLOCK], section_prefix="Discussion")

    assert DATASET in hit.snippet
    assert hit.kind is FtsKind.BLOCK
    assert hit.work == "W0017"
    assert hit.page == 9
    assert hit.section_path == ("Discussion", "Limitations")


def test_the_limit_bounds_the_result_set(engine: Engine) -> None:
    assert len(search_fts(engine, DATASET, limit=1)) == 1
    assert search_fts(engine, DATASET, limit=0) == []


def test_a_term_nothing_mentions_returns_no_hits(engine: Engine) -> None:
    assert search_fts(engine, "UNSW-NB15") == []


def test_an_unknown_kind_is_refused(engine: Engine) -> None:
    with pytest.raises(ProjectionError, match="unknown search kind"):
        search_fts(engine, DATASET, kinds=["paragraph"])


# --- safe input -------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        'CICIDS2017" OR "',
        "CICIDS2017 (",
        '") ; DROP TABLE blocks; --',
        "^%$#",
        "",
        "   ",
        "NEAR",
        "AND OR NOT",
    ],
)
def test_hostile_input_is_searched_for_and_never_executed(engine: Engine, hostile: str) -> None:
    hits = search_fts(engine, hostile)

    assert isinstance(hits, list)


def test_a_query_that_looks_like_syntax_still_finds_the_term(engine: Engine) -> None:
    assert {"B0081", "B0082"} <= set(_ids(search_fts(engine, f"{DATASET} (")))
    # An operator smuggled inside quotes stays a search term: no block contains "or".
    assert search_fts(engine, f'{DATASET}" OR "') == []


def test_fts_query_quotes_every_term_and_keeps_the_operators() -> None:
    assert fts_query("CICIDS2017") == '"CICIDS2017"'
    assert fts_query('"encrypted traffic"') == '"encrypted traffic"'
    assert fts_query("CICI*") == '"CICI"*'
    assert fts_query("f1 AND recall") == '"f1" AND "recall"'
    assert fts_query("byte-level") == '"byte level"'
    assert fts_query('a " b') == '"a" "b"'


def test_fts_query_drops_syntax_that_would_not_parse() -> None:
    assert fts_query("(((") == ""
    assert fts_query("") == ""
    assert fts_query("AND") == ""
    assert fts_query("AND CICIDS2017 OR") == '"CICIDS2017"'
    assert fts_query("f1 AND OR recall") == '"f1" AND "recall"'

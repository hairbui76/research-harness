"""Structured and lexical retrieval over a real projection (ROADMAP Task 5.1).

The corpus is small and hand-built so every assertion can name the row it expects: two
Works, one parsed artifact with an abstract, a dataset paragraph, a results table and a
limitations paragraph, one accepted numeric Evidence and one candidate that was never
accepted, a Claim, a Decision, a Question and a matrix cell.

What is being tested is the pair of guarantees the retrieval ladder rests on: a structured
lookup answers by *joining accepted state* rather than by scoring text, and lexical search
finds exact terminology with no embeddings and no service, under structural constraints
that survive the numbering publishers put in front of their headings.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine

from research_harness.domain.document import BoundingBox, TableCell
from research_harness.domain.enums import (
    ClaimStatus,
    DocumentBlockKind,
    EvidenceStatus,
    EvidenceType,
    ReviewAction,
    StaleState,
)
from research_harness.domain.errors import ProjectionError
from research_harness.domain.evidence import Evidence, EvidenceContent, VerificationRecord
from research_harness.domain.ids import (
    ArtifactId,
    BlockId,
    ClaimId,
    EvidenceId,
    SynthesisId,
    VersionId,
    WorkId,
)
from research_harness.domain.research import MatrixCell, SynthesisMatrix
from research_harness.projection import create_all, create_engine_for, rows_for, upsert_rows
from research_harness.projection.fts import FtsKind, build_fts
from research_harness.retrieval.lexical import SynonymTable, lexical_search
from research_harness.retrieval.structured import (
    Authority,
    StructuredHit,
    StructuredQuery,
    resolve_source,
    section_matches,
    structured_search,
    works_with_evidence,
)
from tests.unit.domain import strategies as sty

WORK = WorkId("W0017")
OTHER = WorkId("W0018")
VERSION = VersionId("V0017-2")
ARTIFACT = ArtifactId("A0017-3")
OTHER_VERSION = VersionId("V0018-1")
OTHER_ARTIFACT = ArtifactId("A0018-1")
DATASET = "CICIDS2017"
ALIAS = "CIC-IDS-2017"

ABSTRACT_BLOCK = BlockId("B0080")
DATASET_BLOCK = BlockId("B0081")
TABLE_BLOCK = BlockId("B0082")
LIMITATION_BLOCK = BlockId("B0083")

ACCEPTED = EvidenceId("E0482")
CANDIDATE = EvidenceId("E0483")
OTHER_EVIDENCE = EvidenceId("E0484")

TABLE_BBOX = BoundingBox(x0=54.0, y0=120.5, x1=558.0, y1=210.25)


def accepted(**overrides: Any) -> Evidence:
    """Evidence a researcher accepted, which is what the top rung of the ladder means."""
    verification = VerificationRecord(
        status=EvidenceStatus.ACCEPTED,
        accepted_by="human:alice",
        review_action=ReviewAction.ACCEPT,
    )
    return sty.make_evidence(verification=verification, **overrides)


def corpus() -> list[object]:
    """Everything the projection needs, in containment order (foreign keys are enforced)."""
    work = sty.make_work(versions=(VERSION,), artifacts=(ARTIFACT,))
    other_work = sty.make_work(
        id=OTHER,
        title="Flow level anomaly detection under domain shift",
        year=2025,
        versions=(OTHER_VERSION,),
        artifacts=(OTHER_ARTIFACT,),
    )
    version = sty.make_version()
    other_version = sty.make_version(id=OTHER_VERSION, work=OTHER)
    artifact = sty.make_artifact()
    other_artifact = sty.make_artifact(id=OTHER_ARTIFACT, work=OTHER, version=OTHER_VERSION)

    blocks = [
        sty.make_block(
            id=ABSTRACT_BLOCK,
            order=1,
            page=1,
            text="We study whether a pretrained sequence model transfers across captures.",
            section_path=("Abstract",),
        ),
        sty.make_block(
            id=DATASET_BLOCK,
            order=12,
            page=3,
            text=f"All experiments use {DATASET}, a labelled capture of benign traffic.",
            section_path=("3 Experiments", "3.1 Dataset"),
        ),
        sty.make_block(
            id=TABLE_BLOCK,
            kind=DocumentBlockKind.TABLE,
            order=18,
            page=4,
            text="Model Dataset F1 TrafficLM CICIDS2017 94.32",
            caption=f"Table 1: Detection performance on {DATASET}.",
            section_path=("4 Results",),
            bbox=TABLE_BBOX,
            cells=(
                TableCell(row=0, col=2, text="F1"),
                TableCell(row=1, col=2, text="94.32"),
            ),
        ),
        sty.make_block(
            id=LIMITATION_BLOCK,
            order=25,
            page=5,
            text="We did not evaluate adversarial evasion on CICIDS2017 captures.",
            section_path=("5 Limitations",),
        ),
    ]
    other_block = sty.make_block(
        id=BlockId("B0090"),
        work=OTHER,
        version=OTHER_VERSION,
        artifact=OTHER_ARTIFACT,
        order=3,
        page=2,
        text="Detection quality is reported per capture site.",
        section_path=("3 Evaluation",),
    )

    evidence = [
        accepted(
            id=ACCEPTED,
            source=sty.make_anchor(block=TABLE_BLOCK, page=4, section_path=("4 Results",)),
            content=EvidenceContent(
                exact_text="TrafficLM reaches 94.32 F1.", numeric=sty.make_numeric()
            ),
            evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
        ),
        sty.make_evidence(
            id=CANDIDATE,
            source=sty.make_anchor(
                block=DATASET_BLOCK, page=3, section_path=("3 Experiments", "3.1 Dataset")
            ),
            content=EvidenceContent(exact_text=f"All experiments use {DATASET}."),
        ),
        accepted(
            id=OTHER_EVIDENCE,
            source=sty.make_anchor(
                work=OTHER,
                version=OTHER_VERSION,
                artifact=OTHER_ARTIFACT,
                block=BlockId("B0090"),
                page=2,
                section_path=("3 Evaluation",),
            ),
            content=EvidenceContent(
                exact_text="Site A reaches 0.971 AUC.",
                numeric=sty.make_numeric(raw="0.971", parsed=0.971, metric="AUC", dataset=DATASET),
            ),
            evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
            stale=StaleState.STALE,
        ),
    ]
    claim = sty.make_claim()
    matrix = SynthesisMatrix(
        id=SynthesisId("S0007"),
        name="representation matrix",
        works=(WORK,),
        fields=("tokenization",),
        cells=(
            MatrixCell(
                work=WORK, field="tokenization", labels=("byte_level",), evidence=(ACCEPTED,)
            ),
        ),
        provenance=sty.HUMAN,
    )
    return [
        work,
        other_work,
        version,
        other_version,
        artifact,
        other_artifact,
        *blocks,
        other_block,
        *evidence,
        claim,
        sty.make_override_decision(),
        sty.make_question(),
        matrix,
        sty.make_note(text=f"Compare the {DATASET} preprocessing between both systems."),
    ]


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    root: Path = tmp_path_factory.mktemp("retrieval")
    built = create_engine_for(root / ".research" / "research.db")
    create_all(built)
    with built.begin() as connection:
        for obj in corpus():
            upsert_rows(connection, rows_for(obj))
    build_fts(built)
    yield built
    built.dispose()


def ids(hits: Sequence[StructuredHit]) -> list[str]:
    return [hit.object_id for hit in hits]


# --- structured lookups -----------------------------------------------------


def test_accepted_evidence_is_found_by_status_and_field(engine: Engine) -> None:
    hits = structured_search(
        engine,
        StructuredQuery(entity="evidence", filters={"status": "accepted", "dataset": DATASET}),
    )

    assert ids(hits) == [str(ACCEPTED), str(OTHER_EVIDENCE)]
    assert all(hit.authority is Authority.ACCEPTED_EVIDENCE for hit in hits)


def test_a_candidate_is_findable_but_never_carries_accepted_authority(engine: Engine) -> None:
    """Product 8.3: a proposed candidate is a real row and is not accepted state."""
    hits = structured_search(
        engine, StructuredQuery(entity="evidence", filters={"id": str(CANDIDATE)})
    )

    assert ids(hits) == [str(CANDIDATE)]
    assert hits[0].authority is Authority.STRUCTURED_FIELD
    assert hits[0].fields["status"] == EvidenceStatus.PROPOSED.value


def test_evidence_filters_cover_origin_type_metric_and_staleness(engine: Engine) -> None:
    by_metric = structured_search(
        engine, StructuredQuery(entity="evidence", filters={"metric": "AUC"})
    )
    stale = structured_search(
        engine, StructuredQuery(entity="evidence", filters={"stale": StaleState.STALE.value})
    )
    by_type = structured_search(
        engine,
        StructuredQuery(
            entity="evidence",
            filters={
                "evidence_type": EvidenceType.EXPERIMENTAL_RESULT.value,
                "origin": "source_observed",
            },
        ),
    )

    assert ids(by_metric) == [str(OTHER_EVIDENCE)]
    assert ids(stale) == [str(OTHER_EVIDENCE)] and stale[0].stale is True
    assert ids(by_type) == [str(ACCEPTED), str(OTHER_EVIDENCE)]


def test_a_list_of_values_becomes_one_lookup(engine: Engine) -> None:
    hits = structured_search(
        engine,
        StructuredQuery(entity="evidence", filters={"id": [str(ACCEPTED), str(CANDIDATE)]}),
    )

    assert ids(hits) == [str(ACCEPTED), str(CANDIDATE)]


def test_blocks_are_filtered_by_page_range_and_section_name(engine: Engine) -> None:
    pages = structured_search(
        engine,
        StructuredQuery(entity="block", filters={"work": str(WORK), "page_min": 3, "page_max": 4}),
    )
    limitations = structured_search(
        engine, StructuredQuery(entity="block", filters={"section_prefix": "Limitations"})
    )

    assert [hit.location.page for hit in pages] == [3, 4]
    assert ids(limitations) == [f"{LIMITATION_BLOCK}@{ARTIFACT}"]


def test_a_section_filter_reads_through_the_numbering_publishers_add(engine: Engine) -> None:
    hits = structured_search(
        engine, StructuredQuery(entity="block", filters={"section_prefix": "Experiments/Dataset"})
    )

    assert ids(hits) == [f"{DATASET_BLOCK}@{ARTIFACT}"]
    assert hits[0].location.section_path == ("3 Experiments", "3.1 Dataset")
    assert hits[0].authority is Authority.PARSED_CORPUS


def test_a_block_reference_names_its_artifact_because_a_block_id_alone_does_not(
    engine: Engine,
) -> None:
    hits = structured_search(engine, StructuredQuery(entity="block", filters={"page": 4}))

    assert ids(hits) == [f"{TABLE_BLOCK}@{ARTIFACT}"]


def test_claims_decisions_questions_and_matrix_cells_are_queryable(engine: Engine) -> None:
    claims = structured_search(
        engine,
        StructuredQuery(entity="claim", filters={"status": ClaimStatus.UNVERIFIED.value}),
    )
    decisions = structured_search(
        engine, StructuredQuery(entity="decision", filters={"status": "accepted"})
    )
    questions = structured_search(
        engine, StructuredQuery(entity="question", filters={"status": "open"})
    )
    cells = structured_search(
        engine, StructuredQuery(entity="matrix_cell", filters={"work": str(WORK)})
    )

    assert ids(claims) == [str(ClaimId("C0041"))]
    assert claims[0].authority is Authority.ACCEPTED_CLAIM
    assert ids(decisions) == ["D0027"]
    assert ids(questions) == ["RQ0003"]
    assert cells and cells[0].fields["field"] == "tokenization"


def test_an_unknown_entity_or_filter_is_refused_rather_than_ignored(engine: Engine) -> None:
    with pytest.raises(ProjectionError, match="unknown retrieval entity"):
        structured_search(
            engine, StructuredQuery(entity="claim").model_copy(update={"entity": "nope"})
        )
    with pytest.raises(ProjectionError, match="unknown filter"):
        structured_search(engine, StructuredQuery(entity="claim", filters={"colour": "red"}))


# --- the join behind "which papers use X?" ----------------------------------


def test_which_works_have_accepted_evidence_for_a_dataset(engine: Engine) -> None:
    hits = works_with_evidence(engine, field="dataset", value=DATASET)

    assert ids(hits) == [str(WORK), str(OTHER)]
    assert hits[0].authority is Authority.ACCEPTED_EVIDENCE
    assert hits[0].fields["evidence"] == str(ACCEPTED)
    assert hits[0].fields["title"]


def test_the_join_ignores_candidates_that_were_never_accepted(engine: Engine) -> None:
    hits = works_with_evidence(engine, field="field", value="anything-unused")

    assert hits == []


def test_the_join_refuses_a_field_it_cannot_filter_on(engine: Engine) -> None:
    with pytest.raises(ProjectionError, match="cannot join works"):
        works_with_evidence(engine, field="page_min", value="3")


# --- resolve_source ---------------------------------------------------------


def test_evidence_resolves_to_its_exact_anchor(engine: Engine) -> None:
    source = resolve_source(engine, str(ACCEPTED))

    assert source.kind == "evidence"
    assert (source.work, source.version, source.artifact) == (WORK, VERSION, ARTIFACT)
    assert source.block == TABLE_BLOCK
    assert source.page == 4
    assert source.section_path == ("4 Results",)
    assert (source.char_start, source.char_end) == (284, 516)
    assert source.text == "TrafficLM reaches 94.32 F1."


def test_a_block_resolves_to_its_page_and_geometry(engine: Engine) -> None:
    source = resolve_source(engine, f"{TABLE_BLOCK}@{ARTIFACT}")

    assert source.kind == "block"
    assert source.page == 4
    assert source.bbox == TABLE_BBOX.as_tuple()
    assert source.location.block == TABLE_BLOCK


def test_a_bare_block_id_resolves_when_it_is_unambiguous(engine: Engine) -> None:
    assert resolve_source(engine, str(DATASET_BLOCK)).ref == f"{DATASET_BLOCK}@{ARTIFACT}"


def test_an_unresolvable_reference_says_so(engine: Engine) -> None:
    with pytest.raises(ProjectionError, match="no evidence E9999"):
        resolve_source(engine, "E9999")
    with pytest.raises(ProjectionError, match="not a resolvable source reference"):
        resolve_source(engine, "banana")


# --- lexical search ---------------------------------------------------------


def test_exact_terminology_is_found_with_no_embeddings(engine: Engine) -> None:
    """The FTS indexes index text, so the dataset is found where it is actually written:
    in the block, in the evidence span that quotes it, and in the note."""
    hits = lexical_search(engine, DATASET)

    assert hits
    assert {hit.object_id for hit in hits} >= {str(DATASET_BLOCK), str(CANDIDATE)}
    assert all(hit.exact for hit in hits)
    assert all(0.0 <= hit.score <= 1.0 for hit in hits)


def test_a_section_constraint_keeps_only_what_lives_in_those_sections(engine: Engine) -> None:
    hits = lexical_search(engine, DATASET, section_prefix=("Discussion", "Limitations"))

    assert [hit.object_id for hit in hits] == [str(LIMITATION_BLOCK)]
    assert hits[0].location.section_path == ("5 Limitations",)


def test_a_section_constraint_excludes_objects_that_have_no_section(engine: Engine) -> None:
    """A Claim is not "in Limitations"; it is not anywhere in a document."""
    hits = lexical_search(engine, "tokenization", section_prefix="Limitations")

    assert hits == []


def test_search_can_be_restricted_to_one_work_and_one_index(engine: Engine) -> None:
    hits = lexical_search(engine, DATASET, work=WORK, kinds=[FtsKind.BLOCK])

    assert hits
    assert all(hit.work == WORK and hit.kind is FtsKind.BLOCK for hit in hits)


def test_a_synonym_adds_recall_without_displacing_an_exact_match(engine: Engine) -> None:
    synonyms = SynonymTable(terms={ALIAS: (DATASET,)})

    hits = lexical_search(engine, f"{ALIAS} OR evasion", synonyms=synonyms, limit=10)
    plain = lexical_search(engine, f"{ALIAS} OR evasion", limit=10)

    assert len(hits) > len(plain)
    assert [hit.object_id for hit in plain] == [str(LIMITATION_BLOCK)]
    assert hits[0].exact is True and hits[0].object_id == str(LIMITATION_BLOCK)
    assert any(hit.via == DATASET for hit in hits if not hit.exact)


def test_a_query_with_no_searchable_term_returns_nothing(engine: Engine) -> None:
    assert lexical_search(engine, "   ???   ") == []
    assert lexical_search(engine, DATASET, limit=0) == []


# --- section matching -------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "prefix", "expected"),
    [
        (("5 Limitations",), "Limitations", True),
        (("3 Experiments", "3.1 Dataset"), "Experiments/Dataset", True),
        (("3 Experiments", "3.1 Dataset"), "Dataset", True),
        (("3 Experiments", "3.1 Dataset"), "Dataset/Experiments", False),
        (("Abstract",), "Results", False),
        ((), "Results", False),
        (("Abstract",), "", True),
    ],
)
def test_section_matching_reads_names_not_numbering(
    path: tuple[str, ...], prefix: str, expected: bool
) -> None:
    assert section_matches(path, prefix) is expected

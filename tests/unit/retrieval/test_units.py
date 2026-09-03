"""Retrieval units: what becomes a chunk, what it says, and what it points back at.

Units are built from the real parser output for the synthetic paper, because the section
roll-up and the table rendering only mean anything against real block structure.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import NegativeEvidenceState
from research_harness.domain.evidence import EvidenceContent
from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.parsing.base import ParseTarget
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.retrieval.units import (
    IndexUnit,
    IndexUnitKind,
    block_unit_id,
    unit_from_work,
    units_from_claim,
    units_from_document,
    units_from_evidence,
)
from tests.fixtures.make_synthetic_paper import SINGLE_COLUMN_PDF
from tests.unit.domain.strategies import make_claim, make_evidence, make_numeric, make_work

WORK = WorkId("W0017")
ARTIFACT = ArtifactId("A0017-1")


@pytest.fixture(scope="module")
def paper() -> ParsedDocument:
    digest = hashlib.sha256(Path(SINGLE_COLUMN_PDF).read_bytes()).hexdigest()
    return PyMuPdfParser().parse(
        ParseTarget(
            work=WORK,
            version=VersionId("V0017-1"),
            artifact=ARTIFACT,
            file_hash=f"sha256:{digest}",
            path=Path(SINGLE_COLUMN_PDF),
            mime_type="application/pdf",
        )
    )


@pytest.fixture(scope="module")
def units(paper: ParsedDocument) -> list[IndexUnit]:
    return units_from_document(paper)


def one(units: list[IndexUnit], needle: str, kind: IndexUnitKind) -> IndexUnit:
    found = [unit for unit in units if unit.kind is kind and needle in unit.text]
    assert found, f"no {kind.value} unit contains {needle!r}"
    return found[0]


# -- document units -----------------------------------------------------------------


def test_block_units_are_identified_by_block_and_artifact(units: list[IndexUnit]) -> None:
    """A block id is unique only inside its artifact, so the unit id names both."""
    for unit in units:
        assert unit.id.endswith(f"@{ARTIFACT}")
        assert unit.artifact == ARTIFACT
        assert unit.work == WORK


def test_only_paragraph_table_caption_and_section_kinds_are_indexed(
    units: list[IndexUnit],
) -> None:
    """Equations, references and footnotes are looked up structurally, not by similarity."""
    kinds = {unit.kind for unit in units}

    assert kinds == {
        IndexUnitKind.PARAGRAPH,
        IndexUnitKind.SECTION,
        IndexUnitKind.TABLE,
        IndexUnitKind.CAPTION,
    }
    assert not any("lambda ||theta||" in unit.text for unit in units)
    assert not any(unit.text.startswith("[1] A. Author") for unit in units)


def test_units_carry_the_page_and_section_they_came_from(units: list[IndexUnit]) -> None:
    dataset = one(units, "All experiments use CICIDS2017", IndexUnitKind.PARAGRAPH)

    assert dataset.page == 3
    assert dataset.section_path == ("3 Experiments", "3.1 Dataset")


def test_a_table_unit_carries_its_caption_and_its_cells(units: list[IndexUnit]) -> None:
    """The metric a table reports is usually named in the caption, not in the cells."""
    table = one(units, "94.32", IndexUnitKind.TABLE)

    assert "Table 1: Detection performance on CICIDS2017." in table.text
    assert "TrafficLM" in table.text
    assert table.page == 4


def test_a_figure_caption_is_its_own_unit(units: list[IndexUnit]) -> None:
    caption = one(units, "Confusion matrix", IndexUnitKind.CAPTION)

    assert caption.kind is IndexUnitKind.CAPTION


def test_a_section_unit_gathers_the_paragraphs_of_its_subsections(
    units: list[IndexUnit],
) -> None:
    section = one(units, "3 Experiments", IndexUnitKind.SECTION)

    assert "one held out test split" in section.text
    assert "All experiments use CICIDS2017" in section.text
    assert "Class imbalance is severe" in section.text


def test_a_heading_with_no_paragraphs_produces_no_unit(units: list[IndexUnit]) -> None:
    """`References` would otherwise be a one-word vector that matches short queries."""
    assert not [unit for unit in units if unit.text.strip() == "References"]


def test_section_units_respect_the_character_budget(paper: ParsedDocument) -> None:
    budgeted = units_from_document(paper, max_section_chars=120)

    sections = [unit for unit in budgeted if unit.kind is IndexUnitKind.SECTION]
    assert sections
    for unit in sections:
        assert len(unit.text) <= 120


def test_building_units_twice_yields_the_same_units(paper: ParsedDocument) -> None:
    assert units_from_document(paper) == units_from_document(paper)


def test_the_work_can_be_overridden_for_an_artifact_indexed_elsewhere(
    paper: ParsedDocument,
) -> None:
    relabelled = units_from_document(paper, work=WorkId("W0099"))

    assert {unit.work for unit in relabelled} == {WorkId("W0099")}


def test_block_unit_id_is_the_composite_form() -> None:
    assert block_unit_id(*("B0081", ARTIFACT)) == f"B0081@{ARTIFACT}"


# -- canonical-object units ---------------------------------------------------------


def test_evidence_units_keep_the_canonical_id_and_the_source_anchor() -> None:
    evidence = make_evidence()

    (unit,) = units_from_evidence(evidence)

    assert unit.id == "E0482"
    assert unit.kind is IndexUnitKind.EVIDENCE
    assert unit.work == WorkId("W0017")
    assert unit.artifact == ArtifactId("A0017-3")
    assert unit.page == 8
    assert unit.section_path == ("Experiments", "Dataset")
    assert unit.text == "We evaluate on CICIDS2017."


def test_a_number_is_indexed_with_its_metric_dataset_and_table() -> None:
    """A naked `94.32` retrieves nothing; the metric and the dataset are the query terms."""
    evidence = make_evidence(
        content=EvidenceContent(exact_text="Our system reaches 94.32.", numeric=make_numeric())
    )

    (unit,) = units_from_evidence(evidence)

    assert "F1 94.32 percent" in unit.text
    assert "CICIDS2017" in unit.text
    assert "split=test" in unit.text
    assert "T004" in unit.text


def test_absence_evidence_is_indexed_by_its_state_not_by_empty_text() -> None:
    evidence = make_evidence(
        content=EvidenceContent(exact_text="", negative_state=NegativeEvidenceState.NOT_REPORTED)
    )

    (unit,) = units_from_evidence(evidence)

    assert unit.text == "absence: not_reported"


def test_claim_units_index_the_statement_and_its_proposition() -> None:
    (unit,) = units_from_claim(make_claim())

    assert unit.id == "C0041"
    assert unit.kind is IndexUnitKind.CLAIM
    assert "heterogeneous traffic tokenization schemes" in unit.text
    assert "existing_systems use traffic_tokenization" in unit.text
    assert "property=heterogeneous" in unit.text
    assert unit.work is None


def test_work_units_carry_title_authors_venue_and_year() -> None:
    work = make_work(
        authors=("A. Researcher", "B. Collaborator"), venue="Example Conference", year=2024
    )

    unit = unit_from_work(work, abstract="We study encrypted traffic representations.")

    assert unit.id == str(work.id)
    assert unit.kind is IndexUnitKind.WORK
    assert unit.work == work.id
    assert work.title in unit.text
    assert "A. Researcher; B. Collaborator" in unit.text
    assert "Example Conference 2024" in unit.text
    assert "We study encrypted traffic representations." in unit.text


def test_a_work_without_an_abstract_still_produces_a_unit() -> None:
    unit = unit_from_work(make_work(venue=None, year=None, authors=()))

    assert unit.text.strip()


# -- text hash ----------------------------------------------------------------------


def test_the_text_hash_tracks_the_text_and_nothing_else() -> None:
    first = IndexUnit(id="X1", kind=IndexUnitKind.PARAGRAPH, text="encrypted traffic")
    same_text = IndexUnit(id="X2", kind=IndexUnitKind.CLAIM, text="encrypted traffic")
    other = first.model_copy(update={"text": "encrypted traffic."})

    assert first.text_hash == same_text.text_hash
    assert first.text_hash != other.text_hash
    assert first.text_hash.startswith("sha256:")

"""The document IR over a PDF that fights the extractor (Task 2.3, 2.4; Product 43).

The fixture reproduces the two faults observed on a real publisher paper: one paragraph
whose inter-word gaps are pen movements rather than space glyphs, and one font whose
character codes are displaced, so the file literally contains `VHUYLFH` where it means
`SERVICE`. Both must come out as text, and what cannot be recovered must be reported rather
than invented.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pymupdf
import pytest

from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import DocumentBlockKind
from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.parsing.anchors import build_anchor, resolve_anchor, validate_anchor
from research_harness.parsing.base import (
    ParseTarget,
    diagnostics_summary,
    document_fingerprint,
)
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from tests.fixtures.make_synthetic_paper import (
    GROUND_TRUTH,
    build_publisher_quirks_paper,
    render,
)

QUIRKS = GROUND_TRUTH["synthetic_publisher_quirks"]
CIPHER = QUIRKS["cipher"]
#: A word this long is a run of words whose spaces were lost, not a word.
LOST_SPACES = re.compile(r"[A-Za-z]{26,}")


def make_target(path: Path) -> ParseTarget:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ParseTarget(
        work=WorkId("W0001"),
        version=VersionId("V0001-1"),
        artifact=ArtifactId("A0001-1"),
        file_hash=f"sha256:{digest}",
        path=path,
        mime_type="application/pdf",
    )


@pytest.fixture(scope="module")
def parser() -> PyMuPdfParser:
    return PyMuPdfParser()


@pytest.fixture(scope="module")
def paper(parser: PyMuPdfParser) -> ParsedDocument:
    return parser.parse(make_target(QUIRKS["path"]))


def one_block_containing(doc: ParsedDocument, needle: str) -> object:
    found = [block for block in doc.blocks if needle in block.text]
    assert found, f"no block contains {needle!r}"
    return found[0]


# -- the file really does carry both faults ------------------------------------------


def test_the_fixture_draws_no_space_in_the_justified_paragraph() -> None:
    """Without this the reconstruction test would pass on a file that never lost a space."""
    flags = pymupdf.TEXTFLAGS_RAWDICT | pymupdf.TEXT_INHIBIT_SPACES
    drawn = "".join(
        char["c"]
        for page in pymupdf.open(QUIRKS["path"])
        for block in page.get_text("rawdict", flags=flags)["blocks"]
        for line in block["lines"]
        for span in line["spans"]
        for char in span["chars"]
    )
    assert "Themajorlimitationof" in drawn
    assert CIPHER["literal"] in drawn, "the file must literally contain the displaced text"
    assert CIPHER["heading"] not in drawn, "and must not contain the recovered text"


# -- space reconstruction ------------------------------------------------------------


def test_a_paragraph_positioned_word_by_word_reads_as_a_sentence(paper: ParsedDocument) -> None:
    block = one_block_containing(paper, QUIRKS["justified"]["opening"])
    assert block.kind is DocumentBlockKind.PARAGRAPH
    assert block.page == QUIRKS["justified"]["page"]
    assert block.text == QUIRKS["justified"]["text"]


def test_no_block_of_the_document_runs_words_together(paper: ParsedDocument) -> None:
    offenders = [block.id for block in paper.blocks if LOST_SPACES.search(block.text)]
    assert offenders == []


# -- displaced-font recovery ---------------------------------------------------------


def test_a_displaced_font_is_recovered_into_its_real_headings(paper: ParsedDocument) -> None:
    headings = [block.text for block in paper.blocks if block.kind is DocumentBlockKind.SECTION]
    assert CIPHER["heading"] in headings
    assert CIPHER["subheading"] in headings
    assert "Service" in CIPHER["subheading"] and "Fingerprint" in CIPHER["subheading"]
    assert not any(CIPHER["literal"] in block.text for block in paper.blocks)


def test_the_recovered_body_text_is_the_text_the_author_wrote(paper: ParsedDocument) -> None:
    block = one_block_containing(paper, "service fingerprint of a session")
    assert block.text == CIPHER["body"]
    assert block.kind is DocumentBlockKind.PARAGRAPH


def test_a_recovered_heading_carries_the_blocks_after_it(paper: ParsedDocument) -> None:
    probe = QUIRKS["section_path_probe"]
    block = one_block_containing(paper, probe["contains"])
    assert block.section_path == probe["section_path"]


def test_every_heading_of_the_paper_is_found_in_order(paper: ParsedDocument) -> None:
    headings = [block.text for block in paper.blocks if block.kind is DocumentBlockKind.SECTION]
    assert headings == list(QUIRKS["headings"])


# -- what cannot be recovered ---------------------------------------------------------


def test_text_no_shift_recovers_keeps_its_raw_form_and_never_opens_a_section(
    paper: ParsedDocument,
) -> None:
    """Never fabricate: the block keeps exactly what was extracted, and stays out of the path."""
    block = one_block_containing(paper, QUIRKS["undecodable"]["text"])
    assert block.text == QUIRKS["undecodable"]["text"]
    assert block.kind is not DocumentBlockKind.SECTION
    assert block.section_path == QUIRKS["section_path_probe"]["section_path"]


def test_the_undecodable_block_is_reported_by_diagnostics(
    parser: PyMuPdfParser, paper: ParsedDocument
) -> None:
    diagnostics = parser.last_diagnostics
    assert diagnostics is not None and not diagnostics.is_clean
    undecodable = one_block_containing(paper, QUIRKS["undecodable"]["text"])
    assert diagnostics.undecodable_blocks == (undecodable.id,)
    assert diagnostics.suspected_shift == CIPHER["shift"]
    assert diagnostics.pages_with_issues == (QUIRKS["undecodable"]["page"],)
    assert any(CIPHER["font"] in note for note in diagnostics.notes)


def test_the_diagnostics_survive_in_the_document_itself(paper: ParsedDocument) -> None:
    """A parser object is not persisted; the document is, so the note has to carry them."""
    summary = diagnostics_summary(paper)
    assert summary == (
        f"1 block undecodable (font shift {CIPHER['shift']} recovered) "
        f"on page {QUIRKS['undecodable']['page']}"
    )


# -- the usual guarantees still hold --------------------------------------------------


def test_pages_and_geometry_are_recorded_as_for_any_other_paper(paper: ParsedDocument) -> None:
    assert paper.page_count == QUIRKS["page_count"]
    assert paper.parser_version == "1.1"
    for block in paper.blocks:
        assert 1 <= block.page <= paper.page_count
        assert block.bbox is not None
        x0, y0, x1, y1 = block.bbox.as_tuple()
        assert 0.0 <= x0 <= x1 <= 612.0
        assert 0.0 <= y0 <= y1 <= 792.0


def test_an_anchor_into_recovered_text_resolves_back_to_it(paper: ParsedDocument) -> None:
    """Recovered text is anchorable like any other: it is text, not a guess about text."""
    block = one_block_containing(paper, "service fingerprint of a session")
    start = block.text.index("service fingerprint")
    anchor = build_anchor(paper, block, start, start + len("service fingerprint"))
    assert validate_anchor(anchor, paper).is_valid
    assert resolve_anchor(anchor, paper).text == "service fingerprint"


def test_recovery_is_deterministic_and_regenerating_the_fixture_reproduces_it(
    tmp_path: Path,
) -> None:
    regenerated = tmp_path / QUIRKS["path"].name
    regenerated.write_bytes(render(build_publisher_quirks_paper()))
    assert regenerated.read_bytes() == QUIRKS["path"].read_bytes()
    first = PyMuPdfParser().parse(make_target(QUIRKS["path"]))
    second = PyMuPdfParser().parse(make_target(regenerated))
    assert document_fingerprint(first) == document_fingerprint(second)

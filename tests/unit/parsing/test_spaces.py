"""Geometric space reconstruction: the only rule that puts spaces into a parsed block.

The parser reads glyph boxes with the extractor's own space guessing switched off, so every
space in a block comes from the gap rule below. These tests drive it through real one-page
PDFs whose pen positions are chosen exactly, which is the only way to pin a geometric rule.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.parsing.base import ParseTarget
from research_harness.parsing.pymupdf_parser import _SPACE_GAP_RATIO, PyMuPdfParser

WORDS = ("The", "major", "limitation", "of", "existing", "solutions")
SENTENCE = " ".join(WORDS)
RUN_TOGETHER = "".join(WORDS)
SIZE = 10.0
FONT = "helv"


def positioned_pdf(path: Path, gap_em: float, *, baseline: float = 100.0) -> Path:
    """One line, one word per `insert_text` call, ``gap_em`` ems of empty space between."""
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    x = 60.0
    for word in WORDS:
        page.insert_text((x, baseline), word, fontsize=SIZE, fontname=FONT)
        x += pymupdf.get_text_length(word, fontname=FONT, fontsize=SIZE) + gap_em * SIZE
    document.save(path)
    document.close()
    return path


def parse(path: Path) -> str:
    target = ParseTarget(
        work=WorkId("W0001"),
        version=VersionId("V0001-1"),
        artifact=ArtifactId("A0001-1"),
        file_hash=f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        path=path,
        mime_type="application/pdf",
    )
    return " ".join(block.text for block in PyMuPdfParser().parse(target).blocks)


def drawn_glyphs(path: Path) -> str:
    """Only the glyphs the PDF actually draws: the extractor's own space guessing is off."""
    flags = pymupdf.TEXTFLAGS_RAWDICT | pymupdf.TEXT_INHIBIT_SPACES
    return "".join(
        char["c"]
        for page in pymupdf.open(path)
        for block in page.get_text("rawdict", flags=flags)["blocks"]
        for line in block["lines"]
        for span in line["spans"]
        for char in span["chars"]
    )


def test_a_line_with_no_space_glyph_is_put_back_together(tmp_path: Path) -> None:
    path = positioned_pdf(tmp_path / "justified.pdf", 0.30)
    assert drawn_glyphs(path) == RUN_TOGETHER, "the file must draw no space, or this proves nothing"
    assert SENTENCE in parse(path)


def test_gaps_narrower_than_the_threshold_are_kerning_and_not_spaces(tmp_path: Path) -> None:
    """Below the rule, glyphs belong to one word; a parser that split here would corrupt text."""
    path = positioned_pdf(tmp_path / "tight.pdf", _SPACE_GAP_RATIO / 2)
    assert RUN_TOGETHER in parse(path)


@pytest.mark.parametrize("gap_em", [0.18, 0.25, 0.4, 0.8])
def test_every_gap_above_the_threshold_becomes_exactly_one_space(
    tmp_path: Path, gap_em: float
) -> None:
    path = positioned_pdf(tmp_path / f"gap-{gap_em}.pdf", gap_em)
    assert SENTENCE in parse(path)


def test_a_real_space_glyph_still_yields_one_space(tmp_path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((60.0, 100.0), SENTENCE, fontsize=SIZE, fontname=FONT)
    path = tmp_path / "spaces.pdf"
    document.save(path)
    document.close()
    assert SENTENCE in parse(path)


def test_two_runs_on_one_baseline_are_read_as_one_line(tmp_path: Path) -> None:
    """A heading set as `2` then `RELATED WORK` is one line, and one line is one heading."""
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((60.0, 100.0), "2", fontsize=12.0, fontname="hebo")
    page.insert_text((77.0, 100.0), "RELATED WORK", fontsize=12.0, fontname="hebo")
    page.insert_text((60.0, 120.0), "2.1", fontsize=12.0, fontname="hebo")
    page.insert_text(
        (85.0, 120.0), "Encrypted Traffic Classification", fontsize=12.0, fontname="hebo"
    )
    page.insert_text(
        (60.0, 140.0),
        "Some studies suggest using unencrypted protocol field information.",
        fontsize=10.0,
        fontname="helv",
    )
    path = tmp_path / "headings.pdf"
    document.save(path)
    document.close()

    target = ParseTarget(
        work=WorkId("W0001"),
        version=VersionId("V0001-1"),
        artifact=ArtifactId("A0001-1"),
        file_hash=f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        path=path,
        mime_type="application/pdf",
    )
    parsed = PyMuPdfParser().parse(target)
    texts = [block.text for block in parsed.blocks]
    assert "2 RELATED WORK" in texts
    assert "2.1 Encrypted Traffic Classification" in texts
    body = next(block for block in parsed.blocks if block.text.startswith("Some studies"))
    assert body.section_path == ("2 RELATED WORK", "2.1 Encrypted Traffic Classification")

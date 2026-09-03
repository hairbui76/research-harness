"""Soft parse failures travel with the document: the provenance note is their storage.

`ParseError` ends a parse; `ParseDiagnostics` accompanies one that succeeded but whose text a
reviewer should not trust everywhere. Because the workspace persists documents and not the
parser object, the counts have to survive a round trip through `provenance.note`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from research_harness.domain.document import ParsedDocument
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId
from research_harness.parsing.base import (
    DIAGNOSTICS_NOTE_PREFIX,
    FILE_HASH_NOTE_PREFIX,
    BlockQuality,
    ParseDiagnostics,
    diagnostics_summary,
    document_diagnostics,
    parse_provenance,
)

FILE_HASH = "sha256:" + "ab" * 32
FIXED = datetime(2024, 1, 1, tzinfo=UTC)


def document(diagnostics: ParseDiagnostics | None) -> ParsedDocument:
    return ParsedDocument(
        work=WorkId("W0001"),
        version=VersionId("V0001-1"),
        artifact=ArtifactId("A0001-1"),
        file_hash=FILE_HASH,
        parser_name="pymupdf",
        parser_version="1.1",
        page_count=4,
        blocks=(),
        parsed_at=FIXED,
        created_at=FIXED,
        updated_at=FIXED,
        provenance=parse_provenance("pymupdf", "1.1", FILE_HASH, diagnostics),
    )


def test_block_quality_records_a_verdict_a_confidence_and_a_reason() -> None:
    quality = BlockQuality(decodable=False, confidence=0.9, reason="displaced font")
    assert not quality.decodable and quality.reason == "displaced font"
    with pytest.raises(ValueError, match="less than or equal to 1"):
        BlockQuality(decodable=True, confidence=1.5)


def test_a_clean_parse_is_clean_and_says_so() -> None:
    diagnostics = ParseDiagnostics()
    assert diagnostics.is_clean
    assert diagnostics.as_note() == "undecodable:0"
    assert diagnostics_summary(document(diagnostics)) == "no undecodable blocks"


def test_the_note_keeps_the_counts_the_shift_and_the_pages() -> None:
    diagnostics = ParseDiagnostics(
        undecodable_blocks=(BlockId("B0007"), BlockId("B0012")),
        suspected_shift=3,
        pages_with_issues=(1, 4),
        notes=("font 'Courier' on page 2 recovered with code-point offset 3",),
    )
    assert not diagnostics.is_clean
    assert diagnostics.as_note() == "undecodable:2;shift:3;pages:1,4"

    parsed = document(diagnostics)
    note = parsed.provenance.note or ""
    assert note.startswith(FILE_HASH_NOTE_PREFIX + FILE_HASH)
    assert DIAGNOSTICS_NOTE_PREFIX in note
    assert document_diagnostics(parsed) == {"undecodable": "2", "shift": "3", "pages": "1,4"}
    assert diagnostics_summary(parsed) == (
        "2 blocks undecodable (font shift 3 recovered) on pages 1, 4"
    )


def test_a_negative_shift_and_a_single_block_read_naturally() -> None:
    parsed = document(
        ParseDiagnostics(
            undecodable_blocks=(BlockId("B0013"),), suspected_shift=-3, pages_with_issues=(2,)
        )
    )
    assert diagnostics_summary(parsed) == "1 block undecodable (font shift -3 recovered) on page 2"


def test_a_document_parsed_before_diagnostics_existed_is_not_reported_as_clean() -> None:
    """Silence is not evidence of health: 1.0 wrote no diagnostics at all."""
    parsed = document(None)
    assert document_diagnostics(parsed) == {}
    assert diagnostics_summary(parsed) == "no parse diagnostics recorded"
    assert parsed.provenance.note == f"{FILE_HASH_NOTE_PREFIX}{FILE_HASH}"

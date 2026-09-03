"""Anchor construction, fingerprinting, validation, and resolution (ADR-002, ADR-008).

The invariants under test: changed artifact bytes make an anchor stale and stop the
check; renumbered blocks are reconciled only through an explicit validation result; and
nothing here ever rewrites an anchor.
"""

from __future__ import annotations

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.document import BoundingBox, DocumentBlock, ParsedDocument
from research_harness.domain.enums import DocumentBlockKind
from research_harness.domain.evidence import SourceAnchor
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId
from research_harness.parsing.anchors import (
    AnchorError,
    AnchorValidationStatus,
    anchor_fingerprint,
    build_anchor,
    resolve_anchor,
    validate_anchor,
)
from research_harness.parsing.base import parse_provenance
from research_harness.parsing.text import text_sha256

WORK = WorkId("W0017")
VERSION = VersionId("V0017-2")
ARTIFACT = ArtifactId("A0017-3")
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
DATASET_TEXT = "All experiments use CICIDS2017 with an F1 of 94.32 on the held-out split."
RESULT_TEXT = "Model | F1\nTrafficLM | 94.32"
F1_START = DATASET_TEXT.index("94.32")
F1_END = F1_START + len("94.32")


def make_block(
    number: int,
    text: str,
    *,
    page: int = 1,
    order: int = 0,
    kind: DocumentBlockKind = DocumentBlockKind.PARAGRAPH,
    section_path: tuple[str, ...] = ("3 Experiments", "3.1 Dataset"),
) -> DocumentBlock:
    """A parsed block with a real text hash, so hash comparisons are meaningful."""
    return DocumentBlock(
        id=BlockId.make(number),
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        kind=kind,
        page=page,
        order=order,
        text=text,
        text_hash=text_sha256(text),
        section_path=section_path,
        bbox=BoundingBox(x0=54.0, y0=136.0, x1=551.4, y1=189.3),
        provenance=Provenance.system(actor="pymupdf@1.0"),
    )


def make_document(
    *blocks: DocumentBlock,
    file_hash: str = HASH_A,
    page_count: int = 5,
) -> ParsedDocument:
    return ParsedDocument(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=file_hash,
        parser_name="pymupdf",
        parser_version="1.0",
        page_count=page_count,
        blocks=blocks,
        provenance=parse_provenance("pymupdf", "1.0", file_hash),
    )


@pytest.fixture
def document() -> ParsedDocument:
    return make_document(
        make_block(17, DATASET_TEXT, page=3, order=0),
        make_block(18, RESULT_TEXT, page=4, order=1, kind=DocumentBlockKind.TABLE),
    )


@pytest.fixture
def anchor(document: ParsedDocument) -> SourceAnchor:
    return build_anchor(document, document.blocks[0], F1_START, F1_END)


# -- construction --------------------------------------------------------------------


def test_build_anchor_copies_the_full_source_identity(
    document: ParsedDocument, anchor: SourceAnchor
) -> None:
    block = document.blocks[0]
    assert (anchor.work, anchor.version, anchor.artifact) == (WORK, VERSION, ARTIFACT)
    assert anchor.file_hash == HASH_A
    assert anchor.block == block.id
    assert anchor.text_hash == block.text_hash
    assert anchor.page == 3
    assert anchor.section_path == ("3 Experiments", "3.1 Dataset")
    assert anchor.bbox == block.bbox
    assert block.text[anchor.char_start : anchor.char_end] == "94.32"


def test_build_anchor_rejects_offsets_outside_the_block_text(document: ParsedDocument) -> None:
    with pytest.raises(AnchorError, match="exceeds block"):
        build_anchor(document, document.blocks[0], 10, len(DATASET_TEXT) + 1)
    with pytest.raises(AnchorError, match="invalid character span"):
        build_anchor(document, document.blocks[0], 20, 10)


def test_build_anchor_rejects_a_block_from_another_document(document: ParsedDocument) -> None:
    stranger = make_block(99, "a block nobody parsed here")
    with pytest.raises(AnchorError, match="does not belong"):
        build_anchor(document, stranger, 0, 1)


def test_build_anchor_takes_the_artifact_hash_from_the_document(
    document: ParsedDocument, anchor: SourceAnchor
) -> None:
    assert document.file_hash == HASH_A
    assert anchor.file_hash == document.file_hash
    assert build_anchor(document, document.blocks[0], 0, 3, file_hash=HASH_B).file_hash == HASH_B


# -- fingerprint ---------------------------------------------------------------------


def test_fingerprint_survives_a_model_dump_round_trip(anchor: SourceAnchor) -> None:
    restored = SourceAnchor.model_validate(anchor.model_dump())
    assert anchor_fingerprint(restored) == anchor_fingerprint(anchor)


def test_fingerprint_changes_with_bytes_offsets_and_geometry(anchor: SourceAnchor) -> None:
    baseline = anchor_fingerprint(anchor)
    assert anchor_fingerprint(anchor.touch(file_hash=HASH_B)) != baseline
    assert anchor_fingerprint(anchor.touch(char_start=0, char_end=5)) != baseline
    assert anchor_fingerprint(anchor.touch(page=4)) != baseline
    assert anchor_fingerprint(anchor.touch(bbox=None)) != baseline
    assert anchor_fingerprint(anchor.touch(block=BlockId("B0099"))) != baseline


# -- validation ----------------------------------------------------------------------


def test_an_unchanged_document_validates(document: ParsedDocument, anchor: SourceAnchor) -> None:
    result = validate_anchor(anchor, document)
    assert result.status is AnchorValidationStatus.VALID
    assert result.matched_block == anchor.block
    assert result.renumbered is False
    assert result.exact_text == "94.32"


def test_a_one_byte_artifact_change_makes_the_anchor_stale(anchor: SourceAnchor) -> None:
    """ADR-002: different bytes, different artifact hash, no reattachment attempt."""
    changed = make_document(*[make_block(17, DATASET_TEXT, page=3)], file_hash=HASH_B)
    result = validate_anchor(anchor, changed)
    assert result.status is AnchorValidationStatus.STALE
    assert "artifact bytes changed" in result.reason
    assert result.matched_block is None
    assert result.exact_text is None


def test_block_renumbering_reconciles_only_through_validation(anchor: SourceAnchor) -> None:
    """The same text under a new block id is reported, never silently rewritten."""
    reparsed = make_document(
        make_block(1, "a new front-matter block the old parse missed", page=3),
        make_block(2, DATASET_TEXT, page=3, order=1),
    )
    result = validate_anchor(anchor, reparsed)
    assert result.status is AnchorValidationStatus.VALID
    assert result.matched_block == BlockId("B0002")
    assert result.renumbered is True
    assert result.exact_text == "94.32"
    assert anchor.block == BlockId("B0017")


def test_text_that_moved_to_another_page_is_stale(anchor: SourceAnchor) -> None:
    moved = make_document(make_block(17, DATASET_TEXT, page=4))
    result = validate_anchor(anchor, moved)
    assert result.status is AnchorValidationStatus.STALE
    assert "page 4" in result.reason
    assert result.matched_block is None


def test_text_that_is_gone_is_stale(anchor: SourceAnchor) -> None:
    rewritten = make_document(make_block(17, "the paragraph was rewritten entirely", page=3))
    result = validate_anchor(anchor, rewritten)
    assert result.status is AnchorValidationStatus.STALE
    assert "text hash" in result.reason


def test_a_page_beyond_the_document_is_missing(anchor: SourceAnchor) -> None:
    shortened = make_document(make_block(17, DATASET_TEXT, page=1), page_count=2)
    result = validate_anchor(anchor, shortened)
    assert result.status is AnchorValidationStatus.MISSING
    assert "beyond" in result.reason


def test_an_anchor_for_another_artifact_is_stale(anchor: SourceAnchor) -> None:
    other = ParsedDocument(
        work=WORK,
        version=VERSION,
        artifact=ArtifactId("A0017-4"),
        file_hash=HASH_A,
        parser_name="pymupdf",
        parser_version="1.0",
        page_count=5,
        blocks=(),
        provenance=parse_provenance("pymupdf", "1.0", HASH_A),
    )
    result = validate_anchor(anchor, other)
    assert result.status is AnchorValidationStatus.STALE
    assert "artifact" in result.reason


def test_offsets_outside_a_matching_block_are_stale(document: ParsedDocument) -> None:
    block = document.blocks[0]
    overlong = SourceAnchor(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=HASH_A,
        block=block.id,
        text_hash=block.text_hash,
        page=3,
        char_start=0,
        char_end=len(block.text) + 40,
    )
    result = validate_anchor(overlong, document)
    assert result.status is AnchorValidationStatus.STALE
    assert "falls outside" in result.reason


def test_validation_can_take_the_artifact_hash_from_the_caller(
    document: ParsedDocument, anchor: SourceAnchor
) -> None:
    assert validate_anchor(anchor, document, file_hash=HASH_B).status is (
        AnchorValidationStatus.STALE
    )


# -- resolution ----------------------------------------------------------------------


def test_resolve_anchor_returns_the_exact_page_and_span(
    document: ParsedDocument, anchor: SourceAnchor
) -> None:
    span = resolve_anchor(anchor, document)
    assert span.page == 3
    assert span.text == "94.32"
    assert span.block == anchor.block
    assert span.bbox == document.blocks[0].bbox


def test_resolve_anchor_refuses_a_stale_anchor(anchor: SourceAnchor) -> None:
    changed = make_document(make_block(17, DATASET_TEXT, page=3), file_hash=HASH_B)
    with pytest.raises(AnchorError, match="stale"):
        resolve_anchor(anchor, changed)

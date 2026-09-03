"""Document IR: blocks, geometry, table cells, and parsed-document consistency."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_harness.domain import (
    ArtifactId,
    BlockId,
    BoundingBox,
    DocumentBlockKind,
    ParsedDocument,
    TableCell,
    VersionId,
    WorkId,
)
from tests.unit.domain import strategies as sty


def test_blocks_anchor_to_work_version_artifact_and_page() -> None:
    block = sty.make_block()
    assert (block.work, block.version, block.artifact) == ("W0017", "V0017-2", "A0017-3")
    assert block.page == 8
    assert block.section_path == ("Experiments", "Dataset")
    assert block.text_hash.startswith("sha256:")


def test_pages_are_one_based() -> None:
    with pytest.raises(ValidationError):
        sty.make_block(page=0)


def test_bounding_boxes_are_ordered() -> None:
    assert BoundingBox(x0=0, y0=0, x1=10, y1=10).as_tuple() == (0.0, 0.0, 10.0, 10.0)
    with pytest.raises(ValidationError, match="x1 >= x0"):
        BoundingBox(x0=10, y0=0, x1=0, y1=10)


def test_table_blocks_preserve_row_and_column_coordinates() -> None:
    table = sty.make_block(
        kind=DocumentBlockKind.TABLE,
        cells=(
            TableCell(row=0, col=0, text="Model"),
            TableCell(row=0, col=1, text="F1"),
            TableCell(row=1, col=1, text="94.32", bbox=BoundingBox(x0=1, y0=2, x1=3, y1=4)),
        ),
    )
    assert [(cell.row, cell.col) for cell in table.cells] == [(0, 0), (0, 1), (1, 1)]
    assert table.cells[2].bbox is not None


def test_only_table_blocks_carry_cells() -> None:
    with pytest.raises(ValidationError, match="table blocks"):
        sty.make_block(kind=DocumentBlockKind.PARAGRAPH, cells=(TableCell(row=0, col=0, text="x"),))


def test_blocks_carry_optional_caption_and_reference_metadata() -> None:
    caption = sty.make_block(
        kind=DocumentBlockKind.FIGURE_CAPTION,
        caption="Figure 3: architecture",
        caption_for=BlockId("B0080"),
    )
    reference = sty.make_block(
        kind=DocumentBlockKind.REFERENCE,
        reference_key="smith2026",
        reference_raw="Smith et al. 2026. A paper.",
    )
    assert caption.caption_for == "B0080"
    assert reference.reference_key == "smith2026"


def parsed(**overrides: object) -> ParsedDocument:
    fields: dict[str, object] = {
        "work": WorkId("W0017"),
        "version": VersionId("V0017-2"),
        "artifact": ArtifactId("A0017-3"),
        "file_hash": sty.HASH_A,
        "parser_name": "pymupdf",
        "parser_version": "1.24.0",
        "page_count": 12,
        "blocks": (sty.make_block(),),
        "provenance": sty.SYSTEM,
    }
    return ParsedDocument(**{**fields, **overrides})


def test_parsed_document_names_its_parser() -> None:
    document = parsed()
    assert (document.parser_name, document.parser_version) == ("pymupdf", "1.24.0")
    assert document.page_count == 12
    assert document.parsed_at.tzinfo is not None


def test_parsed_document_carries_the_identity_of_the_bytes_it_parsed() -> None:
    """Anchors replay against these three fields, so the IR names them itself."""
    document = parsed()
    assert (document.work, document.version, document.artifact) == (
        "W0017",
        "V0017-2",
        "A0017-3",
    )
    assert document.file_hash == sty.HASH_A


def test_parsed_document_requires_the_artifact_hash() -> None:
    fields = {
        "work": WorkId("W0017"),
        "version": VersionId("V0017-2"),
        "artifact": ArtifactId("A0017-3"),
        "parser_name": "pymupdf",
        "parser_version": "1.24.0",
        "page_count": 12,
        "provenance": sty.SYSTEM,
    }
    # `fields` is a plain dict of mixed value types, which is what makes the call a
    # missing-argument test rather than a typed construction.
    with pytest.raises(ValidationError, match="file_hash"):
        ParsedDocument(**fields)  # type: ignore[arg-type]


def test_parsed_document_blocks_belong_to_its_artifact() -> None:
    with pytest.raises(ValidationError, match="belongs to artifact"):
        parsed(blocks=(sty.make_block(artifact=ArtifactId("A0018-1")),))


def test_parsed_document_rejects_pages_beyond_the_page_count() -> None:
    with pytest.raises(ValidationError, match="page"):
        parsed(page_count=2)


def test_parsed_document_rejects_duplicate_block_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate block id"):
        parsed(blocks=(sty.make_block(), sty.make_block(order=13)))

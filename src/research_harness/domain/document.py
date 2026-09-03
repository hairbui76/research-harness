"""Structural document IR produced by parsers (Product 16).

Blocks preserve page, geometry, section path, and content hashes so an Evidence anchor
can be replayed - and detected as stale - after a re-parse or a new artifact revision.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from research_harness.domain.base import (
    CanonicalObject,
    DomainModel,
    NonEmptyStr,
    Sha256,
    TrackedObject,
    UtcDatetime,
    utc_now,
)
from research_harness.domain.enums import DocumentBlockKind
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId

__all__ = ["BoundingBox", "DocumentBlock", "ParsedDocument", "TableCell"]


class BoundingBox(DomainModel):
    """Page geometry in parser coordinates, origin at the top-left of the page."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _ordered(self) -> BoundingBox:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bounding box requires x1 >= x0 and y1 >= y0")
        return self

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Geometry as ``(x0, y0, x1, y1)``."""
        return (self.x0, self.y0, self.x1, self.y1)


class TableCell(DomainModel):
    """One table cell with its row/column coordinates (Product 16).

    Row/column structure is preserved because many technical claims are supported
    primarily by tabular results.
    """

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    text: str
    bbox: BoundingBox | None = None


class DocumentBlock(CanonicalObject):
    """A parsed section, paragraph, table, caption, equation, reference, or footnote.

    Blocks are regenerable parser output, but they carry a stable `BlockId` and
    provenance because evidence anchors point at them and must be replayable.
    """

    id: BlockId
    work: WorkId
    version: VersionId
    artifact: ArtifactId
    kind: DocumentBlockKind
    page: int = Field(ge=1)
    order: int = Field(ge=0)
    text: str
    text_hash: Sha256
    section_path: tuple[str, ...] = ()
    bbox: BoundingBox | None = None
    cells: tuple[TableCell, ...] = ()
    caption: str | None = None
    caption_for: BlockId | None = None
    reference_key: str | None = None
    reference_raw: str | None = None

    @model_validator(mode="after")
    def _cells_only_on_tables(self) -> DocumentBlock:
        if self.cells and self.kind is not DocumentBlockKind.TABLE:
            raise ValueError("only table blocks may carry table cells")
        return self


class ParsedDocument(TrackedObject):
    """The document IR for one artifact: identity, parser identity, and ordered blocks.

    ``file_hash`` is the hash of the artifact bytes this parse read, so an anchor can be
    replayed against the exact file it was accepted from without re-deriving the hash.
    """

    work: WorkId
    version: VersionId
    artifact: ArtifactId
    file_hash: Sha256
    parser_name: NonEmptyStr
    parser_version: NonEmptyStr
    page_count: int = Field(ge=0)
    blocks: tuple[DocumentBlock, ...] = ()
    parsed_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _blocks_belong_to_this_artifact(self) -> ParsedDocument:
        seen: set[BlockId] = set()
        for block in self.blocks:
            if block.artifact != self.artifact:
                raise ValueError(f"block {block.id} belongs to artifact {block.artifact}")
            if block.page > self.page_count:
                raise ValueError(f"block {block.id} is on page {block.page} of {self.page_count}")
            if block.id in seen:
                raise ValueError(f"duplicate block id {block.id}")
            seen.add(block.id)
        return self

"""PDF parser producing the structural document IR (Product 16, Roadmap Task 2.3).

Extraction is deliberately geometric and rule-based rather than model-driven: the same
bytes must always yield the same blocks, ids, and hashes, because evidence anchors are
replayed against them. Every heuristic below is a documented rule, not a tuned model, so
a wrong classification is reproducible and reviewable.

Reading order, per page:

* a page is treated as two-column when at least two text segments sit clearly left of the
  page midline, at least two sit clearly right of it, and none straddles it;
* on such a page, page-wide segments come first, then the whole left column, then the
  right column; on any other page, segments are read top to bottom, left to right.

Classification rules, in the order they are applied to a text segment:

* `SECTION` - section numbering (`3`, `3.1`), a known unnumbered heading name (Abstract,
  References, Acknowledgments, ...), or a short single line that is bold or larger than
  the body text and does not end a sentence. Numbering depth gives the heading level, so
  `section_path` is the stack of enclosing headings; a `SECTION` block's own path includes
  itself, every other block's path names the section it sits in.
* `REFERENCE` - one block per bibliography entry once a References heading is open.
  Entries split on `[n]` / `n.` markers, and a segment with no marker continues the
  previous entry, which is how hanging indents are rejoined.
* `FIGURE_CAPTION` / `TABLE_CAPTION` - a `Figure N:` or `Table N:` line. A table caption
  within 90 points of a detected table is attached to that table instead of becoming a
  block; a table caption with no table nearby becomes a `TABLE_CAPTION` block, so an
  orphaned caption is never filed as a figure's.
* `EQUATION` - an isolated `(n)` line, a short line ending in `(n)` that contains a
  relation symbol, or a short line that is at least half mathematical characters.
* `FOOTNOTE` - type smaller than the body in the bottom 15 percent of the page.
* `PARAGRAPH` - everything else.

Text inside a detected table's bounding box never becomes a paragraph: the table block
owns it, and evidence anchors reach a cell through `tables.cell_span`.

Version 1.1 - hardening against real publisher PDFs
---------------------------------------------------

Version 1.1 changes the text of blocks and may renumber them for bytes that 1.0 already
parsed, so it is a new parser version and anchors taken under 1.0 must be revalidated
(ADR-008). What changed:

* **Spaces are reconstructed geometrically.** Text is read as glyphs with their own boxes
  (`rawdict` with `TEXT_INHIBIT_SPACES`), and a space is written between two glyphs whose
  horizontal gap exceeds 0.15 of the font size. 1.0 asked the extractor for spaces and then
  dropped the whitespace-only spans it returned, so justified lines that encode inter-word
  gaps as positioning collapsed into `Themajorlimitationof`.
* **Same-baseline runs are one line.** A heading typeset as `2` + `RELATED WORK` arrives as
  two extractor lines on one baseline; they are merged before grouping, so the heading is a
  one-line segment again instead of a four-line paragraph.
* **Displaced fonts are detected and, when validated, recovered.** A subsetted font with no
  ToUnicode map returns raw character codes, so its text is the real text at a constant
  code-point offset (`VHUYLFH` for `SERVICE`). Per page and font, the offset that lifts that
  font's own words to plausible English is searched for and applied (`parsing.quality`);
  text that no offset recovers is kept exactly as extracted and never invented.
* **Headings must be readable.** Undecodable text, text smaller than the body, and lines
  that contain a sentence break (a bold run-in lead, not a heading) no longer open a
  section, so `section_path` falls back to the last heading that could actually be read.
  All-caps short lines and, in a narrow column, a bold two-line heading now do open one.
* **Soft failures are reported.** `PyMuPdfParser.last_diagnostics` and the parse provenance
  note carry a `ParseDiagnostics`; `parsing.diagnostics_summary` renders it for a CLI.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from statistics import median
from typing import Any, ClassVar

import pymupdf

from research_harness.domain.base import utc_now
from research_harness.domain.document import BoundingBox, DocumentBlock, ParsedDocument, TableCell
from research_harness.domain.enums import DocumentBlockKind
from research_harness.domain.ids import BlockId
from research_harness.parsing.base import (
    BlockIdAllocator,
    BlockQuality,
    DocumentParser,
    ParseDiagnostics,
    ParseError,
    ParseTarget,
    UnsupportedArtifactError,
    parse_provenance,
)
from research_harness.parsing.quality import (
    DECODABLE_SCORE,
    assess_text,
    detect_offset,
    english_score,
    shift_text,
    verify_offset,
)
from research_harness.parsing.tables import flatten_cells
from research_harness.parsing.text import normalize_text, text_sha256

# PyMuPDF prints a one-off recommendation to stdout from find_tables(); library code in
# this project never writes to stdout, so the recommendation is disabled at import.
# Every `type: ignore[no-untyped-call]` below is the same cause: PyMuPDF ships py.typed
# but leaves its own API unannotated, so mypy sees untyped calls into a typed module.
pymupdf.no_recommend_layout()  # type: ignore[no-untyped-call]

__all__ = ["PDF_MIME_TYPES", "PyMuPdfParser"]

PDF_MIME_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/acrobat"})

PARSER_NAME = "pymupdf"
PARSER_VERSION = "1.1"
"""Bump whenever extraction behaviour changes: anchors compare only within one version."""

_BOLD_FLAG = 1 << 4

#: Glyph boxes and raw character codes, with the extractor's own space guessing switched off
#: so the gap rule below is the only rule that inserts a space.
_TEXT_FLAGS = pymupdf.TEXTFLAGS_RAWDICT | pymupdf.TEXT_INHIBIT_SPACES

#: `2`, `3.1`, `4.2.1` followed by a title.
_NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")
_KNOWN_HEADINGS = frozenset(
    {
        "abstract",
        "acknowledgement",
        "acknowledgements",
        "acknowledgment",
        "acknowledgments",
        "appendix",
        "approach",
        "background",
        "bibliography",
        "conclusion",
        "conclusions",
        "discussion",
        "evaluation",
        "experiments",
        "experimental setup",
        "future work",
        "introduction",
        "limitations",
        "method",
        "methodology",
        "methods",
        "references",
        "related work",
        "results",
        "threats to validity",
    }
)
_REFERENCE_HEADINGS = frozenset({"references", "bibliography"})

#: A caption must carry an explicit delimiter after its number ("Table 1:", "Figure 2."),
#: so a paragraph opening with "Table 1 reports ..." is not mistaken for one.
_CAPTION = re.compile(
    r"^(?P<kind>Table|Figure|Fig\.|Algorithm)\s*(?P<number>\d+[a-z]?)\s*[:.\u2013\u2014]\s"
)
_REFERENCE_MARKER = re.compile(r"^\[(?P<bracket>[^\]]{1,16})\]\s*|^(?P<number>\d{1,3})\.\s")
_REFERENCE_SPLIT = re.compile(r"(?=\[[^\]]{1,16}\]\s)")
_EQUATION_TAG = re.compile(r"\(\d+\)\s*$")
_STANDALONE_TAG = re.compile(r"^\(\d+\)$")
_RELATION_CHARS = frozenset("=<>\u2264\u2265\u2248\u223c\u221d\u2260")
_MATH_CHARS = frozenset(
    "0123456789+-*/^_=<>|()[]{}"
    "\u03b1\u03b2\u03b3\u03b4\u03b8\u03bb\u03bc\u03c3\u03c0\u03c6\u03c8\u03c9"
    "\u0393\u0394\u0398\u039b\u039e\u03a0\u03a3\u03a6\u03a8\u03a9"
    "\u2211\u220f\u222b\u221a\u2264\u2265\u2248\u2260\u2208\u2200\u2203\u2202\u2207\u2212"
)

#: A bold lead-in that finishes a sentence and keeps going is body text, not a heading:
#: "Same-origin BURST Prediction. The importance of ..." must not open a section.
_RUN_IN_HEADING = re.compile(r"[a-z][.!?]\s+[A-Z(]")

_MAX_HEADING_CHARS = 120
_MAX_CAPS_HEADING_CHARS = 60
_MAX_EQUATION_CHARS = 200
_CAPTION_DISTANCE = 90.0
_FULL_WIDTH_RATIO = 0.6
_COLUMN_MARGIN_RATIO = 0.08
_TABLE_OVERLAP_RATIO = 0.5
_FOOTNOTE_SIZE_RATIO = 0.9
_FOOTNOTE_PAGE_RATIO = 0.85
#: A heading is never set smaller than the body text; figure and axis labels are.
_HEADING_SIZE_FLOOR = 0.95
#: Horizontal gap between two glyph boxes, as a fraction of the font size, that stands for a
#: space the PDF encoded as positioning rather than as a space glyph.
_SPACE_GAP_RATIO = 0.15
#: Two extractor lines are one visual line when their baselines agree within this fraction of
#: the font size and the second starts no further right than `_SAME_LINE_GAP` ems.
_BASELINE_TOLERANCE = 0.25
_SAME_LINE_GAP = 4.0
#: Diagnostic notes kept per parse, so a pathological document cannot grow the note without
#: bound; the counts in `ParseDiagnostics` stay exact either way.
_MAX_DIAGNOSTIC_NOTES = 20

Box = tuple[float, float, float, float]
FontKey = tuple[int, str]


@dataclass(frozen=True)
class _Segment:
    """One run of lines with consistent size and weight: a heading, paragraph, or caption."""

    page: int
    text: str
    bbox: Box
    max_size: float
    bold: bool
    line_count: int
    quality: BlockQuality
    narrow: bool


@dataclass(frozen=True)
class _RawTable:
    """A detected table with normalized cell text and per-cell geometry."""

    page: int
    bbox: Box
    cells: tuple[TableCell, ...]


@dataclass
class _Item:
    """A placed page element awaiting reading-order sorting and classification."""

    page: int
    bbox: Box
    segment: _Segment | None = None
    table: _RawTable | None = None

    @property
    def is_text(self) -> bool:
        return self.segment is not None


@dataclass
class _Emission:
    """A block-to-be, before ids and reading-order indices are allocated."""

    kind: DocumentBlockKind
    page: int
    text: str
    bbox: Box | None
    section_path: tuple[str, ...]
    quality: BlockQuality
    cells: tuple[TableCell, ...] = ()
    caption: str | None = None
    reference_key: str | None = None
    reference_raw: str | None = None


def _box(raw: Sequence[float]) -> Box:
    return (
        round(float(raw[0]), 2),
        round(float(raw[1]), 2),
        round(float(raw[2]), 2),
        round(float(raw[3]), 2),
    )


def _bbox_model(bbox: Box) -> BoundingBox:
    return BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3])


def _center_x(bbox: Box) -> float:
    return (bbox[0] + bbox[2]) / 2


def _area(bbox: Box) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _overlap(inner: Box, outer: Box) -> float:
    """Fraction of ``inner`` covered by ``outer``."""
    width = min(inner[2], outer[2]) - max(inner[0], outer[0])
    height = min(inner[3], outer[3]) - max(inner[1], outer[1])
    if width <= 0 or height <= 0:
        return 0.0
    area = _area(inner)
    return (width * height) / area if area else 0.0


def _union(boxes: Iterable[Box]) -> Box:
    items = list(boxes)
    return (
        min(box[0] for box in items),
        min(box[1] for box in items),
        max(box[2] for box in items),
        max(box[3] for box in items),
    )


def _math_ratio(text: str) -> float:
    dense = [char for char in text if not char.isspace()]
    if not dense:
        return 0.0
    return sum(1 for char in dense if char in _MATH_CHARS) / len(dense)


def _heading_level(text: str) -> int:
    """Depth from section numbering (`3` -> 1, `3.1` -> 2); unnumbered headings are level 1."""
    match = re.match(r"^(\d+(?:\.\d+)*)", text)
    return len(match.group(1).split(".")) if match else 1


def _heading_key(text: str) -> str:
    return text.strip().rstrip(":.").strip().lower()


class PyMuPdfParser(DocumentParser):
    """Rule-based PDF parser: pages, sections, paragraphs, tables, captions, equations, refs.

    The optional ``clock`` exists so tests can pin `parsed_at`; block content never depends
    on it.
    """

    name: ClassVar[str] = PARSER_NAME
    version: ClassVar[str] = PARSER_VERSION

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock
        self._last_diagnostics: ParseDiagnostics | None = None

    @property
    def last_diagnostics(self) -> ParseDiagnostics | None:
        """Soft failures of the most recent `parse`, or None before the first one.

        A convenience for a caller holding the parser; the same facts travel with the
        document itself in its provenance note, so nothing depends on reading this in time.
        """
        return self._last_diagnostics

    def supports(self, mime_type: str) -> bool:
        """True for PDF media types, ignoring any parameters after ``;``."""
        return mime_type.split(";")[0].strip().lower() in PDF_MIME_TYPES

    def parse(self, target: ParseTarget) -> ParsedDocument:
        """Read the artifact and return its document IR; never writes, never partially returns."""
        if not self.supports(target.mime_type):
            raise UnsupportedArtifactError(
                f"{PARSER_NAME} cannot parse mime type {target.mime_type!r}"
            )
        if not target.path.is_file():
            raise ParseError(f"artifact file not found: {target.path}")
        self._last_diagnostics = None
        try:
            page_count, emissions, recoveries = self._read(target)
        except ParseError:
            raise
        except Exception as exc:  # PyMuPDF signals every corruption as a plain exception
            raise ParseError(f"failed to parse {target.path}: {exc}") from exc
        return self._assemble(target, page_count, emissions, recoveries)

    # -- reading -------------------------------------------------------------

    def _read(self, target: ParseTarget) -> tuple[int, list[_Emission], dict[FontKey, int]]:
        with pymupdf.open(target.path) as document:  # type: ignore[no-untyped-call]
            if document.is_encrypted and document.needs_pass:
                raise ParseError(f"artifact is password protected: {target.path}")
            page_count = int(document.page_count)
            raw_pages: list[tuple[int, Box, list[list[_Line]], list[_RawTable]]] = []
            for index in range(page_count):
                page = document[index]
                number = index + 1
                rect = _box((page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1))
                tables = self._read_tables(page, number)
                raw_pages.append((number, rect, _read_page_lines(page), tables))
        recoveries = _font_offsets(raw_pages)

        pages: list[tuple[Box, list[_Item]]] = []
        sizes: list[tuple[float, int]] = []
        for number, rect, blocks, tables in raw_pages:
            lines = [
                [_recover_line(line, number, recoveries) for line in block] for block in blocks
            ]
            segments = _build_segments(number, rect, lines, tables, sizes)
            items = [_Item(page=number, bbox=segment.bbox, segment=segment) for segment in segments]
            items.extend(_Item(page=number, bbox=table.bbox, table=table) for table in tables)
            pages.append((rect, items))

        body_size = _body_size(sizes)
        emissions: list[_Emission] = []
        state = _DocumentState()
        for rect, items in pages:
            ordered = _order_page(items, rect)
            captions = _match_table_captions(ordered)
            for item in ordered:
                self._classify(item, rect, body_size, captions, state, emissions)
        state.flush(emissions)
        return page_count, emissions, recoveries

    def _read_tables(self, page: pymupdf.Page, number: int) -> list[_RawTable]:
        tables: list[_RawTable] = []
        for found in page.find_tables().tables:  # type: ignore[no-untyped-call]
            rows: list[list[str | None]] = [list(row) for row in found.extract()]
            boxes: list[list[Any]] = [list(row.cells) for row in found.rows]
            header = getattr(found, "header", None)
            if header is not None and getattr(header, "external", False) and header.names:
                rows.insert(0, list(header.names))
                boxes.insert(0, list(header.cells))
            cells: list[TableCell] = []
            for row_index, row in enumerate(rows):
                row_boxes = boxes[row_index] if row_index < len(boxes) else []
                for col_index, value in enumerate(row):
                    raw_box = row_boxes[col_index] if col_index < len(row_boxes) else None
                    cells.append(
                        TableCell(
                            row=row_index,
                            col=col_index,
                            text=normalize_text(value or ""),
                            bbox=None if raw_box is None else _bbox_model(_box(raw_box)),
                        )
                    )
            if cells:
                tables.append(_RawTable(page=number, bbox=_box(found.bbox), cells=tuple(cells)))
        return tables

    # -- classification ------------------------------------------------------

    def _classify(
        self,
        item: _Item,
        rect: Box,
        body_size: float,
        captions: dict[int, _Segment],
        state: _DocumentState,
        emissions: list[_Emission],
    ) -> None:
        if item.table is not None:
            state.flush(emissions)
            caption = captions.get(id(item.table))
            text = flatten_cells(item.table.cells)
            emissions.append(
                _Emission(
                    kind=DocumentBlockKind.TABLE,
                    page=item.page,
                    text=text,
                    bbox=item.table.bbox,
                    section_path=state.section_path,
                    quality=assess_text(text),
                    cells=item.table.cells,
                    caption=None if caption is None else caption.text,
                )
            )
            return
        segment = item.segment
        if segment is None:
            return
        if any(consumed is segment for consumed in captions.values()):
            return
        if _is_heading(segment, body_size):
            state.flush(emissions)
            state.push_heading(segment.text)
            emissions.append(
                _Emission(
                    kind=DocumentBlockKind.SECTION,
                    page=segment.page,
                    text=segment.text,
                    bbox=segment.bbox,
                    section_path=state.section_path,
                    quality=segment.quality,
                )
            )
            return
        if state.in_references:
            state.add_reference(segment)
            return
        emissions.append(
            _Emission(
                kind=_text_kind(segment, rect, body_size),
                page=segment.page,
                text=segment.text,
                bbox=segment.bbox,
                section_path=state.section_path,
                quality=segment.quality,
                caption=segment.text if _CAPTION.match(segment.text) else None,
            )
        )

    # -- assembly ------------------------------------------------------------

    def _assemble(
        self,
        target: ParseTarget,
        page_count: int,
        emissions: Sequence[_Emission],
        recoveries: dict[FontKey, int],
    ) -> ParsedDocument:
        allocator = BlockIdAllocator()
        ids = [allocator.allocate() for _ in emissions]
        diagnostics = _diagnostics(ids, emissions, recoveries)
        provenance = parse_provenance(PARSER_NAME, PARSER_VERSION, target.file_hash, diagnostics)
        self._last_diagnostics = diagnostics
        now = self._clock()
        blocks: list[DocumentBlock] = []
        for order, emission in enumerate(emissions):
            blocks.append(
                DocumentBlock(
                    id=ids[order],
                    work=target.work,
                    version=target.version,
                    artifact=target.artifact,
                    kind=emission.kind,
                    page=emission.page,
                    order=order,
                    text=emission.text,
                    text_hash=text_sha256(emission.text),
                    section_path=emission.section_path,
                    bbox=None if emission.bbox is None else _bbox_model(emission.bbox),
                    cells=emission.cells,
                    caption=emission.caption,
                    reference_key=emission.reference_key,
                    reference_raw=emission.reference_raw,
                    created_at=now,
                    updated_at=now,
                    provenance=provenance,
                )
            )
        return ParsedDocument(
            work=target.work,
            version=target.version,
            artifact=target.artifact,
            file_hash=target.file_hash,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            page_count=page_count,
            blocks=tuple(blocks),
            parsed_at=now,
            created_at=now,
            updated_at=now,
            provenance=provenance,
        )


@dataclass(frozen=True)
class _Span:
    """One run of glyphs in a single font, with the spaces the geometry implies restored.

    ``space_before`` records that the gap to the previous span of the same line is wide
    enough to be a space; it is kept apart from ``text`` because recovering a displaced font
    rewrites the text of a span but never its position.
    """

    font: str
    size: float
    bold: bool
    text: str
    space_before: bool


@dataclass(frozen=True)
class _Line:
    """One visual line of text: its spans, its box, and the baseline they were drawn on."""

    spans: tuple[_Span, ...]
    bbox: Box
    baseline: float

    @property
    def text(self) -> str:
        return "".join((" " if span.space_before else "") + span.text for span in self.spans)

    @property
    def visible(self) -> tuple[_Span, ...]:
        return tuple(span for span in self.spans if span.text.strip())

    @property
    def size(self) -> float:
        spans = self.visible or self.spans
        return round(max(span.size for span in spans), 1)

    @property
    def bold(self) -> bool:
        spans = self.visible or self.spans
        weighted = sum(len(span.text) for span in spans if span.bold)
        return weighted * 2 >= sum(len(span.text) for span in spans)


def _read_page_lines(page: pymupdf.Page) -> list[list[_Line]]:
    """Every text block of one page as visual lines, spaces restored from glyph geometry."""
    blocks: list[list[_Line]] = []
    for raw in page.get_text("rawdict", flags=_TEXT_FLAGS)["blocks"]:  # type: ignore[no-untyped-call]
        if raw.get("type") != 0:
            continue
        lines = [line for line in (_read_line(item) for item in raw["lines"]) if line is not None]
        merged = _merge_baseline_runs(lines)
        if merged:
            blocks.append(merged)
    return blocks


def _read_line(raw: dict[str, Any]) -> _Line | None:
    """Rebuild one extractor line, writing a space wherever the glyphs leave room for one.

    The rule is the only source of spaces: a gap wider than `_SPACE_GAP_RATIO` of the font
    size between two glyph boxes is an inter-word gap the PDF encoded as positioning. It is
    applied only to left-to-right lines, because for any other writing direction the
    horizontal distance between glyph boxes does not mean what it means here.
    """
    horizontal = tuple(round(float(value), 3) for value in raw.get("dir", (1.0, 0.0))) == (
        1.0,
        0.0,
    )
    spans: list[_Span] = []
    previous: dict[str, Any] | None = None
    previous_size = 0.0
    for raw_span in raw["spans"]:
        size = float(raw_span["size"])
        pieces: list[str] = []
        space_before = False
        for index, char in enumerate(raw_span["chars"]):
            if horizontal and previous is not None and _is_gap(previous, char, previous_size, size):
                if index:
                    pieces.append(" ")
                else:
                    space_before = True
            pieces.append(str(char["c"]))
            previous, previous_size = char, size
        text = "".join(pieces)
        if not text:
            continue
        spans.append(
            _Span(
                font=str(raw_span.get("font", "")),
                size=round(size, 1),
                bold=_is_bold(raw_span),
                text=text,
                space_before=space_before and bool(spans),
            )
        )
    if not any(span.text.strip() for span in spans):
        return None
    origins = [float(raw_span["origin"][1]) for raw_span in raw["spans"] if raw_span["chars"]]
    return _Line(
        spans=tuple(spans),
        bbox=_box(raw["bbox"]),
        baseline=round(max(origins), 2) if origins else _box(raw["bbox"])[3],
    )


def _is_gap(previous: dict[str, Any], char: dict[str, Any], left: float, right: float) -> bool:
    """True when two consecutive glyph boxes are far enough apart to stand for a space."""
    if str(previous["c"]).isspace() or str(char["c"]).isspace():
        return False
    gap = float(char["bbox"][0]) - float(previous["bbox"][2])
    return gap > _SPACE_GAP_RATIO * max(left, right, 1.0)


def _merge_baseline_runs(lines: Sequence[_Line]) -> list[_Line]:
    """Join extractor lines that share a baseline: they are one line split by a wide gap.

    Publishers set a heading as `2` and `RELATED WORK` at two pen positions on one baseline;
    left unmerged they look like two lines of a four-line paragraph and no heading is found.
    """
    merged: list[_Line] = []
    for line in lines:
        previous = merged[-1] if merged else None
        if previous is None or not _same_visual_line(previous, line):
            merged.append(line)
            continue
        size = max(previous.size, line.size, 1.0)
        gap = line.bbox[0] - previous.bbox[2]
        spans = list(line.spans)
        spans[0] = replace(spans[0], space_before=gap > _SPACE_GAP_RATIO * size)
        merged[-1] = _Line(
            spans=previous.spans + tuple(spans),
            bbox=_union((previous.bbox, line.bbox)),
            baseline=previous.baseline,
        )
    return merged


def _same_visual_line(left: _Line, right: _Line) -> bool:
    """True when ``right`` continues ``left``: same baseline, to its right, and close by."""
    size = max(left.size, right.size, 1.0)
    if abs(left.baseline - right.baseline) > _BASELINE_TOLERANCE * size:
        return False
    gap = right.bbox[0] - left.bbox[2]
    return 0.0 <= gap <= _SAME_LINE_GAP * size


def _is_bold(span: dict[str, Any]) -> bool:
    if int(span.get("flags", 0)) & _BOLD_FLAG:
        return True
    name = str(span.get("font", "")).lower()
    return "bold" in name or "black" in name or "heavy" in name


def _font_offsets(
    pages: Sequence[tuple[int, Box, list[list[_Line]], list[_RawTable]]],
) -> dict[FontKey, int]:
    """The code-point offset that recovers each displaced font, keyed by page and font name.

    Fonts are page resources, and one name can stand for two differently subsetted fonts in
    one document, so the offset is fitted per page. A page whose sample is too small to fit
    an offset against borrows one already validated for the same font name elsewhere, and
    only keeps it if it reads here too - the offset is never re-fitted from too little text.
    """
    samples: dict[FontKey, list[str]] = {}
    for number, _rect, blocks, _tables in pages:
        for block in blocks:
            for line in block:
                for span in line.spans:
                    if span.text.strip():
                        samples.setdefault((number, span.font), []).append(span.text)
    offsets: dict[FontKey, int] = {}
    for key in sorted(samples):
        offset = detect_offset(samples[key])
        if offset is not None:
            offsets[key] = offset
    by_font: dict[str, list[int]] = {}
    for (_page, font), offset in offsets.items():
        by_font.setdefault(font, []).append(offset)
    for key in sorted(samples):
        if key in offsets:
            continue
        text = "\n".join(samples[key])
        if english_score(text) >= DECODABLE_SCORE:
            continue
        for offset in sorted(set(by_font.get(key[1], [])), key=lambda value: (abs(value), value)):
            if verify_offset(samples[key], offset):
                offsets[key] = offset
                break
    return offsets


def _recover_line(line: _Line, page: int, offsets: dict[FontKey, int]) -> _Line:
    """Apply each font's validated offset to that font's spans; leave every other span alone."""
    if not offsets:
        return line
    spans = tuple(
        span
        if (page, span.font) not in offsets
        else replace(span, text=shift_text(span.text, offsets[(page, span.font)]))
        for span in line.spans
    )
    if spans == line.spans:
        return line
    return _Line(spans=spans, bbox=line.bbox, baseline=line.baseline)


def _build_segments(
    number: int,
    rect: Box,
    blocks: Sequence[Sequence[_Line]],
    tables: Sequence[_RawTable],
    sizes: list[tuple[float, int]],
) -> list[_Segment]:
    """Group one page's lines into segments, recording the font sizes seen on the way."""
    segments: list[_Segment] = []
    full_width = _FULL_WIDTH_RATIO * (rect[2] - rect[0])
    for lines in blocks:
        for line in lines:
            sizes.append((line.size, len(line.text)))
        for group in _group_lines(lines):
            bbox = _union(line.bbox for line in group)
            if any(_overlap(bbox, table.bbox) >= _TABLE_OVERLAP_RATIO for table in tables):
                continue
            text = normalize_text("\n".join(line.text for line in group))
            if not text:
                continue
            segments.append(
                _Segment(
                    page=number,
                    text=text,
                    bbox=bbox,
                    max_size=max(line.size for line in group),
                    bold=sum(1 for line in group if line.bold) * 2 >= len(group),
                    line_count=len(group),
                    quality=assess_text(text),
                    narrow=(bbox[2] - bbox[0]) < full_width,
                )
            )
    return segments


def _group_lines(lines: Sequence[_Line]) -> list[list[_Line]]:
    """Split a PDF text block where size, weight, vertical spacing, or numbering changes."""
    groups: list[list[_Line]] = []
    for line in lines:
        if not groups:
            groups.append([line])
            continue
        previous = groups[-1][-1]
        height = max(previous.bbox[3] - previous.bbox[1], line.bbox[3] - line.bbox[1], 1.0)
        changed = (
            abs(previous.size - line.size) > 0.6
            or previous.bold != line.bold
            or line.bbox[1] - previous.bbox[3] > 0.8 * height
            # A bold line that opens its own section number starts a new segment, so two
            # consecutive headings set tight together stay two headings.
            or (line.bold and _NUMBERED_HEADING.match(line.text) is not None)
        )
        if changed:
            groups.append([line])
        else:
            groups[-1].append(line)
    return groups


def _diagnostics(
    ids: Sequence[BlockId],
    emissions: Sequence[_Emission],
    recoveries: dict[FontKey, int],
) -> ParseDiagnostics:
    """Collect the soft failures of one parse: what stayed unreadable, and what was recovered."""
    undecodable = tuple(
        block_id
        for block_id, emission in zip(ids, emissions, strict=True)
        if not emission.quality.decodable
    )
    pages = {emission.page for emission in emissions if not emission.quality.decodable}
    pages.update(page for page, _font in recoveries)
    counts: dict[int, int] = {}
    for offset in recoveries.values():
        counts[offset] = counts.get(offset, 0) + 1
    suspected = (
        max(counts, key=lambda offset: (counts[offset], -abs(offset), -offset)) if counts else None
    )
    notes = [
        f"font {font!r} on page {page} recovered with code-point offset {offset}"
        for (page, font), offset in sorted(recoveries.items())
    ]
    if undecodable:
        notes.append(f"{len(undecodable)} blocks kept their raw text: no offset recovered them")
    if len(notes) > _MAX_DIAGNOSTIC_NOTES:
        hidden = len(notes) - _MAX_DIAGNOSTIC_NOTES + 1
        notes = [*notes[: _MAX_DIAGNOSTIC_NOTES - 1], f"and {hidden} further notes"]
    return ParseDiagnostics(
        undecodable_blocks=tuple(undecodable),
        suspected_shift=suspected,
        pages_with_issues=tuple(sorted(pages)),
        notes=tuple(notes),
    )


def _body_size(sizes: Sequence[tuple[float, int]]) -> float:
    """Character-weighted median font size: the document's body text size."""
    weighted = [size for size, count in sizes for _ in range(max(1, count // 8))]
    return float(median(weighted)) if weighted else 10.0


def _order_page(items: Sequence[_Item], rect: Box) -> list[_Item]:
    """Reading order for one page; see the module docstring for the column rule."""
    width = rect[2] - rect[0]
    mid = (rect[0] + rect[2]) / 2
    margin = _COLUMN_MARGIN_RATIO * width
    full_width = _FULL_WIDTH_RATIO * width

    def spans_page(item: _Item) -> bool:
        return (item.bbox[2] - item.bbox[0]) >= full_width

    columnar = [item for item in items if item.is_text and not spans_page(item)]
    left = sum(1 for item in columnar if _center_x(item.bbox) < mid - margin)
    right = sum(1 for item in columnar if _center_x(item.bbox) > mid + margin)
    straddling = sum(
        1 for item in columnar if item.bbox[0] < mid - margin and item.bbox[2] > mid + margin
    )
    if not (left >= 2 and right >= 2 and straddling == 0):
        return sorted(items, key=lambda item: (item.bbox[1], item.bbox[0]))

    def key(item: _Item) -> tuple[int, float, float]:
        column = -1 if spans_page(item) else (0 if _center_x(item.bbox) < mid else 1)
        return (column, item.bbox[1], item.bbox[0])

    return sorted(items, key=key)


def _match_table_captions(items: Sequence[_Item]) -> dict[int, _Segment]:
    """Map each table (by identity) to the nearest ``Table N`` line above or below it."""
    tables = [item.table for item in items if item.table is not None]
    captions = [
        item.segment
        for item in items
        if item.segment is not None and _caption_kind(item.segment.text) == "table"
    ]
    matched: dict[int, _Segment] = {}
    used: set[int] = set()
    for table in tables:
        best: _Segment | None = None
        best_distance = _CAPTION_DISTANCE
        for caption in captions:
            if id(caption) in used:
                continue
            distance = min(
                abs(table.bbox[1] - caption.bbox[3]), abs(caption.bbox[1] - table.bbox[3])
            )
            if distance < best_distance:
                best, best_distance = caption, distance
        if best is not None:
            matched[id(table)] = best
            used.add(id(best))
    return matched


def _caption_kind(text: str) -> str | None:
    match = _CAPTION.match(text)
    if match is None:
        return None
    return "table" if match.group("kind").lower().startswith("table") else "figure"


def _is_heading(segment: _Segment, body_size: float) -> bool:
    """Numbering, a known section name, an all-caps line, or a short prominent line.

    Text the parser could not decode never opens a section: a displaced font would otherwise
    push nonsense onto the heading stack and every block after it would inherit that as its
    `section_path`, which is worse than having no heading at all (Product 16, ADR-008).
    """
    text = segment.text
    if not text or len(text) > _MAX_HEADING_CHARS or not segment.quality.decodable:
        return False
    if _heading_key(text) in _KNOWN_HEADINGS:
        return True
    if segment.line_count > 2 or text.endswith((".", ",", ";", ":")):
        return False
    if _RUN_IN_HEADING.search(text):
        return False
    if segment.max_size < body_size * _HEADING_SIZE_FLOOR:
        # Figure, axis, and legend labels are set below the body size; headings are not.
        return False
    if segment.line_count == 1:
        if _NUMBERED_HEADING.match(text):
            return True
        if text.isupper() and len(text) <= _MAX_CAPS_HEADING_CHARS:
            return True
        return (segment.bold or segment.max_size > body_size * 1.1) and len(text) <= 90
    # Two-column papers set headings in the body font and distinguish them only by weight,
    # and inside a narrow column such a heading wraps; a bold two-line segment that neither
    # ends nor contains a sentence is one of those.
    return segment.bold and segment.narrow and len(text) <= 90


def _is_equation(segment: _Segment) -> bool:
    """A numbered formula line, or a short line that is mostly mathematics."""
    text = segment.text
    if _STANDALONE_TAG.match(text):
        return True
    if segment.line_count > 2 or len(text) > _MAX_EQUATION_CHARS:
        return False
    if _EQUATION_TAG.search(text) and any(char in _RELATION_CHARS for char in text):
        return True
    return len(text) <= 120 and _math_ratio(text) >= 0.5


def _is_footnote(segment: _Segment, rect: Box, body_size: float) -> bool:
    """Small type in the bottom band of the page."""
    height = rect[3] - rect[1]
    return (
        segment.max_size < body_size * _FOOTNOTE_SIZE_RATIO
        and segment.bbox[3] > rect[1] + height * _FOOTNOTE_PAGE_RATIO
    )


def _text_kind(segment: _Segment, rect: Box, body_size: float) -> DocumentBlockKind:
    caption = _caption_kind(segment.text)
    if caption is not None:
        # A matched table caption is consumed by its table, so one reaching here is an
        # orphan and keeps its own kind rather than being filed under figures.
        return (
            DocumentBlockKind.TABLE_CAPTION
            if caption == "table"
            else DocumentBlockKind.FIGURE_CAPTION
        )
    if _is_equation(segment):
        return DocumentBlockKind.EQUATION
    if _is_footnote(segment, rect, body_size):
        return DocumentBlockKind.FOOTNOTE
    return DocumentBlockKind.PARAGRAPH


@dataclass
class _ReferenceEntry:
    """One bibliography entry, possibly spread over several hanging-indent segments."""

    page: int
    key: str | None
    parts: list[str]
    boxes: list[Box]

    @property
    def text(self) -> str:
        return " ".join(self.parts).strip()


class _DocumentState:
    """Heading stack and reference buffer carried across the page sequence."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []
        self.in_references = False
        self._entries: list[_ReferenceEntry] = []

    @property
    def section_path(self) -> tuple[str, ...]:
        return tuple(text for _, text in self._stack)

    def push_heading(self, text: str) -> None:
        level = _heading_level(text)
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))
        self.in_references = _heading_key(text) in _REFERENCE_HEADINGS

    def add_reference(self, segment: _Segment) -> None:
        for part in _REFERENCE_SPLIT.split(segment.text):
            chunk = part.strip()
            if not chunk:
                continue
            match = _REFERENCE_MARKER.match(chunk)
            if match is None and self._entries:
                self._entries[-1].parts.append(chunk)
                self._entries[-1].boxes.append(segment.bbox)
                continue
            key = None
            if match is not None:
                key = match.group("bracket") or match.group("number")
            self._entries.append(
                _ReferenceEntry(page=segment.page, key=key, parts=[chunk], boxes=[segment.bbox])
            )

    def flush(self, emissions: list[_Emission]) -> None:
        """Emit buffered bibliography entries as REFERENCE blocks, in order."""
        for entry in self._entries:
            emissions.append(
                _Emission(
                    kind=DocumentBlockKind.REFERENCE,
                    page=entry.page,
                    text=entry.text,
                    bbox=_union(entry.boxes),
                    section_path=self.section_path,
                    quality=assess_text(entry.text),
                    reference_key=entry.key,
                    reference_raw=entry.text,
                )
            )
        self._entries = []

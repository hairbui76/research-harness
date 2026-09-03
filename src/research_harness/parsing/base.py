"""Parser abstraction: what a parser is given, what it must return, and how it may fail.

Parsing is a pure function of the artifact bytes (Product 16, ADR-002): a parser reads a
file, returns a `ParsedDocument`, and writes nothing. Failure raises `ParseError` and
leaves no state behind, so a broken PDF can never mutate accepted scientific state.

Real publisher PDFs also fail *softly*: a subsetted font with no ToUnicode map yields text
that is displaced rather than wrong, and a justified line can lose the spaces between its
words. Those never justify refusing the document, but they must never pass silently either
(Product 43, "parser instability"). `BlockQuality` records the verdict on one block's text
and `ParseDiagnostics` the whole run's, which the parser both exposes as
`last_diagnostics` and folds into the parse provenance note so the workspace keeps it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from pydantic import Field

from research_harness.domain.base import DomainModel, Provenance, Sha256
from research_harness.domain.document import ParsedDocument
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId
from research_harness.parsing.text import text_sha256

__all__ = [
    "DIAGNOSTICS_NOTE_PREFIX",
    "FILE_HASH_NOTE_PREFIX",
    "BlockIdAllocator",
    "BlockQuality",
    "DocumentParser",
    "ParseDiagnostics",
    "ParseError",
    "ParseTarget",
    "UnsupportedArtifactError",
    "diagnostics_summary",
    "document_diagnostics",
    "document_file_hash",
    "document_fingerprint",
    "parse_provenance",
    "select_parser",
]


class ParseError(ResearchHarnessError):
    """An artifact could not be parsed. Raised instead of returning a partial document."""


class UnsupportedArtifactError(ParseError):
    """No parser handles this artifact's media type."""


class ParseTarget(DomainModel):
    """The one artifact a parse run is about: its identity, its bytes, and its location."""

    work: WorkId
    version: VersionId
    artifact: ArtifactId
    file_hash: Sha256
    path: Path
    mime_type: str


class BlockQuality(DomainModel):
    """Whether one block's extracted text is readable, how sure of that, and why not.

    `decodable` is the parser's verdict on the *characters*, not on the writing: a table of
    numbers or a line of Chinese is decodable, a span drawn by a font whose code points are
    displaced is not. `confidence` is confidence in the verdict itself, so a block with too
    little text to judge is reported decodable at confidence 0 rather than condemned.
    """

    decodable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class ParseDiagnostics(DomainModel):
    """The soft failures of one parse run: what could not be read, and what was recovered.

    Distinct from `ParseError`, which ends a parse. Diagnostics accompany a document that
    was produced successfully but whose text a reviewer should not trust everywhere.
    """

    undecodable_blocks: tuple[BlockId, ...] = ()
    suspected_shift: int | None = None
    pages_with_issues: tuple[int, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        """True when every block of the parse read as text."""
        return not self.undecodable_blocks and self.suspected_shift is None

    def as_note(self) -> str:
        """Compact provenance form: ``undecodable:12;shift:3;pages:1,4``."""
        parts = [f"undecodable:{len(self.undecodable_blocks)}"]
        if self.suspected_shift is not None:
            parts.append(f"shift:{self.suspected_shift}")
        if self.pages_with_issues:
            parts.append("pages:" + ",".join(str(page) for page in self.pages_with_issues))
        return ";".join(parts)


#: `ParsedDocument.file_hash` now carries the artifact hash, so this prefix is only the
#: legacy provenance-note form kept for documents written before that field existed.
FILE_HASH_NOTE_PREFIX = "file_hash="

#: Second field of a parse provenance note; see `ParseDiagnostics.as_note`.
DIAGNOSTICS_NOTE_PREFIX = "diagnostics="


def parse_provenance(
    parser_name: str,
    parser_version: str,
    file_hash: Sha256,
    diagnostics: ParseDiagnostics | None = None,
) -> Provenance:
    """Provenance for a parse run: a deterministic system action by one parser version.

    ``diagnostics`` is folded into the note so a persisted document still says how much of
    its text the parser could read; omitting it records no diagnostics at all, which is how
    a document parsed before diagnostics existed is told apart from a clean one.
    """
    note = f"{FILE_HASH_NOTE_PREFIX}{file_hash}"
    if diagnostics is not None:
        note = f"{note} {DIAGNOSTICS_NOTE_PREFIX}{diagnostics.as_note()}"
    return Provenance.system(
        actor=f"{parser_name}@{parser_version}",
        workflow="parse",
        note=note,
    )


def document_diagnostics(doc: ParsedDocument) -> dict[str, str]:
    """The ``diagnostics=`` fields of a parse provenance note, as raw key -> value strings.

    The parse writes one provenance onto the document *and* onto every block it produced,
    so a document rebuilt from stored blocks (`WorkspaceRepository.get_parsed_document`)
    still answers: its own provenance is the workspace's replay note, and the diagnostics
    are read off the blocks instead. That is what lets `research work show` report a parse
    it did not run (dogfood F6).

    Empty when the document was parsed before diagnostics were recorded; a caller must not
    read that as "clean", which is why `diagnostics_summary` reports the two differently.
    """
    notes = [doc.provenance.note or ""]
    notes.extend(block.provenance.note or "" for block in doc.blocks[:1])
    for note in notes:
        fields = _diagnostics_fields(note)
        if fields:
            return fields
    return {}


def _diagnostics_fields(note: str) -> dict[str, str]:
    """Parse one ``diagnostics=`` note; an unmarked note carries none."""
    marker = note.find(DIAGNOSTICS_NOTE_PREFIX)
    if marker < 0:
        return {}
    fields: dict[str, str] = {}
    for part in note[marker + len(DIAGNOSTICS_NOTE_PREFIX) :].split(";"):
        key, separator, value = part.partition(":")
        if separator and key:
            fields[key] = value
    return fields


def diagnostics_summary(doc: ParsedDocument) -> str:
    """One line a CLI can print: ``12 blocks undecodable (font shift 3 recovered)``."""
    fields = document_diagnostics(doc)
    if not fields:
        return "no parse diagnostics recorded"
    undecodable = fields.get("undecodable", "0")
    shift = fields.get("shift")
    pages = fields.get("pages")
    if undecodable == "0" and shift is None:
        return "no undecodable blocks"
    plural = "" if undecodable == "1" else "s"
    summary = f"{undecodable} block{plural} undecodable"
    if shift is not None:
        summary += f" (font shift {shift} recovered)"
    if pages:
        summary += f" on page{'' if ',' not in pages else 's'} {pages.replace(',', ', ')}"
    return summary


def document_file_hash(doc: ParsedDocument) -> Sha256:
    """The artifact hash this document was parsed from: `doc.file_hash`."""
    return doc.file_hash


def document_fingerprint(doc: ParsedDocument) -> Sha256:
    """Content hash of a parse: parser identity plus every block, ignoring timestamps.

    Two parses of identical bytes by identical parser versions must share a fingerprint;
    it is the cheap determinism check and a safe cache key for regenerable projections.
    """
    parts: list[str] = [doc.parser_name, doc.parser_version, str(doc.page_count), str(doc.artifact)]
    for block in doc.blocks:
        parts.extend(
            [
                str(block.id),
                block.kind.value,
                str(block.page),
                str(block.order),
                block.text_hash,
                "\x1f".join(block.section_path),
                "" if block.bbox is None else repr(block.bbox.as_tuple()),
                block.caption or "",
                block.reference_key or "",
                "\x1f".join(f"{cell.row}:{cell.col}:{cell.text}" for cell in block.cells),
            ]
        )
    return text_sha256("\x1e".join(parts))


class BlockIdAllocator:
    """Hands out `B####` ids in reading order, starting at 1.

    Ids are positional on purpose: identical bytes parsed by an identical parser version
    yield identical ids, and a parser change may renumber them, which is exactly the case
    anchor validation must reconcile explicitly (ADR-008).
    """

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def allocate(self) -> BlockId:
        """Next block id in reading order."""
        block_id = BlockId.make(self._next)
        self._next += 1
        return block_id


class DocumentParser(ABC):
    """Contract every artifact parser implements.

    `name` and `version` identify the parser in `ParsedDocument`; changing extraction
    behaviour requires bumping `version`, because anchors are only comparable within one
    parser version.
    """

    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def supports(self, mime_type: str) -> bool:
        """True when this parser handles ``mime_type``."""

    @abstractmethod
    def parse(self, target: ParseTarget) -> ParsedDocument:
        """Parse the artifact at ``target.path``; never writes, raises `ParseError` on failure."""


def select_parser(parsers: Iterable[DocumentParser], mime_type: str) -> DocumentParser:
    """First parser that supports ``mime_type``; raises `UnsupportedArtifactError` otherwise."""
    for parser in parsers:
        if parser.supports(mime_type):
            return parser
    raise UnsupportedArtifactError(f"no parser supports mime type {mime_type!r}")

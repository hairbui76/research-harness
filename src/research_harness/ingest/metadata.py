"""Best-effort bibliographic inspection of a local PDF (Product 13, 16; Roadmap 2.1).

Extraction is heuristic, so nothing here invents a value: an unreadable field stays
``None`` and every field that *is* extracted keeps the provenance source and an
extraction note saying where it came from, which is what the identity resolver and the
researcher need in order to trust or override it.

Two of those rules are answers to what a real corpus did to this module (dogfood F4, F6):

* **Undecodable text is not metadata.** A publisher font with a broken ToUnicode CMap
  hands back displaced character codes, and `parsing.quality.assess_text` can say so. A
  title or an author list that fails that test is left ``None`` with a
  ``decodability:low`` note rather than written into the corpus as mojibake, so external
  metadata can fill the gap instead of colliding with garbage.
* **An arXiv banner's date is not a publication year.** `arXiv:2301.01234v3 [cs.CR] 12
  Mar 2025` is a 2023 paper whose third version was stamped in 2025; the year comes from
  the identifier's `YYMM`, never from the date beside it.
"""

from __future__ import annotations

import datetime
import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from research_harness.domain.base import DomainModel, NonEmptyStr, Provenance
from research_harness.domain.enums import ProvenanceSource
from research_harness.domain.errors import IngestError
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.ingest.hashing import ArtifactFingerprint
from research_harness.ingest.identity import arxiv_base_id, arxiv_version_label, arxiv_year
from research_harness.parsing.quality import assess_text

__all__ = [
    "ARXIV_ID_PATTERN",
    "DOI_PATTERN",
    "INGEST_ACTOR",
    "NOTE_ARXIV_BANNER",
    "NOTE_DECODABILITY_LOW",
    "NOTE_PAGE1_AFTER_TITLE",
    "NOTE_PAGE1_LARGEST_FONT",
    "NOTE_PAGE1_REGEX",
    "NOTE_PDF_METADATA_AUTHOR",
    "NOTE_PDF_METADATA_DATE",
    "NOTE_PDF_METADATA_TITLE",
    "ArxivBanner",
    "FieldNote",
    "PdfInspection",
    "build_work_candidate",
    "find_arxiv_banner",
    "find_arxiv_id",
    "find_doi",
    "find_year",
    "inspect_pdf",
    "inspect_pdf_detail",
]

logger = logging.getLogger(__name__)

INGEST_ACTOR = "ingest"

NOTE_PDF_METADATA_TITLE = "pdf_metadata:title"
NOTE_PDF_METADATA_AUTHOR = "pdf_metadata:author"
NOTE_PDF_METADATA_DATE = "pdf_metadata:creation_date"
NOTE_PAGE1_LARGEST_FONT = "page1:largest_font"
NOTE_PAGE1_AFTER_TITLE = "page1:after_title"
NOTE_PAGE1_REGEX = "page1:regex"
NOTE_ARXIV_BANNER = "page1:arxiv_banner"
NOTE_DECODABILITY_LOW = "decodability:low"

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
ARXIV_ID_PATTERN = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?")
_ARXIV_LABELLED = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
#: The stamp arXiv prints down the left margin of every page of a hosted PDF:
#: ``arXiv:2301.01234v3  [cs.CR]  12 Mar 2025``. The category and the date are optional
#: because a cross-listed or withdrawn paper prints neither.
_ARXIV_BANNER = re.compile(
    r"arXiv:\s*(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z-]*(?:\.[a-z]{2})?/\d{7}(?:v\d+)?)"
    r"(?:\s*\[(?P<category>[^\]\n]{1,40})\])?"
    r"(?:\s*(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3,9})\.?\s+(?P<year>\d{4}))?",
    re.IGNORECASE,
)
_MONTHS: dict[str, int] = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_ARXIV_MENTION = re.compile(r"arxiv", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"\b(1[4-9]\d{2}|2[01]\d{2})\b")
_PDF_DATE_YEAR = re.compile(r"^\s*(?:D\s*:)?\s*(\d{4})")
_ABSTRACT_LINE = re.compile(r"^\s*abstract\b", re.IGNORECASE)
_AFFILIATION_MARKS = re.compile(r"[\d*†‡§¶¹²³]+")
_AUTHOR_SEPARATORS = re.compile(r",|;|&|\band\b", re.IGNORECASE)
#: A semicolon-separated list uses commas inside names ("Roe, Jane Q.; Doe, John").
_AUTHOR_SEPARATORS_SEMICOLON = re.compile(r";|&|\band\b", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:'\")]}>"

#: Fraction of the page height inside which a title line is still "near the top".
TITLE_TOP_FRACTION = 0.5
#: How close two font sizes must be (in points) to count as the same title run.
FONT_SIZE_TOLERANCE = 0.1
#: How many lines after the title may be scanned for an author list.
MAX_AUTHOR_LINES = 3
#: Characters either side of an "arXiv" mention searched for a bare identifier.
ARXIV_WINDOW = 120
#: Plausible publication years, matching the bounds `Work.year` accepts.
MIN_YEAR = 1400
MAX_YEAR = 2200

_CONFIDENCE_PDF_METADATA = 0.8
_CONFIDENCE_PDF_DATE = 0.7
_CONFIDENCE_PAGE_TITLE = 0.6
_CONFIDENCE_PAGE_REGEX = 0.9
_CONFIDENCE_PAGE_HEURISTIC = 0.4


class FieldNote(DomainModel):
    """Where one extracted metadata field came from.

    ``IdentifierField.note`` now carries the same string on the value itself; this
    per-field index is kept so a caller can ask for a note by field name without walking
    the metadata tree.
    """

    field: NonEmptyStr
    note: NonEmptyStr


class PdfInspection(DomainModel):
    """Candidate metadata plus one extraction note per populated field."""

    metadata: CandidateMetadata = CandidateMetadata()
    notes: tuple[FieldNote, ...] = ()

    def note_for(self, field: str) -> str | None:
        """Extraction note recorded for ``field``, or ``None`` when it was not extracted."""
        for entry in self.notes:
            if entry.field == field:
                return entry.note
        return None


class ArxivBanner(DomainModel):
    """The stamp arXiv prints down the margin of a hosted PDF, parsed into its parts.

    ``year`` is read from the identifier's `YYMM`, not from ``submitted``: a v3 stamped in
    2025 is still a 2023 paper, and taking the banner's date as the publication year is
    what put one into the corpus two years late (dogfood F4).
    """

    identifier: NonEmptyStr
    """The id exactly as printed, version suffix kept: `2301.01234v3`."""
    base_id: NonEmptyStr
    """The same id without its `vN` suffix: the Work's identifier (ADR-002)."""
    version: str | None = None
    primary_category: str | None = None
    submitted: datetime.date | None = None
    """The date beside the id: when *this version* was stamped, not when the work appeared."""
    year: int | None = None
    """Publication year decoded from the identifier's `YYMM`."""


@dataclass(frozen=True)
class _Line:
    """One extracted text line with the largest font size it uses."""

    text: str
    size: float
    top: float


def inspect_pdf(path: Path | str) -> CandidateMetadata:
    """Read best-effort bibliographic metadata out of a PDF; missing fields stay ``None``.

    Raises :class:`IngestError` when ``path`` is not a readable PDF.
    """
    return inspect_pdf_detail(path).metadata


def inspect_pdf_detail(path: Path | str) -> PdfInspection:
    """Like :func:`inspect_pdf`, but also reports where each extracted field came from."""
    file_path = Path(path)
    try:
        # PyMuPDF ships `py.typed` but leaves `Document`/`Page` members unannotated.
        with pymupdf.open(file_path) as document:  # type: ignore[no-untyped-call]
            raw = {key: str(value or "") for key, value in (document.metadata or {}).items()}
            lines, page_height, page_text = _first_page(document)
    except Exception as exc:  # PyMuPDF reports a non-PDF or a corrupt file as a plain error
        raise IngestError(f"cannot inspect {file_path} as a PDF: {exc}") from exc

    notes: list[FieldNote] = []
    title_block = _largest_font_block(lines, page_height)
    title = _screened_title(_title(raw, title_block, notes), notes)
    authors = _screened_authors(_authors(raw, lines, title_block, notes), notes)
    identifiers = _identifiers(page_text, notes)
    year = _year(raw, page_text, notes)

    metadata = CandidateMetadata(
        title=title,
        authors=authors,
        year=year,
        identifiers=identifiers,
    )
    return PdfInspection(metadata=metadata, notes=tuple(notes))


def build_work_candidate(
    path: Path | str,
    fingerprint: ArtifactFingerprint,
    metadata: CandidateMetadata,
    *,
    provenance: Provenance | None = None,
    source_query: str | None = None,
) -> WorkCandidate:
    """Stage one ingested file as a candidate; it carries no research ID until resolved."""
    file_path = Path(path)
    return WorkCandidate(
        provenance=provenance
        or Provenance.system(actor=INGEST_ACTOR, note=f"local file ingest: {file_path.name}"),
        metadata=metadata,
        candidate_file_hash=fingerprint.sha256,
        original_filename=fingerprint.original_filename,
        source_query=source_query,
    )


# -- identifier extraction ---------------------------------------------------


def find_doi(text: str) -> str | None:
    """First DOI in ``text`` with sentence punctuation trimmed off the end."""
    match = DOI_PATTERN.search(text)
    if match is None:
        return None
    return _strip_trailing_punctuation(match.group(0)) or None


def find_arxiv_id(text: str) -> str | None:
    """arXiv identifier, preferring a labelled ``arXiv:`` form over a bare id near one."""
    labelled = _ARXIV_LABELLED.search(text)
    if labelled is not None:
        return labelled.group(1)
    for mention in _ARXIV_MENTION.finditer(text):
        start = max(0, mention.start() - ARXIV_WINDOW)
        window = text[start : mention.end() + ARXIV_WINDOW]
        bare = ARXIV_ID_PATTERN.search(window)
        if bare is not None:
            return bare.group(0)
    return None


def find_arxiv_banner(text: str) -> ArxivBanner | None:
    """Parse the `arXiv:<id>v<n> [<category>] <date>` margin stamp, or ``None``.

    Only the identifier is required; a cross-listed or withdrawn paper prints no category
    and no date. The publication year always comes from the id, never from the date.
    """
    match = _ARXIV_BANNER.search(text)
    if match is None:
        return None
    raw = match.group("id")
    base = arxiv_base_id(raw)
    if base is None:  # pragma: no cover - the pattern only matches well-formed ids
        return None
    return ArxivBanner(
        identifier=raw.casefold(),
        base_id=base,
        version=arxiv_version_label(raw),
        primary_category=(match.group("category") or "").strip() or None,
        submitted=_banner_date(match),
        year=arxiv_year(raw),
    )


def _banner_date(match: re.Match[str]) -> datetime.date | None:
    """The banner's stamp date, or ``None`` when it printed none or an impossible one."""
    day, month, year = match.group("day"), match.group("month"), match.group("year")
    if not (day and month and year):
        return None
    number = _MONTHS.get(month.casefold())
    if number is None:
        return None
    try:
        return datetime.date(int(year), number, int(day))
    except ValueError:
        logger.debug("arXiv banner carries an impossible date: %s %s %s", day, month, year)
        return None


def find_year(text: str) -> int | None:
    """Latest plausible 4-digit year in ``text``, ignoring digits inside DOIs and arXiv ids."""
    cleaned = ARXIV_ID_PATTERN.sub(" ", DOI_PATTERN.sub(" ", text))
    years = [int(match.group(0)) for match in _YEAR_PATTERN.finditer(cleaned)]
    return max(years) if years else None


# -- page-one heuristics -----------------------------------------------------


def _first_page(document: pymupdf.Document) -> tuple[tuple[_Line, ...], float, str]:
    if document.page_count == 0:
        return (), 0.0, ""
    page = document[0]
    text: str = str(page.get_text())  # type: ignore[no-untyped-call]  # untyped PyMuPDF
    return _text_lines(page), float(page.rect.height), text


def _text_lines(page: pymupdf.Page) -> tuple[_Line, ...]:
    lines: list[_Line] = []
    page_dict = page.get_text("dict")  # type: ignore[no-untyped-call]  # untyped PyMuPDF
    blocks = page_dict.get("blocks", [])
    for block in blocks:
        if block.get("type", 0) != 0:  # 0 is a text block; 1 is an image
            continue
        for line in block.get("lines", ()):
            spans = line.get("spans", ())
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if not text or not spans:
                continue
            lines.append(
                _Line(
                    text=text,
                    size=max(float(span.get("size", 0.0)) for span in spans),
                    top=float(line["bbox"][1]),
                )
            )
    lines.sort(key=lambda item: (item.top, item.text))
    return tuple(lines)


def _largest_font_block(lines: Sequence[_Line], page_height: float) -> tuple[str, int] | None:
    """Text of the largest-font run near the top of page one, and the line after it."""
    limit = page_height * TITLE_TOP_FRACTION
    upper = [index for index, line in enumerate(lines) if line.top <= limit]
    if not upper:
        return None
    largest = max(lines[index].size for index in upper)
    start = next(
        index for index in upper if abs(lines[index].size - largest) <= FONT_SIZE_TOLERANCE
    )
    end = start
    while end < len(lines) and abs(lines[end].size - largest) <= FONT_SIZE_TOLERANCE:
        end += 1
    text = " ".join(lines[index].text for index in range(start, end)).strip()
    return (text, end) if text else None


def _title(
    raw: dict[str, str], title_block: tuple[str, int] | None, notes: list[FieldNote]
) -> IdentifierField | None:
    embedded = raw.get("title", "").strip()
    if embedded:
        notes.append(FieldNote(field="title", note=NOTE_PDF_METADATA_TITLE))
        return IdentifierField(
            value=embedded,
            source=ProvenanceSource.EXTERNAL_METADATA,
            confidence=_CONFIDENCE_PDF_METADATA,
            note=NOTE_PDF_METADATA_TITLE,
        )
    if title_block is None:
        return None
    notes.append(FieldNote(field="title", note=NOTE_PAGE1_LARGEST_FONT))
    return IdentifierField(
        value=title_block[0],
        source=ProvenanceSource.SYSTEM,
        confidence=_CONFIDENCE_PAGE_TITLE,
        note=NOTE_PAGE1_LARGEST_FONT,
    )


def _authors(
    raw: dict[str, str],
    lines: Sequence[_Line],
    title_block: tuple[str, int] | None,
    notes: list[FieldNote],
) -> tuple[IdentifierField, ...]:
    embedded = _split_authors(raw.get("author", ""))
    if embedded:
        notes.append(FieldNote(field="authors", note=NOTE_PDF_METADATA_AUTHOR))
        return tuple(
            IdentifierField(
                value=name,
                source=ProvenanceSource.EXTERNAL_METADATA,
                confidence=_CONFIDENCE_PDF_METADATA,
                note=NOTE_PDF_METADATA_AUTHOR,
            )
            for name in embedded
        )
    if title_block is None:
        return ()
    names = _authors_after_title(lines, title_block[1])
    if not names:
        return ()
    notes.append(FieldNote(field="authors", note=NOTE_PAGE1_AFTER_TITLE))
    return tuple(
        IdentifierField(
            value=name,
            source=ProvenanceSource.SYSTEM,
            confidence=_CONFIDENCE_PAGE_HEURISTIC,
            note=NOTE_PAGE1_AFTER_TITLE,
        )
        for name in names
    )


def _readable(text: str) -> bool:
    """True when `parsing.quality` reads this text as language rather than displaced codes."""
    return assess_text(text).decodable


def _screened_title(
    title: IdentifierField | None, notes: list[FieldNote]
) -> IdentifierField | None:
    """Drop a title the font never let the extractor read, and say so (dogfood F6)."""
    if title is None or _readable(title.value):
        return title
    logger.info("dropping an undecodable extracted title: %r", title.value)
    _record_note(notes, "title", NOTE_DECODABILITY_LOW)
    return None


def _screened_authors(
    authors: tuple[IdentifierField, ...], notes: list[FieldNote]
) -> tuple[IdentifierField, ...]:
    """Drop the whole author list when any name is undecodable.

    The list is one field: a run of names in which one is displaced was read off the same
    broken font as the rest, and a half-trustworthy author list is worse than none, because
    discovery can fill an empty one and cannot safely correct a populated one.
    """
    if not authors or all(_readable(field.value) for field in authors):
        return authors
    logger.info("dropping an undecodable extracted author list of %d name(s)", len(authors))
    _record_note(notes, "authors", NOTE_DECODABILITY_LOW)
    return ()


def _record_note(notes: list[FieldNote], field: str, note: str) -> None:
    """Set ``field``'s extraction note, replacing whatever was recorded for it."""
    replacement = FieldNote(field=field, note=note)
    for index, entry in enumerate(notes):
        if entry.field == field:
            notes[index] = replacement
            return
    notes.append(replacement)


def _authors_after_title(lines: Sequence[_Line], start: int) -> tuple[str, ...]:
    names: list[str] = []
    for line in lines[start : start + MAX_AUTHOR_LINES]:
        if _ABSTRACT_LINE.match(line.text):
            break
        found = _split_authors(line.text)
        if found:
            names.extend(found)
        elif names:
            break
    return tuple(dict.fromkeys(names))


def _split_authors(text: str) -> tuple[str, ...]:
    if not text.strip() or "@" in text or "http" in text.casefold():
        return ()
    if DOI_PATTERN.search(text) or _ARXIV_MENTION.search(text):
        return ()
    separator = _AUTHOR_SEPARATORS_SEMICOLON if ";" in text else _AUTHOR_SEPARATORS
    names: list[str] = []
    for part in separator.split(text):
        name = _AFFILIATION_MARKS.sub("", part).strip(" ,·-")
        if len(name) < 2 or not any(char.isalpha() for char in name):
            continue
        names.append(unicodedata.normalize("NFC", name))
    return tuple(dict.fromkeys(names))


def _identifiers(page_text: str, notes: list[FieldNote]) -> WorkIdentifiers:
    doi = find_doi(page_text)
    arxiv = find_arxiv_id(page_text)
    if doi is not None:
        notes.append(FieldNote(field="identifiers.doi", note=NOTE_PAGE1_REGEX))
    if arxiv is not None:
        notes.append(FieldNote(field="identifiers.arxiv", note=NOTE_PAGE1_REGEX))
    return WorkIdentifiers(
        doi=_page_field(doi, _CONFIDENCE_PAGE_REGEX, NOTE_PAGE1_REGEX),
        arxiv=_page_field(arxiv, _CONFIDENCE_PAGE_REGEX, NOTE_PAGE1_REGEX),
    )


def _year(raw: dict[str, str], page_text: str, notes: list[FieldNote]) -> IdentifierField | None:
    banner = find_arxiv_banner(page_text)
    if banner is not None and banner.year is not None:
        # The banner's own date belongs to whichever version this file is; the id does not
        # move between versions, so it is the only year on the page that cannot drift.
        notes.append(FieldNote(field="year", note=NOTE_ARXIV_BANNER))
        return IdentifierField(
            value=str(banner.year),
            source=ProvenanceSource.SYSTEM,
            confidence=_CONFIDENCE_PAGE_REGEX,
            note=NOTE_ARXIV_BANNER,
        )
    embedded = _year_from_pdf_date(raw.get("creationDate", ""))
    if embedded is not None:
        notes.append(FieldNote(field="year", note=NOTE_PDF_METADATA_DATE))
        return IdentifierField(
            value=str(embedded),
            source=ProvenanceSource.EXTERNAL_METADATA,
            confidence=_CONFIDENCE_PDF_DATE,
            note=NOTE_PDF_METADATA_DATE,
        )
    found = find_year(page_text)
    if found is None:
        return None
    notes.append(FieldNote(field="year", note=NOTE_PAGE1_REGEX))
    return IdentifierField(
        value=str(found),
        source=ProvenanceSource.SYSTEM,
        confidence=_CONFIDENCE_PAGE_HEURISTIC,
        note=NOTE_PAGE1_REGEX,
    )


def _year_from_pdf_date(value: str) -> int | None:
    match = _PDF_DATE_YEAR.match(value)
    if match is None:
        return None
    year = int(match.group(1))
    return year if MIN_YEAR <= year <= MAX_YEAR else None


def _page_field(value: str | None, confidence: float, note: str) -> IdentifierField | None:
    if value is None:
        return None
    return IdentifierField(
        value=value, source=ProvenanceSource.SYSTEM, confidence=confidence, note=note
    )


def _strip_trailing_punctuation(value: str) -> str:
    """Trim sentence punctuation a DOI picked up from running text, keeping balanced parens."""
    while value and value[-1] in _TRAILING_PUNCTUATION:
        if value[-1] == ")" and value.count("(") >= value.count(")"):
            break
        value = value[:-1]
    return value

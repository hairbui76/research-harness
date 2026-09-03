"""PDF metadata inspection: heuristic, provenance-carrying, and never inventive."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pymupdf
import pytest

from research_harness.domain.enums import IdentityResolutionOutcome, ProvenanceSource
from research_harness.domain.errors import IngestError
from research_harness.domain.work import CandidateMetadata
from research_harness.ingest.hashing import fingerprint_file
from research_harness.ingest.metadata import (
    INGEST_ACTOR,
    NOTE_ARXIV_BANNER,
    NOTE_DECODABILITY_LOW,
    NOTE_PAGE1_AFTER_TITLE,
    NOTE_PAGE1_LARGEST_FONT,
    NOTE_PAGE1_REGEX,
    NOTE_PDF_METADATA_AUTHOR,
    NOTE_PDF_METADATA_DATE,
    NOTE_PDF_METADATA_TITLE,
    build_work_candidate,
    find_arxiv_banner,
    find_arxiv_id,
    find_doi,
    find_year,
    inspect_pdf,
    inspect_pdf_detail,
)
from tests.fixtures.make_synthetic_paper import CIPHER_SHIFT, caesar

TITLE_SIZE = 20.0
AUTHOR_SIZE = 11.0
BODY_SIZE = 9.0

PAPER_LINES: tuple[tuple[str, float], ...] = (
    ("Neural Scaling Laws for Dense Retrieval", TITLE_SIZE),
    ("Jane Q. Roe, John Doe and Ada Lovelace", AUTHOR_SIZE),
    ("arXiv:2401.01234v2  [cs.CL]  3 Jan 2024", BODY_SIZE),
    ("Published 2019. doi:10.1145/1234567.1234568.", BODY_SIZE),
    ("Abstract", AUTHOR_SIZE),
    ("Retrieval quality scales with corpus size.", BODY_SIZE),
)

#: The same paper as a publisher would ship it: no arXiv margin stamp anywhere on page one.
NO_BANNER_LINES: tuple[tuple[str, float], ...] = tuple(
    line for line in PAPER_LINES if "arXiv" not in line[0]
)


def write_pdf(
    tmp_path: Path,
    lines: tuple[tuple[str, float], ...] = PAPER_LINES,
    *,
    metadata: dict[str, str] | None = None,
    name: str = "paper.pdf",
) -> Path:
    """Build a one-page PDF in ``tmp_path``; no shared fixture, no network."""
    document = pymupdf.open()
    page = document.new_page()
    top = 90.0
    for text, size in lines:
        page.insert_text((72, top), text, fontsize=size)
        top += size * 1.8
    if metadata is not None:
        document.set_metadata(metadata)
    path = tmp_path / name
    document.save(path)
    document.close()
    return path


def test_embedded_document_metadata_is_external_metadata_provenance(tmp_path: Path) -> None:
    path = write_pdf(
        tmp_path,
        NO_BANNER_LINES,
        metadata={
            "title": "Neural Scaling Laws",
            "author": "Roe, Jane Q.; Doe, John",
            "creationDate": "D:20240115120000Z",
        },
    )

    inspection = inspect_pdf_detail(path)
    metadata = inspection.metadata

    assert metadata.title is not None
    assert metadata.title.value == "Neural Scaling Laws"
    assert metadata.title.source is ProvenanceSource.EXTERNAL_METADATA
    assert metadata.title.note == NOTE_PDF_METADATA_TITLE
    assert inspection.note_for("title") == NOTE_PDF_METADATA_TITLE

    assert [field.value for field in metadata.authors] == ["Roe, Jane Q.", "Doe, John"]
    assert all(field.source is ProvenanceSource.EXTERNAL_METADATA for field in metadata.authors)
    assert all(field.note == NOTE_PDF_METADATA_AUTHOR for field in metadata.authors)
    assert inspection.note_for("authors") == NOTE_PDF_METADATA_AUTHOR

    assert metadata.year is not None
    assert metadata.year.value == "2024"
    assert metadata.year.source is ProvenanceSource.EXTERNAL_METADATA
    assert metadata.year.note == NOTE_PDF_METADATA_DATE
    assert inspection.note_for("year") == NOTE_PDF_METADATA_DATE


def test_title_falls_back_to_the_largest_font_near_the_top_of_page_one(
    tmp_path: Path,
) -> None:
    path = write_pdf(tmp_path)

    inspection = inspect_pdf_detail(path)

    assert inspection.metadata.title is not None
    assert inspection.metadata.title.value == "Neural Scaling Laws for Dense Retrieval"
    assert inspection.metadata.title.source is ProvenanceSource.SYSTEM
    assert inspection.metadata.title.note == NOTE_PAGE1_LARGEST_FONT
    assert inspection.note_for("title") == NOTE_PAGE1_LARGEST_FONT


def test_authors_are_the_lines_after_the_title_and_before_the_abstract(
    tmp_path: Path,
) -> None:
    path = write_pdf(tmp_path)

    inspection = inspect_pdf_detail(path)

    assert [field.value for field in inspection.metadata.authors] == [
        "Jane Q. Roe",
        "John Doe",
        "Ada Lovelace",
    ]
    assert all(field.source is ProvenanceSource.SYSTEM for field in inspection.metadata.authors)
    assert all(field.note == NOTE_PAGE1_AFTER_TITLE for field in inspection.metadata.authors)
    assert inspection.note_for("authors") == NOTE_PAGE1_AFTER_TITLE


def test_doi_and_arxiv_are_regex_extracted_from_page_one(tmp_path: Path) -> None:
    path = write_pdf(tmp_path)

    inspection = inspect_pdf_detail(path)
    identifiers = inspection.metadata.identifiers

    assert identifiers.doi is not None
    assert identifiers.doi.value == "10.1145/1234567.1234568"
    assert identifiers.doi.source is ProvenanceSource.SYSTEM
    assert identifiers.doi.note == NOTE_PAGE1_REGEX
    assert inspection.note_for("identifiers.doi") == NOTE_PAGE1_REGEX

    assert identifiers.arxiv is not None
    assert identifiers.arxiv.value == "2401.01234v2"
    assert identifiers.arxiv.note == NOTE_PAGE1_REGEX
    assert inspection.note_for("identifiers.arxiv") == NOTE_PAGE1_REGEX


def test_year_falls_back_to_a_four_digit_year_on_page_one(tmp_path: Path) -> None:
    path = write_pdf(tmp_path, NO_BANNER_LINES, name="no-banner.pdf")

    inspection = inspect_pdf_detail(path)

    assert inspection.metadata.year is not None
    assert inspection.metadata.year.value == "2019"
    assert inspection.metadata.year.source is ProvenanceSource.SYSTEM
    assert inspection.metadata.year.note == NOTE_PAGE1_REGEX
    assert inspection.note_for("year") == NOTE_PAGE1_REGEX


def test_absent_fields_stay_none_rather_than_being_invented(tmp_path: Path) -> None:
    path = write_pdf(tmp_path, lines=(), name="blank.pdf")

    inspection = inspect_pdf_detail(path)

    assert inspection.metadata == CandidateMetadata()
    assert inspection.notes == ()
    assert inspection.note_for("title") is None


def test_lines_without_a_recognisable_identifier_produce_no_identifier(
    tmp_path: Path,
) -> None:
    path = write_pdf(
        tmp_path,
        lines=(("A Note On Nothing In Particular", TITLE_SIZE),),
        name="note.pdf",
    )

    identifiers = inspect_pdf(path).identifiers

    assert identifiers.doi is None
    assert identifiers.arxiv is None


def test_every_extracted_field_records_where_it_was_found(tmp_path: Path) -> None:
    """The field-level note travels on the value, so an override knows what it replaces."""
    path = write_pdf(tmp_path)

    inspection = inspect_pdf_detail(path)
    metadata = inspection.metadata
    extracted = [
        field
        for field in (
            metadata.title,
            metadata.year,
            *metadata.authors,
            metadata.identifiers.doi,
            metadata.identifiers.arxiv,
        )
        if field is not None
    ]

    assert extracted
    assert all(field.note for field in extracted)
    assert {field.note for field in extracted} <= {
        NOTE_ARXIV_BANNER,
        NOTE_PAGE1_AFTER_TITLE,
        NOTE_PAGE1_LARGEST_FONT,
        NOTE_PAGE1_REGEX,
        NOTE_PDF_METADATA_AUTHOR,
        NOTE_PDF_METADATA_DATE,
        NOTE_PDF_METADATA_TITLE,
    }


def test_a_file_that_is_not_a_pdf_raises_ingest_error(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    path.write_text("this was never a PDF", encoding="utf-8")

    with pytest.raises(IngestError, match="cannot inspect") as caught:
        inspect_pdf(path)

    assert caught.value.__cause__ is not None, "the reader's own failure stays attached"


def test_a_corrupt_pdf_raises_ingest_error_chaining_the_reader_failure(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\n" + bytes(64))

    with pytest.raises(IngestError, match=r"corrupt\.pdf") as caught:
        inspect_pdf_detail(corrupt)

    assert isinstance(caught.value.__cause__, Exception)


def test_a_missing_file_raises_ingest_error(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="cannot inspect"):
        inspect_pdf(tmp_path / "absent.pdf")


def test_inspect_pdf_returns_only_the_metadata(tmp_path: Path) -> None:
    path = write_pdf(tmp_path)
    assert inspect_pdf(path) == inspect_pdf_detail(path).metadata


def test_inspection_is_deterministic_for_the_same_bytes(tmp_path: Path) -> None:
    path = write_pdf(tmp_path)
    assert inspect_pdf_detail(path) == inspect_pdf_detail(path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see doi:10.1145/1234567.1234568.", "10.1145/1234567.1234568"),
        ("(https://doi.org/10.1000/xyz123)", "10.1000/xyz123"),
        ("DOI 10.48550/arXiv.2401.01234;", "10.48550/arXiv.2401.01234"),
        ("10.1016/j.artint.2020.103245 (2020)", "10.1016/j.artint.2020.103245"),
        ("no identifier here", None),
        ("10.123/too-short-prefix", None),
    ],
)
def test_find_doi_trims_trailing_sentence_punctuation(text: str, expected: str | None) -> None:
    assert find_doi(text) == expected


def test_find_doi_keeps_a_balanced_closing_parenthesis() -> None:
    assert find_doi("10.1000/xyz(123)") == "10.1000/xyz(123)"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("arXiv:2401.01234v2 [cs.CL]", "2401.01234v2"),
        ("arXiv: 2401.01234", "2401.01234"),
        ("Preprint on arXiv, id 2401.01234v11, 2024", "2401.01234v11"),
        ("2401.01234 with no mention of the archive", None),
        ("arXiv but no identifier anywhere near it", None),
    ],
)
def test_find_arxiv_id_prefers_labelled_ids_and_needs_a_nearby_mention(
    text: str, expected: str | None
) -> None:
    assert find_arxiv_id(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Published 2019, revised 2024.", 2024),
        ("doi:10.1145/1234567.1234568 only", None),
        ("arXiv:2401.01234v2 only", None),
        ("no digits at all", None),
    ],
)
def test_find_year_ignores_digits_inside_identifiers(text: str, expected: int | None) -> None:
    assert find_year(text) == expected


def test_build_work_candidate_carries_the_hash_filename_and_system_provenance(
    tmp_path: Path,
) -> None:
    path = write_pdf(tmp_path, name="downloaded.pdf")
    fingerprint = fingerprint_file(path)
    metadata = inspect_pdf(path)

    candidate = build_work_candidate(path, fingerprint, metadata)

    assert candidate.candidate_file_hash == fingerprint.sha256
    assert candidate.original_filename == "downloaded.pdf"
    assert candidate.metadata == metadata
    assert candidate.provenance.source is ProvenanceSource.SYSTEM
    assert candidate.provenance.actor == INGEST_ACTOR
    assert candidate.provenance.note is not None
    assert "downloaded.pdf" in candidate.provenance.note
    assert candidate.resolution is IdentityResolutionOutcome.UNRESOLVED
    assert candidate.matched_work is None


def test_build_work_candidate_records_the_discovery_query_when_given(tmp_path: Path) -> None:
    path = write_pdf(tmp_path)
    candidate = build_work_candidate(
        path, fingerprint_file(path), inspect_pdf(path), source_query="dense retrieval scaling"
    )
    assert candidate.source_query == "dense retrieval scaling"


# -- the arXiv margin banner (dogfood F4) ------------------------------------


def test_the_arxiv_banner_parses_into_id_version_category_and_stamp_date() -> None:
    banner = find_arxiv_banner("arXiv:2301.01234v3  [cs.CR]  12 Mar 2025")

    assert banner is not None
    assert banner.identifier == "2301.01234v3"
    assert banner.base_id == "2301.01234"
    assert banner.version == "v3"
    assert banner.primary_category == "cs.CR"
    assert banner.submitted == date(2025, 3, 12)
    assert banner.year == 2023, "the id's YYMM, never the stamp date"


def test_a_banner_without_a_category_or_date_still_yields_the_id() -> None:
    banner = find_arxiv_banner("arXiv:2304.09513v3")

    assert banner is not None
    assert banner.base_id == "2304.09513"
    assert banner.primary_category is None
    assert banner.submitted is None
    assert banner.year == 2023


def test_an_old_style_banner_is_recognised() -> None:
    banner = find_arxiv_banner("arXiv:cs/0101001v1 [cs.DL] 3 Jan 2001")

    assert banner is not None
    assert banner.base_id == "cs/0101001"
    assert banner.year == 2001


def test_text_without_a_banner_yields_none() -> None:
    assert find_arxiv_banner("Proceedings of the ACM Web Conference 2022") is None


def test_the_publication_year_comes_from_the_arxiv_id_not_the_banner_date(
    tmp_path: Path,
) -> None:
    """Dogfood F4: a v3 stamped in 2025 made a 2023 paper unciteable from its bibliography."""
    path = write_pdf(
        tmp_path,
        (
            ("NetGPT: Generative Pretrained Transformer for Network Traffic", TITLE_SIZE),
            ("Xuying Meng, Chungang Lin, Yequan Wang", AUTHOR_SIZE),
            ("arXiv:2304.09513v3  [cs.NI]  21 Aug 2025", BODY_SIZE),
            ("Abstract", AUTHOR_SIZE),
            ("Traffic models can be pretrained on raw datagrams.", BODY_SIZE),
        ),
        metadata={"creationDate": "D:20250821120000Z"},
        name="netgpt.pdf",
    )

    inspection = inspect_pdf_detail(path)

    assert inspection.metadata.year is not None
    assert inspection.metadata.year.value == "2023"
    assert inspection.metadata.year.note == NOTE_ARXIV_BANNER
    assert inspection.note_for("year") == NOTE_ARXIV_BANNER
    identifiers = inspection.metadata.identifiers
    assert identifiers.arxiv is not None and identifiers.arxiv.value == "2304.09513v3"


# -- undecodable extracted text (dogfood F6) ---------------------------------


def _shifted(text: str) -> str:
    """``text`` as a font with no ToUnicode CMap hands it to an extractor."""
    return caesar(text, CIPHER_SHIFT)


def test_a_title_the_font_never_let_the_extractor_read_is_left_none(tmp_path: Path) -> None:
    path = write_pdf(
        tmp_path,
        (
            (_shifted("Robust Encrypted Traffic Fingerprinting"), TITLE_SIZE),
            ("Jane Q. Roe, John Doe", AUTHOR_SIZE),
            ("Abstract", AUTHOR_SIZE),
            ("We study encrypted traffic fingerprinting under drift.", BODY_SIZE),
        ),
        name="broken-cmap.pdf",
    )

    inspection = inspect_pdf_detail(path)

    assert inspection.metadata.title is None, "mojibake is not a title"
    assert inspection.note_for("title") == NOTE_DECODABILITY_LOW


def test_one_undecodable_name_drops_the_whole_author_list(tmp_path: Path) -> None:
    """The list came off one font: a half-readable author list is worse than an empty one."""
    path = write_pdf(
        tmp_path,
        (
            ("Datagram Representations for Traffic Classification", TITLE_SIZE),
            (f"Xinjie Lin, {_shifted('Gaopeng Gou')}, Junzheng Shi", AUTHOR_SIZE),
            ("Abstract", AUTHOR_SIZE),
            ("Representations decide what a classifier can learn.", BODY_SIZE),
        ),
        name="broken-authors.pdf",
    )

    inspection = inspect_pdf_detail(path)

    assert inspection.metadata.authors == ()
    assert inspection.note_for("authors") == NOTE_DECODABILITY_LOW
    assert inspection.metadata.title is not None, "only the unreadable field is dropped"


def test_readable_metadata_is_never_dropped_by_the_decodability_screen(tmp_path: Path) -> None:
    path = write_pdf(tmp_path)

    inspection = inspect_pdf_detail(path)

    assert inspection.metadata.title is not None
    assert inspection.metadata.authors
    assert inspection.note_for("title") != NOTE_DECODABILITY_LOW
    assert inspection.note_for("authors") != NOTE_DECODABILITY_LOW

"""Crossref field mapping: DOI normalization, list-valued fields, deposited references."""

from __future__ import annotations

import pytest

from research_harness.domain.enums import ProvenanceSource
from research_harness.domain.work import IdentifierField, WorkIdentifiers
from research_harness.providers.search import NotSupportedError, SearchQuery, normalize_doi
from research_harness.providers.search.base import (
    REFERENCE_DROP_WARNING_PREFIX,
    reference_warnings,
)
from research_harness.providers.search.crossref import (
    DROP_FRAGMENT,
    CrossrefSearchProvider,
)
from tests.contract.search.conftest import (
    CROSSREF_ITEM,
    CallRecorder,
    crossref_body,
    crossref_work_body,
    json_response,
    make_transport,
)


def _provider(recorder: CallRecorder, *bodies: dict[str, object]) -> CrossrefSearchProvider:
    responses = [json_response(body) for body in bodies]
    return CrossrefSearchProvider(transport=make_transport(recorder, *responses), env={})


def test_a_record_maps_to_a_candidate_without_inventing_anything(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, crossref_body())

    hit = provider.search(query).hits[0]
    metadata = hit.candidate.metadata

    assert metadata.title is not None
    assert metadata.title.value == "Detecting Protocol-Compliant Adversarial Traffic"
    assert [author.value for author in metadata.authors] == [
        "Ada Lovelace",
        "Hopper",
        "The Standards Consortium",
    ]
    assert metadata.year is not None and metadata.year.value == "2019"
    assert metadata.venue is not None and metadata.venue.value == "Proceedings of KDD '19"
    assert metadata.identifiers.doi is not None
    assert metadata.identifiers.doi.value == "10.1145/3292500.3330701"
    assert hit.raw_id == "10.1145/3292500.3330701"
    assert hit.url == "https://doi.org/10.1145/3292500.3330701"
    assert hit.cited_by_count == 42


def test_the_snippet_is_stripped_of_jats_markup_and_stays_a_hint(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, crossref_body())

    hit = provider.search(query).hits[0]

    assert hit.snippet is not None
    assert "<jats:" not in hit.snippet
    assert hit.snippet.startswith("We study protocol-compliant adversarial traffic")
    assert hit.is_evidence is False


def test_a_pdf_link_counts_as_open_access_only_when_the_record_says_so(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    """Crossref asserts no open access; a text-mining link is not an OA PDF."""
    licensed = _provider(recorder, crossref_body())
    assert licensed.search(query).hits[0].open_access_pdf_url == "https://example.org/paper.pdf"

    unlicensed_item = {key: value for key, value in CROSSREF_ITEM.items() if key != "license"}
    unlicensed = _provider(CallRecorder(), crossref_body([unlicensed_item]))
    assert unlicensed.search(query).hits[0].open_access_pdf_url is None


def test_missing_metadata_stays_missing(query: SearchQuery, recorder: CallRecorder) -> None:
    provider = _provider(recorder, crossref_body([{"DOI": "10.1000/xyz", "title": ["Bare"]}]))

    hit = provider.search(query).hits[0]
    metadata = hit.candidate.metadata

    assert metadata.year is None
    assert metadata.venue is None
    assert metadata.authors == ()
    assert metadata.identifiers.arxiv is None
    assert hit.snippet is None
    assert hit.cited_by_count is None
    assert hit.open_access_pdf_url is None


def test_a_record_with_neither_doi_nor_title_is_dropped_and_reported(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, crossref_body([{"type": "journal-article"}]))

    page = provider.search(query)

    assert page.hits == ()
    assert page.incomplete is True
    assert any("dropped rather than guessed" in warning for warning in page.warnings)


def test_the_first_page_opens_a_cursor_and_filters_are_translated(
    recorder: CallRecorder,
) -> None:
    provider = _provider(recorder, crossref_body())

    provider.search(
        SearchQuery(
            text="adversarial traffic",
            year_from=2018,
            year_to=2021,
            venue="KDD",
            max_results=7,
            fields_of_study=("Computer Science",),
        )
    )

    params = recorder.last_params
    assert params["cursor"] == "*"
    assert params["rows"] == "7"
    assert params["query"] == "adversarial traffic"
    assert params["filter"] == "from-pub-date:2018-01-01,until-pub-date:2021-12-31"
    assert params["query.container-title"] == "KDD"


def test_an_unapplied_filter_is_warned_about_rather_than_silently_dropped(
    recorder: CallRecorder,
) -> None:
    provider = _provider(recorder, crossref_body())

    page = provider.search(SearchQuery(text="x", fields_of_study=("Computer Science",)))

    assert any("fields_of_study" in warning for warning in page.warnings)
    assert page.incomplete is False


def test_references_come_from_the_deposited_reference_list(recorder: CallRecorder) -> None:
    provider = _provider(recorder, crossref_work_body())

    references = provider.fetch_references(_identifiers("https://doi.org/10.1145/3292500.3330701"))

    assert recorder.last.url.path == "/works/10.1145/3292500.3330701"
    titles = [
        reference.metadata.title.value
        for reference in references
        if reference.metadata.title is not None
    ]
    assert titles == [
        "Adversarial Examples in the Physical World",
        "Anonymous. A note without a DOI. 2018.",
        "A Book Without a DOI",
    ]
    first = references[0]
    assert first.metadata.identifiers.doi is not None
    assert first.metadata.identifiers.doi.value == "10.1109/sp.2016.42"
    assert first.metadata.year is not None and first.metadata.year.value == "2016"
    assert first.provenance.actor == "crossref"
    assert "10.1145/3292500.3330701#e_1_3_2_1_1" in (first.provenance.note or "")


def test_a_deposited_fragment_does_not_become_a_seed(recorder: CallRecorder) -> None:
    """Dogfood F10: bad reference segmentation turned 45 references into 474 junk seeds."""
    provider = _provider(
        recorder,
        crossref_work_body(
            reference=[
                {
                    "key": "1",
                    "unstructured": "international conference on learning representations",
                },
                {
                    "key": "2",
                    "unstructured": (
                        "the international conference on neural information processing "
                        "systems 6000 6010"
                    ),
                },
                {
                    "key": "3",
                    "unstructured": (
                        "but cannot fly in the annual meeting of the association for "
                        "computational linguistics 7811 7818"
                    ),
                },
                {"key": "4", "unstructured": "H. Reader. A whole reference. Journal, 2021."},
            ]
        ),
    )

    references = provider.fetch_references(_identifiers("10.1145/3292500.3330701"))

    titles = [
        reference.metadata.title.value
        for reference in references
        if reference.metadata.title is not None
    ]
    assert titles == ["H. Reader. A whole reference. Journal, 2021."]

    assert reference_warnings(references), "a silent gate makes the funnel unreadable"
    warning = reference_warnings(references)[0]
    assert warning.startswith(REFERENCE_DROP_WARNING_PREFIX)
    assert "deposited 4 record(s)" in warning
    assert f"3 {DROP_FRAGMENT}" in warning


def test_a_reference_list_with_nothing_dropped_warns_about_nothing(
    recorder: CallRecorder,
) -> None:
    provider = _provider(
        recorder,
        crossref_work_body(
            reference=[{"key": "1", "unstructured": "H. Reader. A whole reference. Journal, 2021."}]
        ),
    )

    references = provider.fetch_references(_identifiers("10.1145/3292500.3330701"))

    assert len(references) == 1
    assert reference_warnings(references) == ()


def test_a_fragment_carrying_a_structured_year_or_a_doi_is_still_a_seed(
    recorder: CallRecorder,
) -> None:
    """The gate reads raw text only; a year or a DOI the publisher deposited settles it."""
    provider = _provider(
        recorder,
        crossref_work_body(
            reference=[
                {"key": "1", "unstructured": "proceedings of the web conference", "year": "2022"},
                {
                    "key": "2",
                    "unstructured": "international conference on learning representations",
                    "DOI": "10.1109/SP.2016.42",
                },
            ]
        ),
    )

    references = provider.fetch_references(_identifiers("10.1145/3292500.3330701"))

    assert len(references) == 2


def test_forward_citations_are_not_available_from_crossref(recorder: CallRecorder) -> None:
    provider = _provider(recorder, crossref_body())

    assert provider.capabilities().supports_citations is False
    with pytest.raises(NotSupportedError):
        provider.fetch_citations(_identifiers("10.1145/3292500.3330701"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://doi.org/10.1145/ABC.123", "10.1145/abc.123"),
        ("doi:10.1145/abc", "10.1145/abc"),
        ("  10.1145/ABC  ", "10.1145/abc"),
        ("http://dx.doi.org/10.1/x", "10.1/x"),
        ("not-a-doi", None),
        ("", None),
        (None, None),
    ],
)
def test_doi_normalization(raw: str | None, expected: str | None) -> None:
    assert normalize_doi(raw) == expected


def _identifiers(doi: str) -> WorkIdentifiers:
    return WorkIdentifiers(
        doi=IdentifierField(value=doi, source=ProvenanceSource.EXTERNAL_METADATA)
    )

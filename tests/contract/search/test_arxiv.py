"""arXiv mapping: Atom namespaces, versioned ids, and API errors served as 200 feeds."""

from __future__ import annotations

import pytest

from research_harness.domain.work import WorkIdentifiers
from research_harness.providers.search import (
    NotSupportedError,
    SearchQuery,
    SearchResponseError,
    normalize_arxiv_id,
)
from research_harness.providers.search.arxiv import ArxivSearchProvider
from tests.contract.search.conftest import (
    ARXIV_ENTRY,
    ARXIV_ERROR_ENTRY,
    ARXIV_MULTI_TERM_ENTRY,
    ARXIV_MULTI_TERM_QUERY,
    ARXIV_MULTI_TERM_WIRE_QUERY,
    CallRecorder,
    arxiv_empty_feed,
    arxiv_feed,
    atom_response,
    make_transport,
)


def _provider(recorder: CallRecorder, *feeds: str) -> ArxivSearchProvider:
    responses = [atom_response(feed) for feed in feeds]
    return ArxivSearchProvider(transport=make_transport(recorder, *responses), env={})


def test_an_entry_maps_to_a_candidate_with_its_version_suffix(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, arxiv_feed())

    hit = provider.search(query).hits[0]
    metadata = hit.candidate.metadata

    assert metadata.identifiers.arxiv is not None
    assert metadata.identifiers.arxiv.value == "2101.00001v2"
    assert hit.raw_id == "2101.00001v2"
    assert metadata.identifiers.doi is not None
    assert metadata.identifiers.doi.value == "10.1109/tifs.2021.000001"


def test_a_wrapped_title_is_collapsed_and_authors_are_ordered(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, arxiv_feed())

    metadata = provider.search(query).hits[0].candidate.metadata

    assert metadata.title is not None
    assert metadata.title.value == "Protocol-Compliant Adversarial Traffic"
    assert [author.value for author in metadata.authors] == ["Ada Lovelace", "Grace Hopper"]


def test_the_year_comes_from_the_submission_date(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, arxiv_feed())

    metadata = provider.search(query).hits[0].candidate.metadata

    assert metadata.year is not None and metadata.year.value == "2021"
    assert metadata.venue is not None and metadata.venue.value == "IEEE TIFS 16 (2021) 1-14"


def test_the_links_separate_the_landing_page_from_the_pdf(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, arxiv_feed())

    hit = provider.search(query).hits[0]

    assert hit.url == "http://arxiv.org/abs/2101.00001v2"
    assert hit.open_access_pdf_url == "http://arxiv.org/pdf/2101.00001v2"


def test_the_summary_becomes_a_snippet_not_evidence(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, arxiv_feed())

    hit = provider.search(query).hits[0]

    assert hit.snippet == "We study protocol-compliant adversarial traffic and how detectors fail."
    assert hit.is_evidence is False


def test_free_text_and_date_bounds_become_one_search_query(recorder: CallRecorder) -> None:
    """Each term is its own `all:` clause; the date bound is AND-ed on unchanged."""
    provider = _provider(recorder, arxiv_feed())

    provider.search(SearchQuery(text="adversarial traffic", year_from=2020, year_to=2021))

    params = recorder.last_params
    assert params["search_query"] == (
        'all:"adversarial" AND all:"traffic" AND submittedDate:[202001010000 TO 202112312359]'
    )
    assert params["start"] == "0"
    assert params["max_results"] == "25"


def test_a_multi_term_question_is_sent_as_a_conjunction_not_one_phrase(
    recorder: CallRecorder,
) -> None:
    """Dogfood F1: `all:"<the whole question>"` matched nothing; the conjunction matches."""
    provider = _provider(recorder, arxiv_feed(ARXIV_MULTI_TERM_ENTRY, total=1))

    page = provider.search(SearchQuery(text=ARXIV_MULTI_TERM_QUERY, max_results=5))

    assert recorder.last_params["search_query"] == ARXIV_MULTI_TERM_WIRE_QUERY
    assert (
        '"pre-trained transformer encrypted traffic classification"'
        not in (recorder.last_params["search_query"])
    )
    assert len(page.hits) == 1
    assert page.warnings == ()
    identifiers = page.hits[0].candidate.metadata.identifiers
    assert identifiers.arxiv is not None and identifiers.arxiv.value == "2202.06335v1"


def test_a_quoted_substring_stays_one_phrase_clause(recorder: CallRecorder) -> None:
    provider = _provider(recorder, arxiv_feed())

    provider.search(SearchQuery(text='LLM "network intrusion detection" survey'))

    assert recorder.last_params["search_query"] == (
        'all:"LLM" AND all:"network intrusion detection" AND all:"survey"'
    )


def test_a_zero_result_multi_term_page_says_what_was_sent(recorder: CallRecorder) -> None:
    """A zero that a query shape may have caused must never look like a plain zero."""
    provider = _provider(recorder, arxiv_empty_feed())

    page = provider.search(SearchQuery(text=ARXIV_MULTI_TERM_QUERY, max_results=5))

    assert page.hits == ()
    assert page.incomplete is False, "a zero result is not a partial page"
    warning = next(warning for warning in page.warnings if warning.startswith("zero_result_query:"))
    assert ARXIV_MULTI_TERM_WIRE_QUERY in warning
    assert "5-term" in warning


def test_a_zero_result_single_term_page_carries_no_query_warning(recorder: CallRecorder) -> None:
    """One term cannot have been mangled into an unmatchable phrase, so nothing is said."""
    provider = _provider(recorder, arxiv_empty_feed())

    page = provider.search(SearchQuery(text="steganography"))

    assert page.hits == ()
    assert page.warnings == ()


def test_a_venue_filter_is_reported_as_unapplied(recorder: CallRecorder) -> None:
    provider = _provider(recorder, arxiv_feed())

    page = provider.search(SearchQuery(text="x", venue="NeurIPS"))

    assert any("venue" in warning for warning in page.warnings)
    assert page.incomplete is False


def test_paging_uses_the_start_offset(query: SearchQuery, recorder: CallRecorder) -> None:
    provider = _provider(recorder, arxiv_feed(total=42))

    page = provider.search(query)
    provider.search(query.at_cursor(page.next_cursor))

    assert page.next_cursor == "1"
    assert recorder.last_params["start"] == "1"


def test_the_last_page_reports_no_cursor(query: SearchQuery, recorder: CallRecorder) -> None:
    provider = _provider(recorder, arxiv_feed(total=1))

    assert provider.search(query).next_cursor is None


def test_an_api_error_feed_is_a_response_error_not_a_zero_result(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    """arXiv reports bad queries as a 200 Atom feed holding one error entry."""
    provider = _provider(recorder, arxiv_feed(ARXIV_ERROR_ENTRY, total=1))

    with pytest.raises(SearchResponseError) as excinfo:
        provider.search(query)

    assert "incorrect id format" in str(excinfo.value)


def test_a_body_that_is_not_atom_is_a_response_error(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, "<feed><entry></feed>")

    with pytest.raises(SearchResponseError):
        provider.search(query)


def test_arxiv_publishes_no_citation_graph(query: SearchQuery, recorder: CallRecorder) -> None:
    provider = _provider(recorder, arxiv_feed())
    capabilities = provider.capabilities()

    assert capabilities.supports_references is False
    assert capabilities.supports_citations is False
    with pytest.raises(NotSupportedError):
        provider.fetch_references(WorkIdentifiers())
    with pytest.raises(NotSupportedError):
        provider.fetch_citations(WorkIdentifiers())


def test_two_entries_are_ranked_in_feed_order(query: SearchQuery, recorder: CallRecorder) -> None:
    provider = _provider(recorder, arxiv_feed(ARXIV_ENTRY + ARXIV_ENTRY, total=9))

    hits = provider.search(query).hits

    assert [hit.rank for hit in hits] == [1, 2]
    assert hits[0].raw_id == hits[1].raw_id == "2101.00001v2"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://arxiv.org/abs/2101.00001v2", "2101.00001v2"),
        ("arXiv:2101.00001", "2101.00001"),
        ("  2101.00001v3 ", "2101.00001v3"),
        ("cs/0101001v1", "cs/0101001v1"),
        (None, None),
        ("", None),
    ],
)
def test_arxiv_id_normalization_keeps_the_version(raw: str | None, expected: str | None) -> None:
    assert normalize_arxiv_id(raw) == expected

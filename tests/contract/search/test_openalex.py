"""OpenAlex field mapping: id URLs, inverted abstracts, and both citation directions."""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.domain.enums import ProvenanceSource
from research_harness.domain.work import IdentifierField, WorkIdentifiers
from research_harness.providers.search import NotSupportedError, SearchQuery
from research_harness.providers.search.openalex import OpenAlexSearchProvider
from tests.contract.search.conftest import (
    OPENALEX_ITEM,
    CallRecorder,
    json_response,
    make_transport,
    openalex_body,
    openalex_work_body,
)


def _provider(recorder: CallRecorder, *bodies: dict[str, Any]) -> OpenAlexSearchProvider:
    responses = [json_response(body) for body in bodies]
    return OpenAlexSearchProvider(transport=make_transport(recorder, *responses), env={})


def test_ids_are_shortened_and_the_doi_is_normalized(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, openalex_body())

    hit = provider.search(query).hits[0]
    identifiers = hit.candidate.metadata.identifiers

    assert identifiers.openalex is not None
    assert identifiers.openalex.value == "W2741809807"
    assert identifiers.doi is not None
    assert identifiers.doi.value == "10.7717/peerj.4375"
    assert hit.raw_id == "W2741809807"


def test_an_arxiv_id_is_read_from_a_location_url_it_actually_carries(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, openalex_body())

    identifiers = provider.search(query).hits[0].candidate.metadata.identifiers

    assert identifiers.arxiv is not None
    assert identifiers.arxiv.value == "1802.00001v3"


def test_authors_venue_year_and_counts_map_across(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, openalex_body())

    hit = provider.search(query).hits[0]
    metadata = hit.candidate.metadata

    assert [author.value for author in metadata.authors] == [
        "Heather Piwowar",
        "Jason Priem",
    ]
    assert metadata.venue is not None and metadata.venue.value == "PeerJ"
    assert metadata.year is not None and metadata.year.value == "2018"
    assert hit.cited_by_count == 311
    assert hit.open_access_pdf_url == "https://peerj.com/articles/4375.pdf"


def test_the_inverted_abstract_index_is_rebuilt_in_position_order(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, openalex_body())

    snippet = provider.search(query).hits[0].snippet

    assert snippet == "Despite growing interest in open access in scholarly publishing"


def test_a_record_without_metadata_keeps_none_rather_than_a_guess(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, openalex_body([{"id": "https://openalex.org/W9"}]))

    hit = provider.search(query).hits[0]
    metadata = hit.candidate.metadata

    assert metadata.title is None
    assert metadata.year is None
    assert metadata.identifiers.doi is None
    assert hit.snippet is None
    assert hit.open_access_pdf_url is None


def test_filters_are_translated_into_openalex_filter_syntax(recorder: CallRecorder) -> None:
    provider = _provider(recorder, openalex_body())

    provider.search(
        SearchQuery(text="adversarial traffic", year_from=2019, year_to=2022, venue="PeerJ")
    )

    params = recorder.last_params
    assert params["search"] == "adversarial traffic"
    assert params["cursor"] == "*"
    assert params["filter"] == (
        "from_publication_date:2019-01-01,to_publication_date:2022-12-31,"
        "primary_location.source.display_name.search:PeerJ"
    )


def test_references_are_hydrated_from_referenced_works(recorder: CallRecorder) -> None:
    provider = _provider(recorder, openalex_work_body(), openalex_body())

    references = provider.fetch_references(_identifiers(openalex="W2741809807"))

    assert recorder.requests[0].url.path == "/works/W2741809807"
    assert recorder.requests[1].url.params["filter"] == "openalex_id:W1|W2"
    assert recorder.requests[1].url.params["per-page"] == "2"
    assert len(references) == 1
    assert references[0].provenance.actor == "openalex"
    assert references[0].source_query == "references of W2741809807"


def test_a_work_can_be_addressed_by_doi_when_no_openalex_id_is_known(
    recorder: CallRecorder,
) -> None:
    provider = _provider(recorder, openalex_work_body(), openalex_body())

    provider.fetch_references(_identifiers(doi="10.7717/peerj.4375"))

    assert recorder.requests[0].url.path == "/works/doi:10.7717/peerj.4375"


def test_forward_citations_use_the_cites_filter(recorder: CallRecorder) -> None:
    provider = _provider(recorder, openalex_work_body(), openalex_body(next_cursor=None))

    citations = provider.fetch_citations(_identifiers(openalex="W2741809807"))

    assert recorder.requests[1].url.params["filter"] == "cites:W2741809807"
    assert len(citations) == 1
    assert citations[0].source_query == "cites:W2741809807"


def test_the_citation_graph_needs_an_addressable_identifier(recorder: CallRecorder) -> None:
    provider = _provider(recorder, openalex_body())

    with pytest.raises(NotSupportedError):
        provider.fetch_citations(_identifiers())
    assert recorder.requests == []


def test_the_recorded_item_is_not_mutated_by_mapping(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    """Adapters read the wire record; they never write back into it."""
    before = dict(OPENALEX_ITEM)
    _provider(recorder, openalex_body()).search(query)

    assert before == OPENALEX_ITEM


def _identifiers(*, doi: str | None = None, openalex: str | None = None) -> WorkIdentifiers:
    def field(value: str | None) -> IdentifierField | None:
        if value is None:
            return None
        return IdentifierField(value=value, source=ProvenanceSource.EXTERNAL_METADATA)

    return WorkIdentifiers(doi=field(doi), openalex=field(openalex))

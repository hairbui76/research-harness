"""Semantic Scholar mapping: requested fields, external ids, offsets, optional key."""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.domain.enums import ProvenanceSource
from research_harness.domain.work import IdentifierField, WorkIdentifiers
from research_harness.providers.search import NotSupportedError, SearchQuery
from research_harness.providers.search.semantic_scholar import (
    API_KEY_ENV_VAR,
    PAPER_FIELDS,
    SemanticScholarSearchProvider,
)
from tests.contract.search.conftest import (
    API_KEY,
    CallRecorder,
    json_response,
    make_transport,
    semantic_scholar_body,
    semantic_scholar_graph_body,
)


def _provider(
    recorder: CallRecorder,
    *bodies: dict[str, Any],
    env: dict[str, str] | None = None,
) -> SemanticScholarSearchProvider:
    responses = [json_response(body) for body in bodies]
    return SemanticScholarSearchProvider(
        transport=make_transport(recorder, *responses), env=env or {}
    )


def test_external_ids_become_provenance_carrying_identifiers(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, semantic_scholar_body())

    hit = provider.search(query).hits[0]
    identifiers = hit.candidate.metadata.identifiers

    assert identifiers.doi is not None and identifiers.doi.value == "10.18653/v1/n18-3011"
    assert identifiers.arxiv is not None and identifiers.arxiv.value == "1805.06556"
    assert identifiers.dblp is not None
    assert identifiers.dblp.value == "conf/naacl/AmmarGBBCDDEFGH18"
    assert identifiers.semantic_scholar is not None
    assert identifiers.semantic_scholar.value == hit.raw_id


def test_venue_year_authors_and_open_access_pdf_map_across(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, semantic_scholar_body())

    hit = provider.search(query).hits[0]
    metadata = hit.candidate.metadata

    assert metadata.venue is not None and metadata.venue.value == "NAACL"
    assert metadata.year is not None and metadata.year.value == "2018"
    assert [author.value for author in metadata.authors] == [
        "Waleed Ammar",
        "Dirk Groeneveld",
    ]
    assert hit.open_access_pdf_url == "https://aclanthology.org/N18-3011.pdf"
    assert hit.cited_by_count == 321
    assert hit.url == "https://www.semanticscholar.org/paper/649def34"
    assert hit.snippet is not None and hit.snippet.startswith("We describe a deployed")


def test_the_requested_field_list_is_explicit(query: SearchQuery, recorder: CallRecorder) -> None:
    """The Graph API returns only `paperId` unless every field is named."""
    provider = _provider(recorder, semantic_scholar_body())

    provider.search(query)

    assert recorder.last_params["fields"] == ",".join(PAPER_FIELDS)
    assert "externalIds" in PAPER_FIELDS


@pytest.mark.parametrize(
    ("year_from", "year_to", "expected"),
    [(2018, 2022, "2018-2022"), (2018, None, "2018-"), (None, 2022, "-2022")],
)
def test_year_bounds_become_the_year_parameter(
    recorder: CallRecorder, year_from: int | None, year_to: int | None, expected: str
) -> None:
    provider = _provider(recorder, semantic_scholar_body())

    provider.search(SearchQuery(text="x", year_from=year_from, year_to=year_to))

    assert recorder.last_params["year"] == expected


def test_fields_of_study_and_venue_are_supported_filters(recorder: CallRecorder) -> None:
    provider = _provider(recorder, semantic_scholar_body())

    page = provider.search(
        SearchQuery(text="x", venue="NAACL", fields_of_study=("Computer Science", "Physics"))
    )

    assert recorder.last_params["fieldsOfStudy"] == "Computer Science,Physics"
    assert recorder.last_params["venue"] == "NAACL"
    assert page.warnings == ()


def test_the_next_offset_becomes_the_cursor(query: SearchQuery, recorder: CallRecorder) -> None:
    provider = _provider(recorder, semantic_scholar_body(next_offset=5))

    page = provider.search(query)
    provider.search(query.at_cursor(page.next_cursor))

    assert page.next_cursor == "5"
    assert recorder.last_params["offset"] == "5"
    assert recorder.last_params["limit"] == str(query.max_results)


def test_no_api_key_is_sent_when_none_is_configured(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, semantic_scholar_body(), env={})

    provider.search(query)

    assert provider.has_api_key is False
    assert "x-api-key" not in recorder.last.headers


def test_a_configured_api_key_travels_in_the_header_only(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, semantic_scholar_body(), env={API_KEY_ENV_VAR: API_KEY})

    provider.search(query)

    assert provider.has_api_key is True
    assert recorder.last.headers["x-api-key"] == API_KEY
    assert API_KEY not in str(recorder.last.url)
    assert API_KEY not in repr(provider)


def test_references_and_citations_unwrap_the_neighbour_record(recorder: CallRecorder) -> None:
    references = _provider(recorder, semantic_scholar_graph_body("citedPaper")).fetch_references(
        _identifiers(semantic_scholar="649def34")
    )

    assert recorder.last.url.path == "/graph/v1/paper/649def34/references"
    assert len(references) == 1
    assert references[0].metadata.title is not None
    assert references[0].source_query == "references of 649def34"

    citing_recorder = CallRecorder()
    citations = _provider(
        citing_recorder, semantic_scholar_graph_body("citingPaper")
    ).fetch_citations(_identifiers(semantic_scholar="649def34"))

    assert citing_recorder.last.url.path == "/graph/v1/paper/649def34/citations"
    assert len(citations) == 1


@pytest.mark.parametrize(
    ("identifiers", "expected"),
    [
        ({"doi": "10.18653/v1/N18-3011"}, "DOI:10.18653/v1/n18-3011"),
        ({"arxiv": "arXiv:1805.06556"}, "arXiv:1805.06556"),
        ({"dblp": "conf/naacl/Lo18"}, "DBLP:conf/naacl/Lo18"),
    ],
)
def test_a_paper_can_be_addressed_by_any_external_id(
    recorder: CallRecorder, identifiers: dict[str, str], expected: str
) -> None:
    provider = _provider(recorder, semantic_scholar_graph_body("citedPaper"))

    provider.fetch_references(_identifiers(**identifiers))

    assert recorder.last.url.path == f"/graph/v1/paper/{expected}/references"


def test_expansion_without_any_known_identifier_is_not_supported(
    recorder: CallRecorder,
) -> None:
    provider = _provider(recorder, semantic_scholar_body())

    with pytest.raises(NotSupportedError):
        provider.fetch_references(WorkIdentifiers())
    assert recorder.requests == []


def _identifiers(
    *,
    doi: str | None = None,
    arxiv: str | None = None,
    dblp: str | None = None,
    semantic_scholar: str | None = None,
) -> WorkIdentifiers:
    def field(value: str | None) -> IdentifierField | None:
        if value is None:
            return None
        return IdentifierField(value=value, source=ProvenanceSource.EXTERNAL_METADATA)

    return WorkIdentifiers(
        doi=field(doi),
        arxiv=field(arxiv),
        dblp=field(dblp),
        semantic_scholar=field(semantic_scholar),
    )

"""DBLP mapping: string counters, collapsed single-element lists, no citation graph."""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.domain.work import WorkIdentifiers
from research_harness.providers.search import NotSupportedError, SearchQuery
from research_harness.providers.search.dblp import DblpSearchProvider
from tests.contract.search.conftest import (
    DBLP_HIT,
    DBLP_SINGLE_AUTHOR_HIT,
    CallRecorder,
    dblp_body,
    json_response,
    make_transport,
)


def _provider(recorder: CallRecorder, *bodies: dict[str, Any]) -> DblpSearchProvider:
    responses = [json_response(body) for body in bodies]
    return DblpSearchProvider(transport=make_transport(recorder, *responses), env={})


def test_a_publication_record_maps_to_a_candidate(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, dblp_body())

    hit = provider.search(query).hits[0]
    metadata = hit.candidate.metadata

    assert metadata.title is not None
    assert metadata.title.value == "Analytical Engines and Adversarial Traffic."
    assert [author.value for author in metadata.authors] == ["Ada Lovelace", "Grace Hopper"]
    assert metadata.venue is not None and metadata.venue.value == "NeurIPS"
    assert metadata.year is not None and metadata.year.value == "2020"
    assert metadata.identifiers.dblp is not None
    assert metadata.identifiers.dblp.value == "conf/nips/LovelaceH20"
    assert metadata.identifiers.doi is not None
    assert metadata.identifiers.doi.value == "10.5555/nips.2020.1"
    assert hit.raw_id == "conf/nips/LovelaceH20"
    assert hit.url == "https://dblp.org/rec/conf/nips/LovelaceH20"


def test_a_single_author_object_is_read_like_a_list(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    """DBLP collapses one-element lists into a bare object."""
    provider = _provider(recorder, dblp_body())

    second = provider.search(query).hits[1]

    assert [author.value for author in second.candidate.metadata.authors] == ["Solo Author"]
    assert second.candidate.metadata.venue is not None
    assert second.candidate.metadata.venue.value == "CoRR"


def test_only_an_open_pdf_link_is_reported_as_open_access(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, dblp_body())

    hits = provider.search(query).hits

    assert hits[0].open_access_pdf_url == "https://proceedings.example.org/paper.pdf"
    assert hits[1].open_access_pdf_url is None


def test_dblp_publishes_neither_snippets_nor_citation_counts(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, dblp_body())

    hit = provider.search(query).hits[0]

    assert hit.snippet is None
    assert hit.cited_by_count is None


def test_filters_dblp_cannot_apply_are_reported_not_hidden(recorder: CallRecorder) -> None:
    provider = _provider(recorder, dblp_body())

    page = provider.search(
        SearchQuery(text="x", year_from=2019, venue="NeurIPS", fields_of_study=("CS",))
    )

    assert provider.capabilities().supports_year_filter is False
    assert len(page.warnings) == 3
    assert any("year" in warning for warning in page.warnings)
    assert any("venue" in warning for warning in page.warnings)
    assert any("fields_of_study" in warning for warning in page.warnings)
    assert page.incomplete is False
    assert "year" not in recorder.last_params


def test_offset_paging_stops_at_the_reported_total(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, dblp_body(total="2"))

    page = provider.search(query)

    assert page.total_estimate == 2
    assert page.next_cursor is None


def test_paging_continues_while_records_remain(query: SearchQuery, recorder: CallRecorder) -> None:
    provider = _provider(recorder, dblp_body(total="77"))

    page = provider.search(query)
    provider.search(query.at_cursor(page.next_cursor))

    assert page.next_cursor == "2"
    assert recorder.last_params["f"] == "2"
    assert recorder.last_params["h"] == str(query.max_results)
    assert recorder.last_params["format"] == "json"


def test_a_record_without_key_title_or_doi_is_dropped(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, dblp_body([{"@id": "1", "info": {"type": "Editorship"}}]))

    page = provider.search(query)

    assert page.hits == ()
    assert page.incomplete is True


def test_the_citation_graph_is_unavailable_from_dblp(
    query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = _provider(recorder, dblp_body())
    capabilities = provider.capabilities()

    assert capabilities.supports_references is False
    assert capabilities.supports_citations is False
    with pytest.raises(NotSupportedError):
        provider.fetch_references(WorkIdentifiers())
    with pytest.raises(NotSupportedError):
        provider.fetch_citations(WorkIdentifiers())


def test_recorded_hits_are_left_untouched(query: SearchQuery, recorder: CallRecorder) -> None:
    before = (dict(DBLP_HIT), dict(DBLP_SINGLE_AUTHOR_HIT))

    _provider(recorder, dblp_body()).search(query)

    assert before == (DBLP_HIT, DBLP_SINGLE_AUTHOR_HIT)

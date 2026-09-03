"""The contract every discovery source must honour (ROADMAP Task 12.1).

Three acceptance requirements are the spine of this file:

1. a search result is candidate material only -- `WorkCandidate`s in `discovered` /
   `unresolved` state, every metadata field carrying `external_metadata` provenance;
2. snippets are discovery hints and can never be Evidence;
3. provider errors, rate limits, authentication failures and access barriers stay
   distinct from a successful zero-result search.

Plus the two things Task 12.2 has to be able to record honestly: what the outgoing
request disclosed, and where paging stopped.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from research_harness.domain.enums import (
    IdentityResolutionOutcome,
    ProvenanceSource,
    ScreeningState,
)
from research_harness.domain.errors import ProviderError, ResearchHarnessError
from research_harness.domain.research import SourceFailure
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkIdentifiers,
)
from research_harness.providers.search import (
    CONTACT_EMAIL_ENV_VAR,
    CROSSREF,
    MAX_RESULTS_PER_PAGE,
    SEARCH_SOURCES,
    NotSupportedError,
    SearchAccessBarrierError,
    SearchAuthError,
    SearchHit,
    SearchProviderError,
    SearchQuery,
    SearchRateLimitError,
    SearchResponseError,
    SearchTransportError,
    UnknownSearchProviderError,
    build_search_providers,
    build_search_registry,
    looks_like_reference,
    query_terms,
    to_source_failure,
)
from tests.contract.search.conftest import (
    CONTACT_EMAIL,
    CallRecorder,
    SearchCase,
    html_response,
    make_transport,
    rate_limited_response,
)

CREDENTIAL_PARAMS = frozenset({"api_key", "apikey", "key", "token", "access_token"})


# ------------------------------------------------------- discovery yields candidates


def test_recorded_page_yields_ranked_candidates_with_external_provenance(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})

    page = provider.search(query)

    assert page.source == search_case.id
    assert page.query == query
    assert page.hits, "the recorded response contains at least one record"
    assert [hit.rank for hit in page.hits] == list(range(1, len(page.hits) + 1))
    assert page.total_estimate == search_case.total_estimate
    assert page.incomplete is False
    assert page.warnings == ()
    assert page.executed_at.tzinfo is not None

    for hit in page.hits:
        candidate = hit.candidate
        assert hit.source == search_case.id
        assert hit.raw_id
        assert candidate.provenance.source is ProvenanceSource.EXTERNAL_METADATA
        assert candidate.provenance.actor == search_case.id
        assert hit.raw_id in (candidate.provenance.note or "")
        assert candidate.source_query == query.text
        for identifier in _stated_fields(candidate.metadata):
            assert identifier.source is ProvenanceSource.EXTERNAL_METADATA


def test_search_results_are_discovery_space_not_corpus_members(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    """Product 14: a discovered candidate is unscreened and unresolved, with no Work."""
    provider = search_case.build(make_transport(recorder, search_case.success()), {})

    for candidate in provider.search(query).candidates:
        assert candidate.screening is ScreeningState.DISCOVERED
        assert candidate.resolution is IdentityResolutionOutcome.UNRESOLVED
        assert candidate.matched_work is None
        assert candidate.candidate_file_hash is None


def test_snippets_are_discovery_hints_that_can_never_be_evidence(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})

    hit = provider.search(query).hits[0]

    assert hit.is_evidence is False
    with pytest.raises(ValidationError):
        SearchHit.model_validate(hit.model_dump() | {"is_evidence": True})


def test_a_hit_is_frozen(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})
    hit = provider.search(query).hits[0]

    with pytest.raises(ValidationError):
        # ignore: assigning to a frozen model field is the behaviour under test.
        hit.snippet = "quoted as if it were evidence"  # type: ignore[misc]


# -------------------------------------------------------------- zero results vs error


def test_zero_results_is_an_empty_page_not_an_error(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.empty()), {})

    page = provider.search(query)

    assert page.hits == ()
    assert page.candidates == ()
    assert page.incomplete is False
    assert page.next_cursor is None
    assert page.source == search_case.id


# ------------------------------------------------------------------ distinct failures


def test_rate_limiting_raises_a_rate_limit_error_carrying_retry_after(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, rate_limited_response("2")), {})

    with pytest.raises(SearchRateLimitError) as excinfo:
        provider.search(query)

    assert excinfo.value.retry_after == 2.0
    assert excinfo.value.source == search_case.id
    assert excinfo.value.query == query.text
    assert "retry after 2s" in excinfo.value.reason


def test_unauthorized_raises_an_auth_error(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    response = httpx.Response(401, json={"error": "unauthorized"})
    provider = search_case.build(make_transport(recorder, response), {})

    with pytest.raises(SearchAuthError) as excinfo:
        provider.search(query)

    assert not isinstance(excinfo.value, SearchAccessBarrierError)
    assert excinfo.value.reason.startswith("auth:")


def test_an_html_challenge_page_raises_an_access_barrier_error(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, html_response(403)), {})

    with pytest.raises(SearchAccessBarrierError) as excinfo:
        provider.search(query)

    assert excinfo.value.reason.startswith("access_barrier:")


def test_an_html_body_with_a_200_status_is_still_an_access_barrier(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    """A CDN interstitial served as 200 must not be parsed as zero results."""
    provider = search_case.build(make_transport(recorder, html_response(200)), {})

    with pytest.raises(SearchAccessBarrierError):
        provider.search(query)


def test_server_errors_and_timeouts_raise_transport_errors(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    server_error = search_case.build(
        make_transport(recorder, httpx.Response(500, text="upstream failure")), {}
    )
    with pytest.raises(SearchTransportError):
        server_error.search(query)

    timing_out = search_case.build(make_transport(recorder, httpx.ConnectTimeout("timed out")), {})
    with pytest.raises(SearchTransportError):
        timing_out.search(query)


def test_a_malformed_body_raises_a_response_error(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.malformed()), {})

    with pytest.raises(SearchResponseError) as excinfo:
        provider.search(query)

    assert excinfo.value.reason.startswith("malformed_response:")


def test_every_search_failure_is_one_harness_error_family(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, rate_limited_response()), {})

    with pytest.raises(SearchProviderError) as excinfo:
        provider.search(query)

    assert isinstance(excinfo.value, ProviderError)
    assert isinstance(excinfo.value, ResearchHarnessError)


def test_a_failure_converts_into_a_source_failure_for_the_search_run(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    """Task 12.2 records failed *and* incomplete source queries, never zero results."""
    provider = search_case.build(make_transport(recorder, rate_limited_response("30")), {})

    with pytest.raises(SearchProviderError) as excinfo:
        provider.search(query)
    failure = to_source_failure(excinfo.value, search_case.id, incomplete=True)

    assert isinstance(failure, SourceFailure)
    assert failure.source == search_case.id
    assert failure.query == query.text
    assert failure.incomplete is True
    assert "rate_limit" in failure.reason


# --------------------------------------------------------------- what leaves the box


def test_requests_are_polite_and_anonymous_when_nothing_is_configured(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})

    provider.search(query)

    request = recorder.last
    assert request.method == "GET"
    assert request.url.path == search_case.path
    assert request.headers["user-agent"].startswith("research-harness/")
    assert "mailto" not in request.headers["user-agent"]
    assert "x-api-key" not in request.headers
    assert "authorization" not in request.headers
    params = recorder.last_params
    assert "mailto" not in params
    assert CREDENTIAL_PARAMS.isdisjoint({name.lower() for name in params})
    assert not request.content


def test_the_contact_address_is_sent_only_when_the_environment_sets_one(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(
        make_transport(recorder, search_case.success()),
        {CONTACT_EMAIL_ENV_VAR: CONTACT_EMAIL},
    )

    provider.search(query)

    assert f"mailto:{CONTACT_EMAIL}" in recorder.last.headers["user-agent"]
    if search_case.mailto_param:
        assert recorder.last_params["mailto"] == CONTACT_EMAIL
    else:
        assert "mailto" not in recorder.last_params


def test_capabilities_declare_the_endpoint_and_the_egress(
    search_case: SearchCase, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})

    capabilities = provider.capabilities()

    assert capabilities.supports_cursor is True
    assert capabilities.requires_api_key is False
    assert capabilities.egress.sends_source_text is False
    assert capabilities.egress.endpoint_host
    assert "." in capabilities.egress.endpoint_host
    assert capabilities.egress.description


# ------------------------------------------------------------------------- pagination


def test_the_next_cursor_is_read_from_the_response_and_echoed_into_the_next_request(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})

    page = provider.search(query)
    assert page.next_cursor == search_case.next_cursor

    provider.search(query.at_cursor(page.next_cursor))

    assert len(recorder.requests) == 2
    assert recorder.last_params[search_case.cursor_param] == search_case.next_cursor


def test_an_exhausted_page_reports_no_cursor(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.empty()), {})

    assert provider.search(query).next_cursor is None


# ------------------------------------------------------------------- citation graph


def test_unavailable_graph_directions_are_declared_and_refused(
    search_case: SearchCase, query: SearchQuery, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})
    identifiers = WorkIdentifiers(
        doi=IdentifierField(
            value="10.1145/3292500.3330701", source=ProvenanceSource.EXTERNAL_METADATA
        )
    )
    capabilities = provider.capabilities()

    if not capabilities.supports_references:
        with pytest.raises(NotSupportedError):
            provider.fetch_references(identifiers)
    if not capabilities.supports_citations:
        with pytest.raises(NotSupportedError):
            provider.fetch_citations(identifiers)


def test_graph_expansion_without_a_usable_identifier_is_not_supported(
    search_case: SearchCase, recorder: CallRecorder
) -> None:
    provider = search_case.build(make_transport(recorder, search_case.success()), {})

    with pytest.raises(NotSupportedError):
        provider.fetch_references(WorkIdentifiers())
    assert recorder.requests == [], "a request must not be attempted without an identifier"


# ---------------------------------------------------------------------- the registry


def test_the_registry_builds_every_source_offline(recorder: CallRecorder) -> None:
    transport = make_transport(recorder, httpx.Response(200, json={}))

    providers = build_search_providers({}, transport=transport)

    assert tuple(providers) == SEARCH_SOURCES
    assert all(name == provider.name for name, provider in providers.items())


def test_the_registry_is_name_addressed_and_declares_egress(recorder: CallRecorder) -> None:
    transport = make_transport(recorder, httpx.Response(200, json={}))

    registry = build_search_registry({}, transport=transport)

    assert registry.names == SEARCH_SOURCES
    assert registry.get(CROSSREF).name == CROSSREF
    assert set(registry.egress()) == set(SEARCH_SOURCES)
    assert len(registry) == len(SEARCH_SOURCES)
    with pytest.raises(UnknownSearchProviderError):
        registry.get("scopus")


def test_an_unknown_source_cannot_be_built(recorder: CallRecorder) -> None:
    transport = make_transport(recorder, httpx.Response(200, json={}))

    with pytest.raises(UnknownSearchProviderError):
        build_search_providers({}, transport=transport, sources=["scopus"])


# ------------------------------------------------------------------------ the query


def test_a_page_may_not_exceed_the_shared_result_ceiling() -> None:
    with pytest.raises(ValidationError):
        SearchQuery(text="x", max_results=MAX_RESULTS_PER_PAGE + 1)


def test_a_reversed_year_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchQuery(text="x", year_from=2020, year_to=2019)


# ------------------------------------------------------- shared query and reference helpers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("encrypted traffic classification", ("encrypted", "traffic", "classification")),
        ('LLM "network intrusion detection"', ("LLM", "network intrusion detection")),
        ("Rethinking, the: BURST?", ("Rethinking", "the", "BURST")),
        ("pre-trained cs/0101001", ("pre-trained", "cs/0101001")),
        ('an "unclosed quote', ("an", "unclosed", "quote")),
        ("traffic traffic", ("traffic",)),
        ("   ", ()),
    ],
)
def test_query_terms_splits_on_words_and_keeps_quoted_phrases(
    text: str, expected: tuple[str, ...]
) -> None:
    """Order is the caller's; duplicates collapse, so the wire form is deterministic."""
    assert query_terms(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("H. Reader. A whole reference. Journal, 2021.", True),
        ("international conference on learning representations", False),
        ("the international conference on neural information processing systems 6000 6010", False),
        ("but cannot fly in the annual meeting of the association 7811 7818", False),
        ("2021", False),
    ],
)
def test_looks_like_reference_admits_whole_references_and_refuses_fragments(
    text: str, expected: bool
) -> None:
    assert looks_like_reference(text) is expected


def test_a_structured_year_settles_a_reference_the_text_alone_would_not() -> None:
    fragment = "proceedings of the web conference"
    assert looks_like_reference(fragment) is False
    assert looks_like_reference(fragment, year=2022) is True
    assert looks_like_reference(fragment, year=6010) is False, "a page number is not a year"


def _stated_fields(metadata: CandidateMetadata) -> list[IdentifierField | None]:
    """Every metadata field the source actually stated, identifiers included."""
    identifiers = metadata.identifiers
    stated: list[IdentifierField | None] = [
        metadata.title,
        metadata.year,
        metadata.venue,
        identifiers.doi,
        identifiers.arxiv,
        identifiers.dblp,
        identifiers.semantic_scholar,
        identifiers.openalex,
        *metadata.authors,
    ]
    return [field for field in stated if field is not None]

"""External discovery sources behind one neutral contract (Product 17, ROADMAP 12.1).

Import the contract and the adapters from here::

    from research_harness.providers.search import (
        SearchQuery, SearchPage, build_search_providers,
    )

Discovery output is candidate material only: a `SearchHit` is a hint that a work exists,
its snippet can never become Evidence, and a zero-result page is a different outcome from
a source that could not be searched (Product 14, 18).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import httpx

from research_harness.privacy.policy import EgressPolicy, check_egress, denial
from research_harness.providers.search._http import (
    CONTACT_EMAIL_ENV_VAR,
    DEFAULT_TIMEOUT_SECONDS,
    HttpSearchProvider,
    contact_email,
    polite_user_agent,
)
from research_harness.providers.search.arxiv import SOURCE_NAME as ARXIV
from research_harness.providers.search.arxiv import (
    ArxivSearchProvider,
    default_arxiv_capabilities,
)
from research_harness.providers.search.base import (
    MAX_GRAPH_RECORDS,
    MAX_RESULTS_PER_PAGE,
    SNIPPET_MAX_CHARS,
    ZERO_RESULT_WARNING_PREFIX,
    NotSupportedError,
    SearchAccessBarrierError,
    SearchAuthError,
    SearchHit,
    SearchPage,
    SearchProvider,
    SearchProviderCapabilities,
    SearchProviderError,
    SearchProviderRegistry,
    SearchQuery,
    SearchRateLimitError,
    SearchResponseError,
    SearchTransportError,
    UnknownSearchProviderError,
    build_candidate,
    degenerate_query_warning,
    external_provenance,
    looks_like_reference,
    normalize_arxiv_id,
    normalize_doi,
    query_terms,
    to_source_failure,
    work_identifiers,
)
from research_harness.providers.search.crossref import SOURCE_NAME as CROSSREF
from research_harness.providers.search.crossref import (
    CrossrefSearchProvider,
    default_crossref_capabilities,
)
from research_harness.providers.search.dblp import SOURCE_NAME as DBLP
from research_harness.providers.search.dblp import (
    DblpSearchProvider,
    default_dblp_capabilities,
)
from research_harness.providers.search.openalex import SOURCE_NAME as OPENALEX
from research_harness.providers.search.openalex import (
    OpenAlexSearchProvider,
    default_openalex_capabilities,
)
from research_harness.providers.search.semantic_scholar import (
    API_KEY_ENV_VAR as SEMANTIC_SCHOLAR_API_KEY_ENV_VAR,
)
from research_harness.providers.search.semantic_scholar import SOURCE_NAME as SEMANTIC_SCHOLAR
from research_harness.providers.search.semantic_scholar import (
    SemanticScholarSearchProvider,
    default_semantic_scholar_capabilities,
)

__all__ = [
    "ARXIV",
    "CONTACT_EMAIL_ENV_VAR",
    "CROSSREF",
    "DBLP",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_GRAPH_RECORDS",
    "MAX_RESULTS_PER_PAGE",
    "OPENALEX",
    "SEARCH_CAPABILITIES",
    "SEARCH_SOURCES",
    "SEMANTIC_SCHOLAR",
    "SEMANTIC_SCHOLAR_API_KEY_ENV_VAR",
    "SNIPPET_MAX_CHARS",
    "ZERO_RESULT_WARNING_PREFIX",
    "ArxivSearchProvider",
    "CrossrefSearchProvider",
    "DblpSearchProvider",
    "HttpSearchProvider",
    "NotSupportedError",
    "OpenAlexSearchProvider",
    "SearchAccessBarrierError",
    "SearchAuthError",
    "SearchHit",
    "SearchPage",
    "SearchProvider",
    "SearchProviderCapabilities",
    "SearchProviderError",
    "SearchProviderRegistry",
    "SearchQuery",
    "SearchRateLimitError",
    "SearchResponseError",
    "SearchTransportError",
    "SemanticScholarSearchProvider",
    "UnknownSearchProviderError",
    "build_candidate",
    "build_search_providers",
    "build_search_registry",
    "contact_email",
    "default_arxiv_capabilities",
    "default_crossref_capabilities",
    "default_dblp_capabilities",
    "default_openalex_capabilities",
    "default_semantic_scholar_capabilities",
    "degenerate_query_warning",
    "external_provenance",
    "looks_like_reference",
    "normalize_arxiv_id",
    "normalize_doi",
    "polite_user_agent",
    "query_terms",
    "search_source_capabilities",
    "to_source_failure",
    "work_identifiers",
]

_Builder = Callable[..., SearchProvider]

_BUILDERS: dict[str, _Builder] = {
    CROSSREF: CrossrefSearchProvider,
    OPENALEX: OpenAlexSearchProvider,
    SEMANTIC_SCHOLAR: SemanticScholarSearchProvider,
    DBLP: DblpSearchProvider,
    ARXIV: ArxivSearchProvider,
}

SEARCH_SOURCES: tuple[str, ...] = tuple(_BUILDERS)
"""Configured discovery sources, in the order a `SearchRun` should record them."""

_CapabilityFactory = Callable[[], SearchProviderCapabilities]

SEARCH_CAPABILITIES: dict[str, _CapabilityFactory] = {
    CROSSREF: default_crossref_capabilities,
    OPENALEX: default_openalex_capabilities,
    SEMANTIC_SCHOLAR: default_semantic_scholar_capabilities,
    DBLP: default_dblp_capabilities,
    ARXIV: default_arxiv_capabilities,
}
"""What each source declares at its default endpoint, without constructing an adapter.

The privacy policy and the egress report both need a source's declaration before anything
is built, so the declarations are addressable by name (Product 34).
"""


def search_source_capabilities(source: str) -> SearchProviderCapabilities:
    """The declared capabilities and egress of one discovery source, by name."""
    try:
        return SEARCH_CAPABILITIES[source]()
    except KeyError as exc:
        raise UnknownSearchProviderError(
            f"unknown search source {source!r}; available: {', '.join(SEARCH_SOURCES)}",
            source=source,
        ) from exc


def build_search_providers(
    env: Mapping[str, str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    sources: Sequence[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    policy: EgressPolicy | None = None,
) -> dict[str, SearchProvider]:
    """Every configured discovery source, keyed by name.

    Credentials and the polite-pool contact address come from `env` (defaulting to the
    process environment) and never from a workspace file (Product 34). `transport` is
    injected into every adapter, which is how the whole set is exercised offline.

    `policy` is the project's egress policy, applied before any adapter is constructed. A
    source the researcher asked for by name is refused loudly with `EgressDeniedError`; a
    source that is merely part of the default set is left out, and when the policy leaves
    nothing to search the refusal is raised rather than an empty set returned -- "we could
    not search" must never look like "we searched and found nothing" (Product 18).
    """
    names = list(SEARCH_SOURCES) if sources is None else list(sources)
    unknown = [name for name in names if name not in _BUILDERS]
    if unknown:
        raise UnknownSearchProviderError(
            f"unknown search source(s): {', '.join(unknown)}; "
            f"available: {', '.join(SEARCH_SOURCES)}"
        )
    if policy is not None:
        names = _permitted_sources(names, policy, requested=sources is not None)
    return {name: _BUILDERS[name](env=env, transport=transport, timeout=timeout) for name in names}


def _permitted_sources(names: Sequence[str], policy: EgressPolicy, *, requested: bool) -> list[str]:
    """The sources the policy allows; raises when an asked-for or the last one is refused."""
    allowed: list[str] = []
    refusals: list[Exception] = []
    for name in names:
        egress = search_source_capabilities(name).egress
        check = check_egress(policy, egress, kind="search")
        if check.allowed:
            allowed.append(name)
            continue
        refusal = denial(name, egress, check, kind="search")
        if requested:
            raise refusal
        refusals.append(refusal)
    if not allowed and refusals:
        raise refusals[0]
    return allowed


def build_search_registry(
    env: Mapping[str, str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    sources: Sequence[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    policy: EgressPolicy | None = None,
) -> SearchProviderRegistry:
    """The same set as `build_search_providers`, wrapped for name lookup and egress."""
    return SearchProviderRegistry(
        build_search_providers(
            env, transport=transport, sources=sources, timeout=timeout, policy=policy
        ).values()
    )

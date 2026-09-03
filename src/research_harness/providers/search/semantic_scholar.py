"""Semantic Scholar adapter: relevance search plus both citation directions.

Wire assumptions:

* `GET {base}/paper/search?query=&fields=&offset=&limit=`; the reply's `next` field is
  the next offset, which this adapter hands back as the opaque cursor.
* `fields` must be requested explicitly -- the API returns only `paperId` otherwise.
* `x-api-key` is sent only when a key is configured, from `SEMANTIC_SCHOLAR_API_KEY` or
  an explicit argument; the API is usable (at a lower rate limit) without one, so the
  adapter never fails for a missing key.
* Graph expansion uses `/paper/{id}/references` and `/paper/{id}/citations`, whose rows
  wrap the neighbour in `citedPaper` / `citingPaper`. Ids may be a Semantic Scholar
  paper id or a prefixed external id (`DOI:`, `arXiv:`, `DBLP:`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx

from research_harness.domain.work import WorkCandidate, WorkIdentifiers
from research_harness.providers.models.base import EgressDeclaration
from research_harness.providers.search._http import (
    DEFAULT_TIMEOUT_SECONDS,
    HttpSearchProvider,
    endpoint_host,
)
from research_harness.providers.search.base import (
    MAX_GRAPH_RECORDS,
    NotSupportedError,
    SearchHit,
    SearchPage,
    SearchProviderCapabilities,
    SearchQuery,
    as_int,
    as_mapping,
    build_candidate,
    clean_text,
    iter_mappings,
    normalize_arxiv_id,
    normalize_doi,
    offset_from_cursor,
    snippet_from,
    unmapped_records_warning,
    work_identifiers,
)

__all__ = [
    "API_KEY_ENV_VAR",
    "DEFAULT_BASE_URL",
    "PAPER_FIELDS",
    "SOURCE_NAME",
    "SemanticScholarSearchProvider",
    "default_semantic_scholar_capabilities",
]

SOURCE_NAME = "semantic_scholar"
DEFAULT_BASE_URL = "https://api.semanticscholar.org/graph/v1"
API_KEY_ENV_VAR = "SEMANTIC_SCHOLAR_API_KEY"
SEARCH_PATH = "/paper/search"
PAPER_FIELDS = (
    "paperId",
    "externalIds",
    "title",
    "abstract",
    "venue",
    "year",
    "authors",
    "citationCount",
    "openAccessPdf",
    "url",
)
GRAPH_PAGE_SIZE = 100


def default_semantic_scholar_capabilities(
    base_url: str = DEFAULT_BASE_URL,
) -> SearchProviderCapabilities:
    """Semantic Scholar: offset paging, year filter, references and citations."""
    return SearchProviderCapabilities(
        supports_cursor=True,
        supports_year_filter=True,
        supports_references=True,
        supports_citations=True,
        requires_api_key=False,
        egress=EgressDeclaration(
            endpoint_host=endpoint_host(base_url),
            sends_source_text=False,
            sends_identifiers=True,
            description=(
                "Query terms, filters and the paper identifiers being expanded are sent "
                "to the Semantic Scholar Graph API, with an API key in the x-api-key "
                "header when one is configured. No source text leaves the workstation."
            ),
        ),
    )


class SemanticScholarSearchProvider(HttpSearchProvider):
    """Discovery and citation-graph expansion against the Semantic Scholar Graph API."""

    name = SOURCE_NAME

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        env: Mapping[str, str] | None = None,
        capabilities: SearchProviderCapabilities | None = None,
    ) -> None:
        key = _resolve_api_key(api_key, env)
        super().__init__(
            base_url=base_url,
            capabilities=capabilities or default_semantic_scholar_capabilities(base_url),
            timeout=timeout,
            transport=transport,
            env=env,
            extra_headers={"x-api-key": key} if key else None,
        )
        self.has_api_key = key is not None

    def search(self, query: SearchQuery) -> SearchPage:
        """One offset page of Semantic Scholar relevance search."""
        offset = offset_from_cursor(query.cursor, source=SOURCE_NAME, query=query.text)
        params: dict[str, str] = {
            "query": query.text,
            "fields": ",".join(PAPER_FIELDS),
            "offset": str(offset),
            "limit": str(query.max_results),
        }
        year = _year_filter(query)
        if year:
            params["year"] = year
        if query.venue:
            params["venue"] = query.venue
        if query.fields_of_study:
            params["fieldsOfStudy"] = ",".join(query.fields_of_study)

        body = self._get_json(SEARCH_PATH, params, query=query.text)
        rows = list(iter_mappings(body.get("data")))

        warnings: list[str] = []
        hits: list[SearchHit] = []
        dropped = 0
        for item in rows:
            hit = _to_hit(item, rank=len(hits) + 1, query_text=query.text)
            if hit is None:
                dropped += 1
                continue
            hits.append(hit)
        if dropped:
            warnings.append(unmapped_records_warning(SOURCE_NAME, dropped))

        next_offset = as_int(body.get("next"))
        return SearchPage(
            source=SOURCE_NAME,
            query=query,
            hits=tuple(hits),
            next_cursor=str(next_offset) if next_offset is not None and rows else None,
            total_estimate=as_int(body.get("total")),
            incomplete=dropped > 0,
            warnings=tuple(warnings),
        )

    def fetch_references(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        """Works this paper cites, for backward snowballing."""
        paper_id = _paper_id(identifiers)
        return self._graph(paper_id, "references", "citedPaper")

    def fetch_citations(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        """Works citing this paper, for forward snowballing."""
        paper_id = _paper_id(identifiers)
        return self._graph(paper_id, "citations", "citingPaper")

    def _graph(self, paper_id: str, edge: str, neighbour_key: str) -> list[WorkCandidate]:
        source_query = f"{edge} of {paper_id}"
        candidates: list[WorkCandidate] = []
        offset: int | None = 0
        while offset is not None and len(candidates) < MAX_GRAPH_RECORDS:
            limit = min(GRAPH_PAGE_SIZE, MAX_GRAPH_RECORDS - len(candidates))
            body = self._get_json(
                f"/paper/{paper_id}/{edge}",
                {
                    "fields": ",".join(PAPER_FIELDS),
                    "offset": str(offset),
                    "limit": str(limit),
                },
                query=source_query,
            )
            rows = list(iter_mappings(body.get("data")))
            for row in rows:
                candidate = _to_candidate(
                    as_mapping(row.get(neighbour_key)), query_text=source_query
                )
                if candidate is not None:
                    candidates.append(candidate)
            offset = as_int(body.get("next")) if rows else None
        return candidates[:MAX_GRAPH_RECORDS]


def _resolve_api_key(explicit: str | None, env: Mapping[str, str] | None) -> str | None:
    """Explicit key, else the environment variable; never a workspace file (Product 34)."""
    if explicit:
        return explicit
    source: Mapping[str, str] = os.environ if env is None else env
    return source.get(API_KEY_ENV_VAR, "").strip() or None


def _year_filter(query: SearchQuery) -> str:
    if query.year_from is not None and query.year_to is not None:
        return f"{query.year_from}-{query.year_to}"
    if query.year_from is not None:
        return f"{query.year_from}-"
    if query.year_to is not None:
        return f"-{query.year_to}"
    return ""


def _paper_id(identifiers: WorkIdentifiers) -> str:
    """Address the paper by Semantic Scholar id, else by a prefixed external id."""
    if identifiers.semantic_scholar is not None:
        return identifiers.semantic_scholar.value
    doi = normalize_doi(identifiers.doi.value if identifiers.doi else None)
    if doi is not None:
        return f"DOI:{doi}"
    arxiv = normalize_arxiv_id(identifiers.arxiv.value if identifiers.arxiv else None)
    if arxiv is not None:
        return f"arXiv:{arxiv}"
    if identifiers.dblp is not None:
        return f"DBLP:{identifiers.dblp.value}"
    raise NotSupportedError(
        "semantic_scholar needs a Semantic Scholar, DOI, arXiv or DBLP id to expand "
        "the citation graph",
        source=SOURCE_NAME,
    )


def _authors(value: object) -> list[str]:
    return [
        name for name in (clean_text(author.get("name")) for author in iter_mappings(value)) if name
    ]


def _to_hit(item: Mapping[str, Any], *, rank: int, query_text: str) -> SearchHit | None:
    candidate = _to_candidate(item, query_text=query_text)
    if candidate is None:
        return None
    external = as_mapping(item.get("externalIds"))
    raw_id = clean_text(item.get("paperId")) or clean_text(external.get("DOI")) or ""
    return SearchHit(
        candidate=candidate,
        source=SOURCE_NAME,
        rank=rank,
        snippet=snippet_from(item.get("abstract")),
        raw_id=raw_id,
        url=clean_text(item.get("url")),
        open_access_pdf_url=clean_text(as_mapping(item.get("openAccessPdf")).get("url")),
        cited_by_count=as_int(item.get("citationCount")),
    )


def _to_candidate(item: Mapping[str, Any], *, query_text: str) -> WorkCandidate | None:
    paper_id = clean_text(item.get("paperId"))
    title = clean_text(item.get("title"))
    external = as_mapping(item.get("externalIds"))
    doi = normalize_doi(clean_text(external.get("DOI")))
    if paper_id is None and title is None and doi is None:
        return None
    return build_candidate(
        source=SOURCE_NAME,
        raw_id=paper_id or doi or title or "",
        title=title,
        authors=_authors(item.get("authors")),
        year=as_int(item.get("year")),
        venue=clean_text(item.get("venue"))
        or clean_text(as_mapping(item.get("publicationVenue")).get("name")),
        identifiers=work_identifiers(
            doi=doi,
            arxiv=clean_text(external.get("ArXiv")),
            dblp=clean_text(external.get("DBLP")),
            semantic_scholar=paper_id,
        ),
        source_query=query_text,
    )

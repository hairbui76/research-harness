"""DBLP adapter: authoritative computer-science bibliographic keys, no citation graph.

Wire assumptions:

* `GET {base}/search/publ/api?q=&format=json&h=<hits>&f=<first>` -- offset paging, whose
  `f` offset is handed back as the opaque cursor.
* Counters arrive as strings under `result.hits` (`@total`, `@sent`, `@first`), and
  single-element lists are collapsed into bare objects (one author, one hit).
* DBLP publishes no abstracts, no citation counts, and no reference lists, so snippets
  and both citation directions are unavailable rather than empty: `fetch_references` and
  `fetch_citations` raise `NotSupportedError` (ROADMAP Task 12.3 must use another source).
* The free-text API applies no year or venue filter; both are reported as unapplied
  filters in `SearchPage.warnings` instead of being silently ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from research_harness.providers.models.base import EgressDeclaration
from research_harness.providers.search._http import (
    DEFAULT_TIMEOUT_SECONDS,
    HttpSearchProvider,
    endpoint_host,
)
from research_harness.providers.search.base import (
    SearchHit,
    SearchPage,
    SearchProviderCapabilities,
    SearchQuery,
    as_int,
    as_mapping,
    build_candidate,
    clean_text,
    iter_mappings,
    normalize_doi,
    offset_from_cursor,
    unmapped_records_warning,
    unsupported_filter_warning,
    work_identifiers,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "SOURCE_NAME",
    "DblpSearchProvider",
    "default_dblp_capabilities",
]

SOURCE_NAME = "dblp"
DEFAULT_BASE_URL = "https://dblp.org"
SEARCH_PATH = "/search/publ/api"


def default_dblp_capabilities(base_url: str = DEFAULT_BASE_URL) -> SearchProviderCapabilities:
    """DBLP: offset paging only; no year filter and no citation graph."""
    return SearchProviderCapabilities(
        supports_cursor=True,
        supports_year_filter=False,
        supports_references=False,
        supports_citations=False,
        requires_api_key=False,
        egress=EgressDeclaration(
            endpoint_host=endpoint_host(base_url),
            sends_source_text=False,
            sends_identifiers=False,
            description=(
                "Query terms and paging offsets are sent to the DBLP publication search "
                "API. No identifiers and no source text leave the workstation."
            ),
        ),
    )


class DblpSearchProvider(HttpSearchProvider):
    """Discovery against the DBLP publication search API."""

    name = SOURCE_NAME

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        env: Mapping[str, str] | None = None,
        capabilities: SearchProviderCapabilities | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            capabilities=capabilities or default_dblp_capabilities(base_url),
            timeout=timeout,
            transport=transport,
            env=env,
        )

    def search(self, query: SearchQuery) -> SearchPage:
        """One offset page of DBLP publication hits."""
        offset = offset_from_cursor(query.cursor, source=SOURCE_NAME, query=query.text)
        params = {
            "q": query.text,
            "format": "json",
            "h": str(query.max_results),
            "f": str(offset),
        }
        warnings = [
            unsupported_filter_warning(SOURCE_NAME, name)
            for name, requested in (
                ("year", query.year_from is not None or query.year_to is not None),
                ("venue", bool(query.venue)),
                ("fields_of_study", bool(query.fields_of_study)),
            )
            if requested
        ]

        body = self._get_json(SEARCH_PATH, params, query=query.text)
        hits_block = as_mapping(as_mapping(body.get("result")).get("hits"))
        rows = list(iter_mappings(hits_block.get("hit")))

        hits: list[SearchHit] = []
        dropped = 0
        for row in rows:
            hit = _to_hit(row, rank=len(hits) + 1, query_text=query.text)
            if hit is None:
                dropped += 1
                continue
            hits.append(hit)
        if dropped:
            warnings.append(unmapped_records_warning(SOURCE_NAME, dropped))

        total = as_int(hits_block.get("@total"))
        first = as_int(hits_block.get("@first")) or offset
        sent = as_int(hits_block.get("@sent")) or len(rows)
        return SearchPage(
            source=SOURCE_NAME,
            query=query,
            hits=tuple(hits),
            next_cursor=_next_cursor(first=first, sent=sent, total=total),
            total_estimate=total,
            incomplete=dropped > 0,
            warnings=tuple(warnings),
        )


def _next_cursor(*, first: int, sent: int, total: int | None) -> str | None:
    if sent <= 0:
        return None
    nxt = first + sent
    if total is not None and nxt >= total:
        return None
    return str(nxt)


def _to_hit(row: Mapping[str, Any], *, rank: int, query_text: str) -> SearchHit | None:
    info = as_mapping(row.get("info"))
    key = clean_text(info.get("key"))
    title = clean_text(info.get("title"))
    doi = normalize_doi(clean_text(info.get("doi")))
    if key is None and title is None and doi is None:
        return None
    raw_id = key or clean_text(row.get("@id")) or doi or title or ""
    candidate = build_candidate(
        source=SOURCE_NAME,
        raw_id=raw_id,
        title=title,
        authors=_authors(info.get("authors")),
        year=as_int(info.get("year")),
        venue=_venue(info.get("venue")),
        identifiers=work_identifiers(doi=doi, dblp=key),
        source_query=query_text,
    )
    return SearchHit(
        candidate=candidate,
        source=SOURCE_NAME,
        rank=rank,
        snippet=None,
        raw_id=raw_id,
        url=clean_text(info.get("url")) or clean_text(info.get("ee")),
        open_access_pdf_url=_open_access_pdf(info),
        cited_by_count=None,
    )


def _authors(value: object) -> list[str]:
    """`authors.author` is a list, or a bare object when the work has one author."""
    entries = iter_mappings(as_mapping(value).get("author"))
    return [name for name in (clean_text(author.get("text")) for author in entries) if name]


def _venue(value: object) -> str | None:
    """`venue` is a string, or a list for works published in more than one stream."""
    if isinstance(value, list):
        for item in value:
            text = clean_text(item)
            if text is not None:
                return text
        return None
    return clean_text(value)


def _open_access_pdf(info: Mapping[str, Any]) -> str | None:
    """Only an `ee` link that DBLP marks open *and* that is a PDF is reported as one."""
    if clean_text(info.get("access")) != "open":
        return None
    ee = clean_text(info.get("ee"))
    if ee is None or not ee.lower().endswith(".pdf"):
        return None
    return ee

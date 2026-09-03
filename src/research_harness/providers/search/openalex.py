"""OpenAlex adapter: open bibliographic graph with both citation directions.

Wire assumptions:

* `GET {base}/works?search=&per-page=&cursor=*`; later pages echo `meta.next_cursor`.
* `mailto` goes in the parameters as well as the User-Agent (OpenAlex polite pool).
* Dates are filtered with `filter=from_publication_date:,to_publication_date:`, venue
  with `primary_location.source.display_name.search:`.
* Backward references come from the work's `referenced_works` (OpenAlex ids), which are
  then hydrated in batches of `MAX_FILTER_IDS` through `filter=openalex_id:W1|W2|...`.
* Forward citations come from `filter=cites:<openalex id>`, paged by cursor up to
  `MAX_GRAPH_RECORDS`.
* Abstracts arrive as `abstract_inverted_index` and are rebuilt into a snippet here;
  OpenAlex publishes no plain abstract field.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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
    snippet_from,
    unmapped_records_warning,
    unsupported_filter_warning,
    work_identifiers,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "MAX_FILTER_IDS",
    "SOURCE_NAME",
    "OpenAlexSearchProvider",
    "default_openalex_capabilities",
]

SOURCE_NAME = "openalex"
DEFAULT_BASE_URL = "https://api.openalex.org"
WORKS_PATH = "/works"
FIRST_CURSOR = "*"
MAX_FILTER_IDS = 50
"""OpenAlex accepts at most 50 alternatives in one `key:a|b|c` filter."""

_ARXIV_MARKERS = ("arxiv.org/abs/", "arxiv.org/pdf/")


def default_openalex_capabilities(base_url: str = DEFAULT_BASE_URL) -> SearchProviderCapabilities:
    """OpenAlex: cursor paging, date filter, and both citation directions."""
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
                "Query terms, filters and the identifiers being expanded (OpenAlex ids "
                "or DOIs) are sent to the OpenAlex API, with the configured contact "
                "address when one is set. No source text leaves the workstation."
            ),
        ),
    )


class OpenAlexSearchProvider(HttpSearchProvider):
    """Discovery and citation-graph expansion against the OpenAlex API."""

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
            capabilities=capabilities or default_openalex_capabilities(base_url),
            timeout=timeout,
            transport=transport,
            env=env,
        )

    def search(self, query: SearchQuery) -> SearchPage:
        """One cursor page of OpenAlex works matching `query`."""
        warnings: list[str] = []
        params: dict[str, str] = {
            "search": query.text,
            "per-page": str(query.max_results),
            "cursor": query.cursor or FIRST_CURSOR,
        }
        filters = _filters(query)
        if filters:
            params["filter"] = filters
        if query.fields_of_study:
            warnings.append(unsupported_filter_warning(SOURCE_NAME, "fields_of_study"))
        self._add_mailto(params)

        body = self._get_json(WORKS_PATH, params, query=query.text)
        results = list(iter_mappings(body.get("results")))
        meta = as_mapping(body.get("meta"))

        hits: list[SearchHit] = []
        dropped = 0
        for item in results:
            hit = _to_hit(item, rank=len(hits) + 1, query_text=query.text)
            if hit is None:
                dropped += 1
                continue
            hits.append(hit)
        if dropped:
            warnings.append(unmapped_records_warning(SOURCE_NAME, dropped))

        return SearchPage(
            source=SOURCE_NAME,
            query=query,
            hits=tuple(hits),
            next_cursor=clean_text(meta.get("next_cursor")) if results else None,
            total_estimate=as_int(meta.get("count")),
            incomplete=dropped > 0,
            warnings=tuple(warnings),
        )

    def fetch_references(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        """Hydrate the work's `referenced_works` ids into candidates."""
        work = self._resolve_work(identifiers)
        referenced = [
            short_id
            for short_id in (_short_id(value) for value in _as_list(work.get("referenced_works")))
            if short_id is not None
        ][:MAX_GRAPH_RECORDS]
        source_query = f"references of {_short_id(work.get('id')) or ''}".strip()
        candidates: list[WorkCandidate] = []
        for chunk in _chunks(referenced, MAX_FILTER_IDS):
            params = {
                "filter": f"openalex_id:{'|'.join(chunk)}",
                "per-page": str(len(chunk)),
            }
            self._add_mailto(params)
            body = self._get_json(WORKS_PATH, params, query=source_query)
            candidates.extend(
                candidate
                for candidate in (
                    _to_candidate(item, query_text=source_query)
                    for item in iter_mappings(body.get("results"))
                )
                if candidate is not None
            )
        return candidates

    def fetch_citations(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        """Works citing this one, via `filter=cites:`, capped at `MAX_GRAPH_RECORDS`."""
        work = self._resolve_work(identifiers)
        work_id = _short_id(work.get("id"))
        if work_id is None:
            raise NotSupportedError(
                "openalex returned a work without an id; citations cannot be listed",
                source=SOURCE_NAME,
            )
        source_query = f"cites:{work_id}"
        candidates: list[WorkCandidate] = []
        cursor = FIRST_CURSOR
        while cursor and len(candidates) < MAX_GRAPH_RECORDS:
            params = {
                "filter": source_query,
                "per-page": str(min(MAX_GRAPH_RECORDS - len(candidates), MAX_FILTER_IDS)),
                "cursor": cursor,
            }
            self._add_mailto(params)
            body = self._get_json(WORKS_PATH, params, query=source_query)
            page = list(iter_mappings(body.get("results")))
            candidates.extend(
                candidate
                for candidate in (_to_candidate(item, query_text=source_query) for item in page)
                if candidate is not None
            )
            if not page:
                break
            cursor = clean_text(as_mapping(body.get("meta")).get("next_cursor")) or ""
        return candidates[:MAX_GRAPH_RECORDS]

    # --------------------------------------------------------------------- helpers

    def _add_mailto(self, params: dict[str, str]) -> None:
        if self.contact_email:
            params["mailto"] = self.contact_email

    def _resolve_work(self, identifiers: WorkIdentifiers) -> Mapping[str, Any]:
        """Fetch the record addressed by an OpenAlex id, else by DOI."""
        openalex_id = _short_id(identifiers.openalex.value if identifiers.openalex else None)
        doi = normalize_doi(identifiers.doi.value if identifiers.doi else None)
        if openalex_id is not None:
            key = openalex_id
        elif doi is not None:
            key = f"doi:{doi}"
        else:
            raise NotSupportedError(
                "openalex needs an OpenAlex id or a DOI to expand the citation graph",
                source=SOURCE_NAME,
            )
        params: dict[str, str] = {}
        self._add_mailto(params)
        return self._get_json(f"{WORKS_PATH}/{key}", params, query=key)


def _filters(query: SearchQuery) -> str:
    parts: list[str] = []
    if query.year_from is not None:
        parts.append(f"from_publication_date:{query.year_from}-01-01")
    if query.year_to is not None:
        parts.append(f"to_publication_date:{query.year_to}-12-31")
    if query.venue:
        parts.append(f"primary_location.source.display_name.search:{_filter_value(query.venue)}")
    return ",".join(parts)


def _filter_value(value: str) -> str:
    """Commas and pipes separate OpenAlex filter clauses, so they cannot appear in one."""
    return value.replace(",", " ").replace("|", " ").strip()


def _to_hit(item: Mapping[str, Any], *, rank: int, query_text: str) -> SearchHit | None:
    candidate = _to_candidate(item, query_text=query_text)
    if candidate is None:
        return None
    raw_id = _short_id(item.get("id")) or _title(item) or ""
    return SearchHit(
        candidate=candidate,
        source=SOURCE_NAME,
        rank=rank,
        snippet=snippet_from(_abstract(item)),
        raw_id=raw_id,
        url=clean_text(item.get("id")) or clean_text(item.get("doi")),
        open_access_pdf_url=_open_access_pdf(item),
        cited_by_count=as_int(item.get("cited_by_count")),
    )


def _to_candidate(item: Mapping[str, Any], *, query_text: str) -> WorkCandidate | None:
    openalex_id = _short_id(item.get("id"))
    title = _title(item)
    doi = normalize_doi(clean_text(item.get("doi")))
    if openalex_id is None and title is None and doi is None:
        return None
    return build_candidate(
        source=SOURCE_NAME,
        raw_id=openalex_id or doi or title or "",
        title=title,
        authors=_authors(item.get("authorships")),
        year=as_int(item.get("publication_year")),
        venue=_venue(item),
        identifiers=work_identifiers(doi=doi, openalex=openalex_id, arxiv=_arxiv_id(item)),
        source_query=query_text,
    )


def _title(item: Mapping[str, Any]) -> str | None:
    return clean_text(item.get("title")) or clean_text(item.get("display_name"))


def _authors(value: object) -> list[str]:
    names: list[str] = []
    for authorship in iter_mappings(value):
        name = clean_text(as_mapping(authorship.get("author")).get("display_name")) or clean_text(
            authorship.get("raw_author_name")
        )
        if name:
            names.append(name)
    return names


def _venue(item: Mapping[str, Any]) -> str | None:
    primary = as_mapping(item.get("primary_location"))
    venue = clean_text(as_mapping(primary.get("source")).get("display_name"))
    if venue is not None:
        return venue
    return clean_text(as_mapping(item.get("host_venue")).get("display_name"))


def _open_access_pdf(item: Mapping[str, Any]) -> str | None:
    best = as_mapping(item.get("best_oa_location"))
    for candidate in (best.get("pdf_url"), as_mapping(item.get("open_access")).get("oa_url")):
        url = clean_text(candidate)
        if url is not None:
            return url
    return clean_text(as_mapping(item.get("primary_location")).get("pdf_url"))


def _arxiv_id(item: Mapping[str, Any]) -> str | None:
    """arXiv id from a location URL the record itself carries; never guessed."""
    locations: list[Mapping[str, Any]] = list(iter_mappings(item.get("locations")))
    locations.extend(iter_mappings(item.get("primary_location")))
    locations.extend(iter_mappings(item.get("best_oa_location")))
    for location in locations:
        for key in ("landing_page_url", "pdf_url"):
            url = clean_text(location.get(key))
            if url is None:
                continue
            lowered = url.lower()
            for marker in _ARXIV_MARKERS:
                if marker in lowered:
                    tail = url[lowered.index(marker) + len(marker) :]
                    return normalize_arxiv_id(tail.removesuffix(".pdf"))
    return None


def _abstract(item: Mapping[str, Any]) -> str | None:
    """Rebuild OpenAlex's inverted index into running text, in position order."""
    index = as_mapping(item.get("abstract_inverted_index"))
    if not index:
        return clean_text(item.get("abstract"))
    positions: list[tuple[int, str]] = []
    for word, places in index.items():
        if not isinstance(places, list):
            continue
        for place in places:
            offset = as_int(place)
            if offset is not None:
                positions.append((offset, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def _short_id(value: object) -> str | None:
    """`W2741809807` from either the bare id or its `https://openalex.org/...` URL."""
    text = clean_text(value)
    if text is None:
        return None
    tail = text.rsplit("/", 1)[-1]
    return tail or None


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])

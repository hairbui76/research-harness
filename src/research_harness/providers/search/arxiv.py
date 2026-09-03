"""arXiv adapter: preprint discovery from the Atom API (supplementary source).

Wire assumptions:

* `GET {base}/api/query?search_query=&start=&max_results=`; `start` is the opaque cursor.
* The reply is Atom XML, parsed with `xml.etree.ElementTree` and explicit namespaces --
  never with a regex, because entry text is arbitrary author-supplied markup.
* Free text is sent as a conjunction of `all:"term"` clauses, one per term, because
  arXiv reads a quoted run as a literal phrase and a whole research question is a phrase
  no abstract contains (dogfood F1). A double-quoted substring of the caller's text stays
  one phrase clause; submission dates are filtered with
  `submittedDate:[YYYYMMDDHHMM TO ...]`.
* A zero-result page for a query of more than one term is reported in
  `SearchPage.warnings` naming exactly what was sent, so a `SearchRun` can tell a query
  that matched nothing from a query the source could not have matched (Product 18).
* An arXiv id keeps its version suffix (`2101.00001v2`): v1 and v2 are different
  `Version`s of one `Work` (ADR-002), so the suffix is identity, not noise.
* The API reports its own failures as a 200 feed holding a single `api/errors` entry;
  that is a `SearchResponseError`, not a zero-result page.
* arXiv exposes no reference or citation lists, so both graph directions raise
  `NotSupportedError`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping

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
    SearchResponseError,
    as_int,
    build_candidate,
    clean_text,
    degenerate_query_warning,
    normalize_arxiv_id,
    normalize_doi,
    offset_from_cursor,
    query_terms,
    snippet_from,
    unmapped_records_warning,
    unsupported_filter_warning,
    work_identifiers,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "NAMESPACES",
    "SOURCE_NAME",
    "ArxivSearchProvider",
    "default_arxiv_capabilities",
    "search_query_for",
]

SOURCE_NAME = "arxiv"
DEFAULT_BASE_URL = "https://export.arxiv.org"
QUERY_PATH = "/api/query"

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_ERROR_ID_MARKER = "api/errors"


def default_arxiv_capabilities(base_url: str = DEFAULT_BASE_URL) -> SearchProviderCapabilities:
    """arXiv: offset paging and a submission-date filter; no citation graph."""
    return SearchProviderCapabilities(
        supports_cursor=True,
        supports_year_filter=True,
        supports_references=False,
        supports_citations=False,
        requires_api_key=False,
        egress=EgressDeclaration(
            endpoint_host=endpoint_host(base_url),
            sends_source_text=False,
            sends_identifiers=False,
            description=(
                "Query terms, date bounds and paging offsets are sent to the arXiv Atom "
                "API. No identifiers and no source text leave the workstation."
            ),
        ),
    )


class ArxivSearchProvider(HttpSearchProvider):
    """Discovery against the arXiv Atom API."""

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
            capabilities=capabilities or default_arxiv_capabilities(base_url),
            timeout=timeout,
            transport=transport,
            env=env,
            extra_headers={"accept": "application/atom+xml"},
        )

    def search(self, query: SearchQuery) -> SearchPage:
        """One offset page of arXiv entries."""
        start = offset_from_cursor(query.cursor, source=SOURCE_NAME, query=query.text)
        search_query = search_query_for(query)
        params = {
            "search_query": search_query,
            "start": str(start),
            "max_results": str(query.max_results),
        }
        warnings = [
            unsupported_filter_warning(SOURCE_NAME, name)
            for name, requested in (
                ("venue", bool(query.venue)),
                ("fields_of_study", bool(query.fields_of_study)),
            )
            if requested
        ]

        text = self._get_text(QUERY_PATH, params, query=query.text)
        feed = self._parse(text, query_text=query.text)
        entries = feed.findall("atom:entry", NAMESPACES)
        self._raise_on_api_error(entries, query_text=query.text)

        hits: list[SearchHit] = []
        dropped = 0
        for entry in entries:
            hit = _to_hit(entry, rank=len(hits) + 1, query_text=query.text)
            if hit is None:
                dropped += 1
                continue
            hits.append(hit)
        if dropped:
            warnings.append(unmapped_records_warning(SOURCE_NAME, dropped))
        terms = len(query_terms(query.text))
        if not hits and terms > 1:
            warnings.append(degenerate_query_warning(SOURCE_NAME, search_query, terms=terms))

        total = as_int(_text(feed, "opensearch:totalResults"))
        return SearchPage(
            source=SOURCE_NAME,
            query=query,
            hits=tuple(hits),
            next_cursor=_next_cursor(start=start, sent=len(entries), total=total),
            total_estimate=total,
            incomplete=dropped > 0,
            warnings=tuple(warnings),
        )

    def _parse(self, text: str, *, query_text: str) -> ET.Element:
        try:
            return ET.fromstring(text)
        except ET.ParseError as exc:
            raise SearchResponseError(
                f"arxiv returned a body that is not valid Atom XML: {exc}",
                source=SOURCE_NAME,
                query=query_text,
            ) from exc

    def _raise_on_api_error(self, entries: list[ET.Element], *, query_text: str) -> None:
        """arXiv reports malformed queries as a 200 feed with one `api/errors` entry."""
        if len(entries) != 1:
            return
        entry_id = _text(entries[0], "atom:id") or ""
        if _ERROR_ID_MARKER not in entry_id:
            return
        detail = _text(entries[0], "atom:summary") or entry_id
        raise SearchResponseError(
            f"arxiv rejected the query: {detail}", source=SOURCE_NAME, query=query_text
        )


def search_query_for(query: SearchQuery) -> str:
    """The `search_query` this adapter puts on the wire, exposed so a run can record it.

    Every term is AND-ed as its own `all:"term"` clause rather than sent as one phrase:
    `all:"pre-trained transformer encrypted traffic classification"` matches nothing at
    arXiv while the conjunction of its five terms matches the field (dogfood F1). A term
    the caller quoted stays a phrase, which is how a phrase can still be asked for.

    Quoting is not escaping: arXiv's grammar has no escape for a double quote inside a
    phrase, so a stray quote is removed by `query_terms` before the clause is built, and
    `httpx` percent-encodes the result on the wire.
    """
    terms = query_terms(query.text)
    parts = [f'all:"{term}"' for term in terms] or [f'all:"{query.text.strip()}"']
    date_range = _date_range(query)
    if date_range:
        parts.append(date_range)
    return " AND ".join(parts)


def _date_range(query: SearchQuery) -> str:
    if query.year_from is None and query.year_to is None:
        return ""
    start = f"{query.year_from}01010000" if query.year_from is not None else "*"
    end = f"{query.year_to}12312359" if query.year_to is not None else "*"
    return f"submittedDate:[{start} TO {end}]"


def _next_cursor(*, start: int, sent: int, total: int | None) -> str | None:
    if sent <= 0:
        return None
    nxt = start + sent
    if total is not None and nxt >= total:
        return None
    return str(nxt)


def _to_hit(entry: ET.Element, *, rank: int, query_text: str) -> SearchHit | None:
    arxiv_id = normalize_arxiv_id(_text(entry, "atom:id"))
    title = clean_text(_text(entry, "atom:title"))
    if arxiv_id is None and title is None:
        return None
    doi = normalize_doi(_text(entry, "arxiv:doi"))
    raw_id = arxiv_id or title or ""
    candidate = build_candidate(
        source=SOURCE_NAME,
        raw_id=raw_id,
        title=_collapse(title),
        authors=[
            name
            for name in (
                clean_text(author.findtext("atom:name", namespaces=NAMESPACES))
                for author in entry.findall("atom:author", NAMESPACES)
            )
            if name
        ],
        year=_year(entry),
        venue=clean_text(_text(entry, "arxiv:journal_ref")),
        identifiers=work_identifiers(arxiv=arxiv_id, doi=doi),
        source_query=query_text,
    )
    return SearchHit(
        candidate=candidate,
        source=SOURCE_NAME,
        rank=rank,
        snippet=snippet_from(_text(entry, "atom:summary")),
        raw_id=raw_id,
        url=_link(entry, rel="alternate") or clean_text(_text(entry, "atom:id")),
        open_access_pdf_url=_pdf_link(entry),
        cited_by_count=None,
    )


def _text(element: ET.Element, path: str) -> str | None:
    return clean_text(element.findtext(path, namespaces=NAMESPACES))


def _collapse(value: str | None) -> str | None:
    """arXiv wraps long titles across lines; canonical metadata is single-spaced."""
    return " ".join(value.split()) if value is not None else None


def _year(entry: ET.Element) -> int | None:
    """Year of the submission date; never derived from a journal reference."""
    for path in ("atom:published", "atom:updated"):
        stamp = _text(entry, path)
        if stamp and len(stamp) >= 4:
            year = as_int(stamp[:4])
            if year is not None:
                return year
    return None


def _link(entry: ET.Element, *, rel: str) -> str | None:
    for link in entry.findall("atom:link", NAMESPACES):
        if link.get("rel") == rel and link.get("type") != "application/pdf":
            return clean_text(link.get("href"))
    return None


def _pdf_link(entry: ET.Element) -> str | None:
    """arXiv preprints are open access; the PDF link is labelled in the entry."""
    for link in entry.findall("atom:link", NAMESPACES):
        if link.get("type") == "application/pdf" or link.get("title") == "pdf":
            return clean_text(link.get("href"))
    return None

"""Crossref adapter: DOI-registered metadata and publisher reference lists.

Wire assumptions, so drift is easy to spot:

* `GET {base}/works?query=&rows=&cursor=*` -- deep paging is cursor-based; the first
  page asks for `cursor=*` and every later page echoes `message.next-cursor`.
* `mailto` is sent as a parameter as well as in the User-Agent: it is what Crossref uses
  to put a caller in the polite pool.
* Year filtering uses `filter=from-pub-date:YYYY-01-01,until-pub-date:YYYY-12-31`, venue
  filtering uses `query.container-title`.
* References come from `GET {base}/works/{doi}` -> `message.reference`, a
  publisher-deposited list that is frequently partial or unstructured; entries without a
  DOI and without a title are dropped rather than reconstructed.
* Crossref asserts no open access, so a PDF link is reported only when the record itself
  says it is free to read or carries a Creative Commons license.
"""

from __future__ import annotations

import logging
from collections import Counter
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
    NotSupportedError,
    ReferenceCandidates,
    SearchHit,
    SearchPage,
    SearchProviderCapabilities,
    SearchQuery,
    as_int,
    as_mapping,
    build_candidate,
    clean_text,
    iter_mappings,
    looks_like_reference,
    normalize_doi,
    reference_drop_warning,
    snippet_from,
    unmapped_records_warning,
    unsupported_filter_warning,
    work_identifiers,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DROP_FRAGMENT",
    "DROP_UNIDENTIFIABLE",
    "SOURCE_NAME",
    "CrossrefSearchProvider",
    "default_crossref_capabilities",
]

logger = logging.getLogger(__name__)

SOURCE_NAME = "crossref"
DEFAULT_BASE_URL = "https://api.crossref.org"
WORKS_PATH = "/works"
FIRST_CURSOR = "*"

DROP_FRAGMENT = "reference fragment(s)"
"""A deposited free-text string that is a piece of a reference, not a whole one."""
DROP_UNIDENTIFIABLE = "record(s) with neither a title nor a DOI"
"""A deposited record that names nothing at all; there is no work to seed from it."""


def default_crossref_capabilities(base_url: str = DEFAULT_BASE_URL) -> SearchProviderCapabilities:
    """Crossref: cursor paging, year filter, backward references, no forward citations."""
    return SearchProviderCapabilities(
        supports_cursor=True,
        supports_year_filter=True,
        supports_references=True,
        supports_citations=False,
        requires_api_key=False,
        egress=EgressDeclaration(
            endpoint_host=endpoint_host(base_url),
            sends_source_text=False,
            sends_identifiers=True,
            description=(
                "Query terms, filters and (for reference lookups) DOIs are sent to the "
                "Crossref REST API, together with the configured contact address when "
                "one is set. No source text or local file content leaves the workstation."
            ),
        ),
    )


class CrossrefSearchProvider(HttpSearchProvider):
    """Discovery against the Crossref REST API."""

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
            capabilities=capabilities or default_crossref_capabilities(base_url),
            timeout=timeout,
            transport=transport,
            env=env,
        )

    def search(self, query: SearchQuery) -> SearchPage:
        """One cursor page of Crossref works matching `query`."""
        warnings: list[str] = []
        params: dict[str, str] = {
            "query": query.text,
            "rows": str(query.max_results),
            "cursor": query.cursor or FIRST_CURSOR,
        }
        date_filter = _date_filter(query)
        if date_filter:
            params["filter"] = date_filter
        if query.venue:
            params["query.container-title"] = query.venue
        if query.fields_of_study:
            warnings.append(unsupported_filter_warning(SOURCE_NAME, "fields_of_study"))
        if self.contact_email:
            params["mailto"] = self.contact_email

        body = self._get_json(WORKS_PATH, params, query=query.text)
        message = as_mapping(body.get("message"))
        items = list(iter_mappings(message.get("items")))

        hits: list[SearchHit] = []
        dropped = 0
        for item in items:
            hit = self._to_hit(item, rank=len(hits) + 1, query=query)
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
            next_cursor=clean_text(message.get("next-cursor")) if items else None,
            total_estimate=as_int(message.get("total-results")),
            incomplete=dropped > 0,
            warnings=tuple(warnings),
        )

    def fetch_references(self, identifiers: WorkIdentifiers) -> ReferenceCandidates:
        """Publisher-deposited reference list of the DOI, for backward snowballing.

        A reference list segmented badly deposits its pieces, and each piece would become a
        seed and land in a coverage denominator; the gate that stops that is silent unless
        the count comes back with the results (dogfood F10).
        """
        doi = _require_doi(identifiers)
        body = self._get_json(f"{WORKS_PATH}/{doi}", {}, query=doi)
        message = as_mapping(body.get("message"))
        candidates: list[WorkCandidate] = []
        drops: Counter[str] = Counter()
        deposited = 0
        for index, entry in enumerate(iter_mappings(message.get("reference")), start=1):
            deposited += 1
            candidate = _reference_candidate(entry, parent_doi=doi, index=index, drops=drops)
            if candidate is not None:
                candidates.append(candidate)
        warnings = (
            (reference_drop_warning(SOURCE_NAME, deposited=deposited, dropped=dict(drops)),)
            if drops
            else ()
        )
        return ReferenceCandidates(candidates, warnings=warnings)

    # --------------------------------------------------------------------- mapping

    def _to_hit(
        self, item: Mapping[str, Any], *, rank: int, query: SearchQuery
    ) -> SearchHit | None:
        doi = normalize_doi(clean_text(item.get("DOI")))
        title = _first_text(item.get("title"))
        if doi is None and title is None:
            return None
        raw_id = doi or title or ""
        candidate = build_candidate(
            source=SOURCE_NAME,
            raw_id=raw_id,
            title=title,
            authors=_authors(item.get("author")),
            year=_year(item),
            venue=_first_text(item.get("container-title"))
            or _first_text(item.get("short-container-title")),
            identifiers=work_identifiers(doi=doi),
            source_query=query.text,
        )
        return SearchHit(
            candidate=candidate,
            source=SOURCE_NAME,
            rank=rank,
            snippet=snippet_from(item.get("abstract")),
            raw_id=raw_id,
            url=clean_text(item.get("URL")),
            open_access_pdf_url=_open_access_pdf(item),
            cited_by_count=as_int(item.get("is-referenced-by-count")),
        )


def _require_doi(identifiers: WorkIdentifiers) -> str:
    doi = normalize_doi(identifiers.doi.value if identifiers.doi else None)
    if doi is None:
        raise NotSupportedError(
            "crossref can only follow references from a DOI; none was supplied",
            source=SOURCE_NAME,
        )
    return doi


def _date_filter(query: SearchQuery) -> str:
    parts: list[str] = []
    if query.year_from is not None:
        parts.append(f"from-pub-date:{query.year_from}-01-01")
    if query.year_to is not None:
        parts.append(f"until-pub-date:{query.year_to}-12-31")
    return ",".join(parts)


def _first_text(value: object) -> str | None:
    """Crossref returns most human-readable fields as a list of strings."""
    if isinstance(value, list):
        for item in value:
            text = clean_text(item)
            if text is not None:
                return text
        return None
    return clean_text(value)


def _authors(value: object) -> list[str]:
    names: list[str] = []
    for entry in iter_mappings(value):
        given = clean_text(entry.get("given"))
        family = clean_text(entry.get("family"))
        if given and family:
            names.append(f"{given} {family}")
            continue
        name = family or given or clean_text(entry.get("name"))
        if name:
            names.append(name)
    return names


_DATE_KEYS = ("issued", "published", "published-print", "published-online", "created")


def _year(item: Mapping[str, Any]) -> int | None:
    """First four-digit year in the record's date parts; never inferred from anything else."""
    for key in _DATE_KEYS:
        parts = as_mapping(item.get(key)).get("date-parts")
        if not isinstance(parts, list):
            continue
        for group in parts:
            if isinstance(group, list) and group:
                year = as_int(group[0])
                if year is not None:
                    return year
    return None


def _is_free_to_read(item: Mapping[str, Any]) -> bool:
    if "free-to-read" in item:
        return True
    return any(
        "creativecommons.org" in (clean_text(licence.get("URL")) or "").lower()
        for licence in iter_mappings(item.get("license"))
    )


def _open_access_pdf(item: Mapping[str, Any]) -> str | None:
    """Only report a PDF the record itself says is freely readable."""
    if not _is_free_to_read(item):
        return None
    for link in iter_mappings(item.get("link")):
        if clean_text(link.get("content-type")) == "application/pdf":
            return clean_text(link.get("URL"))
    return None


def _reference_candidate(
    entry: Mapping[str, Any], *, parent_doi: str, index: int, drops: Counter[str]
) -> WorkCandidate | None:
    """One deposited reference as a candidate, or ``None`` when it is only a fragment.

    A structured `article-title`/`volume-title` is the publisher's own assertion that the
    string is a title, so it is taken as one. A bare `unstructured` string is raw text that
    may be half a reference, and is admitted only when it reads like a whole one
    (dogfood F10) -- unless the entry carries a DOI, which resolves regardless. Every
    refusal is counted in ``drops`` under the reason for it, so the caller can report what
    its seeds leave out.
    """
    doi = normalize_doi(clean_text(entry.get("DOI")))
    author = clean_text(entry.get("author"))
    year = as_int(entry.get("year"))
    title = clean_text(entry.get("article-title")) or clean_text(entry.get("volume-title"))
    fragment = False
    if title is None:
        raw = clean_text(entry.get("unstructured"))
        if raw is not None and (doi is not None or looks_like_reference(raw, year=year)):
            title = raw
        elif raw is not None:
            fragment = True
            logger.debug(
                "dropping a reference fragment deposited for %s: %r", parent_doi, raw[:120]
            )
    if doi is None and title is None:
        drops[DROP_FRAGMENT if fragment else DROP_UNIDENTIFIABLE] += 1
        return None
    key = clean_text(entry.get("key")) or str(index)
    return build_candidate(
        source=SOURCE_NAME,
        raw_id=f"{parent_doi}#{key}",
        title=title,
        authors=[author] if author else [],
        year=year,
        venue=clean_text(entry.get("journal-title")),
        identifiers=work_identifiers(doi=doi),
        source_query=f"references of {parent_doi}",
    )

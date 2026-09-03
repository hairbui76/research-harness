"""In-memory discovery sources for the discovery tests: no network, no keys, no recordings.

Each source is a list of pages (and optionally a reference table for snowballing), so a
test can say exactly what a source returns, how many pages it has, and how it breaks. A
source can also be `heal()`ed, which is what makes "the rerun finished what the first run
could not" testable without a second fixture, and it can carry `warnings`, which is how a
page that completed but has something to say about the query it was asked is exercised.
"""

from __future__ import annotations

from collections.abc import Sequence

from research_harness.domain.base import Provenance
from research_harness.domain.enums import ProvenanceSource
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.providers.models.base import EgressDeclaration
from research_harness.providers.search.base import (
    NotSupportedError,
    ReferenceCandidates,
    SearchHit,
    SearchPage,
    SearchProvider,
    SearchProviderCapabilities,
    SearchProviderError,
    SearchQuery,
)

EGRESS = EgressDeclaration(
    endpoint_host="fake.invalid",
    sends_source_text=False,
    sends_identifiers=True,
    description="in-memory discovery source",
)

EXTERNAL = ProvenanceSource.EXTERNAL_METADATA


def field(value: str, source: str) -> IdentifierField:
    """One metadata value carrying the provenance of the source that reported it."""
    return IdentifierField(value=value, source=EXTERNAL, note=f"record from {source}")


def record(
    source: str,
    *,
    doi: str | None = None,
    arxiv: str | None = None,
    title: str | None = None,
    year: int | None = None,
    authors: Sequence[str] = (),
) -> WorkCandidate:
    """A candidate exactly as one source would map it; nothing is invented."""
    return WorkCandidate(
        provenance=Provenance(source=EXTERNAL, actor=source),
        metadata=CandidateMetadata(
            title=field(title, source) if title else None,
            authors=tuple(field(name, source) for name in authors),
            year=field(str(year), source) if year is not None else None,
            identifiers=WorkIdentifiers(
                doi=field(doi, source) if doi else None,
                arxiv=field(arxiv, source) if arxiv else None,
            ),
        ),
        source_query="fake",
    )


class FakeSearchSource(SearchProvider):
    """A discovery source with a fixed page list, an optional break, and an optional graph."""

    def __init__(
        self,
        name: str,
        pages: Sequence[Sequence[WorkCandidate]] = (),
        *,
        error: SearchProviderError | None = None,
        open_access: bool = False,
        references: dict[str, list[WorkCandidate]] | None = None,
        citations: dict[str, list[WorkCandidate]] | None = None,
        warnings: Sequence[str] = (),
    ) -> None:
        self.name = name
        self._pages = [tuple(page) for page in pages]
        self._error = error
        self._warnings = tuple(warnings)
        self._open_access = open_access
        self._references = references or {}
        self._citations = citations or {}
        self.searches: list[str | None] = []

    def heal(self) -> None:
        """Stop failing; the next search of this source completes."""
        self._error = None

    def capabilities(self) -> SearchProviderCapabilities:
        return SearchProviderCapabilities(
            supports_cursor=True,
            supports_year_filter=True,
            supports_references=bool(self._references),
            supports_citations=bool(self._citations),
            requires_api_key=False,
            egress=EGRESS,
        )

    def search(self, query: SearchQuery) -> SearchPage:
        self.searches.append(query.cursor)
        if self._error is not None:
            raise self._error
        index = 0 if query.cursor is None else int(query.cursor)
        page = self._pages[index] if index < len(self._pages) else ()
        following = index + 1
        return SearchPage(
            source=self.name,
            query=query,
            hits=tuple(
                SearchHit(
                    candidate=candidate,
                    source=self.name,
                    rank=rank,
                    raw_id=f"{self.name}-{index}-{rank}",
                    open_access_pdf_url=(
                        f"https://fake.invalid/{self.name}/{index}/{rank}.pdf"
                        if self._open_access
                        else None
                    ),
                )
                for rank, candidate in enumerate(page, start=1)
            ),
            next_cursor=str(following) if following < len(self._pages) else None,
            warnings=self._warnings,
        )

    def fetch_references(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        return self._graph(self._references, identifiers, "reference list")

    def fetch_citations(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        return self._graph(self._citations, identifiers, "forward citations")

    def _graph(
        self,
        table: dict[str, list[WorkCandidate]],
        identifiers: WorkIdentifiers,
        what: str,
    ) -> list[WorkCandidate]:
        if not table:
            raise NotSupportedError(f"{self.name} publishes no {what}", source=self.name)
        if self._error is not None:
            raise self._error
        for name in ("doi", "arxiv"):
            found: IdentifierField | None = getattr(identifiers, name)
            if found is not None and found.value in table:
                entries = table[found.value]
                # A `ReferenceCandidates` carries the adapter's drop counts; a copy loses them.
                return entries if isinstance(entries, ReferenceCandidates) else list(entries)
        return []

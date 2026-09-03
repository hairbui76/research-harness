"""Neutral discovery contract: one query, one page, one candidate shape (Product 17).

Discovery is not evidence. A `SearchHit` says only that some external index believes a
work exists and might be relevant; its snippet was written by that index, not read from
an artifact this workstation holds, so it can never be anchored and never becomes
Evidence (Product 14, 17; ROADMAP Task 12.1). `SearchHit.is_evidence` is a frozen
`Literal[False]` marker that states this in the type system: there is no value of the
field that turns a hit into support for a claim.

Outcomes are deliberately separated, because coverage claims depend on the difference
(Product 18): a query that legitimately matched nothing returns a `SearchPage` with no
hits, while an unusable source raises a `SearchProviderError` subclass naming *why* it
was unusable. `to_source_failure` turns such an error into the `SourceFailure` that a
`SearchRun` persists, so "we searched and found nothing" is never recorded as "we could
not search".

Every mapped record becomes a `WorkCandidate` whose metadata fields each carry
`external_metadata` provenance naming the provider and the raw record id. Adapters never
invent a DOI, a year, or a venue: a field the source did not supply stays `None`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_harness.domain.base import NonEmptyStr, Provenance, UtcDatetime, utc_now
from research_harness.domain.enums import ProvenanceSource, ScreeningState
from research_harness.domain.errors import ProviderError
from research_harness.domain.research import SourceFailure
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.providers.models.base import EgressDeclaration

__all__ = [
    "MAX_GRAPH_RECORDS",
    "MAX_PUBLICATION_YEAR",
    "MAX_RESULTS_PER_PAGE",
    "MIN_PUBLICATION_YEAR",
    "MIN_REFERENCE_WORDS",
    "REFERENCE_DROP_WARNING_PREFIX",
    "SNIPPET_MAX_CHARS",
    "ZERO_RESULT_WARNING_PREFIX",
    "NotSupportedError",
    "ReferenceCandidates",
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
    "UnknownSearchProviderError",
    "as_int",
    "as_mapping",
    "build_candidate",
    "clean_text",
    "degenerate_query_warning",
    "external_provenance",
    "identifier_field",
    "iter_mappings",
    "looks_like_reference",
    "normalize_arxiv_id",
    "normalize_doi",
    "offset_from_cursor",
    "query_terms",
    "reference_drop_warning",
    "reference_warnings",
    "snippet_from",
    "to_source_failure",
    "unmapped_records_warning",
    "unsupported_filter_warning",
    "work_identifiers",
]

MAX_RESULTS_PER_PAGE = 100
"""Ceiling on one page. Every supported source refuses or truncates more than this."""

SNIPPET_MAX_CHARS = 500
"""Discovery hints are truncated: they are for triage, never for quotation."""

#: Bounds `Work.year` accepts. A 4-digit number outside them -- `6010`, `7811` -- is a page
#: range or a paper count, never a publication year.
MIN_PUBLICATION_YEAR = 1400
MAX_PUBLICATION_YEAR = 2200

MIN_REFERENCE_WORDS = 4
"""Fewer words than this and a raw reference string is a fragment, not a reference."""

ZERO_RESULT_WARNING_PREFIX = "zero_result_query:"
"""Machine-groupable prefix so coverage can discount a zero that a query shape produced."""

REFERENCE_DROP_WARNING_PREFIX = "reference_drops:"
"""Machine-groupable prefix for records a citation-graph call refused to make into seeds."""

MAX_GRAPH_RECORDS = 200
"""Ceiling on one `fetch_references`/`fetch_citations` call.

Forward citation lists are unbounded; snowballing that needs the whole list belongs in a
paged `SearchRun` (Task 12.2), not in a single blocking call."""


# --------------------------------------------------------------------------- errors


class SearchProviderError(ProviderError):
    """A discovery source could not answer. Never raised for a legitimate zero result.

    `kind` is a stable, machine-groupable label that survives into the `SourceFailure`
    a `SearchRun` persists, so coverage reporting does not have to parse messages.
    """

    kind: ClassVar[str] = "provider_error"

    def __init__(
        self, message: str, *, source: str | None = None, query: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.source = source
        self.query = query

    @property
    def reason(self) -> str:
        """`kind: message`, the text recorded on a `SourceFailure`."""
        return f"{self.kind}: {self.message}"


class SearchRateLimitError(SearchProviderError):
    """The source throttled the query (HTTP 429); the slice was not searched."""

    kind: ClassVar[str] = "rate_limit"

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        query: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, source=source, query=query)
        self.retry_after = retry_after

    @property
    def reason(self) -> str:
        """Includes the advertised wait so a resumed run can honour it."""
        if self.retry_after is None:
            return super().reason
        return f"{super().reason} (retry after {self.retry_after:g}s)"


class SearchAuthError(SearchProviderError):
    """Credentials are missing, rejected, or insufficient for this source."""

    kind: ClassVar[str] = "auth"


class SearchAccessBarrierError(SearchProviderError):
    """The source served a barrier instead of data: captcha, challenge, or an HTML wall.

    Distinct from `SearchAuthError` because no key fixes it and distinct from a zero
    result because nothing was actually searched (ROADMAP Task 12.1).
    """

    kind: ClassVar[str] = "access_barrier"


class SearchTransportError(SearchProviderError):
    """Timeout, connection failure, or source-side 5xx: the query never completed."""

    kind: ClassVar[str] = "transport"


class SearchResponseError(SearchProviderError):
    """The source answered with something unparsable or structurally unexpected."""

    kind: ClassVar[str] = "malformed_response"


class NotSupportedError(SearchProviderError):
    """This source cannot perform the requested operation for this input.

    Raised by `fetch_references`/`fetch_citations` on sources that publish no such graph,
    and when the given identifiers contain nothing the source can address. Declared in
    advance by `SearchProviderCapabilities`, so a caller can avoid it rather than catch it.
    """

    kind: ClassVar[str] = "not_supported"


class UnknownSearchProviderError(SearchProviderError):
    """A source name was requested that this registry does not hold."""

    kind: ClassVar[str] = "unknown_source"


def to_source_failure(
    error: SearchProviderError,
    source: str,
    *,
    query: str | None = None,
    incomplete: bool = False,
) -> SourceFailure:
    """Convert a provider error into the `SourceFailure` a `SearchRun` persists.

    `incomplete` is the caller's knowledge, not the error's: pass True when some pages
    of this query did succeed before the failure, so coverage reads "partial" rather
    than "nothing" (ROADMAP Task 12.2).
    """
    return SourceFailure(
        source=source,
        query=query if query is not None else error.query,
        reason=error.reason,
        incomplete=incomplete,
    )


# -------------------------------------------------------------------------- contract


class SearchQuery(BaseModel):
    """One slice of a discovery search, identical for every source.

    `cursor` is opaque and source-specific: it is whatever `SearchPage.next_cursor` of
    the previous page carried, and is echoed back unchanged. Filters a source cannot
    honour are reported in `SearchPage.warnings` rather than silently dropped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: NonEmptyStr
    year_from: int | None = Field(default=None, ge=1400, le=2200)
    year_to: int | None = Field(default=None, ge=1400, le=2200)
    venue: str | None = None
    max_results: int = Field(default=25, ge=1, le=MAX_RESULTS_PER_PAGE)
    cursor: str | None = None
    fields_of_study: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _years_are_ordered(self) -> SearchQuery:
        low, high = self.year_from, self.year_to
        if low is not None and high is not None and low > high:
            raise ValueError("year_from must not be later than year_to")
        return self

    def at_cursor(self, cursor: str | None) -> SearchQuery:
        """The same query positioned at `cursor`; used to walk pages."""
        return self.model_copy(update={"cursor": cursor})


class SearchHit(BaseModel):
    """One discovery hint from one source. Never evidence, by construction.

    `snippet` is third-party index text (an abstract or a highlighted fragment). It has
    no artifact, no page, and no character offsets, so it cannot be anchored and must
    never be promoted into Evidence (Product 17; ROADMAP Task 12.1). `is_evidence` is
    pinned to `False` and the model is frozen, so no caller can flip it.

    `rank` is the 1-based position *within this page* as the source ordered it; combine
    it with the page's cursor to reconstruct a global ordering.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: WorkCandidate
    source: NonEmptyStr
    rank: int = Field(ge=1)
    snippet: str | None = None
    raw_id: NonEmptyStr
    url: str | None = None
    open_access_pdf_url: str | None = None
    cited_by_count: int | None = Field(default=None, ge=0)
    is_evidence: Literal[False] = False


class SearchPage(BaseModel):
    """One page of results, plus everything needed to judge how complete it is.

    A successful search that matched nothing is this object with an empty `hits` tuple
    and `incomplete=False`; a source that could not be searched raises instead.
    `incomplete=True` means this page is knowingly partial -- records the adapter could
    not map, or a slice the source truncated -- and `warnings` says which.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: NonEmptyStr
    query: SearchQuery
    hits: tuple[SearchHit, ...] = ()
    next_cursor: str | None = None
    total_estimate: int | None = Field(default=None, ge=0)
    executed_at: UtcDatetime = Field(default_factory=utc_now)
    incomplete: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def candidates(self) -> tuple[WorkCandidate, ...]:
        """The candidates of this page, in rank order."""
        return tuple(hit.candidate for hit in self.hits)


class ReferenceCandidates(list[WorkCandidate]):
    """What one citation-graph call mapped, carrying what it refused to map.

    `fetch_references` and `fetch_citations` return a plain `list[WorkCandidate]`, which
    has nowhere to say that a publisher deposited 45 references and 400 fragments of them
    (dogfood F10). This is that list, plus `warnings`: a caller that only iterates sees no
    difference, and `reference_warnings` reads the counts back so a snowball run can report
    what its coverage denominator does *not* include.
    """

    def __init__(
        self, entries: Iterable[WorkCandidate] = (), *, warnings: Sequence[str] = ()
    ) -> None:
        super().__init__(entries)
        self.warnings: tuple[str, ...] = tuple(warnings)


def reference_warnings(entries: Sequence[WorkCandidate]) -> tuple[str, ...]:
    """Warnings a graph call attached to its results; a plain list carries none."""
    return entries.warnings if isinstance(entries, ReferenceCandidates) else ()


def reference_drop_warning(source: str, *, deposited: int, dropped: Mapping[str, int]) -> str:
    """Uniform wording for records a graph call would not turn into seeds.

    ``dropped`` is reason -> count, so the run says *why* a denominator is smaller than the
    deposited reference list rather than leaving the difference to be inferred.
    """
    detail = ", ".join(f"{count} {reason}" for reason, count in sorted(dropped.items()))
    return (
        f"{REFERENCE_DROP_WARNING_PREFIX} {source} deposited {deposited} record(s); "
        f"{detail} were not made into seeds"
    )


class SearchProviderCapabilities(BaseModel):
    """What a discovery source can do, and what leaves the workstation to use it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supports_cursor: bool
    supports_year_filter: bool
    supports_references: bool
    supports_citations: bool
    requires_api_key: bool
    egress: EgressDeclaration


class SearchProvider(ABC):
    """One external discovery source behind the neutral contract.

    `search` is mandatory; the citation-graph methods default to raising
    `NotSupportedError` so a source that publishes no reference list simply inherits the
    honest answer (ROADMAP Task 12.3 consumes both).
    """

    name: str

    @abstractmethod
    def capabilities(self) -> SearchProviderCapabilities:
        """What this source supports and what calling it discloses (Product 34)."""

    @abstractmethod
    def search(self, query: SearchQuery) -> SearchPage:
        """Run one page of `query`; zero matches is an empty page, not an error."""

    def fetch_references(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        """Works this one cites, for backward snowballing (Product 17).

        An adapter that drops records it will not vouch for returns a `ReferenceCandidates`
        rather than a bare list, so the count reaches the run that walks it (dogfood F10).
        """
        raise NotSupportedError(f"{self.name} publishes no reference list", source=self.name)

    def fetch_citations(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        """Works citing this one, for forward snowballing (Product 17)."""
        raise NotSupportedError(f"{self.name} publishes no forward citations", source=self.name)


class SearchProviderRegistry:
    """Name-addressed set of configured sources, with their egress on the record.

    Keeps declaration order so a `SearchRun` records sources deterministically.
    """

    def __init__(self, providers: Iterable[SearchProvider]) -> None:
        self._providers: dict[str, SearchProvider] = {}
        for provider in providers:
            if provider.name in self._providers:
                raise ValueError(f"duplicate search provider name {provider.name!r}")
            self._providers[provider.name] = provider

    @property
    def names(self) -> tuple[str, ...]:
        """Configured source names, in declaration order."""
        return tuple(self._providers)

    def get(self, name: str) -> SearchProvider:
        """The named source, or `UnknownSearchProviderError` listing what is configured."""
        try:
            return self._providers[name]
        except KeyError as exc:
            known = ", ".join(self._providers) or "none"
            raise UnknownSearchProviderError(
                f"unknown search source {name!r}; configured: {known}", source=name
            ) from exc

    def select(self, names: Sequence[str] | None = None) -> tuple[SearchProvider, ...]:
        """The named sources, or every configured source when `names` is None."""
        if names is None:
            return tuple(self._providers.values())
        return tuple(self.get(name) for name in names)

    def egress(self) -> dict[str, EgressDeclaration]:
        """Per-source egress declarations, for the disclosure surface of Product 34."""
        return {name: provider.capabilities().egress for name, provider in self._providers.items()}

    def as_dict(self) -> dict[str, SearchProvider]:
        """A plain mapping copy, for callers that prefer one."""
        return dict(self._providers)

    def close(self) -> None:
        """Release every source's connection pool."""
        for provider in self._providers.values():
            closer = getattr(provider, "close", None)
            if callable(closer):
                closer()

    def __contains__(self, name: object) -> bool:
        return name in self._providers

    def __iter__(self) -> Iterator[SearchProvider]:
        return iter(self._providers.values())

    def __len__(self) -> int:
        return len(self._providers)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# ------------------------------------------------------------------ candidate mapping


def external_provenance(source: str, raw_id: str) -> Provenance:
    """`external_metadata` provenance naming the source and the raw record id.

    The raw id is what makes a candidate re-fetchable from the source it came from, so
    it is recorded rather than the human-readable title.
    """
    return Provenance(
        source=ProvenanceSource.EXTERNAL_METADATA,
        actor=source,
        note=f"record {raw_id}",
    )


def identifier_field(
    value: str | None, *, confidence: float | None = None
) -> IdentifierField | None:
    """An `external_metadata` identifier field, or `None` when the source said nothing."""
    cleaned = clean_text(value)
    if cleaned is None:
        return None
    return IdentifierField(
        value=cleaned, source=ProvenanceSource.EXTERNAL_METADATA, confidence=confidence
    )


def work_identifiers(
    *,
    doi: str | None = None,
    arxiv: str | None = None,
    dblp: str | None = None,
    semantic_scholar: str | None = None,
    openalex: str | None = None,
) -> WorkIdentifiers:
    """External identifiers, normalized where a canonical form exists, else dropped."""
    return WorkIdentifiers(
        doi=identifier_field(normalize_doi(doi)),
        arxiv=identifier_field(normalize_arxiv_id(arxiv)),
        dblp=identifier_field(dblp),
        semantic_scholar=identifier_field(semantic_scholar),
        openalex=identifier_field(openalex),
    )


def build_candidate(
    *,
    source: str,
    raw_id: str,
    title: str | None = None,
    authors: Sequence[str] = (),
    year: int | None = None,
    venue: str | None = None,
    identifiers: WorkIdentifiers | None = None,
    source_query: str | None = None,
) -> WorkCandidate:
    """A discovered candidate: every stated field provenance-carrying, nothing invented.

    Candidates start `discovered`/`unresolved`; screening (Product 14) and identity
    resolution (Product 13) happen later and elsewhere.
    """
    metadata = CandidateMetadata(
        title=identifier_field(title),
        authors=tuple(
            field for field in (identifier_field(author) for author in authors) if field is not None
        ),
        year=identifier_field(str(year) if year is not None else None),
        venue=identifier_field(venue),
        identifiers=identifiers if identifiers is not None else WorkIdentifiers(),
    )
    return WorkCandidate(
        provenance=external_provenance(source, raw_id),
        metadata=metadata,
        screening=ScreeningState.DISCOVERED,
        source_query=clean_text(source_query),
    )


# --------------------------------------------------------------------- value helpers


def offset_from_cursor(cursor: str | None, *, source: str, query: str | None = None) -> int:
    """Decode an offset-shaped cursor, or refuse it.

    Offset-paged sources (Semantic Scholar, DBLP, arXiv) hand out their next offset as
    the opaque `next_cursor`; anything else was not produced by this adapter and paging
    from it would silently re-read page one.
    """
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise SearchProviderError(
            f"{source} cursor {cursor!r} is not an offset produced by this source",
            source=source,
            query=query,
        ) from exc
    if offset < 0:
        raise SearchProviderError(
            f"{source} cursor {cursor!r} is negative", source=source, query=query
        )
    return offset


def unsupported_filter_warning(source: str, filter_name: str) -> str:
    """Uniform wording for a filter the caller asked for and the source cannot apply."""
    return f"{source} cannot apply the {filter_name} filter; results are unfiltered on it"


def query_terms(text: str) -> tuple[str, ...]:
    """Free text split, in order, into the terms a boolean source should AND together.

    A double-quoted run stays one term -- the researcher asked for that phrase -- and
    everything else becomes one term per word, because wrapping a whole question in
    quotes asks an index for a literal phrase that no abstract contains (dogfood F1).
    Punctuation that is only sentence furniture is stripped; a hyphen or a slash inside a
    word is not, because `pre-trained` and `cs/0101001` are single terms. An unclosed
    quote is treated as ordinary text rather than swallowing the rest of the query.
    """
    terms: list[str] = []
    rest = text
    while rest:
        opening = rest.find('"')
        closing = rest.find('"', opening + 1) if opening >= 0 else -1
        if opening < 0 or closing < 0:
            terms.extend(_WORD.findall(rest))
            break
        terms.extend(_WORD.findall(rest[:opening]))
        terms.append(rest[opening + 1 : closing])
        rest = rest[closing + 1 :]
    trimmed = (_trimmed(term) for term in terms)
    return tuple(dict.fromkeys(term for term in trimmed if term))


def degenerate_query_warning(source: str, sent: str, *, terms: int) -> str:
    """Uniform wording for a zero-result page that a multi-term query may have caused.

    Product 18 (and dogfood F1): a source that reports zero for a query it may have read
    as one literal phrase is not evidence that nothing exists, so the page says exactly
    what went on the wire and the run records it beside the exhausted cursor.
    """
    return (
        f"{ZERO_RESULT_WARNING_PREFIX} {source} returned no records for a {terms}-term "
        f"query; the query sent was: {sent}"
    )


def unmapped_records_warning(source: str, dropped: int) -> str:
    """Uniform wording for records the adapter refused to invent metadata for."""
    return (
        f"{source} returned {dropped} record(s) with neither a title nor an identifier; "
        "they were dropped rather than guessed at"
    )


def looks_like_reference(text: str, *, year: int | None = None) -> bool:
    """True when a raw, unstructured reference string is a whole reference, not a fragment.

    Publishers deposit reference lists as free text, and a bibliography whose entries were
    segmented badly deposits the pieces: `international conference on learning
    representations`, or a run of page numbers with the tail of one entry and the head of
    the next. Each piece has a title-shaped string and nothing else, so each becomes a
    "work" -- one dogfood run turned 45 references into 474 seeds and every one of them
    landed in a coverage denominator (F10).

    The test is deliberately crude and one-sided: a reference names a year, and a fragment
    of one usually does not. A `year` the publisher deposited as its own field settles the
    question outright; otherwise the text must name one itself, and the digits that look
    like years but are not (`6010`, `7811`) are the page ranges these fragments end with.
    A caller with a resolvable identifier should not ask at all.
    """
    words = text.split()
    if len(words) < MIN_REFERENCE_WORDS:
        return False
    if year is not None and MIN_PUBLICATION_YEAR <= year <= MAX_PUBLICATION_YEAR:
        return True
    return any(
        MIN_PUBLICATION_YEAR <= int(found) <= MAX_PUBLICATION_YEAR
        for found in _FOUR_DIGITS.findall(text)
    )


def clean_text(value: object) -> str | None:
    """A stripped string, or `None` for anything empty or not a string."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def as_int(value: object) -> int | None:
    """An int from loose JSON (`3`, `"1998"`), or `None`; booleans are not numbers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def as_mapping(value: object) -> Mapping[str, Any]:
    """`value` when it is a JSON object, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def iter_mappings(value: object) -> Iterator[Mapping[str, Any]]:
    """The JSON objects inside a list, skipping anything else.

    A lone object is yielded as a one-element sequence: DBLP collapses single-element
    lists into the bare object.
    """
    if isinstance(value, Mapping):
        yield value
        return
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, Mapping):
            yield item


def normalize_doi(value: str | None) -> str | None:
    """Bare lowercase DOI (`10.…`), stripped of resolver prefixes; `None` if not one.

    DOIs are case-insensitive, so lowercasing is the canonical form used for matching.
    Anything that does not start with `10.` is dropped rather than guessed at.
    """
    cleaned = clean_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix) :]
            break
    lowered = lowered.strip()
    return lowered if lowered.startswith("10.") else None


def normalize_arxiv_id(value: str | None) -> str | None:
    """Bare arXiv id, version suffix preserved (`2101.00001v2`), or `None`.

    The version is part of the identity: arXiv v1 and v2 are different `Version`s of one
    `Work` (ADR-002), so dropping the suffix would erase which one was discovered.
    """
    cleaned = clean_text(value)
    if cleaned is None:
        return None
    for prefix in ("http://arxiv.org/abs/", "https://arxiv.org/abs/"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    if cleaned.lower().startswith("arxiv:"):
        cleaned = cleaned[len("arxiv:") :]
    cleaned = cleaned.strip()
    return cleaned or None


_WORD = re.compile(r"[^\s\"]+")
_FOUR_DIGITS = re.compile(r"(?<!\d)\d{4}(?!\d)")
_TERM_TRIM = " \t\r\n.,;:!?()[]{}<>'`"


def _trimmed(value: str) -> str:
    """One term with sentence punctuation stripped from both ends."""
    return " ".join(value.strip(_TERM_TRIM).split())


_TAG_OPEN = "<"
_TAG_CLOSE = ">"


def snippet_from(value: object) -> str | None:
    """A short, tag-free discovery hint; `None` when the source supplied no text.

    Abstracts arrive as JATS or HTML fragments; markup is removed and the text is
    truncated, because a snippet exists for triage and must never be quotable.
    """
    text = clean_text(value)
    if text is None:
        return None
    stripped = _strip_tags(text)
    collapsed = " ".join(stripped.split())
    if not collapsed:
        return None
    if len(collapsed) <= SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[:SNIPPET_MAX_CHARS].rstrip() + "..."


def _strip_tags(text: str) -> str:
    out: list[str] = []
    depth = 0
    for char in text:
        if char == _TAG_OPEN:
            depth += 1
        elif char == _TAG_CLOSE:
            depth = max(depth - 1, 0)
            out.append(" ")
        elif depth == 0:
            out.append(char)
    return "".join(out)

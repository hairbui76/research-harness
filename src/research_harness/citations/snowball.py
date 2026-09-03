"""Backward and forward snowballing over the citation graph (Product 17, 18).

Snowballing walks outwards from a set of seeds: backward along reference lists, forward
along citing works, one level at a time, from every source that publishes such a graph.
What comes back is *discovery*, not corpus state (Product 14): every record stays a
`WorkCandidate` in screening state `discovered`, and nothing here writes canonical files.

Three distinctions do the real work here:

* A source that cannot answer (`NotSupportedError`) is not a failure - it never claimed
  it could. A source that *breaks* becomes a `SourceFailure` and marks the whole result
  `incomplete`, because a failed query is never a zero-result (Product 18).
* Candidates deduplicate by node key across sources, but every source's own record and
  provenance survives in the graph's reference lists: two sources reporting the same
  citation is corroboration, and collapsing it would erase that.
* Versions and artifacts are never merged into a candidate. Only identity resolution
  (`existing`) may collapse a node, and only for its three definite outcomes (ADR-002).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from research_harness.citations.graph import (
    CitationGraph,
    FetchDirection,
    NodeKey,
    NodeResolution,
    ReferenceList,
    node_key_for,
    resolve_nodes,
)
from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.enums import IdentityResolutionOutcome
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.research import SourceFailure
from research_harness.domain.work import WorkCandidate, WorkIdentifiers
from research_harness.ingest.identity import ExistingRecord, MetadataLookup
from research_harness.providers.search.base import (
    NotSupportedError,
    SearchProvider,
    SearchProviderError,
    UnknownSearchProviderError,
    reference_warnings,
    to_source_failure,
)

__all__ = [
    "DEFAULT_MAX_PER_LEVEL",
    "MAX_SNOWBALL_DEPTH",
    "SnowballDirection",
    "SnowballPlan",
    "SnowballResult",
    "run_snowball",
]

logger = logging.getLogger(__name__)

MAX_SNOWBALL_DEPTH = 3
"""Levels a single run may walk. Beyond three hops the neighbourhood is the field."""

DEFAULT_MAX_PER_LEVEL = 50
"""Newly discovered works expanded at the next level unless the plan says otherwise."""

SnowballDirection = Literal["backward", "forward", "both"]

_IDENTIFIER_FIELDS: tuple[str, ...] = tuple(WorkIdentifiers.model_fields)


class SnowballPlan(DomainModel):
    """What to walk, how far, and how wide - recorded so a run is reproducible.

    ``max_per_level`` bounds the *frontier*: everything a level fetches is recorded, but
    at most this many newly discovered works are expanded at the next level, and hitting
    the bound marks the result `incomplete` rather than silently narrowing coverage.
    An empty ``sources`` means every provider handed to :func:`run_snowball`.
    """

    seeds: tuple[NonEmptyStr, ...] = Field(min_length=1)
    direction: SnowballDirection = "both"
    depth: int = Field(default=1, ge=1, le=MAX_SNOWBALL_DEPTH)
    max_per_level: int = Field(default=DEFAULT_MAX_PER_LEVEL, ge=1)
    sources: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _sources_are_distinct(self) -> SnowballPlan:
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("a snowball plan must not name the same source twice")
        return self

    @property
    def wants_backward(self) -> bool:
        """True when reference lists should be fetched."""
        return self.direction in ("backward", "both")

    @property
    def wants_forward(self) -> bool:
        """True when citing works should be fetched."""
        return self.direction in ("forward", "both")

    def wants(self, direction: FetchDirection) -> bool:
        """True when this plan asks for ``direction``."""
        return self.wants_backward if direction == "backward" else self.wants_forward


class SnowballResult(DomainModel):
    """One snowball run: the graph it built and how honest the coverage behind it is.

    ``incomplete`` is true when any source failed or any level was truncated, so a
    caller can never mistake a partial walk for an exhausted one (Product 18).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    graph: CitationGraph
    discovered: tuple[WorkCandidate, ...] = ()
    per_level_counts: tuple[int, ...] = ()
    failures: tuple[SourceFailure, ...] = ()
    unresolved: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    """What the walk did not seed from, in the order it was met.

    A source that deposits 45 references and 400 fragments of them answers successfully,
    so this is not a failure; it is the difference between the reference list and the
    coverage denominator, which has to be readable for the denominator to be honest
    (dogfood F10).
    """
    incomplete: bool = False

    @property
    def levels_fetched(self) -> int:
        """How many levels actually ran; a level with nothing left to expand ends the walk."""
        return len(self.per_level_counts)

    def keys(self) -> tuple[NodeKey, ...]:
        """Node keys of the discovered candidates, sorted."""
        return tuple(sorted(node_key_for(candidate) for candidate in self.discovered))

    def candidates_for(self, key: NodeKey) -> tuple[WorkCandidate, ...]:
        """Every source's own record of ``key``, in fetch order - one per reporting source.

        Deduplication picks one candidate per node; this is where the records it stood
        in for are still readable, each with the provenance of the source that sent it.
        """
        aliases = {key, *self.graph.merges().get(key, ())}
        return tuple(
            entry
            for ref_list in self.graph.reference_lists()
            for entry in ref_list.entries
            if node_key_for(entry) in aliases
        )

    def sources_for(self, key: NodeKey) -> tuple[str, ...]:
        """Sources that reported ``key``, sorted; more than one is corroboration."""
        aliases = {key, *self.graph.merges().get(key, ())}
        return tuple(
            sorted(
                {
                    ref_list.source
                    for ref_list in self.graph.reference_lists()
                    for entry in ref_list.entries
                    if node_key_for(entry) in aliases
                }
            )
        )


def run_snowball(
    plan: SnowballPlan,
    providers: Mapping[str, SearchProvider],
    seed_identifiers: Mapping[str, WorkIdentifiers],
    *,
    existing: Sequence[ExistingRecord] = (),
    lookup: MetadataLookup | None = None,
) -> SnowballResult:
    """Walk ``plan`` over ``providers`` and return the graph, the candidates, and the gaps.

    Sources are asked only for what they declare in `capabilities()`, so an unsupported
    direction costs no call; a `NotSupportedError` from a source that does declare it is
    still tolerated (the identifiers may be unaddressable for that source) and is not
    recorded as a failure. Any other provider error becomes a `SourceFailure` and marks
    the result incomplete.

    ``existing`` enables same-work resolution: candidates that definitely are a corpus
    Work collapse onto its Work id and carry the outcome, while `unresolved` ones are
    reported by key and left as separate nodes. With no corpus to resolve against,
    candidates stay `unresolved` - nothing was decided, so nothing is claimed.
    """
    selected = _select_sources(plan, providers)
    graph = CitationGraph()
    identifiers: dict[str, WorkIdentifiers] = dict(seed_identifiers)
    discovered: dict[str, WorkCandidate] = {}
    failures: list[SourceFailure] = []
    warnings: dict[str, None] = {}
    per_level_counts: list[int] = []
    incomplete = False

    frontier: tuple[str, ...] = tuple(dict.fromkeys(plan.seeds))
    seen: set[str] = set(frontier)

    for _ in range(plan.depth):
        if not frontier:
            break
        fresh: dict[str, WorkCandidate] = {}
        for node in frontier:
            node_identifiers = identifiers.get(node)
            if node_identifiers is None or not _addressable(node_identifiers):
                logger.debug("no usable identifiers for %s; not expanding it", node)
                continue
            for name, provider in selected:
                for direction, fetch in _operations(plan, provider):
                    entries, failure = _fetch(fetch, node_identifiers, name, node, direction)
                    if failure is not None:
                        failures.append(failure)
                        incomplete = True
                        continue
                    if entries is None:
                        continue
                    notes = list(reference_warnings(entries))
                    keyed, dropped = _keyed(entries)
                    if dropped:
                        note = _unusable_identity_warning(name, dropped, node)
                        logger.warning("%s", note)
                        notes.append(note)
                        incomplete = True
                    warnings.update(dict.fromkeys(notes))
                    graph.add_reference_list(
                        ReferenceList(
                            work=node,
                            source=name,
                            direction=direction,
                            entries=tuple(entry for _, entry in keyed),
                            incomplete=bool(dropped),
                            warnings=tuple(notes),
                        )
                    )
                    for key, entry in keyed:
                        discovered.setdefault(key, entry)
                        identifiers.setdefault(key, entry.metadata.identifiers)
                        if key not in seen:
                            fresh.setdefault(key, entry)
        per_level_counts.append(len(fresh))
        seen.update(fresh)
        expandable = sorted(fresh)
        if len(expandable) > plan.max_per_level:
            logger.info(
                "level frontier truncated to %d of %d works", plan.max_per_level, len(expandable)
            )
            expandable = expandable[: plan.max_per_level]
            incomplete = True
        frontier = tuple(expandable)

    resolutions = (
        resolve_nodes(tuple(discovered.values()), existing, lookup=lookup) if existing else ()
    )
    mapping = {
        resolution.key: str(resolution.work)
        for resolution in resolutions
        if resolution.work is not None and resolution.key != str(resolution.work)
    }
    if mapping:
        graph = graph.merge_nodes(mapping)
    return SnowballResult(
        graph=graph,
        discovered=_collapse(discovered, resolutions, mapping),
        per_level_counts=tuple(per_level_counts),
        failures=tuple(failures),
        unresolved=_unresolved(resolutions),
        warnings=tuple(warnings),
        incomplete=incomplete,
    )


# -- internals ---------------------------------------------------------------

_Fetch = Callable[[WorkIdentifiers], list[WorkCandidate]]


def _unusable_identity_warning(source: str, dropped: int, node: str) -> str:
    """Wording for records that cannot be keyed at all, so cannot be deduplicated or cited."""
    return (
        f"{source} sent {dropped} record(s) for {node} with no usable identity; "
        "they were dropped rather than seeded"
    )


def _select_sources(
    plan: SnowballPlan, providers: Mapping[str, SearchProvider]
) -> tuple[tuple[str, SearchProvider], ...]:
    """The sources to ask, in plan order when named, else in mapping order."""
    if not plan.sources:
        return tuple(providers.items())
    selected: list[tuple[str, SearchProvider]] = []
    for name in plan.sources:
        provider = providers.get(name)
        if provider is None:
            known = ", ".join(providers) or "none"
            raise UnknownSearchProviderError(
                f"unknown search source {name!r}; configured: {known}", source=name
            )
        selected.append((name, provider))
    return tuple(selected)


def _operations(
    plan: SnowballPlan, provider: SearchProvider
) -> tuple[tuple[FetchDirection, _Fetch], ...]:
    """The (direction, call) pairs this plan wants and this source declares support for."""
    capabilities = provider.capabilities()
    declared: tuple[tuple[FetchDirection, bool, _Fetch], ...] = (
        ("backward", capabilities.supports_references, provider.fetch_references),
        ("forward", capabilities.supports_citations, provider.fetch_citations),
    )
    return tuple(
        (direction, fetch)
        for direction, supported, fetch in declared
        if supported and plan.wants(direction)
    )


def _fetch(
    fetch: _Fetch,
    identifiers: WorkIdentifiers,
    source: str,
    node: str,
    direction: FetchDirection,
) -> tuple[Sequence[WorkCandidate] | None, SourceFailure | None]:
    """Run one graph call: entries, a failure, or neither when the source cannot answer.

    The entries are handed back exactly as the adapter returned them, because a
    `ReferenceCandidates` carries the counts of what it refused to map and a tuple would
    drop them (dogfood F10).
    """
    try:
        return fetch(identifiers), None
    except NotSupportedError:
        logger.debug("%s cannot walk %s from %s", source, direction, node)
        return None, None
    except SearchProviderError as error:
        return None, to_source_failure(error, source, query=f"{direction}:{node}")


def _keyed(entries: Sequence[WorkCandidate]) -> tuple[list[tuple[str, WorkCandidate]], int]:
    """Pair each entry with its node key, dropping records that have no identity at all.

    A record with neither an identifier nor a title cannot be deduplicated, cited, or
    resolved. Dropping it is the only honest option, and the count is what makes the
    reference list - and the run - report itself as incomplete rather than exhaustive.
    """
    keyed: list[tuple[str, WorkCandidate]] = []
    dropped = 0
    for entry in entries:
        try:
            keyed.append((node_key_for(entry), entry))
        except DomainValidationError:
            dropped += 1
    return keyed, dropped


def _addressable(identifiers: WorkIdentifiers) -> bool:
    """True when at least one external identifier is present to query a source with."""
    return any(getattr(identifiers, name) is not None for name in _IDENTIFIER_FIELDS)


def _collapse(
    discovered: Mapping[str, WorkCandidate],
    resolutions: Sequence[NodeResolution],
    mapping: Mapping[str, str],
) -> tuple[WorkCandidate, ...]:
    """One candidate per final node key, carrying its resolution outcome, sorted by key."""
    resolved = {resolution.key: resolution.resolved for resolution in resolutions}
    collapsed: dict[str, WorkCandidate] = {}
    for key in sorted(discovered):
        collapsed.setdefault(mapping.get(key, key), resolved.get(key, discovered[key]))
    return tuple(collapsed[key] for key in sorted(collapsed))


def _unresolved(resolutions: Sequence[NodeResolution]) -> tuple[str, ...]:
    """Node keys the resolver could not decide about; they stay separate nodes."""
    return tuple(
        sorted(
            resolution.key
            for resolution in resolutions
            if resolution.outcome is IdentityResolutionOutcome.UNRESOLVED
        )
    )

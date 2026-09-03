"""Executing and persisting a `SearchRun`: paging, dedup, identity, and provenance.

A `SearchRun` is the record that makes a coverage or absence claim checkable months later
(Product 18): which sources were asked, with which query, how far each one was paged, what
broke, what could not be identified, and what has no full text to read. Everything here
exists to keep those five things honest.

Three separations are load-bearing:

* **A failure is not a zero result.** A source that could not be searched becomes a
  `SourceFailure` and leaves its `SourceCursor` unexhausted, so `claims.coverage` reads the
  run as incomplete. A source that searched and matched nothing simply contributes no
  candidates (ROADMAP 12.1, 12.2).
* **Dedup is work-level; records are not.** Hits collapse by citation-graph node key, but
  every reporting source and its rank survive on the candidate, and two candidates that
  resolve to the same `Work` stay two entries. Nothing here merges a Version or an
  Artifact (ADR-002).
* **Discovery is not corpus state.** Candidates are recorded at screening state
  `discovered` with their identity outcome; only `discovery.screening` moves them, and
  only source acquisition creates a `Work` (Product 14).

A fourth follows from the third and was learned the hard way (dogfood F5): when a hit
resolves to a `Work` the corpus already holds, the source's own title, authors, year and
venue are *not* thrown away -- they are persisted on the candidate and readable back as a
:class:`MetadataEnrichment`. The harness found the right six authors for a paper whose
own PDF gave it mojibake and never said so. `DiscoveryService.enrichments` is that record
made visible; :func:`apply_enrichments` says exactly what would change and refuses to
write it behind the capability layer's back.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from inspect import signature
from typing import Any, get_type_hints

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import MutationResult, RecordSearchRunRequest
from research_harness.capabilities.handlers import CAPABILITY_HANDLERS, record_search_run
from research_harness.citations.graph import node_key_for
from research_harness.citations.snowball import (
    DEFAULT_MAX_PER_LEVEL,
    SnowballDirection,
    SnowballPlan,
    SnowballResult,
    run_snowball,
)
from research_harness.claims.coverage import parse_cutoff
from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.enums import IdentityResolutionOutcome, ProvenanceSource
from research_harness.domain.errors import (
    CapabilityError,
    DomainValidationError,
    ResearchHarnessError,
)
from research_harness.domain.ids import QuestionId, SearchRunId, WorkId
from research_harness.domain.research import (
    SearchCandidate,
    SearchResultCounts,
    SearchRun,
    SourceCursor,
    SourceFailure,
)
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    Work,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.ingest.identity import (
    ExistingRecord,
    author_surnames,
    normalize_title,
    resolve_identity,
)
from research_harness.parsing.quality import assess_text
from research_harness.providers.search.base import (
    SearchHit,
    SearchProvider,
    SearchProviderError,
    SearchProviderRegistry,
    SearchQuery,
    to_source_failure,
)
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "DEFAULT_MAX_PAGES",
    "ENRICHABLE_FIELDS",
    "METADATA_UPDATE_CAPABILITY",
    "SNOWBALL_QUERY_PREFIX",
    "DiscoveryService",
    "EnrichmentPlan",
    "MetadataConflict",
    "MetadataEnrichment",
    "apply_enrichments",
    "enrichment_for",
    "enrichments_for",
    "next_search_run_id",
]

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 3
"""Pages one source is walked per run unless the caller asks for more."""

SNOWBALL_QUERY_PREFIX = "snowball:"
"""Marks a run produced by walking the citation graph rather than by a text query."""

ENRICHABLE_FIELDS: tuple[str, ...] = ("title", "authors", "year", "venue")
"""Work fields a discovery record can improve, in the order an enrichment reports them."""

METADATA_UPDATE_CAPABILITY = "work.update_metadata"
"""The capability that would have to exist for an enrichment to be written (ADR-004)."""

_FILTER_MAX_PAGES = "max_pages"
_FILTER_CUTOFF = "cutoff"
_FILTER_DEPTH = "snowball_depth"
_FILTER_DIRECTION = "snowball_direction"
_FILTER_PER_LEVEL = "snowball_max_per_level"

_DIRECTIONS: tuple[SnowballDirection, ...] = ("backward", "forward", "both")


def next_search_run_id(repo: WorkspaceRepository) -> SearchRunId:
    """The id the next `search_run.record` will write.

    `search_run.record` takes a fully built run, so the id is read before the transaction
    the way the capability layer reads every other announced id: the highest on disk, and
    never below the `research.yaml` counter.
    """
    on_disk = SearchRunId.next(str(run.id) for run in repo.list_search_runs())
    return SearchRunId.make(max(on_disk.number, repo.config.counter(SearchRunId.prefix) + 1))


class MetadataConflict(DomainModel):
    """A discovery value that disagrees with what the corpus Work already records.

    A conflict is never resolved here. It is the record that lets a researcher decide, and
    it is what stops "discovery knows better" from silently rewriting accepted state.
    """

    field: NonEmptyStr
    existing: NonEmptyStr
    incoming: NonEmptyStr
    existing_is_undecodable: bool = False
    """True when the recorded value is mojibake, which makes the incoming one safe to take."""


class MetadataEnrichment(DomainModel):
    """Better metadata one discovery candidate carries for a Work the corpus already holds.

    `fields` maps a `Work` field name to the values the sources reported, each keeping its
    own `IdentifierField` provenance, so applying one never loses which source said what
    (Product 13). A field appears only when the Work's own value is empty or undecodable,
    or -- with `only_empty_or_undecodable=False` -- when the researcher asked for the
    conflicting ones too; either way every disagreement is in `conflicts`.
    """

    work: WorkId
    candidate_key: NonEmptyStr
    sources: tuple[str, ...] = ()
    """The discovery sources that reported this candidate, in the order they were searched."""
    fields: dict[str, tuple[IdentifierField, ...]] = Field(default_factory=dict)
    conflicts: tuple[MetadataConflict, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when there is nothing to propose and nothing to disagree about."""
        return not self.fields and not self.conflicts

    def values(self, field: str) -> tuple[str, ...]:
        """The proposed values for one field as plain strings, in source order."""
        return tuple(entry.value for entry in self.fields.get(field, ()))


class EnrichmentPlan(DomainModel):
    """What applying a run's enrichments changed, or would change if it could be written.

    `works` is always the Works as they *would* read, whether or not anything was written,
    so a caller can show the researcher exactly what is on offer. `applied` says whether
    `work.update_metadata` existed to write it; when it did not, `missing_capability` names
    it and `message` says why nothing was written -- the change is withheld visibly rather
    than disappearing the way it did in the dogfood (F5).
    """

    enrichments: tuple[MetadataEnrichment, ...] = ()
    works: tuple[Work, ...] = ()
    """The Works as they would read once applied; not written, and not corpus state."""
    applied: bool = False
    updated: tuple[WorkId, ...] = ()
    """Works `work.update_metadata` actually changed; empty when nothing was written."""
    missing_capability: str | None = None
    message: str = ""


@dataclass(slots=True)
class _Bucket:
    """One deduplicated work, and every source that reported it."""

    key: str
    candidate: WorkCandidate
    sources: list[str] = field(default_factory=list)
    ranks: dict[str, int] = field(default_factory=dict)
    open_access: bool = False

    def add(self, hit: SearchHit) -> None:
        """Record one more source's sighting; the first record of a work is the one kept."""
        if hit.source not in self.sources:
            self.sources.append(hit.source)
        self.ranks.setdefault(hit.source, hit.rank)
        self.open_access = self.open_access or hit.open_access_pdf_url is not None


@dataclass(frozen=True, slots=True)
class _SourceOutcome:
    """What one source produced: its hits, where paging stopped, and what broke."""

    cursor: SourceCursor
    hits: tuple[SearchHit, ...] = ()
    failures: tuple[SourceFailure, ...] = ()


class DiscoveryService:
    """Runs external discovery and persists it as a reproducible `SearchRun`.

    The registry is injected rather than built here, so the whole surface runs offline
    against in-memory sources and no adapter reads a credential from a workspace file.
    """

    def __init__(self, ctx: CapabilityContext, registry: SearchProviderRegistry) -> None:
        self._ctx = ctx
        self._registry = registry

    # -- search --------------------------------------------------------------

    def run_search(
        self,
        question: str,
        query: SearchQuery,
        *,
        sources: Sequence[str] | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        cutoff: str | date | None = None,
        research_question: QuestionId | None = None,
        reproduces: SearchRunId | None = None,
    ) -> tuple[SearchRun, MutationResult]:
        """Search every selected source, page it, deduplicate it, and record the run.

        Each source is walked to `max_pages` or until it runs out of pages, whichever comes
        first, and either way its `SourceCursor` says which. A provider error stops that one
        source, is recorded as a `SourceFailure`, and leaves its cursor unexhausted; the
        other sources still run, because a broken source is a gap in coverage rather than a
        reason to lose the results that did arrive.
        """
        if max_pages < 1:
            raise CapabilityError("discovery.search: max_pages must be at least 1")
        selected = self._registry.select(None if sources is None else list(sources))
        outcomes = [_search_source(provider, query, max_pages) for provider in selected]
        buckets, unmappable = _deduplicate(outcomes)
        failures = [failure for outcome in outcomes for failure in outcome.failures]
        failures.extend(unmappable)
        candidates = self._resolved_candidates(buckets)
        return self._record(
            question=question,
            sources=tuple(provider.name for provider in selected),
            queries=(query.text,),
            filters=_filters_of(query, max_pages=max_pages, cutoff=_as_date(cutoff)),
            cutoff=_as_date(cutoff),
            cursors=tuple(outcome.cursor for outcome in outcomes),
            failures=tuple(failures),
            candidates=candidates,
            research_question=research_question,
            reproduces=reproduces,
        )

    def rerun(self, run_id: SearchRunId | str) -> tuple[SearchRun, MutationResult]:
        """Re-execute a recorded run and persist the result as a new run.

        Reproducibility here means *re-running the recorded operation*, not replaying its
        results: the queries, sources, filters, cutoff, and page budget come off the stored
        run, and what comes back is a new `SearchRun` naming the one it reproduces. The
        earlier run is never edited, so a coverage claim that cited it still reads the
        record it was made from.
        """
        previous = self._ctx.repo.get_search_run(SearchRunId(str(run_id)))
        if not previous.queries:
            raise CapabilityError(f"discovery.rerun: {previous.id} recorded no query to re-run")
        if previous.queries[0].startswith(SNOWBALL_QUERY_PREFIX):
            return self._rerun_snowball(previous)
        return self.run_search(
            previous.question,
            _query_of(previous),
            sources=previous.sources or None,
            max_pages=_int_filter(previous.filters, _FILTER_MAX_PAGES, DEFAULT_MAX_PAGES),
            cutoff=previous.cutoff,
            research_question=previous.research_question,
            reproduces=previous.id,
        )

    # -- snowball ------------------------------------------------------------

    def snowball(
        self,
        seed: WorkId | str,
        plan: SnowballPlan,
        *,
        question: str | None = None,
        research_question: QuestionId | None = None,
        reproduces: SearchRunId | None = None,
    ) -> tuple[SearchRun, MutationResult]:
        """Walk the citation graph from one seed and record the walk as a `SearchRun`.

        ``seed`` wins over ``plan.seeds``: the plan carries depth, direction, and sources,
        and the seed says where the walk starts. A truncated level or a source that broke
        leaves the run's cursors unexhausted, so a walk that stopped early can never be read
        as an exhausted neighbourhood.
        """
        key, identifiers = self._seed(seed)
        walk = plan.touch(seeds=(key,))
        providers = self._registry.as_dict()
        result = run_snowball(walk, providers, {key: identifiers}, existing=self._existing())
        walked = _walked_sources(walk, providers)
        broken = {failure.source for failure in result.failures}
        cursors = tuple(
            SourceCursor(
                source=name,
                query=f"{SNOWBALL_QUERY_PREFIX}{key}",
                pages_fetched=result.levels_fetched,
                exhausted=not result.incomplete and name not in broken,
            )
            for name in walked
        )
        failures = (*result.failures, *_reference_drop_notes(result, walked))
        if not walked:
            failures = (*failures, *_no_graph_failures(walk, providers, key))
        return self._record(
            question=question if question else f"citation neighbourhood of {key}",
            sources=walked,
            queries=(f"{SNOWBALL_QUERY_PREFIX}{key}",),
            filters={
                _FILTER_DEPTH: str(walk.depth),
                _FILTER_DIRECTION: walk.direction,
                _FILTER_PER_LEVEL: str(walk.max_per_level),
            },
            cutoff=None,
            cursors=cursors,
            failures=failures,
            candidates=self._snowball_candidates(result),
            research_question=research_question,
            reproduces=reproduces,
        )

    # -- metadata enrichment -------------------------------------------------

    def enrichments(
        self, run: SearchRun | SearchRunId | str, *, only_empty_or_undecodable: bool = True
    ) -> list[MetadataEnrichment]:
        """Metadata this run found for Works the corpus already holds (dogfood F5).

        Derived, never stored: a `SearchCandidate` keeps the whole `WorkCandidate` a source
        reported, so nothing was lost when the hit resolved `same_work` -- it was simply
        never read back. Candidates are walked in discovery order and a Work that several
        candidates improve yields one enrichment per candidate, because two sources
        agreeing is corroboration the researcher should see rather than a merge.
        """
        return enrichments_for(self._ctx, run, only_empty_or_undecodable=only_empty_or_undecodable)

    # -- internals -----------------------------------------------------------

    def _rerun_snowball(self, previous: SearchRun) -> tuple[SearchRun, MutationResult]:
        seed = previous.queries[0][len(SNOWBALL_QUERY_PREFIX) :]
        direction = previous.filters.get(_FILTER_DIRECTION, "both")
        if direction not in _DIRECTIONS:
            raise CapabilityError(
                f"discovery.rerun: {previous.id} recorded an unknown snowball direction "
                f"{direction!r}"
            )
        plan = SnowballPlan(
            seeds=(seed,),
            direction=direction,
            depth=_int_filter(previous.filters, _FILTER_DEPTH, 1),
            max_per_level=_int_filter(previous.filters, _FILTER_PER_LEVEL, DEFAULT_MAX_PER_LEVEL),
            sources=previous.sources,
        )
        return self.snowball(
            seed,
            plan,
            question=previous.question,
            research_question=previous.research_question,
            reproduces=previous.id,
        )

    def _record(
        self,
        *,
        question: str,
        sources: tuple[str, ...],
        queries: tuple[str, ...],
        filters: dict[str, str],
        cutoff: date | None,
        cursors: tuple[SourceCursor, ...],
        failures: tuple[SourceFailure, ...],
        candidates: tuple[SearchCandidate, ...],
        research_question: QuestionId | None,
        reproduces: SearchRunId | None,
    ) -> tuple[SearchRun, MutationResult]:
        """Build the run, allocate its id, and persist it through `search_run.record`."""
        ctx = self._ctx
        unresolved = tuple(
            entry.key
            for entry in candidates
            if entry.identity is IdentityResolutionOutcome.UNRESOLVED
        )
        no_full_text = tuple(
            entry.key for entry in candidates if entry.full_text_available is False
        )
        unavailable = tuple(
            sorted(
                {
                    entry.matched_work
                    for entry in candidates
                    if entry.full_text_available is False and entry.matched_work is not None
                }
            )
        )
        with ctx.repo.lock():
            run = SearchRun(
                id=next_search_run_id(ctx.repo),
                question=question,
                research_question=research_question,
                sources=sources,
                queries=queries,
                filters=filters,
                results=SearchResultCounts(discovered=len(candidates)),
                executed_at=ctx.now(),
                cutoff=cutoff,
                cursors=cursors,
                failures=failures,
                unresolved_identities=unresolved,
                unavailable_full_text=unavailable,
                candidates=candidates,
                unresolved_keys=unresolved,
                full_text_unavailable_keys=no_full_text,
                reproduces=reproduces,
                provenance=ctx.provenance(workflow="discovery"),
            )
            mutation = record_search_run(ctx, RecordSearchRunRequest(search_run=run))
        logger.info(
            "%s discovered %d candidate(s) from %d source(s) with %d failure(s)",
            run.id,
            len(candidates),
            len(sources),
            len(failures),
        )
        return run, mutation

    def _resolved_candidates(self, buckets: Sequence[_Bucket]) -> tuple[SearchCandidate, ...]:
        """Resolve each deduplicated work against the corpus and record what it turned out to be."""
        existing = self._existing()
        held = _works_with_artifacts(existing)
        entries: list[SearchCandidate] = []
        for bucket in buckets:
            resolution = resolve_identity(bucket.candidate, existing)
            entries.append(
                SearchCandidate(
                    key=bucket.key,
                    candidate=resolution.applied_to(bucket.candidate),
                    sources=tuple(bucket.sources),
                    ranks=dict(bucket.ranks),
                    identity=resolution.outcome,
                    matched_work=resolution.work,
                    full_text_available=bucket.open_access or resolution.work in held,
                )
            )
        return tuple(entries)

    def _snowball_candidates(self, result: SnowballResult) -> tuple[SearchCandidate, ...]:
        """Turn a snowball walk into candidates, keeping every reporting source and rank."""
        reported = _snowball_reporting(result)
        buckets: list[_Bucket] = []
        for candidate in result.discovered:
            try:
                key = node_key_for(candidate)
            except DomainValidationError:  # pragma: no cover - run_snowball drops these first
                continue
            sources, ranks = reported.get(key, ([], {}))
            buckets.append(
                _Bucket(key=key, candidate=candidate, sources=list(sources), ranks=dict(ranks))
            )
        return self._resolved_candidates(buckets)

    def _existing(self) -> tuple[ExistingRecord, ...]:
        """The corpus as identity resolution reads it: each Work with its versions and artifacts."""
        repo = self._ctx.repo
        return tuple(
            ExistingRecord(
                work=work,
                versions=tuple(repo.list_versions(work.id)),
                artifacts=tuple(repo.list_artifacts(work.id)),
            )
            for work in repo.list_works()
        )

    def _seed(self, seed: WorkId | str) -> tuple[str, WorkIdentifiers]:
        """The seed's node key and the identifiers a source can be queried with."""
        text = str(seed).strip()
        if not text:
            raise CapabilityError("discovery.snowball: the seed is empty")
        if text.startswith(WorkId.prefix):
            work = self._ctx.repo.get_work(WorkId(text))
            return str(work.id), work.identifiers
        prefix, _, value = text.partition(":")
        if not value:
            raise CapabilityError(
                f"discovery.snowball: {text!r} is neither a Work id nor a `doi:`/`arxiv:` key"
            )
        external = ProvenanceSource.EXTERNAL_METADATA
        field_value = IdentifierField(value=value, source=external, note="snowball seed")
        match prefix:
            case "doi":
                return text, WorkIdentifiers(doi=field_value)
            case "arxiv":
                return text, WorkIdentifiers(arxiv=field_value)
            case _:
                raise CapabilityError(
                    f"discovery.snowball: cannot address {text!r}; seed a Work id, a `doi:` "
                    "key, or an `arxiv:` key"
                )


# -- metadata enrichment -----------------------------------------------------


def enrichment_for(
    entry: SearchCandidate, work: Work, *, only_empty_or_undecodable: bool = True
) -> MetadataEnrichment | None:
    """What one resolved candidate could tell the corpus about ``work``, or ``None``.

    Pure and deterministic: the same candidate and Work always produce the same proposal.
    A field is proposed when the Work records nothing for it, or when what it records is
    undecodable -- text `parsing.quality` says no font could have drawn (dogfood F6). A
    disagreement between two readable values is recorded as a :class:`MetadataConflict`
    and proposed only when ``only_empty_or_undecodable`` is False.
    """
    proposals: dict[str, tuple[IdentifierField, ...]] = {}
    conflicts: list[MetadataConflict] = []
    for name in ENRICHABLE_FIELDS:
        incoming = _incoming(entry.candidate.metadata, name)
        if not incoming:
            continue
        existing = _existing(work, name)
        if not existing:
            proposals[name] = incoming
            continue
        if _agrees(name, existing, incoming):
            continue
        undecodable = _undecodable(existing)
        conflicts.append(
            MetadataConflict(
                field=name,
                existing="; ".join(existing),
                incoming="; ".join(value.value for value in incoming),
                existing_is_undecodable=undecodable,
            )
        )
        if undecodable or not only_empty_or_undecodable:
            proposals[name] = incoming
    enrichment = MetadataEnrichment(
        work=work.id,
        candidate_key=entry.key,
        sources=tuple(entry.sources),
        fields=proposals,
        conflicts=tuple(conflicts),
    )
    return None if enrichment.is_empty else enrichment


def enrichments_for(
    ctx: CapabilityContext,
    run: SearchRun | SearchRunId | str,
    *,
    only_empty_or_undecodable: bool = True,
) -> list[MetadataEnrichment]:
    """The enrichments a run offers, read straight off the record (dogfood F5).

    A read, not a service call: it needs the workspace and nothing else, so it works
    without a configured discovery source. `DiscoveryService.enrichments` is the same
    function reached through the service a caller already holds.
    """
    record = run if isinstance(run, SearchRun) else ctx.repo.get_search_run(SearchRunId(str(run)))
    works = {work.id: work for work in ctx.repo.list_works()}
    found: list[MetadataEnrichment] = []
    for entry in record.candidates:
        work = works.get(entry.matched_work) if entry.matched_work is not None else None
        if work is None:
            continue
        enrichment = enrichment_for(
            entry, work, only_empty_or_undecodable=only_empty_or_undecodable
        )
        if enrichment is not None:
            found.append(enrichment)
    return found


def apply_enrichments(
    ctx: CapabilityContext,
    run: SearchRun | SearchRunId | str,
    *,
    only_empty_or_undecodable: bool = True,
) -> EnrichmentPlan:
    """Propose the Work updates a run's enrichments imply; write them if that is possible.

    `capabilities/` is the only supported mutation surface (ADR-004) and neither
    `work.register` nor `work.add_artifact` can update a registered Work's bibliographic
    fields. So the write is attempted through `work.update_metadata`, looked up by name in
    `CAPABILITY_HANDLERS` *at call time*: when that capability exists the enrichment is
    applied through it and the plan names the Works it changed; when it does not, the plan
    comes back with ``applied=False``, `missing_capability` naming it, and the proposed
    `Work` objects in hand.

    Either way nothing is written behind the capability layer, and either way the better
    metadata is visible -- which is the actual defect this fixes. The dogfood's failure was
    that a source's correct author list vanished without a trace, not that it went
    unwritten.
    """
    enrichments = enrichments_for(ctx, run, only_empty_or_undecodable=only_empty_or_undecodable)
    works = {work.id: work for work in ctx.repo.list_works()}
    proposed: dict[WorkId, Work] = {}
    for enrichment in enrichments:
        if not enrichment.fields:
            continue
        current = proposed.get(enrichment.work) or works.get(enrichment.work)
        if current is None:  # pragma: no cover - enrichments only name Works that exist
            continue
        proposed[enrichment.work] = _with_enrichment(current, enrichment)
    if not proposed:
        return EnrichmentPlan(
            enrichments=tuple(enrichments),
            message="no candidate in this run improves on what the corpus records",
        )
    ordered = tuple(proposed[key] for key in sorted(proposed))
    by_work = _first_enrichment_per_work(enrichments)
    updated, refusal = _write_through_capability(
        ctx, ordered, by_work, overwrite=not only_empty_or_undecodable
    )
    if refusal is None:
        logger.info(
            "%d work(s) updated from discovery metadata through %s",
            len(updated),
            METADATA_UPDATE_CAPABILITY,
        )
        return EnrichmentPlan(
            enrichments=tuple(enrichments),
            works=ordered,
            applied=True,
            updated=updated,
            message=(
                f"{len(updated)} work(s) updated from this run's discovery records through "
                f"`{METADATA_UPDATE_CAPABILITY}`; every applied field kept the provenance of "
                "the source that reported it."
            ),
        )
    logger.info(
        "%d work(s) have better external metadata that was not written: %s",
        len(ordered),
        refusal,
    )
    return EnrichmentPlan(
        enrichments=tuple(enrichments),
        works=ordered,
        applied=False,
        missing_capability=METADATA_UPDATE_CAPABILITY,
        message=(
            f"{len(ordered)} work(s) can be improved from this run's discovery records, but "
            f"the change was not written: {refusal} The proposed Work objects are returned "
            "unapplied; nothing was written."
        ),
    )


def _first_enrichment_per_work(
    enrichments: Sequence[MetadataEnrichment],
) -> dict[WorkId, MetadataEnrichment]:
    """One enrichment per Work -- the first candidate that offered anything for it."""
    table: dict[WorkId, MetadataEnrichment] = {}
    for enrichment in enrichments:
        if enrichment.fields:
            table.setdefault(enrichment.work, enrichment)
    return table


def _write_through_capability(
    ctx: CapabilityContext,
    works: Sequence[Work],
    enrichments: Mapping[WorkId, MetadataEnrichment],
    *,
    overwrite: bool,
) -> tuple[tuple[WorkId, ...], str | None]:
    """Apply the proposals through `work.update_metadata`, or say why nothing was written.

    The capability is resolved by name at call time rather than imported: `capabilities/`
    reaches into `discovery/` for its own handlers, so a module-scope import back would be
    a cycle, and the lookup keeps this module working whether or not that handler exists.
    A handler whose request this cannot fill, or that refuses the change, is reported as a
    refusal rather than worked around -- guessing at a mutation surface is exactly what
    ADR-004 forbids.
    """
    handler = CAPABILITY_HANDLERS.get(METADATA_UPDATE_CAPABILITY)
    if handler is None:
        return (), (
            f"`{METADATA_UPDATE_CAPABILITY}` does not exist, and "
            "`work.register`/`work.add_artifact` cannot update a registered Work's "
            "bibliographic fields."
        )
    request_type = _request_type(handler)
    if request_type is None:
        return (), (
            f"`{METADATA_UPDATE_CAPABILITY}` exists but does not declare the request type "
            "it accepts, so no request could be built for it."
        )
    changed: list[WorkId] = []
    for work in works:
        enrichment = enrichments.get(work.id)
        if enrichment is None:  # pragma: no cover - every proposed Work has an enrichment
            continue
        request = _metadata_request(request_type, work, enrichment, overwrite=overwrite)
        if request is None:
            return (), (
                f"`{METADATA_UPDATE_CAPABILITY}` requires request fields this run cannot "
                f"supply ({request_type.__name__})."
            )
        try:
            outcome = handler(ctx, request)
        except ResearchHarnessError as error:
            return (), f"`{METADATA_UPDATE_CAPABILITY}` refused the change: {error}"
        if getattr(outcome, "updated", True):
            changed.append(work.id)
    return tuple(changed), None


def _request_type(handler: Callable[[CapabilityContext, Any], Any]) -> type[BaseModel] | None:
    """The Pydantic request model a capability handler's second parameter is annotated with."""
    try:
        hints = get_type_hints(handler)
    except Exception:  # pragma: no cover
        # Deliberately broad: `get_type_hints` raises whatever evaluating a foreign
        # module's annotations raises, and an unreadable annotation is a reason to refuse
        # the write, never a reason to crash the caller's discovery run.
        logger.debug("cannot read the request type of %s", METADATA_UPDATE_CAPABILITY)
        return None
    parameters = [name for name in signature(handler).parameters if name in hints]
    for name in reversed(parameters):
        hint = hints[name]
        if isinstance(hint, type) and issubclass(hint, BaseModel):
            return hint
    return None


def _metadata_request(
    request_type: type[BaseModel],
    work: Work,
    enrichment: MetadataEnrichment,
    *,
    overwrite: bool,
) -> BaseModel | None:
    """Build the capability's request from the enrichment, or ``None`` when it cannot be.

    The proposed values are handed over as the `IdentifierField`s the sources reported, not
    as the plain strings of the proposed `Work`: field-level provenance is what makes an
    overridden value auditable (Product 13), and dropping it here would lose exactly what
    the enrichment exists to carry. Only field names whose meaning is unambiguous are
    filled; a required field outside that vocabulary means the handler wants something this
    module has no honest value for, and the write is refused rather than guessed at.
    """
    offered: dict[str, object] = {
        "work": work.id,
        "work_id": work.id,
        "overwrite": overwrite,
        "reason": _enrichment_reason(enrichment),
        "note": _enrichment_reason(enrichment),
    }
    for name, values in enrichment.fields.items():
        offered[name] = values if name == "authors" else values[0]
    known = set(request_type.model_fields)
    kwargs = {name: value for name, value in offered.items() if name in known}
    unfillable = [
        name
        for name, spec in request_type.model_fields.items()
        if spec.is_required() and name not in kwargs
    ]
    if unfillable:
        logger.info(
            "%s wants request field(s) %s that discovery cannot supply",
            METADATA_UPDATE_CAPABILITY,
            ", ".join(sorted(unfillable)),
        )
        return None
    try:
        return request_type(**kwargs)
    except PydanticValidationError as error:
        logger.info("%s request could not be built: %s", METADATA_UPDATE_CAPABILITY, error)
        return None


def _enrichment_reason(enrichment: MetadataEnrichment) -> str:
    """One line saying which sources supplied the change, for the mutation's own record."""
    sources = ", ".join(enrichment.sources) or "discovery"
    fields = ", ".join(sorted(enrichment.fields))
    return f"external metadata from {sources}: {fields}"


def _with_enrichment(work: Work, enrichment: MetadataEnrichment) -> Work:
    """``work`` as it would read with this enrichment applied; provenance is untouched."""
    updates: dict[str, object] = {}
    for name, values in enrichment.fields.items():
        if name == "authors":
            updates["authors"] = tuple(value.value for value in values)
        elif name == "year":
            year = _as_int(values[0].value)
            if year is not None:
                updates["year"] = year
        else:
            updates[name] = values[0].value
    return work.touch(**updates) if updates else work


def _incoming(metadata: CandidateMetadata, name: str) -> tuple[IdentifierField, ...]:
    """The candidate's stated values for one Work field, in the order the source gave them."""
    if name == "authors":
        return metadata.authors
    value: IdentifierField | None = getattr(metadata, name, None)
    return (value,) if value is not None else ()


def _existing(work: Work, name: str) -> tuple[str, ...]:
    """What the Work records for one field, as plain strings; empty when it records nothing."""
    if name == "authors":
        return tuple(author for author in work.authors if author.strip())
    current = getattr(work, name, None)
    if current is None:
        return ()
    text = str(current).strip()
    return (text,) if text else ()


def _agrees(name: str, existing: Sequence[str], incoming: Sequence[IdentifierField]) -> bool:
    """True when the source is saying what the corpus already says, so there is nothing to do."""
    values = [value.value for value in incoming]
    if name == "authors":
        return author_surnames(existing) == author_surnames(values)
    if name == "year":
        return _as_int(existing[0]) == _as_int(values[0])
    return normalize_title(existing[0]) == normalize_title(values[0])


def _undecodable(existing: Sequence[str]) -> bool:
    """True when any recorded value is text no font could have drawn (dogfood F6)."""
    return any(not assess_text(value).decodable for value in existing)


def _as_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None


# -- source paging -----------------------------------------------------------


def _search_source(provider: SearchProvider, query: SearchQuery, max_pages: int) -> _SourceOutcome:
    """Walk one source to ``max_pages``, recording exactly where and why paging stopped."""
    hits: list[SearchHit] = []
    failures: list[SourceFailure] = []
    cursor = query.cursor
    pages = 0
    exhausted = False
    while pages < max_pages:
        try:
            page = provider.search(query.at_cursor(cursor))
        except SearchProviderError as error:
            failures.append(
                to_source_failure(error, provider.name, query=query.text, incomplete=pages > 0)
            )
            break
        pages += 1
        hits.extend(page.hits)
        if page.incomplete:
            failures.append(
                SourceFailure(
                    source=provider.name,
                    query=query.text,
                    reason="; ".join(page.warnings) or "the source returned a partial page",
                    incomplete=True,
                )
            )
        elif page.warnings and not page.hits:
            # A complete page that matched nothing but had something to say about the
            # query it was asked (dogfood F1): the slice is exhausted, so `incomplete`
            # stays False, but coverage must be able to see why the zero happened.
            failures.append(
                SourceFailure(
                    source=provider.name,
                    query=query.text,
                    reason="; ".join(page.warnings),
                    incomplete=False,
                )
            )
        cursor = page.next_cursor
        if cursor is None:
            exhausted = True
            break
    return _SourceOutcome(
        cursor=SourceCursor(
            source=provider.name,
            query=query.text,
            last_cursor=cursor,
            pages_fetched=pages,
            exhausted=exhausted,
        ),
        hits=tuple(hits),
        failures=tuple(failures),
    )


def _deduplicate(
    outcomes: Sequence[_SourceOutcome],
) -> tuple[tuple[_Bucket, ...], tuple[SourceFailure, ...]]:
    """Collapse hits by node key, keeping every source and rank that reported the work.

    A record with neither an identifier nor a title has no deterministic identity, so it
    cannot be deduplicated, screened, or cited. Dropping it is the only honest option, and
    the drop is recorded as an incomplete result for that source rather than swallowed.
    """
    buckets: dict[str, _Bucket] = {}
    dropped: dict[str, int] = {}
    for outcome in outcomes:
        for hit in outcome.hits:
            try:
                key = node_key_for(hit.candidate)
            except DomainValidationError:
                dropped[hit.source] = dropped.get(hit.source, 0) + 1
                continue
            bucket = buckets.get(key)
            if bucket is None:
                bucket = _Bucket(key=key, candidate=hit.candidate)
                buckets[key] = bucket
            bucket.add(hit)
    failures = tuple(
        SourceFailure(
            source=source,
            reason=(
                f"{count} record(s) carried neither an identifier nor a title and were "
                "dropped rather than guessed at"
            ),
            incomplete=True,
        )
        for source, count in sorted(dropped.items())
    )
    return tuple(buckets.values()), failures


def _snowball_reporting(result: SnowballResult) -> dict[str, tuple[list[str], dict[str, int]]]:
    """Node key -> the sources that reported it and the rank each gave it.

    Read off the fetched reference lists rather than off the deduplicated candidates, which
    is where two sources reporting the same work is still visible as corroboration.
    """
    alias = {
        source_key: target
        for target, sources in result.graph.merges().items()
        for source_key in sources
    }
    table: dict[str, tuple[list[str], dict[str, int]]] = {}
    for ref_list in result.graph.reference_lists():
        for rank, entry in enumerate(ref_list.entries, start=1):
            try:
                raw = node_key_for(entry)
            except DomainValidationError:  # pragma: no cover - dropped before the graph
                continue
            key = alias.get(raw, raw)
            sources, ranks = table.setdefault(key, ([], {}))
            if ref_list.source not in sources:
                sources.append(ref_list.source)
            ranks.setdefault(ref_list.source, rank)
    return table


# -- small helpers -----------------------------------------------------------


def _works_with_artifacts(existing: Sequence[ExistingRecord]) -> frozenset[WorkId]:
    """Works this workstation actually holds bytes for; the rest have no full text to read."""
    return frozenset(record.work.id for record in existing if record.artifacts)


def _selected_names(plan: SnowballPlan, providers: Mapping[str, SearchProvider]) -> tuple[str, ...]:
    """Source names the plan selects, in the order `run_snowball` asks them."""
    return tuple(plan.sources) if plan.sources else tuple(providers)


def _walked_sources(plan: SnowballPlan, providers: Mapping[str, SearchProvider]) -> tuple[str, ...]:
    """Selected sources that publish the graph this plan asks for.

    A source that publishes no reference list is not a gap in coverage: it never claimed it
    could answer, so it is left off the run's sources rather than recorded as searched.
    """
    return tuple(
        name for name in _selected_names(plan, providers) if _answers(providers[name], plan) is True
    )


def _reference_drop_notes(
    result: SnowballResult, walked: Sequence[str]
) -> tuple[SourceFailure, ...]:
    """Records a walked source deposited and refused to seed from, kept on the run.

    A reference list segmented badly turns 45 references into hundreds of seeds unless the
    fragments are gated, and a gate nobody can see makes the funnel unreadable in the other
    direction. These are complete answers, so `incomplete` is false and no cursor changes;
    they are here so `failures: []` cannot certify a denominator that quietly shrank
    (dogfood F10, and the same shape as the F1 zero-result note).
    """
    source = walked[0] if len(walked) == 1 else "snowball"
    return tuple(
        SourceFailure(source=source, reason=note, incomplete=False) for note in result.warnings
    )


def _no_graph_failures(
    plan: SnowballPlan, providers: Mapping[str, SearchProvider], seed: str
) -> tuple[SourceFailure, ...]:
    """Recorded when nothing could be walked at all, so the empty result is not read as none."""
    return tuple(
        SourceFailure(
            source=name,
            query=f"{SNOWBALL_QUERY_PREFIX}{seed}",
            reason=f"{name} publishes no {plan.direction} citation graph, so it was not walked",
            incomplete=True,
        )
        for name in _selected_names(plan, providers)
    )


def _answers(provider: SearchProvider, plan: SnowballPlan) -> bool:
    """True when this source declares the graph direction the plan wants."""
    capabilities = provider.capabilities()
    return (plan.wants_backward and capabilities.supports_references) or (
        plan.wants_forward and capabilities.supports_citations
    )


def _filters_of(query: SearchQuery, *, max_pages: int, cutoff: date | None) -> dict[str, str]:
    """The run's filter record: everything a rerun needs to ask the same question again."""
    filters = {"max_results": str(query.max_results), _FILTER_MAX_PAGES: str(max_pages)}
    if query.year_from is not None:
        filters["year_from"] = str(query.year_from)
    if query.year_to is not None:
        filters["year_to"] = str(query.year_to)
    if query.venue is not None:
        filters["venue"] = query.venue
    if query.fields_of_study:
        filters["fields_of_study"] = ", ".join(query.fields_of_study)
    if cutoff is not None:
        filters[_FILTER_CUTOFF] = cutoff.isoformat()
    return filters


def _query_of(run: SearchRun) -> SearchQuery:
    """Rebuild the `SearchQuery` a recorded run was executed with."""
    filters = run.filters
    fields = filters.get("fields_of_study", "")
    return SearchQuery(
        text=run.queries[0],
        year_from=_optional_int(filters.get("year_from")),
        year_to=_optional_int(filters.get("year_to")),
        venue=filters.get("venue"),
        max_results=_int_filter(filters, "max_results", 25),
        fields_of_study=tuple(part.strip() for part in fields.split(",") if part.strip()),
    )


def _int_filter(filters: Mapping[str, str], name: str, fallback: int) -> int:
    """A recorded integer filter, or ``fallback`` when the run did not record one."""
    value = _optional_int(filters.get(name))
    return fallback if value is None else value


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        logger.warning("ignoring non-numeric recorded filter value %r", value)
        return None


def _as_date(cutoff: str | date | None) -> date | None:
    """A `YYYY-MM` or `YYYY-MM-DD` cutoff as a date; `YYYY-MM` ends on the last of the month."""
    return None if cutoff is None else parse_cutoff(cutoff)

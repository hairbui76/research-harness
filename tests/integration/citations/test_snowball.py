"""Snowballing against fake in-memory sources: levels, dedup, failures, and screening.

No network, no keys, no recorded traffic: each fake source is a dict of node key ->
records, so the tests can assert exactly which calls a plan makes and what a broken
source does to the honesty of the result.
"""

from __future__ import annotations

from research_harness.citations.graph import node_key_for
from research_harness.citations.snowball import SnowballPlan, run_snowball
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    IdentityResolutionOutcome,
    ProvenanceSource,
    ScreeningState,
)
from research_harness.domain.ids import WorkId
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.ingest.identity import ExistingRecord
from research_harness.providers.models.base import EgressDeclaration
from research_harness.providers.search.base import (
    NotSupportedError,
    ReferenceCandidates,
    SearchPage,
    SearchProvider,
    SearchProviderCapabilities,
    SearchQuery,
    SearchRateLimitError,
)
from tests.unit.domain import strategies as sty

EGRESS = EgressDeclaration(
    endpoint_host="fake.invalid",
    sends_source_text=False,
    sends_identifiers=True,
    description="fake in-memory source",
)


def field(value: str, source: str) -> IdentifierField:
    return IdentifierField(
        value=value, source=ProvenanceSource.EXTERNAL_METADATA, note=f"record from {source}"
    )


def record(doi: str, source: str, *, title: str | None = None) -> WorkCandidate:
    """A candidate as one source would map it, carrying that source's provenance."""
    return WorkCandidate(
        provenance=Provenance(source=ProvenanceSource.EXTERNAL_METADATA, actor=source),
        metadata=CandidateMetadata(
            title=field(title, source) if title else None,
            identifiers=WorkIdentifiers(doi=field(doi, source)),
        ),
    )


def key(doi: str) -> str:
    return f"doi:{doi}"


def seed_ids(doi: str) -> WorkIdentifiers:
    return WorkIdentifiers(doi=field(doi, "seed"))


class FakeSource(SearchProvider):
    """An in-memory discovery source with a declared, and honoured, capability set."""

    def __init__(
        self,
        name: str,
        *,
        references: dict[str, list[WorkCandidate]] | None = None,
        citations: dict[str, list[WorkCandidate]] | None = None,
        supports_references: bool | None = None,
        supports_citations: bool | None = None,
        rate_limit_after: int | None = None,
        not_supported: bool = False,
    ) -> None:
        self.name = name
        self._references = references or {}
        self._citations = citations or {}
        self._supports_references = (
            supports_references if supports_references is not None else references is not None
        )
        self._supports_citations = (
            supports_citations if supports_citations is not None else citations is not None
        )
        self._rate_limit_after = rate_limit_after
        self._not_supported = not_supported
        self.calls: list[tuple[str, str]] = []

    def capabilities(self) -> SearchProviderCapabilities:
        return SearchProviderCapabilities(
            supports_cursor=False,
            supports_year_filter=False,
            supports_references=self._supports_references,
            supports_citations=self._supports_citations,
            requires_api_key=False,
            egress=EGRESS,
        )

    def search(self, query: SearchQuery) -> SearchPage:
        return SearchPage(source=self.name, query=query)

    def fetch_references(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        return self._graph_call("references", self._references, identifiers)

    def fetch_citations(self, identifiers: WorkIdentifiers) -> list[WorkCandidate]:
        return self._graph_call("citations", self._citations, identifiers)

    def _graph_call(
        self,
        operation: str,
        table: dict[str, list[WorkCandidate]],
        identifiers: WorkIdentifiers,
    ) -> list[WorkCandidate]:
        doi = identifiers.doi
        if doi is None:
            raise NotSupportedError(f"{self.name} needs a DOI", source=self.name)
        self.calls.append((operation, doi.value))
        if self._not_supported:
            raise NotSupportedError(f"{self.name} cannot address {doi.value}", source=self.name)
        if self._rate_limit_after is not None and len(self.calls) > self._rate_limit_after:
            raise SearchRateLimitError(
                "429 from fake source", source=self.name, query=doi.value, retry_after=30
            )
        entries = table.get(key(doi.value))
        if entries is None:
            return []
        # A `ReferenceCandidates` carries the adapter's drop counts; copying it loses them.
        return entries if isinstance(entries, ReferenceCandidates) else list(entries)


# -- levels ------------------------------------------------------------------


def test_each_level_is_fetched_and_counted() -> None:
    source = FakeSource(
        "source_a",
        references={
            key("10.1/seed"): [record("10.1/first", "source_a")],
            key("10.1/first"): [record("10.1/second", "source_a")],
            key("10.1/second"): [record("10.1/third", "source_a")],
        },
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=3)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.per_level_counts == (1, 1, 1)
    assert result.levels_fetched == 3
    assert result.keys() == (key("10.1/first"), key("10.1/second"), key("10.1/third"))
    assert result.graph.predecessors(key("10.1/seed"), 3) == (
        key("10.1/first"),
        key("10.1/second"),
        key("10.1/third"),
    )
    assert result.incomplete is False


def test_depth_is_respected() -> None:
    source = FakeSource(
        "source_a",
        references={
            key("10.1/seed"): [record("10.1/first", "source_a")],
            key("10.1/first"): [record("10.1/second", "source_a")],
        },
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.keys() == (key("10.1/first"),)
    assert source.calls == [("references", "10.1/seed")]


def test_both_directions_use_the_source_that_supports_each() -> None:
    backward = FakeSource(
        "references_only",
        references={key("10.1/seed"): [record("10.1/older", "references_only")]},
        supports_citations=False,
    )
    forward = FakeSource(
        "citations_only",
        citations={key("10.1/seed"): [record("10.1/newer", "citations_only")]},
        supports_references=False,
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="both", depth=1)

    result = run_snowball(
        plan,
        {"references_only": backward, "citations_only": forward},
        {key("10.1/seed"): seed_ids("10.1/seed")},
    )

    assert result.keys() == (key("10.1/newer"), key("10.1/older"))
    assert result.graph.references_of(key("10.1/seed")) == (key("10.1/older"),)
    assert result.graph.citations_of(key("10.1/seed")) == (key("10.1/newer"),)
    assert backward.calls == [("references", "10.1/seed")]
    assert forward.calls == [("citations", "10.1/seed")]


def test_a_direction_a_source_does_not_declare_is_never_called() -> None:
    source = FakeSource(
        "references_only",
        references={key("10.1/seed"): []},
        supports_citations=False,
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="forward", depth=1)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert source.calls == []
    assert result.discovered == ()
    assert result.incomplete is False


# -- deduplication -----------------------------------------------------------


def test_one_candidate_per_node_key_with_every_sources_provenance_kept() -> None:
    """Dedup is about counting, not about forgetting which sources agreed."""
    first = FakeSource(
        "source_a", references={key("10.1/seed"): [record("10.1/shared", "source_a")]}
    )
    second = FakeSource(
        "source_b",
        references={key("10.1/seed"): [record("10.1/shared", "source_b", title="Shared paper")]},
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(
        plan,
        {"source_a": first, "source_b": second},
        {key("10.1/seed"): seed_ids("10.1/seed")},
    )

    assert result.keys() == (key("10.1/shared"),)
    assert result.per_level_counts == (1,)
    assert result.sources_for(key("10.1/shared")) == ("source_a", "source_b")
    assert [entry.provenance.actor for entry in result.candidates_for(key("10.1/shared"))] == [
        "source_a",
        "source_b",
    ]
    assert result.graph.sources_for(key("10.1/seed"), key("10.1/shared")) == (
        "source_a",
        "source_b",
    )


def test_a_work_reached_twice_is_expanded_once() -> None:
    source = FakeSource(
        "source_a",
        references={
            key("10.1/seed"): [record("10.1/a", "source_a"), record("10.1/b", "source_a")],
            key("10.1/a"): [record("10.1/shared", "source_a")],
            key("10.1/b"): [record("10.1/shared", "source_a")],
            key("10.1/shared"): [],
        },
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=3)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.per_level_counts == (2, 1, 0)
    assert source.calls.count(("references", "10.1/shared")) == 1


# -- failures ----------------------------------------------------------------


def test_a_broken_source_is_recorded_and_marks_the_result_incomplete() -> None:
    """Product 18: a failed source query is never a zero-result."""
    flaky = FakeSource(
        "flaky_source",
        references={
            key("10.1/seed"): [record("10.1/first", "flaky_source")],
            key("10.1/first"): [record("10.1/never_seen", "flaky_source")],
        },
        rate_limit_after=1,
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=2)

    result = run_snowball(plan, {"flaky_source": flaky}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.incomplete is True
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.source == "flaky_source"
    assert failure.query == f"backward:{key('10.1/first')}"
    assert failure.reason.startswith("rate_limit:")
    assert "retry after 30s" in failure.reason
    assert result.keys() == (key("10.1/first"),), "the level that succeeded is still recorded"


def test_not_supported_is_not_a_failure() -> None:
    """A source that never claimed it could answer has not failed (Product 18)."""
    silent = FakeSource("silent_source", references={key("10.1/seed"): []}, not_supported=True)
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(
        plan, {"silent_source": silent}, {key("10.1/seed"): seed_ids("10.1/seed")}
    )

    assert silent.calls == [("references", "10.1/seed")]
    assert result.failures == ()
    assert result.incomplete is False
    assert result.discovered == ()


def test_a_truncated_level_marks_the_result_incomplete() -> None:
    source = FakeSource(
        "source_a",
        references={
            key("10.1/seed"): [
                record("10.1/a", "source_a"),
                record("10.1/b", "source_a"),
                record("10.1/c", "source_a"),
            ],
            key("10.1/a"): [record("10.1/deep", "source_a")],
            key("10.1/b"): [],
            key("10.1/c"): [],
        },
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=2, max_per_level=1)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.per_level_counts == (3, 1), "everything fetched is still recorded"
    assert result.incomplete is True
    assert source.calls == [("references", "10.1/seed"), ("references", "10.1/a")]


# -- discovery stays discovery -----------------------------------------------


def test_discovered_candidates_are_never_marked_beyond_discovered() -> None:
    """Product 14: snowballing fills the discovery space, not the corpus."""
    source = FakeSource(
        "source_a",
        references={key("10.1/seed"): [record("10.1/first", "source_a", title="A paper")]},
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.discovered
    assert all(entry.screening is ScreeningState.DISCOVERED for entry in result.discovered)
    assert all(
        entry.screening is ScreeningState.DISCOVERED
        for ref_list in result.graph.reference_lists()
        for entry in ref_list.entries
    )


# -- same-work resolution ----------------------------------------------------


def corpus() -> tuple[ExistingRecord, ...]:
    work = sty.make_work(
        id=WorkId("W0017"),
        title="An already ingested paper",
        authors=("Jane Doe",),
        year=2024,
        identifiers=WorkIdentifiers(doi=field("10.1/first", "corpus")),
    )
    return (ExistingRecord(work=work),)


def test_a_discovered_work_already_in_the_corpus_collapses_onto_its_work_id() -> None:
    source = FakeSource(
        "source_a", references={key("10.1/seed"): [record("10.1/first", "source_a")]}
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(
        plan,
        {"source_a": source},
        {key("10.1/seed"): seed_ids("10.1/seed")},
        existing=corpus(),
    )

    assert result.graph.references_of(key("10.1/seed")) == ("W0017",)
    assert result.graph.merges() == {"W0017": (key("10.1/first"),)}
    assert [node_key_for(entry) for entry in result.discovered] == ["W0017"]
    assert result.discovered[0].resolution is IdentityResolutionOutcome.SAME_WORK
    assert result.discovered[0].matched_work == WorkId("W0017")
    assert result.sources_for("W0017") == ("source_a",)


def test_an_ambiguous_identity_stays_its_own_node_and_is_reported() -> None:
    source = FakeSource(
        "source_a",
        references={
            key("10.1/seed"): [record("10.1/other", "source_a", title="An already ingested papers")]
        },
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(
        plan,
        {"source_a": source},
        {key("10.1/seed"): seed_ids("10.1/seed")},
        existing=corpus(),
    )

    assert result.unresolved == (key("10.1/other"),)
    assert result.graph.references_of(key("10.1/seed")) == (key("10.1/other"),)
    assert result.graph.merges() == {}


def test_without_a_corpus_nothing_is_resolved_and_nothing_is_claimed() -> None:
    source = FakeSource(
        "source_a", references={key("10.1/seed"): [record("10.1/first", "source_a")]}
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.unresolved == ()
    assert result.discovered[0].resolution is IdentityResolutionOutcome.UNRESOLVED


# -- plan selection ----------------------------------------------------------


def test_a_plan_may_name_the_sources_it_walks() -> None:
    asked = FakeSource("asked", references={key("10.1/seed"): []})
    ignored = FakeSource("ignored", references={key("10.1/seed"): []})
    plan = SnowballPlan(
        seeds=(key("10.1/seed"),), direction="backward", depth=1, sources=("asked",)
    )

    run_snowball(
        plan,
        {"asked": asked, "ignored": ignored},
        {key("10.1/seed"): seed_ids("10.1/seed")},
    )

    assert asked.calls == [("references", "10.1/seed")]
    assert ignored.calls == []


def test_a_seed_with_no_identifiers_is_not_expanded() -> None:
    source = FakeSource("source_a", references={key("10.1/seed"): []})
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(plan, {"source_a": source}, {})

    assert source.calls == []
    assert result.per_level_counts == (0,)


def test_a_record_with_no_identity_is_dropped_and_the_run_says_so() -> None:
    """A record that cannot be deduplicated or cited is a coverage gap, not a result."""
    nameless = WorkCandidate(
        provenance=Provenance(source=ProvenanceSource.EXTERNAL_METADATA, actor="source_a")
    )
    source = FakeSource(
        "source_a",
        references={key("10.1/seed"): [record("10.1/first", "source_a"), nameless]},
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.keys() == (key("10.1/first"),)
    assert result.incomplete is True
    assert result.failures == (), "a mangled record is not a source failure"
    assert result.graph.reference_lists()[0].incomplete is True
    assert any("no usable identity" in note for note in result.warnings)
    assert result.graph.reference_lists()[0].warnings == result.warnings


def test_an_adapters_own_drop_count_reaches_the_result() -> None:
    """Dogfood F10: the gate that stops fragments becoming seeds must be readable.

    `fetch_references` returns a list, so a source that deposited 45 references and 400
    fragments of them had nowhere to say so; `ReferenceCandidates` carries the count and
    the walk reports it on the reference list and on the run.
    """
    source = FakeSource(
        "source_a",
        references={
            key("10.1/seed"): ReferenceCandidates(
                [record("10.1/first", "source_a")],
                warnings=("reference_drops: source_a deposited 45 record(s); 3 fragments",),
            )
        },
    )
    plan = SnowballPlan(seeds=(key("10.1/seed"),), direction="backward", depth=1)

    result = run_snowball(plan, {"source_a": source}, {key("10.1/seed"): seed_ids("10.1/seed")})

    assert result.keys() == (key("10.1/first"),)
    assert result.failures == (), "a gated fragment is not a source failure"
    assert result.warnings == ("reference_drops: source_a deposited 45 record(s); 3 fragments",)
    assert result.graph.reference_lists()[0].warnings == result.warnings

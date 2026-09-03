"""SearchRun execution against fake sources: paging, failures, dedup, identity, screening.

The invariants under test are the ones a coverage claim later rests on (ROADMAP 12.2): a
source that broke is recorded as broken rather than as empty, paging boundaries are on the
record, two sources reporting one work is corroboration rather than a duplicate, and
nothing here turns a discovery result into corpus state.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    InitProjectRequest,
    MutationResult,
    RegisterWorkRequest,
)
from research_harness.capabilities.handlers import init_project, register_work
from research_harness.claims.coverage import run_is_incomplete, uncompleted_sources
from research_harness.discovery.screening import acquire, screen
from research_harness.discovery.search_runs import DiscoveryService
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    ArtifactKind,
    IdentityResolutionOutcome,
    ProvenanceSource,
    ScreeningState,
    VersionKind,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.research import SearchRun
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.providers.search.base import (
    SearchProviderRegistry,
    SearchQuery,
    SearchRateLimitError,
)
from tests.integration.discovery.fakes import FakeSearchSource, field, record

CORPUS_TITLE = "Structured traffic representations for LLM detection"
NEAR_TITLE = "Structured traffic representation for LLM detection"
CORPUS_DOI = "10.1234/corpus"
CORPUS_ARXIV = "2101.00001"
ARTIFACT_BYTES = b"%PDF-1.7\n% a stand-in for an acquired source file\n"

ALPHA = "10.1234/alpha"
BETA = "10.1234/beta"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """An initialized workspace opened as the researcher."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="discovery"))
    yield open_context(result.root, HUMAN_ACTOR)


@pytest.fixture
def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "source" / "corpus.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ARTIFACT_BYTES)
    return path


@pytest.fixture
def corpus(project: CapabilityContext, artifact: Path) -> CapabilityContext:
    """One registered Work carrying both a DOI and an arXiv id, so hits can match either."""
    register_work(
        project,
        RegisterWorkRequest(
            candidate=WorkCandidate(
                provenance=Provenance.system(actor="ingest"),
                metadata=CandidateMetadata(
                    title=IdentifierField(value=CORPUS_TITLE, source=ProvenanceSource.HUMAN),
                    identifiers=WorkIdentifiers(
                        doi=field(CORPUS_DOI, "corpus"), arxiv=field(CORPUS_ARXIV, "corpus")
                    ),
                ),
            ),
            artifact_path=artifact,
            version_kind=VersionKind.PREPRINT,
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    return project


def sources() -> tuple[FakeSearchSource, FakeSearchSource, FakeSearchSource]:
    """Three sources: one paged over two pages, one broken, one mirroring page one.

    The mirror reports `alpha` with the DOI upper-cased, which is the same work: DOIs are
    case-insensitive, so the node key normalizes and the two records deduplicate.
    """
    paged = FakeSearchSource(
        "paged",
        pages=[
            [
                record("paged", doi=ALPHA, title="Alpha", year=2024),
                record("paged", doi=CORPUS_DOI, title="Corpus by doi", year=2023),
            ],
            [
                record("paged", doi=BETA, title="Beta", year=2025),
                record("paged", arxiv=CORPUS_ARXIV, title="Corpus by arxiv", year=2023),
                record("paged", title=NEAR_TITLE, year=2023, authors=("Someone Else",)),
            ],
        ],
        open_access=True,
    )
    flaky = FakeSearchSource(
        "flaky",
        pages=[[record("flaky", doi="10.1234/never-seen", title="Unreachable")]],
        error=SearchRateLimitError("throttled", source="flaky", retry_after=30.0),
    )
    mirror = FakeSearchSource(
        "mirror", pages=[[record("mirror", doi=ALPHA.upper(), title="ALPHA, mirrored")]]
    )
    return paged, flaky, mirror


def registry(*providers: FakeSearchSource) -> SearchProviderRegistry:
    return SearchProviderRegistry(providers)


def run_discovery(
    ctx: CapabilityContext, *providers: FakeSearchSource, max_pages: int = 3
) -> tuple[SearchRun, MutationResult]:
    """Execute the standard query and return the persisted run with its mutation."""
    service = DiscoveryService(ctx, registry(*providers))
    return service.run_search(
        "structured traffic representations",
        SearchQuery(text="structured traffic representations", year_from=2020),
        max_pages=max_pages,
        cutoff="2026-08",
    )


def test_a_run_records_its_paging_boundaries_and_persists_them(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()

    run, mutation = run_discovery(corpus, paged, flaky, mirror)

    assert mutation.event.event.value == "search_run.recorded"
    cursors = {cursor.source: cursor for cursor in run.cursors}
    assert cursors["paged"].pages_fetched == 2
    assert cursors["paged"].exhausted is True
    assert cursors["paged"].last_cursor is None
    assert cursors["mirror"].pages_fetched == 1
    assert paged.searches == [None, "1"]
    assert corpus.repo.get_search_run(run.id).cursors == run.cursors
    assert run.cutoff is not None and run.cutoff.isoformat() == "2026-08-31"
    assert run.filters["max_pages"] == "3"
    assert run.filters["year_from"] == "2020"


def test_a_broken_source_is_recorded_as_broken_not_as_empty(corpus: CapabilityContext) -> None:
    """ROADMAP 12.1/12.2: a rate limit is a gap in coverage, never a zero-result search."""
    paged, flaky, mirror = sources()

    run, _ = run_discovery(corpus, paged, flaky, mirror)

    failures = {failure.source: failure for failure in run.failures}
    assert "rate_limit" in failures["flaky"].reason
    assert "retry after 30s" in failures["flaky"].reason
    assert failures["flaky"].incomplete is False
    flaky_cursor = next(cursor for cursor in run.cursors if cursor.source == "flaky")
    assert flaky_cursor.pages_fetched == 0 and flaky_cursor.exhausted is False
    assert run_is_incomplete(run) is True
    assert uncompleted_sources([run]) == ("flaky",)


def test_work_level_dedup_keeps_every_source_and_rank(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()

    run, _ = run_discovery(corpus, paged, flaky, mirror)

    alpha = run.candidate(f"doi:{ALPHA}")
    assert alpha is not None
    assert alpha.sources == ("paged", "mirror")
    assert alpha.ranks == {"paged": 1, "mirror": 1}
    assert len([entry for entry in run.candidates if entry.key == f"doi:{ALPHA}"]) == 1


def test_counts_follow_the_recorded_candidates(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()

    run, _ = run_discovery(corpus, paged, flaky, mirror)

    assert run.results.discovered == len(run.candidates) == 5
    assert run.results.screened == 0
    assert run.results.included == 0


def test_identity_resolution_records_matches_and_what_it_could_not_decide(
    corpus: CapabilityContext,
) -> None:
    paged, flaky, mirror = sources()
    work = corpus.repo.list_works()[0].id

    run, _ = run_discovery(corpus, paged, flaky, mirror)

    by_doi = run.candidate(f"doi:{CORPUS_DOI}")
    by_arxiv = run.candidate(f"arxiv:{CORPUS_ARXIV}")
    assert by_doi is not None and by_arxiv is not None
    assert by_doi.identity is IdentityResolutionOutcome.SAME_WORK
    assert by_arxiv.identity is IdentityResolutionOutcome.SAME_WORK
    assert by_doi.matched_work == by_arxiv.matched_work == work
    assert len(run.unresolved_keys) == 1
    unresolved = run.candidate(run.unresolved_keys[0])
    assert unresolved is not None
    assert unresolved.identity is IdentityResolutionOutcome.UNRESOLVED
    assert run.unresolved_identities == run.unresolved_keys


def test_two_candidates_for_one_work_stay_two_records(corpus: CapabilityContext) -> None:
    """ADR-002: work-level dedup never merges the Version and Artifact records behind it."""
    paged, flaky, mirror = sources()
    work = corpus.repo.list_works()[0]

    run, _ = run_discovery(corpus, paged, flaky, mirror)

    matched = [entry for entry in run.candidates if entry.matched_work == work.id]
    assert len(matched) == 2
    assert {entry.key for entry in matched} == {f"doi:{CORPUS_DOI}", f"arxiv:{CORPUS_ARXIV}"}
    assert [entry.sources for entry in matched] == [("paged",), ("paged",)]
    assert len(corpus.repo.list_versions(work.id)) == 1
    assert len(corpus.repo.list_artifacts(work.id)) == 1


def test_full_text_availability_is_recorded_per_candidate(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()

    run, _ = run_discovery(corpus, paged, flaky, mirror)

    mirrored_only = run.candidate(f"doi:{ALPHA}")
    assert mirrored_only is not None and mirrored_only.full_text_available is True
    assert set(run.full_text_unavailable_keys) <= {entry.key for entry in run.candidates}


def test_rerun_reproduces_the_same_candidates_as_a_new_run(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()
    first, _ = run_discovery(corpus, paged, flaky, mirror)

    service = DiscoveryService(corpus, registry(paged, flaky, mirror))
    second, mutation = service.rerun(first.id)

    assert second.id != first.id
    assert second.reproduces == first.id
    assert {entry.key for entry in second.candidates} == {entry.key for entry in first.candidates}
    assert second.queries == first.queries
    assert second.sources == first.sources
    assert second.filters == first.filters
    assert second.cutoff == first.cutoff
    assert mutation.validation.ok
    assert len(corpus.repo.list_search_runs()) == 2


def test_a_rerun_can_finish_what_the_first_run_could_not(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()
    first, _ = run_discovery(corpus, paged, flaky, mirror)
    flaky.heal()

    second, _ = DiscoveryService(corpus, registry(paged, flaky, mirror)).rerun(first.id)

    assert second.failures == ()
    assert run_is_incomplete(second) is False
    assert uncompleted_sources([first, second]) == ()


def test_excluding_a_candidate_requires_a_persisted_reason(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()
    run, _ = run_discovery(corpus, paged, flaky, mirror)
    key = f"doi:{ALPHA}"

    with pytest.raises(CapabilityError, match="requires a reason"):
        screen(corpus, run.id, key, ScreeningState.EXCLUDED)

    excluded, _ = screen(corpus, run.id, key, ScreeningState.EXCLUDED, reason="not about traffic")

    entry = excluded.candidate(key)
    assert entry is not None
    assert entry.screening is ScreeningState.EXCLUDED
    assert entry.exclusion_reason == "not about traffic"
    assert entry.screened_by == HUMAN_ACTOR and entry.screened_at is not None
    stored = corpus.repo.get_search_run(run.id).candidate(key)
    assert stored is not None and stored.exclusion_reason == "not about traffic"
    assert excluded.results.screened == 1 and excluded.results.included == 0


def test_an_inclusion_records_the_reason_it_was_included(corpus: CapabilityContext) -> None:
    """Dogfood F9: inclusion is the decision a reviewer is most often asked to defend."""
    paged, flaky, mirror = sources()
    run, _ = run_discovery(corpus, paged, flaky, mirror)

    included, _ = screen(
        corpus,
        run.id,
        f"doi:{ALPHA}",
        ScreeningState.INCLUDED,
        reason="pre-trained transformer over raw traffic",
    )

    entry = included.candidate(f"doi:{ALPHA}")
    assert entry is not None
    assert entry.screening_reason == "pre-trained transformer over raw traffic"
    assert entry.reason == "pre-trained transformer over raw traffic"
    assert entry.exclusion_reason is None
    stored = corpus.repo.get_search_run(run.id).candidate(f"doi:{ALPHA}")
    assert stored is not None and stored.screening_reason == entry.screening_reason


def test_an_exclusion_still_fills_the_legacy_field(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()
    run, _ = run_discovery(corpus, paged, flaky, mirror)

    excluded, _ = screen(
        corpus, run.id, f"doi:{ALPHA}", ScreeningState.EXCLUDED, reason="not about traffic"
    )

    entry = excluded.candidate(f"doi:{ALPHA}")
    assert entry is not None
    assert entry.exclusion_reason == "not about traffic"
    assert entry.screening_reason == "not about traffic"


def test_an_unscreened_candidate_records_no_reason(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()
    run, _ = run_discovery(corpus, paged, flaky, mirror)

    with pytest.raises(CapabilityError, match="records no reason"):
        screen(corpus, run.id, f"doi:{ALPHA}", ScreeningState.DISCOVERED, reason="not a decision")


def test_including_a_distinct_candidate_creates_no_work(corpus: CapabilityContext) -> None:
    """Product 14: inclusion is a decision; only source acquisition creates corpus state."""
    paged, flaky, mirror = sources()
    run, _ = run_discovery(corpus, paged, flaky, mirror)
    before = len(corpus.repo.list_works())

    included, _ = screen(corpus, run.id, f"doi:{BETA}", ScreeningState.INCLUDED)

    entry = included.candidate(f"doi:{BETA}")
    assert entry is not None
    assert entry.screening is ScreeningState.INCLUDED
    assert entry.identity is IdentityResolutionOutcome.DISTINCT_WORK
    assert entry.matched_work is None
    assert len(corpus.repo.list_works()) == before
    assert included.results.included == 1


def test_acquiring_a_candidate_is_what_creates_the_work(
    corpus: CapabilityContext, tmp_path: Path
) -> None:
    paged, flaky, mirror = sources()
    run, _ = run_discovery(corpus, paged, flaky, mirror)
    screen(corpus, run.id, f"doi:{BETA}", ScreeningState.INCLUDED)
    source_file = tmp_path / "beta.pdf"
    source_file.write_bytes(b"%PDF-1.7\n% beta\n")
    before = len(corpus.repo.list_works())

    acquired, ingested, _ = acquire(corpus, run.id, f"doi:{BETA}", source_file)

    entry = acquired.candidate(f"doi:{BETA}")
    assert entry is not None
    assert entry.matched_work == ingested.work
    assert entry.full_text_available is True
    assert len(corpus.repo.list_works()) == before + 1


def test_an_excluded_candidate_is_not_acquired_by_accident(
    corpus: CapabilityContext, tmp_path: Path
) -> None:
    paged, flaky, mirror = sources()
    run, _ = run_discovery(corpus, paged, flaky, mirror)
    screen(corpus, run.id, f"doi:{ALPHA}", ScreeningState.EXCLUDED, reason="out of scope")
    source_file = tmp_path / "alpha.pdf"
    source_file.write_bytes(b"%PDF-1.7\n% alpha\n")

    with pytest.raises(CapabilityError, match="was excluded"):
        acquire(corpus, run.id, f"doi:{ALPHA}", source_file)


def test_selecting_one_source_searches_only_that_source(corpus: CapabilityContext) -> None:
    paged, flaky, mirror = sources()
    service = DiscoveryService(corpus, registry(paged, flaky, mirror))

    run, _ = service.run_search(
        "structured traffic", SearchQuery(text="structured traffic"), sources=["mirror"]
    )

    assert run.sources == ("mirror",)
    assert paged.searches == [] and flaky.searches == []
    assert [entry.key for entry in run.candidates] == [f"doi:{ALPHA}"]


def test_a_zero_result_page_with_a_warning_is_recorded_as_such(
    corpus: CapabilityContext,
) -> None:
    """Dogfood F1: `exhausted: true, failures: []` made a degenerate zero look like a real one."""
    degenerate = FakeSearchSource(
        "arxiv",
        pages=[[]],
        warnings=(
            "zero_result_query: arxiv returned no records for a 3-term query; "
            'the query sent was: all:"structured" AND all:"traffic"',
        ),
    )

    run, _ = run_discovery(corpus, degenerate)

    assert run.candidates == ()
    failure = next(item for item in run.failures if item.source == "arxiv")
    assert failure.incomplete is False, "the slice was searched; only the query is suspect"
    assert failure.reason.startswith("zero_result_query:")
    assert 'all:"structured"' in failure.reason
    cursor = next(item for item in run.cursors if item.source == "arxiv")
    assert cursor.exhausted is True


def test_a_zero_result_page_without_a_warning_records_no_failure(
    corpus: CapabilityContext,
) -> None:
    """A source that searched and matched nothing is not a source that could not be searched."""
    quiet = FakeSearchSource("arxiv", pages=[[]])

    run, _ = run_discovery(corpus, quiet)

    assert run.candidates == ()
    assert [item for item in run.failures if item.source == "arxiv"] == []

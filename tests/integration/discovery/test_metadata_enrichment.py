"""Discovery metadata that a resolved candidate carries for a Work the corpus holds.

Dogfood F5: an OpenAlex record carried the correct six authors and venue for a paper the
corpus already held, resolved `same_work`, and the better metadata was never seen again --
while the Work kept the mojibake author list a broken publisher CMap had produced. These
tests pin the two halves of the fix: the enrichment is readable back off the run, and
applying it refuses loudly rather than writing behind the capability layer (ADR-004).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import InitProjectRequest, RegisterWorkRequest
from research_harness.capabilities.handlers import (
    CAPABILITY_HANDLERS,
    init_project,
    register_work,
)
from research_harness.discovery.search_runs import (
    METADATA_UPDATE_CAPABILITY,
    DiscoveryService,
    apply_enrichments,
    enrichments_for,
)
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    ArtifactKind,
    IdentityResolutionOutcome,
    ProvenanceSource,
    VersionKind,
)
from research_harness.domain.ids import WorkId
from research_harness.domain.research import SearchRun
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.providers.search.base import SearchProviderRegistry, SearchQuery
from tests.integration.discovery.fakes import FakeSearchSource, field, record

ET_BERT_TITLE = "ET-BERT: A Contextualized Datagram Representation for Encrypted Traffic"
ET_BERT_DOI = "10.1145/3485447.3512217"
ET_BERT_VENUE = "Proceedings of the ACM Web Conference 2022"

#: What a broken ToUnicode CMap left on page one: two abstract fragments and one
#: Caesar-shifted run. `parsing.quality` calls the third of these undecodable.
MOJIBAKE_AUTHORS = (
    "anced traffic data for accurate classification",
    "which is challenging",
    "ORVH\x10GRPDLQ",
)
REAL_AUTHORS = ("Xinjie Lin", "Gang Xiong", "Gaopeng Gou", "Zhen Li", "Junzheng Shi", "Jing Yu")

QUESTION = "pre-trained transformer encrypted traffic classification"

#: `work.update_metadata` is the capability an enrichment needs in order to be written
#: (ADR-004: `capabilities/` is the only mutation surface). Whether it exists is a
#: property of the build, so both halves of the contract are asserted here and the one
#: that does not apply is skipped rather than silently untested.
HAS_UPDATE_CAPABILITY = METADATA_UPDATE_CAPABILITY in CAPABILITY_HANDLERS


@pytest.fixture
def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "source" / "etbert.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n% a stand-in for the acquired source file\n")
    return path


@pytest.fixture
def corpus(tmp_path: Path, artifact: Path) -> Iterator[CapabilityContext]:
    """One Work ingested from a PDF whose author list came out as mojibake."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="enrichment"))
    ctx = open_context(result.root, HUMAN_ACTOR)
    register_work(
        ctx,
        RegisterWorkRequest(
            candidate=WorkCandidate(
                provenance=Provenance.system(actor="ingest"),
                metadata=CandidateMetadata(
                    title=IdentifierField(value=ET_BERT_TITLE, source=ProvenanceSource.SYSTEM),
                    authors=tuple(
                        IdentifierField(value=name, source=ProvenanceSource.SYSTEM)
                        for name in MOJIBAKE_AUTHORS
                    ),
                    year=IdentifierField(value="2022", source=ProvenanceSource.SYSTEM),
                    identifiers=WorkIdentifiers(doi=field(ET_BERT_DOI, "ingest")),
                ),
            ),
            artifact_path=artifact,
            version_kind=VersionKind.PREPRINT,
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    yield ctx


def discover(ctx: CapabilityContext, *providers: FakeSearchSource) -> SearchRun:
    service = DiscoveryService(ctx, SearchProviderRegistry(providers))
    run, _ = service.run_search(QUESTION, SearchQuery(text=QUESTION))
    return run


def openalex_like(
    *,
    title: str = ET_BERT_TITLE,
    year: int = 2022,
    authors: tuple[str, ...] = REAL_AUTHORS,
    venue: str | None = ET_BERT_VENUE,
) -> FakeSearchSource:
    """A source reporting the corpus paper with the metadata OpenAlex actually holds."""
    candidate = record("openalex", doi=ET_BERT_DOI, title=title, year=year, authors=authors)
    if venue is not None:
        candidate = candidate.touch(
            metadata=candidate.metadata.touch(venue=field(venue, "openalex"))
        )
    return FakeSearchSource("openalex", pages=[[candidate]])


def test_a_same_work_hit_keeps_its_better_metadata_as_an_enrichment(
    corpus: CapabilityContext,
) -> None:
    run = discover(corpus, openalex_like())
    entry = run.candidates[0]
    assert entry.identity is IdentityResolutionOutcome.SAME_WORK

    enrichments = DiscoveryService(corpus, SearchProviderRegistry(())).enrichments(run)

    assert len(enrichments) == 1
    enrichment = enrichments[0]
    assert enrichment.work == WorkId("W0001")
    assert enrichment.candidate_key == entry.key
    assert enrichment.sources == ("openalex",)
    assert enrichment.values("authors") == REAL_AUTHORS
    assert enrichment.values("venue") == (ET_BERT_VENUE,)
    assert "title" not in enrichment.fields, "the corpus title already agrees"
    assert "year" not in enrichment.fields


def test_the_enrichment_keeps_field_level_provenance(corpus: CapabilityContext) -> None:
    run = discover(corpus, openalex_like())

    enrichment = DiscoveryService(corpus, SearchProviderRegistry(())).enrichments(run)[0]

    proposed = enrichment.fields["authors"]
    assert all(value.source is ProvenanceSource.EXTERNAL_METADATA for value in proposed)
    assert all("openalex" in (value.note or "") for value in proposed)


def test_an_undecodable_author_list_is_reported_as_a_conflict_that_may_be_replaced(
    corpus: CapabilityContext,
) -> None:
    """Mojibake is not a value worth protecting, but replacing it is still recorded."""
    run = discover(corpus, openalex_like())

    enrichment = DiscoveryService(corpus, SearchProviderRegistry(())).enrichments(run)[0]

    conflict = next(item for item in enrichment.conflicts if item.field == "authors")
    assert conflict.existing_is_undecodable is True
    assert "ORVH" in conflict.existing
    assert "Xinjie Lin" in conflict.incoming


def test_a_readable_disagreement_is_recorded_but_not_proposed(corpus: CapabilityContext) -> None:
    run = discover(corpus, openalex_like(title="A Completely Different Title", year=2019))

    service = DiscoveryService(corpus, SearchProviderRegistry(()))
    enrichment = service.enrichments(run)[0]

    assert "title" not in enrichment.fields
    assert "year" not in enrichment.fields
    fields = {conflict.field for conflict in enrichment.conflicts}
    assert {"title", "year"} <= fields
    assert all(
        conflict.existing_is_undecodable is False
        for conflict in enrichment.conflicts
        if conflict.field in {"title", "year"}
    )


def test_a_researcher_can_ask_for_the_conflicting_fields_too(corpus: CapabilityContext) -> None:
    run = discover(corpus, openalex_like(title="A Completely Different Title", year=2019))

    service = DiscoveryService(corpus, SearchProviderRegistry(()))
    enrichment = service.enrichments(run, only_empty_or_undecodable=False)[0]

    assert enrichment.values("title") == ("A Completely Different Title",)
    assert enrichment.values("year") == ("2019",)


def test_a_source_that_agrees_produces_no_enrichment(corpus: CapabilityContext) -> None:
    """Nothing to add and nothing to disagree about is not an enrichment."""
    agreeing = FakeSearchSource(
        "openalex",
        pages=[
            [
                record(
                    "openalex",
                    doi=ET_BERT_DOI,
                    title=ET_BERT_TITLE,
                    year=2022,
                    authors=MOJIBAKE_AUTHORS,
                )
            ]
        ],
    )
    run = discover(corpus, agreeing)

    assert DiscoveryService(corpus, SearchProviderRegistry(())).enrichments(run) == []


def test_a_distinct_work_hit_is_not_an_enrichment(corpus: CapabilityContext) -> None:
    """Enrichment is about Works the corpus holds; a new paper is a discovery, not a fix."""
    other = FakeSearchSource(
        "openalex",
        pages=[[record("openalex", doi="10.1145/9999999", title="Something Else", year=2024)]],
    )
    run = discover(corpus, other)

    assert DiscoveryService(corpus, SearchProviderRegistry(())).enrichments(run) == []


# -- applying ----------------------------------------------------------------


@pytest.mark.skipif(HAS_UPDATE_CAPABILITY, reason="the capability exists in this build")
def test_applying_an_enrichment_refuses_and_names_the_missing_capability(
    corpus: CapabilityContext,
) -> None:
    """Without a capability to write it, the change is withheld loudly, never dropped."""
    run = discover(corpus, openalex_like())

    plan = apply_enrichments(corpus, run)

    assert plan.applied is False
    assert plan.missing_capability == METADATA_UPDATE_CAPABILITY
    assert METADATA_UPDATE_CAPABILITY in plan.message
    assert "nothing was written" in plan.message
    assert plan.updated == ()


@pytest.mark.skipif(not HAS_UPDATE_CAPABILITY, reason="the capability is not in this build")
def test_applying_an_enrichment_writes_it_through_the_capability(
    corpus: CapabilityContext,
) -> None:
    """When `work.update_metadata` exists the change goes through it, never around it."""
    run = discover(corpus, openalex_like())

    plan = apply_enrichments(corpus, run)

    assert plan.applied is True
    assert plan.missing_capability is None
    assert plan.updated == (WorkId("W0001"),)
    stored = corpus.repo.get_work(WorkId("W0001"))
    assert stored.authors == REAL_AUTHORS
    assert stored.venue == ET_BERT_VENUE
    assert stored.title == ET_BERT_TITLE


def test_the_plan_shows_the_work_as_it_would_read(corpus: CapabilityContext) -> None:
    run = discover(corpus, openalex_like())

    plan = apply_enrichments(corpus, run)

    assert len(plan.works) == 1
    proposed = plan.works[0]
    assert proposed.id == WorkId("W0001")
    assert proposed.authors == REAL_AUTHORS
    assert proposed.venue == ET_BERT_VENUE
    assert proposed.title == ET_BERT_TITLE, "an agreeing field is left exactly as it was"


@pytest.mark.skipif(HAS_UPDATE_CAPABILITY, reason="the capability exists in this build")
def test_the_stored_work_is_untouched_when_nothing_can_write_it(
    corpus: CapabilityContext,
) -> None:
    run = discover(corpus, openalex_like())

    apply_enrichments(corpus, run)

    stored = corpus.repo.get_work(WorkId("W0001"))
    assert stored.authors == MOJIBAKE_AUTHORS
    assert stored.venue is None


def test_reading_enrichments_never_writes_anything(corpus: CapabilityContext) -> None:
    """`enrichments` is a read: it must be safe to call before deciding anything."""
    run = discover(corpus, openalex_like())

    DiscoveryService(corpus, SearchProviderRegistry(())).enrichments(run)

    stored = corpus.repo.get_work(WorkId("W0001"))
    assert stored.authors == MOJIBAKE_AUTHORS
    assert stored.venue is None


def test_a_run_with_nothing_to_offer_yields_an_empty_plan(corpus: CapabilityContext) -> None:
    nothing = FakeSearchSource(
        "openalex",
        pages=[[record("openalex", doi="10.1145/9999999", title="Something Else", year=2024)]],
    )
    run = discover(corpus, nothing)

    plan = apply_enrichments(corpus, run)

    assert plan.works == ()
    assert plan.applied is False
    assert plan.missing_capability is None
    assert plan.updated == ()
    assert "no candidate" in plan.message


def test_enrichments_are_deterministic_for_the_same_run(corpus: CapabilityContext) -> None:
    run = discover(corpus, openalex_like())
    service = DiscoveryService(corpus, SearchProviderRegistry(()))

    assert service.enrichments(run) == service.enrichments(run)
    assert service.enrichments(run) == service.enrichments(str(run.id))


def test_the_read_needs_a_workspace_and_no_configured_source(corpus: CapabilityContext) -> None:
    """`enrichments_for` reads the record; it must work with no discovery source at all."""
    run = discover(corpus, openalex_like())

    assert enrichments_for(corpus, run) == enrichments_for(corpus, str(run.id))
    assert enrichments_for(corpus, run)[0].values("authors") == REAL_AUTHORS

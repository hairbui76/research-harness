"""Citation graph: node identity, `cites`-only edges, BFS limits, and same-work merging."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from research_harness.citations.graph import (
    CitationEdge,
    CitationGraph,
    ReferenceList,
    SemanticRelation,
    candidate_key,
    node_key_for,
    resolve_nodes,
    resolve_same_work,
)
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    IdentityResolutionOutcome,
    ProvenanceSource,
    VersionKind,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import EvidenceId, VersionId, WorkId
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    Version,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.ingest.identity import ExistingRecord
from tests.unit.domain import strategies as sty

RESNET_TITLE = "Deep Residual Learning for Image Recognition"
RESNET_DOI = "10.1109/cvpr.2016.90"
RESNET_ARXIV = "1512.03385"
EXTERNAL = Provenance(source=ProvenanceSource.EXTERNAL_METADATA, actor="fake_source")


def field(value: str) -> IdentifierField:
    return IdentifierField(value=value, source=ProvenanceSource.EXTERNAL_METADATA)


def candidate(
    *,
    doi: str | None = None,
    arxiv: str | None = None,
    title: str | None = None,
    year: str | None = None,
    authors: tuple[str, ...] = (),
    openalex: str | None = None,
    **overrides: Any,
) -> WorkCandidate:
    """A discovery candidate carrying exactly the identifiers the test cares about."""
    metadata = CandidateMetadata(
        title=field(title) if title else None,
        authors=tuple(field(author) for author in authors),
        year=field(year) if year else None,
        identifiers=WorkIdentifiers(
            doi=field(doi) if doi else None,
            arxiv=field(arxiv) if arxiv else None,
            openalex=field(openalex) if openalex else None,
        ),
    )
    return WorkCandidate(provenance=EXTERNAL, metadata=metadata, **overrides)


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 12, 0, tzinfo=UTC)


# -- node identity -----------------------------------------------------------


def test_doi_beats_arxiv_beats_title_when_building_a_node_key() -> None:
    everything = candidate(doi=RESNET_DOI, arxiv=RESNET_ARXIV, title=RESNET_TITLE, year="2016")
    no_doi = candidate(arxiv=RESNET_ARXIV, title=RESNET_TITLE, year="2016")
    title_only = candidate(title=RESNET_TITLE, year="2016")

    assert node_key_for(everything) == f"doi:{RESNET_DOI}"
    assert node_key_for(no_doi) == f"arxiv:{RESNET_ARXIV}"
    assert node_key_for(title_only) == "title:deep residual learning for image recognition|2016"


def test_node_key_normalizes_the_identifier_it_keys_on() -> None:
    resolver_url = candidate(doi="https://doi.org/10.1109/CVPR.2016.90")
    assert node_key_for(resolver_url) == f"doi:{RESNET_DOI}"


def test_arxiv_version_suffix_does_not_split_one_work_into_two_nodes() -> None:
    """The `vN` suffix identifies a Version; the graph is about the Work (ADR-002)."""
    assert node_key_for(candidate(arxiv=f"{RESNET_ARXIV}v1")) == node_key_for(
        candidate(arxiv=f"{RESNET_ARXIV}v2")
    )


def test_a_titled_candidate_without_a_year_still_keys_deterministically() -> None:
    assert candidate_key(candidate(title=RESNET_TITLE).metadata) == (
        "title:deep residual learning for image recognition|"
    )


def test_source_specific_identifiers_rank_below_the_title() -> None:
    """Keying on one source's id would keep two sources reporting one paper apart."""
    both = candidate(title=RESNET_TITLE, year="2016", openalex="W2194775991")
    assert node_key_for(both).startswith("title:")
    assert node_key_for(candidate(openalex="W2194775991")) == "openalex:w2194775991"


def test_a_candidate_with_no_identifier_and_no_title_is_refused() -> None:
    with pytest.raises(DomainValidationError):
        node_key_for(candidate())


def test_a_corpus_work_keys_on_its_work_id() -> None:
    assert node_key_for(sty.make_work()) == "W0017"


def test_a_resolved_candidate_keys_on_the_work_it_resolved_to() -> None:
    resolved = candidate(
        doi=RESNET_DOI,
        resolution=IdentityResolutionOutcome.SAME_WORK,
        matched_work=WorkId("W0017"),
    )
    assert node_key_for(resolved) == "W0017"


# -- link types --------------------------------------------------------------


def test_a_citation_edge_is_always_cites() -> None:
    edge = CitationEdge(citing="W0001", cited="W0002", source="fake_source")
    assert edge.kind == "cites"
    with pytest.raises(ValidationError):
        CitationEdge(citing="W0001", cited="W0002", source="fake_source", kind="extends")


def test_a_semantic_relation_without_evidence_is_rejected() -> None:
    """Product 17: only `cites` may exist without evidence."""
    with pytest.raises(ValidationError):
        SemanticRelation(
            kind="contradicts",
            from_work=WorkId("W0001"),
            to_work=WorkId("W0002"),
            evidence=(),
        )
    with pytest.raises(ValidationError):
        SemanticRelation(kind="extends", from_work=WorkId("W0001"), to_work=WorkId("W0002"))


def test_a_semantic_relation_with_evidence_records_its_verification() -> None:
    relation = SemanticRelation(
        kind="extends",
        from_work=WorkId("W0002"),
        to_work=WorkId("W0001"),
        evidence=(EvidenceId("E0482"),),
    )
    assert relation.evidence == (EvidenceId("E0482"),)
    assert relation.is_asserted is False
    assert relation.touch(verified=True).is_asserted is True


def test_a_semantic_relation_may_not_point_a_work_at_itself() -> None:
    with pytest.raises(ValidationError):
        SemanticRelation(
            kind="replicates",
            from_work=WorkId("W0001"),
            to_work=WorkId("W0001"),
            evidence=(EvidenceId("E0482"),),
        )


# -- adjacency ---------------------------------------------------------------


def test_a_reference_list_orients_its_edges_by_direction() -> None:
    graph = CitationGraph()
    graph.add_reference_list(
        ReferenceList(
            work="W0001",
            source="fake_source",
            direction="backward",
            entries=(candidate(doi=RESNET_DOI),),
        )
    )
    graph.add_reference_list(
        ReferenceList(
            work="W0001",
            source="fake_source",
            direction="forward",
            entries=(candidate(doi="10.1/newer"),),
        )
    )
    assert graph.references_of("W0001") == (f"doi:{RESNET_DOI}",)
    assert graph.citations_of("W0001") == ("doi:10.1/newer",)


def test_two_sources_reporting_one_citation_stay_two_edges() -> None:
    """Corroboration is information: collapsing it would erase who agreed with whom."""
    graph = CitationGraph()
    for source in ("source_a", "source_b"):
        graph.add_edge(CitationEdge(citing="W0001", cited="W0002", source=source))
    assert len(graph.edges()) == 2
    assert graph.sources_for("W0001", "W0002") == ("source_a", "source_b")
    assert graph.references_of("W0001") == ("W0002",)


def test_repeating_one_source_keeps_the_first_sighting() -> None:
    graph = CitationGraph()
    graph.add_edge(CitationEdge(citing="W0001", cited="W0002", source="a", recorded_at=at(2)))
    graph.add_edge(CitationEdge(citing="W0001", cited="W0002", source="a", recorded_at=at(1)))
    graph.add_edge(CitationEdge(citing="W0001", cited="W0002", source="a", recorded_at=at(3)))
    assert [edge.recorded_at for edge in graph.edges()] == [at(1)]


def chain() -> CitationGraph:
    """`a` cites `b` cites `c` cites `d`, all from one source."""
    graph = CitationGraph()
    for citing, cited in (("a", "b"), ("b", "c"), ("c", "d")):
        graph.add_edge(CitationEdge(citing=citing, cited=cited, source="fake_source"))
    return graph


def test_predecessor_exploration_stops_at_the_requested_depth() -> None:
    graph = chain()
    assert graph.predecessors("a", 0) == ()
    assert graph.predecessors("a", 1) == ("b",)
    assert graph.predecessors("a", 2) == ("b", "c")
    assert graph.predecessors("a", 3) == ("b", "c", "d")
    assert graph.predecessors("a", 9) == ("b", "c", "d")


def test_successor_exploration_walks_the_other_way() -> None:
    graph = chain()
    assert graph.successors("d", 1) == ("c",)
    assert graph.successors("d", 2) == ("c", "b")
    assert graph.successors("a", 1) == ()


def test_a_citation_cycle_terminates() -> None:
    graph = chain()
    graph.add_edge(CitationEdge(citing="d", cited="a", source="fake_source"))
    assert graph.predecessors("a", 9) == ("b", "c", "d")


# -- merging -----------------------------------------------------------------


def test_merge_nodes_collapses_duplicate_edges_and_records_what_it_collapsed() -> None:
    graph = CitationGraph()
    graph.add_edge(CitationEdge(citing=f"doi:{RESNET_DOI}", cited="W0002", source="a"))
    graph.add_edge(CitationEdge(citing="W0001", cited="W0002", source="a"))
    graph.add_edge(CitationEdge(citing="W0003", cited="W0002", source="a"))

    merged = graph.merge_nodes({f"doi:{RESNET_DOI}": "W0001"})

    assert [(edge.citing, edge.cited) for edge in merged.edges()] == [
        ("W0001", "W0002"),
        ("W0003", "W0002"),
    ]
    assert merged.merges() == {"W0001": (f"doi:{RESNET_DOI}",)}
    assert len(graph.edges()) == 3, "merge_nodes returns a new graph and leaves this one alone"


def test_merging_two_ends_of_one_edge_drops_the_self_citation() -> None:
    graph = CitationGraph()
    graph.add_edge(CitationEdge(citing=f"arxiv:{RESNET_ARXIV}", cited="W0001", source="a"))
    merged = graph.merge_nodes({f"arxiv:{RESNET_ARXIV}": "W0001"})
    assert merged.edges() == ()
    assert merged.merges() == {"W0001": (f"arxiv:{RESNET_ARXIV}",)}


def test_merging_keeps_each_sources_edge_and_remaps_reference_lists() -> None:
    graph = CitationGraph()
    for source in ("source_a", "source_b"):
        graph.add_reference_list(
            ReferenceList(
                work=f"doi:{RESNET_DOI}", source=source, entries=(candidate(doi="10.1/cited"),)
            )
        )
    merged = graph.merge_nodes({f"doi:{RESNET_DOI}": "W0017"})
    assert merged.sources_for("W0017", "doi:10.1/cited") == ("source_a", "source_b")
    assert {ref_list.work for ref_list in merged.reference_lists()} == {"W0017"}


# -- projection rows ---------------------------------------------------------


def test_rows_round_trip_the_adjacency() -> None:
    graph = chain()
    graph.add_edge(CitationEdge(citing="a", cited="b", source="other_source", recorded_at=at(4)))

    rows = graph.to_rows()

    assert rows[0] == {
        "citing": "a",
        "cited": "b",
        "kind": "cites",
        "source": "fake_source",
        "recorded_at": rows[0]["recorded_at"],
    }
    assert CitationGraph.from_rows(rows).edges() == graph.edges()
    assert CitationGraph.from_rows(rows).to_rows() == rows


# -- same-work resolution ----------------------------------------------------


def corpus() -> tuple[ExistingRecord, ...]:
    """One corpus work with a DOI, an arXiv base id, and one pinned arXiv version."""
    work = sty.make_work(
        title=RESNET_TITLE,
        authors=("Kaiming He", "Xiangyu Zhang"),
        year=2016,
        identifiers=WorkIdentifiers(doi=field(RESNET_DOI), arxiv=field(RESNET_ARXIV)),
    )
    version = Version(
        id=VersionId("V0017-2"),
        work=WorkId("W0017"),
        kind=VersionKind.ARXIV,
        label="v2",
        identifiers=WorkIdentifiers(arxiv=field(f"{RESNET_ARXIV}v2")),
        provenance=EXTERNAL,
    )
    return (ExistingRecord(work=work, versions=(version,)),)


def test_resolve_same_work_maps_only_the_definite_outcomes() -> None:
    same_work = candidate(doi=RESNET_DOI)
    same_version = candidate(arxiv=f"{RESNET_ARXIV}v2")
    distinct = candidate(doi="10.1/unrelated", title="A completely different paper")
    ambiguous = candidate(title=RESNET_TITLE + "s")

    mapping = resolve_same_work((same_work, same_version, distinct, ambiguous), corpus())

    assert mapping == {f"doi:{RESNET_DOI}": "W0017", f"arxiv:{RESNET_ARXIV}": "W0017"}


def test_resolve_nodes_reports_the_outcomes_that_did_not_map() -> None:
    distinct = candidate(doi="10.1/unrelated", title="A completely different paper")
    ambiguous = candidate(title=RESNET_TITLE + "s")

    outcomes = {
        resolution.key: resolution.outcome
        for resolution in resolve_nodes((distinct, ambiguous), corpus())
    }

    assert outcomes["doi:10.1/unrelated"] is IdentityResolutionOutcome.DISTINCT_WORK
    assert outcomes[f"title:{RESNET_TITLE.casefold()}s|"] is IdentityResolutionOutcome.UNRESOLVED


def test_a_resolved_node_carries_its_outcome_without_advancing_screening() -> None:
    """Identity resolution is not screening: discovery stays discovery (Product 14)."""
    resolution = resolve_nodes((candidate(doi=RESNET_DOI),), corpus())[0]
    assert resolution.is_same_work
    assert resolution.resolved.matched_work == WorkId("W0017")
    assert resolution.resolved.screening.value == "discovered"


def test_resolving_against_an_empty_corpus_maps_nothing() -> None:
    assert resolve_same_work((candidate(doi=RESNET_DOI),), ()) == {}


def test_candidates_sharing_a_node_key_are_resolved_once() -> None:
    twice = (candidate(doi=RESNET_DOI), candidate(doi=RESNET_DOI, title=RESNET_TITLE))
    assert len(resolve_nodes(twice, corpus())) == 1


def test_a_work_is_never_confused_with_its_versions_in_the_graph() -> None:
    """A Version id is not a node: the graph is Work-level (ADR-002)."""
    record = corpus()[0]
    assert node_key_for(record.work) == "W0017"
    assert isinstance(record.versions[0], Version)
    assert node_key_for(record.work) not in {str(version.id) for version in record.versions}

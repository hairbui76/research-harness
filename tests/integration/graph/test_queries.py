"""The query modes: exact resolution, autocomplete, traversal, provenance, search, filters.

Graph spec 11.2 lives here: Claim -> supporting/contradicting Evidence -> the exact Artifact
anchor, in both directions, with the page and block the evidence was accepted from.
"""

from __future__ import annotations

from research_harness.domain.graph import (
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.graph.projectors import block_identity, candidate_identity, citation_identity
from research_harness.graph.queries import Direction, GraphFilter
from research_harness.graph.service import ResearchGraph
from tests.integration.graph.conftest import (
    ARTIFACT,
    CANDIDATE_ID,
    CITATION_KEY,
    CLAIM,
    CONTRADICTING,
    DATASET,
    MATRIX,
    PARAGRAPH,
    SUPPORTING,
    TABLE,
    WORK,
)

QUESTION = "RQ0003"
DECISION = "D0027"


# --- exact reference resolution ---------------------------------------------


def test_a_stable_reference_resolves_with_or_without_the_sigil(graph: ResearchGraph) -> None:
    with_sigil = graph.resolve("@E0482")
    without = graph.resolve("E0482")

    assert with_sigil is not None
    assert with_sigil == without
    assert with_sigil.kind is NodeKind.EVIDENCE
    assert with_sigil.authority is GraphAuthority.ACCEPTED


def test_a_node_identity_that_is_not_a_reference_still_resolves(graph: ResearchGraph) -> None:
    assert graph.resolve(citation_identity(CITATION_KEY)) is not None
    assert graph.resolve(block_identity(str(ARTIFACT), str(PARAGRAPH))) is not None


def test_an_unknown_reference_resolves_to_nothing(graph: ResearchGraph) -> None:
    assert graph.resolve("@E9999") is None
    assert graph.resolve("not-a-reference") is None


# --- autocomplete -----------------------------------------------------------


def test_autocomplete_matches_an_identity_prefix_first(graph: ResearchGraph) -> None:
    found = [record.identity for record in graph.autocomplete("@E04")]

    assert found == [str(SUPPORTING), str(CONTRADICTING)]


def test_autocomplete_falls_back_to_the_text_index(graph: ResearchGraph) -> None:
    found = [record.identity for record in graph.autocomplete("CICIDS")]

    assert str(SUPPORTING) in found
    assert block_identity(str(ARTIFACT), str(PARAGRAPH)) in found


def test_autocomplete_can_be_narrowed_to_one_kind(graph: ResearchGraph) -> None:
    found = graph.autocomplete("CICIDS", kinds=(NodeKind.EVIDENCE,))

    assert found
    assert {record.kind for record in found} == {NodeKind.EVIDENCE}


def test_autocomplete_of_nothing_is_nothing(graph: ResearchGraph) -> None:
    assert graph.autocomplete("") == []
    assert graph.autocomplete("@E04", limit=0) == []


# --- traversal in both directions -------------------------------------------


def test_a_claim_reaches_its_supporting_and_contradicting_evidence(
    graph: ResearchGraph,
) -> None:
    supporting = graph.neighbors(
        str(CLAIM), hops=1, direction=Direction.IN, edge_kinds=(EdgeKind.SUPPORTS,), limit=0
    )
    contradicting = graph.neighbors(
        str(CLAIM), hops=1, direction=Direction.IN, edge_kinds=(EdgeKind.CONTRADICTS,), limit=0
    )

    assert {n.node.identity for n in supporting if n.edge.origin is EdgeOrigin.ACCEPTED} == {
        str(SUPPORTING)
    }
    assert {n.node.identity for n in contradicting} == {str(CONTRADICTING)}


def test_evidence_reaches_its_claim_the_other_way(graph: ResearchGraph) -> None:
    out = graph.neighbors(
        str(SUPPORTING), hops=1, direction=Direction.OUT, edge_kinds=(EdgeKind.SUPPORTS,), limit=0
    )

    assert [n.node.identity for n in out] == [str(CLAIM)]


def test_evidence_reaches_its_exact_artifact_anchor(graph: ResearchGraph) -> None:
    anchored = graph.neighbors(str(SUPPORTING), hops=1, edge_kinds=(EdgeKind.ANCHORED_AT,), limit=0)
    by_target = {n.node.identity: n.edge for n in anchored}

    assert set(by_target) == {
        str(ARTIFACT),
        block_identity(str(ARTIFACT), str(PARAGRAPH)),
    }
    anchor = by_target[str(ARTIFACT)]
    assert anchor.metadata["page"] == 8
    assert anchor.metadata["block"] == str(PARAGRAPH)
    assert anchor.metadata["char_start"] == 284


def test_two_hops_reach_the_block_from_the_claim(graph: ResearchGraph) -> None:
    reached = {n.node.identity for n in graph.neighbors(str(CLAIM), hops=2, limit=0)}

    assert block_identity(str(ARTIFACT), str(PARAGRAPH)) in reached
    assert block_identity(str(ARTIFACT), str(TABLE)) in reached
    assert str(ARTIFACT) in reached


def test_one_hop_does_not_reach_what_only_two_hops_can(graph: ResearchGraph) -> None:
    one = {n.node.identity for n in graph.neighbors(str(CLAIM), hops=1, limit=0)}

    assert str(ARTIFACT) not in one


def test_a_traversal_can_be_filtered_by_node_kind_and_authority(graph: ResearchGraph) -> None:
    evidence = graph.neighbors(
        str(CLAIM),
        hops=1,
        kinds=(NodeKind.EVIDENCE,),
        authority=(GraphAuthority.ACCEPTED,),
        limit=0,
    )

    assert {n.node.identity for n in evidence} == {str(SUPPORTING), str(CONTRADICTING)}


def test_a_visibility_filter_is_already_a_first_class_traversal_argument(
    graph: ResearchGraph,
) -> None:
    """Nothing canonical is private yet; the slot the session namespace needs is here."""
    visible = graph.neighbors(str(CLAIM), hops=2, visibility=(GraphVisibility.PROJECT,), limit=0)
    hidden = graph.neighbors(str(CLAIM), hops=2, visibility=(GraphVisibility.PRIVATE,), limit=0)

    assert visible
    assert hidden == []


def test_neighbours_come_back_in_a_stable_order(graph: ResearchGraph) -> None:
    first = graph.neighbors(str(CLAIM), hops=2, limit=0)
    second = graph.neighbors(str(CLAIM), hops=2, limit=0)

    assert [n.node.identity for n in first] == [n.node.identity for n in second]
    assert [n.hops for n in first] == sorted(n.hops for n in first)


# --- provenance -------------------------------------------------------------


def test_provenance_walks_claim_to_evidence_to_the_artifact_anchor(
    graph: ResearchGraph,
) -> None:
    path = graph.provenance(str(CLAIM))

    assert path is not None
    assert path.origin.identity == str(CLAIM)
    assert path.target.identity == str(ARTIFACT)
    assert path.identities[1] in {str(SUPPORTING), str(CONTRADICTING)}
    assert path.anchor["page"] in {8, 9}
    assert str(path.anchor["block"]).startswith("B008")


def test_provenance_from_evidence_is_one_hop(graph: ResearchGraph) -> None:
    path = graph.provenance(str(SUPPORTING))

    assert path is not None
    assert path.identities == (str(SUPPORTING), str(ARTIFACT))
    assert path.anchor["text_hash"]


def test_provenance_to_the_node_kind_it_already_is_is_empty(graph: ResearchGraph) -> None:
    path = graph.provenance(str(ARTIFACT))

    assert path is not None
    assert path.steps == ()
    assert path.target.identity == str(ARTIFACT)


def test_provenance_of_an_unknown_node_is_nothing(graph: ResearchGraph) -> None:
    assert graph.provenance("E9999") is None


def test_provenance_can_target_another_kind(graph: ResearchGraph) -> None:
    path = graph.provenance(str(CLAIM), to_kind=NodeKind.WORK)

    assert path is not None
    assert path.target.identity == str(WORK)


# --- dependencies and citations ---------------------------------------------


def test_dependents_names_what_a_change_to_the_evidence_reaches(graph: ResearchGraph) -> None:
    found = {record.identity for record in graph.dependents(str(SUPPORTING))}

    assert found == {str(CLAIM), str(MATRIX)}


def test_dependents_of_a_claim_reaches_the_question_and_the_anchor(
    graph: ResearchGraph,
) -> None:
    found = {record.identity for record in graph.dependents(str(CLAIM))}

    assert QUESTION in found
    assert any(identity.startswith("anchor:") for identity in found)


def test_citations_lists_what_a_document_cites(graph: ResearchGraph) -> None:
    assert [record.identity for record in graph.citations(str(ARTIFACT))] == [
        citation_identity(CITATION_KEY)
    ]


def test_what_cites_a_reference_is_the_reverse_traversal(graph: ResearchGraph) -> None:
    citing = graph.neighbors(
        citation_identity(CITATION_KEY),
        hops=1,
        direction=Direction.IN,
        edge_kinds=(EdgeKind.CITES,),
        limit=0,
    )

    assert str(ARTIFACT) in {n.node.identity for n in citing}
    assert any(n.node.kind is NodeKind.MANUSCRIPT_ANCHOR for n in citing)


# --- structured query -------------------------------------------------------


def test_query_filters_by_kind_and_authority(graph: ResearchGraph) -> None:
    accepted = graph.query(
        GraphFilter(kinds=(NodeKind.EVIDENCE,), authorities=(GraphAuthority.ACCEPTED,))
    )
    candidates = graph.query(
        GraphFilter(kinds=(NodeKind.EVIDENCE,), authorities=(GraphAuthority.CANDIDATE,))
    )

    assert {record.identity for record in accepted} == {str(SUPPORTING), str(CONTRADICTING)}
    assert {record.identity for record in candidates} == {candidate_identity(CANDIDATE_ID)}


def test_query_can_join_through_an_edge(graph: ResearchGraph) -> None:
    supporting = graph.query(
        GraphFilter(
            kinds=(NodeKind.EVIDENCE,),
            edge_kinds=(EdgeKind.SUPPORTS,),
            origins=(EdgeOrigin.ACCEPTED,),
            direction=Direction.IN,
            linked_to=str(CLAIM),
        )
    )

    assert [record.identity for record in supporting] == [str(SUPPORTING)]


def test_query_respects_its_limit_and_is_ordered_by_identity(graph: ResearchGraph) -> None:
    found = graph.query(GraphFilter(limit=3))

    assert len(found) == 3
    assert [record.identity for record in found] == sorted(record.identity for record in found)


def test_a_zero_limit_returns_nothing(graph: ResearchGraph) -> None:
    assert graph.query(GraphFilter(limit=0)) == []


# --- lexical search ---------------------------------------------------------


def test_search_finds_the_dataset_name_across_kinds(graph: ResearchGraph) -> None:
    hits = graph.search(DATASET)

    assert {hit.node.identity for hit in hits} >= {
        str(SUPPORTING),
        block_identity(str(ARTIFACT), str(PARAGRAPH)),
    }
    assert all(hit.snippet for hit in hits)


def test_search_can_be_constrained_to_a_neighbourhood(graph: ResearchGraph) -> None:
    inside = graph.search(DATASET, neighbourhood=str(CLAIM), hops=1)
    outside = graph.search(DATASET, neighbourhood=str(MATRIX), hops=1)

    assert {hit.node.identity for hit in inside} == {str(SUPPORTING)}
    assert {hit.node.identity for hit in outside} == {str(SUPPORTING)}
    assert block_identity(str(ARTIFACT), str(PARAGRAPH)) not in {
        hit.node.identity for hit in inside
    }


def test_search_input_is_never_an_fts_syntax_error(graph: ResearchGraph) -> None:
    hostile = ['"', "AND", "((", "NOT", "* OR", 'CICIDS2017" OR "x', "a AND AND b"]
    for terms in hostile:
        assert isinstance(graph.search(terms), list)


def test_search_can_be_filtered_by_authority(graph: ResearchGraph) -> None:
    hits = graph.search(DATASET, filters=GraphFilter(authorities=(GraphAuthority.CANDIDATE,)))

    assert {hit.node.identity for hit in hits} == {candidate_identity(CANDIDATE_ID)}

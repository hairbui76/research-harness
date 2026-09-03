"""`ResearchGraph.context_fragments`: the selection order and provenance of graph spec §7.

The assembler is the graph's contribution to a `ContextPack`, and the properties that make
it usable to the conversation layer are all about *order and labelling* rather than about
which particular rows come back:

1. an exactly referenced accepted object outranks everything;
2. the accepted relations that bear on it come next;
3. then the current session, then relevant cross-session and corpus material, then the
   wider neighbourhood;
4. every fragment names the path walked to reach it, so the answer is traceable;
5. a candidate or a stale node is labelled and demoted, never substituted for an accepted
   one (ADR-003, graph spec §8).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from research_harness.domain.graph import ContextFragment, GraphAuthority, GraphVisibility
from research_harness.graph.context import (
    ACCEPTED_STATE,
    ATTACHMENTS,
    CURRENT_SESSION,
    DISCOVERY,
    PRIOR_SESSIONS,
    estimate_tokens,
)
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import CANDIDATE_ID, CLAIM, CONTRADICTING, SUPPORTING
from tests.integration.graph.test_sessions_rebuild import (
    PRIVATE,
    SHARED,
    SHARED_ATTACHMENT,
    SHARED_QUESTION,
    add_sessions,
)

LOCAL = GraphVisibility.PRIVATE.value


@pytest.fixture
def graph_with_sessions(repo: WorkspaceRepository) -> Iterator[ResearchGraph]:
    add_sessions(repo)
    built = ResearchGraph(repo)
    built.rebuild()
    yield built
    built.close()


def by_id(fragments: tuple[ContextFragment, ...]) -> dict[str, ContextFragment]:
    return {fragment.id: fragment for fragment in fragments}


# --- selection order --------------------------------------------------------


def test_an_exactly_referenced_object_outranks_everything_else(
    graph_with_sessions: ResearchGraph,
) -> None:
    fragments = graph_with_sessions.context_fragments(
        session=str(SHARED), query="CICIDS2017", references=[f"@{CLAIM}"], visibility=LOCAL
    )

    assert fragments[0].id == str(CLAIM)
    assert fragments[0].score == 1.0
    assert fragments[0].context_class == ACCEPTED_STATE


def test_the_accepted_relations_of_a_referenced_claim_come_next(
    graph_with_sessions: ResearchGraph,
) -> None:
    """Supporting and contradicting Evidence, both — a pack that hid one would mislead."""
    fragments = graph_with_sessions.context_fragments(
        session=None, query="", references=[str(CLAIM)], visibility=LOCAL
    )
    found = by_id(fragments)

    for evidence in (str(SUPPORTING), str(CONTRADICTING)):
        assert evidence in found, evidence
        assert found[evidence].relation_path == (str(CLAIM), evidence)
        assert found[evidence].score < fragments[0].score


def test_the_current_session_ranks_below_accepted_state_and_above_the_rest(
    graph_with_sessions: ResearchGraph,
) -> None:
    """Workspace spec §6: accepted scientific state outranks conversational memory."""
    fragments = graph_with_sessions.context_fragments(
        session=str(SHARED), query="CICIDS2017", references=[str(CLAIM)], visibility=LOCAL
    )
    found = by_id(fragments)

    assert found[str(CLAIM)].score > found[str(SHARED)].score
    assert found[str(SHARED)].context_class == CURRENT_SESSION
    assert found[str(SHARED_QUESTION)].context_class == CURRENT_SESSION
    assert found[str(SHARED_ATTACHMENT)].context_class == ATTACHMENTS


def test_another_session_is_prior_context_rather_than_current(
    graph_with_sessions: ResearchGraph,
) -> None:
    fragments = graph_with_sessions.context_fragments(
        session=str(SHARED), query="hunches CICIDS2017", references=[], visibility=LOCAL
    )
    found = by_id(fragments)

    assert str(PRIVATE) in found
    assert found[str(PRIVATE)].context_class == PRIOR_SESSIONS


def test_a_query_with_no_references_still_finds_relevant_corpus_material(
    graph_with_sessions: ResearchGraph,
) -> None:
    fragments = graph_with_sessions.context_fragments(
        session=None, query="CICIDS2017", references=[], visibility=LOCAL
    )

    assert fragments
    assert any(fragment.text for fragment in fragments)


# --- provenance -------------------------------------------------------------


def test_every_fragment_names_the_path_walked_to_reach_it(
    graph_with_sessions: ResearchGraph,
) -> None:
    fragments = graph_with_sessions.context_fragments(
        session=str(SHARED), query="CICIDS2017", references=[str(CLAIM)], visibility=LOCAL
    )

    for fragment in fragments:
        assert fragment.relation_path, fragment.id
        assert fragment.relation_path[-1] == fragment.id


def test_every_fragment_points_at_the_durable_file_it_came_from(
    graph_with_sessions: ResearchGraph,
) -> None:
    fragments = graph_with_sessions.context_fragments(
        session=str(SHARED), query="CICIDS2017", references=[str(CLAIM)], visibility=LOCAL
    )
    found = by_id(fragments)

    assert found[str(CLAIM)].source_pointer == "claims/C0041.yaml"
    assert found[str(SHARED)].source_pointer == "conversations/CS0001/session.yaml"


def test_the_token_estimate_matches_the_text_that_was_offered(
    graph_with_sessions: ResearchGraph,
) -> None:
    """C1 packs against these numbers, so they have to be the text's own."""
    fragments = graph_with_sessions.context_fragments(
        session=str(SHARED), query="CICIDS2017", references=[str(CLAIM)], visibility=LOCAL
    )

    assert all(fragment.tokens == estimate_tokens(fragment.text) for fragment in fragments)


def test_assembly_is_deterministic(graph_with_sessions: ResearchGraph) -> None:
    """The same request twice returns the same fragments in the same order."""
    request = {
        "session": str(SHARED),
        "query": "CICIDS2017 tokenization",
        "references": [str(CLAIM), str(SUPPORTING)],
        "visibility": LOCAL,
        "limit": 20,
    }
    first = graph_with_sessions.context_fragments(**request)  # type: ignore[arg-type]
    second = graph_with_sessions.context_fragments(**request)  # type: ignore[arg-type]

    assert first == second


# --- candidates and staleness -----------------------------------------------


def test_a_staged_candidate_is_labelled_and_never_files_as_accepted_state(
    graph_with_sessions: ResearchGraph,
) -> None:
    """ADR-003: a model's proposal keeps its label wherever it surfaces."""
    fragments = graph_with_sessions.context_fragments(
        session=None,
        query="CICIDS2017",
        references=[f"candidate:{CANDIDATE_ID}"],
        visibility=LOCAL,
        limit=50,
    )
    found = by_id(fragments)
    candidate = found[f"candidate:{CANDIDATE_ID}"]

    assert candidate.authority is GraphAuthority.CANDIDATE
    assert candidate.context_class == DISCOVERY


def test_a_candidate_never_outranks_the_accepted_object_it_proposes_about(
    graph_with_sessions: ResearchGraph,
) -> None:
    fragments = graph_with_sessions.context_fragments(
        session=None,
        query="CICIDS2017",
        references=[f"candidate:{CANDIDATE_ID}", str(CLAIM)],
        visibility=LOCAL,
        limit=50,
    )
    found = by_id(fragments)

    assert found[str(CLAIM)].score > found[f"candidate:{CANDIDATE_ID}"].score
    accepted = [item for item in fragments if item.authority is GraphAuthority.ACCEPTED]
    assert all(item.score > found[f"candidate:{CANDIDATE_ID}"].score for item in accepted[:2])


def test_a_model_proposed_relation_does_not_reach_the_accepted_relation_tier(
    graph_with_sessions: ResearchGraph,
) -> None:
    """The fixture stages a `supports` proposal on the claim; only accepted edges rank there."""
    fragments = graph_with_sessions.context_fragments(
        session=None, query="", references=[str(CLAIM)], visibility=LOCAL, limit=50
    )
    relation_tier = [item for item in fragments if len(item.relation_path) == 2]

    assert relation_tier
    assert all(item.authority is not GraphAuthority.CANDIDATE for item in relation_tier)


# --- budget and omissions ---------------------------------------------------


def test_the_limit_is_respected_and_what_it_cut_is_reported(
    graph_with_sessions: ResearchGraph,
) -> None:
    assembly = graph_with_sessions.context_assembly(
        session=str(SHARED), query="CICIDS2017", references=[str(CLAIM)], visibility=LOCAL, limit=3
    )

    assert len(assembly.fragments) == 3
    assert {item.reason for item in assembly.omitted} == {"low_relevance"}


def test_a_reference_that_resolves_to_nothing_is_reported_as_unresolved(
    graph_with_sessions: ResearchGraph,
) -> None:
    assembly = graph_with_sessions.context_assembly(
        session=None, query="", references=["@E9999"], visibility=LOCAL
    )

    assert [(item.id, item.reason) for item in assembly.omitted] == [
        ("@E9999", "unresolved_reference")
    ]


def test_a_request_against_a_missing_graph_returns_nothing_rather_than_raising(
    repo: WorkspaceRepository,
) -> None:
    """Graph spec §8: direct canonical reads stay possible while the index is absent."""
    unbuilt = ResearchGraph(repo)
    try:
        assert unbuilt.context_fragments(session=None, query="CICIDS2017") == ()
    finally:
        unbuilt.close()

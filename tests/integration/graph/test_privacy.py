"""A private session node cannot enter a project-visible request — graph spec §8, §11.5.

The property under test is stronger than "private rows are filtered out of the answer".
Filtering the *result* would still let a caller learn a private node exists by finding
something only reachable through it, and would let a two-hop walk step onto a private node
on the way to an allowed one. So the assertions below are about the walk:

* a private session, message, and attachment are unreachable at one hop and at two;
* they are unreachable *through* an allowed public neighbour — the exact bypass §8 names;
* `neighbors`, `search`, and `context_fragments` all honour the same allow-list;
* and the transcript is still readable directly, because refusing a projection request is
  not the same as losing the data (§8, last bullet).

`E0482` is the hinge: the private session's message mentions it, and it is accepted,
project-visible state that a project-visible pack legitimately contains. Any path that
walks from `E0482` back to `M0003` is the leak.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from research_harness.domain.graph import (
    EdgeKind,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.graph.queries import Direction, GraphFilter
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import SUPPORTING
from tests.integration.graph.test_sessions_rebuild import (
    PRIVATE,
    PRIVATE_NOTE,
    PRIVATE_TEXT,
    add_sessions,
)

PROJECT_ONLY: tuple[GraphVisibility, ...] = (GraphVisibility.PROJECT,)
PRIVATE_NODES = frozenset({str(PRIVATE), str(PRIVATE_NOTE)})


@pytest.fixture
def private_repo(repo: WorkspaceRepository) -> WorkspaceRepository:
    """The canonical fixture plus one shared and one private session."""
    add_sessions(repo)
    return repo


@pytest.fixture
def private_graph(private_repo: WorkspaceRepository) -> Iterator[ResearchGraph]:
    built = ResearchGraph(private_repo)
    built.rebuild()
    yield built
    built.close()


# --- the projection labels it -----------------------------------------------


def test_a_private_session_and_its_message_project_as_private(
    private_graph: ResearchGraph,
) -> None:
    for identity in PRIVATE_NODES:
        node = private_graph.resolve(identity)

        assert node is not None, identity
        assert node.visibility is GraphVisibility.PRIVATE, identity
        assert node.authority is GraphAuthority.PRIVATE, identity


def test_the_private_message_really_does_touch_accepted_project_visible_state(
    private_graph: ResearchGraph,
) -> None:
    """Without this edge the rest of the module would be proving nothing."""
    found = private_graph.neighbors(
        str(PRIVATE_NOTE), hops=1, direction=Direction.OUT, edge_kinds=(EdgeKind.MENTIONED_IN,)
    )

    assert [item.node.identity for item in found] == [str(SUPPORTING)]
    evidence = private_graph.resolve(str(SUPPORTING))
    assert evidence is not None and evidence.visibility is GraphVisibility.PROJECT


# --- traversal cannot reach it ----------------------------------------------


@pytest.mark.parametrize("hops", [1, 2])
def test_a_project_visible_walk_from_the_private_session_reaches_nothing_private(
    private_graph: ResearchGraph, hops: int
) -> None:
    found = private_graph.neighbors(str(PRIVATE), hops=hops, visibility=PROJECT_ONLY, limit=0)

    assert not [item for item in found if item.node.visibility is GraphVisibility.PRIVATE]


def test_a_two_hop_walk_cannot_route_around_the_restriction_through_a_public_neighbour(
    private_graph: ResearchGraph,
) -> None:
    """The bypass graph spec §8 forbids, stated as a test.

    `E0482` is public and one hop from the private message, so an unfiltered two-hop walk
    from the project node reaches `M0003`. With the filter, the walk must not: the private
    node is marked visited and never expanded, so nothing behind it is reachable either.
    """
    unfiltered = private_graph.neighbors(str(SUPPORTING), hops=1, limit=0)
    assert str(PRIVATE_NOTE) in {item.node.identity for item in unfiltered}, (
        "the fixture no longer has a public node adjacent to the private message"
    )

    filtered = private_graph.neighbors(str(SUPPORTING), hops=2, visibility=PROJECT_ONLY, limit=0)

    reached = {item.node.identity for item in filtered}
    assert not reached & PRIVATE_NODES
    assert str(PRIVATE) not in reached, "the private session was reached through its message"


def test_a_structured_query_for_project_material_returns_no_private_node(
    private_graph: ResearchGraph,
) -> None:
    nodes = private_graph.query(
        GraphFilter(
            kinds=(NodeKind.SESSION, NodeKind.MESSAGE, NodeKind.ATTACHMENT),
            visibility=PROJECT_ONLY,
            limit=100,
        )
    )

    assert nodes
    assert not {node.identity for node in nodes} & PRIVATE_NODES


def test_search_for_the_private_text_finds_nothing_under_a_project_filter(
    private_graph: ResearchGraph,
) -> None:
    """The words are indexed — they have to be, for the researcher's own search."""
    local = private_graph.search("leaks flows")
    filtered = private_graph.search(
        "leaks flows", filters=GraphFilter(visibility=PROJECT_ONLY, limit=20)
    )

    assert str(PRIVATE_NOTE) in {hit.node.identity for hit in local}
    assert not {hit.node.identity for hit in filtered} & PRIVATE_NODES


def test_a_neighbourhood_search_cannot_reach_a_private_node_through_a_public_one(
    private_graph: ResearchGraph,
) -> None:
    """The neighbourhood a search is constrained to is itself walked under the filter."""
    hits = private_graph.search(
        "leaks flows",
        neighbourhood=str(SUPPORTING),
        hops=2,
        filters=GraphFilter(visibility=PROJECT_ONLY, limit=20),
    )

    assert not {hit.node.identity for hit in hits} & PRIVATE_NODES


def test_a_provenance_path_will_not_step_onto_a_private_node(
    private_graph: ResearchGraph,
) -> None:
    path = private_graph.provenance(
        str(SUPPORTING), to_kind=NodeKind.MESSAGE, visibility=PROJECT_ONLY
    )

    assert path is None or not set(path.identities) & PRIVATE_NODES


def test_autocomplete_can_be_restricted_to_project_visible_objects(
    private_graph: ResearchGraph,
) -> None:
    """The researcher's own composer completes over everything; a host may ask for less."""
    everything = private_graph.autocomplete("CS", limit=10)
    project_only = private_graph.autocomplete("CS", visibility=PROJECT_ONLY, limit=10)

    assert str(PRIVATE) in {record.identity for record in everything}
    assert str(PRIVATE) not in {record.identity for record in project_only}


# --- context assembly honours the same allow-list ----------------------------


def test_a_project_visible_pack_contains_no_private_fragment(
    private_graph: ResearchGraph,
) -> None:
    fragments = private_graph.context_fragments(
        session=str(PRIVATE),
        query="CICIDS2017 leaks flows",
        references=[str(SUPPORTING), str(PRIVATE), str(PRIVATE_NOTE)],
        visibility=GraphVisibility.PROJECT.value,
        limit=50,
    )

    assert fragments, "the pack should still carry the accepted material it may carry"
    assert not {fragment.id for fragment in fragments} & PRIVATE_NODES
    assert all(fragment.visibility is GraphVisibility.PROJECT for fragment in fragments)


def test_no_private_text_appears_anywhere_in_a_project_visible_pack(
    private_graph: ResearchGraph,
) -> None:
    """Not just the id: the words themselves must not travel (workspace spec §7)."""
    fragments = private_graph.context_fragments(
        session=str(PRIVATE),
        query="leaks flows",
        references=[str(PRIVATE_NOTE)],
        visibility=GraphVisibility.PROJECT.value,
        limit=50,
    )

    assert PRIVATE_TEXT not in "\n".join(fragment.text for fragment in fragments)


def test_the_receipt_says_the_private_reference_was_refused_by_policy(
    private_graph: ResearchGraph,
) -> None:
    """The caller named it, so it is told why — the local receipt, never the pack."""
    assembly = private_graph.context_assembly(
        session=str(PRIVATE),
        query="leaks flows",
        references=[str(PRIVATE_NOTE)],
        visibility=GraphVisibility.PROJECT.value,
        limit=50,
    )

    reasons = {item.id: item.reason for item in assembly.omitted}
    assert reasons.get(str(PRIVATE_NOTE)) == "privacy_policy"
    assert reasons.get(str(PRIVATE)) == "privacy_policy"


def test_a_private_request_may_carry_the_same_session_locally(
    private_graph: ResearchGraph,
) -> None:
    """The restriction is about egress, not about the researcher's own machine."""
    fragments = private_graph.context_fragments(
        session=str(PRIVATE),
        query="leaks flows",
        references=[str(PRIVATE_NOTE)],
        visibility=GraphVisibility.PRIVATE.value,
        limit=50,
    )

    assert {fragment.id for fragment in fragments} >= PRIVATE_NODES


# --- the data is still there -------------------------------------------------


def test_the_private_transcript_is_still_readable_directly(
    private_repo: WorkspaceRepository,
) -> None:
    """Refusing to project material into a pack is not the same as losing it (§8)."""
    store = ConversationStore.for_repository(private_repo)
    messages = list(store.iter_messages(PRIVATE))

    assert [message.id for message in messages] == [PRIVATE_NOTE]
    assert PRIVATE_TEXT in messages[0].text()

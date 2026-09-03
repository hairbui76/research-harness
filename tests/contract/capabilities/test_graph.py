"""The `graph.*` capabilities: typed, read-only, label-carrying, and honest when unbuilt.

Three contracts a client depends on and cannot recover on its own:

* every one of the six is registered, `READ`, and callable by a host;
* every response names the `authority` and `visibility` of what it returns, so the Web can
  render a candidate differently from an accepted object without recomputing anything;
* a workspace with no index answers — emptily, and saying so — rather than raising, because
  `.research/` is disposable and a missing projection must not break a client.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.graph import (
    GRAPH_CAPABILITIES,
    AutocompleteRequest,
    GraphQueryRequest,
    GraphStatusRequest,
    NeighborsRequest,
    ProvenanceRequest,
    ResolveRequest,
    graph_autocomplete,
    graph_neighbors,
    graph_provenance,
    graph_query,
    graph_resolve,
    graph_status,
)
from research_harness.capabilities.permissions import InvalidRequest, Permission, Principal
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.graph import GraphAuthority, GraphVisibility, NodeKind
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import ARTIFACT, CLAIM, SUPPORTING, populated_workspace
from tests.integration.graph.test_sessions_rebuild import PRIVATE, SHARED, add_sessions


@pytest.fixture
def graph_repo(tmp_path: Path) -> WorkspaceRepository:
    """The graph fixture workspace with a shared and a private session."""
    repo = populated_workspace(tmp_path / "project")
    add_sessions(repo)
    return repo


@pytest.fixture
def graph_project(graph_repo: WorkspaceRepository) -> Iterator[CapabilityContext]:
    """That workspace, indexed, opened as the researcher."""
    built = ResearchGraph(graph_repo)
    built.rebuild()
    built.close()
    yield open_context(graph_repo.root, HUMAN_ACTOR)


@pytest.fixture
def unbuilt_project(tmp_path: Path) -> CapabilityContext:
    """A workspace whose graph has never been built."""
    repo = populated_workspace(tmp_path / "unbuilt")
    return open_context(repo.root, HUMAN_ACTOR)


# --- registration -----------------------------------------------------------


@pytest.mark.parametrize("name", GRAPH_CAPABILITIES)
def test_every_graph_capability_is_registered_as_a_read(name: str) -> None:
    spec = build_default_registry().get(name)

    assert spec.permission is Permission.READ
    assert not spec.human_only


@pytest.mark.parametrize("name", GRAPH_CAPABILITIES)
def test_an_agent_host_may_call_every_graph_capability(name: str) -> None:
    """Reads are host-readable: a host that cannot traverse cannot cite (Product 22)."""
    spec = build_default_registry().get(name)

    Principal.agent_host("mcp").authorize(name, spec.permission, human_only=spec.human_only)


@pytest.mark.parametrize("name", GRAPH_CAPABILITIES)
def test_every_graph_capability_publishes_both_schemas(name: str) -> None:
    descriptor = build_default_registry().get(name).descriptor()

    assert descriptor.request_schema["type"] == "object"
    assert descriptor.response_schema["type"] == "object"


def test_an_unknown_request_field_is_refused_rather_than_ignored() -> None:
    spec = build_default_registry().get("graph.neighbors")

    with pytest.raises(InvalidRequest, match=r"graph\.neighbors"):
        spec.validate_request({"id": "C0041", "hopz": 3})


# --- resolve ----------------------------------------------------------------


def test_resolve_answers_from_canonical_state_and_carries_both_labels(
    graph_project: CapabilityContext,
) -> None:
    view = graph_resolve(graph_project, ResolveRequest(reference="@C0041"))

    assert view.ok
    assert view.authority is GraphAuthority.ACCEPTED
    assert view.visibility is GraphVisibility.PROJECT
    assert view.link == "rh://claim/C0041"
    assert view.node is not None and view.node.id == str(CLAIM)


def test_resolve_validates_a_deep_link_against_the_stored_parse(
    graph_project: CapabilityContext,
) -> None:
    view = graph_resolve(
        graph_project, ResolveRequest(reference=f"rh://artifact/{ARTIFACT}?page=1&block=B9999")
    )

    assert not view.ok
    assert not view.fresh
    assert any("B9999" in problem for problem in view.problems)


def test_resolve_reaches_a_session_through_its_durable_record(
    graph_project: CapabilityContext,
) -> None:
    """`conversations/` is durable, so a session link resolves like any other target."""
    view = graph_resolve(graph_project, ResolveRequest(reference=f"rh://session/{SHARED}"))

    assert view.ok
    assert view.authority is GraphAuthority.PRIVATE
    assert view.visibility is GraphVisibility.PROJECT


def test_resolve_reports_a_private_session_as_private(
    graph_project: CapabilityContext,
) -> None:
    view = graph_resolve(graph_project, ResolveRequest(reference=f"rh://session/{PRIVATE}"))

    assert view.visibility is GraphVisibility.PRIVATE


def test_resolve_refuses_a_message_a_session_does_not_hold(
    graph_project: CapabilityContext,
) -> None:
    view = graph_resolve(
        graph_project, ResolveRequest(reference=f"rh://session/{SHARED}?message=M9999")
    )

    assert not view.ok
    assert any("M9999" in problem for problem in view.problems)


def test_resolve_answers_for_an_identity_that_has_no_link_grammar(
    graph_project: CapabilityContext,
) -> None:
    view = graph_resolve(graph_project, ResolveRequest(reference="block:A0017-3#B0081"))

    assert view.exists
    assert view.link is None
    assert view.node is not None and view.node.kind is NodeKind.PARAGRAPH


# --- the other five ---------------------------------------------------------


def test_autocomplete_returns_identity_matches_with_their_labels(
    graph_project: CapabilityContext,
) -> None:
    result = graph_autocomplete(graph_project, AutocompleteRequest(prefix="E04", limit=5))

    assert [match.id for match in result.matches] == ["E0482", "E0483"]
    assert all(match.authority for match in result.matches)


def test_autocomplete_can_exclude_private_objects(graph_project: CapabilityContext) -> None:
    everything = graph_autocomplete(graph_project, AutocompleteRequest(prefix="CS", limit=5))
    shared_only = graph_autocomplete(
        graph_project,
        AutocompleteRequest(prefix="CS", visibility=(GraphVisibility.PROJECT,), limit=5),
    )

    assert str(PRIVATE) in {match.id for match in everything.matches}
    assert str(PRIVATE) not in {match.id for match in shared_only.matches}


def test_neighbors_names_the_edge_that_reached_each_node(
    graph_project: CapabilityContext,
) -> None:
    view = graph_neighbors(graph_project, NeighborsRequest(id=str(CLAIM), hops=1, limit=50))

    assert view.origin is not None and view.origin.id == str(CLAIM)
    assert view.neighbours
    assert all(item.edge.from_id and item.edge.to_id for item in view.neighbours)
    assert all(item.hops == 1 for item in view.neighbours)


def test_neighbors_keeps_a_model_proposed_edge_visibly_candidate(
    graph_project: CapabilityContext,
) -> None:
    """Graph spec §11.3: the proposal is offered, and it is labelled a proposal."""
    view = graph_neighbors(graph_project, NeighborsRequest(id=str(CLAIM), hops=1, limit=50))
    candidates = [item for item in view.neighbours if item.edge.is_candidate]

    assert candidates
    assert all(item.edge.authority is GraphAuthority.CANDIDATE for item in candidates)


def test_neighbors_will_not_traverse_into_a_visibility_it_was_not_given(
    graph_project: CapabilityContext,
) -> None:
    view = graph_neighbors(
        graph_project,
        NeighborsRequest(
            id=str(SUPPORTING), hops=2, visibility=(GraphVisibility.PROJECT,), limit=100
        ),
    )

    assert all(item.node.visibility is GraphVisibility.PROJECT for item in view.neighbours)


def test_query_filters_by_kind_and_authority(graph_project: CapabilityContext) -> None:
    result = graph_query(
        graph_project,
        GraphQueryRequest(kinds=(NodeKind.EVIDENCE,), authorities=(GraphAuthority.ACCEPTED,)),
    )

    assert {node.id for node in result.nodes} == {str(SUPPORTING), "E0483"}


def test_provenance_traces_a_claim_to_the_artifact_anchor(
    graph_project: CapabilityContext,
) -> None:
    view = graph_provenance(graph_project, ProvenanceRequest(id=str(CLAIM)))

    assert view.found
    assert view.identities[0] == str(CLAIM)
    assert view.target is not None and view.target.kind is NodeKind.ARTIFACT
    assert view.anchor.get("block")


def test_status_reports_a_built_index(graph_project: CapabilityContext) -> None:
    view = graph_status(graph_project, GraphStatusRequest())

    assert view.available and view.exists
    assert view.nodes and view.edges and view.sources
    assert view.rebuilding is False


# --- degradation ------------------------------------------------------------


def test_status_says_so_when_the_index_has_never_been_built(
    unbuilt_project: CapabilityContext,
) -> None:
    view = graph_status(unbuilt_project, GraphStatusRequest())

    assert not view.available
    assert not view.exists
    assert (view.nodes, view.edges) == (0, 0)


def test_the_reads_answer_emptily_rather_than_raising_without_an_index(
    unbuilt_project: CapabilityContext,
) -> None:
    """A client that lost `.research/` still gets an answer it can act on (graph spec §8)."""
    assert graph_autocomplete(unbuilt_project, AutocompleteRequest(prefix="E")).matches == ()
    assert graph_neighbors(unbuilt_project, NeighborsRequest(id=str(CLAIM))).neighbours == ()
    assert graph_query(unbuilt_project, GraphQueryRequest()).nodes == ()
    assert not graph_provenance(unbuilt_project, ProvenanceRequest(id=str(CLAIM))).found


def test_resolve_still_answers_from_canonical_files_without_an_index(
    unbuilt_project: CapabilityContext,
) -> None:
    """The point of ADR-001: the canonical file decides, the index only speeds it up."""
    view = graph_resolve(unbuilt_project, ResolveRequest(reference=f"@{CLAIM}"))

    assert view.exists
    assert view.authority is GraphAuthority.ACCEPTED
    assert view.node is None

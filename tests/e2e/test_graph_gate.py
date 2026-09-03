"""Gate P20: rebuild the graph, resolve the same references, traverse, and stay private.

The gate has five clauses, and each is one section below, driven through the surfaces a
researcher and a host actually use — the `graph.*` capabilities and `research graph ...` —
rather than through the query layer directly:

1. rebuild the graph from durable sources and resolve the same stable references;
2. traverse Claim ↔ Evidence ↔ Artifact anchor, in both directions;
3. preserve candidate/accepted labels;
4. enforce session privacy during traversal;
5. meet the warm latency budgets (under 100 ms exact, under 250 ms one/two-hop).

The corpus is the graph fixture plus a conversation history: one project-visible session
and one private session whose message references the same accepted Evidence a
project-visible pack legitimately carries. That overlap is what makes clause 4 a real
question rather than a tautology.

Clause 5 is measured on this small workspace, so it is not the benchmark — the personal-scale
numbers live in `docs/plans/performance-budgets.md` and `tests/perf/test_graph_budgets.py`.
What it asserts here is that the gate's own workspace meets the gate's own budget, warm,
with no fixture large enough to hide a linear scan.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.graph import (
    GraphStatusRequest,
    NeighborsRequest,
    ProvenanceRequest,
    ResolveRequest,
    graph_neighbors,
    graph_provenance,
    graph_resolve,
    graph_status,
)
from research_harness.cli.commands.graph import register
from research_harness.domain.graph import (
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.graph.bench import (
    AUTOCOMPLETE_BUDGET_MS,
    EXACT_REFERENCE_BUDGET_MS,
    NEIGHBOURHOOD_BUDGET_MS,
    measure_graph_latency,
)
from research_harness.graph.queries import Direction, GraphFilter
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import (
    ARTIFACT,
    CLAIM,
    CONTRADICTING,
    SUPPORTING,
    populated_workspace,
)
from tests.integration.graph.test_sessions_rebuild import (
    PRIVATE,
    PRIVATE_NOTE,
    PRIVATE_TEXT,
    SHARED,
    SHARED_ATTACHMENT,
    SHARED_QUESTION,
    add_sessions,
)

#: Every reference the gate resolves before and after `rm -rf .research/`.
GATE_REFERENCES: tuple[str, ...] = (
    f"@{CLAIM}",
    f"@{SUPPORTING}",
    f"@{CONTRADICTING}",
    f"@{ARTIFACT}",
    f"@{SHARED}",
    f"@{SHARED_QUESTION}",
    f"@{SHARED_ATTACHMENT}",
    f"@{PRIVATE}",
    f"@{PRIVATE_NOTE}",
)

PROJECT_ONLY: tuple[GraphVisibility, ...] = (GraphVisibility.PROJECT,)


@pytest.fixture
def gate_workspace(tmp_path: Path) -> Path:
    """The full fixture: canonical objects, a manuscript, staged proposals, two sessions."""
    repo = populated_workspace(tmp_path / "project")
    add_sessions(repo)
    return repo.root


@pytest.fixture
def gate_repo(gate_workspace: Path) -> WorkspaceRepository:
    return WorkspaceRepository.open(gate_workspace, repair=True)


@pytest.fixture
def gate_graph(gate_repo: WorkspaceRepository) -> Iterator[ResearchGraph]:
    built = ResearchGraph(gate_repo)
    built.rebuild()
    yield built
    built.close()


@pytest.fixture
def gate_project(gate_graph: ResearchGraph) -> CapabilityContext:
    """The workspace opened as the researcher, with the index already built."""
    return open_context(gate_graph.repo.root, HUMAN_ACTOR)


@pytest.fixture
def cli() -> typer.Typer:
    app = typer.Typer()
    register(app)
    return app


def run(app: typer.Typer, *args: str) -> Result:
    """`research graph <command> ...`, driven in process."""
    result = CliRunner().invoke(app, ["graph", *args])
    assert result.exit_code == 0, result.output
    return result


def payload(result: Result) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(result.output)
    return body


# --- 1. rebuild from durable sources, resolve the same references ------------


def test_rebuilding_from_durable_sources_resolves_every_stable_reference(
    gate_repo: WorkspaceRepository, gate_graph: ResearchGraph, tmp_path: Path
) -> None:
    """Gate P20 clause 1, Product §42 O: identity lives in the files, not in the index."""
    before = {name: gate_graph.resolve(name) for name in GATE_REFERENCES}
    assert all(node is not None for node in before.values()), before
    gate_graph.close()

    staging = tmp_path / "staging-backup"
    research = gate_repo.layout.research_dir
    shutil.copytree(research / "staging", staging)
    shutil.rmtree(research)
    research.mkdir(parents=True)
    shutil.copytree(staging, research / "staging")
    assert not (research / "graph").exists()

    rebuilt = ResearchGraph(gate_repo)
    try:
        report = rebuilt.rebuild()
        after = {name: rebuilt.resolve(name) for name in GATE_REFERENCES}

        assert report.nodes and report.edges
        assert after == before
    finally:
        rebuilt.close()


def test_the_transcript_and_the_corpus_outlive_the_projection(
    gate_repo: WorkspaceRepository, gate_graph: ResearchGraph
) -> None:
    """Deleting `.research/` may cost speed and never a durable or canonical object."""
    gate_graph.close()
    shutil.rmtree(gate_repo.layout.research_dir)
    store = ConversationStore.for_repository(gate_repo)

    assert [message.id for message in store.iter_messages(PRIVATE)] == [PRIVATE_NOTE]
    assert gate_repo.get_claim(CLAIM).statement
    assert store.get_session(SHARED).message_count == 2


def test_the_status_capability_reports_the_rebuilt_index(
    gate_project: CapabilityContext,
) -> None:
    view = graph_status(gate_project, GraphStatusRequest())

    assert view.available and not view.rebuilding
    assert view.nodes and view.edges and view.sources


# --- 2. traverse Claim <-> Evidence <-> Artifact anchor ----------------------


def test_the_claim_reaches_its_supporting_and_contradicting_evidence(
    gate_project: CapabilityContext,
) -> None:
    view = graph_neighbors(
        gate_project,
        NeighborsRequest(
            id=str(CLAIM),
            hops=1,
            direction=Direction.IN,
            edge_kinds=(EdgeKind.SUPPORTS, EdgeKind.CONTRADICTS),
            limit=50,
        ),
    )
    accepted = {
        (item.edge.kind, item.node.id)
        for item in view.neighbours
        if item.edge.origin is EdgeOrigin.ACCEPTED
    }

    assert (EdgeKind.SUPPORTS, str(SUPPORTING)) in accepted
    assert (EdgeKind.CONTRADICTS, str(CONTRADICTING)) in accepted


def test_the_evidence_reaches_the_claim_in_the_other_direction(
    gate_project: CapabilityContext,
) -> None:
    """Graph spec §11.2 asks for both directions, because a reviewer reads both ways."""
    view = graph_neighbors(
        gate_project,
        NeighborsRequest(
            id=str(SUPPORTING),
            hops=1,
            direction=Direction.OUT,
            edge_kinds=(EdgeKind.SUPPORTS,),
            limit=50,
        ),
    )

    assert str(CLAIM) in {item.node.id for item in view.neighbours}


def test_the_evidence_reaches_the_exact_artifact_anchor(
    gate_project: CapabilityContext,
) -> None:
    view = graph_neighbors(
        gate_project,
        NeighborsRequest(
            id=str(SUPPORTING),
            hops=1,
            direction=Direction.OUT,
            edge_kinds=(EdgeKind.ANCHORED_AT,),
            limit=50,
        ),
    )
    reached = {item.node.id: item.edge for item in view.neighbours}

    assert str(ARTIFACT) in reached
    assert reached[str(ARTIFACT)].metadata["block"] == "B0081"
    assert reached[str(ARTIFACT)].metadata["page"]


def test_provenance_walks_the_whole_claim_to_anchor_path_in_one_call(
    gate_project: CapabilityContext, cli: typer.Typer, gate_workspace: Path
) -> None:
    view = graph_provenance(gate_project, ProvenanceRequest(id=str(CLAIM)))
    printed = payload(
        run(cli, "provenance", str(CLAIM), "--workspace", str(gate_workspace), "--json")
    )

    assert view.found
    assert view.identities[0] == str(CLAIM)
    assert view.target is not None and view.target.kind is NodeKind.ARTIFACT
    assert view.anchor.get("block") == "B0081"
    assert printed["identities"] == list(view.identities)


# --- 3. candidate and accepted labels survive --------------------------------


def test_a_model_proposed_relation_stays_candidate_beside_the_accepted_one(
    gate_project: CapabilityContext,
) -> None:
    """Graph spec §11.3: the proposal is visible, and it is visibly a proposal."""
    view = graph_neighbors(
        gate_project, NeighborsRequest(id=str(CLAIM), hops=1, direction=Direction.IN, limit=100)
    )
    proposed = [item for item in view.neighbours if item.edge.origin is EdgeOrigin.MODEL_PROPOSED]

    assert proposed
    assert all(item.edge.authority is GraphAuthority.CANDIDATE for item in proposed)
    assert all(item.edge.is_candidate for item in proposed)


def test_a_staged_candidate_never_takes_an_evidence_identity(
    gate_graph: ResearchGraph,
) -> None:
    """A proposal keeps the `candidate:` namespace until a researcher accepts it."""
    candidates = gate_graph.query(GraphFilter(authorities=(GraphAuthority.CANDIDATE,), limit=50))

    assert candidates
    assert all(node.identity.startswith("candidate:") for node in candidates)


def test_a_transcript_is_never_labelled_accepted(gate_graph: ResearchGraph) -> None:
    """Chat is working context; the projection cannot promote it (Product 8.2)."""
    kinds = (NodeKind.SESSION, NodeKind.MESSAGE, NodeKind.ATTACHMENT)
    nodes = gate_graph.query(GraphFilter(kinds=kinds, limit=100))

    assert nodes
    assert {node.authority for node in nodes} == {GraphAuthority.PRIVATE}


# --- 4. session privacy during traversal -------------------------------------


def test_a_project_visible_traversal_cannot_reach_the_private_session(
    gate_project: CapabilityContext,
) -> None:
    """Gate P20 clause 4, graph spec §11.5: not even through the public Evidence it names."""
    unfiltered = graph_neighbors(
        gate_project, NeighborsRequest(id=str(SUPPORTING), hops=1, limit=100)
    )
    assert str(PRIVATE_NOTE) in {item.node.id for item in unfiltered.neighbours}

    filtered = graph_neighbors(
        gate_project,
        NeighborsRequest(id=str(SUPPORTING), hops=2, visibility=PROJECT_ONLY, limit=200),
    )
    reached = {item.node.id for item in filtered.neighbours}

    assert str(PRIVATE_NOTE) not in reached
    assert str(PRIVATE) not in reached


def test_a_project_visible_context_pack_carries_no_private_material(
    gate_graph: ResearchGraph,
) -> None:
    fragments = gate_graph.context_fragments(
        session=str(SHARED),
        query="CICIDS2017 leaks flows",
        references=[str(CLAIM), str(PRIVATE_NOTE)],
        visibility=GraphVisibility.PROJECT.value,
        limit=50,
    )

    assert fragments
    assert all(item.visibility is GraphVisibility.PROJECT for item in fragments)
    assert PRIVATE_TEXT not in "\n".join(item.text for item in fragments)


def test_the_researcher_still_sees_the_private_session_locally(
    gate_project: CapabilityContext, cli: typer.Typer, gate_workspace: Path
) -> None:
    """The restriction is egress, not access: the CLI on this machine shows it."""
    view = graph_resolve(gate_project, ResolveRequest(reference=f"@{PRIVATE}"))
    listed = payload(
        run(cli, "query", "--kind", "session", "--workspace", str(gate_workspace), "--json")
    )

    assert view.exists and view.visibility is GraphVisibility.PRIVATE
    assert str(PRIVATE) in {node["id"] for node in listed["nodes"]}


# --- 5. the latency budgets ---------------------------------------------------


def test_the_gate_workspace_meets_every_warm_latency_budget(
    gate_graph: ResearchGraph,
) -> None:
    """Gate P20 clause 5, warm: a discarded pass first, then the median of nine runs."""
    report = measure_graph_latency(gate_graph)
    over = [sample.summary() for sample in report.samples if not sample.within_budget]

    assert report.samples
    assert not over, "\n".join(over)


def test_the_budgets_measured_are_the_ones_the_spec_states() -> None:
    """A budget that drifted from graph spec §9 would make the clause above meaningless."""
    assert (EXACT_REFERENCE_BUDGET_MS, NEIGHBOURHOOD_BUDGET_MS) == (100.0, 250.0)
    assert AUTOCOMPLETE_BUDGET_MS <= 100.0


# --- the CLI answers the same way ---------------------------------------------


def test_the_cli_resolves_and_completes_the_same_references(
    cli: typer.Typer, gate_workspace: Path, gate_graph: ResearchGraph
) -> None:
    resolved = payload(
        run(cli, "resolve", f"@{CLAIM}", "--workspace", str(gate_workspace), "--json")
    )
    completed = payload(run(cli, "complete", "E04", "--workspace", str(gate_workspace), "--json"))
    status = payload(run(cli, "status", "--workspace", str(gate_workspace), "--json"))

    assert resolved["exists"] and resolved["authority"] == "accepted"
    assert [match["id"] for match in completed["matches"]] == [str(SUPPORTING), "E0483"]
    assert status["available"] is True

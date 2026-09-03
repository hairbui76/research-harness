"""Rebuilding the graph: deterministic, disposable, and never a source of authority.

Graph spec 11.1 and 11.3 live here: deleting `.research/` and rebuilding resolves the same
`@E####` to the same Evidence with identical accepted relations, and a model-proposed edge
stays a candidate no matter how many times the projection is rebuilt.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select

from research_harness.domain.graph import EdgeKind, EdgeOrigin, GraphAuthority, NodeKind
from research_harness.graph.projectors import (
    anchor_identity,
    block_identity,
    candidate_identity,
    citation_identity,
    manuscript_file_identity,
    project_identity,
)
from research_harness.graph.queries import GraphFilter
from research_harness.graph.schema import (
    EDGES,
    FINGERPRINTS,
    GRAPH_SCHEMA_VERSION,
    NODES,
    create_engine_for,
    graph_database_path,
)
from research_harness.graph.service import ResearchGraph
from research_harness.projection.rebuild import rebuild_workspace
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import (
    ARTIFACT,
    CANDIDATE_ID,
    CITATION_KEY,
    CLAIM,
    CONTRADICTING,
    MANUSCRIPT_FILE,
    MATRIX,
    PARAGRAPH,
    SENTENCE_FINGERPRINT,
    SUPPORTING,
    VERSION,
    WORK,
)


def _identities(graph: ResearchGraph, kind: NodeKind) -> set[str]:
    return {record.identity for record in graph.query(GraphFilter(kinds=(kind,), limit=500))}


# --- what a rebuild projects ------------------------------------------------


def test_rebuild_projects_every_namespace(graph: ResearchGraph) -> None:
    assert _identities(graph, NodeKind.PROJECT) == {project_identity("structured-traffic")}
    assert _identities(graph, NodeKind.WORK) == {str(WORK)}
    assert _identities(graph, NodeKind.VERSION) == {str(VERSION)}
    assert _identities(graph, NodeKind.ARTIFACT) == {str(ARTIFACT)}
    assert _identities(graph, NodeKind.PARAGRAPH) == {block_identity(str(ARTIFACT), "B0081")}
    assert _identities(graph, NodeKind.TABLE) == {block_identity(str(ARTIFACT), "B0082")}
    assert _identities(graph, NodeKind.REFERENCE) == {block_identity(str(ARTIFACT), "B0083")}
    assert _identities(graph, NodeKind.CLAIM) == {str(CLAIM)}
    assert _identities(graph, NodeKind.QUESTION) == {"RQ0003"}
    assert _identities(graph, NodeKind.DECISION) == {"D0027"}
    assert _identities(graph, NodeKind.SYNTHESIS) == {str(MATRIX)}
    assert _identities(graph, NodeKind.CITATION) == {citation_identity(CITATION_KEY)}
    assert _identities(graph, NodeKind.MANUSCRIPT_ANCHOR) == {
        anchor_identity(MANUSCRIPT_FILE, SENTENCE_FINGERPRINT)
    }
    assert manuscript_file_identity(MANUSCRIPT_FILE) in _identities(graph, NodeKind.MANUSCRIPT_FILE)
    assert _identities(graph, NodeKind.EVIDENCE) == {
        str(SUPPORTING),
        str(CONTRADICTING),
        candidate_identity(CANDIDATE_ID),
    }


def test_the_corpus_spine_is_version_of_and_artifact_of(graph: ResearchGraph) -> None:
    spine = {
        (neighbour.edge.from_id, neighbour.edge.kind, neighbour.edge.to_id)
        for identity in (str(VERSION), str(ARTIFACT))
        for neighbour in graph.neighbors(identity, hops=1)
    }

    assert (str(VERSION), EdgeKind.VERSION_OF, str(WORK)) in spine
    assert (str(ARTIFACT), EdgeKind.ARTIFACT_OF, str(VERSION)) in spine


def test_the_artifact_contains_its_blocks_and_cites_its_parsed_references(
    graph: ResearchGraph,
) -> None:
    out = graph.neighbors(str(ARTIFACT), hops=1, limit=0)
    contained = {n.edge.to_id for n in out if n.edge.kind is EdgeKind.CONTAINS}

    assert block_identity(str(ARTIFACT), "B0081") in contained
    assert [record.identity for record in graph.citations(str(ARTIFACT))] == [
        citation_identity(CITATION_KEY)
    ]


def test_a_rebuild_records_its_checkpoints(graph: ResearchGraph) -> None:
    status = graph.status()

    assert status.current
    assert status.schema_version == GRAPH_SCHEMA_VERSION
    assert status.canonical_digest is not None and status.canonical_digest.startswith("sha256:")
    assert status.event_cursor
    assert status.nodes and status.edges and status.sources


def test_every_source_key_is_a_durable_file_of_this_workspace(
    graph: ResearchGraph, repo: WorkspaceRepository
) -> None:
    engine = graph.engine
    assert engine is not None
    with engine.connect() as connection:
        sources = [
            str(value) for value in connection.execute(select(FINGERPRINTS.c.source_key)).scalars()
        ]

    assert sources
    for source in sources:
        assert (repo.layout.root / source).is_file(), source


# --- graph spec 11.1: delete `.research/` and rebuild ------------------------


def _preserve_staging(repo: WorkspaceRepository, tmp_path: Path) -> None:
    """Delete `.research/` the way a researcher would, keeping the staged proposals.

    Staging is regenerable too, so a bare `rm -rf .research/` would take the model's
    proposals with it; restoring them is what lets the comparison cover the candidate rows
    as well as the accepted ones.
    """
    staging = tmp_path / "staging-backup"
    research = repo.layout.research_dir
    shutil.copytree(research / "staging", staging)
    shutil.rmtree(research)
    research.mkdir(parents=True)
    shutil.copytree(staging, research / "staging")


def test_deleting_the_research_directory_and_rebuilding_reproduces_the_graph(
    repo: WorkspaceRepository, tmp_path: Path
) -> None:
    first = ResearchGraph(repo)
    first.rebuild()
    before = first.dump()
    resolved_before = first.resolve("@E0482")
    first.close()

    _preserve_staging(repo, tmp_path)
    second = ResearchGraph(repo)
    report = second.rebuild()
    after = second.dump()
    resolved_after = second.resolve("@E0482")
    second.close()

    assert report.nodes and report.edges
    assert after == before
    assert resolved_before is not None
    assert resolved_after == resolved_before


def test_accepted_relations_survive_deleting_even_the_staged_proposals(
    repo: WorkspaceRepository,
) -> None:
    first = ResearchGraph(repo)
    first.rebuild()
    accepted_before = _accepted_edges(first)
    first.close()

    shutil.rmtree(repo.layout.research_dir)
    second = ResearchGraph(repo)
    second.rebuild()
    accepted_after = _accepted_edges(second)
    candidates = [
        neighbour
        for neighbour in second.neighbors(str(CLAIM), hops=1, limit=0)
        if neighbour.edge.origin is EdgeOrigin.MODEL_PROPOSED
    ]
    second.close()

    assert accepted_after == accepted_before
    assert accepted_before
    assert candidates == [], "candidate edges come from staging, which was deleted"


def _accepted_edges(graph: ResearchGraph) -> set[tuple[str, str, str]]:
    engine = graph.engine
    assert engine is not None
    with engine.connect() as connection:
        rows = connection.execute(
            select(EDGES.c.from_id, EDGES.c.kind, EDGES.c.to_id).where(
                EDGES.c.origin == EdgeOrigin.ACCEPTED.value
            )
        )
        return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}


def test_two_rebuilds_of_an_unchanged_workspace_are_identical(repo: WorkspaceRepository) -> None:
    graph = ResearchGraph(repo)
    graph.rebuild()
    first = graph.dump(include_sources=True)
    graph.rebuild()
    second = graph.dump(include_sources=True)
    graph.close()

    assert second == first


# --- graph spec 11.3: candidates stay candidates -----------------------------


def test_a_staged_relation_proposal_is_a_candidate_model_proposed_edge(
    graph: ResearchGraph,
) -> None:
    proposals = [
        neighbour
        for neighbour in graph.neighbors(str(CLAIM), hops=1, limit=0)
        if neighbour.edge.origin is EdgeOrigin.MODEL_PROPOSED
    ]

    assert len(proposals) == 1
    edge = proposals[0].edge
    assert (edge.from_id, edge.kind, edge.to_id) == (
        str(CONTRADICTING),
        EdgeKind.SUPPORTS,
        str(CLAIM),
    )
    assert edge.authority is GraphAuthority.CANDIDATE
    assert edge.is_candidate


def test_the_accepted_relation_and_the_proposal_coexist_without_one_hiding_the_other(
    graph: ResearchGraph,
) -> None:
    """Both edges run E0483 -> C0041; only their kind and origin differ."""
    edges = {
        (n.edge.kind, n.edge.origin, n.edge.authority)
        for n in graph.neighbors(str(CLAIM), hops=1, limit=0)
        if n.node.identity == str(CONTRADICTING)
    }

    assert edges == {
        (EdgeKind.CONTRADICTS, EdgeOrigin.ACCEPTED, GraphAuthority.ACCEPTED),
        (EdgeKind.SUPPORTS, EdgeOrigin.MODEL_PROPOSED, GraphAuthority.CANDIDATE),
        (EdgeKind.DEPENDS_ON, EdgeOrigin.STRUCTURAL, GraphAuthority.ACCEPTED),
    }


def test_no_projected_edge_is_model_proposed_and_accepted(graph: ResearchGraph) -> None:
    engine = graph.engine
    assert engine is not None
    with engine.connect() as connection:
        offending = connection.execute(
            select(EDGES).where(
                EDGES.c.origin == EdgeOrigin.MODEL_PROPOSED.value,
                EDGES.c.authority == GraphAuthority.ACCEPTED.value,
            )
        ).all()

    assert offending == []


def test_the_staged_evidence_candidate_never_becomes_an_evidence_id(
    graph: ResearchGraph,
) -> None:
    node = graph.resolve(candidate_identity(CANDIDATE_ID))

    assert node is not None
    assert node.authority is GraphAuthority.CANDIDATE
    assert node.identity.startswith("candidate:")
    anchored = graph.neighbors(node.identity, hops=1, edge_kinds=(EdgeKind.ANCHORED_AT,), limit=0)
    assert {n.edge.origin for n in anchored} == {EdgeOrigin.MODEL_PROPOSED}
    assert {n.node.identity for n in anchored} == {
        str(ARTIFACT),
        block_identity(str(ARTIFACT), str(PARAGRAPH)),
    }


# --- the hook into the existing rebuild -------------------------------------


def test_research_rebuild_also_rebuilds_the_graph(repo: WorkspaceRepository) -> None:
    report = rebuild_workspace(repo)

    assert report.ok
    assert report.graph_nodes > 0
    assert report.graph_edges > 0
    assert "graph" in report.summary()
    assert graph_database_path(repo.layout.research_dir).is_file()


def test_the_graph_follows_an_explicit_research_dir(
    repo: WorkspaceRepository, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "index"

    report = rebuild_workspace(repo, research_dir=elsewhere)

    assert report.ok
    assert graph_database_path(elsewhere).is_file()


def test_an_unbuilt_graph_answers_emptily_instead_of_raising(
    repo: WorkspaceRepository,
) -> None:
    graph = ResearchGraph(repo, research_dir=repo.layout.root / "nowhere")

    assert graph.engine is None
    assert graph.resolve("@E0482") is None
    assert graph.neighbors(str(CLAIM)) == []
    assert graph.search("CICIDS2017") == []
    assert graph.dump() == ""
    assert not graph.status().exists


def test_the_projection_rebuild_survives_a_graph_that_cannot_be_written(
    repo: WorkspaceRepository, monkeypatch: object
) -> None:
    """The graph is a navigation index; losing it must not fail a clean projection."""
    import research_harness.graph.rebuild as graph_rebuild

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(graph_rebuild, "rebuild_graph", _boom)
    report = rebuild_workspace(repo)

    assert report.ok
    assert (report.graph_nodes, report.graph_edges) == (0, 0)


def test_node_rows_carry_the_source_file_they_were_projected_from(
    graph: ResearchGraph,
) -> None:
    engine = graph.engine
    assert engine is not None
    with engine.connect() as connection:
        row = (
            connection.execute(select(NODES).where(NODES.c.identity == str(SUPPORTING)))
            .mappings()
            .one()
        )

    assert row["source"] == "corpus/works/W0017/evidence.jsonl"
    assert row["source_key"] == "corpus/works/W0017/evidence.jsonl"
    assert row["fingerprint"]


def test_a_graph_engine_can_be_reopened_from_the_database_alone(
    repo: WorkspaceRepository, graph: ResearchGraph
) -> None:
    graph.close()
    engine = create_engine_for(graph_database_path(repo.layout.research_dir))
    try:
        with engine.connect() as connection:
            count = connection.execute(select(NODES.c.identity)).scalars().all()
    finally:
        engine.dispose()

    assert str(SUPPORTING) in {str(value) for value in count}

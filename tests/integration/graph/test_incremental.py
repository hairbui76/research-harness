"""Incremental updates: replace only what changed, and leave no obsolete adjacency.

Graph spec 11.6. The strongest available oracle is a full rebuild, so almost every test
here ends by comparing the updated database with one built from scratch: if an update ever
leaves a row a rebuild would not write, the dumps differ.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select

from research_harness.domain import ClaimEvidenceRelation, ClaimEvidenceRelationType
from research_harness.domain.enums import ResearchEventType
from research_harness.domain.graph import EdgeKind, EdgeOrigin, NodeKind
from research_harness.domain.research import ResearchEvent
from research_harness.graph.projectors import citation_identity, manuscript_file_identity
from research_harness.graph.rebuild import dump_graph, rebuild_graph, update_graph
from research_harness.graph.schema import EDGES, create_engine_for, graph_database_path
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import (
    BIB_FILE,
    CITATION_KEY,
    CLAIM,
    CONTRADICTING,
    MANUSCRIPT_FILE,
    SUPPORTING,
    T5,
    stage_relation_proposal,
)


def _fresh_dump(repo: WorkspaceRepository, tmp_path: Path) -> str:
    """A full rebuild of the same workspace, built somewhere else so it cannot interfere.

    The staged proposals are copied across because a projection's research directory is
    also where staging lives; without them the oracle would simply have fewer candidates.
    """
    elsewhere = tmp_path / "oracle"
    if elsewhere.exists():
        shutil.rmtree(elsewhere)
    elsewhere.mkdir(parents=True)
    staging = repo.layout.research_dir / "staging"
    if staging.is_dir():
        shutil.copytree(staging, elsewhere / "staging")
    rebuild_graph(repo, research_dir=elsewhere)
    engine = create_engine_for(graph_database_path(elsewhere))
    try:
        return dump_graph(engine)
    finally:
        engine.dispose()


def _event(summary: str) -> ResearchEvent:
    return ResearchEvent(
        event=ResearchEventType.CLAIM_RELATION_CHANGED,
        actor="human:alice",
        summary=summary,
        occurred_at=T5,
    )


# --- the no-op ---------------------------------------------------------------


def test_an_update_with_nothing_changed_does_no_work(
    repo: WorkspaceRepository, graph: ResearchGraph
) -> None:
    before = graph.dump()

    report = graph.update()

    assert report.incremental
    assert report.changed_sources == ()
    assert report.removed_sources == ()
    assert graph.dump() == before


def test_an_update_with_no_database_falls_back_to_a_full_rebuild(
    repo: WorkspaceRepository,
) -> None:
    graph = ResearchGraph(repo)
    report = graph.update()
    graph.close()

    assert not report.incremental
    assert report.nodes


# --- a changed canonical file ------------------------------------------------


def test_a_changed_claim_reprojects_only_its_own_source(
    repo: WorkspaceRepository, graph: ResearchGraph, tmp_path: Path
) -> None:
    claim = repo.get_claim(CLAIM)
    with repo.transaction(_event("drop the contradicting relation")) as tx:
        tx.put(
            claim.model_copy(
                update={
                    "relations": (
                        ClaimEvidenceRelation(
                            evidence=SUPPORTING, relation=ClaimEvidenceRelationType.SUPPORTS
                        ),
                    )
                }
            )
        )

    report = graph.update()

    assert report.incremental
    assert report.changed_sources == ("claims/C0041.yaml",)
    assert graph.dump() == _fresh_dump(repo, tmp_path)


def test_the_obsolete_edge_of_a_changed_claim_is_gone(
    repo: WorkspaceRepository, graph: ResearchGraph
) -> None:
    claim = repo.get_claim(CLAIM)
    with repo.transaction(_event("drop the contradicting relation")) as tx:
        tx.put(claim.model_copy(update={"relations": ()}))

    graph.update()

    accepted = [
        neighbour
        for neighbour in graph.neighbors(str(CLAIM), hops=1, limit=0)
        if neighbour.edge.origin is EdgeOrigin.ACCEPTED
        and neighbour.edge.kind in {EdgeKind.SUPPORTS, EdgeKind.CONTRADICTS}
    ]

    assert accepted == []


def test_a_new_relation_appears_after_an_update(
    repo: WorkspaceRepository, graph: ResearchGraph, tmp_path: Path
) -> None:
    claim = repo.get_claim(CLAIM)
    with repo.transaction(_event("qualify with E0483")) as tx:
        tx.put(
            claim.model_copy(
                update={
                    "relations": (
                        *claim.relations,
                        ClaimEvidenceRelation(
                            evidence=CONTRADICTING,
                            relation=ClaimEvidenceRelationType.QUALIFIES,
                            aspect="tokenizer granularity",
                        ),
                    )
                }
            )
        )

    graph.update()

    qualifying = graph.neighbors(str(CLAIM), hops=1, edge_kinds=(EdgeKind.QUALIFIES,), limit=0)

    assert {n.node.identity for n in qualifying} == {str(CONTRADICTING)}
    assert graph.dump() == _fresh_dump(repo, tmp_path)


# --- a changed manuscript source --------------------------------------------


def test_a_changed_bibliography_reprojects_its_citation_nodes(
    repo: WorkspaceRepository, graph: ResearchGraph, tmp_path: Path
) -> None:
    (repo.layout.root / BIB_FILE).write_text(
        "@article{jones2025,\n  title = {Another system},\n  year = {2025}\n}\n",
        encoding="utf-8",
    )

    report = graph.update()

    assert BIB_FILE in report.changed_sources
    assert graph.resolve(citation_identity("jones2025")) is not None
    assert graph.dump() == _fresh_dump(repo, tmp_path)


def test_a_citation_named_by_two_sources_survives_one_of_them_changing(
    repo: WorkspaceRepository, graph: ResearchGraph, tmp_path: Path
) -> None:
    """`cite:smith2024` comes from the bibliography *and* from a parsed reference block.

    Deleting by source key would take it with the bibliography; the update restores what
    the unchanged parse still projects, so the artifact's `cites` edge keeps its endpoint.
    """
    (repo.layout.root / BIB_FILE).write_text("% no entries any more\n", encoding="utf-8")

    graph.update()

    assert graph.resolve(citation_identity(CITATION_KEY)) is not None
    assert graph.dump() == _fresh_dump(repo, tmp_path)


def test_a_removed_manuscript_file_removes_its_node(
    repo: WorkspaceRepository, graph: ResearchGraph, tmp_path: Path
) -> None:
    other = repo.layout.root / "manuscript" / "appendix.tex"
    other.write_text("\\section{Appendix}\n", encoding="utf-8")
    graph.update()
    assert graph.resolve(manuscript_file_identity("manuscript/appendix.tex")) is not None

    other.unlink()
    report = graph.update()

    assert "manuscript/appendix.tex" in report.removed_sources
    assert graph.resolve(manuscript_file_identity("manuscript/appendix.tex")) is None
    assert graph.dump() == _fresh_dump(repo, tmp_path)


# --- staged proposals --------------------------------------------------------


def test_removing_a_staged_proposal_removes_its_candidate_edge(
    repo: WorkspaceRepository, graph: ResearchGraph, tmp_path: Path
) -> None:
    report_path = stage_relation_proposal(repo)
    graph.update()
    assert _candidate_edges(graph)

    report_path.unlink()
    report = graph.update()

    assert report.removed_sources
    assert _candidate_edges(graph) == []
    assert graph.dump() == _fresh_dump(repo, tmp_path)


def _candidate_edges(graph: ResearchGraph, kind: EdgeKind = EdgeKind.SUPPORTS) -> list[str]:
    """Model-proposed edges of one kind; the staged anchors are proposals too."""
    engine = graph.engine
    assert engine is not None
    with engine.connect() as connection:
        rows = connection.execute(
            select(EDGES.c.from_id, EDGES.c.to_id).where(
                EDGES.c.origin == EdgeOrigin.MODEL_PROPOSED.value,
                EDGES.c.kind == kind.value,
            )
        )
        return [f"{row[0]}->{row[1]}" for row in rows]


# --- fingerprints and checkpoints -------------------------------------------


def test_an_update_advances_the_checkpoints(
    repo: WorkspaceRepository, graph: ResearchGraph
) -> None:
    before = graph.status()
    claim = repo.get_claim(CLAIM)
    with repo.transaction(_event("touch the claim")) as tx:
        tx.put(claim.model_copy(update={"statement": "A revised statement."}))

    graph.update()
    after = graph.status()

    assert after.built_at != before.built_at
    assert after.canonical_digest != before.canonical_digest
    assert after.event_cursor != before.event_cursor


def test_a_schema_version_mismatch_forces_a_full_rebuild(
    repo: WorkspaceRepository, graph: ResearchGraph
) -> None:
    engine = graph.engine
    assert engine is not None
    from sqlalchemy import update as sql_update

    from research_harness.graph.schema import CHECKPOINT_SCHEMA_VERSION, CHECKPOINTS

    with engine.begin() as connection:
        connection.execute(
            sql_update(CHECKPOINTS)
            .where(CHECKPOINTS.c.name == CHECKPOINT_SCHEMA_VERSION)
            .values(value="0")
        )
    graph.close()

    report = update_graph(repo)

    assert not report.incremental
    assert report.nodes


def test_an_update_and_a_rebuild_agree_after_several_changes(
    repo: WorkspaceRepository, graph: ResearchGraph, tmp_path: Path
) -> None:
    (repo.layout.root / MANUSCRIPT_FILE).write_text("\\documentclass{article}\n", encoding="utf-8")
    (repo.layout.root / BIB_FILE).write_text(
        "@book{other2020,\n  title = {A book}\n}\n", encoding="utf-8"
    )
    claim = repo.get_claim(CLAIM)
    with repo.transaction(_event("revise")) as tx:
        tx.put(claim.model_copy(update={"statement": "Revised again."}))

    report = graph.update()

    assert len(report.changed_sources) >= 3
    assert graph.dump() == _fresh_dump(repo, tmp_path)
    assert graph.resolve(str(CLAIM)) is not None


def test_nothing_the_update_writes_is_a_model_proposed_accepted_edge(
    repo: WorkspaceRepository, graph: ResearchGraph
) -> None:
    stage_relation_proposal(repo)
    graph.update()

    candidates = _candidate_edges(graph)
    engine = graph.engine
    assert engine is not None
    with engine.connect() as connection:
        offending = connection.execute(
            select(EDGES).where(
                EDGES.c.origin == EdgeOrigin.MODEL_PROPOSED.value,
                EDGES.c.authority == "accepted",
            )
        ).all()

    assert candidates
    assert offending == []


def test_the_node_kinds_survive_an_update(repo: WorkspaceRepository, graph: ResearchGraph) -> None:
    graph.update()
    engine = graph.engine
    assert engine is not None
    from research_harness.graph.schema import NODES

    with engine.connect() as connection:
        kinds = {str(value) for value in connection.execute(select(NODES.c.kind)).scalars()}

    assert NodeKind.CLAIM.value in kinds
    assert NodeKind.MANUSCRIPT_ANCHOR.value in kinds

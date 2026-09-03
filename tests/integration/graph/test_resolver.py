"""Deep links resolve against canonical files, not against a projected row."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.domain import (
    EvidenceContent,
    ManuscriptAnchor,
    ResearchEvent,
    ResearchEventType,
    StaleState,
)
from research_harness.domain.graph import DeepLink, GraphAuthority, GraphVisibility
from research_harness.graph.resolver import resolve_deep_link
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import (
    ARTIFACT,
    CLAIM,
    MANUSCRIPT_FILE,
    PARAGRAPH,
    SUPPORTING,
    T2,
    T5,
    WORK,
    _tracked,
)
from tests.unit.domain import strategies as sty


@pytest.mark.parametrize(
    "link",
    [
        "rh://work/W0017",
        "rh://version/V0017-2",
        "rh://artifact/A0017-3",
        "rh://artifact/A0017-3?page=8&block=B0081",
        "rh://evidence/E0482",
        "rh://claim/C0041",
        "rh://question/RQ0003",
        "rh://decision/D0027",
        "rh://manuscript/main.tex?line=41",
    ],
)
def test_a_link_to_a_real_object_resolves(graph: ResearchGraph, link: str) -> None:
    target = graph.resolve_deep_link(link)

    assert target.ok, target.summary()
    assert target.project == "structured-traffic"
    assert target.authority is GraphAuthority.ACCEPTED
    assert target.visibility is GraphVisibility.PROJECT


def test_the_resolved_node_comes_back_beside_the_canonical_verdict(
    graph: ResearchGraph,
) -> None:
    target = graph.resolve_deep_link(f"rh://evidence/{SUPPORTING}")

    assert target.node is not None
    assert target.node.identity == str(SUPPORTING)
    assert target.node.metadata["block"] == str(PARAGRAPH)


@pytest.mark.parametrize(
    "link",
    [
        "rh://work/W9999",
        "rh://evidence/E9999",
        "rh://claim/C9999",
        "rh://artifact/A9999-1",
        "rh://manuscript/missing.tex",
    ],
)
def test_a_link_to_something_this_project_does_not_hold_is_refused(
    graph: ResearchGraph, link: str
) -> None:
    target = graph.resolve_deep_link(link)

    assert not target.ok
    assert not target.exists
    assert target.problems


def test_a_block_that_is_not_in_the_stored_parse_is_not_fresh(graph: ResearchGraph) -> None:
    target = graph.resolve_deep_link(f"rh://artifact/{ARTIFACT}?block=B9999")

    assert target.exists
    assert not target.fresh
    assert "not in the stored parse" in target.problems[0]


def test_a_page_that_disagrees_with_the_stored_parse_is_not_fresh(
    graph: ResearchGraph,
) -> None:
    target = graph.resolve_deep_link(f"rh://artifact/{ARTIFACT}?page=3&block={PARAGRAPH}")

    assert not target.ok
    assert "page 8, not page 3" in target.problems[0]


def test_a_manuscript_line_past_the_end_of_the_file_is_not_fresh(
    graph: ResearchGraph,
) -> None:
    target = graph.resolve_deep_link("rh://manuscript/main.tex?line=9999")

    assert target.exists
    assert not target.fresh
    assert "past the end" in target.problems[0]


def test_a_manuscript_link_may_name_the_path_with_or_without_the_directory(
    graph: ResearchGraph,
) -> None:
    with_directory = graph.resolve_deep_link(f"rh://manuscript/{MANUSCRIPT_FILE}")
    without = graph.resolve_deep_link("rh://manuscript/main.tex")

    assert with_directory.ok
    assert without.ok


def test_session_and_attachment_links_say_they_are_not_this_projection_s_to_answer(
    graph: ResearchGraph,
) -> None:
    for link in ("rh://session/CS0001?message=M0042", "rh://attachment/SA0003"):
        target = graph.resolve_deep_link(link)

        assert not target.ok
        assert target.visibility is GraphVisibility.PRIVATE
        assert "conversation store" in target.problems[0]


def test_an_evidence_anchor_whose_text_moved_is_reported_stale(
    repo: WorkspaceRepository, graph: ResearchGraph
) -> None:
    """A re-parse that changed the block's text invalidates the anchor (ADR-011, 22)."""
    moved = sty.make_block(
        id=PARAGRAPH,
        text="A completely different paragraph.",
        text_hash="sha256:" + "d" * 64,
        **_tracked(T5),
    )
    document = repo.get_parsed_document(ARTIFACT, work=WORK)
    assert document is not None
    reparsed = document.model_copy(update={"blocks": (moved, *document.blocks[1:])})
    with repo.transaction(
        ResearchEvent(
            event=ResearchEventType.WORK_PARSED,
            actor="system",
            summary="re-parse A0017-3",
            occurred_at=T5,
        )
    ) as tx:
        tx.put(reparsed)

    target = resolve_deep_link(repo, DeepLink.parse(f"rh://evidence/{SUPPORTING}"))

    assert target.exists
    assert not target.fresh
    assert any("no longer holds the text" in problem for problem in target.problems)


def test_stale_evidence_resolves_but_says_so(repo: WorkspaceRepository) -> None:
    stale = sty.make_evidence(
        id=SUPPORTING,
        source=sty.make_anchor(file_hash=repo.get_artifact(ARTIFACT, work=WORK).file_hash),
        content=EvidenceContent(exact_text="We evaluate on CICIDS2017."),
        stale=StaleState.STALE,
        **_tracked(T2),
    )
    with repo.transaction(
        ResearchEvent(
            event=ResearchEventType.EVIDENCE_STALE,
            actor="system",
            summary="mark E0482 stale",
            occurred_at=T5,
        )
    ) as tx:
        tx.append_evidence(stale)

    target = resolve_deep_link(repo, DeepLink.parse(f"rh://evidence/{SUPPORTING}"))

    assert target.exists
    assert target.authority is GraphAuthority.STALE
    assert not target.fresh


def test_an_anchor_whose_manuscript_file_is_gone_is_refused(
    repo: WorkspaceRepository, tmp_path: Path
) -> None:
    (repo.layout.root / MANUSCRIPT_FILE).unlink()

    target = resolve_deep_link(repo, DeepLink.parse("rh://manuscript/main.tex"))

    assert not target.exists
    assert tmp_path.is_dir()


def test_the_resolver_works_without_a_graph_at_all(repo: WorkspaceRepository) -> None:
    """Graph spec 8: direct canonical reads stay possible while the index is unavailable."""
    target = resolve_deep_link(repo, "rh://claim/C0041")

    assert target.ok
    assert target.node is None
    assert str(CLAIM) in target.link.format()


def test_a_stale_claim_resolves_as_stale(repo: WorkspaceRepository) -> None:
    claim = repo.get_claim(CLAIM)
    with repo.transaction(
        ResearchEvent(
            event=ResearchEventType.OBJECTS_MARKED_STALE,
            actor="system",
            summary="mark C0041 stale",
            occurred_at=T5,
        )
    ) as tx:
        tx.put(claim.model_copy(update={"stale": StaleState.STALE}))

    target = resolve_deep_link(repo, "rh://claim/C0041")

    assert target.authority is GraphAuthority.STALE
    assert not target.fresh


def test_an_anchor_object_is_not_addressed_by_a_deep_link_kind(
    repo: WorkspaceRepository,
) -> None:
    """Anchors are graph nodes, not link targets; a manuscript link plus a line is."""
    anchor = next(iter(repo.iter_anchors()))

    assert isinstance(anchor, ManuscriptAnchor)
    assert DeepLink.try_parse("rh://anchor/whatever") is None

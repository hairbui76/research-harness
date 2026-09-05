"""Gate P3: delete `.research/`, run a rebuild, and lose nothing that carries authority.

PRODUCT 8.2 and §42 C: `.research/` is machine state. Deleting the whole tree and
rebuilding must reproduce the same accepted Works, Evidence, Claims, Decisions, and
manuscript links, and must give back a working lexical index and the same stale set -
because a researcher who deletes a cache should not lose an answer.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from research_harness.cli.commands.rebuild import register
from research_harness.domain import ClaimId
from research_harness.projection import create_engine_for, load_stale_marks
from research_harness.projection.fts import FtsKind, search_fts
from research_harness.projection.rebuild import rebuild_workspace, verify_rebuild
from research_harness.workspace.events import digest_key, object_digest
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.projection.test_rebuild import (
    DATASET,
    populated_workspace,
    revise_the_decision,
    tree_digest,
)


def accepted_digests(repo: WorkspaceRepository) -> dict[str, str]:
    """Every accepted object's canonical digest, keyed the way the event log keys it."""
    objects = [
        *repo.list_works(),
        *repo.list_claims(),
        *repo.list_decisions(),
        *repo.list_questions(),
        *repo.list_matrices(),
        *repo.list_search_runs(),
        *repo.list_taxonomies(),
        *repo.iter_notes(),
        *repo.iter_anchors(),
    ]
    for work in repo.list_works():
        objects.extend(repo.list_versions(work.id))
        objects.extend(repo.list_artifacts(work.id))
        objects.extend(repo.iter_evidence(work.id))
    return {digest_key(obj): object_digest(obj) for obj in objects}


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    built = populated_workspace(tmp_path / "project")
    revise_the_decision(built)  # so there is a real stale set to lose
    return built


def cli() -> typer.Typer:
    """The `research rebuild` command on a bare app, the way `cli/app.py` will mount it."""
    app = typer.Typer()

    @app.callback()
    def _root() -> None:
        """Test harness."""

    register(app)
    return app


def test_deleting_research_and_rebuilding_reproduces_the_accepted_state(
    repo: WorkspaceRepository,
) -> None:
    first = rebuild_workspace(repo)
    assert first.ok
    before_objects = accepted_digests(repo)
    before_tree = tree_digest(repo.root)
    engine = create_engine_for(repo.layout.database_file)
    try:
        with engine.connect() as connection:
            before_marks = set(load_stale_marks(connection))
        before_hits = [hit.object_id for hit in search_fts(engine, DATASET)]
    finally:
        engine.dispose()
    assert before_marks
    assert before_hits

    shutil.rmtree(repo.layout.research_dir)
    assert not repo.layout.research_dir.exists()

    reopened = WorkspaceRepository.open(repo.root)
    second = rebuild_workspace(reopened)

    assert second.ok
    assert accepted_digests(reopened) == before_objects
    assert second.canonical_digest == first.canonical_digest
    assert tree_digest(reopened.root) == before_tree
    assert second.objects_by_type == first.objects_by_type

    engine = create_engine_for(reopened.layout.database_file)
    try:
        assert verify_rebuild(reopened, engine) == []
        with engine.connect() as connection:
            assert set(load_stale_marks(connection)) == before_marks
        hits = search_fts(engine, DATASET)
        assert [hit.object_id for hit in hits] == before_hits
        assert any(hit.kind is FtsKind.BLOCK for hit in hits)
        assert all(DATASET in hit.snippet for hit in hits)
    finally:
        engine.dispose()


def test_exact_terminology_search_needs_no_embeddings_or_services(
    repo: WorkspaceRepository,
) -> None:
    shutil.rmtree(repo.layout.research_dir)
    report = rebuild_workspace(WorkspaceRepository.open(repo.root))

    assert report.fts_rows > 0
    engine = create_engine_for(repo.layout.database_file)
    try:
        blocks = search_fts(engine, DATASET, kinds=[FtsKind.BLOCK])
        evidence = search_fts(engine, f'"We evaluate on {DATASET}"', kinds=[FtsKind.EVIDENCE])
    finally:
        engine.dispose()

    assert [hit.object_id for hit in blocks] == ["B0081"]
    assert [hit.object_id for hit in evidence] == ["E0482"]


def test_a_rebuild_of_a_deleted_projection_still_answers_stale_dependency_queries(
    repo: WorkspaceRepository,
) -> None:
    shutil.rmtree(repo.layout.research_dir)
    rebuild_workspace(WorkspaceRepository.open(repo.root))

    engine = create_engine_for(repo.layout.database_file)
    try:
        with engine.connect() as connection:
            marks = load_stale_marks(connection)
    finally:
        engine.dispose()

    # PRODUCT 37: the revised decision reaches the claim and the manuscript sentence.
    assert "C0041" in marks.object_ids()
    assert any(object_id.startswith("MA:") for object_id in marks.object_ids())
    priorities = [mark.priority for mark in marks]
    assert priorities == sorted(priorities, reverse=True)


# --- the command a researcher actually runs ---------------------------------


def test_research_rebuild_prints_a_report_and_exits_zero(repo: WorkspaceRepository) -> None:
    result = CliRunner().invoke(cli(), ["rebuild", "--workspace", str(repo.root), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["objects_by_type"]["Claim"] == 1
    assert payload["canonical_digest"].startswith("sha256:")


def test_research_rebuild_exits_non_zero_on_an_invalid_canonical_file(
    repo: WorkspaceRepository,
) -> None:
    claim = repo.layout.claim_file(ClaimId("C0041"))
    claim.write_text(f"{claim.read_text(encoding='utf-8')}not_a_claim_field: 1\n", encoding="utf-8")

    result = CliRunner().invoke(cli(), ["rebuild", "--workspace", str(repo.root)])

    assert result.exit_code == 1
    assert "claims/C0041.yaml" in result.output.replace("\\", "/")
    assert not repo.layout.database_file.exists()

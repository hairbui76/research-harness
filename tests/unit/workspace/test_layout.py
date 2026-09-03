"""The canonical layout is exactly Product 8.1, and `.research/` is never committed."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.domain import (
    ArtifactId,
    ClaimId,
    DecisionId,
    QuestionId,
    ResearchNote,
    SearchRunId,
    SynthesisId,
    VersionId,
    WorkId,
)
from research_harness.domain.errors import WorkspaceError
from research_harness.workspace.layout import (
    CANONICAL_DIRECTORIES,
    RESEARCH_DIRECTORIES,
    RESEARCH_DIRNAME,
    WorkspaceLayout,
    artifact_extension,
    note_key,
)
from research_harness.workspace.repository import WorkspaceRepository
from tests.unit.domain.strategies import (
    HUMAN,
    make_artifact,
    make_block,
    make_claim,
    make_evidence,
    make_search_run,
    make_version,
    make_work,
)

EXPECTED_CANONICAL_FILES = {".gitignore", "research.yaml", "events/research.jsonl"}


def _relative_paths(root: Path, *, directories: bool) -> set[str]:
    return {
        str(path.relative_to(root).as_posix())
        for path in root.rglob("*")
        if path.is_dir() is directories
    }


def test_init_creates_exactly_the_product_8_1_tree(tmp_path: Path) -> None:
    WorkspaceRepository.init(tmp_path / "project", "demo")
    root = tmp_path / "project"

    directories = _relative_paths(root, directories=True)
    canonical = {name for name in directories if not name.startswith(RESEARCH_DIRNAME)}
    machine = {name for name in directories if name.startswith(RESEARCH_DIRNAME)}

    assert canonical == set(CANONICAL_DIRECTORIES)
    assert machine == set(RESEARCH_DIRECTORIES)

    files = _relative_paths(root, directories=False)
    assert {name for name in files if not name.startswith(RESEARCH_DIRNAME)} == (
        EXPECTED_CANONICAL_FILES
    )


def test_init_gitignores_the_regenerable_research_directory(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "project", "demo")
    gitignore = repo.layout.gitignore_file.read_text(encoding="utf-8")
    assert f"{RESEARCH_DIRNAME}/" in gitignore.splitlines()


def test_init_refuses_to_overwrite_an_existing_workspace(tmp_path: Path) -> None:
    WorkspaceRepository.init(tmp_path, "demo")
    with pytest.raises(WorkspaceError, match="already exists"):
        WorkspaceRepository.init(tmp_path, "demo again")


def test_paths_match_the_documented_layout(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    work = WorkId("W0001")

    assert layout.research_file == tmp_path / "research.yaml"
    assert layout.work_file(work) == tmp_path / "corpus/works/W0001/work.yaml"
    assert layout.version_file(work, VersionId("V0001-1")) == (
        tmp_path / "corpus/works/W0001/versions/V0001-1.yaml"
    )
    assert layout.artifact_file(work, ArtifactId("A0001-1")) == (
        tmp_path / "corpus/works/W0001/artifacts/A0001-1.yaml"
    )
    assert layout.evidence_file(work) == tmp_path / "corpus/works/W0001/evidence.jsonl"
    assert layout.blocks_file(work, ArtifactId("A0001-1")) == (
        tmp_path / "corpus/works/W0001/parsed/A0001-1.blocks.jsonl"
    )
    assert layout.claim_file(ClaimId("C0041")) == tmp_path / "claims/C0041.yaml"
    assert layout.question_file(QuestionId("RQ0003")) == tmp_path / "questions/RQ0003.yaml"
    assert layout.decision_file(DecisionId("D0027")) == tmp_path / "decisions/D0027.yaml"
    assert layout.matrix_file(SynthesisId("S0002")) == tmp_path / "matrices/S0002.yaml"
    assert layout.search_run_file(SearchRunId("SR0019")) == tmp_path / "searches/SR0019.yaml"
    assert layout.taxonomy_file("tokenization") == tmp_path / "taxonomy/tokenization.yaml"
    assert layout.note_file("note-20260101-120000-abcdef") == (
        tmp_path / "notes/note-20260101-120000-abcdef.yaml"
    )
    assert layout.events_file == tmp_path / "events/research.jsonl"
    assert layout.anchors_file == tmp_path / "manuscript/anchors.jsonl"
    assert layout.lock_file == tmp_path / ".research/lock"
    assert layout.journal_dir == tmp_path / ".research/journal"
    assert layout.database_file == tmp_path / ".research/research.db"


def test_artifact_bytes_sit_beside_their_metadata_with_the_original_suffix(
    tmp_path: Path,
) -> None:
    layout = WorkspaceLayout(tmp_path)
    artifact = make_artifact()
    assert artifact_extension(artifact) == ".pdf"
    assert layout.artifact_bytes_file(artifact) == (
        tmp_path / "corpus/works/W0017/artifacts/A0017-3.pdf"
    )
    assert layout.artifact_file(artifact.work, artifact.id).with_suffix(".pdf") == (
        layout.artifact_bytes_file(artifact)
    )


def test_artifact_extension_falls_back_when_the_filename_carries_none() -> None:
    assert artifact_extension(make_artifact(original_filename="paper")) == ".pdf"
    assert (
        artifact_extension(make_artifact(original_filename="paper", mime_type="x/unknown"))
        == ".bin"
    )


def test_path_for_dispatches_on_the_object_type(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)

    assert layout.path_for(make_work()) == layout.work_file(WorkId("W0017"))
    assert layout.path_for(make_version()) == layout.version_file(
        WorkId("W0017"), VersionId("V0017-2")
    )
    assert layout.path_for(make_artifact()) == layout.artifact_file(
        WorkId("W0017"), ArtifactId("A0017-3")
    )
    assert layout.path_for(make_evidence()) == layout.evidence_file(WorkId("W0017"))
    assert layout.path_for(make_block()) == layout.blocks_file(
        WorkId("W0017"), ArtifactId("A0017-3")
    )
    assert layout.path_for(make_claim()) == layout.claim_file(ClaimId("C0041"))
    assert layout.path_for(make_search_run()) == layout.search_run_file(SearchRunId("SR0019"))


def test_path_for_refuses_a_note_without_a_key(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    with pytest.raises(WorkspaceError, match="needs a key"):
        layout.path_for(ResearchNote(text="unsaved", provenance=HUMAN))


def test_path_for_refuses_an_object_with_no_canonical_home(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="no canonical path"):
        WorkspaceLayout(tmp_path).path_for(object())


def test_note_key_uses_the_capture_timestamp(tmp_path: Path) -> None:
    note = ResearchNote(text="captured", provenance=HUMAN)
    key = note_key(note.created_at, "abc123")
    assert key.startswith("note-")
    assert key.endswith("-abc123")
    assert WorkspaceLayout(tmp_path).note_file(key).name == f"{key}.yaml"


def test_id_from_path_inverts_path_for_where_a_file_carries_an_id(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    for obj, expected in (
        (make_work(), WorkId("W0017")),
        (make_version(), VersionId("V0017-2")),
        (make_artifact(), ArtifactId("A0017-3")),
        (make_claim(), ClaimId("C0041")),
        (make_search_run(), SearchRunId("SR0019")),
    ):
        assert layout.id_from_path(layout.path_for(obj)) == expected

    assert layout.id_from_path(layout.taxonomy_file("tokenization")) is None
    assert layout.id_from_path(layout.note_file("note-20260101-120000-abcdef")) is None
    assert layout.id_from_path(layout.events_file) is None
    assert layout.id_from_path(tmp_path / "claims/not-an-id.yaml") is None


def test_relative_refuses_paths_outside_the_workspace(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path / "project")
    assert str(layout.relative(tmp_path / "project/claims/C0001.yaml")) == "claims/C0001.yaml"
    with pytest.raises(WorkspaceError, match="outside the workspace"):
        layout.relative(tmp_path / "elsewhere/C0001.yaml")


def test_is_regenerable_separates_authority_from_machine_state(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    assert layout.is_regenerable(layout.database_file)
    assert layout.is_regenerable(layout.journal_dir / "tx.json")
    assert not layout.is_regenerable(layout.claim_file(ClaimId("C0001")))
    assert not layout.is_regenerable(layout.events_file)


def test_unsafe_taxonomy_and_note_names_are_refused(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    for name in ("../escape", "a/b", "", ".hidden"):
        with pytest.raises(WorkspaceError, match="unsafe"):
            layout.taxonomy_file(name)

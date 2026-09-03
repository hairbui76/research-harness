"""Listing, reading, and saving manuscript source without ever losing an outside edit."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from research_harness.manuscript.files import (
    FileSnapshot,
    ManuscriptBinaryFileError,
    ManuscriptConflictError,
    ManuscriptFileExistsError,
    ManuscriptFileKind,
    ManuscriptFileNotFoundError,
    ManuscriptFiles,
    ManuscriptPathError,
    content_hash,
)
from research_harness.workspace.layout import WorkspaceLayout

BODY = "\\section{Introduction}\nStructured traffic classifiers degrade under load.\n"


@pytest.fixture
def files(tmp_path: Path) -> ManuscriptFiles:
    """A workspace whose `manuscript/` holds a main file, an include, and a bibliography."""
    layout = WorkspaceLayout(tmp_path)
    root = layout.manuscript_dir
    (root / "sections").mkdir(parents=True)
    (root / "main.tex").write_text("\\input{sections/intro.tex}\n", encoding="utf-8")
    (root / "sections" / "intro.tex").write_text(BODY, encoding="utf-8")
    (root / "references.bib").write_text("@article{a2019,}\n", encoding="utf-8")
    return ManuscriptFiles(layout)


# -- the tree ---------------------------------------------------------------------------


def test_the_tree_lists_relative_posix_paths_sorted_with_their_kinds(
    files: ManuscriptFiles,
) -> None:
    listed = files.tree()

    assert [(item.path, item.kind) for item in listed] == [
        ("main.tex", ManuscriptFileKind.TEX),
        ("references.bib", ManuscriptFileKind.BIB),
        ("sections/intro.tex", ManuscriptFileKind.TEX),
    ]
    assert all(item.size_bytes > 0 for item in listed)
    assert all(item.modified_at.tzinfo is not None for item in listed)


def test_a_figure_is_listed_as_an_image(files: ManuscriptFiles) -> None:
    (files.root / "figures").mkdir()
    (files.root / "figures" / "loss.png").write_bytes(b"\x89PNG\r\n")

    kinds = {item.path: item.kind for item in files.tree()}

    assert kinds["figures/loss.png"] is ManuscriptFileKind.IMAGE


def test_hidden_entries_and_compiler_leftovers_are_not_manuscript_source(
    files: ManuscriptFiles,
) -> None:
    (files.root / "main.aux").write_text("\\relax\n", encoding="utf-8")
    (files.root / "main.synctex.gz").write_bytes(b"\x1f\x8b")
    (files.root / "main.log").write_text("log\n", encoding="utf-8")
    (files.root / "anchors.jsonl").write_text("{}\n", encoding="utf-8")
    (files.root / ".hidden.tex").write_text("x\n", encoding="utf-8")
    (files.root / ".build").mkdir()
    (files.root / ".build" / "draft.tex").write_text("x\n", encoding="utf-8")

    assert [item.path for item in files.tree()] == [
        "main.tex",
        "references.bib",
        "sections/intro.tex",
    ]


def test_an_empty_manuscript_directory_lists_nothing(tmp_path: Path) -> None:
    assert ManuscriptFiles(tmp_path).tree() == ()


# -- reading ----------------------------------------------------------------------------


def test_reading_returns_the_text_and_the_hash_of_the_bytes_on_disk(
    files: ManuscriptFiles,
) -> None:
    snapshot = files.read("sections/intro.tex")

    assert isinstance(snapshot, FileSnapshot)
    assert snapshot.content == BODY
    assert snapshot.content_hash == content_hash(BODY.encode("utf-8"))
    assert snapshot.path == "sections/intro.tex"


def test_reading_preserves_line_endings_exactly(files: ManuscriptFiles) -> None:
    """A save must be able to write back what a read returned, byte for byte."""
    (files.root / "windows.tex").write_bytes(b"one\r\ntwo\r\n")

    snapshot = files.read("windows.tex")

    assert snapshot.content == "one\r\ntwo\r\n"
    assert files.hash_of("windows.tex") == content_hash(b"one\r\ntwo\r\n")


def test_reading_a_missing_file_says_so(files: ManuscriptFiles) -> None:
    with pytest.raises(ManuscriptFileNotFoundError):
        files.read("sections/method.tex")


def test_a_binary_figure_cannot_be_opened_as_text(files: ManuscriptFiles) -> None:
    (files.root / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")

    with pytest.raises(ManuscriptBinaryFileError):
        files.read("plot.png")

    assert files.read_bytes("plot.png").startswith(b"\x89PNG")


# -- confinement ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "../research.yaml",
        "sections/../../escape.tex",
        "/etc/passwd",
        "sections\\intro.tex",
        "C:/Windows/system.ini",
        ".ssh/id_rsa",
        "sections/.hidden.tex",
        "",
        "   ",
    ],
)
def test_a_path_that_escapes_or_hides_is_refused_before_the_filesystem_is_touched(
    files: ManuscriptFiles, path: str
) -> None:
    with pytest.raises(ManuscriptPathError):
        files.path_for(path)


def test_a_symlink_pointing_out_of_the_manuscript_directory_is_refused(
    files: ManuscriptFiles, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.tex"
    outside.write_text("secret\n", encoding="utf-8")
    os.symlink(outside, files.root / "link.tex")

    with pytest.raises(ManuscriptPathError):
        files.read("link.tex")
    assert "link.tex" not in [item.path for item in files.tree()]


def test_the_harness_owned_anchor_file_is_not_editable_source(files: ManuscriptFiles) -> None:
    (files.root / "anchors.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ManuscriptPathError):
        files.read("anchors.jsonl")


# -- writing ----------------------------------------------------------------------------


def test_a_save_that_presents_the_current_hash_replaces_the_file(
    files: ManuscriptFiles,
) -> None:
    snapshot = files.read("sections/intro.tex")

    saved = files.write("sections/intro.tex", "New text.\n", snapshot.content_hash)

    assert saved.content == "New text.\n"
    assert saved.content_hash != snapshot.content_hash
    assert (files.root / "sections" / "intro.tex").read_text(encoding="utf-8") == "New text.\n"


def test_a_save_against_a_stale_hash_is_refused_and_leaves_the_file_untouched(
    files: ManuscriptFiles,
) -> None:
    snapshot = files.read("sections/intro.tex")
    outside_edit = "Edited in another editor.\n"
    (files.root / "sections" / "intro.tex").write_text(outside_edit, encoding="utf-8")

    with pytest.raises(ManuscriptConflictError) as error:
        files.write("sections/intro.tex", "Our version.\n", snapshot.content_hash)

    assert error.value.path == "sections/intro.tex"
    assert error.value.expected_hash == snapshot.content_hash
    assert error.value.actual_hash == content_hash(outside_edit.encode("utf-8"))
    assert (files.root / "sections" / "intro.tex").read_text(encoding="utf-8") == outside_edit


def test_saving_a_file_that_no_longer_exists_is_not_a_conflict_but_a_missing_file(
    files: ManuscriptFiles,
) -> None:
    snapshot = files.read("references.bib")
    (files.root / "references.bib").unlink()

    with pytest.raises(ManuscriptFileNotFoundError):
        files.write("references.bib", "x\n", snapshot.content_hash)


def test_a_read_write_round_trip_reproduces_the_same_hash(files: ManuscriptFiles) -> None:
    snapshot = files.read("main.tex")

    saved = files.write("main.tex", snapshot.content, snapshot.content_hash)

    assert saved.content_hash == snapshot.content_hash


# -- create, rename, delete -------------------------------------------------------------


def test_creating_a_file_makes_its_directories_and_refuses_to_overwrite(
    files: ManuscriptFiles,
) -> None:
    created = files.create("sections/method.tex", "\\section{Method}\n")

    assert created.path == "sections/method.tex"
    assert (files.root / "sections" / "method.tex").is_file()
    with pytest.raises(ManuscriptFileExistsError):
        files.create("sections/method.tex")


def test_renaming_moves_the_file_and_refuses_an_occupied_destination(
    files: ManuscriptFiles,
) -> None:
    moved = files.rename("sections/intro.tex", "sections/introduction.tex")

    assert moved.path == "sections/introduction.tex"
    assert moved.kind is ManuscriptFileKind.TEX
    assert files.read("sections/introduction.tex").content == BODY
    assert not (files.root / "sections" / "intro.tex").exists()
    files.create("sections/intro.tex", "placeholder\n")
    with pytest.raises(ManuscriptFileExistsError):
        files.rename("sections/intro.tex", "sections/introduction.tex")


def test_a_figure_can_be_renamed_even_though_it_has_no_text(files: ManuscriptFiles) -> None:
    (files.root / "loss.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")

    moved = files.rename("loss.png", "figures/loss.png")

    assert moved.path == "figures/loss.png"
    assert moved.kind is ManuscriptFileKind.IMAGE


def test_renaming_with_a_stale_hash_is_refused(files: ManuscriptFiles) -> None:
    snapshot = files.read("sections/intro.tex")
    (files.root / "sections" / "intro.tex").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ManuscriptConflictError):
        files.rename("sections/intro.tex", "sections/x.tex", expected_hash=snapshot.content_hash)

    assert (files.root / "sections" / "intro.tex").is_file()


def test_deleting_requires_the_current_hash(files: ManuscriptFiles) -> None:
    snapshot = files.read("references.bib")
    (files.root / "references.bib").write_text("@book{b2020,}\n", encoding="utf-8")

    with pytest.raises(ManuscriptConflictError):
        files.delete("references.bib", snapshot.content_hash)
    assert (files.root / "references.bib").is_file()

    files.delete("references.bib", files.hash_of("references.bib"))
    assert not (files.root / "references.bib").exists()


@pytest.mark.parametrize("path", ["../escape.tex", "/tmp/escape.tex", ".hidden.tex"])
def test_every_mutation_refuses_an_unsafe_path(files: ManuscriptFiles, path: str) -> None:
    with pytest.raises(ManuscriptPathError):
        files.create(path, "x\n")
    with pytest.raises(ManuscriptPathError):
        files.write(path, "x\n", "sha256:" + "0" * 64)
    with pytest.raises(ManuscriptPathError):
        files.delete(path, "sha256:" + "0" * 64)
    with pytest.raises(ManuscriptPathError):
        files.rename("main.tex", path)


# -- the inputs fingerprint -------------------------------------------------------------


def test_the_fingerprint_changes_with_the_source_and_ignores_build_leftovers(
    files: ManuscriptFiles,
) -> None:
    before = files.fingerprint()
    (files.root / "main.aux").write_text("\\relax\n", encoding="utf-8")

    assert files.fingerprint() == before

    files.write("main.tex", "\\input{sections/intro}\n", files.hash_of("main.tex"))
    assert files.fingerprint() != before


def test_the_fingerprint_notices_a_rename(files: ManuscriptFiles) -> None:
    before = files.fingerprint()

    files.rename("sections/intro.tex", "sections/introduction.tex")

    assert files.fingerprint() != before

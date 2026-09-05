"""Platform data locations and root containment are the app's only OS-specific rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.local_app.paths import (
    ProjectPathError,
    app_data_dir,
    assert_beneath,
    canonical_directory,
)


def test_windows_uses_local_app_data(tmp_path: Path) -> None:
    found = app_data_dir(system="Windows", env={"LOCALAPPDATA": str(tmp_path)}, home=tmp_path)
    assert found == tmp_path / "ResearchHarness"


def test_windows_without_local_app_data_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ProjectPathError):
        app_data_dir(system="Windows", env={}, home=tmp_path)


def test_linux_prefers_xdg_data_home(tmp_path: Path) -> None:
    found = app_data_dir(system="Linux", env={"XDG_DATA_HOME": str(tmp_path)}, home=Path("/home/r"))
    assert found == tmp_path / "research-harness"


def test_linux_falls_back_to_the_home_share_directory() -> None:
    found = app_data_dir(system="Linux", env={}, home=Path("/home/r"))
    assert found == Path("/home/r/.local/share/research-harness")


def test_an_unsupported_platform_is_refused() -> None:
    with pytest.raises(ProjectPathError, match="Darwin"):
        app_data_dir(system="Darwin", env={}, home=Path("/Users/r"))


def test_canonical_directory_resolves_symlinks_and_relative_syntax(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("this Windows account cannot create directory symlinks")
    assert canonical_directory(link) == real.resolve()
    assert canonical_directory(real / "." / ".." / "real") == real.resolve()


def test_canonical_directory_refuses_a_file_and_a_missing_path(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ProjectPathError):
        canonical_directory(file_path)
    with pytest.raises(ProjectPathError):
        canonical_directory(tmp_path / "missing")


def test_a_resolved_child_must_remain_beneath_the_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    child = root / "paper.tex"
    child.write_text("x", encoding="utf-8")
    assert assert_beneath(root, child) == child.resolve()
    with pytest.raises(ProjectPathError):
        assert_beneath(root, tmp_path / "outside.txt")


def test_a_parent_traversal_escapes_the_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ProjectPathError):
        assert_beneath(root, root / ".." / "outside.txt")


def test_a_symlink_leaving_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    escape = root / "secret.txt"
    try:
        escape.symlink_to(outside)
    except OSError:
        pytest.skip("this Windows account cannot create file symlinks")
    with pytest.raises(ProjectPathError):
        assert_beneath(root, escape)


def test_the_root_itself_is_beneath_the_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    assert assert_beneath(root, root) == root.resolve()

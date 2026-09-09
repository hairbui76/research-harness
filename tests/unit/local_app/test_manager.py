"""Project lifecycle: only validated folders get registered, and nothing deletes user files."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from research_harness.domain.enums import ReviewPolicy
from research_harness.local_app.manager import ProjectManager, safe_folder_name
from research_harness.local_app.models import (
    ProjectActiveRunsError,
    ProjectAvailability,
    ProjectLifecycleError,
    ProjectNeedsInitializationError,
    ProjectNotFoundError,
)
from research_harness.local_app.paths import ProjectPathError
from research_harness.local_app.registry import ProjectRegistry
from research_harness.workspace.repository import WorkspaceRepository


def ids() -> Callable[[], str]:
    counter = {"n": 0}

    def next_id() -> str:
        counter["n"] += 1
        return f"prj_{counter['n']:016x}"

    return next_id


def clock_from(start: datetime) -> Callable[[], datetime]:
    state = {"now": start}

    def tick() -> datetime:
        state["now"] += timedelta(seconds=1)
        return state["now"]

    return tick


def manager_at(
    tmp_path: Path,
    *,
    active_runs: Callable[[str], Sequence[str]] = lambda _project_id: (),
    reveal: Callable[[Path], None] | None = None,
    on_root_changed: Callable[[str], None] | None = None,
) -> ProjectManager:
    registry = ProjectRegistry(tmp_path / "appdata" / "projects.json")
    return ProjectManager(
        registry,
        clock=clock_from(datetime(2026, 1, 1, tzinfo=UTC)),
        id_factory=ids(),
        active_runs=active_runs,
        reveal=reveal,
        on_root_changed=on_root_changed,
    )


# -- naming ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Độ trễ mạng", "do-tre-mang"),
        ("Latency 2026", "latency-2026"),
        ("  spaced  out  ", "spaced-out"),
        ("a/b\\c", "a-b-c"),
        ("..hidden..", "hidden"),
    ],
)
def test_safe_folder_name_produces_a_portable_slug(name: str, expected: str) -> None:
    assert safe_folder_name(name) == expected


@pytest.mark.parametrize("name", ["...", "///", "   ", "CON", "nul"])
def test_safe_folder_name_refuses_unusable_names(name: str) -> None:
    with pytest.raises(ProjectLifecycleError):
        safe_folder_name(name)


# -- create / open / initialize ----------------------------------------------


def test_create_initializes_a_safe_child_and_registers_it(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    view = manager.create(parent, "Độ trễ mạng", ReviewPolicy.STRICT)
    assert view.path.name == "do-tre-mang"
    assert (view.path / "research.yaml").is_file()
    assert view.display_name == "Độ trễ mạng"
    assert view.availability is ProjectAvailability.available
    assert manager.get(view.project_id).project_id == view.project_id


def test_create_refuses_an_existing_folder_and_registers_nothing(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    (tmp_path / "taken").mkdir()
    with pytest.raises(ProjectLifecycleError):
        manager.create(tmp_path, "Taken", ReviewPolicy.STRICT)
    assert manager.list_projects() == ()


def test_create_refuses_a_missing_parent(tmp_path: Path) -> None:
    with pytest.raises(ProjectPathError):
        manager_at(tmp_path).create(tmp_path / "nowhere", "Fine", ReviewPolicy.STRICT)


def test_open_requires_an_existing_workspace(tmp_path: Path) -> None:
    folder = tmp_path / "ordinary"
    folder.mkdir()
    manager = manager_at(tmp_path)
    with pytest.raises(ProjectNeedsInitializationError):
        manager.open(folder)
    assert manager.list_projects() == ()


def test_opening_the_same_root_returns_the_existing_project_id(tmp_path: Path) -> None:
    root = WorkspaceRepository.init(tmp_path / "project", "P").root
    manager = manager_at(tmp_path)
    first = manager.open(root)
    second = manager.open(root / ".")
    assert second.project_id == first.project_id
    assert len(manager.list_projects()) == 1


def test_open_records_a_newer_last_opened_time(tmp_path: Path) -> None:
    root = WorkspaceRepository.init(tmp_path / "project", "P").root
    manager = manager_at(tmp_path)
    first = manager.open(root)
    second = manager.open(root)
    assert second.last_opened_at > first.last_opened_at


def test_initialize_creates_the_workspace_in_an_existing_folder(tmp_path: Path) -> None:
    folder = tmp_path / "ordinary"
    folder.mkdir()
    manager = manager_at(tmp_path)
    view = manager.initialize(folder, "Ordinary", ReviewPolicy.STRICT)
    assert (folder / "research.yaml").is_file()
    assert view.display_name == "Ordinary"
    assert WorkspaceRepository.open(folder).config.name == "Ordinary"


def test_initialize_refuses_a_folder_that_is_already_a_workspace(tmp_path: Path) -> None:
    root = WorkspaceRepository.init(tmp_path / "project", "P").root
    with pytest.raises(ProjectLifecycleError):
        manager_at(tmp_path).initialize(root, "Again", ReviewPolicy.STRICT)


# -- locate / rename / forget / reveal ---------------------------------------


def test_locate_keeps_the_project_id_and_updates_only_after_validation(tmp_path: Path) -> None:
    evicted: list[str] = []
    manager = manager_at(tmp_path, on_root_changed=evicted.append)
    old = manager.create(tmp_path, "Old", ReviewPolicy.STRICT)
    new_root = WorkspaceRepository.init(tmp_path / "moved", "Old").root
    moved = manager.locate(old.project_id, new_root)
    assert moved.project_id == old.project_id
    assert moved.path == new_root.resolve()
    assert evicted == [old.project_id]


def test_locate_refuses_a_folder_that_is_not_a_workspace(tmp_path: Path) -> None:
    evicted: list[str] = []
    manager = manager_at(tmp_path, on_root_changed=evicted.append)
    view = manager.create(tmp_path, "Old", ReviewPolicy.STRICT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(ProjectLifecycleError):
        manager.locate(view.project_id, elsewhere)
    assert manager.get(view.project_id).path == view.path
    assert evicted == []


def test_locate_refuses_a_project_with_an_active_run(tmp_path: Path) -> None:
    manager = manager_at(tmp_path, active_runs=lambda _project_id: ("run_1",))
    view = manager.create(tmp_path, "Busy", ReviewPolicy.STRICT)
    new_root = WorkspaceRepository.init(tmp_path / "moved", "Busy").root
    with pytest.raises(ProjectActiveRunsError):
        manager.locate(view.project_id, new_root)
    assert manager.get(view.project_id).path == view.path


def test_rename_changes_only_the_application_label(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    view = manager.create(tmp_path, "Before", ReviewPolicy.STRICT)
    original = (view.path / "research.yaml").read_text(encoding="utf-8")
    renamed = manager.rename(view.project_id, "After")
    assert renamed.display_name == "After"
    assert renamed.path == view.path
    assert (view.path / "research.yaml").read_text(encoding="utf-8") == original
    assert WorkspaceRepository.open(view.path).config.name == "Before"


def test_forget_never_deletes_the_workspace(tmp_path: Path) -> None:
    evicted: list[str] = []
    manager = manager_at(tmp_path, on_root_changed=evicted.append)
    view = manager.create(tmp_path, "Keep me", ReviewPolicy.STRICT)
    manager.forget(view.project_id)
    assert view.path.is_dir()
    assert (view.path / "research.yaml").is_file()
    assert manager.list_projects() == ()
    assert evicted == [view.project_id]


def test_forget_refuses_a_project_with_an_active_run(tmp_path: Path) -> None:
    manager = manager_at(tmp_path, active_runs=lambda _project_id: ("run_1",))
    view = manager.create(tmp_path, "Busy", ReviewPolicy.STRICT)
    with pytest.raises(ProjectActiveRunsError):
        manager.forget(view.project_id)
    assert len(manager.list_projects()) == 1


def test_forget_still_works_when_the_folder_is_gone(tmp_path: Path) -> None:
    def explode(_project_id: str) -> Sequence[str]:
        raise FileNotFoundError("the folder is gone")

    manager = manager_at(tmp_path, active_runs=explode)
    view = manager.create(tmp_path, "Gone", ReviewPolicy.STRICT)
    manager.forget(view.project_id)
    assert manager.list_projects() == ()


def test_unknown_projects_are_reported_not_guessed(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    for call in (
        lambda: manager.get("prj_00000000000000ff"),
        lambda: manager.forget("prj_00000000000000ff"),
        lambda: manager.rename("prj_00000000000000ff", "X"),
        lambda: manager.reveal("prj_00000000000000ff"),
        lambda: manager.locate("prj_00000000000000ff", tmp_path),
    ):
        with pytest.raises(ProjectNotFoundError):
            call()


def test_reveal_passes_only_the_registered_root_to_the_platform_action(tmp_path: Path) -> None:
    opened: list[Path] = []
    manager = manager_at(tmp_path, reveal=opened.append)
    view = manager.create(tmp_path, "Shown", ReviewPolicy.STRICT)
    manager.reveal(view.project_id)
    assert opened == [view.path]


# -- availability ------------------------------------------------------------


def test_a_missing_folder_is_unavailable(tmp_path: Path) -> None:
    import shutil

    manager = manager_at(tmp_path)
    view = manager.create(tmp_path, "Moved away", ReviewPolicy.STRICT)
    shutil.rmtree(view.path)
    listed = manager.list_projects()[0]
    assert listed.availability is ProjectAvailability.unavailable
    assert listed.detail == "Folder not found"


def test_a_folder_that_is_no_longer_a_workspace_is_invalid(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    view = manager.create(tmp_path, "Broken", ReviewPolicy.STRICT)
    (view.path / "research.yaml").unlink()
    listed = manager.list_projects()[0]
    assert listed.availability is ProjectAvailability.invalid
    assert listed.detail


def test_a_newer_schema_version_is_incompatible(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    view = manager.create(tmp_path, "Future", ReviewPolicy.STRICT)
    research = view.path / "research.yaml"
    research.write_text(
        re.sub(r"schema_version: \d+", "schema_version: 9999", research.read_text("utf-8")),
        encoding="utf-8",
    )
    listed = manager.list_projects()[0]
    assert listed.availability is ProjectAvailability.incompatible
    assert "9999" in (listed.detail or "")


def test_active_runs_make_a_project_busy(tmp_path: Path) -> None:
    manager = manager_at(tmp_path, active_runs=lambda _project_id: ("run_1", "run_2"))
    manager.create(tmp_path, "Busy", ReviewPolicy.STRICT)
    listed = manager.list_projects()[0]
    assert listed.availability is ProjectAvailability.busy
    assert listed.active_runs == 2


def test_listing_asks_whether_a_project_can_be_opened_without_opening_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The list is read on every page load; opening runs recovery and the consistency check.

    On a slow disk that cost, paid once per registered project, grows with the registry
    until the list itself times out, so availability is derived from a probe instead.
    """
    manager = manager_at(tmp_path)
    manager.create(tmp_path, "Listed", ReviewPolicy.STRICT)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("listing a project must not open its workspace")

    monkeypatch.setattr(WorkspaceRepository, "open", refuse)
    listed = manager.list_projects()[0]
    assert listed.availability is ProjectAvailability.available


def test_one_broken_project_does_not_hide_the_others(tmp_path: Path) -> None:
    import shutil

    manager = manager_at(tmp_path)
    broken = manager.create(tmp_path, "Broken", ReviewPolicy.STRICT)
    healthy = manager.create(tmp_path, "Healthy", ReviewPolicy.STRICT)
    shutil.rmtree(broken.path)
    by_id = {item.project_id: item for item in manager.list_projects()}
    assert by_id[broken.project_id].availability is ProjectAvailability.unavailable
    assert by_id[healthy.project_id].availability is ProjectAvailability.available

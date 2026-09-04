"""The app registry is durable, deduplicated by canonical root, and never silently reset."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_harness.local_app.models import ProjectNotFoundError, ProjectRecord
from research_harness.local_app.registry import (
    DuplicateProjectError,
    ProjectRegistry,
    ProjectRegistryError,
)


def record(root: Path, project_id: str, name: str, opened: datetime) -> ProjectRecord:
    return ProjectRecord(
        project_id=project_id,
        display_name=name,
        canonical_root=root.resolve(),
        created_at=opened,
        last_opened_at=opened,
    )


def test_registry_round_trips_and_orders_most_recent_first(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    store.add(record(tmp_path / "a", "prj_0000000000000001", "A", datetime(2026, 1, 1, tzinfo=UTC)))
    store.add(record(tmp_path / "b", "prj_0000000000000002", "B", datetime(2026, 1, 2, tzinfo=UTC)))
    assert [item.display_name for item in ProjectRegistry(store.path).list()] == ["B", "A"]


def test_a_missing_registry_file_reads_as_an_empty_registry(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "nested" / "projects.json")
    assert store.list() == ()
    assert store.get("prj_0000000000000001") is None
    assert not store.path.exists()


def test_registry_refuses_a_second_id_for_the_same_canonical_root(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    first = record(tmp_path / "same", "prj_0000000000000001", "A", datetime.now(UTC))
    store.add(first)
    with pytest.raises(DuplicateProjectError):
        store.add(first.model_copy(update={"project_id": "prj_00000000000000ff"}))


def test_registry_refuses_a_second_record_for_the_same_id(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    first = record(tmp_path / "one", "prj_0000000000000001", "A", datetime.now(UTC))
    store.add(first)
    with pytest.raises(DuplicateProjectError):
        store.add(first.model_copy(update={"canonical_root": (tmp_path / "two").resolve()}))


def test_corrupt_registry_is_preserved_and_reported(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ProjectRegistryError):
        ProjectRegistry(path).list()
    assert path.read_text(encoding="utf-8") == "not json"


def test_a_registry_with_an_unreadable_record_is_reported_not_dropped(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"version": 1, "projects": [{"project_id": "x"}]}), encoding="utf-8")
    with pytest.raises(ProjectRegistryError):
        ProjectRegistry(path).list()


def test_find_by_root_matches_a_different_spelling_of_the_same_folder(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    store = ProjectRegistry(tmp_path / "projects.json")
    store.add(record(root, "prj_0000000000000001", "A", datetime.now(UTC)))
    found = store.find_by_root(root / "." / ".." / "project")
    assert found is not None
    assert found.project_id == "prj_0000000000000001"


def test_replace_keeps_the_identifier_and_rewrites_the_entry(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    original = record(tmp_path / "old", "prj_0000000000000001", "A", datetime.now(UTC))
    store.add(original)
    moved = original.model_copy(update={"canonical_root": (tmp_path / "new").resolve()})
    store.replace(moved)
    reloaded = ProjectRegistry(store.path).get("prj_0000000000000001")
    assert reloaded is not None
    assert reloaded.canonical_root == (tmp_path / "new").resolve()


def test_replace_refuses_a_root_owned_by_another_project(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    first = record(tmp_path / "a", "prj_0000000000000001", "A", datetime.now(UTC))
    second = record(tmp_path / "b", "prj_0000000000000002", "B", datetime.now(UTC))
    store.add(first)
    store.add(second)
    with pytest.raises(DuplicateProjectError):
        store.replace(second.model_copy(update={"canonical_root": first.canonical_root}))


def test_replacing_or_removing_an_unknown_project_is_reported(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    ghost = record(tmp_path / "ghost", "prj_00000000000000aa", "Ghost", datetime.now(UTC))
    with pytest.raises(ProjectNotFoundError):
        store.replace(ghost)
    with pytest.raises(ProjectNotFoundError):
        store.remove(ghost.project_id)


def test_remove_deletes_only_the_named_entry(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    store.add(record(tmp_path / "a", "prj_0000000000000001", "A", datetime.now(UTC)))
    store.add(record(tmp_path / "b", "prj_0000000000000002", "B", datetime.now(UTC)))
    store.remove("prj_0000000000000001")
    assert [item.project_id for item in store.list()] == ["prj_0000000000000002"]


def test_writes_are_atomic_and_leave_no_temporary_files(tmp_path: Path) -> None:
    home = tmp_path / "data"
    store = ProjectRegistry(home / "projects.json")
    store.add(record(tmp_path / "a", "prj_0000000000000001", "A", datetime.now(UTC)))
    store.add(record(tmp_path / "b", "prj_0000000000000002", "B", datetime.now(UTC)))
    assert [item.name for item in home.iterdir()] == ["projects.json"]


def test_the_registry_document_holds_no_credentials(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    store.add(record(tmp_path / "a", "prj_0000000000000001", "A", datetime.now(UTC)))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert set(payload["projects"][0]) == {
        "project_id",
        "display_name",
        "canonical_root",
        "created_at",
        "last_opened_at",
        "status_hint",
    }

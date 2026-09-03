"""`update_providers` is durable, atomic, secret-refusing, and event-free (spec §11, §16)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.serialization import WorkspaceSerializationError

ENTRY = {
    "name": "codex-sub",
    "kind": "local_cli",
    "runtime": "codex",
    "model": "default",
    "priority": 10,
}


def test_the_new_list_is_written_atomically_and_read_back(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "p", "providers")
    events_before = (
        repo.layout.events_file.read_text(encoding="utf-8")
        if repo.layout.events_file.is_file()
        else ""
    )

    config = repo.update_providers([ENTRY])

    assert config.providers == [ENTRY]
    assert yaml.safe_load(repo.layout.research_file.read_text(encoding="utf-8"))["providers"] == [
        ENTRY
    ]
    assert WorkspaceRepository.open(repo.root).config.providers == [ENTRY]
    after = (
        repo.layout.events_file.read_text(encoding="utf-8")
        if repo.layout.events_file.is_file()
        else ""
    )
    assert after == events_before, "configuration is not scientific state; no ResearchEvent"
    assert not list(repo.root.glob(".tmp-*"))


def test_a_credential_in_the_new_list_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "p", "providers")
    before = repo.layout.research_file.read_bytes()
    with pytest.raises((ValueError, WorkspaceSerializationError), match="must not contain api_key"):
        repo.update_providers([{**ENTRY, "api_key": "sk-x"}])
    assert repo.layout.research_file.read_bytes() == before


def test_update_providers_may_run_inside_a_held_lock(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "p", "providers")
    with repo.lock():
        assert repo.update_providers([ENTRY]).providers == [ENTRY]

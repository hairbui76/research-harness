"""The only component allowed to turn a folder the researcher chose into a registered project.

Every entry point resolves the path, proves the folder really is a workspace through the
existing repository boundary, and only then writes the registry. Forget and locate change
registry rows; nothing here deletes, moves, or rewrites a single file under a project root.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import unicodedata
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.domain.base import utc_now
from research_harness.domain.enums import ReviewPolicy
from research_harness.domain.errors import ResearchHarnessError, WorkspaceError
from research_harness.local_app.models import (
    ProjectActiveRunsError,
    ProjectAvailability,
    ProjectLifecycleError,
    ProjectNeedsInitializationError,
    ProjectNotFoundError,
    ProjectRecord,
    ProjectView,
)
from research_harness.local_app.paths import canonical_directory
from research_harness.local_app.registry import ProjectRegistry
from research_harness.workspace.migrations import UnsupportedSchemaVersionError
from research_harness.workspace.repository import (
    WorkspaceExistsError,
    WorkspaceNotFoundError,
    WorkspaceRepository,
)

__all__ = [
    "WINDOWS_RESERVED_NAMES",
    "ProjectManager",
    "default_reveal",
    "new_project_id",
    "safe_folder_name",
]

logger = logging.getLogger(__name__)

WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)
"""Names Windows refuses as files or folders, with or without an extension."""


def new_project_id() -> str:
    """A fresh opaque project id; it encodes nothing about the folder it will point at."""
    return f"prj_{secrets.token_hex(8)}"


def safe_folder_name(name: str) -> str:
    """Fold a display name into a folder name both Windows and Linux accept.

    The display name keeps its original script; only the folder is transliterated, so a
    project called "Độ trễ mạng" lives in `do-tre-mang` and still shows its real title.
    """
    latin = name.replace("Đ", "D").replace("đ", "d")
    ascii_name = unicodedata.normalize("NFKD", latin).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip(".-").lower()
    if not slug or slug.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        raise ProjectLifecycleError(f"project name does not produce a safe folder name: {name!r}")
    return slug


def default_reveal(path: Path) -> None:
    """Open `path` in the platform file manager, passing the folder as one argument."""
    system = platform.system()
    if system == "Windows":
        # `os.startfile` exists only on Windows, so it is looked up rather than imported.
        startfile = getattr(os, "startfile", None)
        if startfile is None:  # pragma: no cover - defensive; Windows always has it
            raise ProjectLifecycleError("this Windows build cannot open a file manager")
        startfile(os.fspath(path))
        return
    if system == "Linux":
        opener = shutil.which("xdg-open")
        if opener is None:
            raise ProjectLifecycleError("xdg-open is not available; open the folder manually")
        # A fixed argument vector, never a shell string: the path cannot become a command.
        subprocess.run([opener, os.fspath(path)], check=False)
        return
    raise ProjectLifecycleError(f"cannot open a file manager on {system}")


class ProjectManager:
    """Create, open, locate, rename, forget, and list the researcher's local projects."""

    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_project_id,
        active_runs: Callable[[str], Sequence[str]] = lambda _project_id: (),
        reveal: Callable[[Path], None] | None = None,
        on_root_changed: Callable[[str], None] | None = None,
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._id_factory = id_factory
        self._active_runs = active_runs
        self._reveal = reveal if reveal is not None else default_reveal
        self._on_root_changed = on_root_changed

    # -- adding projects -----------------------------------------------------

    def create(
        self, parent: Path | str, name: str, policy: ReviewPolicy = ReviewPolicy.STRICT
    ) -> ProjectView:
        """Initialize a new workspace in a safely named child of `parent` and register it."""
        canonical_parent = canonical_directory(parent)
        root = canonical_parent / safe_folder_name(name)
        if root.exists():
            raise ProjectLifecycleError(f"project folder already exists: {root}")
        result = init_project(InitProjectRequest(root=root, name=name, policy=policy))
        return self._register(result.root, name)

    def open(self, root: Path | str) -> ProjectView:
        """Register an existing workspace, or return the project already bound to it."""
        canonical = canonical_directory(root)
        existing = self._registry.find_by_root(canonical)
        if existing is not None:
            return self._view(self._touch(existing))
        try:
            repo = WorkspaceRepository.open(canonical)
        except WorkspaceNotFoundError as exc:
            raise ProjectNeedsInitializationError(str(exc)) from exc
        return self._register(repo.root, repo.config.name)

    def initialize(
        self, root: Path | str, name: str, policy: ReviewPolicy = ReviewPolicy.STRICT
    ) -> ProjectView:
        """Initialize a workspace inside an existing empty-ish folder, then register it."""
        canonical = canonical_directory(root)
        try:
            result = init_project(InitProjectRequest(root=canonical, name=name, policy=policy))
        except WorkspaceExistsError as exc:
            raise ProjectLifecycleError(str(exc)) from exc
        return self._register(result.root, name)

    # -- changing projects ---------------------------------------------------

    def locate(self, project_id: str, root: Path | str) -> ProjectView:
        """Point an existing project at the folder it was moved to, keeping its identity."""
        record = self._require(project_id)
        self._refuse_active_runs(record)
        canonical = canonical_directory(root)
        try:
            repo = WorkspaceRepository.open(canonical)
        except WorkspaceError as exc:
            raise ProjectLifecycleError(f"cannot use {canonical} as this project: {exc}") from exc
        moved = record.model_copy(
            update={"canonical_root": repo.root.resolve(), "last_opened_at": self._clock()}
        )
        self._registry.replace(moved)
        self._notify_root_changed(project_id)
        return self._view(moved)

    def rename(self, project_id: str, display_name: str) -> ProjectView:
        """Change the application label only; `research.yaml` is scientific state, not ours."""
        record = self._require(project_id)
        renamed = record.model_copy(update={"display_name": display_name})
        self._registry.replace(renamed)
        return self._view(renamed)

    def forget(self, project_id: str) -> None:
        """Drop the registry entry. Every file under the project root stays exactly as it is."""
        record = self._require(project_id)
        self._refuse_active_runs(record)
        self._registry.remove(project_id)
        self._notify_root_changed(project_id)

    def reveal(self, project_id: str) -> None:
        """Show the project folder in the platform file manager."""
        record = self._require(project_id)
        self._reveal(record.canonical_root)

    # -- reading projects ----------------------------------------------------

    def list_projects(self) -> tuple[ProjectView, ...]:
        """Every registered project with freshly derived availability, most recent first."""
        return tuple(self._view(record) for record in self._registry.list())

    def get(self, project_id: str) -> ProjectView:
        """One project's current view; raises when the app has never registered that id."""
        return self._view(self._require(project_id))

    # -- internals -----------------------------------------------------------

    def _require(self, project_id: str) -> ProjectRecord:
        record = self._registry.get(project_id)
        if record is None:
            raise ProjectNotFoundError(f"no such project: {project_id}")
        return record

    def _register(self, root: Path, display_name: str) -> ProjectView:
        canonical = canonical_directory(root)
        existing = self._registry.find_by_root(canonical)
        if existing is not None:
            return self._view(self._touch(existing))
        moment = self._clock()
        record = ProjectRecord(
            project_id=self._id_factory(),
            display_name=display_name,
            canonical_root=canonical,
            created_at=moment,
            last_opened_at=moment,
        )
        self._registry.add(record)
        return self._view(record)

    def _touch(self, record: ProjectRecord) -> ProjectRecord:
        opened = record.model_copy(update={"last_opened_at": self._clock()})
        self._registry.replace(opened)
        return opened

    def _refuse_active_runs(self, record: ProjectRecord) -> None:
        active = self._probe_active_runs(record.project_id)
        if active:
            raise ProjectActiveRunsError(
                f"{record.display_name} has {len(active)} active run(s); "
                "wait for them or cancel them first"
            )

    def _probe_active_runs(self, project_id: str) -> tuple[str, ...]:
        """Active runs for a lifecycle check.

        A workspace we cannot even open has no in-process runs we could wait for, and
        refusing to forget it would strand the researcher, so an unreadable project counts
        as idle here. `list_projects` reports the same failure honestly.
        """
        try:
            return tuple(self._active_runs(project_id))
        except (ResearchHarnessError, OSError) as exc:
            logger.warning("cannot read active runs for %s: %s", project_id, exc)
            return ()

    def _notify_root_changed(self, project_id: str) -> None:
        if self._on_root_changed is not None:
            self._on_root_changed(project_id)

    def _view(self, record: ProjectRecord) -> ProjectView:
        if not record.canonical_root.is_dir():
            return ProjectView.from_record(
                record, availability=ProjectAvailability.unavailable, detail="Folder not found"
            )
        try:
            # A listing asks whether the folder is a workspace this build can open; it
            # does not open it. Opening runs recovery and the consistency check, and a
            # registry of many projects on a slow disk would pay that on every page load.
            WorkspaceRepository.probe(record.canonical_root)
            active = tuple(self._active_runs(record.project_id))
        except FileNotFoundError:
            return ProjectView.from_record(
                record, availability=ProjectAvailability.unavailable, detail="Folder not found"
            )
        except UnsupportedSchemaVersionError as exc:
            return ProjectView.from_record(
                record, availability=ProjectAvailability.incompatible, detail=str(exc)
            )
        except WorkspaceError as exc:
            return ProjectView.from_record(
                record, availability=ProjectAvailability.invalid, detail=str(exc)
            )
        availability = ProjectAvailability.busy if active else ProjectAvailability.available
        return ProjectView.from_record(record, availability=availability, active_runs=len(active))

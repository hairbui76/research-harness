"""`projects.json`: the durable map from opaque project ids to approved canonical roots.

The whole document is rewritten through an atomic replace on every change, mirroring the
durability pattern of `workspace/runs.py`. A registry that cannot be parsed is reported and
kept for diagnosis; it is never replaced with an empty one.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from research_harness.domain.errors import ResearchHarnessError
from research_harness.local_app.models import (
    ProjectNotFoundError,
    ProjectRecord,
    RegistryDocument,
)

__all__ = ["DuplicateProjectError", "ProjectRegistry", "ProjectRegistryError"]

logger = logging.getLogger(__name__)

_TEMP_PREFIX = ".tmp-"


class ProjectRegistryError(ResearchHarnessError):
    """The registry document could not be read or written."""


class DuplicateProjectError(ProjectRegistryError):
    """Another entry already claims this project id or this canonical root."""


class ProjectRegistry:
    """Reads and writes the registry document; every mutation is a whole-file replacement."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"ProjectRegistry({str(self._path)!r})"

    @property
    def path(self) -> Path:
        """The registry document's location, whether or not it exists yet."""
        return self._path

    # -- reads ---------------------------------------------------------------

    def list(self) -> tuple[ProjectRecord, ...]:
        """Every registered project, most recently opened first."""
        return self._ordered(self._load())

    def get(self, project_id: str) -> ProjectRecord | None:
        """The record for `project_id`, or None when the app has never registered it."""
        for record in self._load().projects:
            if record.project_id == project_id:
                return record
        return None

    def find_by_root(self, root: Path | str) -> ProjectRecord | None:
        """The record registered for `root`, comparing resolved paths, not path syntax."""
        target = self._resolve(root)
        for record in self._load().projects:
            if record.canonical_root == target:
                return record
        return None

    # -- writes --------------------------------------------------------------

    def add(self, record: ProjectRecord) -> ProjectRecord:
        """Register a new project; a repeated id or canonical root is refused."""
        with self._lock:
            document = self._load()
            for existing in document.projects:
                if existing.project_id == record.project_id:
                    raise DuplicateProjectError(f"project already registered: {record.project_id}")
                if existing.canonical_root == record.canonical_root:
                    raise DuplicateProjectError(
                        f"project root already registered: {record.canonical_root}"
                    )
            self._save(document.model_copy(update={"projects": (*document.projects, record)}))
        return record

    def replace(self, record: ProjectRecord) -> ProjectRecord:
        """Rewrite the entry with the same project id, keeping registry order stable."""
        with self._lock:
            document = self._load()
            updated: list[ProjectRecord] = []
            found = False
            for existing in document.projects:
                if existing.project_id == record.project_id:
                    updated.append(record)
                    found = True
                    continue
                if existing.canonical_root == record.canonical_root:
                    raise DuplicateProjectError(
                        f"project root already registered: {record.canonical_root}"
                    )
                updated.append(existing)
            if not found:
                raise ProjectNotFoundError(f"no such project: {record.project_id}")
            self._save(document.model_copy(update={"projects": tuple(updated)}))
        return record

    def remove(self, project_id: str) -> None:
        """Delete one registry entry. Nothing on disk beneath the project root is touched."""
        with self._lock:
            document = self._load()
            remaining = tuple(item for item in document.projects if item.project_id != project_id)
            if len(remaining) == len(document.projects):
                raise ProjectNotFoundError(f"no such project: {project_id}")
            self._save(document.model_copy(update={"projects": remaining}))

    # -- persistence ---------------------------------------------------------

    def _load(self) -> RegistryDocument:
        if not self._path.is_file():
            return RegistryDocument()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ProjectRegistryError(f"cannot read the project registry: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProjectRegistryError(
                f"the project registry at {self._path} is not valid JSON: {exc}. "
                "It has been left untouched for inspection."
            ) from exc
        try:
            return RegistryDocument.model_validate(payload)
        except ValidationError as exc:
            raise ProjectRegistryError(
                f"the project registry at {self._path} is not a registry document: {exc}. "
                "It has been left untouched for inspection."
            ) from exc

    def _save(self, document: RegistryDocument) -> None:
        text = json.dumps(document.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        temp = directory / f"{_TEMP_PREFIX}{self._path.name}.{uuid4().hex}"
        try:
            with temp.open("w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self._path)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise ProjectRegistryError(f"cannot write the project registry: {exc}") from exc
        _fsync_dir(directory)

    @staticmethod
    def _ordered(document: RegistryDocument) -> tuple[ProjectRecord, ...]:
        return tuple(sorted(document.projects, key=lambda item: item.last_opened_at, reverse=True))

    @staticmethod
    def _resolve(root: Path | str) -> Path:
        return Path(root).expanduser().resolve()


def _fsync_dir(directory: Path) -> None:
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platforms without directory descriptors
        return
    try:
        os.fsync(handle)
    except OSError:  # pragma: no cover - filesystems that cannot fsync a directory
        pass
    finally:
        os.close(handle)

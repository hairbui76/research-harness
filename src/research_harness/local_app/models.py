"""Persisted project records, the control-plane views built from them, and lifecycle errors.

These are *application* objects: which folders the researcher has opened and how healthy they
look. No scientific state, no credentials, no copied workspace configuration lives here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.base import UtcDatetime
from research_harness.domain.errors import ResearchHarnessError

__all__ = [
    "PROJECT_ID_PATTERN",
    "ProjectActiveRunsError",
    "ProjectAvailability",
    "ProjectLifecycleError",
    "ProjectNeedsInitializationError",
    "ProjectNotFoundError",
    "ProjectRecord",
    "ProjectView",
    "RegistryDocument",
    "RuntimeStatus",
]

PROJECT_ID_PATTERN = r"^prj_[0-9a-f]{16}$"
"""Opaque, stable, random project identifier; it carries no path information."""


class ProjectLifecycleError(ResearchHarnessError):
    """A project lifecycle operation was refused."""


class ProjectNotFoundError(ProjectLifecycleError):
    """No registry entry exists for the given project id."""


class ProjectNeedsInitializationError(ProjectLifecycleError):
    """The folder is usable but is not a research workspace yet."""


class ProjectActiveRunsError(ProjectLifecycleError):
    """The project has pending or running workflow runs, so it cannot be moved or forgotten."""


class ProjectAvailability(StrEnum):
    """How usable a registered project looks right now; never authoritative for long."""

    available = "available"
    unavailable = "unavailable"
    invalid = "invalid"
    incompatible = "incompatible"
    busy = "busy"


class ProjectRecord(BaseModel):
    """One registry entry: an opaque id bound to a canonical folder the researcher approved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    display_name: str = Field(min_length=1, max_length=120)
    canonical_root: Path
    created_at: UtcDatetime
    last_opened_at: UtcDatetime
    status_hint: str | None = None
    """Cached diagnostic from the last listing; recomputed on every read, never trusted."""


class RegistryDocument(BaseModel):
    """The whole `projects.json` document, versioned so it can migrate later."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    projects: tuple[ProjectRecord, ...] = ()


class ProjectView(BaseModel):
    """What the control plane shows for a project: the record plus derived health."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    display_name: str
    path: Path
    availability: ProjectAvailability
    detail: str | None = None
    active_runs: int = Field(default=0, ge=0)
    last_opened_at: UtcDatetime

    @classmethod
    def from_record(
        cls,
        record: ProjectRecord,
        *,
        availability: ProjectAvailability,
        detail: str | None = None,
        active_runs: int = 0,
    ) -> Self:
        """Build the public view of `record` with the availability the caller just derived."""
        return cls(
            project_id=record.project_id,
            display_name=record.display_name,
            path=record.canonical_root,
            availability=availability,
            detail=detail,
            active_runs=active_runs,
            last_opened_at=record.last_opened_at,
        )


class RuntimeStatus(BaseModel):
    """Whether a project's runtime is loaded in this process, and what it is busy with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    root: Path
    loaded: bool
    active_run_ids: tuple[str, ...] = ()
    last_accessed_at: datetime | None = None

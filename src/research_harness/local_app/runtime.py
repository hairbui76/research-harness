"""Per-project operational state: what `create_app(root)` used to hold in a closure.

One `WorkspaceRuntime` per opened project. Each carries its own mutation gate so a write in
project A never blocks project B; the per-workspace repository lock still serialises
mutations of one workspace across processes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.base import utc_now
from research_harness.local_app.models import (
    ProjectNotFoundError,
    ProjectRecord,
    RuntimeStatus,
)
from research_harness.local_app.registry import ProjectRegistry
from research_harness.workflows.models import RunStatus
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore

__all__ = [
    "ACTIVE_RUN_STATUSES",
    "LEGACY_PROJECT_ID",
    "ProjectRuntimePool",
    "WorkspaceRuntime",
    "active_run_ids_at",
]

LEGACY_PROJECT_ID = "prj_0000000000000000"
"""The project id the one-workspace daemon (`research serve`) runs under."""

ACTIVE_RUN_STATUSES = frozenset({RunStatus.pending, RunStatus.running})


@dataclass(slots=True)
class WorkspaceRuntime:
    """Everything one workspace's HTTP routes need, minus the routes themselves."""

    project_id: str
    root: Path
    catalog: CapabilityRegistry
    mutation_gate: threading.Lock = field(default_factory=threading.Lock)
    last_accessed_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        project_id: str,
        root: Path | str,
        *,
        catalog: CapabilityRegistry | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> WorkspaceRuntime:
        """A runtime over ``root``; the registry is built once per runtime when not given."""
        return cls(
            project_id=project_id,
            root=Path(root),
            catalog=catalog if catalog is not None else build_default_registry(),
            mutation_gate=threading.Lock(),
            last_accessed_at=clock(),
        )

    def touch(self, clock: Callable[[], datetime] = utc_now) -> None:
        """Record an access, for idle eviction."""
        self.last_accessed_at = clock()

    def active_run_ids(self) -> tuple[str, ...]:
        """Runs that are pending or running; these block Forget and Locate."""
        return active_run_ids_at(self.root)


def active_run_ids_at(root: Path) -> tuple[str, ...]:
    """Pending and running runs recorded under `root`, read from durable state, not memory.

    Run state lives on disk, so this answers truthfully for a project whose runtime is not
    loaded — and for one a previous process left mid-run.
    """
    repo = WorkspaceRepository.open(root)
    runs = RunStore(repo.layout.research_dir).list_runs()
    return tuple(run.run_id for run in runs if run.status in ACTIVE_RUN_STATUSES)


class ProjectRuntimePool:
    """Lazily built, per-project runtimes, keyed by project id and rooted in the registry.

    Every lookup re-reads the registry and revalidates the workspace, so a relocated or
    broken project can never be served from a stale root. One runtime per project keeps
    project A's mutation gate out of project B's way.
    """

    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        catalog_factory: Callable[[], CapabilityRegistry] = build_default_registry,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._registry = registry
        self._catalog_factory = catalog_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._runtimes: dict[str, WorkspaceRuntime] = {}

    def get(self, project_id: str) -> WorkspaceRuntime:
        """The runtime for `project_id`, created on first use and revalidated on every use."""
        root = self._require(project_id).canonical_root
        WorkspaceRepository.open(root)
        with self._lock:
            runtime = self._runtimes.get(project_id)
            if runtime is None or runtime.root != root:
                runtime = WorkspaceRuntime.create(
                    project_id, root, catalog=self._catalog_factory(), clock=self._clock
                )
                self._runtimes[project_id] = runtime
            else:
                runtime.touch(self._clock)
            return runtime

    def evict(self, project_id: str) -> None:
        """Drop the cached runtime. Nothing durable is lost; reopening rebuilds it."""
        with self._lock:
            self._runtimes.pop(project_id, None)

    def evict_idle(self, before: datetime) -> tuple[str, ...]:
        """Evict runtimes untouched since `before`, never one with an active run."""
        with self._lock:
            candidates = [
                runtime for runtime in self._runtimes.values() if runtime.last_accessed_at < before
            ]
        evicted: list[str] = []
        for candidate in candidates:
            if active_run_ids_at(candidate.root):
                continue
            with self._lock:
                if self._runtimes.get(candidate.project_id) is candidate:
                    del self._runtimes[candidate.project_id]
                    evicted.append(candidate.project_id)
        return tuple(evicted)

    def has_active_runs(self, project_id: str) -> bool:
        """Whether the project has any pending or running workflow run."""
        return bool(self.active_run_ids(project_id))

    def active_run_ids(self, project_id: str) -> tuple[str, ...]:
        """Pending and running run ids for a registered project."""
        return self.get(project_id).active_run_ids()

    def status(self, project_id: str) -> RuntimeStatus:
        """What the pool knows about a project without forcing its runtime to load."""
        record = self._require(project_id)
        with self._lock:
            runtime = self._runtimes.get(project_id)
        return RuntimeStatus(
            project_id=project_id,
            root=record.canonical_root,
            loaded=runtime is not None,
            active_run_ids=active_run_ids_at(record.canonical_root),
            last_accessed_at=runtime.last_accessed_at if runtime is not None else None,
        )

    def runtimes(self) -> tuple[WorkspaceRuntime, ...]:
        """A snapshot of the loaded runtimes, for inspection and shutdown."""
        with self._lock:
            return tuple(self._runtimes.values())

    def _require(self, project_id: str) -> ProjectRecord:
        record = self._registry.get(project_id)
        if record is None:
            raise ProjectNotFoundError(f"no such project: {project_id}")
        return record

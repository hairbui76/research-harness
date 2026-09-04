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
from research_harness.workflows.models import RunStatus
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore

__all__ = ["ACTIVE_RUN_STATUSES", "WorkspaceRuntime"]

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
        repo = WorkspaceRepository.open(self.root)
        runs = RunStore(repo.layout.research_dir).list_runs()
        return tuple(run.run_id for run in runs if run.status in ACTIVE_RUN_STATUSES)

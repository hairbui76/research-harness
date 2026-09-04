"""One runtime per project, isolated locks, honest active-run reads, and safe eviction."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.domain.errors import WorkspaceError
from research_harness.local_app.models import ProjectNotFoundError, ProjectRecord
from research_harness.local_app.registry import ProjectRegistry
from research_harness.local_app.runtime import ProjectRuntimePool, WorkspaceRuntime
from research_harness.workflows.models import RunStatus, WorkflowRun, new_run_id
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore

MOMENT = datetime(2026, 1, 1, tzinfo=UTC)


def counting_catalog() -> tuple[Callable[[], CapabilityRegistry], list[int]]:
    built: list[int] = []

    def factory() -> CapabilityRegistry:
        built.append(1)
        return CapabilityRegistry()

    return factory, built


@dataclass(frozen=True)
class Project:
    project_id: str
    root: Path
    pool: ProjectRuntimePool
    registry: ProjectRegistry

    def save_run(self, status: RunStatus) -> str:
        repo = WorkspaceRepository.open(self.root)
        run_id = new_run_id()
        RunStore(repo.layout.research_dir).create(
            WorkflowRun(
                run_id=run_id,
                workflow="screening",
                workflow_version="1",
                status=status,
                created_at=MOMENT,
                updated_at=MOMENT,
                inputs_fingerprint="sha256:" + "0" * 64,
            )
        )
        return run_id


def registered(
    tmp_path: Path,
    name: str = "p1",
    *,
    registry: ProjectRegistry | None = None,
    pool: ProjectRuntimePool | None = None,
    project_id: str | None = None,
) -> Project:
    store = registry or ProjectRegistry(tmp_path / "appdata" / "projects.json")
    root = WorkspaceRepository.init(tmp_path / name, name).root.resolve()
    identifier = project_id or f"prj_{abs(hash(name)) % (16**16):016x}"
    store.add(
        ProjectRecord(
            project_id=identifier,
            display_name=name,
            canonical_root=root,
            created_at=MOMENT,
            last_opened_at=MOMENT,
        )
    )
    return Project(identifier, root, pool or ProjectRuntimePool(store), store)


# -- isolation ---------------------------------------------------------------


def test_projects_get_distinct_mutation_gates_and_catalogs(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "appdata" / "projects.json")
    factory, built = counting_catalog()
    pool = ProjectRuntimePool(registry, catalog_factory=factory)
    left = registered(tmp_path, "left", registry=registry, pool=pool, project_id="prj_" + "1" * 16)
    right = registered(
        tmp_path, "right", registry=registry, pool=pool, project_id="prj_" + "2" * 16
    )
    first = pool.get(left.project_id)
    second = pool.get(right.project_id)
    assert first.mutation_gate is not second.mutation_gate
    assert first.catalog is not second.catalog
    assert first.root != second.root
    assert len(built) == 2


def test_one_runtime_per_project_is_reused(tmp_path: Path) -> None:
    project = registered(tmp_path)
    assert project.pool.get(project.project_id) is project.pool.get(project.project_id)
    assert len(project.pool.runtimes()) == 1


def test_get_updates_the_last_access_time(tmp_path: Path) -> None:
    ticks = iter([MOMENT, MOMENT + timedelta(minutes=5)])
    registry = ProjectRegistry(tmp_path / "appdata" / "projects.json")
    pool = ProjectRuntimePool(registry, clock=lambda: next(ticks))
    project = registered(tmp_path, registry=registry, pool=pool)
    first = pool.get(project.project_id)
    assert first.last_accessed_at == MOMENT
    assert pool.get(project.project_id).last_accessed_at == MOMENT + timedelta(minutes=5)


def test_an_unknown_project_is_never_served_a_runtime(tmp_path: Path) -> None:
    pool = ProjectRuntimePool(ProjectRegistry(tmp_path / "projects.json"))
    with pytest.raises(ProjectNotFoundError):
        pool.get("prj_00000000000000ff")
    with pytest.raises(ProjectNotFoundError):
        pool.status("prj_00000000000000ff")


def test_a_registered_root_that_is_no_longer_a_workspace_is_refused(tmp_path: Path) -> None:
    project = registered(tmp_path)
    (project.root / "research.yaml").unlink()
    with pytest.raises(WorkspaceError):
        project.pool.get(project.project_id)
    assert project.pool.runtimes() == ()


def test_the_pool_re_reads_the_registry_instead_of_trusting_a_cached_root(tmp_path: Path) -> None:
    project = registered(tmp_path)
    first = project.pool.get(project.project_id)
    moved = WorkspaceRepository.init(tmp_path / "moved", "p1").root.resolve()
    record = project.registry.get(project.project_id)
    assert record is not None
    project.registry.replace(record.model_copy(update={"canonical_root": moved}))
    second = project.pool.get(project.project_id)
    assert second is not first
    assert second.root == moved


# -- active runs -------------------------------------------------------------


def test_a_pending_or_running_run_blocks_forget(tmp_path: Path) -> None:
    project = registered(tmp_path)
    assert project.pool.has_active_runs(project.project_id) is False
    running = project.save_run(RunStatus.running)
    pending = project.save_run(RunStatus.pending)
    assert project.pool.has_active_runs(project.project_id) is True
    assert set(project.pool.active_run_ids(project.project_id)) == {running, pending}


def test_a_finished_run_does_not_keep_a_project_busy(tmp_path: Path) -> None:
    project = registered(tmp_path)
    project.save_run(RunStatus.succeeded)
    project.save_run(RunStatus.cancelled)
    assert project.pool.active_run_ids(project.project_id) == ()


def test_status_reports_load_state_without_forcing_a_load(tmp_path: Path) -> None:
    project = registered(tmp_path)
    run_id = project.save_run(RunStatus.running)
    cold = project.pool.status(project.project_id)
    assert cold.loaded is False
    assert cold.last_accessed_at is None
    assert cold.active_run_ids == (run_id,)
    assert cold.root == project.root
    project.pool.get(project.project_id)
    assert project.pool.status(project.project_id).loaded is True


# -- eviction ----------------------------------------------------------------


def test_idle_eviction_reopens_the_same_root(tmp_path: Path) -> None:
    project = registered(tmp_path)
    first = project.pool.get(project.project_id)
    project.pool.evict(project.project_id)
    second = project.pool.get(project.project_id)
    assert second is not first
    assert second.root == first.root
    assert second.mutation_gate is not first.mutation_gate


def test_evicting_an_unloaded_project_is_harmless(tmp_path: Path) -> None:
    pool = ProjectRuntimePool(ProjectRegistry(tmp_path / "projects.json"))
    pool.evict("prj_00000000000000ff")


def test_evict_idle_keeps_recent_and_busy_runtimes(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "appdata" / "projects.json")
    pool = ProjectRuntimePool(registry, clock=lambda: MOMENT)
    idle = registered(tmp_path, "idle", registry=registry, pool=pool, project_id="prj_" + "1" * 16)
    busy = registered(tmp_path, "busy", registry=registry, pool=pool, project_id="prj_" + "2" * 16)
    pool.get(idle.project_id)
    pool.get(busy.project_id)
    busy.save_run(RunStatus.running)
    assert pool.evict_idle(MOMENT + timedelta(minutes=30)) == (idle.project_id,)
    assert [item.project_id for item in pool.runtimes()] == [busy.project_id]
    assert pool.evict_idle(MOMENT - timedelta(minutes=30)) == ()


# -- concurrency -------------------------------------------------------------


def test_concurrent_callers_share_one_runtime(tmp_path: Path) -> None:
    project = registered(tmp_path)
    seen: list[WorkspaceRuntime] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        seen.append(project.pool.get(project.project_id))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({id(runtime) for runtime in seen}) == 1

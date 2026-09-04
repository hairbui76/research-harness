"""Reusable fixtures for the multi-project host: one app, two populated workspaces.

Every operating-system effect the host can reach - the folder dialog and the file manager -
is injected here, so the suite stays hermetic and a test can assert what the host asked the
platform to do. The project ids are deterministic (`prj_...0001`, `prj_...0002`) because a
cross-project isolation test reads better when the two ids are constants.

Task 13 extends these fixtures; keep them free of assertions about behaviour under test.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from research_harness.capabilities.context import open_context
from research_harness.capabilities.dto import CreateClaimRequest, InitProjectRequest
from research_harness.capabilities.handlers import create_claim, init_project
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.local_app.manager import ProjectManager
from research_harness.local_app.paths import registry_path
from research_harness.local_app.pickers.base import FolderPickerError, FolderSelection
from research_harness.local_app.registry import ProjectRegistry
from research_harness.local_app.runtime import ProjectRuntimePool
from research_harness.server.app import WEB_DIST_ENV
from research_harness.server.multi_app import create_multi_project_app
from research_harness.workflows.models import RunStatus, WorkflowRun, new_run_id
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore
from tests.contract.protocol.conftest import CLAIM, make_claim

APP_TOKEN = "test-app-token"
"""The app token every fixture presents; the real one is random and lives beside the data."""

APP_PORT = 8765
ORIGIN = f"http://127.0.0.1:{APP_PORT}"

LEFT = "prj_0000000000000001"
RIGHT = "prj_0000000000000002"
LEFT_STATEMENT = "left claim"
RIGHT_STATEMENT = "right claim"

MOMENT = datetime(2026, 1, 1, tzinfo=UTC)


def sequential_ids() -> Callable[[], str]:
    """Project ids in registration order, so `LEFT` and `RIGHT` mean something."""
    counter = itertools.count(1)
    return lambda: f"prj_{next(counter):016x}"


@dataclass
class FakePicker:
    """A folder dialog that answers from a queue instead of spawning a helper process."""

    selections: list[FolderSelection] = field(default_factory=list)
    failure: FolderPickerError | None = None
    titles: list[str] = field(default_factory=list)

    def select_folder(self, title: str) -> FolderSelection:
        """Record the title, then answer with the next queued outcome."""
        self.titles.append(title)
        if self.failure is not None:
            raise self.failure
        if not self.selections:
            return FolderSelection(
                path=None, method="manual", cancelled=False, fallback_required=True
            )
        return self.selections.pop(0)


def selected(path: Path) -> FolderSelection:
    """The dialog result for a researcher who chose `path`."""
    return FolderSelection(path=path, method="native", cancelled=False, fallback_required=False)


def cancelled() -> FolderSelection:
    """The dialog result for a researcher who closed the dialog."""
    return FolderSelection(path=None, method="native", cancelled=True, fallback_required=False)


@dataclass(frozen=True)
class MultiHarness:
    """One multi-project app and the collaborators the tests inspect."""

    app: FastAPI
    data_dir: Path
    registry: ProjectRegistry
    manager: ProjectManager
    pool: ProjectRuntimePool
    picker: FakePicker
    revealed: list[Path]


def build_multi_app(data_dir: Path, *, picker: FakePicker | None = None) -> MultiHarness:
    """The host as `research app` builds it, with the two platform effects faked out."""
    store = ProjectRegistry(registry_path(data_dir))
    pool = ProjectRuntimePool(store)
    revealed: list[Path] = []
    dialogs = picker if picker is not None else FakePicker()
    manager = ProjectManager(
        store,
        id_factory=sequential_ids(),
        active_runs=pool.active_run_ids,
        reveal=revealed.append,
        on_root_changed=pool.evict,
    )
    app = create_multi_project_app(
        data_dir,
        port=APP_PORT,
        token=APP_TOKEN,
        registry=store,
        pool=pool,
        manager=manager,
        picker=dialogs,
    )
    return MultiHarness(
        app=app,
        data_dir=data_dir,
        registry=store,
        manager=manager,
        pool=pool,
        picker=dialogs,
        revealed=revealed,
    )


def populated_workspace(root: Path, name: str, statement: str) -> Path:
    """An initialized workspace holding one Claim, built through the capability layer."""
    result = init_project(InitProjectRequest(root=root, name=name))
    ctx = open_context(result.root, HUMAN_ACTOR)
    create_claim(ctx, CreateClaimRequest(claim=make_claim(CLAIM, statement)))
    return result.root


def persist_run(root: Path, status: RunStatus = RunStatus.running) -> str:
    """Write a durable run record under `root`, the way a real workflow would leave one."""
    repo = WorkspaceRepository.open(root)
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


def authenticate(client: TestClient) -> TestClient:
    """Present the app token and the browser's own origin on every request."""
    client.headers["Authorization"] = f"Bearer {APP_TOKEN}"
    client.headers["Origin"] = ORIGIN
    return client


# -- fixtures ----------------------------------------------------------------


@pytest.fixture
def multi_harness(tmp_path: Path) -> MultiHarness:
    """The host over an empty application data directory."""
    return build_multi_app(tmp_path / "appdata")


@pytest.fixture
def multi_client(multi_harness: MultiHarness) -> Iterator[TestClient]:
    """A caller with no credentials at all: a page on another origin, or a stray process."""
    with TestClient(multi_harness.app) as client:
        yield client


@pytest.fixture
def authenticated_multi_client(multi_harness: MultiHarness) -> Iterator[TestClient]:
    """The researcher's own browser: the app token plus the app's own origin."""
    with TestClient(multi_harness.app) as client:
        yield authenticate(client)


@dataclass(frozen=True)
class TwoProjects:
    """Two registered projects whose only Claim shares an id but not a statement."""

    client: TestClient
    harness: MultiHarness
    left_root: Path
    right_root: Path


@pytest.fixture
def two_projects(
    tmp_path: Path, multi_harness: MultiHarness, authenticated_multi_client: TestClient
) -> TwoProjects:
    """`LEFT` and `RIGHT`, opened through the control plane in that order."""
    left_root = populated_workspace(tmp_path / "left", "left", LEFT_STATEMENT)
    right_root = populated_workspace(tmp_path / "right", "right", RIGHT_STATEMENT)
    for root, project_id in ((left_root, LEFT), (right_root, RIGHT)):
        response = authenticated_multi_client.post("/api/projects/open", json={"path": str(root)})
        assert response.status_code == 200, response.text
        assert response.json()["project_id"] == project_id
    return TwoProjects(
        client=authenticated_multi_client,
        harness=multi_harness,
        left_root=left_root,
        right_root=right_root,
    )


@pytest.fixture
def two_projects_client(two_projects: TwoProjects) -> TestClient:
    """The authenticated client with both projects already registered."""
    return two_projects.client


@pytest.fixture
def left_run_id(two_projects: TwoProjects) -> str:
    """A run that is still running in `LEFT`, recorded durably rather than started."""
    return persist_run(two_projects.left_root)


@pytest.fixture
def spa_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A host that also serves a built bundle, so the SPA fallback can be exercised."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>cockpit</title>", encoding="utf-8")
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))
    harness = build_multi_app(tmp_path / "appdata")
    with TestClient(harness.app) as client:
        yield authenticate(client)

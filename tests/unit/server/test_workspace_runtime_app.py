"""One implementation of the workspace routes, used by the daemon and by a mounted project.

`create_app` is now a thin wrapper: it owns the token file and the built bundle, and takes
its routes from `create_workspace_app`. These tests pin the two properties the multi-project
host depends on - the extracted app publishes exactly the routes the daemon publishes, and
it works as a plain ASGI app mounted under a project prefix, with nothing shared between
two runtimes over two different workspaces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.capabilities.permissions import Principal
from research_harness.local_app.runtime import LEGACY_PROJECT_ID, WorkspaceRuntime
from research_harness.server import bearer_token, create_workspace_app
from research_harness.server.app import (
    WEB_DIST_ENV,
    PrincipalResolver,
    create_app,
)

LEFT = "prj_0000000000000001"
RIGHT = "prj_0000000000000002"


def human_resolver() -> PrincipalResolver:
    """A resolver that answers "the local researcher" whatever the header carries."""

    def resolve(_presented: str | None) -> Principal:
        return Principal.human()

    return resolve


def api_routes(app: Any) -> set[tuple[str, frozenset[str]]]:
    """Every path-and-method the app publishes; a mount (the SPA) has no methods."""
    return {
        (route.path, frozenset(route.methods) - {"HEAD"})
        for route in app.routes
        if getattr(route, "methods", None)
        and not route.path.startswith(("/openapi", "/docs", "/redoc"))
    }


def initialized(root: Path, name: str) -> Path:
    return init_project(InitProjectRequest(root=root, name=name)).root


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """One initialized workspace, the way `tests/contract/protocol/conftest.py` makes one."""
    return initialized(tmp_path / "project", "runtime-parity")


# -- parity with the one-workspace daemon ------------------------------------


def test_runtime_app_and_legacy_app_publish_the_same_workspace_routes(workspace: Path) -> None:
    runtime = WorkspaceRuntime.create(LEFT, workspace)
    legacy = create_app(workspace)
    extracted = create_workspace_app(
        runtime, principal_resolver=human_resolver(), serve_bundle=False
    )
    assert api_routes(extracted) == api_routes(legacy)


def test_the_extracted_app_carries_its_runtime_on_the_app_state(workspace: Path) -> None:
    runtime = WorkspaceRuntime.create(LEFT, workspace)
    resolve = human_resolver()
    app = create_workspace_app(runtime, principal_resolver=resolve, serve_bundle=False)
    assert app.state.workspace_root == workspace
    assert app.state.registry is runtime.catalog
    assert app.state.principal_resolver is resolve
    assert app.state.runtime is runtime


def test_the_legacy_daemon_still_runs_the_reserved_project_id_and_keeps_its_token_path(
    workspace: Path,
) -> None:
    app = create_app(workspace)
    assert app.state.runtime.project_id == LEGACY_PROJECT_ID
    assert app.state.token_path == workspace / ".research" / "daemon-token"


def test_only_the_daemon_serves_the_bundle(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mounted project app must never answer an unknown path with the app shell."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>cockpit</title>", encoding="utf-8")
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))

    runtime = WorkspaceRuntime.create(LEFT, workspace)
    mounted = create_workspace_app(runtime, principal_resolver=human_resolver(), serve_bundle=False)
    assert [route.name for route in mounted.routes] != []
    assert "web" not in {route.name for route in mounted.routes}
    assert "web" in {route.name for route in create_app(workspace).routes}


# -- mounted the way the multi-project dispatcher mounts it -------------------


@pytest.fixture
def dispatched(workspace: Path) -> TestClient:
    """The extracted app under `/api/projects/{project_id}`, as Task 7 will mount it."""
    outer = FastAPI()
    runtime = WorkspaceRuntime.create(LEFT, workspace)
    sub = create_workspace_app(runtime, principal_resolver=human_resolver(), serve_bundle=False)
    outer.mount(f"/api/projects/{LEFT}", sub)
    return TestClient(outer)


def test_a_mounted_project_app_answers_health_under_its_prefix(
    dispatched: TestClient, workspace: Path
) -> None:
    response = dispatched.get(f"/api/projects/{LEFT}/health")
    assert response.status_code == 200
    assert Path(response.json()["workspace"]) == workspace.resolve()


def test_an_unknown_path_under_a_project_is_json_and_never_the_app_shell(
    dispatched: TestClient,
) -> None:
    response = dispatched.get(f"/api/projects/{LEFT}/whatever-unknown")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<html" not in response.text.lower()


def test_two_project_apps_serve_their_own_workspace_and_share_no_mutation_gate(
    tmp_path: Path,
) -> None:
    left = create_workspace_app(
        WorkspaceRuntime.create(LEFT, initialized(tmp_path / "left", "left")),
        principal_resolver=human_resolver(),
        serve_bundle=False,
    )
    right = create_workspace_app(
        WorkspaceRuntime.create(RIGHT, initialized(tmp_path / "right", "right")),
        principal_resolver=human_resolver(),
        serve_bundle=False,
    )
    assert left.state.runtime.mutation_gate is not right.state.runtime.mutation_gate
    assert left.state.workspace_root != right.state.workspace_root

    outer = FastAPI()
    outer.mount(f"/api/projects/{LEFT}", left)
    outer.mount(f"/api/projects/{RIGHT}", right)
    client = TestClient(outer)
    assert client.get(f"/api/projects/{LEFT}/health").json()["project"] == "left"
    assert client.get(f"/api/projects/{RIGHT}/health").json()["project"] == "right"


# -- the header reader both hosts use ----------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc123", "abc123"),
        ("bearer  abc123 ", "abc123"),
        ("Basic abc123", None),
        ("Bearer ", None),
        ("", None),
        (None, None),
    ],
)
def test_bearer_token_reads_only_a_bearer_header(header: str | None, expected: str | None) -> None:
    assert bearer_token(header) == expected

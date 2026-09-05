"""The multi-project host: one authenticated control plane, many isolated workspaces.

Three properties are pinned here. The control plane publishes exactly the routes below and
nothing else, because every one of them accepts a filesystem path or opens a native dialog.
An unauthenticated caller learns nothing - not a project, not a path, not whether one
exists. And a project-scoped request is resolved through the registry alone, so a workspace
route can only ever reach the workspace its opaque id is registered for.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from research_harness import __version__
from research_harness.capabilities.permissions import Principal
from research_harness.local_app.pickers.base import FolderPickerError
from research_harness.local_app.registry import ProjectRegistry
from research_harness.server import create_multi_project_app
from research_harness.server.app import DEV_ENV, create_app, create_workspace_app
from research_harness.server.multi_app import MULTI_PROJECT_KIND
from tests.contract.protocol import multi_fixtures
from tests.contract.protocol.conftest import CLAIM
from tests.contract.protocol.multi_fixtures import (
    APP_PORT,
    APP_TOKEN,
    LEFT,
    LEFT_STATEMENT,
    ORIGIN,
    RIGHT,
    RIGHT_STATEMENT,
    MultiHarness,
    TwoProjects,
    authenticate,
    build_multi_app,
    cancelled,
    populated_workspace,
    selected,
)
from tests.contract.protocol.test_http import EXPECTED_ROUTES

# The shared fixtures, bound here so pytest resolves them by name in this module. They are
# re-bound rather than imported so that a test parameter of the same name does not read as a
# redefinition; Task 13 extends this list rather than copying a fixture.
multi_harness = multi_fixtures.multi_harness
multi_client = multi_fixtures.multi_client
authenticated_multi_client = multi_fixtures.authenticated_multi_client
two_projects = multi_fixtures.two_projects
two_projects_client = multi_fixtures.two_projects_client
left_run_id = multi_fixtures.left_run_id
spa_client = multi_fixtures.spa_client

#: Every control-plane route the host publishes. Asserted whole: each of these accepts a
#: local path, opens a dialog, or hands out a credential, so a new one is a deliberate
#: widening of the app's authority rather than something that appears by accident. The
#: mounted project dispatcher has no methods of its own and so is not listed here.
EXPECTED_CONTROL_ROUTES: set[tuple[str, frozenset[str]]] = {
    ("/api/app/health", frozenset({"GET"})),
    ("/api/app/bootstrap", frozenset({"POST"})),
    ("/api/app/session", frozenset({"POST"})),
    ("/api/projects", frozenset({"GET"})),
    ("/api/projects/create", frozenset({"POST"})),
    ("/api/projects/open", frozenset({"POST"})),
    ("/api/projects/initialize", frozenset({"POST"})),
    ("/api/projects/{project_id}/locate", frozenset({"POST"})),
    ("/api/projects/{project_id}/reveal", frozenset({"POST"})),
    ("/api/projects/{project_id}", frozenset({"PATCH", "DELETE"})),
    ("/api/dialogs/folder", frozenset({"POST"})),
}

DOCUMENTATION_ROUTES = ("/openapi", "/docs", "/redoc")

#: The canonical subtrees a lifecycle operation must never touch. Forget is a registry edit,
#: so every one of these is compared byte for byte across it.
CANONICAL_SUBTREES = ("corpus", "claims", "decisions", "events")


def control_routes(app: Any) -> set[tuple[str, frozenset[str]]]:
    """Every method the host answers at each control-plane path, one entry per path."""
    published: dict[str, set[str]] = {}
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods or route.path.startswith(DOCUMENTATION_ROUTES):
            continue
        published.setdefault(route.path, set()).update(set(methods) - {"HEAD"})
    return {(path, frozenset(methods)) for path, methods in published.items()}


def code_of(response: Any) -> str:
    """The stable error code out of the `{"detail": {"code", "message"}}` envelope."""
    detail = response.json()["detail"]
    assert isinstance(detail, dict), detail
    return str(detail["code"])


def digests(root: Path) -> dict[str, str]:
    """Every file under `root` by relative path and content digest."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- the published surface ---------------------------------------------------


def test_the_control_plane_publishes_exactly_the_expected_routes(
    multi_harness: MultiHarness,
) -> None:
    assert control_routes(multi_harness.app) == EXPECTED_CONTROL_ROUTES


def test_health_answers_without_credentials_and_names_nothing_local(
    multi_client: TestClient, multi_harness: MultiHarness
) -> None:
    response = multi_client.get("/api/app/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "kind": MULTI_PROJECT_KIND, "version": __version__}
    assert str(multi_harness.data_dir) not in response.text


# -- authentication ----------------------------------------------------------


def test_project_paths_are_hidden_without_app_authentication(
    multi_client: TestClient, tmp_path: Path
) -> None:
    response = multi_client.get("/api/projects")
    assert response.status_code == 401
    assert code_of(response) == "control_permission_denied"
    assert "project" not in response.text
    assert str(tmp_path) not in response.text


def test_an_unauthenticated_mutation_never_echoes_the_path_it_was_given(
    multi_client: TestClient, tmp_path: Path
) -> None:
    response = multi_client.post(
        "/api/projects/open", json={"path": str(tmp_path)}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 401
    assert str(tmp_path) not in response.text


def test_cross_origin_control_mutation_is_refused(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    response = authenticated_multi_client.post(
        "/api/projects/open",
        json={"path": str(tmp_path)},
        headers={"Origin": "https://evil.test"},
    )
    assert response.status_code == 403
    assert code_of(response) == "control_permission_denied"


def test_a_mutation_without_any_origin_is_refused(multi_client: TestClient, tmp_path: Path) -> None:
    response = multi_client.post(
        "/api/projects/open",
        json={"path": str(tmp_path)},
        headers={"Authorization": f"Bearer {APP_TOKEN}"},
    )
    assert response.status_code == 403


def test_reads_do_not_need_an_origin_only_the_token(multi_client: TestClient) -> None:
    response = multi_client.get("/api/projects", headers={"Authorization": f"Bearer {APP_TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {"projects": []}


# -- the bootstrap handshake -------------------------------------------------


def test_bootstrap_requires_the_app_token_and_no_browser_origin(
    multi_client: TestClient,
) -> None:
    assert multi_client.post("/api/app/bootstrap").status_code == 401
    issued = multi_client.post(
        "/api/app/bootstrap", headers={"Authorization": f"Bearer {APP_TOKEN}"}
    )
    assert issued.status_code == 200
    assert issued.json()["bootstrap"]
    assert issued.json()["expires_in"] > 0


def test_a_bootstrap_is_exchanged_once_for_the_app_token(multi_client: TestClient) -> None:
    nonce = multi_client.post(
        "/api/app/bootstrap", headers={"Authorization": f"Bearer {APP_TOKEN}"}
    ).json()["bootstrap"]

    exchanged = multi_client.post(
        "/api/app/session", json={"bootstrap": nonce}, headers={"Origin": ORIGIN}
    )
    assert exchanged.status_code == 200
    assert exchanged.json() == {"token": APP_TOKEN}

    replayed = multi_client.post(
        "/api/app/session", json={"bootstrap": nonce}, headers={"Origin": ORIGIN}
    )
    assert replayed.status_code == 401
    assert code_of(replayed) == "control_permission_denied"


def test_an_unknown_bootstrap_is_refused(multi_client: TestClient) -> None:
    response = multi_client.post(
        "/api/app/session", json={"bootstrap": "never-issued"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 401


def test_a_session_exchange_from_another_origin_is_refused(multi_client: TestClient) -> None:
    nonce = multi_client.post(
        "/api/app/bootstrap", headers={"Authorization": f"Bearer {APP_TOKEN}"}
    ).json()["bootstrap"]
    response = multi_client.post(
        "/api/app/session", json={"bootstrap": nonce}, headers={"Origin": "https://evil.test"}
    )
    assert response.status_code == 403
    assert APP_TOKEN not in response.text


# -- lifecycle ---------------------------------------------------------------


def test_create_initializes_a_workspace_in_a_safely_named_child(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    response = authenticated_multi_client.post(
        "/api/projects/create", json={"parent": str(tmp_path), "name": "Độ trễ mạng"}
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["display_name"] == "Độ trễ mạng"
    assert Path(view["path"]) == (tmp_path / "do-tre-mang").resolve()
    assert view["availability"] == "available"
    assert (tmp_path / "do-tre-mang" / "research.yaml").is_file()


def test_open_registers_an_existing_workspace(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    response = authenticated_multi_client.post("/api/projects/open", json={"path": str(root)})
    assert response.status_code == 200
    assert Path(response.json()["path"]) == root
    listed = authenticated_multi_client.get("/api/projects").json()["projects"]
    assert [item["project_id"] for item in listed] == [response.json()["project_id"]]


def test_open_reports_a_plain_folder_as_needing_initialization(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    plain = tmp_path / "notes"
    plain.mkdir()
    response = authenticated_multi_client.post("/api/projects/open", json={"path": str(plain)})
    assert response.status_code == 409
    assert code_of(response) == "project_needs_initialization"


def test_initialize_turns_a_confirmed_plain_folder_into_a_project(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    plain = tmp_path / "notes"
    plain.mkdir()
    response = authenticated_multi_client.post(
        "/api/projects/initialize",
        json={"path": str(plain), "name": "Notes", "policy": "policy_batch"},
    )
    assert response.status_code == 200, response.text
    assert Path(response.json()["path"]) == plain.resolve()
    assert (plain / "research.yaml").is_file()


def test_the_same_root_opened_twice_is_one_project(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    first = authenticated_multi_client.post("/api/projects/open", json={"path": str(root)})
    again = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root / "." / "..") + "/one"}
    )
    assert again.status_code == 200, again.text
    assert again.json()["project_id"] == first.json()["project_id"]
    assert len(authenticated_multi_client.get("/api/projects").json()["projects"]) == 1


def test_rename_changes_only_the_application_label(
    two_projects_client: TestClient, two_projects: TwoProjects
) -> None:
    response = two_projects_client.patch(f"/api/projects/{LEFT}", json={"display_name": "Renamed"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"
    workspace_name = two_projects_client.get(f"/api/projects/{LEFT}/health").json()["project"]
    assert workspace_name == "left"


def test_locate_follows_a_moved_project(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root)}
    ).json()["project_id"]
    moved = tmp_path / "moved"
    shutil.move(str(root), str(moved))

    response = authenticated_multi_client.post(
        f"/api/projects/{project_id}/locate", json={"path": str(moved)}
    )
    assert response.status_code == 200, response.text
    assert Path(response.json()["path"]) == moved.resolve()

    served = authenticated_multi_client.get(f"/api/projects/{project_id}/health")
    assert Path(served.json()["workspace"]) == moved.resolve()


def test_locate_with_an_invalid_root_leaves_the_registry_unchanged(
    authenticated_multi_client: TestClient, multi_harness: MultiHarness, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root)}
    ).json()["project_id"]
    plain = tmp_path / "not-a-workspace"
    plain.mkdir()

    response = authenticated_multi_client.post(
        f"/api/projects/{project_id}/locate", json={"path": str(plain)}
    )
    assert response.status_code == 422
    assert code_of(response) == "project_invalid"
    record = multi_harness.registry.get(project_id)
    assert record is not None
    assert record.canonical_root == root


def test_forget_removes_the_entry_and_leaves_every_file_byte_identical(
    authenticated_multi_client: TestClient, multi_harness: MultiHarness, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root)}
    ).json()["project_id"]
    before = digests(root)

    response = authenticated_multi_client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert multi_harness.registry.get(project_id) is None
    assert authenticated_multi_client.get("/api/projects").json() == {"projects": []}
    assert digests(root) == before
    assert (root / "research.yaml").is_file()


def test_forget_is_refused_while_a_run_is_active(
    two_projects_client: TestClient, left_run_id: str, two_projects: TwoProjects
) -> None:
    assert left_run_id
    response = two_projects_client.delete(f"/api/projects/{LEFT}")
    assert response.status_code == 409
    assert code_of(response) == "project_active_runs"
    assert two_projects.harness.registry.get(LEFT) is not None


def test_reveal_asks_the_platform_to_show_the_registered_root(
    two_projects_client: TestClient, two_projects: TwoProjects
) -> None:
    response = two_projects_client.post(f"/api/projects/{RIGHT}/reveal")
    assert response.status_code == 200
    assert response.json()["project_id"] == RIGHT
    assert two_projects.harness.revealed == [two_projects.right_root]


def test_an_unknown_project_is_a_404_with_a_stable_code(
    authenticated_multi_client: TestClient,
) -> None:
    response = authenticated_multi_client.patch(
        f"/api/projects/{LEFT}", json={"display_name": "Nope"}
    )
    assert response.status_code == 404
    assert code_of(response) == "project_not_found"


def test_control_request_models_are_closed(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    response = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(tmp_path), "workspace": "/etc"}
    )
    assert response.status_code == 422


def test_projects_are_listed_most_recently_opened_first(
    two_projects_client: TestClient,
) -> None:
    listed = two_projects_client.get("/api/projects").json()["projects"]
    assert [item["project_id"] for item in listed] == [RIGHT, LEFT]
    assert {item["availability"] for item in listed} == {"available"}


# -- the folder dialog -------------------------------------------------------


def test_the_folder_dialog_returns_what_the_researcher_chose(
    authenticated_multi_client: TestClient, multi_harness: MultiHarness, tmp_path: Path
) -> None:
    multi_harness.picker.selections.append(selected(tmp_path))
    response = authenticated_multi_client.post(
        "/api/dialogs/folder", json={"title": "Choose a project folder"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "path": str(tmp_path),
        "method": "native",
        "cancelled": False,
        "fallback_required": False,
    }
    assert multi_harness.picker.titles == ["Choose a project folder"]


def test_a_cancelled_dialog_is_a_normal_result(
    authenticated_multi_client: TestClient, multi_harness: MultiHarness
) -> None:
    multi_harness.picker.selections.append(cancelled())
    body = authenticated_multi_client.post("/api/dialogs/folder", json={"title": "Choose"}).json()
    assert body == {
        "path": None,
        "method": "native",
        "cancelled": True,
        "fallback_required": False,
    }


def test_an_unavailable_picker_is_a_503_the_ui_can_fall_back_from(
    authenticated_multi_client: TestClient, multi_harness: MultiHarness
) -> None:
    multi_harness.picker.failure = FolderPickerError("the zenity folder dialog failed")
    response = authenticated_multi_client.post("/api/dialogs/folder", json={"title": "Choose"})
    assert response.status_code == 503
    assert code_of(response) == "picker_unavailable"


def test_the_folder_dialog_needs_the_app_token(multi_client: TestClient) -> None:
    response = multi_client.post(
        "/api/dialogs/folder", json={"title": "Choose"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 401


# -- the project dispatcher --------------------------------------------------


def test_a_project_serves_the_workspace_routes_beneath_its_id(
    two_projects_client: TestClient, two_projects: TwoProjects
) -> None:
    health = two_projects_client.get(f"/api/projects/{LEFT}/health")
    assert health.status_code == 200
    assert Path(health.json()["workspace"]) == two_projects.left_root
    assert health.json()["project"] == "left"

    overview = two_projects_client.get(f"/api/projects/{RIGHT}/overview")
    assert overview.status_code == 200
    assert Path(overview.json()["workspace"]) == two_projects.right_root


def test_the_same_object_id_is_resolved_inside_the_selected_project(
    two_projects_client: TestClient,
) -> None:
    left = two_projects_client.get(f"/api/projects/{LEFT}/objects/{CLAIM}").json()
    right = two_projects_client.get(f"/api/projects/{RIGHT}/objects/{CLAIM}").json()
    assert left["object"]["statement"] == LEFT_STATEMENT
    assert right["object"]["statement"] == RIGHT_STATEMENT


def test_a_run_cannot_be_read_through_another_project(
    two_projects_client: TestClient, left_run_id: str
) -> None:
    assert two_projects_client.get(f"/api/projects/{LEFT}/runs/{left_run_id}").status_code == 200
    assert two_projects_client.get(f"/api/projects/{RIGHT}/runs/{left_run_id}").status_code == 404


@pytest.mark.parametrize(
    "project_id",
    ["%2e%2e", "%2e%2e%2fetc", "..%2f..", "prj_0000000000000001%2f..", "prj_zzzz", "left"],
)
def test_a_project_id_that_is_not_an_opaque_id_is_a_404(
    two_projects_client: TestClient, project_id: str
) -> None:
    response = two_projects_client.get(f"/api/projects/{project_id}/health")
    assert response.status_code == 404
    assert "<html" not in response.text.lower()


def test_an_unregistered_project_is_a_404_that_names_no_path(
    two_projects_client: TestClient, two_projects: TwoProjects
) -> None:
    response = two_projects_client.get("/api/projects/prj_00000000000000ff/health")
    assert response.status_code == 404
    assert code_of(response) == "project_not_found"
    assert str(two_projects.left_root) not in response.text


def test_a_project_whose_folder_disappeared_is_a_422_that_names_no_path(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root)}
    ).json()["project_id"]
    shutil.move(str(root), str(tmp_path / "elsewhere"))

    response = authenticated_multi_client.get(f"/api/projects/{project_id}/health")
    assert response.status_code == 422
    assert code_of(response) == "project_invalid"
    assert str(root) not in response.text
    assert str(tmp_path) not in response.text


def test_an_unknown_path_under_a_project_is_json_and_never_the_app_shell(
    two_projects_client: TestClient,
) -> None:
    response = two_projects_client.get(f"/api/projects/{LEFT}/not-an-api-route")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<html" not in response.text.lower()


def test_a_trailing_slash_redirects_inside_the_project_prefix(
    two_projects_client: TestClient,
) -> None:
    response = two_projects_client.get(f"/api/projects/{LEFT}/overview/", follow_redirects=False)
    assert response.status_code in {307, 308}
    assert response.headers["location"].endswith(f"/api/projects/{LEFT}/overview")


def test_the_exact_control_routes_win_over_the_dispatcher(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    """`create`, `open`, and `initialize` are control routes, not project ids."""
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    assert (
        authenticated_multi_client.post("/api/projects/open", json={"path": str(root)}).status_code
        == 200
    )
    assert authenticated_multi_client.post("/api/projects/create", json={}).status_code == 422
    assert authenticated_multi_client.post("/api/projects/initialize", json={}).status_code == 422


def test_a_relocated_project_is_dispatched_to_its_new_root(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root)}
    ).json()["project_id"]
    assert authenticated_multi_client.get(f"/api/projects/{project_id}/health").status_code == 200

    moved = tmp_path / "moved"
    shutil.move(str(root), str(moved))
    authenticated_multi_client.post(f"/api/projects/{project_id}/locate", json={"path": str(moved)})

    served = authenticated_multi_client.get(f"/api/projects/{project_id}/objects/{CLAIM}")
    assert served.status_code == 200
    assert served.json()["object"]["statement"] == "a claim"


def test_a_forgotten_project_stops_being_dispatched(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root)}
    ).json()["project_id"]
    assert authenticated_multi_client.get(f"/api/projects/{project_id}/health").status_code == 200

    assert authenticated_multi_client.delete(f"/api/projects/{project_id}").status_code == 204
    gone = authenticated_multi_client.get(f"/api/projects/{project_id}/health")
    assert gone.status_code == 404
    assert code_of(gone) == "project_not_found"


def test_a_workspace_route_still_answers_an_agent_host_without_the_app_token(
    multi_client: TestClient, two_projects: TwoProjects
) -> None:
    """Below the project prefix the legacy authority model is unchanged: read and stage."""
    assert multi_client.get(f"/api/projects/{LEFT}/health").status_code == 200
    refused = multi_client.post(f"/api/projects/{LEFT}/capabilities/note.add", json={"text": "x"})
    assert refused.status_code == 403


# -- the single-page app -----------------------------------------------------


def test_a_project_deep_link_renders_the_app_shell(spa_client: TestClient) -> None:
    response = spa_client.get(f"/projects/{LEFT}/overview")
    assert response.status_code == 200
    assert "cockpit" in response.text


def test_the_project_api_never_answers_with_the_app_shell(
    spa_client: TestClient, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = spa_client.post("/api/projects/open", json={"path": str(root)}).json()[
        "project_id"
    ]
    response = spa_client.get(f"/api/projects/{project_id}/not-an-api-route")
    assert response.status_code == 404
    assert "cockpit" not in response.text
    assert response.headers["content-type"].startswith("application/json")


# -- the default wiring ------------------------------------------------------


def test_the_default_wiring_persists_a_token_and_serves_a_project(tmp_path: Path) -> None:
    """Everything the CLI does not pass is built here, and nothing opens a workspace."""
    data_dir = tmp_path / "appdata"
    app = create_multi_project_app(data_dir, port=APP_PORT)
    assert app.state.data_dir == data_dir
    assert app.state.app_port == APP_PORT
    assert (data_dir / "app-token").read_text(encoding="utf-8").strip() == app.state.app_token

    root = populated_workspace(tmp_path / "one", "one", "a claim")
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.app_token}"
        client.headers["Origin"] = ORIGIN
        opened = client.post("/api/projects/open", json={"path": str(root)})
        assert opened.status_code == 200, opened.text
        project_id = opened.json()["project_id"]
        assert client.get(f"/api/projects/{project_id}/health").status_code == 200
        assert app.state.pool.status(project_id).loaded is True


def test_health_opens_no_workspace_even_when_a_registered_folder_is_gone(
    authenticated_multi_client: TestClient, multi_client: TestClient, tmp_path: Path
) -> None:
    """Project Home must load on a laptop whose external drive is not plugged in."""
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    opened = authenticated_multi_client.post("/api/projects/open", json={"path": str(root)})
    assert opened.status_code == 200
    shutil.rmtree(root)

    response = multi_client.get("/api/app/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_development_mode_lets_the_dev_server_drive_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pnpm dev` runs the cockpit on another loopback port; nothing remote is ever allowed."""
    monkeypatch.setenv(DEV_ENV, "1")
    harness = build_multi_app(tmp_path / "appdata")
    assert any(middleware.cls is CORSMiddleware for middleware in harness.app.user_middleware)

    root = populated_workspace(tmp_path / "one", "one", "a claim")
    with TestClient(harness.app) as client:
        authenticate(client)
        allowed = client.post(
            "/api/projects/open",
            json={"path": str(root)},
            headers={"Origin": "http://localhost:5173"},
        )
        assert allowed.status_code == 200
        refused = client.post(
            "/api/projects/open",
            json={"path": str(root)},
            headers={"Origin": "https://research.example.com"},
        )
        assert refused.status_code == 403


# -- cross-project safety ----------------------------------------------------


def canonical_digests(root: Path) -> dict[str, str]:
    """`research.yaml` and every file under the canonical subtrees, by digest."""
    listed = {"research.yaml": hashlib.sha256((root / "research.yaml").read_bytes()).hexdigest()}
    for name in CANONICAL_SUBTREES:
        directory = root / name
        assert directory.is_dir(), f"{name}/ is missing"
        listed.update(
            {
                path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            }
        )
    return listed


def test_the_project_list_is_hidden_from_an_unauthenticated_caller_that_projects_exist_for(
    multi_client: TestClient, two_projects: TwoProjects
) -> None:
    """Not the paths, not the ids, not the names: an unauthenticated caller learns nothing."""
    response = multi_client.get("/api/projects")
    assert response.status_code == 401
    assert code_of(response) == "control_permission_denied"
    for secret in (
        str(two_projects.left_root),
        str(two_projects.right_root),
        str(two_projects.left_root.parent),
        LEFT,
        RIGHT,
        "left",
        "right",
    ):
        assert secret not in response.text


@pytest.mark.parametrize("root_field", ["workspace", "root", "workspace_root"])
def test_a_project_scoped_capability_cannot_be_pointed_at_another_root(
    two_projects_client: TestClient, two_projects: TwoProjects, root_field: str
) -> None:
    """A capability takes no root: the only thing that selects a workspace is the opaque id."""
    before = digests(two_projects.right_root)
    response = two_projects_client.post(
        f"/api/projects/{LEFT}/capabilities/note.add",
        json={"text": "a note", root_field: str(two_projects.right_root)},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_request"
    assert RIGHT_STATEMENT not in response.text
    assert digests(two_projects.right_root) == before


@pytest.mark.parametrize(
    "suffix",
    [
        "objects/..",
        "objects/%2e%2e",
        "objects/%2e%2e%2f%2e%2e%2fclaims%2fC0001.yaml",
        "artifacts/..%2f..%2f..%2fetc%2fpasswd/bytes",
        "artifacts/%2e%2e%2f%2e%2e%2fresearch.yaml/bytes",
        f"%2e%2e/{RIGHT}/objects/{CLAIM}",
        f"..%2f{RIGHT}/objects/{CLAIM}",
    ],
)
def test_a_traversal_beneath_a_project_is_a_404_that_is_never_html(
    two_projects_client: TestClient, suffix: str
) -> None:
    response = two_projects_client.get(f"/api/projects/{LEFT}/{suffix}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<html" not in response.text.lower()
    assert RIGHT_STATEMENT not in response.text
    assert LEFT_STATEMENT not in response.text


def test_the_same_canonical_root_spelled_differently_is_always_one_project(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    """Identity is the resolved directory, never the syntax the researcher typed."""
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    first = authenticated_multi_client.post("/api/projects/open", json={"path": str(root)})
    assert first.status_code == 200, first.text
    project_id = first.json()["project_id"]

    spellings = [str(root) + "/", str(root / "."), str(tmp_path / "." / "one" / ".")]
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:  # pragma: no cover - Windows without the symlink privilege
        pass
    else:
        spellings.append(str(alias))

    for spelling in spellings:
        again = authenticated_multi_client.post("/api/projects/open", json={"path": spelling})
        assert again.status_code == 200, f"{spelling}: {again.text}"
        assert again.json()["project_id"] == project_id
        assert Path(again.json()["path"]) == root

    assert len(authenticated_multi_client.get("/api/projects").json()["projects"]) == 1


def test_locate_to_a_missing_folder_leaves_the_registry_file_byte_identical(
    authenticated_multi_client: TestClient, multi_harness: MultiHarness, tmp_path: Path
) -> None:
    root = populated_workspace(tmp_path / "one", "one", "a claim")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(root)}
    ).json()["project_id"]
    before = multi_harness.registry.path.read_bytes()

    response = authenticated_multi_client.post(
        f"/api/projects/{project_id}/locate", json={"path": str(tmp_path / "never-existed")}
    )
    assert response.status_code == 422
    assert code_of(response) == "project_invalid"
    assert multi_harness.registry.path.read_bytes() == before

    reread = ProjectRegistry(multi_harness.registry.path).get(project_id)
    assert reread is not None
    assert reread.canonical_root == root
    assert authenticated_multi_client.get(f"/api/projects/{project_id}/health").status_code == 200


def test_forget_leaves_the_canonical_subtrees_of_a_served_project_byte_identical(
    two_projects_client: TestClient, two_projects: TwoProjects
) -> None:
    """Forget is a registry edit. Even a project whose runtime is open loses no byte."""
    assert two_projects_client.get(f"/api/projects/{LEFT}/objects/{CLAIM}").status_code == 200
    assert two_projects.harness.pool.status(LEFT).loaded is True
    before = canonical_digests(two_projects.left_root)
    assert "claims/C0001.yaml" in before
    assert "events/research.jsonl" in before

    assert two_projects_client.delete(f"/api/projects/{LEFT}").status_code == 204
    assert two_projects.harness.registry.get(LEFT) is None
    assert canonical_digests(two_projects.left_root) == before
    assert two_projects.left_root.is_dir()


def test_locate_serves_the_new_root_even_when_the_old_one_still_exists(
    authenticated_multi_client: TestClient, tmp_path: Path
) -> None:
    """The cached sub-application is bound to a runtime, not to a project id."""
    first_home = populated_workspace(tmp_path / "first", "one", "first home")
    second_home = populated_workspace(tmp_path / "second", "one", "second home")
    project_id = authenticated_multi_client.post(
        "/api/projects/open", json={"path": str(first_home)}
    ).json()["project_id"]
    served = authenticated_multi_client.get(f"/api/projects/{project_id}/objects/{CLAIM}")
    assert served.json()["object"]["statement"] == "first home"

    moved = authenticated_multi_client.post(
        f"/api/projects/{project_id}/locate", json={"path": str(second_home)}
    )
    assert moved.status_code == 200, moved.text

    served = authenticated_multi_client.get(f"/api/projects/{project_id}/objects/{CLAIM}")
    assert served.json()["object"]["statement"] == "second home"
    assert (first_home / "claims" / "C0001.yaml").is_file()


def test_a_mounted_project_publishes_exactly_the_one_workspace_route_contract(
    two_projects: TwoProjects,
) -> None:
    """There is one implementation of the workspace routes, so the two hosts cannot drift."""
    runtime = two_projects.harness.pool.get(LEFT)
    mounted = create_workspace_app(
        runtime, principal_resolver=lambda _presented: Principal.human(), serve_bundle=False
    )
    assert control_routes(mounted) == EXPECTED_ROUTES
    assert control_routes(create_app(two_projects.right_root)) == EXPECTED_ROUTES

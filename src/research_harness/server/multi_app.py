"""The multi-project host: one authenticated control plane in front of many workspaces.

`research app` serves several local projects from one loopback process. Two surfaces meet
here and stay separated:

* the **control plane** (`/api/app/...`, `/api/projects`, `/api/dialogs/folder`) is
  application state - which folders the researcher has approved. Every route on it demands
  the app token, and every mutation additionally demands the app's own `Origin`, because
  these are the only routes that accept a filesystem path or open a native dialog
  (design §8.1). An unauthenticated caller learns nothing: not a path, not a project, not
  whether either exists.
* the **project plane** (`/api/projects/{project_id}/...`) is the existing workspace API,
  unchanged. :class:`ProjectDispatcher` resolves the opaque id through the registry and
  hands the request to :func:`~research_harness.server.app.create_workspace_app` over that
  project's runtime. There is one implementation of those routes, so the one-workspace
  daemon and a mounted project cannot drift, and no capability request can name a root.

Nothing here writes canonical state, and nothing here widens a principal: a caller with the
app token is the local researcher, and a caller without it is the read-and-stage agent host
the daemon already knows (design §8.2).
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from research_harness import __version__
from research_harness.domain.enums import ReviewPolicy
from research_harness.domain.errors import ResearchHarnessError

# `local_app.auth` imports this package's `app` module, so it is imported as a module here:
# binding the module survives the import cycle, and every use below happens at call time.
from research_harness.local_app import auth as app_auth
from research_harness.local_app.manager import ProjectManager
from research_harness.local_app.models import (
    PROJECT_ID_PATTERN,
    ProjectActiveRunsError,
    ProjectLifecycleError,
    ProjectNeedsInitializationError,
    ProjectNotFoundError,
    ProjectView,
)
from research_harness.local_app.paths import ProjectPathError, registry_path
from research_harness.local_app.pickers import FolderPicker, FolderPickerError, folder_picker
from research_harness.local_app.pickers.base import FolderSelection
from research_harness.local_app.registry import ProjectRegistry, ProjectRegistryError
from research_harness.local_app.runtime import ProjectRuntimePool, WorkspaceRuntime
from research_harness.server.app import (
    PrincipalResolver,
    _allow_dev_origins,
    _serve_bundle,
    create_workspace_app,
)

__all__ = [
    "DEFAULT_APP_PORT",
    "MULTI_PROJECT_KIND",
    "PICKER_UNAVAILABLE",
    "PROJECT_ACTIVE_RUNS",
    "PROJECT_INVALID",
    "PROJECT_NEEDS_INITIALIZATION",
    "PROJECT_NOT_FOUND",
    "AppHealth",
    "CreateProjectBody",
    "FolderDialogBody",
    "InitializeProjectBody",
    "LocateProjectBody",
    "OpenProjectBody",
    "ProjectDispatcher",
    "ProjectList",
    "RenameProjectBody",
    "create_multi_project_app",
]

logger = logging.getLogger(__name__)

DEFAULT_APP_PORT = 8765
"""The loopback port `research app` uses unless the researcher names another one."""

MULTI_PROJECT_KIND: Literal["multi_project"] = "multi_project"
"""What `/api/app/health` calls itself, so a client can tell the two hosts apart."""

PROJECT_NOT_FOUND = "project_not_found"
PROJECT_NEEDS_INITIALIZATION = "project_needs_initialization"
PROJECT_ACTIVE_RUNS = "project_active_runs"
PROJECT_INVALID = "project_invalid"
PICKER_UNAVAILABLE = "picker_unavailable"

_PROJECT_ID = re.compile(PROJECT_ID_PATTERN)
"""An id is `prj_` and sixteen hex digits; nothing else reaches a workspace."""

_UNSAFE_SEGMENT = ("..", "%2e", "%2E", "/", "\\", "%2f", "%2F", "%5c", "%5C")
"""Rejected before the pattern is even consulted, so traversal fails for a nameable reason."""

#: How a refused lifecycle call is rendered. The order is the subclass order: a project that
#: needs initializing is a lifecycle error too, and must not be flattened into one.
_REFUSALS: tuple[tuple[type[Exception], str, int], ...] = (
    (ProjectNotFoundError, PROJECT_NOT_FOUND, 404),
    (ProjectNeedsInitializationError, PROJECT_NEEDS_INITIALIZATION, 409),
    (ProjectActiveRunsError, PROJECT_ACTIVE_RUNS, 409),
    (ProjectLifecycleError, PROJECT_INVALID, 422),
    (ProjectPathError, PROJECT_INVALID, 422),
    (ProjectRegistryError, PROJECT_INVALID, 422),
)


# -- control-plane bodies ----------------------------------------------------


class AppHealth(BaseModel):
    """Which host answered. Unauthenticated, and deliberately free of local detail."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool = True
    kind: Literal["multi_project"] = MULTI_PROJECT_KIND
    version: str


class ProjectList(BaseModel):
    """Project Home's whole payload: the registry with freshly derived availability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projects: tuple[ProjectView, ...] = ()


class CreateProjectBody(BaseModel):
    """Initialize a new workspace in a safely named child of a folder the researcher chose."""

    model_config = ConfigDict(extra="forbid")

    parent: Path
    name: str = Field(min_length=1, max_length=120)
    policy: ReviewPolicy = ReviewPolicy.STRICT


class OpenProjectBody(BaseModel):
    """Register a folder that is already a workspace."""

    model_config = ConfigDict(extra="forbid")

    path: Path


class InitializeProjectBody(BaseModel):
    """Turn an ordinary folder into a workspace, only after the researcher confirmed it."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    name: str = Field(min_length=1, max_length=120)
    policy: ReviewPolicy = ReviewPolicy.STRICT


class LocateProjectBody(BaseModel):
    """Point an existing registry entry at the folder the project was moved to."""

    model_config = ConfigDict(extra="forbid")

    path: Path


class RenameProjectBody(BaseModel):
    """Change the application label only; the workspace's own name is scientific state."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)


class FolderDialogBody(BaseModel):
    """What to put in the title bar of the native dialog. No path is accepted here."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


# -- the host ----------------------------------------------------------------


def create_multi_project_app(
    data_dir: Path,
    *,
    port: int = DEFAULT_APP_PORT,
    manager: ProjectManager | None = None,
    pool: ProjectRuntimePool | None = None,
    picker: FolderPicker | None = None,
    registry: ProjectRegistry | None = None,
    bootstraps: app_auth.BootstrapStore | None = None,
    token: str | None = None,
) -> FastAPI:
    """The `research app` host over one application data directory.

    Everything the launcher does not supply is built here, and none of it opens a workspace:
    starting the app must stay cheap and must not fail because one registered folder was
    unplugged. Runtimes are created lazily, per project, on the first request that needs one.
    """
    directory = Path(data_dir)
    store = registry if registry is not None else ProjectRegistry(registry_path(directory))
    app_token = token if token is not None else app_auth.ensure_app_token(directory)
    runtimes = pool if pool is not None else ProjectRuntimePool(store)
    dispatcher = ProjectDispatcher(runtimes, app_auth.app_principal_resolver(app_token))

    def forget_runtime(project_id: str) -> None:
        """A moved or forgotten project must never be served from its previous root."""
        runtimes.evict(project_id)
        dispatcher.evict(project_id)

    projects = (
        manager
        if manager is not None
        else ProjectManager(
            store, active_runs=runtimes.active_run_ids, on_root_changed=forget_runtime
        )
    )
    dialogs = picker if picker is not None else folder_picker()
    nonces = bootstraps if bootstraps is not None else app_auth.BootstrapStore()

    app = FastAPI(
        title="Research Harness app",
        version=__version__,
        summary="Local projects, and the existing workspace API beneath each of them.",
    )
    app.state.app_token = app_token
    app.state.app_port = port
    app.state.data_dir = directory
    app.state.manager = projects
    app.state.pool = runtimes
    app.state.bootstraps = nonces

    authenticated = [Depends(app_auth.require_app_token)]
    mutation = [Depends(app_auth.require_control_mutation)]

    # -- who answered, and how the browser is let in --------------------------

    @app.get("/api/app/health", response_model=AppHealth)
    def app_health() -> AppHealth:
        """Which host this is. No credential, no path, and no workspace is opened."""
        return AppHealth(ok=True, kind=MULTI_PROJECT_KIND, version=__version__)

    @app.post(
        "/api/app/bootstrap", response_model=app_auth.BootstrapIssued, dependencies=authenticated
    )
    def issue_bootstrap() -> app_auth.BootstrapIssued:
        """Mint the one-time nonce the launcher puts in the browser's URL (design §8.1).

        This is the CLI's route: it takes the app token and no browser credential, so a page
        cannot mint itself a fresh launch nonce.
        """
        return app_auth.BootstrapIssued(bootstrap=nonces.issue(), expires_in=nonces.ttl_seconds)

    @app.post(
        "/api/app/session",
        response_model=app_auth.SessionIssued,
        dependencies=[Depends(app_auth.require_same_origin)],
    )
    def exchange_session(body: app_auth.SessionExchange) -> app_auth.SessionIssued:
        """Trade a nonce from the launch URL for the app token, exactly once."""
        if not nonces.exchange(body.bootstrap):
            raise HTTPException(
                status_code=401,
                detail={
                    "code": app_auth.PERMISSION_DENIED,
                    "message": "this launch link has already been used or has expired",
                },
            )
        return app_auth.SessionIssued(token=app_token)

    # -- the registry ---------------------------------------------------------

    @app.get("/api/projects", response_model=ProjectList, dependencies=authenticated)
    def list_projects() -> ProjectList:
        """Every registered project, most recently opened first, with derived availability."""
        return ProjectList(projects=_lifecycle(projects.list_projects))

    @app.post("/api/projects/create", response_model=ProjectView, dependencies=mutation)
    def create_project(body: CreateProjectBody) -> ProjectView:
        """Initialize a workspace in a new child of a folder the researcher selected."""
        return _lifecycle(lambda: projects.create(body.parent, body.name, body.policy))

    @app.post("/api/projects/open", response_model=ProjectView, dependencies=mutation)
    def open_project(body: OpenProjectBody) -> ProjectView:
        """Register an existing workspace. A plain folder is reported, never initialized."""
        return _lifecycle(lambda: projects.open(body.path))

    @app.post("/api/projects/initialize", response_model=ProjectView, dependencies=mutation)
    def initialize_project(body: InitializeProjectBody) -> ProjectView:
        """Initialize a confirmed ordinary folder, then register it."""
        return _lifecycle(lambda: projects.initialize(body.path, body.name, body.policy))

    @app.post(
        "/api/projects/{project_id}/locate", response_model=ProjectView, dependencies=mutation
    )
    def locate_project(project_id: str, body: LocateProjectBody) -> ProjectView:
        """Follow a project that moved, keeping its identity and its history."""
        return _lifecycle(lambda: projects.locate(project_id, body.path))

    @app.post(
        "/api/projects/{project_id}/reveal", response_model=ProjectView, dependencies=mutation
    )
    def reveal_project(project_id: str) -> ProjectView:
        """Show the registered root in the platform file manager. Takes no path."""

        def show() -> ProjectView:
            projects.reveal(project_id)
            return projects.get(project_id)

        return _lifecycle(show)

    @app.patch("/api/projects/{project_id}", response_model=ProjectView, dependencies=mutation)
    def rename_project(project_id: str, body: RenameProjectBody) -> ProjectView:
        """Rename the entry in this app. `research.yaml` is not touched."""
        return _lifecycle(lambda: projects.rename(project_id, body.display_name))

    @app.delete("/api/projects/{project_id}", status_code=204, dependencies=mutation)
    def forget_project(project_id: str) -> Response:
        """Drop the registry entry. Every file under the project root stays as it is."""
        _lifecycle(lambda: projects.forget(project_id))
        forget_runtime(project_id)
        return Response(status_code=204)

    @app.post("/api/dialogs/folder", response_model=FolderSelection, dependencies=mutation)
    def choose_folder(body: FolderDialogBody) -> FolderSelection:
        """Run the platform folder dialog. Cancellation is a result, not an error."""
        try:
            return dialogs.select_folder(body.title)
        except FolderPickerError as exc:
            raise HTTPException(
                status_code=503, detail={"code": PICKER_UNAVAILABLE, "message": str(exc)}
            ) from exc

    # The dispatcher is registered last so that every exact control route above wins: a
    # mount matches any path beneath it, and `create` is a route, not a project id.
    app.mount("/api/projects", dispatcher, name="project-workspaces")
    _serve_bundle(app)
    _allow_dev_origins(app)
    return app


# -- the project dispatcher --------------------------------------------------


class ProjectDispatcher:
    """Routes `/api/projects/{project_id}/...` to that project's workspace application.

    The id is opaque and is resolved through the registry on every request, so a relocated
    or broken project can never be served from a stale root, and a request can never name a
    workspace directly. The sub-application is cached per project *and* per runtime: when
    the pool rebuilds a runtime (the project moved, or it was evicted), the cached app is
    rebuilt with it rather than kept alive over the previous root.
    """

    def __init__(self, pool: ProjectRuntimePool, principal_resolver: PrincipalResolver) -> None:
        self._pool = pool
        self._resolve = principal_resolver
        self._lock = threading.Lock()
        self._apps: dict[str, tuple[WorkspaceRuntime, FastAPI]] = {}

    def evict(self, project_id: str) -> None:
        """Drop the cached application. Rebuilding it costs one request and nothing durable."""
        with self._lock:
            self._apps.pop(project_id, None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Resolve the first path segment as a project, then serve the rest from its app."""
        project_id, _ = _split_project(_route_path(scope))
        if not _is_project_id(project_id):
            await self._refuse(scope, receive, send, 404, PROJECT_NOT_FOUND, "no such project")
            return
        try:
            runtime = self._pool.get(project_id)
        except ProjectNotFoundError:
            await self._refuse(scope, receive, send, 404, PROJECT_NOT_FOUND, "no such project")
            return
        except (ResearchHarnessError, OSError) as exc:
            # The message is fixed: a caller below the project prefix is not necessarily the
            # researcher, and a workspace error names the root it failed to open.
            logger.info("project %s cannot be served: %s", project_id, exc)
            await self._refuse(
                scope,
                receive,
                send,
                422,
                PROJECT_INVALID,
                "this project cannot be opened right now",
            )
            return
        await self._app_for(project_id, runtime)(_child_scope(scope, project_id), receive, send)

    def _app_for(self, project_id: str, runtime: WorkspaceRuntime) -> FastAPI:
        with self._lock:
            cached = self._apps.get(project_id)
            if cached is not None and cached[0] is runtime:
                return cached[1]
            app = create_workspace_app(
                runtime, principal_resolver=self._resolve, serve_bundle=False
            )
            self._apps[project_id] = (runtime, app)
            return app

    @staticmethod
    async def _refuse(
        scope: Scope, receive: Receive, send: Send, status: int, code: str, message: str
    ) -> None:
        if scope["type"] != "http":  # pragma: no cover - no websocket route exists yet
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)
        await response(scope, receive, send)


def _route_path(scope: Scope) -> str:
    """The part of the path this mount was reached by, whichever way the server spells it.

    Starlette keeps the whole path in the scope and grows `root_path` as mounts match, so
    the remainder is the tail after the prefix; a server that strips the path instead leaves
    the two equal and the same expression still holds.
    """
    path: str = scope.get("path", "")
    root: str = scope.get("root_path", "")
    if root and path.startswith(root):
        return path[len(root) :]
    return path


def _split_project(route_path: str) -> tuple[str, str]:
    """The first segment and the remainder: `/prj_.../overview` -> `prj_...`, `/overview`."""
    segment, _, rest = route_path.lstrip("/").partition("/")
    return segment, f"/{rest}"


def _child_scope(scope: Scope, project_id: str) -> Scope:
    """The scope the project's application sees: the project prefix moved into `root_path`.

    Only `root_path` changes, which is how this Starlette expresses "strip this prefix": the
    sub-application derives `/overview` from it, while the full path stays in the scope so a
    redirect it issues still points inside `/api/projects/{project_id}`.
    """
    child = dict(scope)
    child["root_path"] = f"{scope.get('root_path', '')}/{project_id}"
    return child


def _is_project_id(segment: str) -> bool:
    """Only an opaque registry id may address a workspace; traversal never gets that far."""
    if not segment or any(unsafe in segment for unsafe in _UNSAFE_SEGMENT):
        return False
    return _PROJECT_ID.fullmatch(segment) is not None


# -- refusals ----------------------------------------------------------------


def _lifecycle[T](call: Callable[[], T]) -> T:
    """Run one lifecycle operation, rendering every refusal as the stable error envelope."""
    try:
        return call()
    except (ResearchHarnessError, OSError) as exc:
        raise _refused(exc) from exc


def _refused(exc: Exception) -> HTTPException:
    """The status and stable code for a refusal the control plane is allowed to explain.

    The message is the service's own, path and all: every route that can raise one of these
    has already proved the caller is the local researcher, who selected that path.
    """
    for kind, code, status in _REFUSALS:
        if isinstance(exc, kind):
            return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})
    return HTTPException(status_code=422, detail={"code": PROJECT_INVALID, "message": str(exc)})

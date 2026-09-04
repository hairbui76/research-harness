"""`research app`: start (or join) the multi-project local application.

This is the one command that is not about a workspace. It never resolves `research.yaml`,
never reads the current directory, and takes no `--workspace`: the application manages
projects internally through the app registry, so it must start from anywhere (design
§4.1, §12).

Two things follow from that, and they are the whole module:

* **One instance per port.** If a compatible app is already listening, the command asks it
  for a launch nonce and opens *that* instance rather than racing a second server onto the
  same port. Anything else listening there is an error naming `--port`, never a process to
  drive blindly.
* **No durable secret in a URL.** The launch URL carries a short-lived, single-use
  bootstrap nonce; the persisted app token never leaves the process, the terminal, or the
  app data directory (design §8.1).
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import quote

import httpx
import typer

from research_harness.cli.commands.serve import DEFAULT_PORT, LOOPBACK
from research_harness.cli.context import cli_errors
from research_harness.domain.errors import ResearchHarnessError

if TYPE_CHECKING:  # pragma: no cover - typing only; the server imports lazily
    from fastapi import FastAPI

    from research_harness.local_app.auth import BootstrapStore

__all__ = [
    "AppLaunchError",
    "PortOccupiedError",
    "app_command",
    "app_url",
    "probe_existing_app",
    "register",
    "request_bootstrap",
]

APP_KIND = "multi_project"
"""What `GET /api/app/health` calls itself. Only this answer is an app we may join."""

HEALTH_PATH = "/api/app/health"
BOOTSTRAP_PATH = "/api/app/bootstrap"

PROBE_TIMEOUT_SECONDS = 0.5
"""A loopback round trip is sub-millisecond; half a second is already generous."""

BROWSER_DELAY_SECONDS = 0.5
"""How long the browser waits for uvicorn to bind before it asks for the page."""


class AppLaunchError(ResearchHarnessError):
    """`research app` cannot start or join an application on the requested port."""


class PortOccupiedError(AppLaunchError):
    """Something is listening on the app port, and it is not a Research Harness app."""


def register(app: typer.Typer) -> None:
    """Add `research app`."""
    app.command("app")(app_command)


def app_command(
    port: Annotated[
        int, typer.Option("--port", help="Loopback port the application listens on.")
    ] = DEFAULT_PORT,
    no_open: Annotated[
        bool, typer.Option("--no-open", help="Do not launch a browser; print the URL instead.")
    ] = False,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Application data directory (advanced; defaults to the platform location).",
            hidden=True,
            show_default=False,
        ),
    ] = None,
) -> None:
    """Open the multi-project application in a browser, starting it if it is not running.

    Independent of the current directory: the app manages projects through its own
    registry, so this command reads no research.yaml and takes no --workspace. It
    binds loopback only, and the URL it opens carries a one-time nonce, never the
    app token. `research serve -w <workspace>` is unchanged.
    """
    with cli_errors():
        from research_harness.local_app.auth import BootstrapStore, ensure_app_token
        from research_harness.local_app.paths import app_data_dir

        directory = app_data_dir() if data_dir is None else Path(data_dir)
        token = ensure_app_token(directory)

        if probe_existing_app(port):
            bootstrap = request_bootstrap(port, token)
            url = app_url(port, bootstrap)
            typer.echo(f"research app already on http://{LOOPBACK}:{port}")
            typer.echo(f"open  {url}")
            if not no_open:
                _open_browser(url)
            return

        bootstraps = BootstrapStore()
        bootstrap = bootstraps.issue()
        application = _create_app(directory, port=port, bootstraps=bootstraps)
        url = app_url(port, bootstrap)
        typer.echo(f"research app on http://{LOOPBACK}:{port}")
        typer.echo(f"app data  {directory}")
        typer.echo(f"open  {url}")
        if not no_open:
            _schedule_browser(url)
        _run_server(application, port=port)


# -- the launch URL ----------------------------------------------------------


def app_url(port: int, bootstrap: str) -> str:
    """The local URL to open: loopback, this port, and a one-time nonce.

    The nonce is what the browser exchanges for a session-scoped token. The persisted app
    token is never put in a URL, because a URL reaches shell history, browser history, and
    every referrer (design §8.1).
    """
    return f"http://{LOOPBACK}:{port}/?bootstrap={quote(bootstrap, safe='')}"


# -- is something already there, and is it us? -------------------------------


def probe_existing_app(
    port: int,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    """Whether a compatible app already answers on `port`.

    Three outcomes, and the difference matters: nothing listening is `False` (start one),
    a Research Harness app is `True` (join it), and anything else raises rather than being
    driven or displaced. A legacy `research serve` daemon answers this path with a 404 or
    with HTML, which is exactly the case that must not silently become "start another one".
    """
    url = f"http://{LOOPBACK}:{port}{HEALTH_PATH}"
    try:
        with httpx.Client(transport=transport, timeout=timeout, trust_env=False) as client:
            response = client.get(url)
    except httpx.ConnectError:
        return False
    except httpx.TransportError as exc:
        raise PortOccupiedError(
            f"something is listening on port {port} but did not answer {HEALTH_PATH} ({exc}); "
            f"stop it or run `research app --port <other port>`"
        ) from exc
    if response.status_code == 200 and _health_is_app(response):
        return True
    raise PortOccupiedError(
        f"port {port} is in use by something that is not a Research Harness app "
        f"(HTTP {response.status_code} from {HEALTH_PATH}); stop it, or run "
        f"`research app --port <other port>`. A one-workspace `research serve` daemon "
        f"answers like this."
    )


def _health_is_app(response: httpx.Response) -> bool:
    """True only for `{ok: true, kind: "multi_project", ...}`; any other body is not us."""
    try:
        payload = response.json()
    except ValueError:
        return False
    return (
        isinstance(payload, dict) and payload.get("ok") is True and payload.get("kind") == APP_KIND
    )


# -- joining the instance that is already running ----------------------------


def request_bootstrap(
    port: int,
    token: str,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Ask the running app for a one-time launch nonce, on the authority of the app token.

    Only a process that can read the app token file can do this, which is what keeps a page
    on another origin from minting itself a session.
    """
    url = f"http://{LOOPBACK}:{port}{BOOTSTRAP_PATH}"
    try:
        with httpx.Client(transport=transport, timeout=timeout, trust_env=False) as client:
            response = client.post(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.TransportError as exc:
        raise AppLaunchError(
            f"the app on port {port} stopped answering while starting a session ({exc})"
        ) from exc
    if response.status_code == 401:
        raise AppLaunchError(
            f"the app already running on port {port} does not accept this app token: it was "
            f"started from a different app data directory. Use that instance, stop it, or run "
            f"`research app --port <other port>`."
        )
    if response.status_code != 200:
        raise AppLaunchError(
            f"the app on port {port} refused a launch session (HTTP {response.status_code})"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppLaunchError(
            f"the app on port {port} answered {BOOTSTRAP_PATH} with something that is not JSON"
        ) from exc
    bootstrap = payload.get("bootstrap") if isinstance(payload, dict) else None
    if not isinstance(bootstrap, str) or not bootstrap:
        raise AppLaunchError(
            f"the app on port {port} answered {BOOTSTRAP_PATH} without a launch nonce"
        )
    return bootstrap


# -- every other external effect, in one place so a test can replace it ------


def _create_app(data_dir: Path, *, port: int, bootstraps: BootstrapStore) -> FastAPI:
    """Build the multi-project application. Imported here: it costs FastAPI and the pool."""
    from research_harness.server.multi_app import create_multi_project_app

    return create_multi_project_app(data_dir, port=port, bootstraps=bootstraps)


def _run_server(application: Any, *, port: int) -> None:
    """Serve on loopback until interrupted. Local-first is a boundary, not a default."""
    import uvicorn

    uvicorn.run(application, host=LOOPBACK, port=port)


def _open_browser(url: str) -> None:
    """Hand the URL to the researcher's default browser."""
    webbrowser.open(url)


def _schedule_browser(url: str, delay: float = BROWSER_DELAY_SECONDS) -> None:
    """Open the URL shortly after uvicorn has had time to bind, without blocking it.

    The timer resolves `_open_browser` when it fires rather than capturing it, so the
    injection point stays the module attribute.
    """
    timer = threading.Timer(delay, lambda: _open_browser(url))
    timer.daemon = True
    timer.start()

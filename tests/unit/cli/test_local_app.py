"""`research app`: start one application, or join the one already listening.

What is pinned here is the behaviour a researcher can observe from a terminal, because
every one of these is a way the command could quietly do the wrong thing:

* it must run **outside** any workspace — it is the one command that is not about one, so
  a stray `resolve_workspace` would make the whole application undiscoverable from a home
  directory (design §4.1, §12);
* a compatible instance already on the port must be **joined**, not raced;
* anything else on the port must be an **error naming `--port`**, not a process the
  launcher drives or displaces;
* the launch URL must carry a one-time nonce and **never the persisted app token**
  (design §8.1).

Every external effect (the server, the browser, the two HTTP calls, the application
factory) is a module-level function, so these tests are hermetic: nothing binds a port,
opens a browser, or reaches the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import typer
from typer.testing import CliRunner, Result

from research_harness.cli.app import app
from research_harness.cli.commands import local_app
from research_harness.cli.commands.local_app import (
    AppLaunchError,
    PortOccupiedError,
    app_url,
    probe_existing_app,
    request_bootstrap,
)

runner = CliRunner()

APP_TOKEN = "persisted-app-token-not-for-urls"
NONCE = "one-time-nonce"


def output(result: Result) -> str:
    """Everything the command printed; Click's runner mixes stderr into `output`."""
    return result.output


class Recorder:
    """A stand-in that remembers how it was called, and answers with `result`."""

    def __init__(self, result: Any = None) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.result = result

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.result

    @property
    def called(self) -> bool:
        return bool(self.calls)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An app data directory of this test's own; never the researcher's real one."""
    return tmp_path / "app-data"


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch) -> dict[str, Recorder]:
    """Replace every external effect; return the recorders the assertions read."""
    recorders = {
        "probe": Recorder(False),
        "bootstrap": Recorder(NONCE),
        "create": Recorder(object()),
        "run": Recorder(None),
        "open": Recorder(None),
        "schedule": Recorder(None),
    }
    monkeypatch.setattr(local_app, "probe_existing_app", recorders["probe"])
    monkeypatch.setattr(local_app, "request_bootstrap", recorders["bootstrap"])
    monkeypatch.setattr(local_app, "_create_app", recorders["create"])
    monkeypatch.setattr(local_app, "_run_server", recorders["run"])
    monkeypatch.setattr(local_app, "_open_browser", recorders["open"])
    monkeypatch.setattr(local_app, "_schedule_browser", recorders["schedule"])
    return recorders


def invoke(data_dir: Path, *args: str) -> Result:
    return runner.invoke(app, ["app", "--data-dir", str(data_dir), *args])


# -- the command -------------------------------------------------------------


def test_app_starts_outside_any_workspace(
    launcher: dict[str, Recorder], data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No research.yaml at or above the cwd, and the command still starts the app."""
    elsewhere = tmp_path / "not-a-workspace"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    def explode(_: Any) -> Path:  # pragma: no cover - reached only on a regression
        raise AssertionError("`research app` must not resolve a workspace")

    monkeypatch.setattr("research_harness.cli.context.resolve_workspace", explode)

    result = invoke(data_dir, "--no-open")

    assert result.exit_code == 0, output(result)
    assert launcher["run"].called


def test_app_creates_the_app_token_under_the_given_data_directory(
    launcher: dict[str, Recorder], data_dir: Path
) -> None:
    result = invoke(data_dir, "--no-open")

    assert result.exit_code == 0, output(result)
    assert (data_dir / "app-token").is_file()
    assert str(data_dir) in result.output


def test_an_existing_compatible_instance_is_opened_without_starting_another_server(
    launcher: dict[str, Recorder], data_dir: Path
) -> None:
    launcher["probe"].result = True

    result = invoke(data_dir)

    assert result.exit_code == 0, output(result)
    assert launcher["probe"].calls[0][0] == (local_app.DEFAULT_PORT,)
    assert launcher["bootstrap"].called
    assert launcher["open"].calls[0][0] == (app_url(local_app.DEFAULT_PORT, NONCE),)
    assert not launcher["run"].called
    assert not launcher["create"].called


def test_joining_an_instance_presents_the_app_token_and_never_prints_it(
    launcher: dict[str, Recorder], data_dir: Path
) -> None:
    launcher["probe"].result = True

    result = invoke(data_dir)

    token = (data_dir / "app-token").read_text(encoding="utf-8").strip()
    assert launcher["bootstrap"].calls[0][0] == (local_app.DEFAULT_PORT, token)
    assert token not in output(result)


def test_no_open_starts_the_server_on_the_requested_port_without_a_browser(
    launcher: dict[str, Recorder], data_dir: Path
) -> None:
    result = invoke(data_dir, "--no-open", "--port", "8877")

    assert result.exit_code == 0, output(result)
    assert launcher["run"].calls[0][1]["port"] == 8877
    assert launcher["create"].calls[0][1]["port"] == 8877
    assert not launcher["open"].called
    assert not launcher["schedule"].called
    assert "8877" in result.output


def test_launching_schedules_the_browser_on_the_nonce_url(
    launcher: dict[str, Recorder], data_dir: Path
) -> None:
    result = invoke(data_dir)

    assert result.exit_code == 0, output(result)
    url = launcher["schedule"].calls[0][0][0]
    assert url.startswith(f"http://127.0.0.1:{local_app.DEFAULT_PORT}/?bootstrap=")
    assert not launcher["open"].called


def test_the_launch_url_never_carries_the_persisted_app_token(
    launcher: dict[str, Recorder], data_dir: Path
) -> None:
    result = invoke(data_dir)

    token = (data_dir / "app-token").read_text(encoding="utf-8").strip()
    url = launcher["schedule"].calls[0][0][0]
    bootstraps = launcher["create"].calls[0][1]["bootstraps"]
    assert token not in url
    assert token not in output(result)
    # The nonce in the URL is one the application itself can exchange, and only once.
    assert bootstraps.exchange(url.rsplit("=", 1)[1]) is True


def test_a_port_held_by_another_process_fails_and_names_the_port_option(
    launcher: dict[str, Recorder], data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def occupied(port: int) -> bool:
        raise PortOccupiedError(
            f"port {port} is in use by something that is not a Research Harness app; "
            f"run `research app --port <other port>`"
        )

    monkeypatch.setattr(local_app, "probe_existing_app", occupied)

    result = invoke(data_dir)

    assert result.exit_code == 1
    assert "--port" in output(result)
    assert not launcher["run"].called


def test_app_is_registered_beside_the_legacy_transports() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, output(result)
    for name in ("app", "serve", "mcp", "shell"):
        assert f" {name} " in result.output, f"`research {name}` is no longer registered"


def test_app_takes_no_workspace_option() -> None:
    result = runner.invoke(app, ["app", "--help"])

    assert result.exit_code == 0, output(result)
    # The prose says the command takes no workspace; the options panel must agree.
    assert "RESEARCH_WORKSPACE" not in result.output
    assert "--port" in result.output
    assert "--no-open" in result.output


# -- the launch URL ----------------------------------------------------------


def test_app_url_percent_encodes_the_nonce() -> None:
    url = app_url(8765, "a b/c+d=")

    assert url == "http://127.0.0.1:8765/?bootstrap=a%20b%2Fc%2Bd%3D"


def test_app_url_uses_loopback_and_the_given_port() -> None:
    assert app_url(9001, NONCE).startswith("http://127.0.0.1:9001/?bootstrap=")


# -- probing the port --------------------------------------------------------


def transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_probe_accepts_a_multi_project_health_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/app/health"
        return httpx.Response(200, json={"ok": True, "kind": "multi_project", "version": "0.1.0"})

    assert probe_existing_app(8765, transport=transport(handler)) is True


def test_probe_reports_nothing_listening_as_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert probe_existing_app(8765, transport=transport(handler)) is False


def test_probe_refuses_a_port_answering_with_a_404() -> None:
    """A one-workspace `research serve` daemon has no /api/app/health."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    with pytest.raises(PortOccupiedError, match="--port"):
        probe_existing_app(8765, transport=transport(handler))


def test_probe_refuses_a_port_answering_with_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<!doctype html><title>something else</title>")

    with pytest.raises(PortOccupiedError, match="--port"):
        probe_existing_app(8765, transport=transport(handler))


def test_probe_refuses_a_health_answer_of_another_kind() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "kind": "workspace"})

    with pytest.raises(PortOccupiedError):
        probe_existing_app(8765, transport=transport(handler))


def test_probe_refuses_a_port_that_never_answers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(PortOccupiedError, match="--port"):
        probe_existing_app(8765, transport=transport(handler))


# -- asking the running instance for a nonce ---------------------------------


def test_request_bootstrap_presents_the_token_and_returns_the_nonce() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/app/bootstrap"
        assert request.headers["authorization"] == f"Bearer {APP_TOKEN}"
        return httpx.Response(200, json={"bootstrap": NONCE, "expires_in": 60.0})

    assert request_bootstrap(8765, APP_TOKEN, transport=transport(handler)) == NONCE


def test_request_bootstrap_explains_a_refused_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"code": "control_permission_denied"}})

    with pytest.raises(AppLaunchError, match="different app data directory"):
        request_bootstrap(8765, APP_TOKEN, transport=transport(handler))


def test_request_bootstrap_rejects_an_answer_without_a_nonce() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"bootstrap": "", "expires_in": 60.0})

    with pytest.raises(AppLaunchError, match="without a launch nonce"):
        request_bootstrap(8765, APP_TOKEN, transport=transport(handler))


def test_request_bootstrap_rejects_a_non_json_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(AppLaunchError, match="not JSON"):
        request_bootstrap(8765, APP_TOKEN, transport=transport(handler))


def test_typer_is_imported_for_the_command_module() -> None:
    """The module registers on a Typer app; this keeps the import honest."""
    application = typer.Typer()
    local_app.register(application)

    assert application.registered_commands[0].name == "app"


# -- the loopback probe and the shell's proxy variables -------------------------


def test_the_loopback_probe_ignores_proxy_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proxy in the shell must not capture a request to 127.0.0.1.

    `httpx` honours `HTTP_PROXY` by default, so with one set the health probe would go to
    the proxy instead of the loopback app and either time out or fail to connect — reported
    as "something is listening but did not answer", on every port. The probe talks to a
    loopback socket the process itself may have started; it never wants a proxy.
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"ok": True, "kind": "multi_project", "version": "0"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")  # a port nothing answers on
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)

        assert probe_existing_app(server.server_address[1]) is True
    finally:
        server.shutdown()
        server.server_close()

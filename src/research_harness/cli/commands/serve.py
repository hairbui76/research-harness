"""`research serve`, `research mcp`, `research token`, `research capabilities`.

The three ways into one workspace that are not the CLI itself. Each is a transport binding
and nothing else: they start a server over the capability registry, or print what that
registry exposes (ADR-004, ADR-009).

`serve` binds loopback only. The daemon is a personal workstation service, not a shared
one: authority comes from a token file under `.research/` that only a local process can
read, and a caller without it is an agent host that may read and stage but never accept
(Product 4, 29, 34).
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from research_harness.capabilities.registry import build_default_registry
from research_harness.cli.context import (
    JsonOption,
    WorkspaceOption,
    cli_errors,
    emit,
    resolve_workspace,
)

__all__ = ["register"]

LOOPBACK = "127.0.0.1"
"""The only address the daemon binds. Local-first is a boundary, not a default."""

DEFAULT_PORT = 8765


def register(app: typer.Typer) -> None:
    """Add `research serve`, `research mcp`, `research token`, and `research capabilities`."""
    app.command("serve")(serve)
    app.command("mcp")(mcp)
    app.command("token")(token)
    app.command("capabilities")(capabilities)


def serve(
    workspace: WorkspaceOption = None,
    port: Annotated[int, typer.Option("--port", help="Loopback port to bind.")] = DEFAULT_PORT,
    reload: Annotated[
        bool, typer.Option("--reload", help="Reload on source changes (development only).")
    ] = False,
) -> None:
    """Run the local HTTP daemon over this workspace (loopback only)."""
    with cli_errors():
        import uvicorn

        from research_harness.server.app import create_app, ensure_token, token_path

        root = resolve_workspace(workspace)
        ensure_token(root)
        typer.echo(f"serving {root} on http://{LOOPBACK}:{port}")
        typer.echo(f"local token          {token_path(root)}")
        uvicorn.run(create_app(root), host=LOOPBACK, port=port, reload=reload)


def mcp(
    workspace: WorkspaceOption = None,
    stdio: Annotated[
        bool, typer.Option("--stdio", help="Speak MCP over stdin/stdout (the default).")
    ] = True,
    host: Annotated[
        str,
        typer.Option("--host", help="Label recorded for the calling agent host; changes nothing."),
    ] = "mcp",
) -> None:
    """Expose this workspace to an agent host over MCP: one tool per capability."""
    with cli_errors():
        from research_harness.protocol.mcp import create_mcp_server

        if not stdio:
            raise typer.BadParameter("only the stdio transport is supported; pass --stdio")
        root = resolve_workspace(workspace)
        create_mcp_server(root, host=host).run("stdio")


def token(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """Print the path of this workspace's local daemon token, creating it if needed.

    The path is printed, not the secret: a token that reaches a shell history or a log is
    no longer a local-only credential (Product 34).
    """
    with cli_errors():
        from research_harness.server.app import ensure_token, token_path

        root = resolve_workspace(workspace)
        ensure_token(root)
        path = token_path(root)
        emit(
            {"workspace": str(root), "token_path": str(path)},
            [f"{path}"],
            as_json=as_json,
        )


def capabilities(
    workspace: WorkspaceOption = None,
    schemas: Annotated[
        bool, typer.Option("--schemas", help="Include the request/response JSON schemas.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """List the named capabilities this build exposes, and the ones it does not yet."""
    with cli_errors():
        resolve_workspace(workspace)
        registry = build_default_registry()
        descriptors = registry.describe()
        payload: dict[str, Any] = {
            "capabilities": [
                _descriptor_payload(descriptor, schemas=schemas) for descriptor in descriptors
            ],
            "planned": [item.model_dump(mode="json") for item in registry.planned()],
        }
        emit(payload, _lines(payload), as_json=as_json)


def _descriptor_payload(descriptor: Any, *, schemas: bool) -> dict[str, Any]:
    data: dict[str, Any] = descriptor.model_dump(mode="json")
    if not schemas:
        data.pop("request_schema", None)
        data.pop("response_schema", None)
    return data


def _lines(payload: dict[str, Any]) -> list[str]:
    entries = payload["capabilities"]
    width = max((len(item["name"]) for item in entries), default=0)
    lines = [
        f"{item['name'].ljust(width)}  {item['permission']:<7} "
        f"{'human' if item['human_only'] else '     '} "
        f"{'run' if item['long_running'] else '   '}  {item['summary']}"
        for item in entries
    ]
    lines += [f"planned  {item['name']}: {item['reason']}" for item in payload["planned"]]
    return lines

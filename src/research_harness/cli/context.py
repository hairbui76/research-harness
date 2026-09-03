"""Shared CLI plumbing: which workspace, on whose authority, and how output is shaped.

The CLI is a transport (ADR-004). It resolves a workspace, opens a capability context,
prints, and maps a harness error to exit code 1. It never writes canonical state itself.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.workspace.layout import RESEARCH_FILENAME

__all__ = [
    "CLI_ACTOR",
    "WORKSPACE_ENV",
    "JsonOption",
    "WorkspaceOption",
    "cli_errors",
    "context_for",
    "emit",
    "resolve_workspace",
]

WORKSPACE_ENV = "RESEARCH_WORKSPACE"

#: Every CLI mutation is a researcher action; models reach capabilities through their own
#: transports, never through this one.
CLI_ACTOR = HUMAN_ACTOR

WorkspaceOption = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        "-w",
        envvar=WORKSPACE_ENV,
        help="Workspace root; defaults to the nearest research.yaml above the current directory.",
        show_default=False,
    ),
]

JsonOption = Annotated[
    bool,
    typer.Option("--json", help="Print the result as JSON instead of text."),
]


def resolve_workspace(explicit: Path | None) -> Path:
    """The workspace root: the option, else `RESEARCH_WORKSPACE`, else the nearest one above."""
    if explicit is not None:
        return explicit
    start = Path.cwd()
    for directory in (start, *start.parents):
        if (directory / RESEARCH_FILENAME).is_file():
            return directory
    raise ResearchHarnessError(
        f"no research workspace at or above {start}: run `research init <dir>`, pass "
        f"--workspace, or set {WORKSPACE_ENV}"
    )


def context_for(workspace: Path | None, *, actor: str = CLI_ACTOR) -> CapabilityContext:
    """Open the capability context the command should run in."""
    return open_context(resolve_workspace(workspace), actor)


@contextmanager
def cli_errors() -> Iterator[None]:
    """Turn a harness or request error into one line on stderr and exit code 1."""
    try:
        yield
    except ResearchHarnessError as exc:
        typer.secho(f"error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        typer.secho(f"error: invalid request: {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def emit(payload: Mapping[str, Any], lines: Sequence[str], *, as_json: bool) -> None:
    """Print ``payload`` as JSON, or ``lines`` for a human."""
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    for line in lines:
        typer.echo(line)

"""`research init`: create a workspace through the `project.init` capability."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.cli.context import JsonOption, cli_errors, emit
from research_harness.domain.enums import ReviewPolicy

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Add `research init` to ``app``."""
    app.command("init")(init)


def init(
    directory: Annotated[Path, typer.Argument(help="Directory to create the workspace in.")],
    name: Annotated[
        str | None,
        typer.Option("--name", help="Project name; defaults to the directory name."),
    ] = None,
    policy: Annotated[
        ReviewPolicy,
        typer.Option("--policy", help="Review policy. Strict is the product default."),
    ] = ReviewPolicy.STRICT,
    as_json: JsonOption = False,
) -> None:
    """Initialize a research workspace: canonical directories, `research.yaml`, event log."""
    with cli_errors():
        result = init_project(InitProjectRequest(root=directory, name=name, policy=policy))
        emit(
            result.as_dict(),
            [
                f"initialized {result.name} at {result.root}",
                f"  review policy      {result.policy.value}",
                "  next               research ingest <pdf>",
            ],
            as_json=as_json,
        )

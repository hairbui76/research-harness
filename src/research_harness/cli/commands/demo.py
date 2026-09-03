"""`research demo`: a ready-to-review workspace from the bundled synthetic paper."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.cli.context import JsonOption, cli_errors, emit
from research_harness.demo import DemoReport, run_demo

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Add `research demo`."""
    app.command("demo")(demo)


def demo(
    directory: Annotated[
        Path, typer.Argument(help="Directory to create the demo workspace in (must not exist).")
    ],
    name: Annotated[str, typer.Option("--name", help="Project name.")] = "demo",
    as_json: JsonOption = False,
) -> None:
    """Create a workspace with verified proposals waiting for review — offline, no API key.

    Ingests and parses the bundled synthetic paper, stages three proposals with the
    scripted provider, verifies them, and rebuilds the projection. Nothing is accepted:
    that is the researcher's step, in the cockpit (`research serve`), the CLI
    (`research inbox`, `research review`), or an MCP host.
    """
    with cli_errors():
        report = run_demo(directory, name=name)
        emit(report.as_dict(), _lines(report), as_json=as_json)


def _lines(report: DemoReport) -> list[str]:
    verdicts = ", ".join(f"{field}={verdict}" for field, verdict in sorted(report.verified.items()))
    payload: dict[str, Any] = report.as_dict()
    return [
        f"demo workspace ready at {report.root}",
        f"  work               {report.work} ({report.pages} pages, {report.blocks} blocks)",
        f"  staged             {report.staged} proposals",
        f"  verified           {verdicts}",
        f"  canonical digest   {payload['canonical_digest']}",
        "next",
        f"  research serve -w {report.root}",
        f"  research inbox -w {report.root}",
        "  open http://127.0.0.1:8765/?token=<contents of .research/daemon-token>",
    ]

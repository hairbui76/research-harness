"""`research rebuild`: reconstruct the deletable projection from canonical files.

The command is a thin transport (conventions: layering). It resolves a workspace, hands it
to :func:`~research_harness.projection.rebuild.rebuild_workspace`, prints the report, and
exits non-zero when the workspace holds a canonical file the rebuild refused to accept - so
a rebuild in CI fails loudly instead of quietly indexing less than it should.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import typer

from research_harness.cli.context import (
    JsonOption,
    WorkspaceOption,
    cli_errors,
    emit,
    resolve_workspace,
)
from research_harness.projection.rebuild import RebuildReport, rebuild_workspace
from research_harness.workspace.repository import WorkspaceRepository

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Add `research rebuild` to ``app``."""
    app.command("rebuild")(rebuild)


def rebuild(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """Rebuild `.research/research.db` from canonical files; never writes canonical state.

    The workspace is opened with ``repair=True``: one whose event log disagrees with
    canonical state still deserves an index to diagnose it with, and a rebuild writes
    nothing that carries scientific authority (ADR-001).
    """
    with cli_errors():
        repo = WorkspaceRepository.open(resolve_workspace(workspace), repair=True)
        report = rebuild_workspace(repo)
    emit(_payload(report), _lines(report), as_json=as_json)
    if not report.ok:
        raise typer.Exit(code=1)


def _payload(report: RebuildReport) -> dict[str, Any]:
    return asdict(report)


def _lines(report: RebuildReport) -> list[str]:
    lines = [report.summary()]
    lines += [
        f"  {name:<18} {count}"
        for name, count in report.objects_by_type.items()
        if count or not report.ok
    ]
    lines += [f"  invalid  {invalid.path}: {invalid.error}" for invalid in report.invalid_files]
    lines.append(f"  canonical digest   {report.canonical_digest}")
    return lines

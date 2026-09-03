"""Refused at load: a validator may not import the package that owns canonical state."""

from __future__ import annotations

from collections.abc import Mapping

from research_harness.workspace.repository import WorkspaceRepository


def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:
    """Never runs: `scan_module` refuses this file before it is executed."""
    return [{"field": "x", "message": WorkspaceRepository.__name__, "severity": "error"}]

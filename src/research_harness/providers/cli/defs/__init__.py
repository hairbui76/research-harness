"""The shipped runtime definitions, in display order (CLI providers spec §9)."""

from __future__ import annotations

from research_harness.providers.cli.defs.claude import CLAUDE
from research_harness.providers.cli.defs.codex import CODEX
from research_harness.providers.cli.types import CliRuntimeDef

__all__ = ["SHIPPED_DEFS"]

SHIPPED_DEFS: tuple[CliRuntimeDef, ...] = (CODEX, CLAUDE)

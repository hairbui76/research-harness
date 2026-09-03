"""The shipped runtime definitions, in display order (CLI providers spec §9)."""

from __future__ import annotations

from research_harness.providers.cli.defs.amp import AMP
from research_harness.providers.cli.defs.claude import CLAUDE
from research_harness.providers.cli.defs.codex import CODEX
from research_harness.providers.cli.defs.cursor_agent import CURSOR_AGENT
from research_harness.providers.cli.defs.deepseek_harness import DEEPSEEK_HARNESS
from research_harness.providers.cli.defs.opencode import OPENCODE
from research_harness.providers.cli.defs.pi import PI
from research_harness.providers.cli.types import CliRuntimeDef

__all__ = ["SHIPPED_DEFS"]

SHIPPED_DEFS: tuple[CliRuntimeDef, ...] = (
    CODEX,
    CLAUDE,
    CURSOR_AGENT,
    AMP,
    DEEPSEEK_HARNESS,
    OPENCODE,
    PI,
)

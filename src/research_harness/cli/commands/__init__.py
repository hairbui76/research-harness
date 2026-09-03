"""Command modules for the `research` CLI.

Each module exposes ``register(app: typer.Typer) -> None`` and is listed in
:data:`COMMAND_MODULES`; adding a command family is one import and one line, and no
module here reaches past `capabilities/` to change canonical state.
"""

from __future__ import annotations

from types import ModuleType

import typer

from research_harness.cli.commands import (
    attachment,
    claim,
    corpus,
    demo,
    discover,
    evidence,
    graph,
    init,
    manuscript,
    privacy,
    rebuild,
    research,
    search,
    serve,
    session,
)

__all__ = ["COMMAND_MODULES", "register_all"]

#: Registered in order; later families (`review`, `claim`, `manuscript`, ...) are added here.
COMMAND_MODULES: tuple[ModuleType, ...] = (
    init,
    corpus,
    demo,
    rebuild,
    evidence,
    claim,
    research,
    search,
    discover,
    manuscript,
    graph,
    attachment,
    session,
    privacy,
    serve,
)


def register_all(app: typer.Typer) -> None:
    """Register every command family on ``app``."""
    for module in COMMAND_MODULES:
        register = getattr(module, "register", None)
        if register is None:  # pragma: no cover - guarded by the module contract
            raise TypeError(f"{module.__name__} does not expose register(app)")
        register(app)

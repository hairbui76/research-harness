"""The small event vocabulary every CLI stream is translated into (CLI providers spec §13).

A parser turns one vendor line into zero or more `CliEvent`s. The engine consumes only
this vocabulary, so a new CLI with a known wire format is a definition plus fixtures and
no engine change. Tool calls and file writes are `tool` events: the engine never executes
them and treats one as a bounded-authority violation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from research_harness.providers.models.base import Usage

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a cycle with types.py consumers
    from research_harness.providers.cli.types import CliRuntimeDef, ProtocolFamily

__all__ = ["PARSERS", "CliEvent", "EventKind", "EventParser", "ParserFactory", "parser_for"]

EventKind = Literal[
    "text_delta", "final_text", "usage", "model", "stop", "status", "error", "tool", "done"
]


@dataclass(frozen=True, slots=True)
class CliEvent:
    """One thing a runtime said, in the only vocabulary the engine understands."""

    kind: EventKind
    text: str = ""
    usage: Usage | None = None
    model: str | None = None
    stop_reason: str | None = None
    status: str | None = None
    message: str | None = None
    code: str | None = None
    tool: str | None = None


class EventParser(Protocol):
    """Stateful per run: `feed` one line at a time, then `finish` at end of stream."""

    def feed(self, line: str) -> Iterable[CliEvent]: ...

    def finish(self) -> Iterable[CliEvent]: ...


ParserFactory = Callable[["CliRuntimeDef"], EventParser]


class _Unimplemented:
    """Placeholder for a protocol family whose parser module has not landed yet.

    It keeps `PARSERS` complete so `registry.validate_definition` can already refuse a
    definition with no parser, and fails loudly rather than silently if anything tries to
    read a stream with it.
    """

    def __init__(self, family: str) -> None:
        self._family = family

    def feed(self, line: str) -> Iterable[CliEvent]:
        raise NotImplementedError(f"the {self._family} parser is not implemented")

    def finish(self) -> Iterable[CliEvent]:
        raise NotImplementedError(f"the {self._family} parser is not implemented")


def _unimplemented_factory(family: str) -> ParserFactory:
    def factory(definition: CliRuntimeDef) -> EventParser:
        return _Unimplemented(family)

    return factory


PARSERS: dict[str, ParserFactory] = {
    family: _unimplemented_factory(family)
    for family in ("claude_stream", "json_events", "dsh_profile", "pi_rpc")
}
"""Protocol family → parser factory. The four parser modules replace their entry on import
(`register` below); `registry.validate_definition` refuses a family with no entry."""


def register(family: ProtocolFamily, factory: ParserFactory) -> None:
    """Claim a protocol family for a real parser, replacing the placeholder."""
    PARSERS[family] = factory


def parser_for(definition: CliRuntimeDef) -> EventParser:
    """A fresh parser for one run of `definition`."""
    return PARSERS[definition.protocol](definition)

"""The small event vocabulary every CLI stream is translated into (CLI providers spec §13).

A parser turns one vendor line into zero or more `CliEvent`s. The engine consumes only
this vocabulary, so a new CLI with a known wire format is a definition plus fixtures and
no engine change. Tool calls and file writes are `tool` events: the engine never executes
them and treats one as a bounded-authority violation.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from research_harness.providers.models.base import Usage

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a cycle with types.py consumers
    from research_harness.providers.cli.types import CliRuntimeDef, ProtocolFamily

__all__ = [
    "PARSERS",
    "CliEvent",
    "EventKind",
    "EventParser",
    "ParserFactory",
    "json_payload",
    "load_json_object",
    "parser_for",
    "register",
]

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


PARSERS: dict[str, ParserFactory] = {}
"""Protocol family → parser factory. The four parser modules claim their entry on import
(`register` below, driven by the imports at the bottom of this module), so `PARSERS` is
complete whenever this package is imported; `registry.validate_definition` refuses a
family with no entry."""


def register(family: ProtocolFamily, factory: ParserFactory) -> None:
    """Claim a protocol family for a parser; each parser module calls this on import."""
    PARSERS[family] = factory


def parser_for(definition: CliRuntimeDef) -> EventParser:
    """A fresh parser for one run of `definition`."""
    return PARSERS[definition.protocol](definition)


def json_payload(line: str) -> str:
    """The JSON text on `line`, or `""` when it is blank or a `#` comment line."""
    stripped = line.strip()
    return "" if not stripped or stripped.startswith("#") else stripped


def load_json_object(line: str) -> dict[str, Any] | None:
    """Skips blank and `#` comment lines; the parsed JSON object, or `None` for anything else."""
    payload = json_payload(line)
    if not payload:
        return None
    try:
        value = json.loads(payload)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# Register the four parsers by importing them; each module calls `register` on import.
# E402: these must follow `register`, which they call at import time.
from research_harness.providers.cli.parsers import claude_stream as _claude_stream  # noqa: E402
from research_harness.providers.cli.parsers import dsh_profile as _dsh_profile  # noqa: E402
from research_harness.providers.cli.parsers import json_events as _json_events  # noqa: E402
from research_harness.providers.cli.parsers import pi_rpc as _pi_rpc  # noqa: E402

del _claude_stream, _dsh_profile, _json_events, _pi_rpc

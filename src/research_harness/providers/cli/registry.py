"""The runtime registry: shipped definitions, validated once, looked up by id (spec §8).

Construction fails immediately on a duplicate id, a missing parser, an argument builder
that is not pure data, a bypass flag, a local egress host, or research content in argv —
so an unsafe definition cannot be loaded, let alone spawned (spec §12).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from research_harness.privacy.policy import is_local_endpoint
from research_harness.providers.cli import parsers as _parsers
from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    CliInvocation,
    CliRuntimeDef,
)

__all__ = [
    "FORBIDDEN_ARGS",
    "FORBIDDEN_VALUES",
    "RUNTIMES",
    "RUNTIME_DEFS",
    "RUNTIME_IDS",
    "SAMPLE_INVOCATIONS",
    "RegistryError",
    "UnknownRuntimeError",
    "build_registry",
    "get_runtime",
    "validate_definition",
]

FORBIDDEN_ARGS: frozenset[str] = frozenset(
    {
        "--dangerously-skip-permissions",
        "--dangerously-allow-all",
        "--dangerously-bypass-approvals-and-sandbox",
        "--allow-dangerously-skip-permissions",
        "--approve-for-me",
        "--force",
        "--trust",
        "bypassPermissions",
        "danger-full-access",
        "workspace-write",
    }
)
"""Flags Open Design uses to run a *full* agent. Never in a bounded definition (spec §12)."""

FORBIDDEN_VALUES: frozenset[str] = frozenset(
    token for token in FORBIDDEN_ARGS if not token.startswith("-")
)
"""The forbidden tokens that name a *setting*, not a flag: `bypassPermissions`,
`danger-full-access`, `workspace-write`. A CLI takes these as the value half of a
configuration override -- `-c sandbox_mode="danger-full-access"`, `--sandbox=workspace-write`
-- which arrives as one argv item whose `=`-split still carries the quotes, so nothing but a
substring match sees it. Screened that way, and deliberately over-broad: no bounded
definition has any business mentioning them at all."""

_SHELL_OPERATORS = frozenset({";", "&&", "||", "|", ">", ">>", "<", "`"})
_PROMPT_MARKER = "PROMPT-MARKER"

SAMPLE_INVOCATIONS: tuple[CliInvocation, ...] = (
    CliInvocation(
        model=None, reasoning=None, cwd=Path("/tmp/rh-cli-sample"), request_id="req-sample"
    ),
    CliInvocation(
        model="sample-model",
        reasoning="high",
        cwd=Path("/tmp/rh-cli-sample"),
        request_id="req-sample",
        schema_path=Path("/tmp/rh-cli-sample/response.schema.json"),
    ),
)
"""Invocations every builder is exercised with at registry construction."""

_TRANSPORTS_FOR_PROTOCOL: Mapping[str, frozenset[str]] = {
    "claude_stream": frozenset({"stdin_text", "stdin_jsonl"}),
    "json_events": frozenset({"stdin_text"}),
    "dsh_profile": frozenset({"dsh_profile"}),
    "pi_rpc": frozenset({"pi_rpc"}),
}


class RegistryError(ValueError):
    """A definition is not pure, bounded data."""


class UnknownRuntimeError(KeyError):
    """No definition with that id."""

    def __init__(self, runtime: str, known: Sequence[str]) -> None:
        super().__init__(runtime)
        self.runtime = runtime
        self.message = f"unknown runtime {runtime!r} (known: {', '.join(known) or 'none'})"

    def __str__(self) -> str:
        return self.message


def validate_definition(
    definition: CliRuntimeDef, *, parsers: Mapping[str, object] | None = None
) -> None:
    """Refuse a definition that is not data, or not bounded (spec §8, §12)."""
    known_parsers = _parsers.PARSERS if parsers is None else parsers
    name = definition.id
    if (
        not name
        or not name.replace("-", "").isalnum()
        or not name[0].isalpha()
        or name != name.lower()
    ):
        raise RegistryError(f"runtime id {name!r} must be lowercase letters, digits and dashes")
    if definition.protocol not in known_parsers:
        raise RegistryError(
            f"runtime {name!r}: no parser is registered for protocol {definition.protocol!r}"
        )
    if definition.transport not in _TRANSPORTS_FOR_PROTOCOL[definition.protocol]:
        raise RegistryError(
            f"runtime {name!r}: transport {definition.transport!r} does not carry "
            f"protocol {definition.protocol!r}"
        )
    if (definition.protocol == "json_events") != (definition.json_events_variant is not None):
        raise RegistryError(
            f"runtime {name!r}: json_events_variant is required exactly when the protocol "
            f"is json_events"
        )
    if is_local_endpoint(definition.egress_host):
        raise RegistryError(
            f"runtime {name!r}: egress host {definition.egress_host!r} reads as local; "
            f"a CLI provider is never local (spec §4)"
        )
    if (definition.egress == "unknown_external") != (
        definition.egress_host == UNKNOWN_EXTERNAL_HOST
    ):
        raise RegistryError(
            f"runtime {name!r}: unknown_external egress must use host "
            f"{UNKNOWN_EXTERNAL_HOST!r} and nothing else may"
        )
    if set(definition.verified_versions) & set(definition.blocked_versions):
        raise RegistryError(f"runtime {name!r}: a version cannot be both verified and blocked")
    if definition.posture.kind != "none" and definition.posture.help_probe is None:
        raise RegistryError(
            f"runtime {name!r}: a bounded posture must declare the help probe that proves it"
        )
    for invocation in SAMPLE_INVOCATIONS:
        _check_args(name, definition.build_args(invocation))


def _check_args(name: str, args: object) -> None:
    """Refuse argv that is not a plain string tuple, or that carries authority or content."""
    if not isinstance(args, tuple) or not all(isinstance(item, str) for item in args):
        raise RegistryError(f"runtime {name!r}: build_args must return a tuple of strings")
    for item in args:
        if (
            item in FORBIDDEN_ARGS
            or any(token in item.split("=") for token in FORBIDDEN_ARGS)
            or any(token in item for token in FORBIDDEN_VALUES)
        ):
            raise RegistryError(f"runtime {name!r}: forbidden argument {item!r}")
        if item in _SHELL_OPERATORS:
            raise RegistryError(f"runtime {name!r}: shell operator {item!r} in argv")
        if _PROMPT_MARKER in item:
            raise RegistryError(f"runtime {name!r}: prompt content in argv")


def build_registry(definitions: Sequence[CliRuntimeDef]) -> Mapping[str, CliRuntimeDef]:
    """Validate every definition and index them by id, in the order given."""
    registry: dict[str, CliRuntimeDef] = {}
    for definition in definitions:
        if definition.id in registry:
            raise RegistryError(f"duplicate runtime id {definition.id!r}")
        validate_definition(definition)
        registry[definition.id] = definition
    return MappingProxyType(registry)


def get_runtime(
    runtime: str, *, registry: Mapping[str, CliRuntimeDef] | None = None
) -> CliRuntimeDef:
    """The definition with that id, or `UnknownRuntimeError` naming the ids that exist."""
    table = RUNTIMES if registry is None else registry
    try:
        return table[runtime]
    except KeyError:
        raise UnknownRuntimeError(runtime, tuple(table)) from None


def _shipped() -> tuple[CliRuntimeDef, ...]:
    from research_harness.providers.cli.defs import SHIPPED_DEFS

    return SHIPPED_DEFS


RUNTIME_DEFS: tuple[CliRuntimeDef, ...] = _shipped()
RUNTIMES: Mapping[str, CliRuntimeDef] = build_registry(RUNTIME_DEFS)
RUNTIME_IDS: tuple[str, ...] = tuple(RUNTIMES)

"""Immutable contracts for subscription-backed local CLI runtimes (CLI providers spec §8, §10).

A runtime definition is data plus pure builders. Nothing here spawns a process, reads a
credential, or touches the workspace: `detection.py` and `process.py` own behaviour, and
`registry.py` refuses a definition that carries anything but data. "Local CLI" names where
the *client process* starts, not where inference happens (spec §4): every definition
declares an external egress host, and `UNKNOWN_EXTERNAL_HOST` when it cannot name one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

__all__ = [
    "DEFAULT_MODEL",
    "UNKNOWN_EXTERNAL_HOST",
    "ArgBuilder",
    "AuthClassifier",
    "AuthStatus",
    "BoundedMode",
    "BoundedPosture",
    "CliInvocation",
    "CliModelOption",
    "CliModelView",
    "CliRuntimeDef",
    "CliRuntimeStatus",
    "Compatibility",
    "EgressKind",
    "JsonEventsVariant",
    "ModelParser",
    "ModelSource",
    "Probe",
    "ProbeOutcome",
    "PromptTransport",
    "ProtocolFamily",
    "VersionParser",
    "unavailable_reason",
]

AuthStatus = Literal["ok", "missing", "unknown"]
BoundedMode = Literal["safe", "unsupported", "unknown"]
Compatibility = Literal["verified", "warning", "blocked", "unknown"]
ModelSource = Literal["live", "fallback"]
PromptTransport = Literal["stdin_text", "stdin_jsonl", "pi_rpc", "dsh_profile"]
ProtocolFamily = Literal["claude_stream", "json_events", "dsh_profile", "pi_rpc"]
JsonEventsVariant = Literal["codex", "cursor_agent", "opencode"]
EgressKind = Literal["external", "unknown_external"]

UNKNOWN_EXTERNAL_HOST = "unknown.external"
"""The host a definition declares when the exact destination cannot be established before
execution. Host-shaped on purpose: `privacy.policy.is_local_endpoint` treats a value that
starts with `(` as an in-process marker, and this must never read as local."""

DEFAULT_MODEL = "default"
"""The model id meaning "whatever the CLI is configured to use"; no `--model` flag is sent."""


@dataclass(frozen=True, slots=True)
class Probe:
    """One side-effect-free subprocess call: arguments and a bounded timeout."""

    args: tuple[str, ...]
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("a probe timeout must be positive")


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """What one probe produced. `os_error` set means the process never started.

    `truncated` says a stream hit the probe's output cap, so `stdout`/`stderr` are a
    prefix rather than the whole answer: a parser that finds nothing in a truncated
    outcome has learned nothing, not that the CLI said nothing.
    """

    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    os_error: str | None = None
    truncated: bool = False

    @property
    def started(self) -> bool:
        return self.os_error is None

    @property
    def text(self) -> str:
        """stdout and stderr together, for classifiers that read either."""
        return f"{self.stdout}\n{self.stderr}"


@dataclass(frozen=True, slots=True)
class CliModelOption:
    """One model a runtime offers; `reasoning` are the effort names it accepts for it."""

    id: str
    label: str
    reasoning: tuple[str, ...] = ()
    context_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class BoundedPosture:
    """How a runtime is kept from touching anything (spec §12).

    `native_flags`: argv flags deny tools/writes; `native_env`: an environment-injected
    configuration denies them; `none`: no tested posture, so the runtime is never spawned
    for research. `required_help_flags` are substrings the help probe must print for the
    posture to count as proven on the installed version.
    """

    kind: Literal["native_flags", "native_env", "none"]
    help_probe: Probe | None = None
    required_help_flags: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class CliInvocation:
    """Everything a pure argument builder may know about one bounded request.

    No prompt and no research content: those travel through stdin or the RPC channel.
    `schema_path` is the one file the engine writes into the temp cwd.
    """

    model: str | None
    reasoning: str | None
    cwd: Path
    request_id: str
    schema_path: Path | None = None


ArgBuilder = Callable[[CliInvocation], tuple[str, ...]]
VersionParser = Callable[[ProbeOutcome], "str | None"]
AuthClassifier = Callable[[ProbeOutcome], "tuple[AuthStatus, str]"]
ModelParser = Callable[[ProbeOutcome], "tuple[CliModelOption, ...] | None"]


@dataclass(frozen=True, slots=True)
class CliRuntimeDef:
    """One supported CLI, as data (spec §8). See `registry.validate_definition`."""

    id: str
    name: str
    executable: str
    version_probe: Probe
    parse_version: VersionParser
    protocol: ProtocolFamily
    transport: PromptTransport
    build_args: ArgBuilder
    posture: BoundedPosture
    egress: EgressKind
    egress_host: str
    default_context_tokens: int
    login_guidance: str
    upstream_source: str
    fallback_executables: tuple[str, ...] = ()
    auth_probe: Probe | None = None
    classify_auth: AuthClassifier | None = None
    model_probe: Probe | None = None
    parse_models: ModelParser | None = None
    fallback_models: tuple[CliModelOption, ...] = ()
    reasoning_choices: tuple[str, ...] = ()
    json_events_variant: JsonEventsVariant | None = None
    structured_output: bool = True
    verified_versions: tuple[str, ...] = ()
    blocked_versions: tuple[str, ...] = ()
    minimum_version: str | None = None
    env_keep: tuple[str, ...] = ()
    env_drop: tuple[str, ...] = ()
    env_set: Mapping[str, str] = field(default_factory=dict)
    notes: str = ""


class CliModelView(BaseModel):
    """One model choice as a scan reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    reasoning: tuple[str, ...] = ()
    context_tokens: int | None = None


class CliRuntimeStatus(BaseModel):
    """What one scan found for one runtime (spec §10). Never carries a secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime: str
    name: str
    available: bool
    executable: str | None
    """The resolved path with the home directory replaced by `~`."""
    version: str | None
    auth_status: AuthStatus
    auth_guidance: str
    bounded_mode: BoundedMode
    compatibility: Compatibility
    models: tuple[CliModelView, ...]
    model_source: ModelSource
    reasoning_choices: tuple[str, ...]
    egress_kind: EgressKind
    egress_host: str
    diagnostics: tuple[str, ...]
    scanned_at: datetime

    # Both verdicts are computed fields, not plain properties, so a serialized status
    # carries them to the CLI, the Web cockpit, and any JSON consumer without that
    # consumer re-deriving the gates. mypy does not model a decorator stacked on
    # `@property`, hence the documented Pydantic ignore below.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def routable(self) -> bool:
        """Installed, not known to be logged out, provably bounded, not a blocked version."""
        return (
            self.available
            and self.auth_status != "missing"
            and self.bounded_mode == "safe"
            and self.compatibility != "blocked"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unavailable_reason(self) -> str | None:
        """The first failing gate, as `unavailable_reason()` phrases it; `None` when routable."""
        return unavailable_reason(self)


def unavailable_reason(status: CliRuntimeStatus) -> str | None:
    """The first gate that stops this runtime from being routed, as one sentence."""
    label = status.runtime if status.version is None else f"{status.runtime} {status.version}"
    if not status.available:
        return f"{status.runtime} is not installed on this workstation"
    if status.auth_status == "missing":
        return f"{status.runtime} is not logged in: {status.auth_guidance}"
    if status.bounded_mode == "unsupported":
        return f"{label} has no tested bounded (no-tools, read-only) mode"
    if status.bounded_mode == "unknown":
        return f"{label} could not prove a bounded (no-tools, read-only) mode"
    if status.compatibility == "blocked":
        return f"{label} is a known-incompatible version"
    return None

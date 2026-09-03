"""`provider.cli.scan|configure|remove|test`: subscription-backed CLIs (CLI providers spec §16).

One server-side source of truth. The Web settings screen, `research providers …`, and an
MCP host call these handlers and render what comes back; none of them probes an executable
or validates a configuration on its own. Scan is a read that edits nothing; configure and
remove are researcher acts on `research.yaml`; test is a read that causes external egress
and is therefore human-only.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilitySpec
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.privacy.policy import EgressDeniedError, load_policy
from research_harness.privacy.traces import trace_writer_for
from research_harness.providers.cli.detection import scan
from research_harness.providers.cli.errors import redact
from research_harness.providers.cli.registry import RUNTIMES, UnknownRuntimeError, get_runtime
from research_harness.providers.cli.types import CliRuntimeStatus, EgressKind, unavailable_reason
from research_harness.providers.models.base import (
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
    ProviderError,
    StructuredOutputError,
)
from research_harness.providers.models.router import (
    RouterConfig,
    RouterProviderConfig,
    build_router,
)

__all__ = [
    "CLI_PROVIDER_CAPABILITIES",
    "CLI_PROVIDER_CAPABILITY_HANDLERS",
    "EXTERNAL_EGRESS_NOTICE",
    "CliProbeReply",
    "CliProviderConfigured",
    "CliProviderRemoved",
    "CliProviderTestReport",
    "CliScanReport",
    "ConfigureCliProviderRequest",
    "ConfiguredCliProviderView",
    "RemoveCliProviderRequest",
    "ScanCliRuntimesRequest",
    "TestCliProviderRequest",
    "cli_availability",
    "cli_provider_specs",
    "configure_cli_provider",
    "remove_cli_provider",
    "scan_cli_runtimes",
    "test_cli_provider",
]

CLI_PROVIDER_CAPABILITIES: tuple[str, ...] = (
    "provider.cli.scan",
    "provider.cli.configure",
    "provider.cli.remove",
    "provider.cli.test",
)

EXTERNAL_EGRESS_NOTICE = (
    "A local CLI starts on this workstation, but the model it talks to is the vendor's: "
    "research content and object IDs leave the machine when a CLI provider is used."
)

_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


# -- requests and responses ---------------------------------------------------


class ScanCliRuntimesRequest(CapabilityRequest):
    """`provider.cli.scan`: every supported runtime, fresh or from the short cache."""

    rescan: bool = False


class ConfiguredCliProviderView(BaseModel):
    """One `local_cli` entry of `research.yaml`, with today's verdict on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    runtime: str
    model: str
    priority: int
    enabled: bool
    reasoning: str | None = None
    timeout_seconds: float | None = None
    roles: tuple[str, ...] | None = None
    available: bool
    unavailable_reason: str | None = None


class CliScanReport(BaseModel):
    """What one scan found, and what this project has already configured."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scanned_at: datetime
    count: int
    runtimes: tuple[CliRuntimeStatus, ...]
    configured: tuple[ConfiguredCliProviderView, ...]
    notice: str = EXTERNAL_EGRESS_NOTICE


class ConfigureCliProviderRequest(CapabilityRequest):
    """`provider.cli.configure`: add or update one `local_cli` entry in `research.yaml`."""

    name: str = Field(pattern=_NAME)
    runtime: str
    model: str = Field(default="default", min_length=1)
    priority: int = 100
    reasoning: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    roles: list[str] | None = None
    enabled: bool = True


class CliProviderConfigured(BaseModel):
    """The entry as it now stands in `research.yaml`, and whether it is new."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry: ConfiguredCliProviderView
    created: bool
    file: str = "research.yaml"


class RemoveCliProviderRequest(CapabilityRequest):
    """`provider.cli.remove`: drop one `local_cli` entry by name."""

    name: str


class CliProviderRemoved(BaseModel):
    """Which entry was removed, and from which file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    file: str = "research.yaml"


class TestCliProviderRequest(CapabilityRequest):
    """`provider.cli.test`: one minimal request through a configured entry."""

    __test__ = False
    """Named for the capability `provider.cli.test`, not for pytest, which would otherwise
    try to collect this class wherever it is imported. A dunder, so it is not a field."""

    name: str


class CliProviderTestReport(BaseModel):
    """What the test call learned: the destination, the verdict, and why.

    No field can hold a secret: `message` is redacted before it is stored, and the only
    other strings are the entry's own configuration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    runtime: str
    model: str
    version: str | None
    egress_host: str
    egress_kind: EgressKind
    ok: bool
    latency_ms: int | None = None
    message: str
    diagnostic: str | None = None


class CliProbeReply(BaseModel):
    """What `provider.cli.test` asks for: `ok` and the nonce echoed back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    echo: str


# -- helpers -------------------------------------------------------------------


def _entries(ctx: CapabilityContext) -> list[dict[str, Any]]:
    return [dict(item) for item in ctx.repo.config.providers]


def _require_human(ctx: CapabilityContext, capability: str) -> None:
    if not ctx.is_human:
        raise AuthorityError(
            f"{capability}: only a human actor may change or test provider configuration"
        )


def _statuses(*, fresh: bool, only: set[str] | None = None) -> dict[str, CliRuntimeStatus]:
    definitions = [item for item in RUNTIMES.values() if only is None or item.id in only]
    return {status.runtime: status for status in scan(definitions, fresh=fresh)}


def cli_availability(
    entry: RouterProviderConfig, statuses: Mapping[str, CliRuntimeStatus], policy_reason: str | None
) -> tuple[bool, str | None]:
    """Policy first, then the runtime's own gates (spec §11)."""
    if policy_reason is not None:
        return False, f"refused by the privacy policy: {policy_reason}"
    status = statuses.get(entry.runtime or "")
    if status is None:
        return False, f"{entry.runtime} is not a supported runtime"
    reason = unavailable_reason(status)
    return reason is None, reason


def _view(
    entry: RouterProviderConfig, statuses: Mapping[str, CliRuntimeStatus]
) -> ConfiguredCliProviderView:
    available, reason = cli_availability(entry, statuses, None)
    return ConfiguredCliProviderView(
        name=entry.name,
        runtime=entry.runtime or "",
        model=entry.model,
        priority=entry.priority,
        enabled=entry.enabled,
        reasoning=entry.reasoning,
        timeout_seconds=entry.timeout_seconds,
        roles=tuple(entry.roles) if entry.roles is not None else None,
        available=available,
        unavailable_reason=reason,
    )


def _cli_entries(ctx: CapabilityContext) -> list[RouterProviderConfig]:
    config = RouterConfig.model_validate({"providers": _entries(ctx)})
    return [item for item in config.providers if item.kind == "local_cli"]


# -- handlers ------------------------------------------------------------------


def scan_cli_runtimes(ctx: CapabilityContext, request: ScanCliRuntimesRequest) -> CliScanReport:
    """Fresh, bounded, fault-isolated detection of every supported runtime (spec §10)."""
    statuses = _statuses(fresh=request.rescan)
    ordered = tuple(statuses[item.id] for item in RUNTIMES.values())
    configured = tuple(_view(entry, statuses) for entry in _cli_entries(ctx))
    scanned_at = max((item.scanned_at for item in ordered), default=datetime.now(UTC))
    return CliScanReport(
        scanned_at=scanned_at, count=len(ordered), runtimes=ordered, configured=configured
    )


def configure_cli_provider(
    ctx: CapabilityContext, request: ConfigureCliProviderRequest
) -> CliProviderConfigured:
    """Add or update one `local_cli` entry; refuses an unavailable or unsafe runtime.

    Spec §11, §17: an entry that could not be routed today is a configuration the
    researcher would discover only at the next run, so the gates are asked here.
    """
    _require_human(ctx, "provider.cli.configure")
    try:
        definition = get_runtime(request.runtime)
    except UnknownRuntimeError as exc:
        raise CapabilityError(str(exc)) from exc
    status = _statuses(fresh=True, only={definition.id})[definition.id]
    reason = unavailable_reason(status)
    if reason is not None:
        raise CapabilityError(f"cannot configure {request.runtime}: {reason}")

    entry: dict[str, Any] = {
        "name": request.name,
        "kind": "local_cli",
        "runtime": request.runtime,
        "model": request.model,
        "priority": request.priority,
    }
    if request.reasoning is not None:
        entry["reasoning"] = request.reasoning
    if request.timeout_seconds is not None:
        entry["timeout_seconds"] = float(request.timeout_seconds)
    if request.roles is not None:
        entry["roles"] = list(request.roles)
    entry["enabled"] = request.enabled

    current = _entries(ctx)
    created = True
    replaced: list[dict[str, Any]] = []
    for item in current:
        if item.get("name") != request.name:
            replaced.append(item)
            continue
        if item.get("kind") != "local_cli":
            raise CapabilityError(
                f"provider {request.name!r} is an {item.get('kind')} entry; choose another "
                f"name or remove it in research.yaml"
            )
        created = False
        replaced.append(entry)
    if created:
        replaced.append(entry)
    RouterConfig.model_validate({"providers": replaced})  # a bad list never reaches the file
    ctx.repo.update_providers(replaced)
    stored = next(item for item in _cli_entries(ctx) if item.name == request.name)
    return CliProviderConfigured(entry=_view(stored, {definition.id: status}), created=created)


def remove_cli_provider(
    ctx: CapabilityContext, request: RemoveCliProviderRequest
) -> CliProviderRemoved:
    """Remove exactly one `local_cli` entry and nothing else (spec §16)."""
    _require_human(ctx, "provider.cli.remove")
    current = _entries(ctx)
    match = next((item for item in current if item.get("name") == request.name), None)
    if match is None:
        raise CapabilityError(f"no provider named {request.name!r} in research.yaml")
    if match.get("kind") != "local_cli":
        raise CapabilityError(
            f"provider {request.name!r} is an {match.get('kind')} entry; "
            f"`provider.cli.remove` only removes local_cli entries"
        )
    ctx.repo.update_providers([item for item in current if item is not match])
    return CliProviderRemoved(name=request.name)


def test_cli_provider(
    ctx: CapabilityContext, request: TestCliProviderRequest
) -> CliProviderTestReport:
    """One minimal schema-validated request through the configured entry (spec §16, §17)."""
    _require_human(ctx, "provider.cli.test")
    entry = next((item for item in _cli_entries(ctx) if item.name == request.name), None)
    if entry is None:
        raise CapabilityError(f"no local_cli provider named {request.name!r} in research.yaml")
    definition = get_runtime(entry.runtime or "")
    status = _statuses(fresh=True, only={definition.id})[definition.id]
    base: dict[str, Any] = {
        "name": entry.name,
        "runtime": definition.id,
        "model": entry.model,
        "version": status.version,
        "egress_host": definition.egress_host,
        "egress_kind": definition.egress,
    }
    reason = unavailable_reason(status)
    if reason is not None:
        return CliProviderTestReport(**base, ok=False, message=reason, diagnostic="unavailable")

    policy = load_policy(ctx.repo)
    router = build_router(
        RouterConfig.model_validate(
            {"providers": [entry.model_dump(mode="json", exclude_none=True)]}
        ),
        policy=policy,
    )
    refusal = router.egress_refusal()
    if refusal is not None:
        return CliProviderTestReport(
            **base, ok=False, message=refusal.message, diagnostic="privacy_refused"
        )

    nonce = f"provider.cli.test-{os.urandom(4).hex()}"
    probe: ModelRequest[CliProbeReply] = ModelRequest(
        role="provider_test",
        requirements=ModelRequirements(
            structured_output=True, context_tokens=1_000, reasoning="low", max_output_tokens=200
        ),
        instructions=(
            f"This is a connectivity test. Reply with ok=true and set echo to exactly {nonce!r}."
        ),
        inputs=[InputEnvelope(object_id=None, kind="nonce", content=nonce)],
        response_schema=CliProbeReply,
        temperature=0.0,
        metadata={"capability": "provider.cli.test"},
    )
    provider = router.entries[0].provider
    if hasattr(provider, "version"):
        provider.version = status.version
    started = time.perf_counter()
    try:
        response = provider.complete(probe, trace=trace_writer_for(ctx.repo))
    except StructuredOutputError as exc:
        return CliProviderTestReport(
            **base,
            ok=False,
            message=(
                f"the runtime answered, but not with the requested object: {redact(exc.message)}"
            ),
            diagnostic="structured_output",
        )
    except EgressDeniedError as exc:
        return CliProviderTestReport(
            **base, ok=False, message=exc.message, diagnostic="privacy_refused"
        )
    except ProviderError as exc:
        return CliProviderTestReport(
            **base,
            ok=False,
            message=redact(exc.message),
            diagnostic=str(getattr(exc, "diagnostic", "provider_error")),
        )
    latency = int((time.perf_counter() - started) * 1000)
    if response.parsed.echo != nonce or not response.parsed.ok:
        return CliProviderTestReport(
            **base,
            ok=False,
            latency_ms=latency,
            message="the runtime answered a valid object, but did not echo the nonce",
            diagnostic="structured_output",
        )
    return CliProviderTestReport(
        **base,
        ok=True,
        latency_ms=latency,
        message=f"{definition.name} answered through the subscription login in {latency} ms",
    )


# `test_cli_provider` is the handler behind the capability *named* `provider.cli.test`. It is
# not a test, and pytest would otherwise collect it from every module that imports it.
test_cli_provider.__test__ = False  # type: ignore[attr-defined]


# -- registration --------------------------------------------------------------


CLI_PROVIDER_CAPABILITY_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], Any]] = (
    MappingProxyType(
        {
            "provider.cli.scan": scan_cli_runtimes,
            "provider.cli.configure": configure_cli_provider,
            "provider.cli.remove": remove_cli_provider,
            "provider.cli.test": test_cli_provider,
        }
    )
)


def cli_provider_specs() -> list[CapabilitySpec]:
    """The four `provider.cli.*` capabilities, named and permissioned."""
    return [
        CapabilitySpec(
            name="provider.cli.scan",
            summary=(
                "Detect the supported local CLIs: installed, version, login, bounded mode, models."
            ),
            permission=Permission.READ,
            scientific_semantics=(
                "runs local version/login/help probes; edits nothing and sends no research content"
            ),
            request_model=ScanCliRuntimesRequest,
            response_model=CliScanReport,
            handler=scan_cli_runtimes,
        ),
        CapabilitySpec(
            name="provider.cli.configure",
            summary="Add or update one subscription-backed CLI provider entry in research.yaml.",
            permission=Permission.ADMIN,
            scientific_semantics=(
                "changes provider configuration only; writes no research object and no event"
            ),
            request_model=ConfigureCliProviderRequest,
            response_model=CliProviderConfigured,
            handler=configure_cli_provider,
            human_only=True,
        ),
        CapabilitySpec(
            name="provider.cli.remove",
            summary="Remove one subscription-backed CLI provider entry from research.yaml.",
            permission=Permission.ADMIN,
            scientific_semantics=(
                "changes provider configuration only; writes no research object and no event"
            ),
            request_model=RemoveCliProviderRequest,
            response_model=CliProviderRemoved,
            handler=remove_cli_provider,
            human_only=True,
        ),
        CapabilitySpec(
            name="provider.cli.test",
            summary="Run one minimal schema-validated request through a configured CLI provider.",
            permission=Permission.READ,
            scientific_semantics=(
                "sends one test prompt off the workstation under the privacy policy; stages nothing"
            ),
            request_model=TestCliProviderRequest,
            response_model=CliProviderTestReport,
            handler=test_cli_provider,
            human_only=True,
        ),
    ]

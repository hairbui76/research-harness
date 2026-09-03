"""The MCP binding: one tool per named capability, plus read-only resources (ADR-009).

MCP is the primary host integration boundary, and this module is the whole of it. It
contains no research rule and no host-specific behaviour: every tool is generated from a
:class:`~research_harness.capabilities.registry.CapabilitySpec`, advertises that spec's own
JSON schema, and returns the same
:class:`~research_harness.protocol.dto.CapabilityResponse` the HTTP daemon returns. Two
different hosts calling the same tool therefore get the same names, the same schemas, the
same refusals, and the same payloads - which is what Product 29 means by "do not implement
separate business logic per host".

A host is an ``agent_host`` principal (Product 21): it may read the project and stage
proposals, and it asks for approval by leaving something in the review queue. Accepting
evidence over MCP comes back refused, with the same error body HTTP returns. The host's
name is carried as a label for auditing and nothing branches on it.

    server = create_mcp_server(workspace_root)
    server.run("stdio")
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools.base import Tool as McpTool
from mcp.server.mcpserver.utilities.func_metadata import func_metadata

from research_harness import __version__
from research_harness.capabilities.context import open_context
from research_harness.capabilities.permissions import Permission, Principal
from research_harness.capabilities.registry import (
    CapabilityRegistry,
    CapabilitySpec,
    build_default_registry,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.protocol.dto import CapabilityCatalog, CapabilityResponse

__all__ = [
    "DEFAULT_HOST_LABEL",
    "SERVER_NAME",
    "HarnessMcpBridge",
    "capability_for_tool",
    "create_mcp_server",
    "mcp_tool_name",
]

logger = logging.getLogger(__name__)

SERVER_NAME = "research-harness"
DEFAULT_HOST_LABEL = "mcp"
"""What an unnamed host is recorded as. A label for the audit trail, never a branch."""

RESOURCE_SCHEME = "research"


def mcp_tool_name(capability: str) -> str:
    """The MCP tool name for a capability name: dots become underscores, nothing else.

    The mapping is deterministic and total, so a host that has seen `claim.audit` in
    `/capabilities` knows to call `claim_audit` without asking.
    """
    return capability.replace(".", "_")


def capability_for_tool(tool: str, registry: CapabilityRegistry) -> str:
    """The capability a tool name refers to; raises `KeyError` when nothing matches."""
    for name in registry.names():
        if mcp_tool_name(name) == tool:
            return name
    raise KeyError(f"no capability behind MCP tool {tool!r}")


class HarnessMcpBridge:
    """One workspace, one registry, one agent-host principal.

    The bridge is what the MCP tools call, and it is deliberately usable on its own: a
    contract test can compare its answers against the HTTP daemon's without a transport in
    the way, which is exactly the parity ADR-009 requires.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        registry: CapabilityRegistry | None = None,
        host: str = DEFAULT_HOST_LABEL,
    ) -> None:
        self._root = Path(workspace_root)
        self._registry = registry if registry is not None else build_default_registry()
        self._principal = Principal.agent_host(host)

    @property
    def registry(self) -> CapabilityRegistry:
        """The capability registry every tool is generated from."""
        return self._registry

    @property
    def principal(self) -> Principal:
        """The host principal: read and stage, never accept (Product 24, 29)."""
        return self._principal

    def catalog(self) -> CapabilityCatalog:
        """Every capability a host may call, and the names that are not built yet."""
        return CapabilityCatalog.of(self._registry)

    def call(self, capability: str, arguments: Mapping[str, Any]) -> CapabilityResponse:
        """Invoke one capability as the host principal; a refusal is a response, not a raise."""
        try:
            ctx = open_context(self._root, self._principal.actor)
            spec = self._registry.get(capability)
            if spec.permission in {Permission.MUTATE, Permission.ADMIN}:
                # Refused before the workspace lock is taken: a host cannot queue behind a
                # researcher's write only to be told it was never allowed to make one.
                self._principal.authorize(capability, spec.permission, human_only=spec.human_only)
            with _maybe_locked(ctx, spec):
                result = self._registry.invoke(
                    capability, ctx, arguments, principal=self._principal
                )
        except ResearchHarnessError as exc:
            return CapabilityResponse.failed(capability, exc)
        except ValueError as exc:
            return CapabilityResponse.failed(capability, exc)
        return CapabilityResponse.succeeded(capability, result)

    def read(self, capability: str, arguments: Mapping[str, Any]) -> str:
        """A capability's result as a JSON resource body."""
        return _dump(self.call(capability, arguments).model_dump(mode="json"))


class _Locked:
    """Hold the workspace lock for the duration of a mutating call, and nothing else."""

    def __init__(self, ctx: Any, spec: CapabilitySpec) -> None:
        self._ctx = ctx
        self._needed = spec.permission in {Permission.MUTATE, Permission.ADMIN}
        self._lock: Any = None

    def __enter__(self) -> None:
        if self._needed:
            self._lock = self._ctx.repo.lock()
            self._lock.__enter__()

    def __exit__(self, *exc: object) -> None:
        if self._lock is not None:
            self._lock.__exit__(*exc)
            self._lock = None


def _maybe_locked(ctx: Any, spec: CapabilitySpec) -> _Locked:
    return _Locked(ctx, spec)


# -- tool generation ---------------------------------------------------------


def _tool_for(bridge: HarnessMcpBridge, spec: CapabilitySpec) -> McpTool:
    """One MCP tool advertising exactly the registry's request schema.

    The callable's signature is generated from the request model's fields so the SDK can
    validate and dispatch a flat argument object, but the schema a host *reads* is the
    registry's own - so "the MCP schema equals the HTTP schema" is identity, not a copy
    that can drift.
    """
    fields = tuple(spec.request_model.model_fields)

    def call(**arguments: Any) -> dict[str, Any]:
        supplied = {key: value for key, value in arguments.items() if value is not None}
        return bridge.call(spec.name, supplied).model_dump(mode="json")

    call.__name__ = mcp_tool_name(spec.name)
    call.__doc__ = f"{spec.summary} Scientific effect: {spec.scientific_semantics}."
    call.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=Any, default=None)
            for name in fields
        ]
    )
    return McpTool(
        fn=call,
        name=mcp_tool_name(spec.name),
        title=spec.name,
        description=_description(spec),
        parameters=spec.request_model.model_json_schema(),
        fn_metadata=func_metadata(call, structured_output=False),
        is_async=False,
        context_kwarg=None,
        annotations=None,
        meta={
            "capability": spec.name,
            "permission": spec.permission.value,
            "human_only": spec.human_only,
            "long_running": spec.long_running,
        },
    )


def _description(spec: CapabilitySpec) -> str:
    """What the tool does, what it may change, and who has to be asked."""
    lines = [spec.summary, f"Scientific effect: {spec.scientific_semantics}."]
    if spec.permission in {Permission.MUTATE, Permission.ADMIN}:
        lines.append(
            "Changes accepted state, so it is refused for an agent host: propose it and ask "
            "the researcher to accept."
        )
    if spec.long_running:
        lines.append("Returns a durable run id; poll run_status rather than waiting.")
    return " ".join(lines)


def create_mcp_server(
    workspace_root: Path | str,
    *,
    registry: CapabilityRegistry | None = None,
    host: str = DEFAULT_HOST_LABEL,
    bridge: HarnessMcpBridge | None = None,
) -> MCPServer[Any]:
    """The MCP server for one workspace: one tool per capability, plus read-only resources."""
    connector = bridge or HarnessMcpBridge(workspace_root, registry=registry, host=host)
    tools = [_tool_for(connector, spec) for spec in connector.registry]
    server: MCPServer[Any] = MCPServer(
        name=SERVER_NAME,
        title="Research Harness",
        version=__version__,
        instructions=(
            "One local research workspace. Every tool is a named capability with the same "
            "meaning it has on the CLI and the HTTP daemon. You may read the project and "
            "stage proposals; accepting evidence, auditing a claim, and every other change "
            "to accepted state belongs to the researcher, so ask rather than assume. "
            "Conversation is not project knowledge until it is promoted through a capability."
        ),
        tools=tools,
    )
    _register_resources(server, connector)
    return server


def _register_resources(server: MCPServer[Any], bridge: HarnessMcpBridge) -> None:
    """Read-only resources for the objects a host reads most: claims, evidence, the inbox."""

    @server.resource(
        f"{RESOURCE_SCHEME}://inbox",
        name="review-inbox",
        description="The review queue in priority order: what a researcher has to answer.",
        mime_type="application/json",
    )
    def inbox() -> str:
        return bridge.read("review.inbox", {})

    @server.resource(
        f"{RESOURCE_SCHEME}://claims/{{claim_id}}",
        name="claim",
        description="One Claim with the evidence it records, grouped by relation.",
        mime_type="application/json",
    )
    def claim(claim_id: str) -> str:
        return bridge.read("claim.find_support", {"claim_id": claim_id})

    @server.resource(
        f"{RESOURCE_SCHEME}://evidence/{{evidence_id}}",
        name="evidence",
        description="One accepted Evidence object, reopened at its exact source location.",
        mime_type="application/json",
    )
    def evidence(evidence_id: str) -> str:
        return bridge.read("retrieval.resolve_source", {"ref": evidence_id})

    del inbox, claim, evidence  # registered on the server; the local names are not used


def _dump(payload: Any) -> str:
    """Deterministic JSON for a resource body."""
    return json.dumps(payload, indent=2, sort_keys=True, default=str)

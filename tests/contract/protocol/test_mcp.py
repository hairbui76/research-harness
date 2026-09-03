"""Task 10.3: MCP is a binding over the same registry, with no host-specific logic.

The tests here are the ADR-009 invariants made mechanical: the tool list *is* the registry's
name list, each tool's JSON schema *is* the HTTP descriptor's schema, the same call returns
the same payload on both transports, and a host that tries to accept evidence gets the same
refusal it would get over HTTP.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.permissions import PrincipalKind
from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.protocol import mcp as mcp_module
from research_harness.protocol.dto import CapabilityCatalog, CapabilityResponse
from research_harness.protocol.mcp import (
    HarnessMcpBridge,
    capability_for_tool,
    create_mcp_server,
    mcp_tool_name,
)
from tests.contract.protocol.conftest import CLAIM, STATEMENT


def _run(coroutine: Any) -> Any:
    """Drive one SDK coroutine; the server is exercised in process, with no transport."""
    return asyncio.run(coroutine)


@pytest.fixture
def server(workspace: Path, registry: CapabilityRegistry) -> Any:
    return create_mcp_server(workspace, registry=registry)


# -- one surface -------------------------------------------------------------


def test_tool_names_are_the_registry_names(server: Any, registry: CapabilityRegistry) -> None:
    tools = _run(server.list_tools())
    assert {tool.name for tool in tools} == {mcp_tool_name(name) for name in registry.names()}
    for tool in tools:
        assert capability_for_tool(tool.name, registry) in registry


def test_the_tool_name_mapping_is_deterministic_and_reversible(
    registry: CapabilityRegistry,
) -> None:
    assert mcp_tool_name("claim.audit") == "claim_audit"
    names = [mcp_tool_name(name) for name in registry.names()]
    assert len(set(names)) == len(names), "the dot-to-underscore mapping must stay injective"


def test_tool_schemas_are_the_http_descriptors(server: Any, client: TestClient) -> None:
    """The host reads exactly the schema the daemon publishes - not a copy that can drift."""
    catalog = CapabilityCatalog.model_validate(client.get("/capabilities").json())
    by_tool = {mcp_tool_name(item.name): item for item in catalog.capabilities}
    for tool in _run(server.list_tools()):
        assert tool.input_schema == by_tool[tool.name].request_schema


def test_every_tool_declares_its_capability_and_permission(server: Any) -> None:
    for tool in _run(server.list_tools()):
        assert tool.meta is not None
        assert mcp_tool_name(tool.meta["capability"]) == tool.name
        assert tool.meta["permission"] in {"read", "stage", "mutate", "admin"}
        assert tool.description


def test_resources_expose_the_read_only_objects_a_host_needs(server: Any) -> None:
    resources = {str(item.uri) for item in _run(server.list_resources())}
    templates = {item.uri_template for item in _run(server.list_resource_templates())}
    assert "research://inbox" in resources
    assert "research://claims/{claim_id}" in templates
    assert "research://evidence/{evidence_id}" in templates


def test_a_claim_resource_reads_the_same_claim(server: Any) -> None:
    contents = list(_run(server.read_resource(f"research://claims/{CLAIM}")))
    payload = json.loads(str(contents[0].content))
    assert payload["ok"] is True
    assert payload["result"]["statement"] == STATEMENT


# -- host neutrality ---------------------------------------------------------


def test_the_mcp_module_holds_no_host_specific_logic() -> None:
    """Product 29: one integration, not one per vendor."""
    source = Path(inspect.getfile(mcp_module)).read_text(encoding="utf-8").lower()
    assert "claude" not in source
    assert "chatgpt" not in source
    assert "openai" not in source
    assert "anthropic" not in source


@pytest.mark.parametrize("host", ["host-a", "host-b"])
def test_two_hosts_see_the_same_names_and_the_same_answers(
    workspace: Path, registry: CapabilityRegistry, host: str
) -> None:
    bridge = HarnessMcpBridge(workspace, registry=registry, host=host)
    assert bridge.principal.kind is PrincipalKind.AGENT_HOST
    answer = bridge.call("claim.find_support", {"claim_id": str(CLAIM)})
    assert answer.ok
    assert answer.result is not None
    assert answer.result["statement"] == STATEMENT
    assert [item.name for item in bridge.catalog().capabilities] == list(registry.names())


# -- transport parity --------------------------------------------------------


def test_a_read_returns_the_same_payload_on_both_transports(
    bridge: HarnessMcpBridge, host_client: TestClient
) -> None:
    over_http = CapabilityResponse.model_validate(
        host_client.post("/capabilities/claim.find_support", json={"claim_id": str(CLAIM)}).json()
    )
    over_mcp = bridge.call("claim.find_support", {"claim_id": str(CLAIM)})
    assert over_mcp.model_dump(mode="json") == over_http.model_dump(mode="json")


def test_claim_audit_answers_identically_on_both_transports(
    bridge: HarnessMcpBridge, host_client: TestClient
) -> None:
    """`claim.audit` changes accepted state, so both transports refuse an agent host alike."""
    request = {
        "claim_id": str(CLAIM),
        "status": "supported",
        "allowed_strength": "observed_subset",
    }
    over_http = CapabilityResponse.model_validate(
        host_client.post("/capabilities/claim.audit", json=request).json()
    )
    over_mcp = bridge.call("claim.audit", request)
    assert over_mcp.model_dump(mode="json") == over_http.model_dump(mode="json")
    assert over_mcp.error is not None
    assert over_mcp.error.code == "permission_denied"


def test_an_agent_host_accepting_evidence_is_refused_identically(
    bridge: HarnessMcpBridge, host_client: TestClient
) -> None:
    over_http = CapabilityResponse.model_validate(
        host_client.post("/capabilities/evidence.accept", json={}).json()
    )
    over_mcp = bridge.call("evidence.accept", {})
    assert over_mcp.error is not None
    assert over_http.error is not None
    assert over_mcp.error.model_dump() == over_http.error.model_dump()
    assert over_mcp.error.code == "permission_denied"


def test_calling_a_tool_returns_the_capability_response(server: Any) -> None:
    result = _run(server.call_tool("claim_find_support", {"claim_id": str(CLAIM)}))
    payload = json.loads(result.content[0].text)
    assert payload["capability"] == "claim.find_support"
    assert payload["result"]["statement"] == STATEMENT


def test_calling_a_mutating_tool_is_refused_rather_than_erroring(server: Any) -> None:
    """A refusal is an answer the host can act on, not a protocol failure."""
    result = _run(server.call_tool("note_add", {"text": "a host's note"}))
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "permission_denied"


def test_an_agent_host_never_writes_canonical_state(
    bridge: HarnessMcpBridge, workspace: Path
) -> None:
    before = sorted(path.name for path in (workspace / "claims").glob("*.yaml"))
    for name in ("claim.create", "evidence.accept", "state.rebuild", "note.promote"):
        assert bridge.call(name, {}).ok is False
    after = sorted(path.name for path in (workspace / "claims").glob("*.yaml"))
    assert before == after == ["C0001.yaml"]

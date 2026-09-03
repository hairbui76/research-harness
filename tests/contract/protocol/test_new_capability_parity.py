"""The capabilities added for the clients answer identically on HTTP and on MCP (ADR-009).

The gap these close was a *transport* gap, not a missing feature: the Web cockpit could
list Claims because the daemon publishes `GET /index`, and an MCP host could not, because a
route is not a capability. So parity is the property worth pinning, and it is checked three
ways: the tool exists, the schemas are the same object, and the payloads match byte for
byte.

`GET /index` stays, and is asserted to be composed from the same summaries `claim.list`
returns - the route is a convenience over one round trip, never a second answer.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.protocol.mcp import (
    HarnessMcpBridge,
    capability_for_tool,
    create_mcp_server,
    mcp_tool_name,
)

#: Every capability this task added, and a request a fresh workspace can answer.
NEW_CAPABILITIES: dict[str, dict[str, Any]] = {
    "anchor.list": {},
    "claim.list": {},
    "decision.list": {},
    "evidence.list": {},
    "question.list": {},
    "state.index": {},
    "work.list": {},
    # Phase 20. All six `graph.*` reads answer on a workspace whose index has never been
    # built - emptily, and saying so - because `.research/` is disposable and a client
    # that lost it must still get the same answer on both transports (graph spec 8).
    "graph.autocomplete": {"prefix": "C"},
    "graph.neighbors": {"id": "C0001"},
    "graph.provenance": {"id": "C0001"},
    "graph.query": {},
    "graph.resolve": {"reference": "@C0001"},
    "graph.status": {},
    # Phase 21. Three manuscript reads that answer on a workspace with no LaTeX project and
    # no build: an empty tree, a build view that says the audit could not run, and a SyncTeX
    # lookup that says there is no map. "Nothing here yet" has to be the same answer on both
    # transports, because that is the answer a client meets first (LaTeX spec 6, 9).
    "manuscript.files": {},
    "manuscript.build": {},
    "manuscript.synctex": {"file": "main.tex", "line": 1},
    # Phase 18. Listing and searching sessions are reads a host may make; a fresh
    # workspace answers both with nothing, and the nothing has to match on both
    # transports too.
    "session.list": {},
    "session.search": {"query": "latency"},
    # Phase 18. The model catalog is a read of configuration and the egress disclosure, so
    # a workspace with no `providers:` list answers with an empty catalog rather than an
    # error — and answers it the same way to a Web client and to an agent host, which is
    # what lets either of them offer a model selector (v1.1 plan SS0.4).
    "provider.list": {},
}

#: The mutations added for the clients. A host is refused all of them, identically.
NEW_MUTATIONS: dict[str, dict[str, Any]] = {
    "claim.update_coverage": {"claim_id": "C0001", "coverage": {}},
    "manuscript.revalidate": {},
    "review.accept": {"candidate_id": "cand_0000000000000000"},
    "review.defer": {"candidate_id": "cand_0000000000000000", "note": "later"},
    "review.edit": {"candidate_id": "cand_0000000000000000", "edited": {}},
    "review.qualify": {"candidate_id": "cand_0000000000000000", "qualification": "x"},
    "review.reject": {"candidate_id": "cand_0000000000000000", "reason": "x"},
    "review.request_more": {"candidate_id": "cand_0000000000000000", "note": "x"},
    "review.split": {"candidate_id": "cand_0000000000000000", "interpretation": "a reading"},
    "work.update_metadata": {"work": "W0001"},
    # Phase 19. Attaching bytes and promoting them are researcher acts on both transports:
    # a host may read `attachment.check_send` and `attachment.resolve_identity` and must
    # ask a person to attach or to save anything to the corpus (Product 24, 29).
    "attachment.add": {"session": "CS0001", "path": "missing.pdf"},
    "attachment.remove": {"session": "CS0001", "attachment": "SA0001"},
    "attachment.save_to_corpus": {"session": "CS0001", "attachment": "SA0001"},
    # Phase 21. Saving a manuscript file, running a compiler, and applying a candidate diff
    # are researcher acts: source ownership is the researcher's (LaTeX spec 4). A host may
    # read the manuscript and stage a `manuscript.suggest` candidate, and asks a person to
    # apply it.
    "manuscript.write_file": {
        "path": "main.tex",
        "content": "x",
        "expected_hash": f"sha256:{'0' * 64}",
    },
    "manuscript.compile": {},
    "manuscript.apply_suggestion": {"candidate_id": "run_20260101T000000Z_deadbeef"},
    # Phase 18. Conversation is the researcher's private working context (Product 39):
    # a host may read a transcript and may not write one, stop one, summarize one, or
    # promote out of one, on either transport.
    "session.create": {"title": "from a host"},
    "session.rename": {"session": "CS0001", "title": "renamed"},
    "session.summarize": {"session": "CS0001"},
    "session.send": {"session": "CS0001", "text": "hello"},
    "session.stop": {"run_id": "run_20260101T000000Z_deadbeef"},
    "session.retry": {"message": "M0001"},
    "session.promote": {"session": "CS0001", "message": "M0001", "target": "note"},
}

ALL_NEW = sorted(
    {
        *NEW_CAPABILITIES,
        *NEW_MUTATIONS,
        "review.candidate",
        "manuscript.anchors",
        "manuscript.trace",
        "attachment.check_send",
        "attachment.resolve_identity",
        "manuscript.read_file",
        "manuscript.suggest",
        # These need a session (and, for `context.get`, a recorded receipt) that already
        # exists, so they are discovered here and exercised in
        # `tests/contract/capabilities/test_conversation.py`.
        "session.get",
        "context.preview",
        "context.get",
    }
)


def http(client: TestClient, name: str, request: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = client.post(f"/capabilities/{name}", json=request).json()
    return body


def tools(workspace: Path, registry: CapabilityRegistry) -> list[Any]:
    """The MCP tool list, driven in process with no transport in the way."""
    server = create_mcp_server(workspace, registry=registry)
    return list(asyncio.run(server.list_tools()))


# -- discovery ---------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_NEW)
def test_every_new_capability_is_in_the_daemon_catalog(client: TestClient, name: str) -> None:
    catalog = client.get("/capabilities").json()
    assert name in {item["name"] for item in catalog["capabilities"]}


@pytest.mark.parametrize("name", ALL_NEW)
def test_every_new_capability_is_an_mcp_tool(
    workspace: Path, registry: CapabilityRegistry, name: str
) -> None:
    """A host discovers by tool name; the mapping is deterministic and total."""
    published = {tool.name for tool in tools(workspace, registry)}
    assert mcp_tool_name(name) in published
    assert capability_for_tool(mcp_tool_name(name), registry) == name


@pytest.mark.parametrize("name", ALL_NEW)
def test_the_two_transports_advertise_the_same_request_schema(
    client: TestClient, workspace: Path, registry: CapabilityRegistry, name: str
) -> None:
    """Identity, not a copy: both read the registry descriptor."""
    tool = next(item for item in tools(workspace, registry) if item.name == mcp_tool_name(name))
    catalog = client.get("/capabilities").json()
    descriptor = next(item for item in catalog["capabilities"] if item["name"] == name)
    assert tool.input_schema == descriptor["request_schema"]


# -- the same answers --------------------------------------------------------


@pytest.mark.parametrize("name", sorted(NEW_CAPABILITIES))
def test_a_read_answers_identically_over_http_and_mcp(
    client: TestClient, bridge: HarnessMcpBridge, name: str
) -> None:
    over_http = http(client, name, NEW_CAPABILITIES[name])
    over_mcp = bridge.call(name, NEW_CAPABILITIES[name]).model_dump(mode="json")

    assert over_http["ok"] is True, over_http
    assert over_mcp["ok"] is True, over_mcp
    assert over_http["result"] == over_mcp["result"]


def test_claim_list_and_the_index_route_report_the_same_claims(
    client: TestClient, bridge: HarnessMcpBridge
) -> None:
    """`GET /index` is one round trip over the list capabilities, not a second answer."""
    index = client.get("/index").json()
    listed = bridge.call("claim.list", {}).model_dump(mode="json")["result"]

    assert index["claims"] == list(listed["claims"])
    assert listed["count"] == len(index["claims"])


def test_state_index_returns_exactly_what_the_index_route_returns(
    client: TestClient, bridge: HarnessMcpBridge
) -> None:
    """An MCP host with no HTTP routes still gets the whole navigation in one call."""
    route = client.get("/index").json()
    capability = bridge.call("state.index", {}).model_dump(mode="json")["result"]

    assert json.dumps(route, sort_keys=True) == json.dumps(capability, sort_keys=True)


# -- refusals are identical too ---------------------------------------------


@pytest.mark.parametrize("name", sorted(NEW_MUTATIONS))
def test_an_agent_host_is_refused_every_new_mutation_the_same_way(
    host_client: TestClient, bridge: HarnessMcpBridge, name: str
) -> None:
    """Product 24, 29: a host reads and proposes; the researcher accepts."""
    over_http = http(host_client, name, NEW_MUTATIONS[name])
    over_mcp = bridge.call(name, NEW_MUTATIONS[name]).model_dump(mode="json")

    assert over_http["ok"] is False
    assert over_mcp["ok"] is False
    assert over_http["error"]["code"] == "permission_denied"
    assert over_mcp["error"] == over_http["error"]


@pytest.mark.parametrize("name", sorted(NEW_MUTATIONS))
def test_the_new_mutations_are_marked_human_only_in_both_catalogs(
    client: TestClient, registry: CapabilityRegistry, name: str
) -> None:
    spec = registry.get(name)
    descriptor = next(
        item for item in client.get("/capabilities").json()["capabilities"] if item["name"] == name
    )
    assert spec.permission in {Permission.MUTATE, Permission.STAGE}
    assert descriptor["human_only"] is True


def test_review_candidate_reports_a_missing_candidate_the_same_way_as_the_route(
    client: TestClient, bridge: HarnessMcpBridge
) -> None:
    """`GET /candidates/{id}` and `review.candidate` are the same read behind one function."""
    route = client.get("/candidates/cand_0000000000000000")
    capability = bridge.call(
        "review.candidate", {"candidate_id": "cand_0000000000000000"}
    ).model_dump(mode="json")

    assert route.status_code == 404
    assert capability["ok"] is False
    assert capability["error"]["code"] == "object_not_found"

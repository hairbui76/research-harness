"""Task 10.2: the local daemon exposes the capability registry and nothing else.

Three acceptance requirements are checked here, plus the authority model that makes the
daemon safe to leave running: the API never exposes arbitrary SQLite mutation, workspace
mutations are serialized, and a long workflow returns a durable run id instead of holding
the connection.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.extra_handlers import _start_in_background
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.protocol.dto import CapabilityCatalog, CapabilityResponse
from research_harness.protocol.http import HarnessHttpClient
from research_harness.server.app import DAEMON_TOKEN_FILENAME, create_app, ensure_token, token_path
from research_harness.workflows.engine import StageBase, Workflow
from tests.contract.protocol.conftest import CLAIM, STATEMENT

#: Every route the daemon publishes. The list is asserted whole: a new route is a
#: deliberate widening of the write surface, not something that appears by accident.
EXPECTED_ROUTES: set[tuple[str, frozenset[str]]] = {
    ("/health", frozenset({"GET"})),
    ("/capabilities", frozenset({"GET"})),
    ("/capabilities/{name}", frozenset({"POST"})),
    ("/runs/{run_id}", frozenset({"GET"})),
    ("/runs/{run_id}/cancel", frozenset({"POST"})),
    ("/objects/{object_id}", frozenset({"GET"})),
    # Phase 11 added five reads for the Web cockpit. Every one of them is a GET, and none
    # of them writes: the write surface is still `POST /capabilities/{name}` alone.
    ("/artifacts/{artifact_id}/bytes", frozenset({"GET"})),
    ("/candidates/{candidate_id}", frozenset({"GET"})),
    ("/index", frozenset({"GET"})),
    ("/blocks/{artifact_id}", frozenset({"GET"})),
    ("/overview", frozenset({"GET"})),
    # Wave 3K adds three more composed reads for the cockpit. Which group an object belongs
    # in, which order the groups are read in, and the words a count is stated inside are
    # scientific judgements, so they are decided here rather than in React (Product 5 P10) -
    # and, like every read above, none of them writes.
    ("/stale", frozenset({"GET"})),
    ("/taxonomy", frozenset({"GET"})),
    ("/synthesis", frozenset({"GET"})),
    # Phase 19 added the attachment surface. The POST is the *one* documented write that is
    # not a capability call (v1.1 plan §0.4): it writes session-only bytes through the same
    # `AttachmentService.add` that `attachment.add` calls, is authorised as that capability
    # is, and can create no Work, Artifact, Evidence, or Claim. The two GETs are byte reads.
    ("/sessions/{session_id}/attachments", frozenset({"POST"})),
    ("/sessions/{session_id}/attachments/{attachment_id}/bytes", frozenset({"GET"})),
    ("/sessions/{session_id}/attachments/{attachment_id}/preview", frozenset({"GET"})),
    # Phase 21 adds one read: a PDF cannot be carried in JSON, so the compiled build is
    # streamed the way artifact bytes are. `latest` and `last-good` are accepted as build
    # ids. There is deliberately no route that writes a manuscript file - saving is
    # `manuscript.write_file` and applying a diff is `manuscript.apply_suggestion`.
    ("/manuscript/builds/{build_id}/pdf", frozenset({"GET"})),
    # Phase 18 adds the run event stream. It is a GET and a *read* of what `session.send`
    # already persisted, so the daemon still publishes no route that appends to a
    # transcript: sending is the capability, and watching it arrive is a read.
    ("/runs/{run_id}/events", frozenset({"GET"})),
}


#: FastAPI's own documentation endpoints; read-only and not part of the capability surface.
DOCUMENTATION_ROUTES = ("/openapi", "/docs", "/redoc")


def _routes(app: Any) -> set[tuple[str, frozenset[str]]]:
    return {
        (route.path, frozenset(route.methods) - {"HEAD"})
        for route in app.routes
        if getattr(route, "methods", None) and not route.path.startswith(DOCUMENTATION_ROUTES)
    }


# -- discovery ---------------------------------------------------------------


def test_health_names_the_workspace_it_serves(client: TestClient, workspace: Path) -> None:
    body = client.get("/health").json()
    assert body["ok"] is True
    assert Path(body["workspace"]) == workspace.resolve()
    assert body["review_policy"] == "strict"


def test_capabilities_are_the_registry_descriptors(
    client: TestClient, registry: CapabilityRegistry
) -> None:
    catalog = CapabilityCatalog.model_validate(client.get("/capabilities").json())
    assert [item.name for item in catalog.capabilities] == list(registry.names())
    assert catalog.capabilities == tuple(registry.describe())
    assert {item.name for item in catalog.planned} == {item.name for item in registry.planned()}


def test_the_api_publishes_no_route_that_writes_outside_a_capability(workspace: Path) -> None:
    """ADR-004: no `execute_sql`, no file write, no object patch - only named capabilities."""
    app = create_app(workspace)
    assert _routes(app) == EXPECTED_ROUTES


def test_no_capability_accepts_sql(client: TestClient) -> None:
    catalog = CapabilityCatalog.model_validate(client.get("/capabilities").json())
    for descriptor in catalog.capabilities:
        properties = set(descriptor.request_schema.get("properties", {}))
        assert not {"sql", "query_sql", "statement_sql"} & properties
        assert "sql" not in descriptor.name


def test_an_unknown_capability_is_a_404_with_a_stable_code(client: TestClient) -> None:
    response = client.post("/capabilities/execute_sql", json={"sql": "DROP TABLE claims"})
    assert response.status_code == 404
    body = CapabilityResponse.model_validate(response.json())
    assert body.ok is False
    assert body.error is not None
    assert body.error.code == "capability_not_found"


# -- authority ---------------------------------------------------------------


def test_the_token_lives_under_the_research_directory_and_not_in_canonical_state(
    workspace: Path,
) -> None:
    ensure_token(workspace)
    path = token_path(workspace)
    assert path.name == DAEMON_TOKEN_FILENAME
    assert path.parent.name == ".research"
    assert path.read_text(encoding="utf-8").strip()


def test_the_token_is_stable_across_restarts(workspace: Path) -> None:
    assert ensure_token(workspace) == ensure_token(workspace)


def test_the_researcher_may_mutate_and_an_agent_host_may_not(
    client: TestClient, host_client: TestClient
) -> None:
    accepted = client.post("/capabilities/note.add", json={"text": "the researcher's note"})
    assert accepted.status_code == 200
    assert CapabilityResponse.model_validate(accepted.json()).ok

    refused = host_client.post("/capabilities/note.add", json={"text": "a host's note"})
    assert refused.status_code == 403
    body = CapabilityResponse.model_validate(refused.json())
    assert body.ok is False
    assert body.error is not None
    assert body.error.code == "permission_denied"


def test_an_agent_host_may_still_read(host_client: TestClient) -> None:
    response = host_client.post("/capabilities/claim.find_support", json={"claim_id": str(CLAIM)})
    assert response.status_code == 200
    body = CapabilityResponse.model_validate(response.json())
    assert body.ok
    assert body.result is not None
    assert body.result["statement"] == STATEMENT


def test_an_invalid_request_is_refused_with_its_field_errors(client: TestClient) -> None:
    response = client.post("/capabilities/claim.find_support", json={"claim_id": 17})
    assert response.status_code == 422
    body = CapabilityResponse.model_validate(response.json())
    assert body.error is not None
    assert body.error.code == "invalid_request"


# -- objects -----------------------------------------------------------------


def test_objects_are_read_through_the_repository(client: TestClient) -> None:
    body = client.get(f"/objects/{CLAIM}").json()
    assert body["kind"] == "claim"
    assert body["object"]["statement"] == STATEMENT


def test_objects_has_no_write_counterpart(client: TestClient) -> None:
    assert client.post(f"/objects/{CLAIM}", json={"statement": "rewritten"}).status_code == 405
    assert client.put(f"/objects/{CLAIM}", json={}).status_code == 405
    assert client.delete(f"/objects/{CLAIM}").status_code == 405


def test_an_unknown_object_is_a_404(client: TestClient) -> None:
    assert client.get("/objects/C9999").status_code == 404
    assert client.get("/objects/not-an-id").status_code == 404


# -- serialization and runs --------------------------------------------------


def test_concurrent_mutations_are_serialized(workspace: Path, token: str) -> None:
    """Product 8.2: one accepted-state mutation at a time, whoever asked for it."""
    with TestClient(create_app(workspace)) as client:
        client.headers["Authorization"] = f"Bearer {token}"

        def add(index: int) -> int:
            response = client.post("/capabilities/note.add", json={"text": f"note {index}"})
            return response.status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(add, range(8)))

    assert statuses == [200] * 8
    events = [
        json.loads(line)
        for line in (workspace / "events" / "research.jsonl").read_text().splitlines()
        if line.strip()
    ]
    captured = [event for event in events if event["event"] == "note.captured"]
    assert len(captured) == 8
    assert len({event["payload"]["note"] for event in captured}) == 8


def test_long_running_capabilities_declare_a_run_id_instead_of_a_result(
    registry: CapabilityRegistry,
) -> None:
    """ADR-009: a long workflow never requires an open connection."""
    long_running = [spec for spec in registry if spec.long_running]
    assert {spec.name for spec in long_running} >= {"work.interrogate", "evidence.verify"}
    for spec in long_running:
        assert "run_id" in spec.response_model.model_fields
        # Proposal work a host may start is `stage`. Phase 18 adds a long call that is not
        # proposal work at all — a conversation send writes the researcher's own private
        # transcript — so it is `mutate` and human-only. Either way the answer is a durable
        # run id rather than a held connection, which is what ADR-009 is about.
        assert spec.permission in {Permission.STAGE, Permission.MUTATE}
        assert spec.permission is Permission.STAGE or spec.descriptor().human_only


def test_an_unknown_run_is_a_404(client: TestClient) -> None:
    assert client.get("/runs/20260101-000000-abcdef").status_code == 404


class _Blocking(StageBase):
    """A stage that stops until the test releases it, so the run is observably in flight."""

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        super().__init__("block")
        self._started = started
        self._release = release

    def run(self, ctx: Any) -> dict[str, Any]:
        del ctx
        self._started.set()
        assert self._release.wait(timeout=10), "the test never released the stage"
        return {"done": True}


def test_a_long_run_is_durable_before_the_call_returns(client: TestClient, project: Any) -> None:
    """Task 10.2: the run id comes back immediately and the record outlives the request."""
    started, release = threading.Event(), threading.Event()
    workflow = Workflow(name="contract-long", version="1", stages=[_Blocking(started, release)])
    try:
        run = _start_in_background(project, "work.interrogate", workflow, {"probe": True})
        assert started.wait(timeout=10)

        in_flight = client.get(f"/runs/{run.run_id}").json()
        assert in_flight["run_id"] == run.run_id
        assert in_flight["workflow"] == "contract-long"

        cancelled = client.post(f"/runs/{run.run_id}/cancel").json()
        assert cancelled["cancel_requested"] is True
    finally:
        release.set()


# -- the typed client --------------------------------------------------------


def test_the_typed_client_speaks_the_same_envelopes(client: TestClient, token: str) -> None:
    del token
    harness = HarnessHttpClient(client=client)
    assert harness.health().ok
    assert harness.capabilities().capabilities
    answer = harness.invoke("claim.find_support", {"claim_id": str(CLAIM)})
    assert answer.ok
    assert answer.result is not None
    assert answer.result["claim"] == str(CLAIM)
    assert harness.object(str(CLAIM)).kind == "claim"


def test_the_typed_client_reports_a_refusal_rather_than_raising(host_client: TestClient) -> None:
    harness = HarnessHttpClient(client=host_client)
    answer = harness.invoke("evidence.accept", {})
    assert answer.ok is False
    assert answer.error is not None
    assert answer.error.code == "permission_denied"


@pytest.mark.parametrize("name", ["state.rebuild", "review.accept_batch", "evidence.accept"])
def test_agent_hosts_are_refused_every_accepted_state_capability(
    host_client: TestClient, name: str
) -> None:
    response = host_client.post(f"/capabilities/{name}", json={})
    assert response.status_code == 403

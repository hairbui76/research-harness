"""`GET /runs/{run_id}/events` answers exactly the frames of implementation plan SS0.4.

The Web client is written against this contract, so it is asserted literally: the event
names, the keys of each `data:` object, the terminal states, and the rule that the stream
ends after a terminal `status`. A run that already finished replays its deltas and then
that status, which is the reconnection story ("read `session.get` and reconcile") made
cheap.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.conversation.send import ScriptedProviders
from research_harness.conversation.service import ConversationService
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.models.base import ProviderTransportError
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.server.app import create_app, ensure_token
from research_harness.server.routes_sessions import EVENT_MEDIA_TYPE, sse_frame
from research_harness.workspace.repository import WorkspaceRepository

ANSWER = "Batching reduced tail latency by nine percent across the pilot corpus."

DELTA_KEYS = {"message_id", "attempt", "text"}
STATUS_KEYS = {"run_id", "state", "message_id", "attempt", "context_pack_id", "detail"}
ERROR_KEYS = {"code", "message", "retryable"}
TERMINAL = {"succeeded", "failed", "cancelled", "incomplete"}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    WorkspaceRepository.init(tmp_path / "project", "session-events")
    return tmp_path / "project"


@pytest.fixture
def ctx(workspace: Path) -> CapabilityContext:
    return open_context(workspace, HUMAN_ACTOR)


@pytest.fixture(scope="session")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def client(workspace: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    token = ensure_token(workspace)
    with TestClient(create_app(workspace, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


@pytest.fixture
def host_client(workspace: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    with TestClient(create_app(workspace, registry=registry)) as test_client:
        yield test_client


def finished_run(ctx: CapabilityContext, provider: ScriptedProvider) -> tuple[str, str, str]:
    """Run one send to completion in process; return run id, message id, pack id."""
    service = ConversationService(ctx, providers=ScriptedProviders(provider, chunk_words=3))
    session = service.create("Latency study")
    started = service.send(session.id, "What did we learn about latency?", background=False)
    return started.run_id, str(started.assistant_message), str(started.context_pack)


def frames(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse an SSE body into `(event, data)` pairs, refusing anything malformed."""
    parsed: list[tuple[str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        assert lines[0].startswith("event: "), block
        assert lines[1].startswith("data: "), block
        assert len(lines) == 2, "one event and one data line per frame"
        parsed.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return parsed


# -- the frame contract ------------------------------------------------------


def test_a_finished_run_replays_its_deltas_and_then_the_terminal_status(
    ctx: CapabilityContext, client: TestClient
) -> None:
    run_id, message, pack = finished_run(ctx, ScriptedProvider([{"text": ANSWER}]))

    response = client.get(f"/runs/{run_id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(EVENT_MEDIA_TYPE)

    events = frames(response.text)
    kinds = [name for name, _ in events]
    assert kinds[-1] == "status", "the stream ends after a terminal status"
    assert kinds[:-1] == ["delta"] * (len(kinds) - 1)

    deltas = [payload for name, payload in events if name == "delta"]
    assert len(deltas) > 1
    assert "".join(str(item["text"]) for item in deltas) == ANSWER
    for payload in deltas:
        assert set(payload) == DELTA_KEYS
        assert payload["message_id"] == message
        assert payload["attempt"] == 1

    status = events[-1][1]
    assert set(status) == STATUS_KEYS
    assert status == {
        "run_id": run_id,
        "state": "succeeded",
        "message_id": message,
        "attempt": 1,
        "context_pack_id": pack,
        "detail": None,
    }


def test_a_failed_run_reports_an_error_frame_before_its_terminal_status(
    ctx: CapabilityContext, client: TestClient
) -> None:
    run_id, message, _ = finished_run(
        ctx, ScriptedProvider([ProviderTransportError("no route to host")])
    )

    events = frames(client.get(f"/runs/{run_id}/events").text)
    kinds = [name for name, _ in events]
    assert kinds == ["error", "status"]

    error = events[0][1]
    assert set(error) == ERROR_KEYS
    assert error["code"] == "provider_unavailable"
    assert error["retryable"] is True
    assert "no route to host" in str(error["message"])

    status = events[1][1]
    assert status["state"] == "failed"
    assert status["message_id"] == message


def test_every_terminal_state_ends_the_stream(ctx: CapabilityContext, client: TestClient) -> None:
    run_id, _, _ = finished_run(ctx, ScriptedProvider([{"text": ANSWER}]))
    events = frames(client.get(f"/runs/{run_id}/events").text)
    assert str(events[-1][1]["state"]) in TERMINAL


def test_after_replays_only_what_the_client_has_not_seen(
    ctx: CapabilityContext, client: TestClient
) -> None:
    run_id, _, _ = finished_run(ctx, ScriptedProvider([{"text": ANSWER}]))
    whole = frames(client.get(f"/runs/{run_id}/events").text)
    resumed = frames(client.get(f"/runs/{run_id}/events?after=2").text)

    assert len(resumed) == len(whole) - 2
    assert resumed[-1] == whole[-1], "the terminal status is always sent"


def test_the_stream_and_the_transcript_hold_the_same_text(
    ctx: CapabilityContext, client: TestClient
) -> None:
    """Plan SS0.4: a client that reconnects reads the same content from `session.get`."""
    run_id, message, _ = finished_run(ctx, ScriptedProvider([{"text": ANSWER}]))
    streamed = "".join(
        str(payload["text"])
        for name, payload in frames(client.get(f"/runs/{run_id}/events").text)
        if name == "delta"
    )

    service = ConversationService(ctx)
    sessions = service.sessions()
    page = service.transcript(sessions[0].id)
    answer = next(item for item in page.messages if str(item.id) == message)
    assert answer.text() == streamed


# -- authority and errors ----------------------------------------------------


def test_an_unknown_run_is_a_404(client: TestClient) -> None:
    response = client.get("/runs/run_20260101T000000Z_deadbeef/events")
    assert response.status_code == 404


def test_an_agent_host_may_watch_a_run(ctx: CapabilityContext, host_client: TestClient) -> None:
    """Watching an answer arrive is a read; it is not authority to have asked for it."""
    run_id, _, _ = finished_run(ctx, ScriptedProvider([{"text": ANSWER}]))
    response = host_client.get(f"/runs/{run_id}/events")
    assert response.status_code == 200
    assert [name for name, _ in frames(response.text)][-1] == "status"


def test_the_events_route_is_a_get_only(client: TestClient) -> None:
    assert client.post("/runs/anything/events").status_code == 405


# -- the frame writer --------------------------------------------------------


def test_a_frame_is_one_event_line_one_data_line_and_a_blank_line() -> None:
    rendered = sse_frame("delta", {"message_id": "M0042", "attempt": 1, "text": "hi"})
    assert rendered == (
        'event: delta\ndata: {"attempt": 1, "message_id": "M0042", "text": "hi"}\n\n'
    )

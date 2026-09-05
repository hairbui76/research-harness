"""How the prompt reaches each runtime, and how a run is asked to stop (spec §12, §14)."""

from __future__ import annotations

import json
from pathlib import Path

from research_harness.providers.cli.parsers import CliEvent
from research_harness.providers.cli.transport import (
    DshProfileTransport,
    PiRpcTransport,
    StdinJsonlTransport,
    StdinTextTransport,
    transport_for,
)
from research_harness.providers.cli.types import CliInvocation
from tests.unit.providers.cli.test_registry import definition

CWD = Path("/tmp/rh-cli-x")


class FakeProcess:
    def __init__(self) -> None:
        self.written: list[str] = []
        self.closed = False

    def write(self, text: str) -> None:
        self.written.append(text)

    def close_stdin(self) -> None:
        self.closed = True


def invocation(**overrides: object) -> CliInvocation:
    values: dict[str, object] = {
        "model": None,
        "reasoning": None,
        "cwd": CWD,
        "request_id": "req-1",
    }
    values.update(overrides)
    return CliInvocation(**values)  # type: ignore[arg-type]


def test_plain_stdin_writes_the_prompt_and_closes() -> None:
    process = FakeProcess()
    StdinTextTransport().start(process, "the prompt", invocation())  # type: ignore[arg-type]
    assert process.written == ["the prompt"] and process.closed


def test_jsonl_stdin_writes_one_user_message_and_closes() -> None:
    process = FakeProcess()
    StdinJsonlTransport().start(process, "the prompt", invocation())  # type: ignore[arg-type]
    assert json.loads(process.written[0])["message"]["content"][0]["text"] == "the prompt"
    assert process.closed


def test_pi_sends_a_prompt_command_keeps_stdin_open_and_aborts_on_cancel() -> None:
    process = FakeProcess()
    transport = PiRpcTransport()
    transport.start(process, "the prompt", invocation())  # type: ignore[arg-type]
    assert json.loads(process.written[0]) == {
        "id": "req-1",
        "type": "prompt",
        "message": "the prompt",
    }
    assert not process.closed
    transport.cancel(process)  # type: ignore[arg-type]
    assert json.loads(process.written[-1]) == {"id": "req-1-abort", "type": "abort"}


def test_pi_answers_an_extension_ui_request_with_cancelled_and_swallows_it() -> None:
    process = FakeProcess()
    transport = PiRpcTransport()
    line = json.dumps({"type": "extension_ui_request", "id": "ui-1", "method": "confirm"})
    assert transport.intercept(process, line)  # type: ignore[arg-type]
    assert json.loads(process.written[-1]) == {
        "type": "extension_ui_response",
        "id": "ui-1",
        "cancelled": True,
    }
    assert not transport.intercept(process, json.dumps({"type": "agent_start"}))  # type: ignore[arg-type]


def test_dsh_waits_for_ready_then_sends_execute_with_no_mcp_servers() -> None:
    process = FakeProcess()
    transport = DshProfileTransport()
    transport.start(
        process, "the prompt", invocation(model="deepseek/deepseek-v3", reasoning="high")
    )  # type: ignore[arg-type]
    assert process.written == [], "nothing is sent before the runtime says ready"
    transport.observe(process, CliEvent(kind="status", status="ready"))  # type: ignore[arg-type]
    command = json.loads(process.written[0])
    assert command == {
        "v": 1,
        "type": "execute",
        "request_id": "req-1",
        "cwd": str(CWD),
        "prompt": "the prompt",
        "mcp_servers": [],
        "model": {"provider": "deepseek", "id": "deepseek-v3"},
        "reasoning_effort": "high",
    }
    transport.cancel(process)  # type: ignore[arg-type]
    assert json.loads(process.written[-1]) == {"v": 1, "type": "cancel", "request_id": "req-1"}


def test_dsh_omits_model_and_reasoning_when_default() -> None:
    process = FakeProcess()
    transport = DshProfileTransport()
    transport.start(process, "p", invocation())  # type: ignore[arg-type]
    transport.observe(process, CliEvent(kind="status", status="ready"))  # type: ignore[arg-type]
    assert set(json.loads(process.written[0])) == {
        "v",
        "type",
        "request_id",
        "cwd",
        "prompt",
        "mcp_servers",
    }


def test_transport_for_follows_the_definition() -> None:
    assert isinstance(transport_for(definition(transport="stdin_text")), StdinTextTransport)
    assert isinstance(
        transport_for(
            definition(protocol="claude_stream", json_events_variant=None, transport="stdin_jsonl")
        ),
        StdinJsonlTransport,
    )
    assert isinstance(
        transport_for(definition(protocol="pi_rpc", json_events_variant=None, transport="pi_rpc")),
        PiRpcTransport,
    )
    assert isinstance(
        transport_for(
            definition(protocol="dsh_profile", json_events_variant=None, transport="dsh_profile")
        ),
        DshProfileTransport,
    )

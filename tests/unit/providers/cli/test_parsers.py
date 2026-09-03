"""Every vendor stream becomes the same small vocabulary (CLI providers spec §13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.providers.cli.parsers import PARSERS, CliEvent, EventParser, parser_for
from research_harness.providers.cli.parsers.claude_stream import ClaudeStreamParser
from research_harness.providers.cli.parsers.dsh_profile import DshProfileParser
from research_harness.providers.cli.parsers.json_events import JsonEventsParser
from research_harness.providers.cli.parsers.pi_rpc import PiRpcParser
from research_harness.providers.cli.registry import RUNTIMES

STREAMS = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "cli" / "streams"
CANONICAL = (
    '{"supported": true, "confidence": 0.82, "rationale": "Table 3 states the throughput '
    'directly.", "evidence_ids": ["ev-001", "ev-002"]}'
)


def run(parser: EventParser, name: str) -> list[CliEvent]:
    events: list[CliEvent] = []
    for line in (STREAMS / name).read_text(encoding="utf-8").splitlines():
        events.extend(parser.feed(line))
    events.extend(parser.finish())
    return events


def kinds(events: list[CliEvent]) -> list[str]:
    return [event.kind for event in events]


def text_of(events: list[CliEvent]) -> str:
    finals = [event.text for event in events if event.kind == "final_text"]
    return finals[-1] if finals else "".join(e.text for e in events if e.kind == "text_delta")


SUCCESS = [
    ("claude-success.jsonl", ClaudeStreamParser, "claude-opus-5"),
    ("amp-success.jsonl", ClaudeStreamParser, "amp-smart"),
    ("codex-success.jsonl", lambda: JsonEventsParser("codex"), None),
    ("cursor-success.jsonl", lambda: JsonEventsParser("cursor_agent"), "sonnet-4"),
    ("opencode-success.jsonl", lambda: JsonEventsParser("opencode"), None),
    ("dsh-success.jsonl", DshProfileParser, "deepseek-v3"),
    ("pi-success.jsonl", PiRpcParser, "anthropic/claude-sonnet-4-5"),
]


@pytest.mark.parametrize(("name", "factory", "model"), SUCCESS, ids=[case[0] for case in SUCCESS])
def test_a_successful_stream_yields_the_answer_usage_and_a_terminal_event(
    name: str, factory: object, model: str | None
) -> None:
    events = run(factory(), name)  # type: ignore[operator]

    assert text_of(events) == CANONICAL
    assert kinds(events)[-1] == "done"
    usage = [event.usage for event in events if event.kind == "usage"][-1]
    assert usage is not None and usage.input_tokens == 1200 and usage.output_tokens == 95
    assert usage.cached_input_tokens == 400
    if model is not None:
        assert model in {event.model for event in events if event.kind == "model"}
    assert "tool" not in kinds(events)


def test_a_captured_live_stream_still_parses_to_a_finished_answer() -> None:
    """Whatever the opt-in live smoke recorded must parse like the hand-written fixtures.

    The parser comes from the shipped definition, exactly as `CliModelProvider` picks it
    (`parser_for(self.runtime)`), so this test follows the registry rather than a table of
    its own. The captures are written by `tests/contract/providers/test_live_cli_smoke.py`
    with `RESEARCH_HARNESS_LIVE_CLI_CAPTURE` set, so a workstation that has never run it
    has nothing to check here (CLI providers spec §20).
    """
    captures = sorted(STREAMS.glob("*-live-*.jsonl"))
    if not captures:
        pytest.skip("no *-live-*.jsonl capture recorded; run the opt-in live CLI smoke first")
    for path in captures:
        runtime = path.name.split("-live-", 1)[0]
        definition = RUNTIMES.get(runtime)
        assert definition is not None, f"{path.name}: {runtime!r} is not a registered runtime"
        events = run(parser_for(definition), path.name)
        assert kinds(events)[-1:] == ["done"], f"{path.name}: ended on {kinds(events)[-3:]}"
        assert text_of(events).strip(), f"{path.name}: the capture carried no answer text"


def test_partial_claude_messages_stream_deltas_that_concatenate_to_the_final_text() -> None:
    events = run(ClaudeStreamParser(), "claude-partial.jsonl")
    deltas = [event.text for event in events if event.kind == "text_delta"]
    assert deltas == ["Batching ", "reduces tail latency ", "across the pilot corpus."]
    assert text_of(events) == "".join(deltas)
    assert [event.stop_reason for event in events if event.kind == "stop"] == ["end_turn"]


TOOLS = [
    ("claude-tool.jsonl", ClaudeStreamParser, "Bash"),
    ("codex-tool.jsonl", lambda: JsonEventsParser("codex"), "command_execution"),
    ("cursor-tool.jsonl", lambda: JsonEventsParser("cursor_agent"), "tool_call"),
    ("opencode-tool.jsonl", lambda: JsonEventsParser("opencode"), "bash"),
    ("dsh-tool.jsonl", DshProfileParser, "bash"),
    ("pi-tool.jsonl", PiRpcParser, "bash"),
]


@pytest.mark.parametrize(("name", "factory", "tool"), TOOLS, ids=[case[0] for case in TOOLS])
def test_a_tool_call_is_reported_and_never_executed(name: str, factory: object, tool: str) -> None:
    events = run(factory(), name)  # type: ignore[operator]
    assert [event.tool for event in events if event.kind == "tool"] == [tool]
    assert "done" not in kinds(events)


ERRORS = [
    ("claude-auth-failed.jsonl", ClaudeStreamParser, "authentication_failed", "Not logged in"),
    ("claude-error-result.jsonl", ClaudeStreamParser, "error_during_execution", "429"),
    ("codex-failed.jsonl", lambda: JsonEventsParser("codex"), None, "gpt-nope"),
    ("opencode-error.jsonl", lambda: JsonEventsParser("opencode"), None, "login required"),
    ("dsh-failed.jsonl", DshProfileParser, "provider_error", "rate limit"),
    ("pi-error.jsonl", PiRpcParser, None, "401"),
]


@pytest.mark.parametrize(
    ("name", "factory", "code", "needle"), ERRORS, ids=[case[0] for case in ERRORS]
)
def test_a_runtime_error_is_a_structured_error_event(
    name: str, factory: object, code: str | None, needle: str
) -> None:
    events = run(factory(), name)  # type: ignore[operator]
    errors = [event for event in events if event.kind == "error"]
    assert errors and needle in (errors[0].message or "")
    if code is not None:
        assert errors[0].code == code
    assert "done" not in kinds(events)


def test_codex_reports_one_error_for_a_failed_turn_not_two() -> None:
    events = run(JsonEventsParser("codex"), "codex-failed.jsonl")
    assert kinds(events).count("error") == 1


def test_malformed_and_comment_lines_are_skipped_not_fatal() -> None:
    parser = JsonEventsParser("codex")
    assert list(parser.feed("# a comment")) == []
    assert list(parser.feed("not json at all")) == []
    assert list(parser.feed("")) == []


def test_opencode_needs_a_finished_step_before_it_is_done() -> None:
    parser = JsonEventsParser("opencode")
    list(parser.feed('{"type":"step_start","sessionID":"s","part":{"type":"step-start"}}'))
    list(parser.feed('{"type":"text","sessionID":"s","part":{"type":"text","text":"x"}}'))
    assert list(parser.finish()) == [], "no step_finish means no terminal event"


def test_dsh_frames_are_validated_strictly() -> None:
    parser = DshProfileParser()
    events = list(parser.feed('{"v":2,"type":"text","request_id":"r","content":"x"}'))
    assert events and events[0].kind == "error" and events[0].code == "protocol_error"


def test_every_family_is_registered() -> None:
    assert set(PARSERS) == {"claude_stream", "json_events", "dsh_profile", "pi_rpc"}

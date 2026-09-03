"""Codex, Cursor Agent, and OpenCode JSON event streams → `CliEvent` (spec §13).

Ported from the pinned Open Design `runtimes/json-event-stream.ts`, one variant per CLI.
Codex reports its answer as `item.completed` agent messages and closes with
`turn.completed` (usage); Cursor streams timestamped assistant chunks and replays the turn
in a terminal assistant message; OpenCode has no terminal event of its own, so a finished
step at end of stream is the terminal signal.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, load_json_object, register
from research_harness.providers.cli.types import JsonEventsVariant
from research_harness.providers.models.base import first_mapping, iter_mappings, usage_from

__all__ = ["JsonEventsParser"]

_CODEX_TOOL_ITEMS = frozenset(
    {"command_execution", "file_change", "mcp_tool_call", "web_search", "tool_call"}
)


def _message(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    mapping = first_mapping(value)
    for key in ("message", "error", "data", "detail"):
        inner = mapping.get(key)
        if isinstance(inner, str) and inner.strip():
            return inner
        if isinstance(inner, dict):
            found = _message(inner, "")
            if found:
                return found
    return fallback


class JsonEventsParser:
    """Translate one Codex, Cursor Agent, or OpenCode run into the event vocabulary."""

    def __init__(self, variant: JsonEventsVariant) -> None:
        self._variant = variant
        self._error_emitted = False
        self._codex_messages: list[str] = []
        self._cursor_text = ""
        self._opencode_finished = False
        self._opencode_failed = False

    def feed(self, line: str) -> Iterable[CliEvent]:
        obj = load_json_object(line)
        if obj is None:
            return []
        if self._variant == "codex":
            return self._codex(obj)
        if self._variant == "cursor_agent":
            return self._cursor(obj)
        return self._opencode(obj)

    def finish(self) -> Iterable[CliEvent]:
        if self._variant == "opencode" and self._opencode_finished and not self._opencode_failed:
            return [CliEvent(kind="done")]
        return []

    def _error_once(self, message: str, code: str | None = None) -> list[CliEvent]:
        """A failed turn often reports itself twice; the engine should hear it once."""
        if self._error_emitted:
            return []
        self._error_emitted = True
        return [CliEvent(kind="error", message=message, code=code)]

    # -- codex ---------------------------------------------------------------

    def _codex(self, obj: Mapping[str, Any]) -> list[CliEvent]:
        kind = obj.get("type")
        if kind in ("thread.started", "turn.started"):
            return [CliEvent(kind="status", status=str(kind))]
        if kind == "error":
            return self._error_once(_message(obj.get("message") or obj.get("error"), "Codex error"))
        if kind == "turn.failed":
            return self._error_once(
                _message(obj.get("error") or obj.get("message"), "Codex turn failed")
            )
        if kind in ("item.started", "item.updated", "item.completed"):
            return self._codex_item(kind, first_mapping(obj.get("item")))
        if kind == "turn.completed":
            usage = first_mapping(obj.get("usage"))
            return [
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                        cached_input_tokens=usage.get("cached_input_tokens"),
                        reasoning_tokens=usage.get("reasoning_output_tokens"),
                    ),
                ),
                CliEvent(kind="done"),
            ]
        return []

    def _codex_item(self, kind: str, item: Mapping[str, Any]) -> list[CliEvent]:
        item_type = item.get("type")
        if item_type in _CODEX_TOOL_ITEMS:
            return [CliEvent(kind="tool", tool=str(item_type))]
        if kind != "item.completed":
            return []
        if item_type == "agent_message" and isinstance(item.get("text"), str):
            self._codex_messages.append(item["text"])
            return [CliEvent(kind="final_text", text="\n".join(self._codex_messages))]
        if item_type == "error" and isinstance(item.get("message"), str):
            return [CliEvent(kind="status", status=f"warning: {item['message']}")]
        return []

    # -- cursor agent --------------------------------------------------------

    def _cursor(self, obj: Mapping[str, Any]) -> list[CliEvent]:
        kind = obj.get("type")
        if kind == "system":
            events = [CliEvent(kind="status", status=str(obj.get("subtype") or "system"))]
            if isinstance(obj.get("model"), str):
                events.append(CliEvent(kind="model", model=obj["model"]))
            return events
        if kind == "tool_call":
            return [CliEvent(kind="tool", tool="tool_call")]
        if kind == "assistant":
            text = "".join(
                block["text"]
                for block in iter_mappings(first_mapping(obj.get("message")).get("content"))
                if block.get("type") == "text" and isinstance(block.get("text"), str)
            )
            if not text:
                return []
            if isinstance(obj.get("timestamp_ms"), int | float) and "model_call_id" not in obj:
                self._cursor_text += text
                return [CliEvent(kind="text_delta", text=text)]
            return [CliEvent(kind="final_text", text=text)]
        if kind == "result":
            return self._cursor_result(obj)
        return []

    def _cursor_result(self, obj: Mapping[str, Any]) -> list[CliEvent]:
        if obj.get("is_error") is True:
            return self._error_once(
                _message(obj.get("result") or obj.get("error"), "Cursor Agent error")
            )
        usage = first_mapping(obj.get("usage"))
        events = [
            CliEvent(
                kind="usage",
                usage=usage_from(
                    input_tokens=usage.get("inputTokens"),
                    output_tokens=usage.get("outputTokens"),
                    cached_input_tokens=usage.get("cacheReadTokens"),
                ),
            )
        ]
        if isinstance(obj.get("result"), str) and obj["result"].strip():
            events.append(CliEvent(kind="final_text", text=obj["result"]))
        events.append(CliEvent(kind="done"))
        return events

    # -- opencode ------------------------------------------------------------

    def _opencode(self, obj: Mapping[str, Any]) -> list[CliEvent]:
        kind = obj.get("type")
        part = first_mapping(obj.get("part"))
        if kind == "step_start":
            return [CliEvent(kind="status", status="running")]
        if kind == "text" and isinstance(part.get("text"), str) and part["text"]:
            return [CliEvent(kind="text_delta", text=part["text"])]
        if kind == "tool_use":
            return [CliEvent(kind="tool", tool=str(part.get("tool") or "tool"))]
        if kind == "step_finish":
            self._opencode_finished = True
            tokens = first_mapping(part.get("tokens"))
            return [
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=tokens.get("input"),
                        output_tokens=tokens.get("output"),
                        cached_input_tokens=first_mapping(tokens.get("cache")).get("read"),
                        reasoning_tokens=tokens.get("reasoning"),
                    ),
                )
            ]
        if kind == "error":
            self._opencode_failed = True
            return self._error_once(
                _message(obj.get("error") or obj.get("message"), "OpenCode error")
            )
        return []


register(
    "json_events", lambda definition: JsonEventsParser(definition.json_events_variant or "codex")
)

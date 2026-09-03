"""Claude Code (and Amp) `--output-format stream-json` → `CliEvent` (spec §13).

Ported from the pinned Open Design `runtimes/claude-stream.ts`. Text arrives either as
`stream_event` deltas (`--include-partial-messages`) or only in the final `assistant`
wrapper; both are handled. `tool_use` blocks are `tool` events. A `result` with
`is_error` is an error, never a usage event.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, load_json_object, register
from research_harness.providers.models.base import first_mapping, iter_mappings, usage_from

__all__ = ["ClaudeStreamParser"]


def _usage(payload: Any) -> CliEvent:
    usage = first_mapping(payload)
    return CliEvent(
        kind="usage",
        usage=usage_from(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_input_tokens=usage.get("cache_read_input_tokens"),
        ),
    )


class ClaudeStreamParser:
    """Translate one Claude/Amp stream-json run into the engine's event vocabulary."""

    def __init__(self) -> None:
        self._final_seen = False
        self._stop_seen = False

    def feed(self, line: str) -> Iterable[CliEvent]:
        obj = load_json_object(line)
        if obj is None:
            return []
        kind = obj.get("type")
        if kind == "system":
            events = [CliEvent(kind="status", status=str(obj.get("subtype") or "system"))]
            if isinstance(obj.get("model"), str):
                events.append(CliEvent(kind="model", model=obj["model"]))
            return events
        if kind == "stream_event":
            return self._stream_event(first_mapping(obj.get("event")))
        if kind == "assistant":
            return self._assistant(obj)
        if kind == "result":
            return self._result(obj)
        return []

    def _stop(self, stop_reason: str) -> list[CliEvent]:
        """One `stop` per turn: partial streams repeat it in the `assistant` wrapper."""
        if self._stop_seen:
            return []
        self._stop_seen = True
        return [CliEvent(kind="stop", stop_reason=stop_reason)]

    def _stream_event(self, event: Mapping[str, Any]) -> list[CliEvent]:
        kind = event.get("type")
        if kind == "message_start":
            model = first_mapping(event.get("message")).get("model")
            return [CliEvent(kind="model", model=model)] if isinstance(model, str) else []
        if kind == "content_block_start":
            block = first_mapping(event.get("content_block"))
            if block.get("type") == "tool_use":
                return [CliEvent(kind="tool", tool=str(block.get("name") or "tool_use"))]
            return []
        if kind == "content_block_delta":
            delta = first_mapping(event.get("delta"))
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                return [CliEvent(kind="text_delta", text=delta["text"])]
            return []
        if kind == "message_delta":
            stop = first_mapping(event.get("delta")).get("stop_reason")
            return self._stop(stop) if isinstance(stop, str) else []
        return []

    def _assistant(self, obj: Mapping[str, Any]) -> list[CliEvent]:
        message = first_mapping(obj.get("message"))
        events: list[CliEvent] = []
        if isinstance(message.get("model"), str):
            events.append(CliEvent(kind="model", model=message["model"]))
        texts: list[str] = []
        for block in iter_mappings(message.get("content")):
            if block.get("type") == "tool_use":
                events.append(CliEvent(kind="tool", tool=str(block.get("name") or "tool_use")))
            elif block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
        if isinstance(obj.get("error"), str):
            events.append(
                CliEvent(
                    kind="error",
                    message="".join(texts) or obj["error"],
                    code=obj["error"],
                )
            )
            return events
        if texts:
            self._final_seen = True
            events.append(CliEvent(kind="final_text", text="".join(texts)))
        if isinstance(message.get("stop_reason"), str):
            events.extend(self._stop(message["stop_reason"]))
        return events

    def _result(self, obj: Mapping[str, Any]) -> list[CliEvent]:
        if obj.get("is_error") is True:
            text = obj.get("result") if isinstance(obj.get("result"), str) else None
            code = str(obj.get("subtype") or "result_error")
            return [CliEvent(kind="error", message=text or f"Claude run failed: {code}", code=code)]
        events = [_usage(obj.get("usage"))]
        if not self._final_seen and isinstance(obj.get("result"), str) and obj["result"].strip():
            events.append(CliEvent(kind="final_text", text=obj["result"]))
        events.append(CliEvent(kind="done"))
        return events

    def finish(self) -> Iterable[CliEvent]:
        return []


register("claude_stream", lambda definition: ClaudeStreamParser())

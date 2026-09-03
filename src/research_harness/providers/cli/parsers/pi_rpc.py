"""Pi `--mode rpc` events → `CliEvent` (spec §13).

Ported from the pinned Open Design `agent-protocol/pi-rpc/events.ts`. The answer streams
as `message_update` text deltas; `turn_end` carries usage and the model; `agent_end` is
the terminal event. `tool_execution_start` is a `tool` event.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, load_json_object, register
from research_harness.providers.models.base import first_mapping, usage_from

__all__ = ["PiRpcParser"]


class PiRpcParser:
    """Translate one Pi RPC run into the event vocabulary."""

    def __init__(self) -> None:
        self._failed = False

    def feed(self, line: str) -> Iterable[CliEvent]:
        obj = load_json_object(line)
        if obj is None:
            return []
        kind = obj.get("type")
        if kind in ("agent_start", "turn_start", "compaction_start", "auto_retry_start"):
            return [CliEvent(kind="status", status=str(kind))]
        if kind == "message_update":
            return self._message_update(first_mapping(obj.get("assistantMessageEvent")))
        if kind == "tool_execution_start":
            return [CliEvent(kind="tool", tool=str(obj.get("toolName") or "tool"))]
        if kind == "turn_end":
            return self._turn_end(first_mapping(obj.get("message")))
        if kind == "extension_error" or (kind == "auto_retry_end" and obj.get("success") is False):
            self._failed = True
            message = str(obj.get("error") or obj.get("finalError") or "Pi error")
            return [CliEvent(kind="error", message=message)]
        if kind == "agent_end":
            return [] if self._failed else [CliEvent(kind="done")]
        return []

    def _message_update(self, event: Mapping[str, Any]) -> list[CliEvent]:
        if event.get("type") == "text_delta" and isinstance(event.get("delta"), str):
            return [CliEvent(kind="text_delta", text=event["delta"])]
        if event.get("type") == "error":
            self._failed = True
            message = str(event.get("reason") or event.get("delta") or "Pi agent error")
            return [CliEvent(kind="error", message=message)]
        return []

    def _turn_end(self, message: Mapping[str, Any]) -> list[CliEvent]:
        usage = first_mapping(message.get("usage"))
        events: list[CliEvent] = []
        if usage:
            events.append(
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=usage.get("input"),
                        output_tokens=usage.get("output"),
                        cached_input_tokens=usage.get("cacheRead"),
                    ),
                )
            )
        if isinstance(message.get("model"), str):
            events.append(CliEvent(kind="model", model=message["model"]))
        if message.get("stopReason") == "error":
            self._failed = True
            reason = str(message.get("errorMessage") or "Pi agent error")
            events.append(CliEvent(kind="error", message=reason))
        elif isinstance(message.get("stopReason"), str):
            events.append(CliEvent(kind="stop", stop_reason=message["stopReason"]))
        return events

    def finish(self) -> Iterable[CliEvent]:
        return []


register("pi_rpc", lambda definition: PiRpcParser())

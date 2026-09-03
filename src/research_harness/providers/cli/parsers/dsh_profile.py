"""DeepSeek Harness `--profile open-design --stdio` frames → `CliEvent` (spec §13).

Ported from the pinned Open Design `agent-protocol/dsh-profile/`: stdout is a
protocol-only channel, so a frame that is not generation-1 JSON is a `protocol_error`
rather than something to skip. `tool_call` frames are `tool` events.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, register
from research_harness.providers.models.base import first_mapping, usage_from

__all__ = ["DshProfileParser"]

PROTOCOL_VERSION = 1
_TYPES = frozenset(
    {
        "probe",
        "ready",
        "session",
        "thinking",
        "text",
        "tool_call",
        "tool_result",
        "usage",
        "result",
        "protocol_error",
        "models",
    }
)


class DshProfileParser:
    """Translate one DeepSeek Harness profile run into the event vocabulary."""

    def feed(self, line: str) -> Iterable[CliEvent]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return []
        try:
            frame: Any = json.loads(stripped)
        except ValueError:
            return [
                CliEvent(
                    kind="error",
                    message="DeepSeek Harness profile emitted malformed JSON",
                    code="protocol_error",
                )
            ]
        if (
            not isinstance(frame, dict)
            or frame.get("v") != PROTOCOL_VERSION
            or frame.get("type") not in _TYPES
        ):
            return [
                CliEvent(
                    kind="error",
                    message="DeepSeek Harness profile emitted an invalid frame",
                    code="protocol_error",
                )
            ]
        return self._frame(frame)

    def _frame(self, frame: dict[str, Any]) -> list[CliEvent]:
        kind = frame["type"]
        if kind in ("ready", "probe", "session"):
            return [CliEvent(kind="status", status=str(kind))]
        if kind == "text" and isinstance(frame.get("content"), str):
            return [CliEvent(kind="text_delta", text=frame["content"])]
        if kind == "tool_call":
            return [CliEvent(kind="tool", tool=str(frame.get("name") or "tool_call"))]
        if kind == "usage":
            events = [
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=frame.get("input_tokens"),
                        output_tokens=frame.get("output_tokens"),
                        cached_input_tokens=frame.get("cache_read_tokens"),
                    ),
                )
            ]
            if isinstance(frame.get("model"), str):
                events.append(CliEvent(kind="model", model=frame["model"]))
            return events
        if kind == "result":
            return self._result(frame)
        if kind == "protocol_error":
            message = str(frame.get("message") or "protocol error")
            return [CliEvent(kind="error", message=message, code="protocol_error")]
        return []

    def _result(self, frame: dict[str, Any]) -> list[CliEvent]:
        status = frame.get("status")
        if status == "completed":
            events: list[CliEvent] = []
            if isinstance(frame.get("output"), str) and frame["output"].strip():
                events.append(CliEvent(kind="final_text", text=frame["output"]))
            if isinstance(frame.get("stop_reason"), str):
                events.append(CliEvent(kind="stop", stop_reason=frame["stop_reason"]))
            events.append(CliEvent(kind="done"))
            return events
        error = first_mapping(frame.get("error"))
        code = str(error.get("code") or ("cancelled" if status == "cancelled" else "failed"))
        message = str(error.get("message") or f"DeepSeek Harness run {status}")
        return [CliEvent(kind="error", message=message, code=code)]

    def finish(self) -> Iterable[CliEvent]:
        return []


register("dsh_profile", lambda definition: DshProfileParser())

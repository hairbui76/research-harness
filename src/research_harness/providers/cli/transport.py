"""How one prompt reaches a runtime and how a run is asked to stop (spec §12, §14).

Research content never touches argv: plain text or one JSONL user message on stdin, or a
command on an RPC channel. Every transport also knows the protocol's own cancel message,
which the engine sends before it terminates the process tree.
"""

from __future__ import annotations

import json
from typing import Protocol

from research_harness.providers.cli.parsers import CliEvent
from research_harness.providers.cli.prompt import stream_json_user_message
from research_harness.providers.cli.types import CliInvocation, CliRuntimeDef

__all__ = [
    "DshProfileTransport",
    "PiRpcTransport",
    "StdinJsonlTransport",
    "StdinTextTransport",
    "Transport",
    "transport_for",
]


class _Stdin(Protocol):
    def write(self, text: str) -> None: ...

    def close_stdin(self) -> None: ...


class Transport(Protocol):
    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None: ...

    def observe(self, process: _Stdin, event: CliEvent) -> None: ...

    def intercept(self, process: _Stdin, line: str) -> bool: ...

    def cancel(self, process: _Stdin) -> None: ...


class StdinTextTransport:
    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        process.write(prompt)
        process.close_stdin()

    def observe(self, process: _Stdin, event: CliEvent) -> None:
        return None

    def intercept(self, process: _Stdin, line: str) -> bool:
        return False

    def cancel(self, process: _Stdin) -> None:
        process.close_stdin()


class StdinJsonlTransport(StdinTextTransport):
    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        process.write(stream_json_user_message(prompt))
        process.close_stdin()


class PiRpcTransport:
    def __init__(self) -> None:
        self._request_id = ""

    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        self._request_id = invocation.request_id
        process.write(
            json.dumps({"id": invocation.request_id, "type": "prompt", "message": prompt}) + "\n"
        )

    def observe(self, process: _Stdin, event: CliEvent) -> None:
        return None

    def intercept(self, process: _Stdin, line: str) -> bool:
        """Refuse every extension dialog: a bounded worker has nobody to ask."""
        try:
            obj = json.loads(line)
        except ValueError:
            return False
        if not isinstance(obj, dict) or obj.get("type") != "extension_ui_request":
            return False
        if obj.get("id") is not None:
            process.write(
                json.dumps({"type": "extension_ui_response", "id": obj["id"], "cancelled": True})
                + "\n"
            )
        return True

    def cancel(self, process: _Stdin) -> None:
        process.write(json.dumps({"id": f"{self._request_id}-abort", "type": "abort"}) + "\n")
        process.close_stdin()


class DshProfileTransport:
    def __init__(self) -> None:
        self._prompt = ""
        self._invocation: CliInvocation | None = None
        self._sent = False

    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        self._prompt = prompt
        self._invocation = invocation

    def observe(self, process: _Stdin, event: CliEvent) -> None:
        if (
            self._sent
            or event.kind != "status"
            or event.status != "ready"
            or self._invocation is None
        ):
            return
        self._sent = True
        command: dict[str, object] = {
            "v": 1,
            "type": "execute",
            "request_id": self._invocation.request_id,
            "cwd": str(self._invocation.cwd),
            "prompt": self._prompt,
            "mcp_servers": [],
        }
        model = self._invocation.model
        if model and "/" in model:
            provider, _, model_id = model.partition("/")
            command["model"] = {"provider": provider, "id": model_id}
        if self._invocation.reasoning:
            command["reasoning_effort"] = self._invocation.reasoning
        process.write(json.dumps(command) + "\n")

    def intercept(self, process: _Stdin, line: str) -> bool:
        return False

    def cancel(self, process: _Stdin) -> None:
        if self._invocation is not None:
            process.write(
                json.dumps({"v": 1, "type": "cancel", "request_id": self._invocation.request_id})
                + "\n"
            )
        process.close_stdin()


def transport_for(definition: CliRuntimeDef) -> Transport:
    if definition.transport == "stdin_jsonl":
        return StdinJsonlTransport()
    if definition.transport == "pi_rpc":
        return PiRpcTransport()
    if definition.transport == "dsh_profile":
        return DshProfileTransport()
    return StdinTextTransport()

"""Deterministic, provider-neutral rendering of one request for a CLI (spec §12).

The same request renders to the same bytes on every runtime, and the rendering never
touches the fingerprint: `ModelRequest.fingerprint()` is computed from the request, not
from what any adapter puts on the wire. The prompt is delivered over stdin or RPC and is
never placed in argv.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from research_harness.providers.models.base import ModelRequest, canonical_json, render_inputs

__all__ = [
    "BOUNDARY",
    "NO_INPUTS_PROMPT",
    "OUTPUT_RULE",
    "render_chat_prompt",
    "render_prompt",
    "stream_json_user_message",
]

NO_INPUTS_PROMPT = "No research inputs were provided; answer from the instructions alone."

OUTPUT_RULE = (
    "Return exactly one JSON object that validates against the schema above. "
    "Do not wrap it in a Markdown fence and do not write anything before or after it."
)

BOUNDARY = (
    "You are running as a bounded research worker inside Research Harness. Do not inspect "
    "the file system, do not run commands, do not edit or create files, do not open any URL, "
    "and do not call any tool. Answer only from the instructions and the inputs above."
)


def render_prompt(request: ModelRequest[Any], schema_json: Mapping[str, Any]) -> str:
    """The five sections of spec §12: role, inputs, schema, output rule, boundary."""
    return "\n\n".join(
        (
            f"# Role: {request.role}\n{request.instructions}",
            f"# Inputs\n{render_inputs(request.inputs) or NO_INPUTS_PROMPT}",
            f"# Response schema (JSON Schema)\n{canonical_json(dict(schema_json))}",
            f"# Output rule\n{OUTPUT_RULE}",
            f"# Boundary\n{BOUNDARY}",
        )
    )


def render_chat_prompt(request: ModelRequest[Any]) -> str:
    """A conversation turn: the same role, inputs and boundary, answered in prose."""
    return "\n\n".join(
        (
            f"# Role: {request.role}\n{request.instructions}",
            f"# Inputs\n{render_inputs(request.inputs) or NO_INPUTS_PROMPT}",
            "# Output rule\nAnswer in plain prose. Do not return JSON.",
            f"# Boundary\n{BOUNDARY}",
        )
    )


def stream_json_user_message(prompt: str) -> str:
    """One Claude Code `--input-format stream-json` user message, newline-terminated."""
    body = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
    }
    return json.dumps(body, ensure_ascii=False) + "\n"

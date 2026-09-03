"""The prompt is deterministic and complete (CLI providers spec §12)."""

from __future__ import annotations

import json

from pydantic import BaseModel

from research_harness.providers.cli.prompt import (
    BOUNDARY,
    OUTPUT_RULE,
    render_chat_prompt,
    render_prompt,
    stream_json_user_message,
)
from research_harness.providers.models.base import InputEnvelope, ModelRequest, ModelRequirements


class Verdict(BaseModel):
    supported: bool
    rationale: str


def request() -> ModelRequest[Verdict]:
    return ModelRequest(
        role="evidence_verifier",
        requirements=ModelRequirements(
            structured_output=True, context_tokens=1000, reasoning="low"
        ),
        instructions="Decide whether the span supports the candidate.",
        inputs=[
            InputEnvelope(
                object_id="W0001", kind="source_text", content="Table 3 reports 1.4 Gbps."
            ),
            InputEnvelope(object_id=None, kind="candidate", content="throughput=1.4 Gbps"),
        ],
        response_schema=Verdict,
    )


def test_the_prompt_has_the_five_sections_in_order() -> None:
    text = render_prompt(request(), request().wire_schema())
    positions = [
        text.index("# Role: evidence_verifier"),
        text.index("Decide whether the span supports the candidate."),
        text.index("[input 1] kind=source_text object_id=W0001\nTable 3 reports 1.4 Gbps."),
        text.index("[input 2] kind=candidate\nthroughput=1.4 Gbps"),
        text.index("# Response schema (JSON Schema)"),
        text.index(json.dumps(request().wire_schema(), sort_keys=True, separators=(",", ":"))),
        text.index(OUTPUT_RULE),
        text.index(BOUNDARY),
    ]
    assert positions == sorted(positions)


def test_the_prompt_is_deterministic_and_does_not_change_the_fingerprint() -> None:
    first, second = request(), request()
    assert render_prompt(first, first.wire_schema()) == render_prompt(second, second.wire_schema())
    assert first.fingerprint() == second.fingerprint()


def test_the_boundary_forbids_every_kind_of_side_effect() -> None:
    for word in ("file system", "run commands", "edit", "create files", "URL", "tool"):
        assert word in BOUNDARY


def test_no_inputs_is_said_rather_than_left_blank() -> None:
    bare = request().model_copy(update={"inputs": []})
    assert "No research inputs were provided" in render_prompt(bare, bare.wire_schema())


def test_a_chat_prompt_asks_for_prose_and_no_schema() -> None:
    text = render_chat_prompt(request())
    assert "# Response schema" not in text and OUTPUT_RULE not in text
    assert "Answer in plain prose" in text and BOUNDARY in text


def test_the_jsonl_user_message_is_one_line_of_claude_stream_json() -> None:
    line = stream_json_user_message("hello\nworld")
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line) == {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": "hello\nworld"}]},
    }

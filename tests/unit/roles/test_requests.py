"""`build_request` is the only way a role becomes a provider call.

It enforces the contract's allowed inputs, keeps a prior role's reasoning out of the next
role's context, and produces a request whose fingerprint depends on the material rather
than on the order a caller happened to assemble it in.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from research_harness.domain.errors import AuthorityError
from research_harness.providers.models.base import (
    ModelRequest,
    StructuredOutputError,
    parse_structured_output,
)
from research_harness.roles import (
    EXTRACTOR,
    VERIFIER,
    WRITER,
    ExtractionOutput,
    InputKind,
    RoleInput,
    RoleRequest,
    VerificationOutput,
    build_request,
)

SOURCE_TEXT = "Table 3 reports 1.4 Gbps on CIC-IDS2017."

CANDIDATE_PAYLOAD: dict[str, Any] = {
    "exact_text": "1.4 Gbps",
    "block": "B0042",
    "field": "throughput",
}


def _verifier_inputs(candidate: dict[str, Any]) -> list[RoleInput]:
    return [
        RoleInput(InputKind.CANDIDATE_EVIDENCE, "E0007", candidate),
        RoleInput(InputKind.SOURCE_DOCUMENT, "W0003", SOURCE_TEXT),
    ]


# --------------------------------------------------------------------- permissions


def test_a_disallowed_input_kind_is_refused() -> None:
    with pytest.raises(AuthorityError, match="may not read 'accepted_claims'"):
        build_request(VERIFIER, [RoleInput(InputKind.ACCEPTED_CLAIMS, "C0001", "a claim")])


def test_the_extractor_is_not_handed_accepted_state() -> None:
    with pytest.raises(AuthorityError, match="evidence_extractor"):
        build_request(
            EXTRACTOR,
            [
                RoleInput(InputKind.SOURCE_DOCUMENT, "W0003", SOURCE_TEXT),
                RoleInput(InputKind.ACCEPTED_EVIDENCE, "E0001", "accepted"),
            ],
        )


# ---------------------------------------------------------------- hidden reasoning


def _candidate_content(built: RoleRequest[Any]) -> str:
    envelope = next(
        item for item in built.request.inputs if item.kind == InputKind.CANDIDATE_EVIDENCE
    )
    return envelope.content


def test_hidden_reasoning_never_reaches_the_next_role() -> None:
    """The verifier must judge the candidate, not the extractor's deliberation."""
    built = build_request(
        VERIFIER,
        _verifier_inputs(
            {
                **CANDIDATE_PAYLOAD,
                "reasoning": "I assumed the encrypted split",
                "hidden_reasoning": "...",
                "chain_of_thought": "step 1, step 2",
            }
        ),
    )
    assert built.stripped_fields == ("chain_of_thought", "hidden_reasoning", "reasoning")
    content = _candidate_content(built)
    for name in ("reasoning", "chain_of_thought", "hidden_reasoning", "deliberation"):
        assert name not in content
    assert "1.4 Gbps" in content


def test_nested_and_oddly_spelled_reasoning_fields_are_stripped() -> None:
    built = build_request(
        VERIFIER,
        _verifier_inputs(
            {
                "candidates": [{"exact_text": "1.4 Gbps", "Chain-Of-Thought": "..."}],
                "notes": {"scratchpad": "..."},
            }
        ),
    )
    assert built.stripped_fields == ("candidates.0.Chain-Of-Thought", "notes.scratchpad")
    content = _candidate_content(built)
    assert "scratchpad" not in content
    assert "Chain-Of-Thought" not in content
    assert "1.4 Gbps" in content


def test_clean_input_strips_nothing() -> None:
    built = build_request(VERIFIER, _verifier_inputs(CANDIDATE_PAYLOAD))
    assert built.stripped_fields == ()


def test_plain_text_content_is_passed_through_unchanged() -> None:
    built = build_request(VERIFIER, [RoleInput(InputKind.SOURCE_DOCUMENT, "W0003", SOURCE_TEXT)])
    assert built.request.inputs[0].content == SOURCE_TEXT


# -------------------------------------------------------------------- request shape


def test_the_request_carries_the_role_schema_and_metadata() -> None:
    built = build_request(VERIFIER, _verifier_inputs(CANDIDATE_PAYLOAD))
    request: ModelRequest[Any] = built.request
    assert request.response_schema is VerificationOutput
    assert request.role == "evidence_verifier"
    assert request.instructions == VERIFIER.system_prompt
    assert request.requirements == VERIFIER.requirements
    assert request.metadata == {
        "role": "evidence_verifier",
        "template_version": VERIFIER.template_version,
    }


def test_each_role_requests_its_own_schema() -> None:
    extraction = build_request(
        EXTRACTOR, [RoleInput(InputKind.SOURCE_DOCUMENT, "W0003", SOURCE_TEXT)]
    )
    assert extraction.request.response_schema is ExtractionOutput
    assert extraction.request.wire_schema()["additionalProperties"] is False


def test_extra_instructions_are_appended_to_the_contract_prompt() -> None:
    built = build_request(
        EXTRACTOR,
        [RoleInput(InputKind.SOURCE_DOCUMENT, "W0003", SOURCE_TEXT)],
        extra_instructions="Extract the dataset field only.",
    )
    assert built.request.instructions.startswith(EXTRACTOR.system_prompt)
    assert built.request.instructions.endswith("Extract the dataset field only.")
    assert (
        built.request.fingerprint()
        != build_request(
            EXTRACTOR, [RoleInput(InputKind.SOURCE_DOCUMENT, "W0003", SOURCE_TEXT)]
        ).request.fingerprint()
    )


# --------------------------------------------------------------------- fingerprints


def test_the_same_material_fingerprints_identically() -> None:
    first = build_request(VERIFIER, _verifier_inputs(CANDIDATE_PAYLOAD))
    second = build_request(VERIFIER, list(reversed(_verifier_inputs(CANDIDATE_PAYLOAD))))
    assert first.request.fingerprint() == second.request.fingerprint()
    assert [envelope.kind for envelope in first.request.inputs] == [
        InputKind.SOURCE_DOCUMENT,
        InputKind.CANDIDATE_EVIDENCE,
    ]


def test_structured_content_is_rendered_key_order_independently() -> None:
    forward = build_request(VERIFIER, _verifier_inputs(dict(CANDIDATE_PAYLOAD)))
    shuffled = build_request(
        VERIFIER, _verifier_inputs(dict(reversed(list(CANDIDATE_PAYLOAD.items()))))
    )
    assert forward.request.fingerprint() == shuffled.request.fingerprint()


def test_different_material_fingerprints_differently() -> None:
    first = build_request(VERIFIER, _verifier_inputs(CANDIDATE_PAYLOAD))
    second = build_request(
        VERIFIER, _verifier_inputs({**CANDIDATE_PAYLOAD, "exact_text": "2.8 Gbps"})
    )
    assert first.request.fingerprint() != second.request.fingerprint()


def test_roles_with_the_same_inputs_still_differ() -> None:
    """Fingerprints cover the role, its prompt, and its schema, not just the text."""
    writer = build_request(WRITER, [RoleInput(InputKind.ACCEPTED_CLAIMS, "C0001", "a claim")])
    assert writer.request.role == "writer"
    assert (
        writer.request.fingerprint()
        != build_request(
            WRITER,
            [RoleInput(InputKind.ACCEPTED_CLAIMS, "C0001", "a claim")],
            extra_instructions="Draft the related work section.",
        ).request.fingerprint()
    )


def test_a_model_answer_validates_through_the_provider_seam() -> None:
    """The schema a role asks for is the schema the provider layer validates (ADR-005)."""
    built = build_request(EXTRACTOR, [RoleInput(InputKind.SOURCE_DOCUMENT, "W0003", SOURCE_TEXT)])
    answer = {
        "candidates": [
            {
                "exact_text": "1.4 Gbps",
                "page": 7,
                "block": "B0042",
                "char_start": 16,
                "char_end": 24,
                "origin": "source_observed",
                "evidence_type": "experimental_result",
                "strength": "direct",
                "field": "throughput",
                "numeric": {
                    "raw": "1.4 Gbps",
                    "parsed": 1.4,
                    "unit": "Gbps",
                    "metric": "throughput",
                    "dataset": "CIC-IDS2017",
                    "condition": {},
                    "source_table": "Table 3",
                    "source_row": None,
                    "source_column": None,
                },
                "negative_state": None,
                "rationale": "Table 3 states the throughput directly.",
            }
        ],
        "fields_not_found": ["latency"],
    }
    parsed = parse_structured_output(json.dumps(answer), built.request.response_schema)
    assert isinstance(parsed, ExtractionOutput)
    assert parsed.fields_not_found == ["latency"]

    with pytest.raises(StructuredOutputError):
        parse_structured_output(
            json.dumps({"candidates": [], "fields_not_found": [], "reasoning": "..."}),
            built.request.response_schema,
        )

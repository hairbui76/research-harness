"""The scripted provider honours the same contract as a real adapter, offline.

It exists so CI and offline demos can run the whole evidence pipeline deterministically, and
that is only worth anything if it fails the way a real provider fails: a reply that does not
satisfy the caller's schema raises `StructuredOutputError` through the shared parse path, so
a test that passes here would pass against a live model too (ADR-005).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from research_harness.providers.models import (
    ModelRequest,
    ModelRequirements,
    ModelRouter,
    NoCapableProviderError,
    ProviderError,
    ProviderRateLimitError,
    StructuredOutputError,
)
from research_harness.providers.models.scripted import (
    DEFAULT_SCRIPTED_MODEL,
    ScriptedProvider,
    default_scripted_capabilities,
    scripted_router,
)
from tests.contract.providers.conftest import CANONICAL_ANSWER, EXPECTED_VERDICT, Verdict

REQUIREMENTS = ModelRequirements(
    structured_output=True, context_tokens=100_000, reasoning="high", vision=False
)


def request_for(role: str = "evidence_verifier") -> ModelRequest[Verdict]:
    return ModelRequest(
        role=role,
        requirements=REQUIREMENTS,
        instructions="Decide whether the source supports the candidate evidence.",
        response_schema=Verdict,
    )


# ---------------------------------------------------------------------- the contract


def test_a_scripted_dict_is_validated_and_returned_with_reproducibility_metadata() -> None:
    provider = ScriptedProvider([CANONICAL_ANSWER])
    request = request_for()

    response = provider.complete(request)

    assert response.parsed == EXPECTED_VERDICT
    assert response.provider == "scripted"
    assert response.model == DEFAULT_SCRIPTED_MODEL
    assert response.request_fingerprint == request.fingerprint()
    assert response.raw_text == json.dumps(CANONICAL_ANSWER, ensure_ascii=False)
    assert response.stop_reason == "stop"


def test_usage_is_reported_as_zero_rather_than_invented() -> None:
    response = ScriptedProvider([CANONICAL_ANSWER]).complete(request_for())

    assert response.usage.input_tokens == 0
    assert response.usage.output_tokens == 0
    assert response.usage.cached_input_tokens is None
    assert response.usage.reasoning_tokens is None


def test_a_pydantic_reply_is_serialized_the_way_a_provider_would() -> None:
    response = ScriptedProvider([EXPECTED_VERDICT]).complete(request_for())

    assert response.parsed == EXPECTED_VERDICT
    assert json.loads(response.raw_text) == CANONICAL_ANSWER


def test_every_request_is_recorded_in_order() -> None:
    provider = ScriptedProvider([CANONICAL_ANSWER, CANONICAL_ANSWER])

    provider.complete(request_for("evidence_extractor"))
    provider.complete(request_for("evidence_verifier"))

    assert [item.role for item in provider.requests] == [
        "evidence_extractor",
        "evidence_verifier",
    ]
    assert provider.remaining == 0


def test_a_callable_script_answers_from_the_request() -> None:
    def answer(request: ModelRequest[Any]) -> dict[str, Any]:
        return {**CANONICAL_ANSWER, "rationale": f"asked by {request.role}"}

    response = ScriptedProvider(answer).complete(request_for("evidence_verifier"))

    assert response.parsed.rationale == "asked by evidence_verifier"


# --------------------------------------------------------------------------- failures


def test_a_reply_that_misses_the_schema_raises_through_the_shared_parse_path() -> None:
    provider = ScriptedProvider([{"supported": True}])

    with pytest.raises(StructuredOutputError) as excinfo:
        provider.complete(request_for())

    assert excinfo.value.provider == "scripted"
    assert excinfo.value.raw_text == '{"supported": true}'


def test_a_reply_that_is_not_json_raises_rather_than_returning_prose() -> None:
    provider = ScriptedProvider(["the source supports it"])

    with pytest.raises(StructuredOutputError, match="not valid JSON"):
        provider.complete(request_for())


def test_a_scripted_exception_is_raised_as_the_provider_failure_it_stands_for() -> None:
    provider = ScriptedProvider([ProviderRateLimitError("slow down", provider="scripted")])

    with pytest.raises(ProviderRateLimitError):
        provider.complete(request_for())

    assert len(provider.requests) == 1, "a failed call is still a recorded call"


def test_running_out_of_scripted_replies_is_an_error_not_a_silent_replay() -> None:
    provider = ScriptedProvider([CANONICAL_ANSWER])
    provider.complete(request_for())

    with pytest.raises(ProviderError, match="ran out of responses"):
        provider.complete(request_for())


# ----------------------------------------------------------------- capability routing


def test_the_provider_declares_no_egress() -> None:
    egress = default_scripted_capabilities().egress

    assert egress.endpoint_host == "localhost"
    assert egress.sends_source_text is False
    assert egress.sends_identifiers is False


def test_it_satisfies_every_role_requirement_the_harness_states() -> None:
    capabilities = default_scripted_capabilities()

    assert capabilities.structured_output
    assert capabilities.max_context_tokens >= 200_000
    assert capabilities.reasoning_levels == {"low", "medium", "high"}


def test_a_scripted_router_routes_to_the_scripted_provider() -> None:
    provider = ScriptedProvider([CANONICAL_ANSWER], name="scripted-a", model="model-a")
    router = scripted_router(provider)

    response = router.complete(request_for())

    assert isinstance(router, ModelRouter)
    assert response.provider == "scripted-a"
    assert response.model == "model-a"


def test_a_scripted_router_can_be_restricted_to_one_role() -> None:
    router = scripted_router(ScriptedProvider([CANONICAL_ANSWER]), roles={"evidence_verifier"})

    with pytest.raises(NoCapableProviderError, match="evidence_extractor"):
        router.complete(request_for("evidence_extractor"))

"""The contract every model provider must honour, and the router that chooses one.

ROADMAP Task 4.1: selection is by declared capability and configuration only, invalid
structured output is rejected before it can reach staging, and hidden chain-of-thought
is neither requested nor persisted.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from research_harness.providers.models import (
    AnthropicProvider,
    EgressDeclaration,
    InputEnvelope,
    LocalOpenAICompatibleProvider,
    ModelRequest,
    ModelRequirements,
    ModelResponse,
    ModelRouter,
    NoCapableProviderError,
    OpenAIProvider,
    ProviderAuthError,
    ProviderCapabilities,
    ProviderEntry,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
    RouterConfig,
    StructuredOutputError,
    build_router,
    normalize_json_schema,
    parse_structured_output,
    render_inputs,
)
from tests.contract.providers.conftest import (
    API_KEY,
    CACHED_TOKENS,
    CANONICAL_JSON,
    EXPECTED_VERDICT,
    INPUT_TOKENS,
    OUTPUT_TOKENS,
    CallRecorder,
    ProviderCase,
    StubProvider,
    Verdict,
    assert_inputs_present,
    assert_no_hidden_reasoning_request,
    json_response,
    make_transport,
)


def _capabilities(
    *,
    structured_output: bool = True,
    max_context_tokens: int = 200_000,
    reasoning_levels: set[str] | None = None,
    vision: bool = False,
    host: str = "example.test",
) -> ProviderCapabilities:
    return ProviderCapabilities(
        structured_output=structured_output,
        max_context_tokens=max_context_tokens,
        reasoning_levels=reasoning_levels or {"low", "medium", "high"},
        vision=vision,
        egress=EgressDeclaration(
            endpoint_host=host,
            sends_source_text=True,
            sends_identifiers=True,
            description="test double",
        ),
    )


def _requirements(**overrides: Any) -> ModelRequirements:
    values: dict[str, Any] = {
        "structured_output": True,
        "context_tokens": 100_000,
        "reasoning": "high",
        "vision": False,
    }
    values.update(overrides)
    return ModelRequirements(**values)


# --------------------------------------------------------- one contract, three wires


def test_every_provider_returns_the_same_validated_object(
    provider_case: ProviderCase, model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = provider_case.build(
        make_transport(recorder, json_response(provider_case.body(CANONICAL_JSON)))
    )

    response = provider.complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert response.provider == provider_case.provider_name
    assert response.model == provider_case.model
    assert response.request_fingerprint == model_request.fingerprint()
    assert response.latency_ms >= 0
    assert response.stop_reason is not None
    assert response.usage.input_tokens == INPUT_TOKENS
    assert response.usage.output_tokens == OUTPUT_TOKENS
    assert response.usage.cached_input_tokens == CACHED_TOKENS
    assert response.usage.reasoning_tokens == provider_case.reasoning_tokens


def test_providers_agree_on_the_canonical_response(
    model_request: ModelRequest[Verdict],
) -> None:
    """Product SS42.A: the same job runs on any provider without schema changes."""
    from tests.contract.providers.conftest import PROVIDER_CASES

    responses: list[ModelResponse[Verdict]] = []
    for case in PROVIDER_CASES:
        recorder = CallRecorder()
        provider = case.build(make_transport(recorder, json_response(case.body(CANONICAL_JSON))))
        responses.append(provider.complete(model_request))

    assert [response.parsed for response in responses] == [EXPECTED_VERDICT] * len(responses)
    assert {response.request_fingerprint for response in responses} == {model_request.fingerprint()}
    assert [response.provider for response in responses] == [
        case.provider_name for case in PROVIDER_CASES
    ]


def test_request_carries_credentials_schema_and_inputs(
    provider_case: ProviderCase, model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = provider_case.build(
        make_transport(recorder, json_response(provider_case.body(CANONICAL_JSON)))
    )

    provider.complete(model_request)

    sent = recorder.last
    assert sent.method == "POST"
    assert sent.url.path == provider_case.path
    assert sent.headers[provider_case.auth_header].endswith(API_KEY)
    serialized = sent.content.decode()
    assert_inputs_present(serialized, model_request.inputs)
    assert model_request.instructions in serialized
    for property_name in Verdict.model_fields:
        assert property_name in serialized


def test_no_provider_asks_for_hidden_reasoning(
    provider_case: ProviderCase, model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = provider_case.build(
        make_transport(recorder, json_response(provider_case.body(CANONICAL_JSON)))
    )

    provider.complete(model_request)

    assert_no_hidden_reasoning_request(recorder.last_payload)


def test_response_has_no_place_to_store_hidden_reasoning() -> None:
    assert set(ModelResponse.model_fields) == {
        "parsed",
        "raw_text",
        "usage",
        "provider",
        "model",
        "latency_ms",
        "request_fingerprint",
        "stop_reason",
    }


# ----------------------------------------------------------- structured output guard


def test_malformed_json_is_rejected(
    provider_case: ProviderCase, model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = provider_case.build(
        make_transport(recorder, json_response(provider_case.body("I think it is supported.")))
    )

    with pytest.raises(StructuredOutputError) as caught:
        provider.complete(model_request)
    assert caught.value.provider == provider_case.provider_name


def test_schema_invalid_json_is_rejected_without_partial_objects(
    provider_case: ProviderCase, model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    incomplete = json.dumps({"supported": True, "confidence": 4.2, "rationale": "over range"})
    provider = provider_case.build(
        make_transport(recorder, json_response(provider_case.body(incomplete)))
    )

    with pytest.raises(StructuredOutputError) as caught:
        provider.complete(model_request)
    assert caught.value.raw_text == incomplete


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimitError),
        (400, ProviderResponseError),
        (500, ProviderTransportError),
        (503, ProviderTransportError),
    ],
)
def test_http_failures_map_to_distinct_errors(
    provider_case: ProviderCase,
    model_request: ModelRequest[Verdict],
    recorder: CallRecorder,
    status: int,
    expected: type[Exception],
) -> None:
    provider = provider_case.build(
        make_transport(recorder, json_response({"error": {"message": "nope"}}, status))
    )

    with pytest.raises(expected):
        provider.complete(model_request)


def test_transport_failure_maps_to_transport_error(
    provider_case: ProviderCase, model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = provider_case.build(
        make_transport(recorder, httpx.ConnectTimeout("no route to provider"))
    )

    with pytest.raises(ProviderTransportError):
        provider.complete(model_request)


def test_rate_limit_error_carries_retry_after(
    provider_case: ProviderCase, model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    throttled = httpx.Response(429, json={"error": "slow down"}, headers={"retry-after": "30"})
    provider = provider_case.build(make_transport(recorder, throttled))

    with pytest.raises(ProviderRateLimitError) as caught:
        provider.complete(model_request)
    assert caught.value.retry_after_seconds == 30.0


def test_parse_structured_output_accepts_a_fenced_object() -> None:
    parsed = parse_structured_output(f"```json\n{CANONICAL_JSON}\n```", Verdict)
    assert parsed == EXPECTED_VERDICT


def test_parse_structured_output_rejects_a_json_array() -> None:
    with pytest.raises(StructuredOutputError):
        parse_structured_output("[1, 2, 3]", Verdict)


# ------------------------------------------------------------------ secret hygiene


def test_api_key_never_appears_in_dump_or_repr(provider_case: ProviderCase) -> None:
    provider = provider_case.build(make_transport(CallRecorder(), json_response({})))
    # `settings` lives on the HTTP adapter base, not on the abstract ModelProvider.
    settings = provider.settings  # type: ignore[attr-defined]

    assert API_KEY not in repr(provider)
    assert API_KEY not in repr(settings)
    assert "api_key" not in settings.model_dump()
    assert API_KEY not in settings.model_dump_json()
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == API_KEY


def test_api_keys_come_from_the_documented_environment_variables() -> None:
    env = {"OPENAI_API_KEY": "openai-env", "ANTHROPIC_API_KEY": "anthropic-env"}
    openai = OpenAIProvider("gpt-test-1", env=env)
    anthropic = AnthropicProvider("claude-test-1", env=env)
    local = LocalOpenAICompatibleProvider("local-test-1", env=env)

    assert openai.settings.api_key is not None
    assert openai.settings.api_key.get_secret_value() == "openai-env"
    assert anthropic.settings.api_key is not None
    assert anthropic.settings.api_key.get_secret_value() == "anthropic-env"
    assert local.settings.api_key is None


# ------------------------------------------------------------------- fingerprints


def test_fingerprint_is_stable_and_provider_independent(
    model_request: ModelRequest[Verdict],
) -> None:
    assert model_request.fingerprint() == model_request.fingerprint()
    assert len(model_request.fingerprint()) == 64


def test_fingerprint_ignores_metadata_but_tracks_the_job(
    model_request: ModelRequest[Verdict],
) -> None:
    same_job = model_request.model_copy(update={"metadata": {"run": "99"}})
    assert same_job.fingerprint() == model_request.fingerprint()

    for change in (
        {"instructions": "Decide something else."},
        {"role": "skeptic"},
        {"temperature": 0.7},
        {"inputs": [InputEnvelope(object_id="work:zzz", kind="source_text", content="other")]},
        {"requirements": _requirements(context_tokens=1_000)},
    ):
        assert model_request.model_copy(update=change).fingerprint() != model_request.fingerprint()


def test_fingerprint_tracks_the_response_schema(model_request: ModelRequest[Verdict]) -> None:
    class OtherVerdict(BaseModel):
        supported: bool

    other = model_request.model_copy(update={"response_schema": OtherVerdict})
    assert other.fingerprint() != model_request.fingerprint()


def test_render_inputs_is_deterministic_and_keeps_object_ids(
    model_request: ModelRequest[Verdict],
) -> None:
    rendered = render_inputs(model_request.inputs)
    assert rendered == render_inputs(model_request.inputs)
    assert "object_id=work:0a1b2c" in rendered
    assert "kind=candidate_evidence" in rendered


# --------------------------------------------------------------- schema normalizer


def test_normalizer_makes_every_object_strict() -> None:
    normalized = normalize_json_schema(Verdict.model_json_schema())

    assert normalized["additionalProperties"] is False
    assert normalized["required"] == list(normalized["properties"])
    assert "minimum" not in normalized["properties"]["confidence"]
    assert "maximum" not in normalized["properties"]["confidence"]


def test_normalizer_recurses_into_defs_and_arrays() -> None:
    class Item(BaseModel):
        label: str
        weight: int = 3

    class Envelope(BaseModel):
        items: list[Item]

    normalized = normalize_json_schema(Envelope.model_json_schema())
    item = normalized["$defs"]["Item"]

    assert item["additionalProperties"] is False
    assert item["required"] == ["label", "weight"]
    assert "default" not in item["properties"]["weight"]


def test_normalizer_rewrites_one_of_and_is_idempotent() -> None:
    schema = {
        "type": "object",
        "properties": {"choice": {"oneOf": [{"type": "string"}, {"type": "null"}]}},
    }
    once = normalize_json_schema(schema)
    assert once["properties"]["choice"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert "oneOf" not in once["properties"]["choice"]
    assert normalize_json_schema(once) == once


# -------------------------------------------------------------------------- router


def test_router_selects_by_capability_not_by_domain(model_request: ModelRequest[Verdict]) -> None:
    text_only = StubProvider("text-only", _capabilities(vision=False))
    with_vision = StubProvider("with-vision", _capabilities(vision=True))
    router = ModelRouter(
        [
            ProviderEntry(provider=text_only, model="text-1", priority=1),
            ProviderEntry(provider=with_vision, model="vision-1", priority=9),
        ]
    )

    assert router.select(_requirements(), "evidence_verifier").model == "text-1"
    assert router.select(_requirements(vision=True), "evidence_verifier").model == "vision-1"


def test_router_excludes_providers_with_too_little_context() -> None:
    small = StubProvider("small", _capabilities(max_context_tokens=8_000))
    large = StubProvider("large", _capabilities(max_context_tokens=400_000))
    router = ModelRouter(
        [
            ProviderEntry(provider=small, model="small-1", priority=1),
            ProviderEntry(provider=large, model="large-1", priority=2),
        ]
    )

    assert router.select(_requirements(context_tokens=1_000), "verifier").model == "small-1"
    assert router.select(_requirements(context_tokens=250_000), "verifier").model == "large-1"


def test_router_honours_reasoning_level_role_scope_and_priority() -> None:
    shallow = StubProvider("shallow", _capabilities(reasoning_levels={"low"}))
    scoped = StubProvider("scoped", _capabilities())
    general = StubProvider("general", _capabilities())
    router = ModelRouter(
        [
            ProviderEntry(provider=shallow, model="shallow-1", priority=1),
            ProviderEntry(provider=scoped, model="scoped-1", priority=2, roles={"skeptic"}),
            ProviderEntry(provider=general, model="general-1", priority=3),
        ]
    )

    assert router.select(_requirements(reasoning="low"), "skeptic").model == "shallow-1"
    assert router.select(_requirements(reasoning="high"), "skeptic").model == "scoped-1"
    assert router.select(_requirements(reasoning="high"), "writer").model == "general-1"


def test_no_capable_provider_error_lists_every_rejection() -> None:
    router = ModelRouter(
        [
            ProviderEntry(
                provider=StubProvider("small", _capabilities(max_context_tokens=8_000)),
                model="small-1",
                priority=1,
            ),
            ProviderEntry(
                provider=StubProvider("blind", _capabilities(max_context_tokens=400_000)),
                model="blind-1",
                priority=2,
                roles={"writer"},
            ),
        ]
    )

    with pytest.raises(NoCapableProviderError) as caught:
        router.select(_requirements(context_tokens=250_000, vision=True), "verifier")

    message = str(caught.value)
    assert "small/small-1" in message
    assert "context window 8000 < required 250000" in message
    assert "blind/blind-1" in message
    assert "role 'verifier' not in allowed roles (writer)" in message
    assert "vision required but not supported" in message


def test_empty_router_explains_itself() -> None:
    with pytest.raises(NoCapableProviderError, match="no providers are configured"):
        ModelRouter([]).select(_requirements(), "verifier")


def test_router_complete_delegates_to_the_selected_provider(
    model_request: ModelRequest[Verdict],
) -> None:
    chosen = StubProvider("chosen", _capabilities(), model="chosen-1")
    ignored = StubProvider("ignored", _capabilities(reasoning_levels={"low"}))
    router = ModelRouter(
        [
            ProviderEntry(provider=ignored, model="ignored-1", priority=1),
            ProviderEntry(provider=chosen, model="chosen-1", priority=2),
        ]
    )

    response = router.complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert response.model == "chosen-1"
    assert [call.role for call in chosen.calls] == ["evidence_verifier"]
    assert ignored.calls == []


# ---------------------------------------------------------------- router from config


ROUTER_CONFIG: dict[str, Any] = {
    "providers": [
        {
            "name": "local-first",
            "kind": "local_openai_compatible",
            "model": "local-test-1",
            "priority": 10,
            "tags": ["cheap"],
            "capabilities": {"max_context_tokens": 8_000},
        },
        {
            "name": "hosted-anthropic",
            "kind": "anthropic",
            "model": "claude-test-1",
            "priority": 20,
            "api_key_env": "ANTHROPIC_API_KEY",
            "roles": ["evidence_verifier", "skeptic"],
            "capabilities": {"max_context_tokens": 400_000},
        },
        {
            "name": "hosted-openai",
            "kind": "openai",
            "model": "gpt-test-1",
            "priority": 30,
            "api_key_env": "OPENAI_API_KEY",
        },
        {
            "name": "retired",
            "kind": "openai",
            "model": "gpt-old",
            "priority": 1,
            "enabled": False,
        },
    ]
}


def test_build_router_from_configuration_without_code(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    from tests.contract.providers.conftest import anthropic_body

    config = RouterConfig.model_validate(ROUTER_CONFIG)
    router = build_router(
        config,
        env={"ANTHROPIC_API_KEY": "anthropic-env-key", "OPENAI_API_KEY": "openai-env-key"},
        transport=make_transport(recorder, json_response(anthropic_body())),
    )

    assert [entry.model for entry in router.entries] == [
        "local-test-1",
        "claude-test-1",
        "gpt-test-1",
    ]
    assert router.entries[0].tags == {"local-first", "cheap"}

    # 100k context excludes the 8k local entry; the role is allowed on the Anthropic one.
    response = router.complete(model_request)

    assert response.provider == "anthropic"
    assert response.parsed == EXPECTED_VERDICT
    assert recorder.last.headers["x-api-key"] == "anthropic-env-key"


def test_config_capability_overrides_change_routing_only() -> None:
    config = RouterConfig.model_validate(ROUTER_CONFIG)
    router = build_router(config, env={})
    local_entry, anthropic_entry, _openai_entry = router.entries

    assert local_entry.provider.capabilities().max_context_tokens == 8_000
    assert anthropic_entry.provider.capabilities().max_context_tokens == 400_000
    assert local_entry.provider.capabilities().egress.endpoint_host == "localhost"
    assert local_entry.provider.capabilities().egress.sends_source_text is False


def test_router_config_loads_from_yaml() -> None:
    """A workspace can describe its routing table in YAML with no code."""
    import yaml

    config = RouterConfig.model_validate(
        yaml.safe_load(
            """
            providers:
              - name: local-first
                kind: local_openai_compatible
                model: llama-test
                priority: 10
              - name: hosted
                kind: anthropic
                model: claude-test-1
                priority: 20
                api_key_env: ANTHROPIC_API_KEY
                roles: [evidence_verifier]
            """
        )
    )

    router = build_router(config, env={"ANTHROPIC_API_KEY": "k"})

    assert [entry.provider.name for entry in router.entries] == ["local", "anthropic"]
    assert router.entries[1].roles == {"evidence_verifier"}


def test_router_config_rejects_unknown_provider_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        RouterConfig.model_validate(
            {"providers": [{"name": "x", "kind": "telepathy", "model": "m"}]}
        )


def test_normalizer_never_mistakes_a_field_name_for_a_keyword() -> None:
    """A schema may legitimately have fields called `pattern`, `default` or `items`."""

    class TrafficShape(BaseModel):
        pattern: str
        default: bool
        items: int
        kind: str

    normalized = normalize_json_schema(TrafficShape.model_json_schema())

    assert set(normalized["properties"]) == {"pattern", "default", "items", "kind"}
    assert normalized["required"] == ["pattern", "default", "items", "kind"]
    assert normalized["properties"]["items"] == {"title": "Items", "type": "integer"}


def test_normalizer_preserves_enum_and_ref_targets() -> None:
    class Level(StrEnum):
        LOW = "low"
        HIGH = "high"

    class Rating(BaseModel):
        level: Level

    normalized = normalize_json_schema(Rating.model_json_schema())

    assert normalized["properties"]["level"]["$ref"] == "#/$defs/Level"
    assert normalized["$defs"]["Level"]["enum"] == ["low", "high"]

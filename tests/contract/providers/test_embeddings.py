"""Embedding provider contract: wire format, batching, fingerprints, and error mapping.

Every adapter is driven through `httpx.MockTransport`: no network, no key, and the
request body is asserted rather than assumed. The offline hashing provider is held to the
same contract, because the index cannot tell which one it is talking to.
"""

from __future__ import annotations

import json
import math
from typing import Any

import httpx
import pytest

from research_harness.providers.models.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
)
from research_harness.providers.models.embeddings import (
    OPENAI_MODEL_DIMENSIONS,
    EmbeddingProvider,
    HashingEmbeddingProvider,
    LocalOpenAICompatibleEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from tests.contract.providers.conftest import API_KEY, CallRecorder, json_response, make_transport

MODEL = "text-embedding-3-small"
DIMENSION = OPENAI_MODEL_DIMENSIONS[MODEL]
TEXTS = ["encrypted traffic classification", "flow level anomaly detection"]


def embedding_body(
    count: int, *, dimension: int = DIMENSION, reversed_order: bool = False
) -> dict[str, Any]:
    """A realistic `/v1/embeddings` reply whose i-th vector is filled with `i`."""
    data = [
        {"object": "embedding", "index": index, "embedding": [float(index)] * dimension}
        for index in range(count)
    ]
    if reversed_order:
        data.reverse()
    return {
        "object": "list",
        "data": data,
        "model": MODEL,
        "usage": {"prompt_tokens": 11, "total_tokens": 11},
    }


def echo_transport(recorder: CallRecorder, *, dimension: int = DIMENSION) -> httpx.MockTransport:
    """Answers every request with one vector per input, so batching stays observable."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.record(request)
        payload = json.loads(request.content)
        return httpx.Response(200, json=embedding_body(len(payload["input"]), dimension=dimension))

    return httpx.MockTransport(handler)


def openai_provider(transport: httpx.BaseTransport, **kwargs: Any) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(MODEL, api_key=API_KEY, transport=transport, env={}, **kwargs)


# -- wire format --------------------------------------------------------------------


def test_posts_input_and_model_to_the_embeddings_endpoint(recorder: CallRecorder) -> None:
    openai_provider(echo_transport(recorder)).embed(TEXTS)

    sent = recorder.last
    assert str(sent.url) == "https://api.openai.com/v1/embeddings"
    assert sent.headers["authorization"] == f"Bearer {API_KEY}"
    assert sent.headers["content-type"] == "application/json"
    assert recorder.last_payload["model"] == MODEL
    assert recorder.last_payload["input"] == TEXTS


def test_maps_data_embeddings_back_in_input_order(recorder: CallRecorder) -> None:
    """`data` may come back in any order; `index` is what says which text it belongs to."""
    transport = make_transport(recorder, json_response(embedding_body(2, reversed_order=True)))

    vectors = openai_provider(transport).embed(TEXTS)

    assert [vector[0] for vector in vectors] == [0.0, 1.0]


def test_embedding_an_empty_sequence_calls_no_backend(recorder: CallRecorder) -> None:
    assert openai_provider(echo_transport(recorder)).embed([]) == []
    assert recorder.requests == []


def test_long_input_is_split_into_batches_and_kept_in_order(recorder: CallRecorder) -> None:
    texts = [f"unit {index}" for index in range(5)]

    vectors = openai_provider(echo_transport(recorder), batch_size=2).embed(texts)

    assert [len(recorder.payload(index)["input"]) for index in range(3)] == [2, 2, 1]
    assert len(vectors) == 5
    assert [vector[0] for vector in vectors] == [0.0, 1.0, 0.0, 1.0, 0.0]


def test_requested_dimensions_are_sent_and_become_the_fingerprint(recorder: CallRecorder) -> None:
    provider = openai_provider(echo_transport(recorder, dimension=256), dimensions=256)

    provider.embed(["one"])

    assert recorder.last_payload["dimensions"] == 256
    assert provider.dimension == 256
    assert provider.fingerprint() == f"openai/{MODEL}/256"


def test_known_model_needs_no_probe_call_for_its_width(recorder: CallRecorder) -> None:
    provider = openai_provider(echo_transport(recorder))

    assert provider.fingerprint() == f"openai/{MODEL}/{DIMENSION}"
    assert recorder.requests == []


def test_usage_is_normalized_like_the_chat_adapters(recorder: CallRecorder) -> None:
    provider = openai_provider(echo_transport(recorder))

    provider.embed(TEXTS)

    assert provider.last_usage is not None
    assert provider.last_usage.input_tokens == 11
    assert provider.last_usage.output_tokens == 0


def test_the_api_key_is_never_serialized_or_repr_ed(recorder: CallRecorder) -> None:
    provider = OpenAIEmbeddingProvider(
        MODEL, transport=echo_transport(recorder), env={"OPENAI_API_KEY": API_KEY}
    )

    provider.embed(["one"])

    assert recorder.last.headers["authorization"] == f"Bearer {API_KEY}"
    assert API_KEY not in repr(provider)
    assert "api_key" not in provider.settings.model_dump()
    assert API_KEY not in provider.settings.model_dump_json()


# -- error mapping ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimitError),
        (500, ProviderTransportError),
        (400, ProviderResponseError),
    ],
)
def test_http_failures_map_to_distinct_provider_errors(
    recorder: CallRecorder, status: int, expected: type[Exception]
) -> None:
    transport = make_transport(recorder, httpx.Response(status, json={"error": "no"}))

    with pytest.raises(expected):
        openai_provider(transport).embed(TEXTS)


def test_rate_limit_carries_retry_after(recorder: CallRecorder) -> None:
    transport = make_transport(
        recorder, httpx.Response(429, json={"error": "slow down"}, headers={"retry-after": "7"})
    )

    with pytest.raises(ProviderRateLimitError) as raised:
        openai_provider(transport).embed(TEXTS)

    assert raised.value.retry_after_seconds == 7.0


def test_transport_failures_report_that_nothing_was_computed(recorder: CallRecorder) -> None:
    transport = make_transport(recorder, httpx.ConnectError("connection refused"))

    with pytest.raises(ProviderTransportError):
        openai_provider(transport).embed(TEXTS)


@pytest.mark.parametrize(
    "body",
    [
        {"object": "list"},
        {"data": "not-a-list"},
        {"data": [{"index": 0, "embedding": [0.1]}]},
        {"data": [{"index": 0, "embedding": []}, {"index": 1, "embedding": []}]},
        {"data": [{"index": 0, "embedding": ["x"]}, {"index": 1, "embedding": ["y"]}]},
    ],
    ids=["no-data", "data-not-a-list", "wrong-count", "empty-vector", "non-numeric"],
)
def test_malformed_bodies_raise_a_response_error(
    recorder: CallRecorder, body: dict[str, Any]
) -> None:
    transport = make_transport(recorder, json_response(body))

    with pytest.raises(ProviderResponseError):
        openai_provider(transport).embed(TEXTS)


def test_a_vector_of_the_wrong_width_is_rejected(recorder: CallRecorder) -> None:
    """The declared dimension is a contract: a shorter vector would corrupt the index."""
    transport = echo_transport(recorder, dimension=DIMENSION - 1)

    with pytest.raises(ProviderResponseError, match="dimensional"):
        openai_provider(transport).embed(TEXTS)


def test_a_non_json_body_raises_a_response_error(recorder: CallRecorder) -> None:
    transport = make_transport(recorder, httpx.Response(200, text="<html>gateway</html>"))

    with pytest.raises(ProviderResponseError):
        openai_provider(transport).embed(TEXTS)


# -- local adapter ------------------------------------------------------------------


def test_local_adapter_talks_to_localhost_without_a_key(recorder: CallRecorder) -> None:
    provider = LocalOpenAICompatibleEmbeddingProvider(
        "nomic-embed-text", transport=echo_transport(recorder, dimension=8), dimension=8, env={}
    )

    provider.embed(["one"])

    assert str(recorder.last.url) == "http://localhost:11434/v1/embeddings"
    assert "authorization" not in recorder.last.headers
    assert provider.fingerprint() == "local/nomic-embed-text/8"


def test_local_adapter_declares_loopback_egress() -> None:
    egress = LocalOpenAICompatibleEmbeddingProvider("nomic-embed-text", env={}).egress

    assert egress.endpoint_host == "localhost"
    assert egress.sends_source_text is False
    assert egress.sends_identifiers is False


def test_a_remote_base_url_is_declared_as_egress() -> None:
    egress = LocalOpenAICompatibleEmbeddingProvider(
        "nomic-embed-text", base_url="http://gpu-box.example.com:8000/v1", env={}
    ).egress

    assert egress.endpoint_host == "gpu-box.example.com"
    assert egress.sends_source_text is True


def test_an_unconfigured_width_is_probed_once(recorder: CallRecorder) -> None:
    provider = LocalOpenAICompatibleEmbeddingProvider(
        "mystery-model", transport=echo_transport(recorder, dimension=8), env={}
    )

    assert provider.dimension == 8
    assert provider.dimension == 8
    assert len(recorder.requests) == 1
    assert recorder.last_payload["input"] == ["dimension probe"]


def test_embedding_first_teaches_the_adapter_its_width(recorder: CallRecorder) -> None:
    """A probe is only for callers that ask the width before indexing anything."""
    provider = LocalOpenAICompatibleEmbeddingProvider(
        "mystery-model", transport=echo_transport(recorder, dimension=8), env={}
    )

    provider.embed(["one"])

    assert provider.dimension == 8
    assert len(recorder.requests) == 1


def test_openai_egress_declares_text_but_not_identifiers() -> None:
    egress = OpenAIEmbeddingProvider(MODEL, api_key=API_KEY, env={}).egress

    assert egress.endpoint_host == "api.openai.com"
    assert egress.sends_source_text is True
    assert egress.sends_identifiers is False


# -- offline hashing provider -------------------------------------------------------


def test_hashing_vectors_are_deterministic_across_instances() -> None:
    first = HashingEmbeddingProvider(dimension=64).embed(["encrypted traffic"])
    second = HashingEmbeddingProvider(dimension=64).embed(["encrypted traffic"])

    assert first == second


def test_hashing_vectors_have_the_requested_width_and_unit_norm() -> None:
    vectors = HashingEmbeddingProvider(dimension=64).embed(TEXTS)

    assert [len(vector) for vector in vectors] == [64, 64]
    for vector in vectors:
        assert math.isclose(math.sqrt(sum(value**2 for value in vector)), 1.0, rel_tol=1e-6)


def test_hashing_text_with_no_tokens_embeds_to_zero_rather_than_failing() -> None:
    (vector,) = HashingEmbeddingProvider(dimension=32).embed(["!!! ---"])

    assert not any(vector)


def test_hashing_similarity_prefers_shared_vocabulary() -> None:
    provider = HashingEmbeddingProvider(dimension=512)
    query, related, unrelated = provider.embed(
        [
            "encrypted traffic classification benchmark",
            "we classify encrypted traffic on a public benchmark",
            "quantile boundaries are frozen after pretraining",
        ]
    )

    assert _cosine(query, related) > _cosine(query, unrelated)


def test_hashing_character_ngrams_survive_a_word_form_change() -> None:
    """Character 3-grams are why `tokenization` still matches `tokenized`."""
    with_chars = HashingEmbeddingProvider(dimension=512)
    words_only = HashingEmbeddingProvider(dimension=512, char_ngram=0)
    pair = ["packet tokenization scheme", "packet tokenized schemes"]

    assert _cosine(*with_chars.embed(pair)) > _cosine(*words_only.embed(pair))


def test_hashing_fingerprint_changes_with_every_feature_setting() -> None:
    fingerprints = {
        HashingEmbeddingProvider().fingerprint(),
        HashingEmbeddingProvider(dimension=256).fingerprint(),
        HashingEmbeddingProvider(ngrams=(1,)).fingerprint(),
        HashingEmbeddingProvider(char_ngram=4).fingerprint(),
        HashingEmbeddingProvider(char_weight=0.5).fingerprint(),
    }

    assert len(fingerprints) == 5


def test_hashing_provider_sends_nothing_anywhere() -> None:
    egress = HashingEmbeddingProvider().egress

    assert egress.sends_source_text is False
    assert egress.sends_identifiers is False


@pytest.mark.parametrize(
    "kwargs",
    [{"dimension": 0}, {"ngrams": ()}, {"ngrams": (0,)}, {"char_weight": -1.0}],
)
def test_hashing_provider_rejects_impossible_settings(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        HashingEmbeddingProvider(**kwargs)


# -- the contract itself ------------------------------------------------------------


@pytest.mark.parametrize(
    "provider",
    [
        HashingEmbeddingProvider(dimension=32),
        OpenAIEmbeddingProvider(MODEL, api_key=API_KEY, env={}),
        LocalOpenAICompatibleEmbeddingProvider("mystery-model", dimension=8, env={}),
    ],
    ids=["hashing", "openai", "local"],
)
def test_every_provider_fingerprints_as_name_model_dimension(provider: EmbeddingProvider) -> None:
    assert provider.fingerprint() == f"{provider.name}/{provider.model}/{provider.dimension}"
    assert provider.egress.endpoint_host


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))

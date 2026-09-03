"""Embedding providers: one neutral contract, two HTTP adapters, one offline adapter.

An embedding is index machinery, never scientific state (Product P7, SS15.1, ADR-006).
Two things follow, and both are enforced here rather than in the index:

* `dimension` and `fingerprint()` are part of the contract, because an index is stored
  per fingerprint (`name/model/dimension`). Changing the provider, the model, or the
  width therefore lands in a different directory instead of silently re-interpreting
  vectors that were written by something else.
* `egress` states what leaves the workstation when unit text is embedded (Product SS34).
  Building a vector index over a corpus ships that corpus to whoever computes the
  vectors, so the disclosure belongs on the provider, not in a comment.

`embed` batches internally so callers hand over a whole corpus and let the adapter
respect the backend's per-request limit. Error mapping is the chat adapters' mapping,
reused from `_http`: 401/403 -> `ProviderAuthError`, 429 -> `ProviderRateLimitError`,
5xx and transport failures -> `ProviderTransportError`, anything else unusable ->
`ProviderResponseError`.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Self

import httpx

from research_harness.providers.models._http import build_client, endpoint_host, post_json
from research_harness.providers.models.base import (
    EgressDeclaration,
    ProviderResponseError,
    ProviderSettings,
    Usage,
    iter_mappings,
    resolve_api_key,
    usage_from,
)

__all__ = [
    "DEFAULT_EMBEDDING_BATCH_SIZE",
    "IN_PROCESS_HOST",
    "LOCAL_API_KEY_ENV_VAR",
    "LOCAL_DEFAULT_BASE_URL",
    "OPENAI_API_KEY_ENV_VAR",
    "OPENAI_DEFAULT_BASE_URL",
    "OPENAI_DEFAULT_EMBEDDING_MODEL",
    "OPENAI_MODEL_DIMENSIONS",
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "LocalOpenAICompatibleEmbeddingProvider",
    "OpenAIEmbeddingProvider",
]

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_BATCH_SIZE = 64
"""Texts per request; well inside every backend's input limit and small enough that one
failed batch does not lose a whole corpus rebuild."""

EMBEDDINGS_PATH = "/embeddings"
_DIMENSION_PROBE = "dimension probe"
"""Text embedded once, and only when a backend's vector width is not configured."""


# --------------------------------------------------------------------------- contract


class EmbeddingProvider(ABC):
    """One embedding backend behind a neutral contract.

    Subclasses implement `_embed_batch` (wire format, error mapping) plus the three
    descriptive properties; `embed` adds batching and the shape checks every caller
    would otherwise repeat.
    """

    name: str
    max_batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE

    @property
    @abstractmethod
    def model(self) -> str:
        """Model identifier as the backend names it; part of the index fingerprint."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Width of the vectors this provider returns."""

    @property
    @abstractmethod
    def egress(self) -> EgressDeclaration:
        """What leaves the workstation when text is embedded (Product SS34)."""

    @abstractmethod
    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed one batch of at most `max_batch_size` texts, in the order given."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed `texts` in order, one `max_batch_size` batch per backend call."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.max_batch_size):
            batch = list(texts[start : start + self.max_batch_size])
            vectors.extend(self._checked(self._embed_batch(batch), len(batch)))
        return vectors

    def fingerprint(self) -> str:
        """`name/model/dimension` — the identity an index directory is keyed by."""
        return f"{self.name}/{self.model}/{self.dimension}"

    def _checked(self, vectors: list[list[float]], expected: int) -> list[list[float]]:
        if len(vectors) != expected:
            raise ProviderResponseError(
                f"{self.name} returned {len(vectors)} vectors for {expected} texts",
                provider=self.name,
            )
        width = self.dimension
        for vector in vectors:
            if len(vector) != width:
                raise ProviderResponseError(
                    f"{self.name} returned a {len(vector)}-dimensional vector, expected {width}",
                    provider=self.name,
                )
        return vectors

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r})"


# ------------------------------------------------------------------- http adapters


class _HttpEmbeddingProvider(EmbeddingProvider):
    """Shared plumbing for `POST {base_url}/embeddings` backends.

    Both hosted and local OpenAI-compatible servers speak the same wire format:
    `{"model": ..., "input": [...]}` in, `{"data": [{"index": i, "embedding": [...]}]}`
    out. Only the credentials, the egress disclosure, and the default endpoint differ.
    """

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        egress: EgressDeclaration,
        dimension: int | None = None,
        requested_dimensions: int | None = None,
        transport: httpx.BaseTransport | None = None,
        batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if dimension is not None and dimension < 1:
            raise ValueError("dimension must be at least 1")
        self.settings = settings
        self.max_batch_size = batch_size
        self.last_usage: Usage | None = None
        """Token accounting for the most recent batch; embeddings carry no response
        object, so usage is reported here rather than alongside a parsed answer."""
        self._egress = egress
        self._dimension = dimension
        self._requested_dimensions = requested_dimensions
        self._client = build_client(
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            transport=transport,
        )

    @property
    def model(self) -> str:
        return self.settings.model

    @property
    def dimension(self) -> int:
        """Configured width, or the width of one probe embedding, cached.

        A server that serves an arbitrary model does not publish its vector width, and
        the index needs it before it can store anything, so an unconfigured provider
        pays exactly one extra call the first time the width is asked for.
        """
        known = self._dimension
        if known is not None:
            return known
        vectors = self._embed_batch([_DIMENSION_PROBE])
        if not vectors:
            raise ProviderResponseError(
                f"{self.name} returned no vector for the dimension probe", provider=self.name
            )
        width = len(vectors[0])
        self._dimension = width
        return width

    @property
    def egress(self) -> EgressDeclaration:
        return self._egress

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "input": list(texts),
            "encoding_format": "float",
        }
        if self._requested_dimensions is not None:
            payload["dimensions"] = self._requested_dimensions
        body = post_json(
            self._client,
            EMBEDDINGS_PATH,
            payload=payload,
            headers=self._headers(),
            provider=self.name,
        )
        vectors = _read_embeddings(body, provider=self.name, expected=len(texts))
        self.last_usage = _read_usage(body)
        if self._dimension is None and vectors:
            self._dimension = len(vectors[0])
        return vectors

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self.settings.api_key
        if key is not None:
            headers["authorization"] = f"Bearer {key.get_secret_value()}"
        return headers

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(model={self.settings.model!r}, "
            f"base_url={self.settings.base_url!r})"
        )


OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"
OPENAI_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

OPENAI_MODEL_DIMENSIONS: Mapping[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}
"""Published widths, so a known model needs no probe call. An unlisted model without an
explicit `dimensions` is measured once instead of guessed."""


class OpenAIEmbeddingProvider(_HttpEmbeddingProvider):
    """Embeddings from the OpenAI `/v1/embeddings` endpoint.

    `dimensions` is the API's own shortening parameter: it is sent on the wire *and*
    becomes the fingerprinted width, so a shortened index never shares a directory with
    a full-width one.
    """

    name = "openai"

    def __init__(
        self,
        model: str = OPENAI_DEFAULT_EMBEDDING_MODEL,
        *,
        api_key: str | None = None,
        base_url: str = OPENAI_DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        dimensions: int | None = None,
        timeout: float = 60.0,
        batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
        env: Mapping[str, str] | None = None,
    ) -> None:
        settings = ProviderSettings(
            provider=self.name,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout,
            api_key=resolve_api_key(api_key, OPENAI_API_KEY_ENV_VAR, env),
        )
        super().__init__(
            settings,
            egress=openai_embedding_egress(base_url),
            dimension=dimensions if dimensions is not None else OPENAI_MODEL_DIMENSIONS.get(model),
            requested_dimensions=dimensions,
            transport=transport,
            batch_size=batch_size,
        )


def openai_embedding_egress(base_url: str = OPENAI_DEFAULT_BASE_URL) -> EgressDeclaration:
    """Egress record for the hosted embeddings endpoint (Product SS34)."""
    return EgressDeclaration(
        endpoint_host=endpoint_host(base_url),
        sends_source_text=True,
        sends_identifiers=False,
        description=(
            "Retrieval unit text — paragraphs, tables, captions, evidence spans and "
            "claim statements — is sent to the OpenAI embeddings API to build the local "
            "vector index. Harness object IDs are not sent with it."
        ),
    )


LOCAL_DEFAULT_BASE_URL = "http://localhost:11434/v1"
LOCAL_API_KEY_ENV_VAR = "LOCAL_MODEL_API_KEY"

#: Hosts that keep embedding traffic on the workstation. Kept here rather than imported
#: from `local_provider`, so neither adapter owns the other's egress rules.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})


class LocalOpenAICompatibleEmbeddingProvider(_HttpEmbeddingProvider):
    """Embeddings from a local OpenAI-compatible server (Ollama, vLLM, LM Studio).

    Same wire format as the hosted adapter; the difference is the egress record, which
    reports that nothing leaves the workstation only when the endpoint really is
    loopback. Pass `dimension` to skip the one-off width probe.
    """

    name = "local"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = LOCAL_DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        dimension: int | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
        env: Mapping[str, str] | None = None,
    ) -> None:
        settings = ProviderSettings(
            provider=self.name,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout,
            api_key=resolve_api_key(api_key, LOCAL_API_KEY_ENV_VAR, env),
        )
        super().__init__(
            settings,
            egress=local_embedding_egress(base_url),
            dimension=dimension,
            transport=transport,
            batch_size=batch_size,
        )


def local_embedding_egress(base_url: str = LOCAL_DEFAULT_BASE_URL) -> EgressDeclaration:
    """Egress record for a local embedding server; honest when it is not loopback."""
    host = endpoint_host(base_url)
    loopback = host in _LOOPBACK_HOSTS or host.endswith(".local")
    return EgressDeclaration(
        endpoint_host=host,
        sends_source_text=not loopback,
        sends_identifiers=False,
        description=(
            f"Retrieval unit text is embedded by the local server at {host}; "
            "no content leaves the workstation."
            if loopback
            else f"Configured endpoint {host} is not loopback: retrieval unit text, and "
            "therefore the local corpus, leaves this workstation."
        ),
    )


def _read_embeddings(body: Mapping[str, Any], *, provider: str, expected: int) -> list[list[float]]:
    """Read `data[].embedding`, ordered by `index` when the backend reports one."""
    data = body.get("data")
    if not isinstance(data, list):
        raise ProviderResponseError(
            f"{provider} response carried no embedding data", provider=provider
        )
    items = list(iter_mappings(data))
    if len(items) != expected:
        raise ProviderResponseError(
            f"{provider} returned {len(items)} embeddings for {expected} texts",
            provider=provider,
        )
    ordered = sorted(enumerate(items), key=lambda pair: _item_index(pair[1], pair[0]))
    return [_read_vector(item.get("embedding"), provider=provider) for _, item in ordered]


def _item_index(item: Mapping[str, Any], fallback: int) -> int:
    value = item.get("index")
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value


def _read_vector(raw: Any, *, provider: str) -> list[float]:
    if not isinstance(raw, list) or not raw:
        raise ProviderResponseError(
            f"{provider} returned an embedding that is not a non-empty array",
            provider=provider,
        )
    vector: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ProviderResponseError(
                f"{provider} returned a non-numeric value inside an embedding",
                provider=provider,
            )
        vector.append(float(value))
    return vector


def _read_usage(body: Mapping[str, Any]) -> Usage:
    """Embedding usage, normalized like the chat adapters; output tokens are always 0."""
    usage = body.get("usage")
    counts: Mapping[str, Any] = usage if isinstance(usage, Mapping) else {}
    return usage_from(input_tokens=counts.get("prompt_tokens"), output_tokens=0)


# ---------------------------------------------------------------- offline adapter

IN_PROCESS_HOST = "(in-process)"
"""Egress host for a provider that opens no socket at all."""

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic offline vectors by signed feature hashing.

    **This is a lexical approximation, not a semantic model.** It hashes lowercased word
    n-grams (unigrams and bigrams by default) plus character 3-grams — which give it some
    robustness to unseen word forms, plurals and hyphenation — into a fixed number of
    buckets with a signed `blake2b` hash, then L2-normalizes. Cosine similarity therefore
    measures shared vocabulary, not shared meaning: a query that describes a paragraph in
    entirely different words will *not* retrieve it, which is exactly what a trained
    embedding model buys and this provider does not.

    It exists so that the index, its persistence, and its ranking are testable offline
    with no service dependency (ROADMAP SS5), and so that a workstation with no embedding
    budget still gets a usable, if lexical, vector index (ADR-006).
    """

    name = "hashing"
    max_batch_size = 512  # nothing leaves the process; batching only bounds list growth

    def __init__(
        self,
        dimension: int = 512,
        *,
        ngrams: tuple[int, ...] = (1, 2),
        char_ngram: int = 3,
        char_weight: float = 0.35,
    ) -> None:
        if dimension < 1:
            raise ValueError("dimension must be at least 1")
        if not ngrams or any(size < 1 for size in ngrams):
            raise ValueError("ngrams must be a non-empty tuple of positive sizes")
        if char_ngram < 0 or char_weight < 0.0:
            raise ValueError("char_ngram and char_weight must not be negative")
        self._dimension = dimension
        self._ngrams = ngrams
        self._char_ngram = char_ngram
        self._char_weight = char_weight

    @property
    def model(self) -> str:
        """Encodes the whole feature configuration: change it and the fingerprint moves."""
        words = "-".join(str(size) for size in self._ngrams)
        return f"blake2b-w{words}-c{self._char_ngram}-cw{self._char_weight:g}"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def egress(self) -> EgressDeclaration:
        return EgressDeclaration(
            endpoint_host=IN_PROCESS_HOST,
            sends_source_text=False,
            sends_identifiers=False,
            description="Vectors are computed in this process; nothing leaves the workstation.",
        )

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for feature, weight in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=9).digest()
            bucket = int.from_bytes(digest[:8], "big") % self._dimension
            vector[bucket] += -weight if digest[8] & 1 else weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]

    def _features(self, text: str) -> Iterator[tuple[str, float]]:
        """Word n-grams at full weight, then padded character n-grams at `char_weight`."""
        tokens = _TOKEN_PATTERN.findall(text.lower())
        for size in self._ngrams:
            for start in range(len(tokens) - size + 1):
                yield "w:" + " ".join(tokens[start : start + size]), 1.0
        if self._char_ngram == 0 or self._char_weight == 0.0:
            return
        for token in tokens:
            padded = f"^{token}$"
            for start in range(len(padded) - self._char_ngram + 1):
                yield "c:" + padded[start : start + self._char_ngram], self._char_weight

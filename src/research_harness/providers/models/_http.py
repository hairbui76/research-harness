"""Shared httpx plumbing: one client per adapter, one HTTP error mapping, one SSE reader.

Keeping the mapping here is what makes `ProviderAuthError`, `ProviderRateLimitError`
and `ProviderTransportError` mean the same thing for every backend, which later phases
rely on to decide what is retryable.

:func:`post_sse` is the same contract for a streamed call. Both hosted APIs answer a
streaming request with `text/event-stream`, and both spell one event as an optional
`event:` line plus one or more `data:` lines; what those payloads *mean* differs per
vendor and is parsed in the adapter. Abandoning the returned iterator closes the response,
which is how an interruption stops the call rather than draining it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from research_harness.providers.models.base import (
    ModelProvider,
    ProviderAuthError,
    ProviderCapabilities,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderSettings,
    ProviderTransportError,
)

_ERROR_EXCERPT_CHARS = 500


def build_client(
    *,
    base_url: str,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Create the adapter's HTTP client; tests inject `httpx.MockTransport` here."""
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(timeout_seconds),
        transport=transport,
    )


def post_json(
    client: httpx.Client,
    url: str,
    *,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    provider: str,
) -> dict[str, Any]:
    """POST JSON and return the decoded object, mapping failures to provider errors."""
    try:
        response = client.post(url, json=dict(payload), headers=dict(headers))
    except httpx.TimeoutException as exc:
        raise ProviderTransportError(
            f"{provider} request timed out: {exc}", provider=provider
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderTransportError(
            f"{provider} transport failure: {exc}", provider=provider
        ) from exc

    _raise_for_status(response, provider=provider)

    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderResponseError(
            f"{provider} returned a non-JSON body: {_excerpt(response.text)}", provider=provider
        ) from exc
    if not isinstance(body, dict):
        raise ProviderResponseError(
            f"{provider} returned JSON that is not an object: {_excerpt(response.text)}",
            provider=provider,
        )
    return body


@contextmanager
def post_sse(
    client: httpx.Client,
    url: str,
    *,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    provider: str,
) -> Iterator[Iterator[tuple[str, Any]]]:
    """POST and yield `(event name, decoded data)` pairs from a server-sent event stream.

    The event name is the `event:` line when the server sends one and `"message"` when it
    does not, which is what the SSE default is. `data:` payloads are decoded as JSON;
    `[DONE]`, the sentinel OpenAI-compatible servers end with, is passed through as the
    string it is so the adapter decides what it means. A payload that is neither is
    skipped rather than raised on: a keep-alive comment or a vendor extension must not
    break an answer that is already arriving.
    """
    try:
        with client.stream("POST", url, json=dict(payload), headers=dict(headers)) as response:
            if response.status_code >= 400:
                response.read()
                _raise_for_status(response, provider=provider)
            yield _sse_events(response, provider=provider)
    except httpx.TimeoutException as exc:
        raise ProviderTransportError(
            f"{provider} request timed out: {exc}", provider=provider
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderTransportError(
            f"{provider} transport failure: {exc}", provider=provider
        ) from exc


def _sse_events(response: httpx.Response, *, provider: str) -> Iterator[tuple[str, Any]]:
    """Decode one `text/event-stream` body into `(event, data)` pairs, in order."""
    del provider
    name = "message"
    data: list[str] = []
    for raw in response.iter_lines():
        line = raw.rstrip("\r")
        if not line:
            if data:
                yield name, _sse_data("\n".join(data))
            name, data = "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            name = value
        elif field == "data":
            data.append(value)
    if data:
        yield name, _sse_data("\n".join(data))


def _sse_data(payload: str) -> Any:
    """One `data:` payload as JSON, or the raw string when it is not JSON."""
    try:
        return json.loads(payload)
    except ValueError:
        return payload


def _raise_for_status(response: httpx.Response, *, provider: str) -> None:
    status = response.status_code
    if status < 400:
        return
    detail = f"{provider} HTTP {status}: {_excerpt(response.text)}"
    if status in (401, 403):
        raise ProviderAuthError(detail, provider=provider)
    if status == 429:
        raise ProviderRateLimitError(
            detail,
            provider=provider,
            retry_after_seconds=_retry_after(response),
        )
    if status >= 500:
        raise ProviderTransportError(detail, provider=provider)
    raise ProviderResponseError(detail, provider=provider)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _ERROR_EXCERPT_CHARS:
        return collapsed
    return collapsed[:_ERROR_EXCERPT_CHARS] + "..."


def endpoint_host(base_url: str) -> str:
    """Host an adapter talks to, for its egress declaration."""
    return urlsplit(base_url).hostname or base_url


class HttpModelProvider(ModelProvider):
    """A `ModelProvider` backed by one HTTP endpoint and a reusable client.

    Owns the client lifecycle, the capability record and a `repr` that can never leak
    the API key; subclasses only implement the wire format in `_execute`.
    """

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        capabilities: ProviderCapabilities,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._capabilities = capabilities
        self._client = build_client(
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            transport=transport,
        )

    def capabilities(self) -> ProviderCapabilities:
        """The configured capability record for this provider/model pair."""
        return self._capabilities

    def _post(
        self, url: str, payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> dict[str, Any]:
        return post_json(self._client, url, payload=payload, headers=headers, provider=self.name)

    def _post_stream(
        self, url: str, payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> AbstractContextManager[Iterator[tuple[str, Any]]]:
        """The same POST as a server-sent event stream; closing it interrupts the call."""
        return post_sse(self._client, url, payload=payload, headers=headers, provider=self.name)

    def _api_key(self) -> str | None:
        key = self.settings.api_key
        return key.get_secret_value() if key is not None else None

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

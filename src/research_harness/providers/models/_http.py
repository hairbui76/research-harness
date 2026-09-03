"""Shared httpx plumbing: one client per adapter and one HTTP error mapping.

Keeping the mapping here is what makes `ProviderAuthError`, `ProviderRateLimitError`
and `ProviderTransportError` mean the same thing for every backend, which later phases
rely on to decide what is retryable.
"""

from __future__ import annotations

from collections.abc import Mapping
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

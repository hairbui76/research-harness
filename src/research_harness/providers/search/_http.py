"""Shared httpx plumbing for discovery sources: one polite client, one error mapping.

Scholarly APIs ask callers to identify themselves and to supply a contact address; doing
so is what keeps a workstation inside the sources' polite-use pools rather than in their
rate-limited anonymous pool. The address is read from
`RESEARCH_HARNESS_CONTACT_EMAIL` only -- never from a canonical workspace file
(Product 34) -- and is optional: without it the adapters still work, they are just
anonymous.

The status mapping lives here so `SearchRateLimitError`, `SearchAuthError`,
`SearchAccessBarrierError`, `SearchTransportError` and `SearchResponseError` mean exactly
the same thing for all five sources, which is what lets Task 12.2 record one honest
`SourceFailure` vocabulary (ROADMAP Task 12.1).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from research_harness import __version__
from research_harness.providers.search.base import (
    SearchAccessBarrierError,
    SearchAuthError,
    SearchProvider,
    SearchProviderCapabilities,
    SearchRateLimitError,
    SearchResponseError,
    SearchTransportError,
)

__all__ = [
    "CONTACT_EMAIL_ENV_VAR",
    "DEFAULT_TIMEOUT_SECONDS",
    "PROJECT_URL",
    "HttpSearchProvider",
    "build_client",
    "contact_email",
    "endpoint_host",
    "polite_user_agent",
]

CONTACT_EMAIL_ENV_VAR = "RESEARCH_HARNESS_CONTACT_EMAIL"
"""Environment variable holding the polite-pool contact address; never a config file."""

PROJECT_URL = "https://github.com/research-harness/research-harness"
DEFAULT_TIMEOUT_SECONDS = 30.0

_ERROR_EXCERPT_CHARS = 300
_BARRIER_SCAN_CHARS = 2000
_BARRIER_MARKERS = (
    "captcha",
    "challenge",
    "cf-browser-verification",
    "are you a robot",
    "access denied",
    "unusual traffic",
)
_HTML_PREFIXES = ("<!doctype html", "<html")


def contact_email(env: Mapping[str, str] | None = None) -> str | None:
    """Polite-pool contact address from the environment, or `None` when unset."""
    source: Mapping[str, str] = os.environ if env is None else env
    value = source.get(CONTACT_EMAIL_ENV_VAR, "")
    return value.strip() or None


def polite_user_agent(email: str | None = None) -> str:
    """`research-harness/<version> (+url; mailto:you@example.org)`, the form Crossref asks for."""
    agent = f"research-harness/{__version__} (+{PROJECT_URL}"
    if email:
        return f"{agent}; mailto:{email})"
    return f"{agent})"


def endpoint_host(base_url: str) -> str:
    """Host an adapter talks to, for its egress declaration."""
    return urlsplit(base_url).hostname or base_url


def build_client(
    *,
    base_url: str,
    timeout_seconds: float,
    headers: Mapping[str, str],
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Create the adapter's HTTP client; tests inject `httpx.MockTransport` here."""
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(timeout_seconds),
        headers=dict(headers),
        follow_redirects=True,
        transport=transport,
    )


class HttpSearchProvider(SearchProvider):
    """A discovery source reached over HTTP, with the shared client and error mapping.

    Subclasses own only their wire format: which parameters express a query and how one
    record becomes a `WorkCandidate`.
    """

    name: str

    def __init__(
        self,
        *,
        base_url: str,
        capabilities: SearchProviderCapabilities,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        env: Mapping[str, str] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.contact_email = contact_email(env)
        self._capabilities = capabilities
        headers = {
            "user-agent": polite_user_agent(self.contact_email),
            "accept": "application/json",
            **(dict(extra_headers) if extra_headers else {}),
        }
        self._client = build_client(
            base_url=base_url,
            timeout_seconds=timeout,
            headers=headers,
            transport=transport,
        )

    def capabilities(self) -> SearchProviderCapabilities:
        """The declared capability and egress record for this source."""
        return self._capabilities

    # ------------------------------------------------------------------ requests

    def _get_json(
        self, url: str, params: Mapping[str, str], *, query: str | None = None
    ) -> Mapping[str, Any]:
        """GET and decode a JSON object, mapping every failure to a search error."""
        response = self._get(url, params, query=query)
        if _is_html_body(response):
            raise SearchAccessBarrierError(
                f"{self.name} served an HTML page instead of JSON: {_excerpt(response.text)}",
                source=self.name,
                query=query,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise SearchResponseError(
                f"{self.name} returned a non-JSON body: {_excerpt(response.text)}",
                source=self.name,
                query=query,
            ) from exc
        if not isinstance(body, Mapping):
            raise SearchResponseError(
                f"{self.name} returned JSON that is not an object: {_excerpt(response.text)}",
                source=self.name,
                query=query,
            )
        return body

    def _get_text(self, url: str, params: Mapping[str, str], *, query: str | None = None) -> str:
        """GET a text body (Atom XML); an HTML body is a barrier, not a document."""
        response = self._get(url, params, query=query)
        if _is_html_body(response):
            raise SearchAccessBarrierError(
                f"{self.name} served an HTML page instead of a feed: {_excerpt(response.text)}",
                source=self.name,
                query=query,
            )
        return response.text

    def _get(self, url: str, params: Mapping[str, str], *, query: str | None) -> httpx.Response:
        try:
            response = self._client.get(url, params=dict(params))
        except httpx.TimeoutException as exc:
            raise SearchTransportError(
                f"{self.name} request timed out: {exc}", source=self.name, query=query
            ) from exc
        except httpx.HTTPError as exc:
            raise SearchTransportError(
                f"{self.name} transport failure: {exc}", source=self.name, query=query
            ) from exc
        self._raise_for_status(response, query=query)
        return response

    def _raise_for_status(self, response: httpx.Response, *, query: str | None) -> None:
        status = response.status_code
        if status < 400:
            return
        detail = f"{self.name} HTTP {status}: {_excerpt(response.text)}"
        if status in (401, 403):
            if _looks_like_access_barrier(response):
                raise SearchAccessBarrierError(detail, source=self.name, query=query)
            raise SearchAuthError(detail, source=self.name, query=query)
        if status == 429:
            raise SearchRateLimitError(
                detail,
                source=self.name,
                query=query,
                retry_after=_retry_after(response),
            )
        if status >= 500:
            raise SearchTransportError(detail, source=self.name, query=query)
        raise SearchResponseError(detail, source=self.name, query=query)

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a numeric `Retry-After`; an HTTP-date form is reported as unknown."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _is_html_body(response: httpx.Response) -> bool:
    """True when the body is an HTML document, whatever the status code says."""
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" in content_type:
        return True
    head = response.text[:_BARRIER_SCAN_CHARS].lstrip().lower()
    return head.startswith(_HTML_PREFIXES)


def _looks_like_access_barrier(response: httpx.Response) -> bool:
    """HTML wall or an interstitial marker; only consulted for 401/403 bodies.

    Marker matching is deliberately not applied to successful bodies: an abstract may
    legitimately contain the word "challenge".
    """
    if _is_html_body(response):
        return True
    head = response.text[:_BARRIER_SCAN_CHARS].lower()
    return any(marker in head for marker in _BARRIER_MARKERS)


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _ERROR_EXCERPT_CHARS:
        return collapsed
    return collapsed[:_ERROR_EXCERPT_CHARS] + "..."

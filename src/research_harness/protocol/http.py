"""A small typed client for the local daemon, shared by tests, the Web cockpit, and VS Code.

`PRODUCT` 35 asks for a local HTTP/JSON-RPC daemon *plus a small SDK* so clients that cannot
speak MCP still call the same capabilities. This is that SDK: it knows the routes and the
envelopes, and nothing else. Every method returns a typed model from
:mod:`research_harness.protocol.dto`, so a client that drifts from the daemon fails at the
boundary rather than three layers in.

    client = HarnessHttpClient("http://127.0.0.1:8765", token=Path(...).read_text())
    catalog = client.capabilities()
    answer = client.invoke("claim.audit", {"claim_id": "C0001", ...})

A caller with no token is an agent host to the daemon: reads and staging succeed, accepting
evidence comes back as ``ok=False`` with ``code="permission_denied"``. That refusal is the
contract, not an error in the client (Product 29).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel

from research_harness.protocol.dto import (
    CapabilityCatalog,
    CapabilityResponse,
    HealthReport,
    ObjectView,
    RunStatus,
)

__all__ = ["DEFAULT_BASE_URL", "HarnessHttpClient"]

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
"""Loopback only. The daemon is a single-user local workstation service (Product 4)."""


class HarnessHttpClient:
    """Typed access to one running daemon.

    ``transport`` exists so tests (and an embedding application) can drive the ASGI app in
    process with no socket at all; production callers pass nothing.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        headers = {"Authorization": f"Bearer {token.strip()}"} if token else {}
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        """Close the underlying connection pool when this client opened it."""
        if self._owns_client:
            self._client.close()

    # -- reads ---------------------------------------------------------------

    def health(self) -> HealthReport:
        """Whether the daemon can serve its workspace, and which workspace that is."""
        return HealthReport.model_validate(self._json("GET", "/health"))

    def capabilities(self) -> CapabilityCatalog:
        """Every named capability, its permission, and both JSON schemas."""
        return CapabilityCatalog.model_validate(self._json("GET", "/capabilities"))

    def object(self, object_id: str) -> ObjectView:
        """One canonical object by research id."""
        return ObjectView.model_validate(self._json("GET", f"/objects/{object_id}"))

    def run(self, run_id: str) -> RunStatus:
        """The durable record of one long-running workflow."""
        return RunStatus.model_validate(self._json("GET", f"/runs/{run_id}"))

    # -- calls ---------------------------------------------------------------

    def invoke(
        self, name: str, request: BaseModel | Mapping[str, Any] | None = None
    ) -> CapabilityResponse:
        """Invoke one capability. A refusal comes back as ``ok=False``, not an exception."""
        payload = _payload(request)
        response = self._client.post(f"/capabilities/{name}", json=payload)
        return CapabilityResponse.model_validate(response.json())

    def cancel(self, run_id: str) -> RunStatus:
        """Ask a run to stop before its next stage."""
        response = self._client.post(f"/runs/{run_id}/cancel")
        response.raise_for_status()
        return RunStatus.model_validate(response.json())

    # -- plumbing ------------------------------------------------------------

    def _json(self, method: str, path: str) -> Any:
        response = self._client.request(method, path)
        response.raise_for_status()
        return response.json()


def _payload(request: BaseModel | Mapping[str, Any] | None) -> dict[str, Any]:
    """The request body: a model dumped to JSON, a mapping as given, or nothing."""
    if request is None:
        return {}
    if isinstance(request, BaseModel):
        return request.model_dump(mode="json")
    return dict(request)

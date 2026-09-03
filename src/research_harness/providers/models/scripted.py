"""Deterministic in-process model provider for CI, offline demos, and tests.

A scripted provider answers from a list (or a function) the caller supplies, records every
`ModelRequest` it was given, and sends nothing anywhere: its egress declaration says so, and
there is no transport to misconfigure. That makes it the provider the evidence pipeline is
exercised with (ROADMAP §5: deterministic, hermetic, offline), and the one a demo workspace
can run without a key.

It is a real adapter, not a stub: replies go through `ModelProvider.complete`, so a scripted
dict that does not satisfy the caller's schema raises `StructuredOutputError` exactly as a
live provider would, and invalid model output still cannot reach staging (ADR-005).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from research_harness.providers.models.base import (
    EgressDeclaration,
    ModelProvider,
    ModelRequest,
    ProviderCapabilities,
    ProviderResponseError,
    RawCompletion,
    Usage,
)
from research_harness.providers.models.media import (
    IMAGE_MEDIA_TYPES,
    MediaPart,
    media_parts,
    normalize_media_type,
)
from research_harness.providers.models.router import ModelRouter, ProviderEntry

__all__ = [
    "DEFAULT_SCRIPTED_MODEL",
    "ScriptedProvider",
    "ScriptedResponse",
    "default_scripted_capabilities",
    "scripted_router",
]

DEFAULT_SCRIPTED_MODEL = "scripted-1"
"""Model identifier every scripted response reports, so provenance stays honest."""

ScriptedResponse = BaseModel | Mapping[str, Any] | str | Exception
"""One canned reply: a model, a JSON object, raw text, or a failure to raise."""

ScriptedScript = Sequence[ScriptedResponse] | Callable[[ModelRequest[Any]], ScriptedResponse]
"""Either a queue of replies consumed in order, or a function of the request."""


def default_scripted_capabilities(*, input_media: Iterable[str] = ()) -> ProviderCapabilities:
    """Everything a role can ask for, and an explicit declaration of no egress.

    `input_media` is the one deliberately configurable capability: a scripted provider
    stands in for a real model in tests, and an attachment send has to be exercised
    against both a model that accepts the media and one that does not (attachments design
    SS5). Passing image types also sets `vision`, exactly as a real adapter's defaults do.
    """
    media = frozenset(normalize_media_type(value) for value in input_media)
    return ProviderCapabilities(
        structured_output=True,
        max_context_tokens=2_000_000,
        reasoning_levels={"low", "medium", "high"},
        vision=bool(media & IMAGE_MEDIA_TYPES),
        input_media=media,
        egress=EgressDeclaration(
            endpoint_host="localhost",
            sends_source_text=False,
            sends_identifiers=False,
            description=(
                "No egress: replies are scripted in-process and no bytes leave the workstation."
            ),
        ),
    )


class ScriptedProvider(ModelProvider):
    """Answers from a script, records every request, and never touches a network.

    `responses` is either a sequence consumed in order (the last one does *not* repeat: an
    exhausted script is a `ProviderResponseError`, because a silent replay would hide a
    test that asked for one call too many) or a callable invoked with the request.
    """

    name = "scripted"

    def __init__(
        self,
        responses: ScriptedScript,
        *,
        name: str = "scripted",
        model: str = DEFAULT_SCRIPTED_MODEL,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.requests: list[ModelRequest[Any]] = []
        self._capabilities = capabilities or default_scripted_capabilities()
        self._script: Callable[[ModelRequest[Any]], ScriptedResponse] | None = None
        self._queue: list[ScriptedResponse] = []
        if callable(responses):
            self._script = responses
        else:
            self._queue = list(responses)

    @property
    def remaining(self) -> int:
        """How many queued replies are left; always 0 for a callable script."""
        return len(self._queue)

    def capabilities(self) -> ProviderCapabilities:
        """Full capabilities with a no-egress declaration (Product §34)."""
        return self._capabilities

    @property
    def media(self) -> list[MediaPart]:
        """Every media part this provider has been handed, in call order.

        Recorded separately from `requests` so a test can assert that an attachment
        reached the model exactly once, which is the property the `Context used` receipt
        claims (attachments design SS5).
        """
        return [part for request in self.requests for part in media_parts(request.inputs)]

    def _execute[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> RawCompletion:
        """Record the request and return the next scripted reply as raw text."""
        self.requests.append(request)
        reply = self._next(request)
        if isinstance(reply, Exception):
            raise reply
        return RawCompletion(
            text=_render(reply),
            usage=Usage(input_tokens=0, output_tokens=0),
            model=self.model,
            stop_reason="stop",
        )

    def _next(self, request: ModelRequest[Any]) -> ScriptedResponse:
        if self._script is not None:
            return self._script(request)
        if not self._queue:
            raise ProviderResponseError(
                f"scripted provider {self.name!r} ran out of responses at call "
                f"{len(self.requests)} for role {request.role!r}",
                provider=self.name,
            )
        return self._queue.pop(0)


def _render(reply: BaseModel | Mapping[str, Any] | str) -> str:
    """Serialize a scripted reply the way a provider would put it on the wire."""
    if isinstance(reply, BaseModel):
        return reply.model_dump_json()
    if isinstance(reply, str):
        return reply
    return json.dumps(dict(reply), ensure_ascii=False)


def scripted_router(
    provider: ScriptedProvider,
    *,
    priority: int = 0,
    roles: set[str] | None = None,
) -> ModelRouter:
    """A one-entry `ModelRouter` over a scripted provider, for router-level code paths.

    Named as a function rather than a class because it builds a plain `ModelRouter`; there
    is no scripted router type to keep in sync with the real one.
    """
    return ModelRouter(
        [ProviderEntry(provider=provider, model=provider.model, priority=priority, roles=roles)]
    )

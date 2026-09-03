"""A tiny in-memory `ModelProvider` plus the schema the cross-verification tests compare on.

No transport, no key, no network: the provider answers from a canned dict or raises, which
is everything a policy test needs from a model backend.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from research_harness.providers.models.base import (
    EgressDeclaration,
    ModelProvider,
    ModelRequest,
    ModelRequirements,
    ProviderCapabilities,
    ProviderError,
    RawCompletion,
    Usage,
)

REQUIREMENTS = ModelRequirements(
    structured_output=True, context_tokens=1000, reasoning="high", vision=False
)


class Judgement(BaseModel):
    """A stand-in role output: one comparable decision plus prose that is never compared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: str
    coverage_state: str = "10 of 10 examined"
    rationale: str = "because the source says so"


def capabilities(host: str = "fake.invalid") -> ProviderCapabilities:
    """Declared capabilities wide enough for any request these tests build."""
    return ProviderCapabilities(
        structured_output=True,
        max_context_tokens=1_000_000,
        reasoning_levels={"low", "medium", "high"},
        vision=False,
        egress=EgressDeclaration(
            endpoint_host=host,
            sends_source_text=False,
            sends_identifiers=False,
            description="fake provider used in tests; nothing leaves the process",
        ),
    )


class FakeProvider(ModelProvider):
    """Answers with a fixed payload, or raises the error it was built with.

    `calls` records every request it was asked to run, which is how the tests check that a
    budget or a skip really prevented a call rather than merely ignoring its result.
    """

    def __init__(
        self,
        name: str,
        answer: Mapping[str, Any] | None = None,
        *,
        model: str = "fake-1",
        error: ProviderError | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._answer = dict(answer or {"verdict": "supported"})
        self._error = error
        self.calls: list[ModelRequest[Any]] = []

    def capabilities(self) -> ProviderCapabilities:
        return capabilities(f"{self.name}.invalid")

    def _execute(self, request: ModelRequest[Any], schema_json: dict[str, Any]) -> RawCompletion:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        return RawCompletion(
            text=json.dumps(self._answer),
            usage=Usage(input_tokens=1, output_tokens=1),
            model=self.model,
            stop_reason="stop",
        )

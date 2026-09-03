"""Provider-neutral semantic runtime: one contract, several model backends.

Import the contract from here rather than from the individual adapter modules::

    from research_harness.providers.models import (
        InputEnvelope, ModelRequest, ModelRequirements, ModelRouter,
    )

:func:`describe_backend` also lives here: naming which provider and model *would* answer a
role's request is a property of the routing layer, and two application packages used to
answer it separately. It takes the role contract structurally rather than importing
`roles/`, which imports this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from research_harness.providers.models.anthropic_provider import (
    AnthropicProvider,
    default_anthropic_capabilities,
)
from research_harness.providers.models.base import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    EgressDeclaration,
    InputEnvelope,
    ModelProvider,
    ModelRequest,
    ModelRequirements,
    ModelResponse,
    ProviderAuthError,
    ProviderCapabilities,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderSettings,
    ProviderTransportError,
    RawCompletion,
    ReasoningLevel,
    StructuredOutputError,
    Usage,
    canonical_json,
    normalize_json_schema,
    parse_structured_output,
    render_inputs,
    resolve_api_key,
)
from research_harness.providers.models.local_provider import (
    LocalOpenAICompatibleProvider,
    default_local_capabilities,
)
from research_harness.providers.models.openai_provider import (
    OpenAIProvider,
    default_openai_capabilities,
)
from research_harness.providers.models.router import (
    CapabilityOverrides,
    ModelRouter,
    NoCapableProviderError,
    ProviderEntry,
    ProviderKind,
    RouterConfig,
    RouterProviderConfig,
    build_router,
)

__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "AnthropicProvider",
    "BackendInfo",
    "CapabilityOverrides",
    "EgressDeclaration",
    "InputEnvelope",
    "LocalOpenAICompatibleProvider",
    "ModelProvider",
    "ModelRequest",
    "ModelRequirements",
    "ModelResponse",
    "ModelRouter",
    "NoCapableProviderError",
    "OpenAIProvider",
    "ProviderAuthError",
    "ProviderCapabilities",
    "ProviderEntry",
    "ProviderError",
    "ProviderKind",
    "ProviderRateLimitError",
    "ProviderResponseError",
    "ProviderSettings",
    "ProviderTransportError",
    "RawCompletion",
    "ReasoningLevel",
    "RoleLike",
    "RouterConfig",
    "RouterProviderConfig",
    "StructuredOutputError",
    "Usage",
    "build_router",
    "canonical_json",
    "default_anthropic_capabilities",
    "default_local_capabilities",
    "default_openai_capabilities",
    "describe_backend",
    "normalize_json_schema",
    "parse_structured_output",
    "render_inputs",
    "resolve_api_key",
]


class RoleLike(Protocol):
    """The part of a role contract that decides which backend answers it.

    Structural on purpose: `roles.contracts` imports this package, so naming
    `RoleContract` here would be a cycle. A role is a name and a set of requirements as far
    as routing is concerned, and nothing else about it belongs in `providers/`.
    """

    @property
    def name(self) -> str:
        """The role name a router selects on."""
        ...

    @property
    def requirements(self) -> ModelRequirements:
        """What the role needs of a provider."""
        ...


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """Which provider and model actually answered, for provenance and fingerprints."""

    provider: str
    model: str

    @property
    def label(self) -> str:
        """`provider/model`, the `Provenance.actor` form for a model proposal."""
        return f"{self.provider}/{self.model}"


def describe_backend(client: ModelProvider | ModelRouter, contract: RoleLike) -> BackendInfo:
    """The provider/model a role's request would go to, without sending it.

    Needed *before* the call, because a stage fingerprint has to include which model
    produced the answer: re-running a field on another provider must recompute that field
    (Product 19.1). A router answers by selecting; a bare adapter answers with the model it
    was configured with, and `unknown` when it names none rather than inventing one.
    """
    if isinstance(client, ModelRouter):
        entry = client.select(contract.requirements, contract.name)
        return BackendInfo(provider=entry.provider.name, model=entry.model)
    return BackendInfo(provider=client.name, model=_configured_model(client))


def _configured_model(provider: ModelProvider) -> str:
    """The model identifier an adapter was configured with, for reproducibility metadata."""
    model = getattr(provider, "model", None)
    if not isinstance(model, str):
        settings = getattr(provider, "settings", None)
        model = getattr(settings, "model", None)
    return model if isinstance(model, str) else "unknown"

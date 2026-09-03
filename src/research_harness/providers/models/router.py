"""Capability-based routing: configuration picks the model, never domain code.

A workflow states what it needs (`ModelRequirements`) and which role is asking; the
router keeps the entries whose declared `ProviderCapabilities` satisfy that and takes
the highest-priority survivor. There is deliberately no branch on evidence, claims, or
any other domain concept -- adding a provider or changing which model does a job is a
configuration edit (ROADMAP Task 4.1, Product SS20.2).

When nothing qualifies the router raises `NoCapableProviderError` naming every
candidate and why it was rejected, so a misconfigured workspace is diagnosable without
reading this module.

A router may also carry the project's `EgressPolicy` (Product SS34). The policy is applied
during *selection*, before a request is built: a provider whose declared egress the policy
refuses is skipped like any other unusable candidate, so a workspace with external models
disabled still routes to a local one, and when every capable candidate is refused the
router raises `EgressDeniedError` rather than sending anything.

`ModelRouter.egress_refusal` asks the same question *without* a request, for a caller that
hands the router to a background run and would otherwise learn the answer on a worker
thread, long after it answered its own caller.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_harness.privacy.policy import (
    EgressDeniedError,
    EgressPolicy,
    check_egress,
    denial,
    refuse_inline_secrets,
)
from research_harness.providers.models.anthropic_provider import (
    DEFAULT_BASE_URL as ANTHROPIC_BASE_URL,
)
from research_harness.providers.models.anthropic_provider import (
    AnthropicProvider,
    default_anthropic_capabilities,
)
from research_harness.providers.models.base import (
    ModelProvider,
    ModelRequest,
    ModelRequirements,
    ModelResponse,
    ProviderCapabilities,
    ProviderError,
    TraceSink,
)
from research_harness.providers.models.local_provider import (
    DEFAULT_BASE_URL as LOCAL_BASE_URL,
)
from research_harness.providers.models.local_provider import (
    LocalOpenAICompatibleProvider,
    default_local_capabilities,
)
from research_harness.providers.models.media import (
    IMAGE_MEDIA_TYPES,
    SUPPORTED_MEDIA_TYPES,
    accepts_media,
    media_parts,
    normalize_media_type,
)
from research_harness.providers.models.openai_provider import (
    DEFAULT_BASE_URL as OPENAI_BASE_URL,
)
from research_harness.providers.models.openai_provider import (
    OpenAIProvider,
    default_openai_capabilities,
)

ProviderKind = Literal["openai", "anthropic", "local_openai_compatible"]

_DEFAULT_BASE_URLS: dict[ProviderKind, str] = {
    "openai": OPENAI_BASE_URL,
    "anthropic": ANTHROPIC_BASE_URL,
    "local_openai_compatible": LOCAL_BASE_URL,
}


class NoCapableProviderError(ProviderError):
    """No configured provider satisfies the requested capabilities for this role."""


@dataclass(frozen=True)
class ProviderEntry:
    """One routable provider/model pair.

    `priority` orders candidates -- lower values are preferred, ties resolve to
    declaration order. `roles` restricts the entry to named roles (`None` means any
    role); `tags` are free labels a workspace can use to describe an entry.
    """

    provider: ModelProvider
    model: str
    priority: int = 100
    roles: set[str] | None = None
    tags: set[str] = field(default_factory=set)

    @property
    def label(self) -> str:
        """Human-readable identity used in routing diagnostics."""
        return f"{self.provider.name}/{self.model}"


class ModelRouter:
    """Selects a provider by declared capability, then priority.

    A failing call is not retried on the next capable provider: which model produced a
    result is reproducibility metadata, so a silent switch would misreport it. Failover
    and cross-model verification are explicit policies for the caller (Product SS20.4).

    `policy` is the project's egress policy (Product SS34); `None` means unrestricted,
    which is what a router built outside a workspace gets.
    """

    def __init__(
        self, entries: Sequence[ProviderEntry], *, policy: EgressPolicy | None = None
    ) -> None:
        self.entries: tuple[ProviderEntry, ...] = tuple(entries)
        self.policy = policy

    def with_policy(self, policy: EgressPolicy | None) -> ModelRouter:
        """The same entries under a different policy; used when a caller narrows a router."""
        return ModelRouter(self.entries, policy=policy)

    def select(
        self,
        requirements: ModelRequirements,
        role: str,
        *,
        media: Sequence[str] = (),
    ) -> ProviderEntry:
        """Return the preferred capable and permitted entry, or explain every rejection.

        The privacy policy is consulted here, before any request exists, so a refused
        provider is never called. A refusal is not a capability problem: when it is the
        only thing standing between the caller and a provider, `EgressDeniedError` is
        raised so the message names the policy rather than the model.

        ``media`` is the media types the request actually carries. `attachment.check_send`
        asks the same question before a person presses send; this is the last line, and it
        reads the inputs rather than a declaration, so a request that gained an attachment
        after it stated its requirements is refused rather than silently stripped.
        """
        rejections: list[str] = []
        denials: list[EgressDeniedError] = []
        for entry in sorted(self.entries, key=lambda item: item.priority):
            reasons = _rejection_reasons(entry, requirements, role, media=media)
            if reasons:
                rejections.append(f"{entry.label}: {'; '.join(reasons)}")
                continue
            refusal = self._denial_for(entry)
            if refusal is not None:
                denials.append(refusal)
                rejections.append(f"{entry.label}: refused by the privacy policy")
                continue
            return entry
        if denials:
            raise _combined_denial(role, denials)
        raise NoCapableProviderError(_no_capable_message(role, requirements, rejections))

    def complete[T: BaseModel](
        self, request: ModelRequest[T], *, trace: TraceSink | None = None
    ) -> ModelResponse[T]:
        """Route the request by its own requirements/role and run it."""
        entry = self.select(
            request.requirements,
            request.role,
            media=[part.media_type for part in media_parts(request.inputs)],
        )
        return entry.provider.complete(request, trace=trace)

    def egress_refusal(self) -> EgressDeniedError | None:
        """The refusal covering *every* entry, or `None` when one of them may be called.

        :meth:`select` refuses lazily, once a request and a role exist, which is right for
        routing: a provider refused for one role can still serve another. A caller that is
        about to hand this router to a background run has to know sooner. A refusal
        discovered on a worker thread is a failed run record rather than an answer, and the
        researcher who started the run over HTTP or MCP never sees the policy that stopped
        it — which is the whole point of deciding egress at selection (Product 34,
        ADR-018).

        Only an entirely refused table answers here. One usable entry means routing is
        still a routing question, and `select` will ask it.
        """
        if self.policy is None or not self.entries:
            return None
        refused = [self._denial_for(entry) for entry in self.entries]
        denials = [item for item in refused if item is not None]
        if len(denials) != len(self.entries):
            return None
        headline = "every configured provider is refused by the privacy policy"
        return _merged_denial(headline, denials)

    def _denial_for(self, entry: ProviderEntry) -> EgressDeniedError | None:
        """The policy refusal for one entry, or `None` when it may be called."""
        if self.policy is None:
            return None
        egress = entry.provider.capabilities().egress
        check = check_egress(self.policy, egress, kind="model")
        if check.allowed:
            return None
        return denial(entry.label, egress, check, kind="model")


def _combined_denial(role: str, denials: Sequence[EgressDeniedError]) -> EgressDeniedError:
    """One error for however many providers the policy refused for one role, naming each."""
    return _merged_denial(
        f"every capable provider for role {role!r} is refused by the privacy policy", denials
    )


def _merged_denial(headline: str, denials: Sequence[EgressDeniedError]) -> EgressDeniedError:
    """The single refusal a caller sees: one denial as itself, several under ``headline``."""
    first = denials[0]
    if len(denials) == 1:
        return first
    listed = "\n".join(f"  - {error.message}" for error in denials)
    fields = tuple(dict.fromkeys(name for error in denials for name in error.policy_fields))
    return EgressDeniedError(
        f"{headline}:\n{listed}",
        provider=first.provider,
        endpoint_host=first.endpoint_host,
        policy_fields=fields,
    )


def _rejection_reasons(
    entry: ProviderEntry,
    requirements: ModelRequirements,
    role: str,
    *,
    media: Sequence[str] = (),
) -> list[str]:
    reasons: list[str] = []
    if entry.roles is not None and role not in entry.roles:
        allowed = ", ".join(sorted(entry.roles)) or "none"
        reasons.append(f"role {role!r} not in allowed roles ({allowed})")
    capabilities = entry.provider.capabilities()
    if requirements.structured_output and not capabilities.structured_output:
        reasons.append("structured output required but not supported")
    if requirements.context_tokens > capabilities.max_context_tokens:
        reasons.append(
            f"context window {capabilities.max_context_tokens} < required "
            f"{requirements.context_tokens}"
        )
    if requirements.reasoning not in capabilities.reasoning_levels:
        levels = ", ".join(sorted(capabilities.reasoning_levels)) or "none"
        reasons.append(f"reasoning {requirements.reasoning!r} not offered (has: {levels})")
    if requirements.vision and not capabilities.vision:
        reasons.append("vision required but not supported")
    refused = _unaccepted_media(capabilities, requirements, media)
    if refused:
        accepted = ", ".join(sorted(capabilities.input_media)) or "no media input"
        reasons.append(f"media {', '.join(refused)} not accepted (accepts: {accepted})")
    return reasons


def _unaccepted_media(
    capabilities: ProviderCapabilities, requirements: ModelRequirements, media: Sequence[str]
) -> list[str]:
    """Media types this request needs and this entry does not take, deduplicated.

    Both spellings count: what the job *declared* it needs, and what its inputs actually
    carry. An adapter raises `UnsupportedMediaError` while encoding the second kind, which
    is a failure discovered after the model was chosen; refusing here keeps the choice
    honest and lets the message name a model that would have taken the file.
    """
    needed = {
        *requirements.input_media,
        *(normalize_media_type(value) for value in media),
    }
    return sorted(item for item in needed if item and not accepts_media(capabilities, item))


def _no_capable_message(
    role: str, requirements: ModelRequirements, rejections: Sequence[str]
) -> str:
    wanted = (
        f"structured_output={requirements.structured_output}, "
        f"context_tokens={requirements.context_tokens}, "
        f"reasoning={requirements.reasoning!r}, vision={requirements.vision}"
    )
    if not rejections:
        return f"no providers are configured; role {role!r} requires {wanted}"
    listed = "\n".join(f"  - {reason}" for reason in rejections)
    return f"no capable provider for role {role!r} requiring {wanted}:\n{listed}"


# ------------------------------------------------------------------- configuration


class CapabilityOverrides(BaseModel):
    """Per-model capability facts a workspace states that the adapter cannot know."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    structured_output: bool | None = None
    max_context_tokens: int | None = Field(default=None, gt=0)
    reasoning_levels: list[str] | None = None
    vision: bool | None = None
    input_media: list[str] | None = None
    """Media types the served model accepts, e.g. `["image/png", "application/pdf"]`.

    `vision` is the older spelling of the image half of this fact; `_merge_capabilities`
    keeps the two in agreement, and stating both leaves them exactly as written."""

    @field_validator("input_media")
    @classmethod
    def _known_media_types(cls, value: list[str] | None) -> list[str] | None:
        """Normalize the declared types and refuse one the harness cannot encode.

        A typo would otherwise become a model that quietly accepts nothing, and the
        attachment would be omitted from the request with a reason naming the model rather
        than the configuration.
        """
        if value is None:
            return None
        normalized = [normalize_media_type(item) for item in value]
        unknown = sorted({item for item in normalized if item not in SUPPORTED_MEDIA_TYPES})
        if unknown:
            known = ", ".join(sorted(SUPPORTED_MEDIA_TYPES))
            raise ValueError(f"unsupported input media {', '.join(unknown)} (supported: {known})")
        return list(dict.fromkeys(normalized))


class RouterProviderConfig(BaseModel):
    """One provider entry as it appears in workspace configuration.

    `api_key_env` names the environment variable to read; there is no field that holds a
    key, and one written in by hand is refused before anything else is validated
    (Product SS34).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: ProviderKind
    model: str
    base_url: str | None = None
    priority: int = 100
    roles: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    api_key_env: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    capabilities: CapabilityOverrides | None = None
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _refuse_inline_secrets(cls, data: Any) -> Any:
        """Refuse a credential written into the entry, with the fix in the message.

        Runs before field validation, so the researcher is told what is wrong instead of
        reading "extra inputs are not permitted".
        """
        if isinstance(data, Mapping):
            name = data.get("name")
            label = f"provider entry {name!r}" if isinstance(name, str) else "a provider entry"
            refuse_inline_secrets(data, where=label)
        return data


class RouterConfig(BaseModel):
    """A routing table loadable from YAML/JSON via `RouterConfig.model_validate(...)`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    providers: list[RouterProviderConfig] = Field(default_factory=list)


def build_router(
    config: RouterConfig,
    env: Mapping[str, str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    policy: EgressPolicy | None = None,
) -> ModelRouter:
    """Build a router from configuration; API keys come from `env`, never from config.

    `transport` is injected into every adapter, which is how the configuration path is
    exercised offline in tests. `policy` is the workspace's egress policy: pass it and the
    router refuses a provider the project forbids before any request is sent.
    """
    environment: Mapping[str, str] = os.environ if env is None else env
    entries = [
        _build_entry(provider_config, environment, transport)
        for provider_config in config.providers
        if provider_config.enabled
    ]
    return ModelRouter(entries, policy=policy)


def _build_entry(
    provider_config: RouterProviderConfig,
    env: Mapping[str, str],
    transport: httpx.BaseTransport | None,
) -> ProviderEntry:
    base_url = entry_base_url(provider_config)
    capabilities = entry_capabilities(provider_config)
    api_key = env.get(provider_config.api_key_env) if provider_config.api_key_env else None
    kwargs: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
        "transport": transport,
        "capabilities": capabilities,
        "env": env,
    }
    if provider_config.timeout_seconds is not None:
        kwargs["timeout"] = provider_config.timeout_seconds

    provider: ModelProvider
    if provider_config.kind == "openai":
        provider = OpenAIProvider(provider_config.model, **kwargs)
    elif provider_config.kind == "anthropic":
        provider = AnthropicProvider(provider_config.model, **kwargs)
    else:
        provider = LocalOpenAICompatibleProvider(provider_config.model, **kwargs)

    return ProviderEntry(
        provider=provider,
        model=provider_config.model,
        priority=provider_config.priority,
        roles=set(provider_config.roles) if provider_config.roles is not None else None,
        tags={provider_config.name, *provider_config.tags},
    )


def entry_base_url(provider_config: RouterProviderConfig) -> str:
    """The endpoint an entry talks to: its own `base_url`, else the adapter default."""
    return provider_config.base_url or _DEFAULT_BASE_URLS[provider_config.kind]


def entry_capabilities(provider_config: RouterProviderConfig) -> ProviderCapabilities:
    """Declared capabilities (and egress) of one configured entry, without building it.

    Lets the egress report state what an entry would send without opening a client or
    resolving a credential.
    """
    return _merge_capabilities(
        _default_capabilities(provider_config.kind, entry_base_url(provider_config)),
        provider_config.capabilities,
    )


def _default_capabilities(kind: ProviderKind, base_url: str) -> ProviderCapabilities:
    if kind == "openai":
        return default_openai_capabilities(base_url)
    if kind == "anthropic":
        return default_anthropic_capabilities(base_url)
    return default_local_capabilities(base_url)


def _merge_capabilities(
    defaults: ProviderCapabilities, overrides: CapabilityOverrides | None
) -> ProviderCapabilities:
    """Apply a workspace's overrides to an adapter's defaults, re-validating the result.

    Re-validated rather than copied: `vision` and `input_media` are two spellings of one
    fact, and `model_copy` skips the validator that keeps them agreeing -- which is how a
    workspace could once switch vision on and get a sighted model accepting no media.
    """
    if overrides is None:
        return defaults
    update: dict[str, Any] = {}
    if overrides.structured_output is not None:
        update["structured_output"] = overrides.structured_output
    if overrides.max_context_tokens is not None:
        update["max_context_tokens"] = overrides.max_context_tokens
    if overrides.reasoning_levels is not None:
        update["reasoning_levels"] = set(overrides.reasoning_levels)
    update.update(_merged_media(defaults, overrides))
    if not update:
        return defaults
    return ProviderCapabilities.model_validate({**defaults.model_dump(), **update})


def _merged_media(defaults: ProviderCapabilities, overrides: CapabilityOverrides) -> dict[str, Any]:
    """`vision` and `input_media` after the overrides, always stated together.

    Stating both leaves them as written; stating only the media list derives `vision` from
    it; stating only `vision` adds or removes the image types and leaves documents alone.
    """
    if overrides.input_media is not None and overrides.vision is not None:
        return {"input_media": frozenset(overrides.input_media), "vision": overrides.vision}
    if overrides.input_media is not None:
        media = frozenset(overrides.input_media)
        return {"input_media": media, "vision": bool(media & IMAGE_MEDIA_TYPES)}
    if overrides.vision is not None:
        media = (
            defaults.input_media | IMAGE_MEDIA_TYPES
            if overrides.vision
            else defaults.input_media - IMAGE_MEDIA_TYPES
        )
        return {"input_media": frozenset(media), "vision": overrides.vision}
    return {}

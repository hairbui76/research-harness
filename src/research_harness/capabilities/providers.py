"""`provider.list`: the model catalog a client offers a selector from (plan v1.1 SS0.4).

One read, and it exists so that no client has to know a provider rule. A model selector
needs four different facts about every configured entry — what it is called, what it can
take, how far a message travels to reach it, and whether it can be called at all today —
and each of them lives somewhere else: the `providers:` table of `research.yaml`, the
adapter's declared `ProviderCapabilities`, the project's egress policy, and the process
environment. Recomputing that in the Web client, the VS Code extension, and an agent host
would be three chances to disagree about what is private.

Two properties are deliberate:

* **No network, no credential.** The catalog is built the way `egress_report` is built:
  from the adapters' own capability factories and the *names* of the environment variables
  a key would come from. `available` is a boolean and `unavailable_reason` is a sentence;
  no field of this module can hold a key (Product 34).
* **`default` is the router's answer, not a preference.** It marks the entry
  `ModelRouter.select` would return for an unconstrained call — the first the policy allows,
  in priority order — so a client that shows a default shows the one that would actually be
  used, including when it is missing its key.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilitySpec
from research_harness.domain.conversation import EgressClass
from research_harness.privacy.egress import EgressEntry, egress_report
from research_harness.privacy.policy import is_local_endpoint
from research_harness.providers.models.base import ProviderCapabilities
from research_harness.providers.models.router import (
    RouterConfig,
    RouterProviderConfig,
    entry_capabilities,
)

__all__ = [
    "PROVIDER_CAPABILITIES",
    "PROVIDER_CAPABILITY_HANDLERS",
    "ListProvidersRequest",
    "ProviderCatalog",
    "ProviderModelView",
    "list_providers",
    "provider_specs",
]

#: Every capability this module registers (v1.1 plan SS0.4).
PROVIDER_CAPABILITIES: tuple[str, ...] = ("provider.list",)


class ListProvidersRequest(CapabilityRequest):
    """`provider.list`: every routable model in this project. Takes nothing."""


class ProviderModelView(BaseModel):
    """One configured model, as a selector renders it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    """What a caller passes as `model` to `session.send` or `--provider` on the CLI: the
    entry's name in `research.yaml`."""

    label: str
    """`<entry>/<served model>` — the same label routing diagnostics and
    `attachment.check_send` print, so one string identifies an entry everywhere."""

    provider: str
    """The adapter this entry is served by, as `kind:` names it in `research.yaml`."""

    egress_class: EgressClass
    """How far a message travels to reach it: `local` stays on this workstation."""

    input_media: tuple[str, ...] = ()
    """Media types it accepts as input, sorted; empty means text only."""

    context_tokens: int
    """The declared context window, in tokens: the ceiling a `ContextPack` is budgeted to."""

    vision: bool
    available: bool
    """Whether it could be called now: allowed by the policy, and either local or holding
    a credential. Never determined by contacting anything."""

    unavailable_reason: str | None = None
    default: bool = False
    """True for the entry the router would select for an unconstrained call."""


class ProviderCatalog(BaseModel):
    """Every routable model in this project, best priority first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int = 0
    models: tuple[ProviderModelView, ...] = ()


def list_providers(ctx: CapabilityContext, request: ListProvidersRequest) -> ProviderCatalog:
    """`provider.list`: the model catalog, derived from configuration and the egress report.

    Disabled entries are left out: they are not routed, so a selector that offered one
    would offer a model that cannot answer.
    """
    del request
    environment: Mapping[str, str] = os.environ
    config = RouterConfig.model_validate({"providers": list(ctx.repo.config.providers)})
    enabled = [entry for entry in config.providers if entry.enabled]
    disclosed = {
        (row.provider, row.model): row
        for row in egress_report(ctx.repo, environment).of_kind("model")
    }
    # Priority order, ties by declaration order: exactly how `ModelRouter.select` reads the
    # same table, so the first policy-allowed row below is the entry it would return.
    ordered = sorted(enumerate(enabled), key=lambda item: (item[1].priority, item[0]))
    rows = [(entry, disclosed.get((entry.name, entry.model))) for _, entry in ordered]
    routed = next(
        (index for index, (_, row) in enumerate(rows) if row is None or row.allowed_by_policy),
        None,
    )
    models = [
        _model_view(entry, entry_capabilities(entry), row, default=index == routed)
        for index, (entry, row) in enumerate(rows)
    ]
    return ProviderCatalog(count=len(models), models=tuple(models))


def _model_view(
    entry: RouterProviderConfig,
    capabilities: ProviderCapabilities,
    disclosure: EgressEntry | None,
    *,
    default: bool,
) -> ProviderModelView:
    """One catalog row: what it is, what it takes, and whether it can be called."""
    host = capabilities.egress.endpoint_host
    local = is_local_endpoint(host)
    available, reason = _availability(disclosure, local=local)
    return ProviderModelView(
        id=entry.name,
        label=f"{entry.name}/{entry.model}",
        provider=entry.kind,
        egress_class=EgressClass.LOCAL if local else EgressClass.EXTERNAL,
        input_media=tuple(sorted(capabilities.input_media)),
        context_tokens=capabilities.max_context_tokens,
        vision=capabilities.vision,
        available=available,
        unavailable_reason=reason,
        default=default,
    )


def _availability(disclosure: EgressEntry | None, *, local: bool) -> tuple[bool, str | None]:
    """Whether this entry could be called, and the sentence that says why not.

    The policy is asked first, because a refused provider is not "missing a key" — it is
    one this project has decided not to talk to (Product 34). A local endpoint needs no
    credential; whether the server is actually running is not asked, because asking would
    be network activity in a read that promises none.
    """
    if disclosure is None:  # pragma: no cover - the report covers every enabled entry
        return (True, None) if local else (False, "no egress disclosure for this entry")
    if not disclosure.allowed_by_policy:
        return False, f"refused by the privacy policy: {disclosure.reason}"
    if local or disclosure.key_present:
        return True, None
    key = disclosure.key_env or "the provider's API key variable"
    return False, f"no credential: set {key} in the environment"


PROVIDER_CAPABILITY_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], Any]] = (
    MappingProxyType({"provider.list": list_providers})
)


def provider_specs() -> list[CapabilitySpec]:
    """`provider.list`, named and permissioned. A read a host may make."""
    return [
        CapabilitySpec(
            name="provider.list",
            summary="Every configured model, with what it accepts and whether it is available.",
            permission=Permission.READ,
            scientific_semantics=(
                "reads configuration and the project's egress disclosure; contacts nothing, "
                "reveals no credential, and changes no state"
            ),
            request_model=ListProvidersRequest,
            response_model=ProviderCatalog,
            handler=list_providers,
        )
    ]

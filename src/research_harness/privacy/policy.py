"""The project's egress policy: what may leave this workstation, and what may not.

Product SS34 makes privacy a default property of a personal research workstation. The
mechanics are split in two so the rule can be enforced everywhere without dragging the
adapters into the workspace:

* `EgressPolicy` is a plain value persisted in `research.yaml` under `privacy:`. Every
  field defaults to today's behaviour, so a workspace written before this section
  existed opens unchanged and gains the policy with its defaults.
* `check_egress` compares one provider's `EgressDeclaration` with that policy and
  returns a verdict *and its reasons*; `enforce_egress` turns a denial into
  `EgressDeniedError`. Neither performs I/O, so the check is cheap enough to run before
  every call and testable without a network.

This module deliberately imports nothing from `providers/` or `workspace/` at runtime:
both of them import *it* (`WorkspaceConfig.privacy`, `ModelRouter(policy=...)`), and the
layering in `docs/architecture/conventions.md` keeps `workspace/` free of `providers/`.
The two type-only imports below are erased at runtime by
`from __future__ import annotations`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_harness.domain.errors import ProviderError

if TYPE_CHECKING:  # pragma: no cover - imports for typing only; see the module docstring
    from research_harness.providers.models.base import EgressDeclaration
    from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "LOOPBACK_HOSTS",
    "SECRET_CONFIG_KEYS",
    "EgressCheck",
    "EgressDeniedError",
    "EgressKind",
    "EgressPolicy",
    "check_egress",
    "denial",
    "enforce_egress",
    "is_local_endpoint",
    "load_policy",
    "refuse_inline_secrets",
    "secret_keys_in",
]

EgressKind = Literal["model", "embedding", "search"]
"""What a provider is used for. Model and embedding traffic carries research content;
search traffic carries queries and identifiers to a discovery index."""

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})
"""Hosts that keep traffic on the workstation. Duplicated from the adapters on purpose:
the policy must be able to judge an endpoint without importing any of them."""

SECRET_CONFIG_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "bearer_token",
        "key",
        "password",
        "secret",
        "token",
    }
)
"""Keys a provider entry in `research.yaml` may never carry. Product SS34: credentials live
in environment variables or the OS keychain, never in a canonical workspace file — which is
committed to Git and read by every transport."""


def secret_keys_in(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """The credential-looking keys of one configuration entry, sorted."""
    return tuple(
        sorted(
            key
            for key in entry
            if isinstance(key, str) and key.strip().lower() in SECRET_CONFIG_KEYS
        )
    )


def refuse_inline_secrets(entry: Mapping[str, Any], *, where: str) -> None:
    """Raise `ValueError` naming any credential written into configuration.

    A `ValueError` so Pydantic reports it as an ordinary validation error wherever provider
    configuration is validated, with a message that says what to do instead.
    """
    found = secret_keys_in(entry)
    if not found:
        return
    listed = ", ".join(found)
    raise ValueError(
        f"{where} must not contain {listed}: API keys are read from environment variables "
        "or the OS keychain, never from research.yaml (Product SS34). Name the variable "
        "with `api_key_env: <VARIABLE>` and export the key in your shell instead."
    )


def is_local_endpoint(host: str) -> bool:
    """True when reaching ``host`` opens no connection off this workstation.

    Covers loopback addresses, mDNS `.local` names, and the parenthesised markers an
    in-process provider uses instead of a host (`(in-process)`). A provider that is local
    by this test is always allowed: there is no egress to have a policy about.
    """
    cleaned = host.strip().lower()
    if not cleaned or cleaned.startswith("("):
        return True
    if cleaned in LOOPBACK_HOSTS or cleaned.endswith(".local"):
        return True
    return cleaned.startswith("127.")


class EgressPolicy(BaseModel):
    """Per-project egress rules, persisted in `research.yaml` under `privacy:`.

    Defaults reproduce the behaviour of a workspace that has never heard of this section,
    so adding the field migrates nothing. Tightening a field is the researcher's explicit
    act (`research privacy set`), and it applies to every provider the workspace can
    reach, not to one call site.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_models: Literal["allowed", "disabled"] = "allowed"
    """`disabled` refuses every non-local model and embedding provider: the sensitive-corpus
    switch of Product SS34."""

    allowed_hosts: tuple[str, ...] = ()
    """Endpoint hosts this project may talk to. Empty means "any host a provider declares";
    a non-empty list refuses every host outside it, local endpoints excepted."""

    allow_source_text: bool = True
    """When false, a provider whose declaration says it sends source text is refused, even
    if its host is allowed."""

    allow_identifiers: bool = True
    """When false, a provider that sends harness object IDs or external identifiers with
    the request is refused."""

    search_providers: Literal["allowed", "disabled"] = "allowed"
    """`disabled` refuses external discovery: no query leaves the workstation."""

    trace_retention_days: int | None = Field(default=30, ge=0)
    """How long `.research/traces/` may keep a trace; `null` means "keep until purged"."""

    redact_traces: bool = False
    """When true, source text is hashed out of a trace as it is written (Product SS19.3)."""

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _normalize_hosts(cls, value: object) -> object:
        """Hosts compare case-insensitively; blanks are dropped rather than matched."""
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list | tuple):
            return value
        return tuple(
            item.strip().lower() for item in value if isinstance(item, str) and item.strip()
        )

    @property
    def blocks_external_models(self) -> bool:
        """Whether external model/embedding egress is switched off for this project."""
        return self.external_models == "disabled"

    @property
    def blocks_search(self) -> bool:
        """Whether external discovery is switched off for this project."""
        return self.search_providers == "disabled"


@dataclass(frozen=True, slots=True)
class EgressCheck:
    """The verdict for one provider, plus why it came out that way.

    `reasons` is human-readable and `policy_fields` names the settings that produced them,
    so a caller can both print the refusal and tell the researcher which knob to turn.
    """

    allowed: bool
    reasons: tuple[str, ...] = ()
    policy_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reason(self) -> str:
        """One line joining every reason; empty when the call is allowed."""
        return "; ".join(self.reasons)


class EgressDeniedError(ProviderError):
    """A provider call was refused by the project's privacy policy, before it was made.

    Deliberately a `research_harness.domain.errors.ProviderError` (and therefore a
    `ResearchHarnessError` the CLI maps to exit code 1) rather than a
    `providers.models.base.ProviderError`: a policy refusal is not a provider failure, and
    must not be mistaken for one by retry or failover logic.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        endpoint_host: str,
        policy_fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.endpoint_host = endpoint_host
        self.policy_fields = policy_fields


def check_egress(
    policy: EgressPolicy, egress: EgressDeclaration, *, kind: EgressKind
) -> EgressCheck:
    """Judge one provider's declared egress against ``policy``; performs no I/O.

    A local endpoint is always allowed — there is nothing to disclose. Everything else is
    measured against each rule in turn and every failing rule is reported, so a researcher
    who tightened several settings sees all of them rather than the first.
    """
    host = egress.endpoint_host
    if is_local_endpoint(host):
        return EgressCheck(allowed=True)

    reasons: list[str] = []
    fields: list[str] = []

    if kind in ("model", "embedding") and policy.blocks_external_models:
        reasons.append(
            f"external model egress is disabled for this project, and {host} is not local"
        )
        fields.append("external_models")
    if kind == "search" and policy.blocks_search:
        reasons.append(f"external discovery is disabled for this project, and {host} is not local")
        fields.append("search_providers")
    if policy.allowed_hosts and host.strip().lower() not in policy.allowed_hosts:
        allowed = ", ".join(policy.allowed_hosts)
        reasons.append(f"{host} is not in the allowed hosts ({allowed})")
        fields.append("allowed_hosts")
    if egress.sends_source_text and not policy.allow_source_text:
        reasons.append(f"it sends source text to {host} and source-text egress is not allowed")
        fields.append("allow_source_text")
    if egress.sends_identifiers and not policy.allow_identifiers:
        reasons.append(
            f"it sends object identifiers to {host} and identifier egress is not allowed"
        )
        fields.append("allow_identifiers")

    return EgressCheck(allowed=not reasons, reasons=tuple(reasons), policy_fields=tuple(fields))


def enforce_egress(
    policy: EgressPolicy,
    egress: EgressDeclaration,
    *,
    provider: str,
    kind: EgressKind,
) -> None:
    """Raise `EgressDeniedError` when ``policy`` refuses this provider; else return.

    Call this *before* building a request, never after: the point of the switch is that no
    byte of the corpus reaches the wire.
    """
    check = check_egress(policy, egress, kind=kind)
    if check.allowed:
        return
    raise denial(provider, egress, check, kind=kind)


def denial(
    provider: str, egress: EgressDeclaration, check: EgressCheck, *, kind: EgressKind
) -> EgressDeniedError:
    """Build the refusal for a failed check, naming provider, host, and policy field."""
    fields = ", ".join(check.policy_fields) or "privacy"
    return EgressDeniedError(
        f"privacy policy refuses the {kind} provider {provider!r} at {egress.endpoint_host}: "
        f"{check.reason} (set privacy.{fields} in research.yaml, or run "
        "`research privacy set`, to change this)",
        provider=provider,
        endpoint_host=egress.endpoint_host,
        policy_fields=check.policy_fields,
    )


def load_policy(repo: WorkspaceRepository) -> EgressPolicy:
    """The workspace's privacy policy, defaulted when `research.yaml` has no `privacy:`."""
    return repo.config.privacy

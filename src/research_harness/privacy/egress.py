"""Enforcement and disclosure: what would leave this workstation, and what is allowed.

Two jobs, both from Product SS34:

* **Enforcement.** `policy_enforced_router` attaches the project's policy to a model
  router, `check_embedding_egress` guards an embedding backend before an index is built,
  and `providers.search.build_search_registry(policy=...)` guards discovery. Every one of
  them refuses *before* a request exists, so a refused provider is never contacted.
* **Disclosure.** `egress_report` is the "visible network activity policy": one row per
  provider the workspace could reach, saying which host it talks to, whether source text
  or identifiers go with the request, whether the policy allows it, and whether a
  credential is present. It reports the *name* of the environment variable and a boolean —
  never a key, and never a value read from `research.yaml`, because a key may not live
  there at all.

Building the report performs no network I/O: every declaration comes from the adapters'
own capability factories.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from research_harness.privacy.policy import (
    EgressKind,
    EgressPolicy,
    check_egress,
    denial,
    load_policy,
)
from research_harness.providers.models.anthropic_provider import (
    API_KEY_ENV_VAR as ANTHROPIC_API_KEY_ENV_VAR,
)
from research_harness.providers.models.base import EgressDeclaration
from research_harness.providers.models.embeddings import (
    LOCAL_API_KEY_ENV_VAR as LOCAL_EMBEDDING_API_KEY_ENV_VAR,
)
from research_harness.providers.models.embeddings import (
    LOCAL_DEFAULT_BASE_URL,
    OPENAI_DEFAULT_BASE_URL,
    OPENAI_DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    HashingEmbeddingProvider,
    local_embedding_egress,
    openai_embedding_egress,
)
from research_harness.providers.models.embeddings import (
    OPENAI_API_KEY_ENV_VAR as OPENAI_EMBEDDING_API_KEY_ENV_VAR,
)
from research_harness.providers.models.local_provider import (
    API_KEY_ENV_VAR as LOCAL_API_KEY_ENV_VAR,
)
from research_harness.providers.models.openai_provider import (
    API_KEY_ENV_VAR as OPENAI_API_KEY_ENV_VAR,
)
from research_harness.providers.models.router import (
    ModelRouter,
    ProviderKind,
    RouterConfig,
    RouterProviderConfig,
    entry_capabilities,
)
from research_harness.providers.search import (
    SEARCH_SOURCES,
    SEMANTIC_SCHOLAR,
    SEMANTIC_SCHOLAR_API_KEY_ENV_VAR,
    search_source_capabilities,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; `workspace/` must not be imported here
    from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "EMBEDDING_BACKENDS",
    "MODEL_KEY_ENV_VARS",
    "SEARCH_KEY_ENV_VARS",
    "EgressEntry",
    "EgressReport",
    "check_embedding_egress",
    "egress_report",
    "policy_enforced_router",
]

MODEL_KEY_ENV_VARS: Mapping[ProviderKind, str] = {
    "openai": OPENAI_API_KEY_ENV_VAR,
    "anthropic": ANTHROPIC_API_KEY_ENV_VAR,
    "local_openai_compatible": LOCAL_API_KEY_ENV_VAR,
}
"""The environment variable each model adapter reads when an entry names none. Documented
here because Product SS34 requires the *names* to be discoverable while the values stay out
of every file the harness writes."""

SEARCH_KEY_ENV_VARS: Mapping[str, str] = {SEMANTIC_SCHOLAR: SEMANTIC_SCHOLAR_API_KEY_ENV_VAR}
"""Discovery sources that read a credential; the others are keyless polite-pool APIs."""

_HASHING = HashingEmbeddingProvider()

EMBEDDING_BACKENDS: tuple[tuple[str, str, EgressDeclaration, str | None], ...] = (
    (
        "hashing",
        _HASHING.model,
        _HASHING.egress,
        None,
    ),
    (
        "openai",
        OPENAI_DEFAULT_EMBEDDING_MODEL,
        openai_embedding_egress(OPENAI_DEFAULT_BASE_URL),
        OPENAI_EMBEDDING_API_KEY_ENV_VAR,
    ),
    (
        "local",
        "(the served model)",
        local_embedding_egress(LOCAL_DEFAULT_BASE_URL),
        LOCAL_EMBEDDING_API_KEY_ENV_VAR,
    ),
)
"""The embedding backends `research index build --embedder` can select, with the egress
each one declares at its default endpoint. Listed rather than instantiated: reporting what
a backend would send must not open a client or read a key."""


class EgressEntry(BaseModel):
    """One provider on the disclosure surface: what it sends, and whether it may.

    `key_present` is a boolean by construction. No field of this model can hold a
    credential, so the report is safe to print, pipe, and paste into an issue.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    kind: EgressKind
    model: str | None = None
    endpoint_host: str
    sends_source_text: bool
    sends_identifiers: bool
    allowed_by_policy: bool
    reason: str = ""
    policy_fields: tuple[str, ...] = ()
    key_env: str | None = None
    key_present: bool = False
    description: str = ""

    @property
    def label(self) -> str:
        """`provider/model`, or just the provider when it has no model of its own."""
        return f"{self.provider}/{self.model}" if self.model else self.provider


class EgressReport(BaseModel):
    """Every provider this workspace could reach, judged against its policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[EgressEntry, ...] = ()
    policy: EgressPolicy = EgressPolicy()

    @property
    def denied(self) -> tuple[EgressEntry, ...]:
        """Providers the policy currently refuses."""
        return tuple(entry for entry in self.entries if not entry.allowed_by_policy)

    @property
    def external(self) -> tuple[EgressEntry, ...]:
        """Providers that would send something off this workstation if used."""
        return tuple(
            entry for entry in self.entries if entry.sends_source_text or entry.sends_identifiers
        )

    def of_kind(self, kind: EgressKind) -> tuple[EgressEntry, ...]:
        return tuple(entry for entry in self.entries if entry.kind == kind)


def egress_report(repo: WorkspaceRepository, env: Mapping[str, str] | None = None) -> EgressReport:
    """The workspace's network-activity disclosure, built without touching the network.

    Model entries come from `providers:` in `research.yaml` (disabled entries are left out:
    they are not routed and therefore send nothing); embedding and discovery entries are
    every backend the CLI can select, because those are chosen per command rather than
    configured.
    """
    environment: Mapping[str, str] = os.environ if env is None else env
    policy = load_policy(repo)
    config = RouterConfig.model_validate({"providers": list(repo.config.providers)})
    entries: list[EgressEntry] = [
        _model_entry(provider_config, policy, environment)
        for provider_config in config.providers
        if provider_config.enabled
    ]
    entries.extend(_embedding_entries(policy, environment))
    entries.extend(_search_entries(policy, environment))
    return EgressReport(entries=tuple(entries), policy=policy)


def _model_entry(
    provider_config: RouterProviderConfig, policy: EgressPolicy, env: Mapping[str, str]
) -> EgressEntry:
    egress = entry_capabilities(provider_config).egress
    # `.get`, not `[]`: a `local_cli` entry reads no credential of its own -- it borrows the
    # CLI's existing login -- so it has no row in the table and discloses `key_env=None`.
    key_env = provider_config.api_key_env or MODEL_KEY_ENV_VARS.get(provider_config.kind)
    return _entry(
        provider=provider_config.name,
        kind="model",
        model=provider_config.model,
        egress=egress,
        policy=policy,
        key_env=key_env,
        env=env,
    )


def _embedding_entries(policy: EgressPolicy, env: Mapping[str, str]) -> list[EgressEntry]:
    return [
        _entry(
            provider=name,
            kind="embedding",
            model=model,
            egress=egress,
            policy=policy,
            key_env=key_env,
            env=env,
        )
        for name, model, egress, key_env in EMBEDDING_BACKENDS
    ]


def _search_entries(policy: EgressPolicy, env: Mapping[str, str]) -> list[EgressEntry]:
    return [
        _entry(
            provider=source,
            kind="search",
            model=None,
            egress=search_source_capabilities(source).egress,
            policy=policy,
            key_env=SEARCH_KEY_ENV_VARS.get(source),
            env=env,
        )
        for source in SEARCH_SOURCES
    ]


def _entry(
    *,
    provider: str,
    kind: EgressKind,
    model: str | None,
    egress: EgressDeclaration,
    policy: EgressPolicy,
    key_env: str | None,
    env: Mapping[str, str],
) -> EgressEntry:
    check = check_egress(policy, egress, kind=kind)
    return EgressEntry(
        provider=provider,
        kind=kind,
        model=model,
        endpoint_host=egress.endpoint_host,
        sends_source_text=egress.sends_source_text,
        sends_identifiers=egress.sends_identifiers,
        allowed_by_policy=check.allowed,
        reason=check.reason,
        policy_fields=check.policy_fields,
        key_env=key_env,
        key_present=bool(key_env and env.get(key_env, "").strip()),
        description=egress.description,
    )


# -- enforcement -------------------------------------------------------------


def policy_enforced_router(router: ModelRouter, policy: EgressPolicy | None) -> ModelRouter:
    """The same routing table, refusing whatever ``policy`` refuses.

    Use it when a caller narrows an existing router (for example to one `--provider`) and
    must not drop the policy on the way.
    """
    return router.with_policy(policy)


def check_embedding_egress(
    policy: EgressPolicy, provider: EmbeddingProvider, *, name: str | None = None
) -> None:
    """Refuse an embedding backend the project's policy forbids, before any text is sent.

    Building a vector index ships the whole corpus to whoever computes the vectors, so this
    belongs at the top of every index build or query that uses a hosted embedder:
    `cli/commands/search.py::_embedder` is the single place where one is constructed.
    """
    egress = provider.egress
    check = check_egress(policy, egress, kind="embedding")
    if check.allowed:
        return
    label = name or f"{provider.name}/{provider.model}"
    raise denial(label, egress, check, kind="embedding")


def denied_sources(policy: EgressPolicy, sources: Sequence[str]) -> tuple[str, ...]:
    """Discovery sources ``policy`` refuses, in the order given."""
    return tuple(
        source
        for source in sources
        if not check_egress(
            policy, search_source_capabilities(source).egress, kind="search"
        ).allowed
    )

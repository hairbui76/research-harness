"""What a session's `defaults.model` means for routing (binding spec §7, §9, §15).

The domain stores two opaque labels; this module is the one place that reads them. A
provider of `local_cli:<runtime>` is a runtime binding, `entry` is an entry binding, and any
other provider is a record written before bindings existed, when `create` stored the
adapter's own name in both fields: it is an entry binding on its `model` value.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_harness.domain.conversation import (
    RUNTIME_PROVIDER_PREFIX,
    ModelIdentity,
    SessionDefaults,
)

ENTRY_PROVIDER = "entry"
SESSION_LABEL_PREFIX = "session:"
PROJECT_DEFAULT_WORDS = "project default"


@dataclass(frozen=True, slots=True)
class EntryBinding:
    """The session sends through one named `research.yaml` entry."""

    name: str

    @property
    def words(self) -> str:
        return f"entry {self.name}"


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    """The session sends through a runtime and model with no `research.yaml` entry."""

    runtime: str
    model: str
    reasoning: str | None

    @property
    def label(self) -> str:
        """The in-memory entry's name, and the transcript's provider label."""
        return f"{SESSION_LABEL_PREFIX}{self.runtime}"

    @property
    def words(self) -> str:
        base = f"{self.label}/{self.model}"
        return base if self.reasoning is None else f"{base} (reasoning {self.reasoning})"


Binding = EntryBinding | RuntimeBinding


def binding_of(defaults: SessionDefaults) -> Binding | None:
    identity = defaults.model
    if identity is None:
        return None
    if identity.provider.startswith(RUNTIME_PROVIDER_PREFIX):
        return RuntimeBinding(
            runtime=identity.provider[len(RUNTIME_PROVIDER_PREFIX) :],
            model=identity.model,
            reasoning=defaults.reasoning,
        )
    return EntryBinding(name=identity.model)


def binding_words(defaults: SessionDefaults) -> str:
    """The fixed wording every surface prints for a session's binding (plan ruling 4)."""
    binding = binding_of(defaults)
    return PROJECT_DEFAULT_WORDS if binding is None else binding.words


def runtime_identity(runtime: str, model: str) -> ModelIdentity:
    return ModelIdentity(provider=f"{RUNTIME_PROVIDER_PREFIX}{runtime}", model=model)


def entry_identity(name: str) -> ModelIdentity:
    return ModelIdentity(provider=ENTRY_PROVIDER, model=name)

"""The context every capability handler runs in: workspace, actor, clock, invalidation.

The context carries no scientific policy of its own. It answers three questions a handler
must not answer twice: which workspace, on whose authority, and where the resulting stale
set goes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from research_harness.capabilities.invalidation import (
    DependencyInvalidation,
    InvalidationHook,
)
from research_harness.domain.base import Provenance, utc_now
from research_harness.domain.transitions import HUMAN_ACTOR, is_human_actor
from research_harness.projection.dependencies import StaleSet
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "SYSTEM_ACTOR",
    "CapabilityContext",
    "actor_provenance",
    "open_context",
]

SYSTEM_ACTOR = "system"

#: Stateless, so one instance serves every context that does not supply its own hook.
_DEFAULT_INVALIDATION = DependencyInvalidation()


def actor_provenance(actor: str, **fields: Any) -> Provenance:
    """Provenance for ``actor``: human, deterministic system action, or model proposal.

    The actor string is the only signal (`Product` 7.3): ``human``/``human:<name>`` is the
    researcher, ``system``/``system:<name>``/``ingest`` is a deterministic harness action,
    and anything else names a model.
    """
    if is_human_actor(actor):
        return Provenance.human(actor, **fields)
    if actor == SYSTEM_ACTOR or actor.startswith(f"{SYSTEM_ACTOR}:") or actor == "ingest":
        return Provenance.system(actor=actor, **fields)
    return Provenance.model(actor, **fields)


@dataclass(frozen=True, slots=True)
class CapabilityContext:
    """One workspace, one actor, one clock, one invalidation hook."""

    repo: WorkspaceRepository
    actor: str = HUMAN_ACTOR
    clock: Callable[[], datetime] = utc_now
    invalidation: InvalidationHook | None = None

    @property
    def root(self) -> Path:
        """Workspace root."""
        return self.repo.root

    @property
    def is_human(self) -> bool:
        """True when the acting actor is the researcher and may exercise human authority."""
        return is_human_actor(self.actor)

    def now(self) -> datetime:
        """Current time according to this context's clock."""
        return self.clock()

    def provenance(self, **fields: Any) -> Provenance:
        """Provenance for the acting actor."""
        return actor_provenance(self.actor, **fields)

    def invalidate(self, changed_ids: Sequence[str]) -> StaleSet:
        """Stale set implied by ``changed_ids``, via this context's invalidation hook."""
        hook = self.invalidation if self.invalidation is not None else _DEFAULT_INVALIDATION
        return hook.invalidate(self.repo, changed_ids)


def open_context(
    root: Path | str,
    actor: str = HUMAN_ACTOR,
    *,
    clock: Callable[[], datetime] = utc_now,
    invalidation: InvalidationHook | None = None,
    repair: bool = False,
) -> CapabilityContext:
    """Open the workspace at ``root`` and bind it to ``actor``."""
    repo = WorkspaceRepository.open(root, repair=repair)
    return CapabilityContext(repo=repo, actor=actor, clock=clock, invalidation=invalidation)

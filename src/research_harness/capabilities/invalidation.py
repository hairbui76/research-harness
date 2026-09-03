"""Dependency invalidation for a committed mutation (Product 36, 37; ADR-008).

Marking downstream objects stale is a *report*, never a rewrite: nothing here changes a
canonical object, and the projection is only touched when it already exists, because a
mutation must never be the thing that creates regenerable state.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

from sqlalchemy.exc import SQLAlchemyError

from research_harness.domain.base import utc_now
from research_harness.projection.dependencies import (
    DependencyGraph,
    StaleSet,
    mark_changed_many,
    persist_stale_marks,
)
from research_harness.projection.schema import create_engine_for
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "DependencyInvalidation",
    "InvalidationHook",
    "NullInvalidation",
    "canonical_objects",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class InvalidationHook(Protocol):
    """What a capability handler calls once its mutation has committed."""

    def invalidate(self, repo: WorkspaceRepository, changed_ids: Sequence[str]) -> StaleSet:
        """Objects that are now stale because ``changed_ids`` changed."""


class DependencyInvalidation:
    """The default hook: derive the graph from canonical state and mark downstream stale."""

    def invalidate(self, repo: WorkspaceRepository, changed_ids: Sequence[str]) -> StaleSet:
        """Stale set for ``changed_ids``, persisted only if a projection already exists."""
        if not changed_ids:
            return StaleSet()
        graph = DependencyGraph.from_objects(canonical_objects(repo))
        stale = mark_changed_many(graph, [str(value) for value in changed_ids])
        if stale:
            self._persist(repo, stale)
        return stale

    def _persist(self, repo: WorkspaceRepository, stale: StaleSet) -> None:
        """Record the stale set in the projection, if there is one to record it in.

        A missing, empty, or outdated database is not a mutation failure: canonical state is
        authoritative and `research rebuild` reconstructs the marks (ADR-001).
        """
        database = repo.layout.database_file
        if not database.is_file():
            return
        engine = create_engine_for(database)
        try:
            with engine.begin() as connection:
                persist_stale_marks(connection, stale, utc_now())
        except SQLAlchemyError:
            logger.warning(
                "could not record %d stale marks in %s; canonical state is unaffected",
                len(stale),
                database,
                exc_info=True,
            )
        finally:
            engine.dispose()


class NullInvalidation:
    """Records nothing and marks nothing; for tests and for read-only contexts."""

    def invalidate(self, repo: WorkspaceRepository, changed_ids: Sequence[str]) -> StaleSet:
        """Always an empty stale set."""
        del repo, changed_ids
        return StaleSet()


def canonical_objects(repo: WorkspaceRepository) -> Iterator[object]:
    """Every canonical object the dependency graph can derive an edge from."""
    works = repo.list_works()
    yield from works
    for work in works:
        yield from repo.iter_evidence(work.id)
    yield from repo.list_claims()
    yield from repo.list_questions()
    yield from repo.list_decisions()
    yield from repo.list_matrices()
    yield from repo.list_taxonomies()
    yield from repo.list_search_runs()
    yield from repo.iter_anchors()

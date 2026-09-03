"""Explicit workspace schema versioning, and the (currently empty) migration registry.

A workspace states its schema version in `research.yaml`. Opening one written by a *newer*
harness fails closed rather than guessing: a scientific record must never be silently
reinterpreted by a version that does not know its fields. Opening an older workspace runs
the registered migrations in order.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from research_harness.domain.errors import WorkspaceError
from research_harness.workspace.layout import WorkspaceLayout

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MIGRATIONS",
    "MINIMUM_SCHEMA_VERSION",
    "UnsupportedSchemaVersionError",
    "check_schema_version",
    "migrate",
]

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1
MINIMUM_SCHEMA_VERSION = 1

#: `version -> migration` where the callable upgrades a workspace *from* ``version`` to
#: ``version + 1``. Empty at schema version 1. Every entry must be idempotent, must go
#: through a `journal.Transaction` like any other canonical write, and — because rewriting a
#: canonical file changes its digest — must append the events that keep
#: `events.verify_consistency` satisfied, or the migrated workspace will fail closed.
MIGRATIONS: dict[int, Callable[[WorkspaceLayout], None]] = {}


class UnsupportedSchemaVersionError(WorkspaceError):
    """The workspace schema version cannot be read by this build of the harness."""


def check_schema_version(version: int) -> None:
    """Fail closed on a future or unreadably old workspace schema version."""
    if version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"workspace schema version {version} was written by a newer Research Harness; "
            f"this build supports up to version {CURRENT_SCHEMA_VERSION}. "
            "Upgrade the harness rather than editing research.yaml: opening it here could "
            "drop fields this version does not know about."
        )
    if version < MINIMUM_SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"workspace schema version {version} is older than the oldest migratable "
            f"version {MINIMUM_SCHEMA_VERSION}"
        )


def migrate(layout: WorkspaceLayout, version: int) -> int:
    """Run every registered migration from ``version`` up to the current schema version."""
    check_schema_version(version)
    while version < CURRENT_SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise UnsupportedSchemaVersionError(
                f"no migration registered from workspace schema version {version} to "
                f"{version + 1}; refusing to guess"
            )
        logger.info("migrating workspace %s from schema version %d", layout.root, version)
        migration(layout)
        version += 1
    return version

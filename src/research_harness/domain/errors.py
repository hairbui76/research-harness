"""Error hierarchy for the whole harness, rooted in the pure domain layer.

Later layers (workspace, projection, providers, capabilities) raise the subclasses
declared here so that a single ``except ResearchHarnessError`` catches everything the
product raises on purpose.
"""

from __future__ import annotations

__all__ = [
    "AuthorityError",
    "CapabilityError",
    "DomainValidationError",
    "IngestError",
    "ProjectionError",
    "ProviderError",
    "ResearchHarnessError",
    "TransitionError",
    "WorkspaceError",
]


class ResearchHarnessError(Exception):
    """Root of every deliberate harness error."""


class DomainValidationError(ResearchHarnessError, ValueError):
    """A domain invariant was violated.

    It is also a ``ValueError`` so that Pydantic turns it into a normal
    ``ValidationError`` when raised from inside a field or model validator.
    """


class TransitionError(ResearchHarnessError):
    """A requested state transition is not part of the allowed transition table."""


class AuthorityError(ResearchHarnessError):
    """The acting role/actor lacks the authority required for the requested change.

    Raised when a transition is structurally legal but epistemically forbidden, for
    example a model trying to accept an interpretive candidate under strict policy.
    """


class WorkspaceError(ResearchHarnessError):
    """Canonical workspace layout, locking, journaling, or serialization failure."""


class IngestError(ResearchHarnessError):
    """An artifact could not be read or inspected during ingestion.

    Raised instead of letting a third-party reader's own exception escape, so a corrupt or
    non-PDF file is a harness error the caller can catch, with the original chained.
    """


class ProjectionError(ResearchHarnessError):
    """A regenerable projection (SQLite, FTS, vector index) failed or is inconsistent."""


class ProviderError(ResearchHarnessError):
    """A model, search, metadata, or parser provider adapter failed."""


class CapabilityError(ResearchHarnessError):
    """A named capability was invoked incorrectly or is not permitted for the caller."""

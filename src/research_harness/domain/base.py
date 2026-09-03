"""Shared base models, provenance, and scalar constraints for canonical objects.

Canonical objects are frozen: every change produces a new object through
:meth:`TrackedObject.touch`, which re-validates the model and bumps ``updated_at``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from research_harness.domain.enums import ProvenanceSource
from research_harness.domain.ids import ResearchId

__all__ = [
    "SCHEMA_VERSION",
    "CanonicalObject",
    "DomainModel",
    "NonEmptyStr",
    "Provenance",
    "Sha256",
    "TrackedObject",
    "UtcDatetime",
    "YearMonth",
    "utc_now",
]

SCHEMA_VERSION = 1

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
YEAR_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
"""Timezone-aware datetime normalized to UTC."""

Sha256 = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
"""Content hash written as ``sha256:<64 lowercase hex chars>``."""

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]

YearMonth = Annotated[str, StringConstraints(pattern=YEAR_MONTH_PATTERN)]
"""Publication cutoff written as ``YYYY-MM`` (Product 10)."""


def is_sha256(value: str) -> bool:
    """True when ``value`` is a well-formed ``sha256:<hex>`` digest."""
    return re.fullmatch(SHA256_PATTERN, value) is not None


class DomainModel(BaseModel):
    """Frozen, closed value object. Base for every model in the domain layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def touch(self, **updates: Any) -> Self:
        """Return a re-validated copy with ``updates`` applied.

        Frozen objects are never mutated in place. When the model carries ``updated_at``
        it is bumped to now unless the caller passes an explicit value.
        """
        data: dict[str, Any] = {**self.__dict__, **updates}
        if "updated_at" in type(self).model_fields and "updated_at" not in updates:
            data["updated_at"] = utc_now()
        return type(self).model_validate(data)


class Provenance(DomainModel):
    """Who/what produced a record, and under which workflow run.

    ``actor`` is an opaque string (``"human"``, ``"human:alice"``, ``"vendor-a/model-x"``,
    ``"local/model-y"``). The domain never interprets it as a provider vocabulary and
    defines no provider names of its own.
    """

    source: ProvenanceSource
    actor: NonEmptyStr
    workflow: str | None = None
    run_id: str | None = None
    template_version: str | None = None
    note: str | None = None

    @classmethod
    def human(cls, actor: str = "human", **kwargs: Any) -> Provenance:
        """Provenance for a researcher action."""
        return cls(source=ProvenanceSource.HUMAN, actor=actor, **kwargs)

    @classmethod
    def model(cls, actor: str, **kwargs: Any) -> Provenance:
        """Provenance for a model proposal; ``actor`` names the model, not the host."""
        return cls(source=ProvenanceSource.MODEL, actor=actor, **kwargs)

    @classmethod
    def system(cls, actor: str = "system", **kwargs: Any) -> Provenance:
        """Provenance for a deterministic harness action."""
        return cls(source=ProvenanceSource.SYSTEM, actor=actor, **kwargs)


class TrackedObject(DomainModel):
    """A versioned, timestamped, provenance-carrying record without a stable ID.

    Staging and low-authority records (work candidates, notes, parsed documents,
    taxonomies) derive from this. Canonical scientific state derives from
    :class:`CanonicalObject`, which adds the stable ID.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)
    provenance: Provenance


class CanonicalObject(DomainModel):
    """Canonical scientific state: schema version, stable ID, timestamps, provenance.

    Field order matches the canonical file layout so serialized YAML/JSONL starts with
    ``schema_version`` and ``id``.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    id: ResearchId
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)
    provenance: Provenance

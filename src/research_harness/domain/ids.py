"""Typed stable identifiers for canonical research objects (Product 7.2).

Every ID is a ``str`` subclass, so it hashes, sorts, and serializes exactly like the
string written into canonical YAML/JSONL, while still validating its prefix on
construction and inside Pydantic models.

Grammar::

    <PREFIX><4+ digits>            e.g. W0017, E0482, RQ0003
    <PREFIX><4+ digits>-<digits>   e.g. V0017-2, A0017-3   (work-scoped ids only)

The optional ``-<digits>`` suffix exists for ``Version`` and ``Artifact`` ids, whose
number mirrors the owning ``Work`` and whose suffix counts within that work.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, ClassVar, Self

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

from research_harness.domain.errors import DomainValidationError

__all__ = [
    "ID_TYPES",
    "MIN_ID_DIGITS",
    "ArtifactId",
    "BlockId",
    "ClaimId",
    "DecisionId",
    "EvidenceId",
    "InterpretationId",
    "QuestionId",
    "ResearchId",
    "SearchRunId",
    "SynthesisId",
    "VersionId",
    "WorkId",
    "parse_id",
]

MIN_ID_DIGITS = 4


class ResearchId(str):
    """Base class for every stable research identifier.

    Used directly as a Pydantic field type it accepts *any* known prefix and returns the
    concrete subclass (see :func:`parse_id`); subclasses accept only their own prefix.
    """

    __slots__ = ()

    prefix: ClassVar[str] = ""
    scoped: ClassVar[bool] = False
    """True when the id may carry a ``-<digits>`` suffix scoped to the owning Work."""

    _compiled: ClassVar[re.Pattern[str]]
    """The class's own compiled grammar, built once by :meth:`__init_subclass__`.

    Ids are constructed millions of times during a corpus read, and recompiling (even
    through ``re``'s cache) dominated that path; the pattern depends only on ``prefix``
    and ``scoped``, both of which are fixed when the class body ends.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._compiled = re.compile(cls.pattern())

    def __new__(cls, value: str) -> Self:
        if cls is ResearchId:
            raise DomainValidationError("ResearchId is abstract; use parse_id() or a subclass")
        text = str(value)
        if not cls._compiled.fullmatch(text):
            raise DomainValidationError(
                f"{cls.__name__} must match {cls.pattern()!r}, got {text!r}"
            )
        return super().__new__(cls, text)

    # -- grammar -------------------------------------------------------------

    @classmethod
    def pattern(cls) -> str:
        """Regular expression (as a string) this id type accepts."""
        suffix = r"(?:-\d+)?" if cls.scoped else ""
        return rf"^{re.escape(cls.prefix)}\d{{{MIN_ID_DIGITS},}}{suffix}$"

    @classmethod
    def _regex(cls) -> re.Pattern[str]:
        return cls._compiled

    # -- parts ---------------------------------------------------------------

    @property
    def number(self) -> int:
        """The primary sequence number, e.g. ``17`` for ``V0017-2``."""
        return int(self[len(self.prefix) :].split("-")[0])

    @property
    def suffix(self) -> int | None:
        """The work-scoped suffix, e.g. ``2`` for ``V0017-2``; ``None`` when absent."""
        _, _, tail = self.partition("-")
        return int(tail) if tail else None

    # -- allocation ----------------------------------------------------------

    @classmethod
    def make(cls, number: int, suffix: int | None = None) -> Self:
        """Build an id from its numeric parts, zero-padded to the minimum width."""
        if number < 0:
            raise DomainValidationError(f"{cls.__name__} number must be non-negative")
        if suffix is not None and not cls.scoped:
            raise DomainValidationError(f"{cls.__name__} does not accept a scope suffix")
        if suffix is not None and suffix < 0:
            raise DomainValidationError(f"{cls.__name__} suffix must be non-negative")
        text = f"{cls.prefix}{number:0{MIN_ID_DIGITS}d}"
        if suffix is not None:
            text = f"{text}-{suffix}"
        return cls(text)

    @classmethod
    def next(cls, existing: Iterable[str]) -> Self:
        """Next free id after the highest number in ``existing`` (ids of other types ignored)."""
        highest = max((cls(value).number for value in cls._own(existing)), default=0)
        return cls.make(highest + 1)

    @classmethod
    def next_in_scope(cls, number: int, existing: Iterable[str]) -> Self:
        """Next suffixed id inside one work, e.g. ``V0017-3`` after ``V0017-2``.

        An unsuffixed member of the scope counts as suffix ``0``, so the first allocation
        is always ``-1``.
        """
        if not cls.scoped:
            raise DomainValidationError(f"{cls.__name__} is not work-scoped")
        suffixes = [
            (candidate.suffix or 0)
            for candidate in (cls(value) for value in cls._own(existing))
            if candidate.number == number
        ]
        return cls.make(number, max(suffixes, default=0) + 1)

    @classmethod
    def _own(cls, existing: Iterable[str]) -> list[str]:
        pattern = cls._regex()
        return [str(value) for value in existing if pattern.fullmatch(str(value))]

    # -- pydantic ------------------------------------------------------------

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        del source_type, handler
        str_schema = core_schema.str_schema(
            pattern=None if cls is ResearchId else cls.pattern(),
            strip_whitespace=False,
        )
        validator = parse_id if cls is ResearchId else cls
        return core_schema.no_info_after_validator_function(
            validator,
            str_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema(), when_used="always"
            ),
        )


#: `__init_subclass__` cannot fill the base class in, so the abstract grammar is compiled
#: here; `_own` and `_regex` are usable on `ResearchId` itself.
ResearchId._compiled = re.compile(ResearchId.pattern())


class WorkId(ResearchId):
    """`W####` - a scholarly work independent of any file."""

    __slots__ = ()
    prefix = "W"


class VersionId(ResearchId):
    """`V####[-n]` - one revision of a Work (arXiv v1, camera-ready, ...)."""

    __slots__ = ()
    prefix = "V"
    scoped = True


class ArtifactId(ResearchId):
    """`A####[-n]` - one immutable file belonging to a Version."""

    __slots__ = ()
    prefix = "A"
    scoped = True


class BlockId(ResearchId):
    """`B####` - a parsed document block."""

    __slots__ = ()
    prefix = "B"


class EvidenceId(ResearchId):
    """`E####` - a source-anchored evidence object."""

    __slots__ = ()
    prefix = "E"


class InterpretationId(ResearchId):
    """`I####` - a derived reading of one or more Evidence objects."""

    __slots__ = ()
    prefix = "I"


class ClaimId(ResearchId):
    """`C####` - a structured research claim."""

    __slots__ = ()
    prefix = "C"


class QuestionId(ResearchId):
    """`RQ####` - a research question."""

    __slots__ = ()
    prefix = "RQ"


class DecisionId(ResearchId):
    """`D####` - an explicit researcher decision."""

    __slots__ = ()
    prefix = "D"


class SearchRunId(ResearchId):
    """`SR####` - one reproducible discovery operation."""

    __slots__ = ()
    prefix = "SR"


class SynthesisId(ResearchId):
    """`S####` - a synthesis/matrix object."""

    __slots__ = ()
    prefix = "S"


#: Longest prefix first so that ``SR`` wins over ``S`` and ``RQ`` over nothing.
ID_TYPES: tuple[type[ResearchId], ...] = (
    ArtifactId,
    BlockId,
    ClaimId,
    DecisionId,
    EvidenceId,
    InterpretationId,
    QuestionId,
    SearchRunId,
    SynthesisId,
    VersionId,
    WorkId,
)

_BY_PREFIX_LENGTH: tuple[type[ResearchId], ...] = tuple(
    sorted(ID_TYPES, key=lambda id_type: len(id_type.prefix), reverse=True)
)


def parse_id(value: str) -> ResearchId:
    """Return the concrete id type for ``value``, dispatching on its prefix."""
    text = str(value)
    for id_type in _BY_PREFIX_LENGTH:
        if text.startswith(id_type.prefix):
            return id_type(text)
    raise DomainValidationError(f"unknown research id prefix: {text!r}")

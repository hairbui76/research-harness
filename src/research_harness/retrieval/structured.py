"""Structured retrieval over the SQLite projection: the high rungs of the ladder.

This is the part of retrieval that answers a question by *looking it up* rather than by
scoring similarity. Product SS15.3 puts accepted Evidence and Claims first, then accepted
structured paper state, and only then the parsed corpus, so a query like "which papers use
CICIDS2017?" must be answerable as a join over accepted objects before any index is
consulted (ADR-006, Product SS43).

Everything here reads the deletable projection through SQLAlchemy Core selects — no string
SQL, no ORM — and writes nothing. A row is only ever a pointer back at a canonical object:
:class:`StructuredHit` carries the object id, where it sits in its document, and which rung
of the authority ladder it came from, and :func:`resolve_source` turns a reference back
into the exact page, block, character range, and geometry it was accepted from
(`retrieval.resolve_source`).

Section filters deliberately do *not* match the projected section path as a raw prefix:
publishers number their headings ("3.1 Dataset") and researchers do not ("Dataset"), so
:func:`section_matches` compares normalized heading names and lets a filter name any
contiguous run of the path.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, ColumnElement, Table, select
from sqlalchemy.engine import Engine

from research_harness.domain.enums import EvidenceStatus, StaleState
from research_harness.domain.errors import ProjectionError
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId
from research_harness.projection.schema import (
    BLOCKS,
    CLAIMS,
    DECISIONS,
    EVIDENCE,
    MATRIX_CELLS,
    QUESTIONS,
    WORKS,
)

__all__ = [
    "AUTHORITY_RUNGS",
    "DEFAULT_LIMIT",
    "MAX_SCAN",
    "SCAN_MULTIPLIER",
    "STRUCTURED_ENTITIES",
    "Authority",
    "Location",
    "SourceRef",
    "StructuredEntity",
    "StructuredHit",
    "StructuredQuery",
    "block_ref",
    "filters_for",
    "normalize_section",
    "resolve_source",
    "section_matches",
    "split_block_ref",
    "structured_search",
    "works_with_evidence",
]

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
"""Hits per structured query. A personal corpus answers a lookup in tens, not thousands."""

SCAN_MULTIPLIER = 8
MAX_SCAN = 2000
"""A section filter is finished in Python (headings are numbered inconsistently), so the
SQL side over-fetches by :data:`SCAN_MULTIPLIER` and stops at :data:`MAX_SCAN` rows."""

BLOCK_REF_SEPARATOR = "@"
"""`B0081@A0017-3`: a block id is unique only inside its artifact, and the composite is
the same one `retrieval.units.block_unit_id` gives the semantic index."""


# --------------------------------------------------------------------- authority


class Authority(StrEnum):
    """Which rung of the Product SS15.3 ladder a hit came from.

    Accepted Evidence and accepted Claims share the top rung: both are accepted research
    state, and the difference between them is a ranking preference (see
    `retrieval.rerank`), not a difference in authority.
    """

    ACCEPTED_EVIDENCE = "accepted_evidence"
    ACCEPTED_CLAIM = "accepted_claim"
    STRUCTURED_FIELD = "structured_field"
    PARSED_CORPUS = "parsed_corpus"
    CITATION_NEIGHBORHOOD = "citation_neighborhood"
    EXTERNAL_HINT = "external_hint"

    @property
    def rung(self) -> int:
        """Ladder rung, 1 (accepted state) through 5 (external discovery)."""
        return AUTHORITY_RUNGS[self]


AUTHORITY_RUNGS: Mapping[Authority, int] = {
    Authority.ACCEPTED_EVIDENCE: 1,
    Authority.ACCEPTED_CLAIM: 1,
    Authority.STRUCTURED_FIELD: 2,
    Authority.PARSED_CORPUS: 3,
    Authority.CITATION_NEIGHBORHOOD: 4,
    Authority.EXTERNAL_HINT: 5,
}
"""The five rungs of Product SS15.3, in order of decreasing authority."""


# ------------------------------------------------------------------------ records


class Location(BaseModel):
    """Where a hit sits inside its document: page, section, block, character range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    block: BlockId | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)

    def describe(self) -> str:
        """One-line human rendering, e.g. ``p.3 3 Experiments/3.1 Dataset B0081 [284:516]``."""
        parts: list[str] = []
        if self.page is not None:
            parts.append(f"p.{self.page}")
        if self.section_path:
            parts.append("/".join(self.section_path))
        if self.block is not None:
            parts.append(str(self.block))
        if self.char_start is not None and self.char_end is not None:
            parts.append(f"[{self.char_start}:{self.char_end}]")
        return " ".join(parts) or "-"


StructuredEntity = Literal[
    "work", "evidence", "claim", "block", "decision", "question", "matrix_cell"
]

STRUCTURED_ENTITIES: tuple[StructuredEntity, ...] = get_args(StructuredEntity)
"""Every entity :func:`structured_search` can query, in declaration order."""


class StructuredQuery(BaseModel):
    """A lookup: one entity, a handful of equality/range/section filters, a limit.

    Filter names are the vocabulary of :func:`filters_for`; a value may be a string, an
    integer, or a sequence of strings, which becomes an ``IN`` clause. An unknown filter
    is a :class:`ProjectionError` rather than a silently ignored constraint — a query that
    quietly dropped ``status=accepted`` would answer a different question.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: StructuredEntity
    filters: dict[str, str | int | Sequence[str]] = Field(default_factory=dict)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1)

    def with_filters(self, **extra: str | int | Sequence[str]) -> StructuredQuery:
        """A copy carrying ``extra`` on top of the existing filters."""
        return self.model_copy(update={"filters": {**self.filters, **extra}})


class StructuredHit(BaseModel):
    """One projected object: what it is, where it is, and what it is worth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: str
    entity: StructuredEntity
    work: WorkId | None = None
    location: Location = Location()
    fields: dict[str, str] = Field(default_factory=dict)
    """The columns that make this row worth reporting (status, dataset, title, ...)."""

    authority: Authority
    stale: bool = False
    snippet: str = ""


class SourceRef(BaseModel):
    """The exact source location a reference resolves to (`retrieval.resolve_source`).

    Complete enough to reopen the document at the right place: work, version, artifact,
    page, block, section path, character range, and page geometry.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str
    kind: Literal["evidence", "block"]
    work: WorkId
    version: VersionId
    artifact: ArtifactId
    block: BlockId
    file_hash: str | None = None
    page: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    bbox: tuple[float, float, float, float] | None = None
    text: str = ""

    @property
    def location(self) -> Location:
        """The same placement as a :class:`Location`."""
        return Location(
            page=self.page,
            section_path=self.section_path,
            block=self.block,
            char_start=self.char_start,
            char_end=self.char_end,
        )


# ------------------------------------------------------------------- section names


_SECTION_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")
_SECTION_NOISE = re.compile(r"[^a-z0-9 ]+")


def normalize_section(name: str) -> str:
    """A heading reduced to its name: no numbering, no punctuation, lower case.

    ``"3.1 Dataset"`` and ``"Dataset."`` both normalize to ``"dataset"``, which is what
    lets a researcher filter on ``Limitations`` in a corpus whose headings are numbered.
    """
    stripped = _SECTION_NUMBER.sub("", name.strip().lower())
    return " ".join(_SECTION_NOISE.sub(" ", stripped).split())


def section_matches(path: Sequence[str], prefix: str) -> bool:
    """True when ``prefix`` names a contiguous run of headings inside ``path``.

    ``prefix`` may be one heading (``"Limitations"``) or a path of them
    (``"Experiments/Dataset"``). Each part matches a heading whose normalized name starts
    with the normalized part, so ``"Experiment"`` finds ``"3 Experiments"``.
    """
    wanted = [normalize_section(part) for part in prefix.split("/") if part.strip()]
    if not wanted:
        return True
    haystack = [normalize_section(segment) for segment in path]
    if len(wanted) > len(haystack):
        return False
    for start in range(len(haystack) - len(wanted) + 1):
        window = haystack[start : start + len(wanted)]
        if all(found.startswith(part) for found, part in zip(window, wanted, strict=True)):
            return True
    return False


def _matches_any_section(path: Sequence[str], prefixes: Sequence[str]) -> bool:
    return not prefixes or any(section_matches(path, prefix) for prefix in prefixes)


# ---------------------------------------------------------------------- block refs


def block_ref(block: BlockId | str, artifact: ArtifactId | str) -> str:
    """`B0081@A0017-3` — the reference form for a parsed block."""
    return f"{block}{BLOCK_REF_SEPARATOR}{artifact}"


def split_block_ref(ref: str) -> tuple[BlockId, ArtifactId | None]:
    """Split ``B0081@A0017-3`` (or a bare ``B0081``) into its parts."""
    block, _, artifact = ref.partition(BLOCK_REF_SEPARATOR)
    try:
        return BlockId(block), (ArtifactId(artifact) if artifact else None)
    except Exception as exc:  # DomainValidationError, and anything a bad id raises
        raise ProjectionError(f"not a block reference: {ref!r}") from exc


# ------------------------------------------------------------------- entity specs


class _FilterKind(StrEnum):
    """How a filter value is compared against its column."""

    EQUALS = "equals"
    NUMBER = "number"
    MIN = "min"
    MAX = "max"
    SECTION = "section"


@dataclass(frozen=True, slots=True)
class _FilterSpec:
    column: str
    kind: _FilterKind = _FilterKind.EQUALS


@dataclass(frozen=True, slots=True)
class _EntitySpec:
    """How one entity is selected, located, and placed on the authority ladder."""

    entity: StructuredEntity
    table: Table
    id_column: str
    filters: Mapping[str, _FilterSpec]
    fields: tuple[str, ...]
    work_column: str | None = None
    artifact_column: str | None = None
    page_column: str | None = None
    section_column: str | None = None
    block_column: str | None = None
    stale_column: str | None = None
    snippet_column: str | None = None
    authority: Authority = Authority.STRUCTURED_FIELD


def _specs() -> dict[str, _EntitySpec]:
    evidence_filters = {
        "id": _FilterSpec("id"),
        "evidence": _FilterSpec("id"),
        "status": _FilterSpec("status"),
        "origin": _FilterSpec("origin"),
        "evidence_type": _FilterSpec("evidence_type"),
        "type": _FilterSpec("evidence_type"),
        "strength": _FilterSpec("strength"),
        "field": _FilterSpec("field"),
        "work": _FilterSpec("work"),
        "artifact": _FilterSpec("artifact"),
        "block": _FilterSpec("block"),
        "dataset": _FilterSpec("dataset"),
        "metric": _FilterSpec("metric"),
        "stale": _FilterSpec("stale"),
        "page": _FilterSpec("page", _FilterKind.NUMBER),
        "page_min": _FilterSpec("page", _FilterKind.MIN),
        "page_max": _FilterSpec("page", _FilterKind.MAX),
        "section_prefix": _FilterSpec("section_path", _FilterKind.SECTION),
    }
    block_filters = {
        "id": _FilterSpec("id"),
        "block": _FilterSpec("id"),
        "work": _FilterSpec("work"),
        "artifact": _FilterSpec("artifact"),
        "kind": _FilterSpec("kind"),
        "page": _FilterSpec("page", _FilterKind.NUMBER),
        "page_min": _FilterSpec("page", _FilterKind.MIN),
        "page_max": _FilterSpec("page", _FilterKind.MAX),
        "section_prefix": _FilterSpec("section_path", _FilterKind.SECTION),
    }
    return {
        "work": _EntitySpec(
            entity="work",
            table=WORKS,
            id_column="id",
            filters={
                "id": _FilterSpec("id"),
                "work": _FilterSpec("id"),
                "status": _FilterSpec("screening"),
                "screening": _FilterSpec("screening"),
                "year": _FilterSpec("year", _FilterKind.NUMBER),
                "venue": _FilterSpec("venue"),
            },
            fields=("title", "year", "venue", "screening"),
            work_column="id",
            snippet_column="title",
        ),
        "evidence": _EntitySpec(
            entity="evidence",
            table=EVIDENCE,
            id_column="id",
            filters=evidence_filters,
            fields=(
                "status",
                "origin",
                "evidence_type",
                "strength",
                "field",
                "dataset",
                "metric",
                "numeric_raw",
                "numeric_source_table",
            ),
            work_column="work",
            artifact_column="artifact",
            page_column="page",
            section_column="section_path",
            block_column="block",
            stale_column="stale",
            snippet_column="exact_text",
            authority=Authority.ACCEPTED_EVIDENCE,
        ),
        "claim": _EntitySpec(
            entity="claim",
            table=CLAIMS,
            id_column="id",
            filters={
                "id": _FilterSpec("id"),
                "claim": _FilterSpec("id"),
                "status": _FilterSpec("status"),
                "type": _FilterSpec("type"),
                "scope": _FilterSpec("scope_level"),
                "scope_level": _FilterSpec("scope_level"),
                "stale": _FilterSpec("stale"),
            },
            fields=("status", "type", "scope_level", "allowed_strength"),
            stale_column="stale",
            snippet_column="statement",
            authority=Authority.ACCEPTED_CLAIM,
        ),
        "block": _EntitySpec(
            entity="block",
            table=BLOCKS,
            id_column="id",
            filters=block_filters,
            fields=("kind", "caption"),
            work_column="work",
            artifact_column="artifact",
            page_column="page",
            section_column="section_path",
            block_column="id",
            snippet_column="text",
            authority=Authority.PARSED_CORPUS,
        ),
        "decision": _EntitySpec(
            entity="decision",
            table=DECISIONS,
            id_column="id",
            filters={
                "id": _FilterSpec("id"),
                "decision": _FilterSpec("id"),
                "type": _FilterSpec("type"),
                "status": _FilterSpec("status"),
                "claim": _FilterSpec("claim"),
            },
            fields=("type", "status", "title", "claim"),
            snippet_column="rationale",
        ),
        "question": _EntitySpec(
            entity="question",
            table=QUESTIONS,
            id_column="id",
            filters={
                "id": _FilterSpec("id"),
                "question": _FilterSpec("id"),
                "status": _FilterSpec("status"),
                "stale": _FilterSpec("stale"),
            },
            fields=("status",),
            stale_column="stale",
            snippet_column="question",
        ),
        "matrix_cell": _EntitySpec(
            entity="matrix_cell",
            table=MATRIX_CELLS,
            id_column="cell_id",
            filters={
                "id": _FilterSpec("cell_id"),
                "matrix": _FilterSpec("matrix"),
                "work": _FilterSpec("work"),
                "field": _FilterSpec("field"),
            },
            fields=("matrix", "field", "labels", "evidence"),
            work_column="work",
            snippet_column="labels",
        ),
    }


_SPECS: dict[str, _EntitySpec] = _specs()


def filters_for(entity: str) -> tuple[str, ...]:
    """Filter names accepted for ``entity``, sorted; the vocabulary of a query."""
    return tuple(sorted(_spec(entity).filters))


def _spec(entity: str) -> _EntitySpec:
    spec = _SPECS.get(str(entity))
    if spec is None:
        known = ", ".join(STRUCTURED_ENTITIES)
        raise ProjectionError(f"unknown retrieval entity {entity!r}; known entities: {known}")
    return spec


# ------------------------------------------------------------------------- search


def structured_search(engine: Engine, query: StructuredQuery) -> list[StructuredHit]:
    """Look ``query`` up in the projection, best authority first.

    Filters are applied in SQL except the section filter, which is finished in Python
    against normalized heading names; the statement therefore over-fetches and the limit
    is applied to the surviving rows. Results are ordered by authority rung and then by
    id, so the same projection always answers in the same order.
    """
    spec = _spec(query.entity)
    clauses, sections = _clauses(spec, query.filters)
    statement = select(spec.table).where(*clauses).order_by(*_order(spec))
    statement = statement.limit(_scan_limit(query.limit, bool(sections)))
    hits: list[StructuredHit] = []
    with engine.connect() as connection:
        for row in connection.execute(statement).mappings():
            values = dict(row)
            if not _matches_any_section(_section_path(values.get(spec.section_column)), sections):
                continue
            hits.append(_hit(spec, values))
            if len(hits) >= query.limit:
                break
    hits.sort(key=lambda hit: (hit.authority.rung, hit.object_id))
    return hits


def works_with_evidence(
    engine: Engine,
    *,
    field: str,
    value: str,
    status: str = EvidenceStatus.ACCEPTED.value,
    limit: int = DEFAULT_LIMIT,
) -> list[StructuredHit]:
    """Works joined to the accepted Evidence that answers ``field = value``.

    This is the join behind "which papers use CICIDS2017?" (Product SS15.2): the answer is
    read off accepted Evidence, not off a similarity score, and each Work hit names the
    Evidence objects that put it in the result. Pass ``status=""`` to include candidates.
    """
    spec = _spec("evidence")
    filter_spec = spec.filters.get(field)
    if filter_spec is None or filter_spec.kind is not _FilterKind.EQUALS:
        known = ", ".join(
            name for name, item in sorted(spec.filters.items()) if item.kind is _FilterKind.EQUALS
        )
        raise ProjectionError(f"cannot join works on evidence field {field!r}; known: {known}")
    evidence_column = _column(EVIDENCE, filter_spec.column)
    clauses: list[ColumnElement[bool]] = [evidence_column == value]
    if status:
        clauses.append(EVIDENCE.c.status == status)
    statement = (
        select(
            WORKS.c.id,
            WORKS.c.title,
            WORKS.c.year,
            WORKS.c.screening,
            EVIDENCE.c.id.label("evidence_id"),
        )
        .select_from(WORKS.join(EVIDENCE, EVIDENCE.c.work == WORKS.c.id))
        .where(*clauses)
        .order_by(WORKS.c.id, EVIDENCE.c.id)
    )
    grouped: dict[str, list[str]] = {}
    details: dict[str, dict[str, Any]] = {}
    with engine.connect() as connection:
        for row in connection.execute(statement).mappings():
            work = str(row["id"])
            grouped.setdefault(work, []).append(str(row["evidence_id"]))
            details[work] = dict(row)
    hits = [
        StructuredHit(
            object_id=work,
            entity="work",
            work=WorkId(work),
            fields={
                "title": _text(details[work]["title"]),
                "year": _text(details[work]["year"]),
                "screening": _text(details[work]["screening"]),
                field: value,
                "evidence": ", ".join(evidence_ids),
            },
            authority=(Authority.ACCEPTED_EVIDENCE if status else Authority.STRUCTURED_FIELD),
            snippet=_text(details[work]["title"]),
        )
        for work, evidence_ids in grouped.items()
    ]
    return hits[:limit]


def resolve_source(engine: Engine, object_id: str) -> SourceRef:
    """The exact source location behind an Evidence id or a block reference.

    Accepts ``E0482``, ``B0081@A0017-3``, and a bare ``B0081`` when the block id occurs in
    exactly one artifact. Raises :class:`ProjectionError` when nothing resolves, because a
    reference that cannot be reopened at its source is not a reference (Product SS9).
    """
    ref = str(object_id).strip()
    if not ref:
        raise ProjectionError("cannot resolve an empty reference")
    if ref.startswith("E"):
        return _resolve_evidence(engine, ref)
    if ref.startswith("B"):
        return _resolve_block(engine, ref)
    raise ProjectionError(
        f"{ref!r} is not a resolvable source reference; expected an Evidence id (E####) "
        "or a block reference (B####@A####-n)"
    )


def _resolve_evidence(engine: Engine, ref: str) -> SourceRef:
    with engine.connect() as connection:
        row = connection.execute(select(EVIDENCE).where(EVIDENCE.c.id == ref)).mappings().first()
    if row is None:
        raise ProjectionError(f"no evidence {ref} in the projection; rebuild it or check the id")
    return SourceRef(
        ref=ref,
        kind="evidence",
        work=WorkId(str(row["work"])),
        version=VersionId(str(row["version"])),
        artifact=ArtifactId(str(row["artifact"])),
        block=BlockId(str(row["block"])),
        file_hash=_optional(row["file_hash"]),
        page=_int(row["page"]),
        section_path=_section_path(row["section_path"]),
        char_start=_int(row["char_start"]),
        char_end=_int(row["char_end"]),
        bbox=_bbox(row["bbox"]),
        text=_text(row["exact_text"]),
    )


def _resolve_block(engine: Engine, ref: str) -> SourceRef:
    block, artifact = split_block_ref(ref)
    clauses: list[ColumnElement[bool]] = [BLOCKS.c.id == str(block)]
    if artifact is not None:
        clauses.append(BLOCKS.c.artifact == str(artifact))
    with engine.connect() as connection:
        rows = list(
            connection.execute(select(BLOCKS).where(*clauses).order_by(BLOCKS.c.artifact))
            .mappings()
            .fetchmany(2)
        )
    if not rows:
        raise ProjectionError(f"no block {ref} in the projection; rebuild it or check the id")
    if len(rows) > 1:
        raise ProjectionError(
            f"block {block} exists in more than one artifact; name it as "
            f"{block_ref(block, str(rows[0]['artifact']))}"
        )
    row = rows[0]
    return SourceRef(
        ref=block_ref(block, str(row["artifact"])),
        kind="block",
        work=WorkId(str(row["work"])),
        version=VersionId(str(row["version"])),
        artifact=ArtifactId(str(row["artifact"])),
        block=block,
        file_hash=_optional(row["file_hash"]),
        page=_int(row["page"]),
        section_path=_section_path(row["section_path"]),
        bbox=_bbox(row["bbox"]),
        text=_text(row["text"]),
    )


# ------------------------------------------------------------------------ internals


def _clauses(
    spec: _EntitySpec, filters: Mapping[str, str | int | Sequence[str]]
) -> tuple[list[ColumnElement[bool]], list[str]]:
    """SQL clauses plus the section prefixes that have to be finished in Python."""
    clauses: list[ColumnElement[bool]] = []
    sections: list[str] = []
    for name, value in filters.items():
        filter_spec = spec.filters.get(name)
        if filter_spec is None:
            known = ", ".join(sorted(spec.filters))
            raise ProjectionError(
                f"unknown filter {name!r} for {spec.entity}; known filters: {known}"
            )
        column = _column(spec.table, filter_spec.column)
        if filter_spec.kind is _FilterKind.SECTION:
            for prefix in _as_texts(value):
                sections.append(prefix)
                clauses.append(_section_contains(column, prefix))
            continue
        clauses.append(_scalar_clause(column, filter_spec.kind, value))
    return clauses, sections


def _scalar_clause(
    column: Column[Any], kind: _FilterKind, value: str | int | Sequence[str]
) -> ColumnElement[bool]:
    if kind is _FilterKind.MIN:
        return column >= _number(value)
    if kind is _FilterKind.MAX:
        return column <= _number(value)
    if kind is _FilterKind.NUMBER:
        return column == _number(value)
    values = _as_texts(value)
    if len(values) == 1:
        return column == values[0]
    return column.in_(values)


def _section_contains(column: Column[Any], prefix: str) -> ColumnElement[bool]:
    """Cheap SQL narrowing before the Python section match; LIKE is ASCII-insensitive."""
    head = normalize_section(prefix.split("/")[0])
    if not head:
        return column.is_not(None)
    return column.like(f"%{_like_escaped(head)}%", escape="\\")


def _like_escaped(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for wildcard in ("%", "_"):
        escaped = escaped.replace(wildcard, f"\\{wildcard}")
    return escaped


def _order(spec: _EntitySpec) -> tuple[ColumnElement[Any], ...]:
    if spec.page_column is not None:
        return (
            _column(spec.table, spec.page_column),
            _column(spec.table, spec.id_column),
        )
    return (_column(spec.table, spec.id_column),)


def _scan_limit(limit: int, has_section_filter: bool) -> int:
    if not has_section_filter:
        return limit
    return min(MAX_SCAN, limit * SCAN_MULTIPLIER)


def _column(table: Table, name: str) -> Column[Any]:
    column = table.c.get(name)
    if column is None:  # pragma: no cover - guarded by the spec tables above
        raise ProjectionError(f"projection table {table.name} has no column {name!r}")
    return column


def _hit(spec: _EntitySpec, row: Mapping[str, Any]) -> StructuredHit:
    object_id = str(row[spec.id_column])
    artifact = None if spec.artifact_column is None else row.get(spec.artifact_column)
    if spec.entity == "block" and artifact is not None:
        object_id = block_ref(object_id, str(artifact))
    work = None if spec.work_column is None else row.get(spec.work_column)
    return StructuredHit(
        object_id=object_id,
        entity=spec.entity,
        work=None if work is None else WorkId(str(work)),
        location=Location(
            page=None if spec.page_column is None else _int(row.get(spec.page_column)),
            section_path=_section_path(
                None if spec.section_column is None else row.get(spec.section_column)
            ),
            block=(
                None
                if spec.block_column is None or row.get(spec.block_column) is None
                else BlockId(str(row[spec.block_column]))
            ),
            char_start=_int(row.get("char_start")),
            char_end=_int(row.get("char_end")),
        ),
        fields={name: _text(row[name]) for name in spec.fields if row.get(name) not in (None, "")},
        authority=_authority(spec, row),
        stale=_is_stale(spec, row),
        snippet=_snippet(spec, row),
    )


def _authority(spec: _EntitySpec, row: Mapping[str, Any]) -> Authority:
    """Accepted Evidence keeps the top rung; a candidate is only structured state.

    A `proposed`, `rejected` or `superseded` candidate is a real projected row, so it is
    still findable — but calling it accepted state would be exactly the failure Product
    SS8.3 exists to prevent.
    """
    if spec.entity == "evidence":
        status = _optional(row.get("status"))
        if status != EvidenceStatus.ACCEPTED.value:
            return Authority.STRUCTURED_FIELD
    return spec.authority


def _is_stale(spec: _EntitySpec, row: Mapping[str, Any]) -> bool:
    if spec.stale_column is None:
        return False
    return _optional(row.get(spec.stale_column)) == StaleState.STALE.value


def _snippet(spec: _EntitySpec, row: Mapping[str, Any]) -> str:
    if spec.snippet_column is None:
        return ""
    return " ".join(_text(row.get(spec.snippet_column)).split())


def _section_path(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple | list):
        return tuple(str(segment) for segment in value)
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        logger.debug("projected section_path is not JSON: %r", value)
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(segment) for segment in decoded)


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        logger.debug("projected bbox is not JSON: %r", value)
        return None
    if not isinstance(decoded, Mapping):
        return None
    try:
        return tuple(float(decoded[key]) for key in ("x0", "y0", "x1", "y1"))  # type: ignore[return-value]
    except (KeyError, TypeError, ValueError):
        logger.debug("projected bbox is not a rectangle: %r", value)
        return None


def _as_texts(value: str | int | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, int):
        return [str(value)]
    return [str(item) for item in value]


def _number(value: str | int | Sequence[str]) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ProjectionError(f"expected a number, got {value!r}") from exc
    raise ProjectionError(f"expected a number, got {value!r}")


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:  # pragma: no cover - projected integers are integers
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _optional(value: Any) -> str | None:
    return None if value is None else str(value)

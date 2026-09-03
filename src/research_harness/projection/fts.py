"""FTS5 lexical index over the projection: exact terminology search, offline (PRODUCT 15.1).

The index answers "which papers say ``CICIDS2017``?" with no embeddings, no vector store,
and no external service (ADR-006, ROADMAP Task 3.3). Like everything in this package it is
disposable: every row it returns is reachable from a canonical file, and dropping the whole
index costs retrieval speed, never a conclusion.

Design
------

* **External content.** Each virtual table declares ``content='<projection table>'`` so the
  text lives once, in the projection row it came from, and the FTS table stores only the
  inverted index. ``rowid`` is the content table's implicit rowid, so a hit joins back to
  its row (and therefore to its canonical id) with an equality join.
* **Tokenizer.** ``unicode61 remove_diacritics 2`` folds case and diacritics while keeping
  digits inside a token, so ``CICIDS2017`` and ``F1`` are single searchable terms rather
  than a word plus a number. ``prefix='2 3'`` adds 2- and 3-character prefix indexes so
  ``CIC*`` does not degrade into a full scan.
* **Safe input.** :func:`fts_query` reduces arbitrary user text to a MATCH expression built
  only from quoted alphanumeric tokens plus the ``AND``/``OR``/``NOT`` operators, so no
  input can reach the FTS5 parser as syntax. :func:`search_fts` always applies it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from research_harness.domain.errors import ProjectionError
from research_harness.domain.ids import WorkId
from research_harness.projection.schema import (
    BLOCKS,
    CLAIMS,
    EVIDENCE,
    NOTES,
    WORKS,
    assert_fts5_available,
)

__all__ = [
    "DEFAULT_LIMIT",
    "FTS_PREFIX",
    "FTS_TOKENIZER",
    "FTS_VERSION",
    "INDEXES",
    "SECTION_SEPARATOR",
    "FtsHit",
    "FtsIndex",
    "FtsKind",
    "build_fts",
    "drop_fts",
    "fts_query",
    "refresh_fts",
    "search_fts",
]

logger = logging.getLogger(__name__)

FTS_TOKENIZER = "unicode61 remove_diacritics 2"
"""Case- and diacritic-folding tokenizer; digits stay inside their token."""

FTS_PREFIX = "2 3"
"""Prefix index widths, so ``CIC*`` is an index lookup rather than a scan."""

FTS_VERSION = "fts5/1"
"""Recorded in ``projection_meta.fts_version``; bump when the index shape changes."""

SECTION_SEPARATOR = "/"
"""Separator in the ``section_prefix`` filter, e.g. ``Experiments/Dataset``."""

_SNIPPET_OPEN = "["
_SNIPPET_CLOSE = "]"
_SNIPPET_ELLIPSIS = "…"
_SNIPPET_TOKENS = 12
_LIKE_ESCAPE = "\\"

DEFAULT_LIMIT = 20


class FtsKind(StrEnum):
    """Which lexical index a hit came from, and the vocabulary of the ``kinds`` filter."""

    BLOCK = "block"
    EVIDENCE = "evidence"
    CLAIM = "claim"
    WORK = "work"
    NOTE = "note"


@dataclass(frozen=True, slots=True)
class FtsIndex:
    """One FTS5 virtual table and how its columns map onto a :class:`FtsHit`."""

    kind: FtsKind
    name: str
    content: str
    indexed: tuple[str, ...]
    unindexed: tuple[str, ...]
    object_id: str
    work: str | None = None
    page: str | None = None
    section_path: str | None = None


@dataclass(frozen=True, slots=True)
class FtsHit:
    """One lexical match: what matched, where it lives, and how well it scored."""

    object_id: str
    kind: FtsKind
    work: str | None
    page: int | None
    section_path: tuple[str, ...]
    snippet: str
    rank: float
    """SQLite ``bm25()``: lower is a better match, and results come back ascending."""


INDEXES: tuple[FtsIndex, ...] = (
    FtsIndex(
        kind=FtsKind.BLOCK,
        name="blocks_fts",
        content=BLOCKS.name,
        indexed=("text",),
        unindexed=("id", "kind", "work", "page", "section_path"),
        object_id="id",
        work="work",
        page="page",
        section_path="section_path",
    ),
    FtsIndex(
        kind=FtsKind.EVIDENCE,
        name="evidence_fts",
        content=EVIDENCE.name,
        indexed=("exact_text",),
        unindexed=("id", "work", "page", "section_path"),
        object_id="id",
        work="work",
        page="page",
        section_path="section_path",
    ),
    FtsIndex(
        kind=FtsKind.CLAIM,
        name="claims_fts",
        content=CLAIMS.name,
        indexed=("statement",),
        unindexed=("id",),
        object_id="id",
    ),
    FtsIndex(
        kind=FtsKind.WORK,
        name="works_fts",
        content=WORKS.name,
        indexed=("title", "authors", "venue", "year"),
        unindexed=("id",),
        object_id="id",
        work="id",
    ),
    FtsIndex(
        kind=FtsKind.NOTE,
        name="notes_fts",
        content=NOTES.name,
        indexed=("text",),
        unindexed=("note_key", "status"),
        object_id="note_key",
    ),
)
"""Every lexical index, in a stable order (PRODUCT 15.1: blocks, evidence, claims, works, notes)."""


# --- lifecycle --------------------------------------------------------------


def build_fts(engine: Engine) -> int:
    """Create any missing FTS5 table and index every row; returns the rows indexed."""
    assert_fts5_available(engine)
    with engine.begin() as connection:
        for index in INDEXES:
            connection.execute(text(_create_statement(index)))
        return _reindex(connection)


def refresh_fts(engine: Engine) -> int:
    """Drop and rebuild every FTS5 table; returns the rows indexed.

    Stronger than the FTS5 ``'rebuild'`` command alone: it also re-applies the current
    tokenizer and prefix configuration, which a table created by an older harness may not
    have. Reads the projection tables only, so it never touches canonical files.
    """
    drop_fts(engine)
    return build_fts(engine)


def drop_fts(engine: Engine) -> None:
    """Drop every FTS5 table; the lexical index is disposable by definition (ADR-006)."""
    with engine.begin() as connection:
        for index in INDEXES:
            connection.execute(text(f'DROP TABLE IF EXISTS "{index.name}"'))


def _create_statement(index: FtsIndex) -> str:
    columns = [f'"{column}"' for column in index.indexed]
    columns += [f'"{column}" UNINDEXED' for column in index.unindexed]
    return (
        f'CREATE VIRTUAL TABLE IF NOT EXISTS "{index.name}" USING fts5('
        f"{', '.join(columns)}, "
        f"content='{index.content}', "
        f"tokenize='{FTS_TOKENIZER}', "
        f"prefix='{FTS_PREFIX}')"
    )


def _reindex(connection: Connection) -> int:
    total = 0
    for index in INDEXES:
        connection.execute(text(f'INSERT INTO "{index.name}"("{index.name}") VALUES(\'rebuild\')'))
        counted = connection.execute(text(f'SELECT count(*) FROM "{index.content}"')).scalar_one()
        total += int(counted)
    return total


# --- query construction -----------------------------------------------------

_OPERATORS = frozenset({"AND", "OR", "NOT"})
_SCAN = re.compile(r'"(?P<phrase>[^"]*)"|(?P<word>[^\s"]+)')


def fts_query(terms: str) -> str:
    """Turn free user text into a MATCH expression that cannot be a syntax error.

    Every search term is emitted as a quoted FTS5 string containing only alphanumeric
    characters and spaces - the same reduction ``unicode61`` performs on the indexed text -
    so quotes, parentheses, and operators pasted into a search box are searched for, never
    executed. Supported syntax: ``"quoted phrases"``, a trailing ``*`` for a prefix search,
    and the ``AND`` / ``OR`` / ``NOT`` operators between terms. Returns ``""`` when the
    input carries no searchable term.
    """
    parts: list[str] = []
    for token, quoted, prefix in _scan(terms):
        if not quoted and token.upper() in _OPERATORS:
            parts.append(token.upper())
            continue
        cleaned = _tokenizable(token)
        if not cleaned:
            continue
        parts.append(f'"{cleaned}"*' if prefix else f'"{cleaned}"')
    return " ".join(_without_dangling_operators(parts))


def _scan(terms: str) -> Iterator[tuple[str, bool, bool]]:
    """Yield ``(token, quoted, prefix)``; an unterminated quote is simply ignored."""
    for match in _SCAN.finditer(terms):
        phrase = match.group("phrase")
        if phrase is not None:
            yield phrase, True, terms[match.end() : match.end() + 1] == "*"
            continue
        word = match.group("word")
        yield word.rstrip("*"), False, word.endswith("*")


def _tokenizable(token: str) -> str:
    """``token`` reduced to what ``unicode61`` would index: alphanumerics and spaces."""
    folded = "".join(character if character.isalnum() else " " for character in token)
    return " ".join(folded.split())


def _without_dangling_operators(parts: Sequence[str]) -> list[str]:
    """Drop leading, trailing, and repeated operators, which FTS5 rejects as syntax."""
    kept: list[str] = []
    for part in parts:
        operator = part in _OPERATORS
        if operator and (not kept or kept[-1] in _OPERATORS):
            continue
        kept.append(part)
    while kept and kept[-1] in _OPERATORS:
        kept.pop()
    return kept


# --- search -----------------------------------------------------------------


def search_fts(
    engine: Engine,
    query: str,
    *,
    kinds: Sequence[str] | None = None,
    work: WorkId | None = None,
    section_prefix: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[FtsHit]:
    """Lexical search across every index, best match first.

    ``query`` is user input: it is normalized by :func:`fts_query`, so it can never be an
    FTS5 syntax error and never returns rows the caller did not ask for. ``kinds`` selects
    which indexes to search (:class:`FtsKind` values). ``work`` and ``section_prefix``
    restrict hits to one Work and to a section path prefix such as
    ``"Experiments/Dataset"``; both drop the indexes that cannot answer them (a Claim has
    no page, a note has no Work), because "in this section" cannot be true of an object
    that has no section.
    """
    match = fts_query(query)
    if not match or limit <= 0:
        return []
    selected = _selected_kinds(kinds)
    pattern = None if section_prefix is None else _section_pattern(section_prefix)
    hits: list[FtsHit] = []
    with engine.connect() as connection:
        for index in INDEXES:
            if index.kind not in selected:
                continue
            if work is not None and index.work is None:
                continue
            if pattern is not None and index.section_path is None:
                continue
            hits.extend(
                _search_index(
                    connection,
                    index,
                    match,
                    work=None if work is None else str(work),
                    pattern=pattern,
                    limit=limit,
                )
            )
    hits.sort(key=lambda hit: (hit.rank, hit.kind.value, hit.object_id))
    return hits[:limit]


def _selected_kinds(kinds: Sequence[str] | None) -> frozenset[FtsKind]:
    if kinds is None:
        return frozenset(FtsKind)
    selected: set[FtsKind] = set()
    for kind in kinds:
        try:
            selected.add(FtsKind(str(kind)))
        except ValueError:
            known = ", ".join(sorted(member.value for member in FtsKind))
            raise ProjectionError(f"unknown search kind {kind!r}; known kinds: {known}") from None
    return frozenset(selected)


def _search_index(
    connection: Connection,
    index: FtsIndex,
    match: str,
    *,
    work: str | None,
    pattern: str | None,
    limit: int,
) -> list[FtsHit]:
    parameters: dict[str, str | int] = {"match": match, "limit": limit}
    if work is not None:
        parameters["work"] = work
    if pattern is not None:
        parameters["section"] = pattern
    rows = connection.execute(
        text(_search_statement(index, work=work is not None, section=pattern is not None)),
        parameters,
    ).mappings()
    return [_hit(index, dict(row)) for row in rows]


def _content_column(column: str | None, alias: str) -> str:
    """``c."<column>" AS <alias>``, or a NULL placeholder when this index has no such column."""
    source = "NULL" if column is None else f'c."{column}"'
    return f"{source} AS {alias}"


def _search_statement(index: FtsIndex, *, work: bool, section: bool) -> str:
    fts = f'"{index.name}"'
    columns = [
        _content_column(index.object_id, "object_id"),
        _content_column(index.work, "work"),
        _content_column(index.page, "page"),
        _content_column(index.section_path, "section_path"),
        f"snippet({fts}, -1, '{_SNIPPET_OPEN}', '{_SNIPPET_CLOSE}', "
        f"'{_SNIPPET_ELLIPSIS}', {_SNIPPET_TOKENS}) AS snippet",
        f"bm25({fts}) AS score",
    ]
    clauses = [f"{fts} MATCH :match"]
    if work and index.work is not None:
        clauses.append(f'c."{index.work}" = :work')
    if section and index.section_path is not None:
        clauses.append(f"c.\"{index.section_path}\" LIKE :section ESCAPE '{_LIKE_ESCAPE}'")
    return (
        f"SELECT {', '.join(columns)} "
        f'FROM {fts} JOIN "{index.content}" AS c ON c.rowid = {fts}.rowid '
        f"WHERE {' AND '.join(clauses)} "
        f"ORDER BY score LIMIT :limit"
    )


def _hit(index: FtsIndex, row: dict[str, object]) -> FtsHit:
    page = row["page"]
    return FtsHit(
        object_id=str(row["object_id"]),
        kind=index.kind,
        work=None if row["work"] is None else str(row["work"]),
        page=None if page is None else int(str(page)),
        section_path=_section_path(row["section_path"]),
        snippet=str(row["snippet"]),
        rank=float(str(row["score"])),
    )


def _section_path(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        logger.debug("projected section_path is not JSON: %r", value)
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(segment) for segment in decoded)


def _section_pattern(section_prefix: str) -> str:
    """LIKE pattern matching the JSON section path whose leading segments are the prefix."""
    segments = [segment for segment in section_prefix.split(SECTION_SEPARATOR) if segment]
    if not segments:
        return "%"
    encoded = json.dumps(segments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{_like_escaped(encoded[:-1])}%"


def _like_escaped(value: str) -> str:
    escaped = value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    for wildcard in ("%", "_"):
        escaped = escaped.replace(wildcard, f"{_LIKE_ESCAPE}{wildcard}")
    return escaped

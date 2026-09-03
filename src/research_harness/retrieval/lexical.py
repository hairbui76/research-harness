"""Lexical retrieval: exact terminology over FTS5, with structure and synonyms on top.

The FTS5 projection (`projection.fts`) already guarantees the thing Product SS15.1 asks a
lexical index for: ``CICIDS2017`` is findable with no embeddings, no service, and no
network. This module adds the two things a research query needs on top of that guarantee
and nothing else:

* **Structural constraints.** "Does this paper acknowledge encrypted-traffic limitations?"
  is a search inside Discussion / Limitations / Conclusion (Product SS15.2). Heading
  numbering differs between publishers, so the constraint is matched against normalized
  heading names (`structured.section_matches`) rather than against the raw projected path.
* **A synonym hook.** A query may carry a small :class:`SynonymTable` — dataset aliases,
  metric spellings — and every alias is searched *in addition to* the terms as given. The
  exact terms are always searched first and an exact match always outranks a match reached
  through an alias, so expansion can add recall but can never take an exact hit away.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine

from research_harness.domain.ids import BlockId, WorkId
from research_harness.projection.fts import FtsHit, FtsKind, fts_query, search_fts
from research_harness.retrieval.structured import (
    MAX_SCAN,
    SCAN_MULTIPLIER,
    Location,
    section_matches,
)

__all__ = [
    "CONCLUSION_SECTIONS",
    "DEFAULT_LIMIT",
    "LEXICAL_FLOOR",
    "RESULT_SECTIONS",
    "LexicalHit",
    "SynonymTable",
    "lexical_search",
]

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20

LEXICAL_FLOOR = 0.2
"""Score of the weakest hit in a result set. A hit that came back at all matched the
query, so it keeps a floor rather than being normalized down to zero and disappearing
under the weighted sum in `retrieval.rerank`."""

CONCLUSION_SECTIONS: tuple[str, ...] = ("Discussion", "Limitations", "Conclusion")
"""Where a paper admits what it does not show (Product SS15.2)."""

RESULT_SECTIONS: tuple[str, ...] = ("Results", "Experiments", "Evaluation", "Ablation")
"""Where a paper reports what it measured; the sections an empirical audit trusts."""


class SynonymTable(BaseModel):
    """A small term -> aliases mapping a query may carry, e.g. dataset spellings.

    Deliberately not a canonical object and deliberately not global: a synonym table is a
    property of one question ("CIC-IDS-2017 is the same corpus as CICIDS2017"), and
    writing it into the project's accepted state would make a search convenience look like
    a scientific equivalence. Lookup folds case; expansion never replaces the original
    term.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    terms: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    def aliases(self, term: str) -> tuple[str, ...]:
        """Aliases registered for ``term``, case-insensitively; ``()`` when there are none."""
        folded = term.strip().lower()
        for key, values in self.terms.items():
            if key.strip().lower() == folded:
                return tuple(value for value in values if value.strip())
        return ()

    def expansions(self, terms: str) -> list[tuple[str, str]]:
        """``(alias, rewritten query)`` for every alias that applies to ``terms``.

        One alias is substituted at a time: replacing several at once would produce a
        query nobody wrote, and the point of the hook is extra recall for one known
        spelling, not a combinatorial rewrite.
        """
        tokens = terms.split()
        rewritten: list[tuple[str, str]] = []
        seen: set[str] = set()
        for index, token in enumerate(tokens):
            stripped = token.strip('.,;:?!"()')
            for alias in self.aliases(stripped):
                candidate = " ".join([*tokens[:index], alias, *tokens[index + 1 :]])
                if candidate != terms and candidate not in seen:
                    seen.add(candidate)
                    rewritten.append((alias, candidate))
        return rewritten

    def __bool__(self) -> bool:
        return bool(self.terms)


class LexicalHit(BaseModel):
    """One FTS5 match: what matched, where it lives, and how strongly it scored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: str
    kind: FtsKind
    work: WorkId | None = None
    location: Location = Location()
    snippet: str = ""
    rank: float
    """Raw SQLite ``bm25()``; lower is a better match."""

    score: float = Field(ge=0.0, le=1.0)
    """``rank`` normalized within this result set; higher is better."""

    exact: bool = True
    """False when only a synonym expansion found this hit, never the terms as given."""

    via: str | None = None
    """The alias that found it, when ``exact`` is False."""


def lexical_search(
    engine: Engine,
    terms: str,
    *,
    kinds: Sequence[FtsKind | str] | None = None,
    work: WorkId | None = None,
    section_prefix: str | Sequence[str] | None = None,
    synonyms: SynonymTable | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[LexicalHit]:
    """Search the lexical projection, best match first.

    ``terms`` is free user text: `projection.fts.fts_query` reduces it to a MATCH
    expression that cannot be a syntax error, so nothing here has to sanitize it again.
    ``section_prefix`` may be one heading or several (``"Limitations"``,
    ``("Discussion", "Conclusion")``) and is matched against normalized heading names, so
    ``Limitations`` finds ``5 Limitations``. ``synonyms`` adds alias searches after the
    exact one. Returns ``[]`` for a query with no searchable term.
    """
    if limit <= 0 or not fts_query(terms):
        return []
    sections = _sections(section_prefix)
    scan = min(MAX_SCAN, limit * SCAN_MULTIPLIER) if sections else limit
    kind_values = None if kinds is None else [str(kind) for kind in kinds]

    found: dict[str, LexicalHit] = {}
    for alias, query in [(None, terms), *_expansions(synonyms, terms)]:
        for hit in search_fts(engine, query, kinds=kind_values, work=work, limit=scan):
            if hit.object_id in found or not _in_sections(hit, sections):
                continue
            found[hit.object_id] = _hit(hit, alias)
    return _ranked(found.values(), limit)


def _expansions(synonyms: SynonymTable | None, terms: str) -> list[tuple[str, str]]:
    if synonyms is None or not synonyms:
        return []
    return synonyms.expansions(terms)


def _sections(section_prefix: str | Sequence[str] | None) -> tuple[str, ...]:
    if section_prefix is None:
        return ()
    if isinstance(section_prefix, str):
        return (section_prefix,) if section_prefix.strip() else ()
    return tuple(prefix for prefix in section_prefix if prefix.strip())


def _in_sections(hit: FtsHit, sections: Sequence[str]) -> bool:
    """A section constraint excludes what has no section: a Claim is not "in Limitations"."""
    if not sections:
        return True
    if not hit.section_path:
        return False
    return any(section_matches(hit.section_path, prefix) for prefix in sections)


def _hit(hit: FtsHit, alias: str | None) -> LexicalHit:
    return LexicalHit(
        object_id=hit.object_id,
        kind=hit.kind,
        work=None if hit.work is None else WorkId(hit.work),
        location=Location(
            page=hit.page,
            section_path=hit.section_path,
            block=BlockId(hit.object_id) if hit.kind is FtsKind.BLOCK else None,
        ),
        snippet=hit.snippet,
        rank=hit.rank,
        score=0.0,
        exact=alias is None,
        via=alias,
    )


def _ranked(hits: Iterable[LexicalHit], limit: int) -> list[LexicalHit]:
    """Score within the result set, exact matches first, then bm25, then id."""
    collected = list(hits)
    if not collected:
        return []
    ranks = [hit.rank for hit in collected]
    best, worst = min(ranks), max(ranks)
    scored = [hit.model_copy(update={"score": _score(hit.rank, best, worst)}) for hit in collected]
    scored.sort(key=lambda hit: (not hit.exact, hit.rank, hit.kind.value, hit.object_id))
    return scored[:limit]


def _score(rank: float, best: float, worst: float) -> float:
    """bm25 mapped into ``[LEXICAL_FLOOR, 1.0]``; ties all score 1.0."""
    if worst <= best:
        return 1.0
    return LEXICAL_FLOOR + (1.0 - LEXICAL_FLOOR) * (worst - rank) / (worst - best)

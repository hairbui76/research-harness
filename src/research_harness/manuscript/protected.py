"""Spans inside a manuscript sentence that a style pass must never alter (Product 30.4).

A humanization, venue-formatting, or copy-editing pass rewrites prose; it may not touch
citation commands, cross-references, math, exact numbers and units, quotations, research
identifiers, code, or links. Recording those spans with exact offsets is what makes the
later semantic diff (Product 42 L) able to prove that a rewrite preserved them.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.ids import ID_TYPES

__all__ = [
    "CITATION_COMMANDS",
    "CITATION_RE",
    "NUMBER_WITH_UNIT_PATTERN",
    "REFERENCE_COMMANDS",
    "ProtectedSpan",
    "ProtectedSpanKind",
    "find_protected_spans",
]


class ProtectedSpanKind(StrEnum):
    """What a protected span is, which decides how a style pass may treat it."""

    CITATION = "citation"
    REFERENCE = "reference"
    MATH = "math"
    NUMBER_WITH_UNIT = "number_with_unit"
    QUOTATION = "quotation"
    IDENTIFIER = "identifier"
    CODE = "code"
    URL = "url"


class ProtectedSpan(BaseModel):
    """One immutable region of a sentence, with offsets relative to that sentence text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProtectedSpanKind
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    text: str


CITATION_COMMANDS: tuple[str, ...] = (
    "autocite",
    "citealp",
    "citealt",
    "citeauthor",
    "citep",
    "citet",
    "citeyear",
    "cite",
    "footcite",
    "parencite",
    "textcite",
)
"""Citation macros recognized in manuscript text (natbib, biblatex, and plain LaTeX)."""

REFERENCE_COMMANDS: tuple[str, ...] = (
    "autoref",
    "cref",
    "Cref",
    "eqref",
    "nameref",
    "pageref",
    "ref",
    "vref",
)
"""Cross-reference macros; their targets are structural, never prose."""


def _alternation(names: tuple[str, ...]) -> str:
    # Longest first so that ``citep`` wins over ``cite``.
    return "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))


#: ``\citep[see][p.~3]{a,b}`` - optional bracket arguments, then one brace group of keys.
CITATION_PATTERN = (
    rf"\\(?:{_alternation(CITATION_COMMANDS)})\*?(?:\s*\[[^\[\]]*\])*\s*\{{([^{{}}]*)\}}"
)
CITATION_RE = re.compile(CITATION_PATTERN)

_REFERENCE_PATTERN = (
    rf"\\(?:{_alternation(REFERENCE_COMMANDS)})\*?(?:\s*\[[^\[\]]*\])*\s*\{{[^{{}}]*\}}"
)

# Inline math only; display math is a block, not part of any sentence. The inner
# alternation consumes escaped characters first so that ``\$`` never closes the span.
_MATH_PATTERNS = (
    r"(?<!\\)\$(?:\\.|[^$\\])*\$",
    r"\\\(.*?\\\)",
    r"\\\[.*?\\\]",
)

_CODE_PATTERNS = (
    r"\\texttt\s*\{[^{}]*\}",
    r"\\lstinline\s*(?:\[[^\[\]]*\])?\{[^{}]*\}",
    r"\\verb\*?(?P<verbdelim>[^A-Za-z\s])(?:(?!(?P=verbdelim)).)*(?P=verbdelim)",
)

_URL_PATTERNS = (
    r"\\(?:url|href)\s*\{[^{}]*\}(?:\s*\{[^{}]*\})?",
    # Bare links stop before trailing sentence punctuation.
    r"(?:https?|ftp)://[^\s{}\\]*[^\s{}\\.,;:)\]'\"]",
)

_QUOTATION_PATTERNS = (
    r"``(?:(?!'').)*''",
    r"\u201c[^\u201d]*\u201d",
    r"\\enquote\s*\{[^{}]*\}",
    r'"[^"\n]*"',
)

_ID_PREFIXES = "|".join(
    re.escape(id_type.prefix) for id_type in sorted(ID_TYPES, key=lambda t: -len(t.prefix))
)
_IDENTIFIER_PATTERNS = (
    # Research ids (C0041, E0132, V0017-2) as written in canonical state.
    rf"(?<![A-Za-z0-9])(?:{_ID_PREFIXES})\d{{4,}}(?:-\d+)?(?![A-Za-z0-9])",
    r"(?<![\w./])10\.\d{4,9}/[-._;()/:A-Za-z0-9]+",
    r"(?i:arXiv):\d{4}\.\d{4,5}(?:v\d+)?",
)

_NUMBER = r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
_UNIT = (
    r"(?:\\?%|ms|\u00b5s|us|ns|Hz|kHz|MHz|GHz|KiB|MiB|GiB|KB|MB|GB|TB|kB"
    r"|px|pt|mm|cm|km|kg|mg|dB|kW|fps|F1|BLEU|ROUGE|mAP|AUC|\u00d7|[smgWBx])"
)
#: A number, optionally followed by one unit or metric token: ``94.32``, ``4.2 F1``,
#: ``50\%``, ``120 ms``, ``3.5 GB``. The lookbehind stops the match from starting inside
#: another number or word (``94.32`` never yields ``32``); the lookahead stops it from
#: eating a following word (``3 models`` yields ``3``).
NUMBER_WITH_UNIT_PATTERN = rf"(?<![\w.]){_NUMBER}(?:[ ~]?{_UNIT})?(?!\w)"

_DETECTORS: tuple[tuple[ProtectedSpanKind, tuple[str, ...]], ...] = (
    (ProtectedSpanKind.URL, _URL_PATTERNS),
    (ProtectedSpanKind.CITATION, (CITATION_PATTERN,)),
    (ProtectedSpanKind.REFERENCE, (_REFERENCE_PATTERN,)),
    (ProtectedSpanKind.CODE, _CODE_PATTERNS),
    (ProtectedSpanKind.MATH, _MATH_PATTERNS),
    (ProtectedSpanKind.QUOTATION, _QUOTATION_PATTERNS),
    (ProtectedSpanKind.IDENTIFIER, _IDENTIFIER_PATTERNS),
    (ProtectedSpanKind.NUMBER_WITH_UNIT, (NUMBER_WITH_UNIT_PATTERN,)),
)

_PRIORITY: dict[ProtectedSpanKind, int] = {
    kind: index for index, (kind, _) in enumerate(_DETECTORS)
}

_COMPILED: tuple[tuple[ProtectedSpanKind, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.DOTALL)) for kind, patterns in _DETECTORS for pattern in patterns
)


def find_protected_spans(sentence_text: str) -> tuple[ProtectedSpan, ...]:
    """Non-overlapping protected spans of ``sentence_text``, in document order.

    Candidates are collected from every detector and then resolved outermost-first: the
    span that starts earliest wins, and the longest wins at an equal start, so a number
    inside a citation or a quotation is covered by the enclosing span rather than split
    out of it. Ties between equal spans are broken by detector order.
    """
    candidates: list[ProtectedSpan] = []
    for kind, pattern in _COMPILED:
        for match in pattern.finditer(sentence_text):
            if match.end() > match.start():
                candidates.append(
                    ProtectedSpan(
                        kind=kind,
                        char_start=match.start(),
                        char_end=match.end(),
                        text=match.group(0),
                    )
                )
    candidates.sort(key=lambda span: (span.char_start, -span.char_end, _PRIORITY[span.kind]))

    kept: list[ProtectedSpan] = []
    covered_to = 0
    for span in candidates:
        if span.char_start >= covered_to:
            kept.append(span)
            covered_to = span.char_end
    return tuple(kept)

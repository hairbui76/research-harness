"""How strong a manuscript sentence *sounds*, on the claim scope ladder (Product 10.2, 10.5).

The claim engine computes the strongest wording the evidence defends
(:mod:`research_harness.claims.strength`); this module reads the wording the author
actually wrote. Comparing the two is what stops a corpus-level result from being published
as a universal one (Product 42.G) without anyone deciding to escalate it.

The estimate is a documented cue table, not a model: a researcher can read
:data:`CUE_TABLE`, see why a sentence was scored L4, and argue with it. Hedges
(:data:`HEDGE_CUES`) lower the level by one, which is what makes "we identified no work
that ..." weaker than "no work exists" - the exact distinction Product 10.5 asks for.

Where the table is silent the estimate is L0. The bias is deliberate: an over-strong
warning that fires on ordinary prose gets the whole audit switched off, so a missed
warning is the cheaper error and the ladder itself remains the hard guard.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict

from research_harness.claims.strength import (
    FIELD_WORDING,
    INDIVIDUAL_WORDING,
    MAJORITY_WORDING,
    OBSERVED_SUBSET_WORDING,
    SEVERAL_WORDING,
)
from research_harness.domain.enums import ClaimScope
from research_harness.manuscript.protected import CITATION_RE

__all__ = [
    "CUE_TABLE",
    "HEDGE_CUES",
    "QUALIFIERS",
    "WordingEstimate",
    "cues_in",
    "stronger_than",
    "wording_level",
]


#: Quantifiers that scope a bare plural. "existing systems" is a field-level statement;
#: "several existing systems" is not, so the qualifier's own cue decides the level.
QUALIFIERS: frozenset[str] = frozenset(
    {
        "a few",
        "a number of",
        "certain",
        "many",
        "most",
        "numerous",
        "several",
        "some",
        "the majority of",
        "these",
        "those",
        "two",
        "three",
        "four",
        "five",
    }
)

CUE_TABLE: Mapping[ClaimScope, tuple[str, ...]] = MappingProxyType(
    {
        #: L4 admits no exception and no unexamined work; it is the only level whose cues
        #: assert something about papers nobody read.
        ClaimScope.UNIVERSAL_OR_ABSENCE: (
            "all",
            "always",
            "never",
            "no work exists",
            "no prior work",
            "no existing work",
            "none of",
            "universally",
            "every",
            "without exception",
        ),
        #: L3 generalizes past the reviewed corpus to the field as a whole.
        ClaimScope.FIELD_GENERALIZATION: (
            FIELD_WORDING,  # "existing work generally"
            "prior work generally",
            "the field",
            "the literature",
            "in general",
            "existing systems",
            "existing approaches",
            "state of the art",
            "state-of-the-art",
            "it is well known",
            "widely",
        ),
        #: L2 speaks for a defined corpus: a majority, or a repeated pattern within it.
        ClaimScope.CORPUS_PATTERN: (
            MAJORITY_WORDING,  # "most systems in the reviewed corpus"
            SEVERAL_WORDING,  # "several existing approaches" - the L1/L2 boundary
            "most",
            "the majority",
            "typically",
            "commonly",
            "usually",
            "in the reviewed corpus",
            "across the corpus",
        ),
        #: L1 speaks only for the papers that were actually examined.
        ClaimScope.OBSERVED_SUBSET: (
            OBSERVED_SUBSET_WORDING,  # "among the papers examined"
            "several",
            "some",
            "a number of",
            "a few",
            "many",
            "in the papers we examined",
        ),
        #: L0 speaks about one work; it is also the floor when no cue fires.
        ClaimScope.INDIVIDUAL: (
            INDIVIDUAL_WORDING,  # "in the work examined"
            "this paper",
            "this work",
            "the authors",
            "a single",
            "one system",
        ),
    }
)
"""Cue phrases per scope level, read highest level first. Documented so a researcher can
audit the audit: every level a sentence is scored at names the phrase that scored it."""

HEDGE_CUES: tuple[str, ...] = (
    "we identified no work that",
    "to our knowledge",
    "to the best of our knowledge",
    "as far as we know",
    "among the examined",
    "we are not aware of",
)
"""Phrases that bound a statement to the search actually performed. Each hedged sentence
drops one ladder level, so "we identified no work that ..." never reads as L4 (Product
10.5); the floor is L0."""


_CLEANUP_RE = re.compile(r"\\[A-Za-z]+\*?(?:\s*\[[^\[\]]*\])*(?:\s*\{([^{}]*)\})?")
_SPACE_RE = re.compile(r"\s+")
_QUALIFIER_TAIL_RE = re.compile(r"([a-z0-9 ]{0,24})$")

#: Bare plurals whose level depends on whether a quantifier scopes them: "existing
#: systems" generalizes to the field, "several existing systems" does not.
_QUALIFIABLE: frozenset[str] = frozenset({"existing approaches", "existing systems"})

#: Phrases whose cue must not also fire at a lower level. "several existing approaches" is
#: an L2 phrase that literally contains the L1 cue "several"; the longer phrase wins.
_SUBSUMED: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        SEVERAL_WORDING: ("several",),
        MAJORITY_WORDING: ("most", "in the reviewed corpus"),
        OBSERVED_SUBSET_WORDING: ("among the examined",),
        FIELD_WORDING: ("in general",),
        "no existing work": ("existing work generally",),
    }
)


class WordingEstimate(BaseModel):
    """The ladder level a sentence reads at, and the phrases that put it there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: ClaimScope
    cues: tuple[str, ...] = ()
    hedges: tuple[str, ...] = ()
    unhedged_level: ClaimScope = ClaimScope.INDIVIDUAL
    """The level before hedges were applied; equal to ``level`` when nothing hedged it."""

    @property
    def hedged(self) -> bool:
        """True when a hedge lowered the level by one."""
        return self.level is not self.unhedged_level


def _normalize(sentence_text: str) -> str:
    """Lowercase prose with citation commands, markup, and braces removed."""
    text = CITATION_RE.sub(" ", sentence_text)
    text = _CLEANUP_RE.sub(lambda match: f" {match.group(1) or ''} ", text)
    text = text.replace("~", " ").replace("{", " ").replace("}", " ")
    return _SPACE_RE.sub(" ", text).casefold().strip()


def _contains(haystack: str, phrase: str) -> bool:
    """Whole-phrase match: ``all`` must not fire on ``allocation``."""
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", haystack) is not None


def _qualified(haystack: str, phrase: str) -> bool:
    """True when every occurrence of ``phrase`` is preceded by a scoping quantifier."""
    occurrences = list(re.finditer(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", haystack))
    if not occurrences:
        return False
    for match in occurrences:
        tail = _QUALIFIER_TAIL_RE.search(haystack[: match.start()].rstrip())
        window = (tail.group(1) if tail else "").strip()
        if not any(window.endswith(qualifier) for qualifier in QUALIFIERS):
            return False
    return True


def cues_in(sentence_text: str) -> Mapping[ClaimScope, tuple[str, ...]]:
    """Every cue phrase the sentence contains, grouped by the level that claims it."""
    haystack = _normalize(sentence_text)
    found: dict[ClaimScope, tuple[str, ...]] = {}
    matched: set[str] = set()
    for level in sorted(CUE_TABLE, key=lambda scope: -scope.level):
        hits: list[str] = []
        for phrase in CUE_TABLE[level]:
            if not _contains(haystack, phrase):
                continue
            if any(phrase in _SUBSUMED.get(longer, ()) for longer in matched):
                continue
            if phrase in _QUALIFIABLE and _qualified(haystack, phrase):
                continue
            hits.append(phrase)
            matched.add(phrase)
        if hits:
            found[level] = tuple(hits)
    return MappingProxyType(found)


def wording_level(sentence_text: str) -> WordingEstimate:
    """Estimate the scope level a sentence asserts, from :data:`CUE_TABLE`.

    The highest level with a cue wins, because a sentence is as strong as its strongest
    claim: "most systems fail, and none recovers" is universal, not corpus-level. A hedge
    from :data:`HEDGE_CUES` then lowers the result one rung, and a sentence with no cue at
    all scores L0.
    """
    haystack = _normalize(sentence_text)
    found = cues_in(sentence_text)
    hedges = tuple(phrase for phrase in HEDGE_CUES if _contains(haystack, phrase))

    unhedged = ClaimScope.INDIVIDUAL
    cues: tuple[str, ...] = ()
    for level in sorted(found, key=lambda scope: -scope.level):
        unhedged, cues = level, found[level]
        break

    level = unhedged
    if hedges and unhedged.level > 0:
        level = ClaimScope.from_level(unhedged.level - 1)
    return WordingEstimate(level=level, cues=cues, hedges=hedges, unhedged_level=unhedged)


def stronger_than(sentence_level: ClaimScope, allowed: ClaimScope) -> bool:
    """True when the sentence reads higher on the ladder than the evidence allows."""
    return sentence_level > allowed

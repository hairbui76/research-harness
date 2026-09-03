"""Research-utility reranking: rank by what a researcher can defend, not by similarity.

A similarity score answers "which text resembles this query". A researcher auditing a
number needs something else: the Results table the number was measured in, before the
abstract sentence that summarises it; accepted Evidence before prose that merely sounds
right (ROADMAP Task 5.4). This module is that preference, written down.

Every component is explicit and travels on the hit, so a ranking can be argued with:

``authority``
    Where the hit sits on the Product SS15.3 ladder — accepted Evidence, then accepted
    Claim, then accepted structured state, then the parsed corpus, then the citation
    neighbourhood, then an external hint.
``structure``
    Where it sits in its document, read through the intent. Auditing an empirical result
    trusts Results/Experiments sections and table blocks and distrusts the abstract;
    hunting counter-evidence trusts Limitations and Discussion.
``lexical`` / ``semantic``
    The normalized index scores, carried through unchanged so a reader can see how much of
    a rank came from matching words and how much from matching vectors.
``staleness``
    1.0 when the object is marked stale, subtracted. A stale object is still shown — it is
    still the project's state (ADR-008) — but it stops outranking a fresh one.
``independence``
    A bonus for the first hit from each Work, so ten paragraphs of one paper cannot fill a
    result list that a researcher will read as corroboration (Product SS18).

Weights per intent are :data:`RERANK_WEIGHTS`; the final score is their weighted sum.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from research_harness.retrieval.planner import Intent, RetrievalHit
from research_harness.retrieval.structured import Authority, normalize_section

__all__ = [
    "ABSTRACT_SECTIONS",
    "AUTHORITY_SCORES",
    "CONCLUSION_SECTIONS",
    "NEUTRAL_STRUCTURE",
    "RERANK_WEIGHTS",
    "RESULT_SECTIONS",
    "RerankWeights",
    "authority_score",
    "independence_scores",
    "rerank",
    "structure_score",
]


@dataclass(frozen=True, slots=True)
class RerankWeights:
    """Weights of one intent's score. ``staleness`` is subtracted, everything else added."""

    authority: float
    structure: float
    lexical: float
    semantic: float
    staleness: float
    independence: float

    def score(self, components: Mapping[str, float]) -> float:
        """The weighted sum of ``components``, clamped to ``[0, 1]``."""
        total = (
            self.authority * components.get("authority", 0.0)
            + self.structure * components.get("structure", 0.0)
            + self.lexical * components.get("lexical", 0.0)
            + self.semantic * components.get("semantic", 0.0)
            + self.independence * components.get("independence", 0.0)
            - self.staleness * components.get("staleness", 0.0)
        )
        return max(0.0, min(1.0, total))

    def as_dict(self) -> dict[str, float]:
        """The weights by component name, for a response that explains its own ranking."""
        return {
            "authority": self.authority,
            "structure": self.structure,
            "lexical": self.lexical,
            "semantic": self.semantic,
            "staleness": -self.staleness,
            "independence": self.independence,
        }


AUTHORITY_SCORES: Mapping[Authority, float] = {
    Authority.ACCEPTED_EVIDENCE: 1.0,
    Authority.ACCEPTED_CLAIM: 0.88,
    Authority.STRUCTURED_FIELD: 0.55,
    Authority.PARSED_CORPUS: 0.25,
    Authority.CITATION_NEIGHBORHOOD: 0.12,
    Authority.EXTERNAL_HINT: 0.05,
}
"""Accepted evidence outranks an accepted claim outranks structured state outranks prose
(Product SS15.3). The gap between accepted state and the parsed corpus is deliberately the
widest one on the scale: under every intent, ``authority`` weighted by that gap exceeds
what either index can contribute on its own, so a perfect lexical or semantic match on raw
prose cannot by itself displace evidence the researcher already accepted (ADR-006)."""

RESULT_SECTIONS: tuple[str, ...] = (
    "results",
    "experiments",
    "experimental",
    "evaluation",
    "ablation",
    "measurements",
)
CONCLUSION_SECTIONS: tuple[str, ...] = ("limitations", "discussion", "conclusion", "threats")
ABSTRACT_SECTIONS: tuple[str, ...] = (
    "abstract",
    "introduction",
    "related work",
    "background",
    "motivation",
)
NEUTRAL_STRUCTURE = 0.4
"""Structure score for a hit whose placement says nothing either way."""

_ABSTRACT_CAP = 0.2
"""Ceiling applied to a hit that lives in the abstract or introduction when the intent
cares where a statement was made. A paper's abstract is where its claims are strongest and
its evidence is thinnest."""

#: Per-intent structure scores by hit kind. Keys are retrieval unit kinds
#: (`retrieval.units.IndexUnitKind`) plus the structured entities.
_KIND_SCORES: Mapping[Intent, Mapping[str, float]] = {
    Intent.AUDIT_EMPIRICAL_RESULT: {
        "table": 1.0,
        "table_cell": 1.0,
        "caption": 0.7,
        "table_caption": 0.7,
        "figure_caption": 0.6,
        "evidence": 0.6,
        "matrix_cell": 0.6,
        "paragraph": 0.4,
        "section": 0.35,
        "claim": 0.3,
        "work": 0.2,
    },
    Intent.FIND_SUPPORT: {
        "evidence": 0.8,
        "claim": 0.6,
        "table": 0.6,
        "matrix_cell": 0.6,
        "paragraph": 0.5,
        "caption": 0.45,
        "section": 0.4,
        "work": 0.3,
    },
    Intent.FIND_COUNTER_EVIDENCE: {
        "evidence": 0.8,
        "paragraph": 0.6,
        "table": 0.6,
        "claim": 0.5,
        "section": 0.45,
        "caption": 0.4,
        "work": 0.3,
    },
    Intent.EXPLORE: {},
}

#: Per-intent structure scores by section family.
_SECTION_SCORES: Mapping[Intent, Mapping[str, float]] = {
    Intent.AUDIT_EMPIRICAL_RESULT: {"results": 1.0, "conclusion": 0.5, "abstract": 0.15},
    Intent.FIND_SUPPORT: {"results": 0.7, "conclusion": 0.5, "abstract": 0.3},
    Intent.FIND_COUNTER_EVIDENCE: {"results": 0.7, "conclusion": 1.0, "abstract": 0.2},
    Intent.EXPLORE: {"results": 0.55, "conclusion": 0.55, "abstract": 0.45},
}

#: Intents that cap a hit found in the abstract or introduction.
_CAPS_ABSTRACT: frozenset[Intent] = frozenset(
    {Intent.AUDIT_EMPIRICAL_RESULT, Intent.FIND_COUNTER_EVIDENCE}
)

RERANK_WEIGHTS: Mapping[Intent, RerankWeights] = {
    Intent.AUDIT_EMPIRICAL_RESULT: RerankWeights(
        authority=0.42,
        structure=0.30,
        lexical=0.13,
        semantic=0.10,
        staleness=0.25,
        independence=0.05,
    ),
    Intent.FIND_SUPPORT: RerankWeights(
        authority=0.55,
        structure=0.12,
        lexical=0.13,
        semantic=0.15,
        staleness=0.30,
        independence=0.05,
    ),
    Intent.FIND_COUNTER_EVIDENCE: RerankWeights(
        authority=0.35,
        structure=0.25,
        lexical=0.15,
        semantic=0.15,
        staleness=0.20,
        independence=0.10,
    ),
    Intent.EXPLORE: RerankWeights(
        authority=0.45,
        structure=0.15,
        lexical=0.20,
        semantic=0.20,
        staleness=0.15,
        independence=0.05,
    ),
}
"""What each intent is willing to trade.

Two constraints hold for every row, and :mod:`tests.unit.retrieval.test_rerank` checks
them: ``authority`` is never smaller than either index weight, and the authority gap
between accepted Evidence and the parsed corpus is wider than either index weight, so no
single index can promote raw prose over accepted state on its own. Auditing then spends
its remaining weight on ``structure`` (where a number was measured), support-hunting on
``authority`` and ``staleness`` (whether it still holds), counter-evidence hunting on
``independence`` (whose paper it is), and exploration on the indexes."""


def authority_score(authority: Authority) -> float:
    """Ladder position as a score in ``[0, 1]``."""
    return AUTHORITY_SCORES[authority]


def structure_score(kind: str, section_path: Sequence[str], intent: Intent) -> float:
    """How much this document position is worth for ``intent``.

    The kind score and the section score are combined by taking the better of the two — a
    table is a table wherever it sits, and a Results paragraph is a Results paragraph —
    except in the abstract and introduction, where an intent that cares about *where* a
    statement was made caps the result instead.
    """
    kind_score = _KIND_SCORES[intent].get(kind.lower(), NEUTRAL_STRUCTURE)
    family = _section_family(section_path)
    section = _SECTION_SCORES[intent].get(family) if family else None
    if family == "abstract" and intent in _CAPS_ABSTRACT:
        return min(kind_score, _ABSTRACT_CAP)
    if section is None:
        return kind_score
    return max(kind_score, section)


def independence_scores(hits: Sequence[RetrievalHit]) -> list[float]:
    """1.0 for the first hit of each Work, then 0.5, then 0.25; 0.5 when there is no Work.

    Order matters, so this is computed after the provisional ranking: the bonus goes to the
    strongest hit from each paper, not to whichever one happened to be built first.
    """
    seen: dict[str, int] = {}
    scores: list[float] = []
    for hit in hits:
        if hit.work is None:
            scores.append(0.5)
            continue
        key = str(hit.work)
        count = seen.get(key, 0)
        seen[key] = count + 1
        scores.append(1.0 if count == 0 else (0.5 if count == 1 else 0.25))
    return scores


def rerank(hits: Iterable[RetrievalHit], *, intent: Intent) -> list[RetrievalHit]:
    """Score and order ``hits`` for ``intent``, components exposed on every hit.

    Two passes: the first scores everything that depends only on the hit itself, the second
    adds the independence bonus, which depends on the provisional order. Ties break on the
    reference so the same corpus always answers in the same order.
    """
    weights = RERANK_WEIGHTS[intent]
    provisional = [(hit, _base_components(hit, intent)) for hit in hits]
    provisional.sort(key=lambda pair: (-weights.score(pair[1]), pair[0].ref))
    bonuses = independence_scores([hit for hit, _ in provisional])
    ranked = [
        hit.model_copy(
            update={
                "components": {**components, "independence": bonus},
                "score": round(weights.score({**components, "independence": bonus}), 6),
            }
        )
        for (hit, components), bonus in zip(provisional, bonuses, strict=True)
    ]
    ranked.sort(key=lambda hit: (-hit.score, hit.ref))
    return ranked


def _base_components(hit: RetrievalHit, intent: Intent) -> dict[str, float]:
    return {
        **{name: value for name, value in hit.components.items() if name in _CARRIED},
        "authority": authority_score(hit.authority),
        "structure": structure_score(hit.kind, hit.location.section_path, intent),
        "staleness": 1.0 if hit.stale else 0.0,
    }


_CARRIED = frozenset({"lexical", "semantic"})
"""Components produced by the indexes and passed through unchanged."""


def _section_family(section_path: Sequence[str]) -> str | None:
    """Which family of sections this path belongs to, innermost heading first."""
    for segment in reversed(list(section_path)):
        name = normalize_section(segment)
        if not name:
            continue
        for family, prefixes in (
            ("results", RESULT_SECTIONS),
            ("conclusion", CONCLUSION_SECTIONS),
            ("abstract", ABSTRACT_SECTIONS),
        ):
            if any(name.startswith(prefix) for prefix in prefixes):
                return family
    return None

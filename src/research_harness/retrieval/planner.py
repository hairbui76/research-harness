"""The query planner and the shared retrieval vocabulary (Product SS15.2, SS15.3).

A query is classified *before* anything is retrieved, and the plan it produces walks the
authority ladder from the top: accepted Evidence and Claims, then accepted structured
paper state, then the parsed local corpus, then the citation neighbourhood, then external
discovery. Preferring accepted state is the whole point — it is what stops an index from
quietly becoming the project's knowledge model (Product SS43, ADR-006).

Classification is rule-based and carries no model call. That is a deliberate limit: the
planner has to be inspectable and reproducible, a researcher must be able to read why a
question went to FTS rather than to the vector index, and a planner that needed a provider
would make offline retrieval impossible. The four worked examples of Product SS15.2 are the
acceptance criteria:

===================================================  ==========================================
query                                                plan
===================================================  ==========================================
"Which papers use CICIDS2017?"                       structured lookup + lexical search
"Which systems serialize traffic similarly?"         structured filters + semantic search
"Does this paper acknowledge <X> limitations?"       lexical + semantic, Discussion/Limitations
"Which papers challenge C0041?"                      claim graph + citations + semantic
===================================================  ==========================================

The hit and response records live here rather than in `service`, so that `rerank` and
`service` both depend on the vocabulary and never on each other.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.enums import EvidenceStatus
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import ClaimId, WorkId
from research_harness.retrieval.lexical import CONCLUSION_SECTIONS, SynonymTable
from research_harness.retrieval.structured import (
    Authority,
    Location,
    StructuredEntity,
    StructuredQuery,
)

__all__ = [
    "LADDER",
    "METRIC_WORDS",
    "STOP_WORDS",
    "Intent",
    "QueryHints",
    "RetrievalHit",
    "RetrievalMode",
    "RetrievalPlan",
    "RetrievalResponse",
    "identifiers",
    "infer_intent",
    "plan_query",
    "search_terms",
]

logger = logging.getLogger(__name__)


class RetrievalMode(StrEnum):
    """One rung's worth of retrieval work: which indexes a step is allowed to use."""

    STRUCTURED_ONLY = "structured_only"
    FTS_SECTION = "fts_section"
    STRUCTURED_SEMANTIC = "structured_semantic"
    CLAIM_GRAPH_SEMANTIC = "claim_graph_semantic"
    CITATION_NEIGHBORHOOD = "citation_neighborhood"
    EXTERNAL_DISCOVERY = "external_discovery"

    @property
    def reaches(self) -> Authority:
        """The lowest authority this mode can return; what the ladder orders it by."""
        return _MODE_AUTHORITY[self]

    @property
    def rung(self) -> int:
        """Ladder rung of :attr:`reaches`, 1 (accepted state) through 5 (external)."""
        return self.reaches.rung


_MODE_AUTHORITY: dict[RetrievalMode, Authority] = {
    RetrievalMode.STRUCTURED_ONLY: Authority.STRUCTURED_FIELD,
    RetrievalMode.CLAIM_GRAPH_SEMANTIC: Authority.PARSED_CORPUS,
    RetrievalMode.FTS_SECTION: Authority.PARSED_CORPUS,
    RetrievalMode.STRUCTURED_SEMANTIC: Authority.PARSED_CORPUS,
    RetrievalMode.CITATION_NEIGHBORHOOD: Authority.CITATION_NEIGHBORHOOD,
    RetrievalMode.EXTERNAL_DISCOVERY: Authority.EXTERNAL_HINT,
}

LADDER: tuple[RetrievalMode, ...] = (
    RetrievalMode.STRUCTURED_ONLY,
    RetrievalMode.CLAIM_GRAPH_SEMANTIC,
    RetrievalMode.FTS_SECTION,
    RetrievalMode.STRUCTURED_SEMANTIC,
    RetrievalMode.CITATION_NEIGHBORHOOD,
    RetrievalMode.EXTERNAL_DISCOVERY,
)
"""Product SS15.3 as an execution order.

The claim graph sits second because it reaches accepted Evidence and Claims through their
recorded relations — higher authority than any text index — even though it finishes with a
semantic sweep. Lexical search precedes semantic search at the same rung: an exact term
match on the parsed corpus is a stronger answer than a similar-sounding one.
"""


class Intent(StrEnum):
    """What the researcher is doing, which decides how hits are reranked."""

    AUDIT_EMPIRICAL_RESULT = "audit_empirical_result"
    FIND_SUPPORT = "find_support"
    FIND_COUNTER_EVIDENCE = "find_counter_evidence"
    EXPLORE = "explore"


class QueryHints(BaseModel):
    """What the caller already knows, so the planner does not have to guess it.

    Every field overrides the corresponding rule: a CLI that was given ``--mode`` or a
    claim audit that already knows its Claim should not depend on a regular expression
    recovering that fact from prose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    work: WorkId | None = None
    claim: ClaimId | None = None
    entity: StructuredEntity | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    sections: tuple[str, ...] = ()
    modes: tuple[RetrievalMode, ...] = ()
    intent: Intent | None = None
    synonyms: SynonymTable | None = None


class RetrievalPlan(BaseModel):
    """What will be consulted, in what order, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    modes: tuple[RetrievalMode, ...]
    structured: StructuredQuery | None = None
    terms: str | None = None
    sections: tuple[str, ...] = ()
    semantic_query: str | None = None
    claim: ClaimId | None = None
    work: WorkId | None = None
    identifiers: tuple[str, ...] = ()
    """Dataset/metric/model-like tokens lifted out of the query, e.g. ``CICIDS2017``."""

    works_question: bool = False
    """True for "which papers/systems/studies ...", which is answered by a join over
    accepted Evidence rather than by ranking text."""

    intent: Intent = Intent.EXPLORE
    synonyms: SynonymTable | None = None
    rationale: tuple[str, ...] = ()


class RetrievalHit(BaseModel):
    """One retrieval result, with everything needed to judge and reopen it.

    Task 5.4 requires a response to expose source, structural location, authority, and
    score components; a hit that showed only a score would ask the researcher to trust the
    ranking, which is precisely what this product does not do.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str
    """Canonical id (``E0482``, ``C0041``, ``W0017``) or block reference ``B0081@A0017-3``."""

    kind: str
    work: WorkId | None = None
    location: Location = Location()
    authority: Authority
    score: float = 0.0
    components: dict[str, float] = Field(default_factory=dict)
    snippet: str = ""
    provenance: str
    """Which index and mode produced it, e.g. ``structured:evidence`` or ``fts:block``."""

    stale: bool = False

    def merged_with(self, other: RetrievalHit) -> RetrievalHit:
        """The same object found twice: keep the better authority and both provenances."""
        best = self if self.authority.rung <= other.authority.rung else other
        sources = [*self.provenance.split("+"), *other.provenance.split("+")]
        provenance = "+".join(dict.fromkeys(sources))
        components = {**other.components, **self.components}
        for name, value in other.components.items():
            components[name] = max(value, self.components.get(name, value))
        return best.model_copy(
            update={
                "provenance": provenance,
                "components": components,
                "snippet": self.snippet or other.snippet,
                "stale": self.stale or other.stale,
                "location": self.location if self.location.page else other.location,
            }
        )


class RetrievalResponse(BaseModel):
    """The answer: the plan that produced it, the ranked hits, and what was consulted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    plan: RetrievalPlan
    hits: tuple[RetrievalHit, ...] = ()
    rungs_consulted: tuple[RetrievalMode, ...] = ()
    notes: tuple[str, ...] = ()
    """Retrieval-performance remarks only — a missing index, a rung skipped because a
    higher one already answered. Never a statement about scientific state."""


# ------------------------------------------------------------------------- cues

_HARNESS_ID = re.compile(r"\b(?:RQ|SR|[WVABEICDS])\d{4,}(?:-\d+)?\b")
_CLAIM_ID = re.compile(r"\bC\d{4,}\b")
_WORK_ID = re.compile(r"\bW\d{4,}\b")

#: A token carrying both letters and digits: `CICIDS2017`, `F1`, `ImageNet21k`, `GPT4`.
_IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9-]*[A-Za-z])(?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9-]+\b")

_WORKS_QUESTION = re.compile(
    r"\b(which|what|any|list|find|show)\b[^?]*?\b"
    r"(papers?|works?|systems?|studies|study|articles?|authors?|models?|methods?)\b",
    re.IGNORECASE,
)
_MISMATCH = re.compile(
    r"\b(similar\w*|equivalent\w*|analogous|comparable|like|resembl\w*|synonym\w*|"
    r"different (?:terminology|terms|words|wording|names?)|"
    r"other (?:terminology|terms|words|names?)|same (?:idea|concept|thing|approach))\b",
    re.IGNORECASE,
)
_ACKNOWLEDGE = re.compile(
    r"\b(acknowledg\w*|discuss\w*|mention\w*|address(?:es|ed)?|admit\w*|concede\w*|"
    r"caveats?|limitations?|threats? to validity|recogni[sz]\w*)\b",
    re.IGNORECASE,
)
_CHALLENGE = re.compile(
    r"\b(challeng\w*|contradict\w*|counter[- ]?evidence|counters?|counterexamples?|"
    r"refut\w*|disput\w*|rebut\w*|conflict\w*|disagree\w*|undermin\w*|falsif\w*)\b",
    re.IGNORECASE,
)
_SUPPORT = re.compile(
    r"\b(support\w*|corroborat\w*|confirm\w*|back(?:s|ed)? up|evidence for|in favou?r of)\b",
    re.IGNORECASE,
)
_DATASET_CONTEXT = re.compile(
    r"\b(dataset|datasets|benchmark|benchmarks|corpus|corpora|evaluate[sd]?|"
    r"evaluated|trained|use[sd]?|using)\b",
    re.IGNORECASE,
)
_RESULT_CONTEXT = re.compile(
    r"\b(results?|scores?|reports?|reported|measured?|numbers?|tables?|metrics?|"
    r"performance|accuracy|improv\w*|outperform\w*|baselines?)\b",
    re.IGNORECASE,
)

METRIC_WORDS: frozenset[str] = frozenset(
    {
        "f1",
        "f-score",
        "auc",
        "auroc",
        "accuracy",
        "precision",
        "recall",
        "bleu",
        "rouge",
        "map",
        "mrr",
        "perplexity",
        "fpr",
        "tpr",
    }
)
"""Metric names common enough to be worth a structured filter of their own."""

STOP_WORDS: frozenset[str] = frozenset(
    {
        # interrogatives and function words
        "a",
        "about",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "list",
        "not",
        "of",
        "on",
        "or",
        "same",
        "show",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "with",
        "would",
        "you",
        # words that describe the corpus rather than anything inside it
        "article",
        "articles",
        "author",
        "authors",
        "paper",
        "papers",
        "study",
        "studies",
        "work",
        "works",
    }
)
"""Dropped before building the FTS expression. Everything here is either grammar or a word
that names the corpus itself, and both match every document equally."""

_PHRASE = re.compile(r'"([^"]+)"')
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


# ----------------------------------------------------------------------- planning


def search_terms(text: str) -> str:
    """The FTS expression for ``text``: quoted phrases kept, stop words dropped, OR-joined.

    OR rather than AND because a research question is written in the researcher's words
    and the corpus is written in the authors': requiring every word to appear would answer
    almost nothing. ``bm25()`` then does the discriminating, which is what it is for — the
    rare term (``CICIDS2017``) dominates the common one.
    """
    phrases = [phrase.strip() for phrase in _PHRASE.findall(text) if phrase.strip()]
    remainder = _PHRASE.sub(" ", text)
    words = [
        word
        for word in _WORD.findall(remainder)
        if word.lower() not in STOP_WORDS and len(word) > 1
    ]
    parts = [f'"{phrase}"' for phrase in phrases] + words
    return " OR ".join(dict.fromkeys(parts))


def infer_intent(text: str) -> Intent:
    """What the query is for, from its verbs; ties resolve to the more sceptical reading."""
    if _CHALLENGE.search(text):
        return Intent.FIND_COUNTER_EVIDENCE
    if _SUPPORT.search(text):
        return Intent.FIND_SUPPORT
    if _RESULT_CONTEXT.search(text) or _metrics(text):
        return Intent.AUDIT_EMPIRICAL_RESULT
    return Intent.EXPLORE


def plan_query(text: str, *, hints: QueryHints | None = None) -> RetrievalPlan:
    """Classify ``text`` and produce the ladder-ordered plan for it.

    Rules, applied together — a query that fires several gets the union of their modes,
    ordered by :data:`LADDER`:

    * an identifier, a metric name, or "which papers use X" -> structured lookup + FTS;
    * a terminology-mismatch cue ("similar", "different terminology", "like")
      -> structured filters + semantic;
    * "does <paper> acknowledge/discuss ..." -> FTS + semantic, constrained to
      Discussion / Limitations / Conclusion;
    * "challenge/contradict/counter C0041" -> claim graph + citation neighbourhood +
      semantic.

    A query that fires nothing walks the local ladder in order and stops before the
    citation neighbourhood, which is a different question from "what does my corpus say".
    """
    hint = hints or QueryHints()
    claim = hint.claim or _claim_in(text)
    work = hint.work or _work_in(text)
    named = identifiers(text)
    metrics = _metrics(text)
    works_question = bool(_WORKS_QUESTION.search(text))

    modes: set[RetrievalMode] = set()
    rationale: list[str] = []
    sections: list[str] = list(hint.sections)

    if named or metrics or works_question:
        modes |= {RetrievalMode.STRUCTURED_ONLY, RetrievalMode.FTS_SECTION}
        names = ", ".join(named or metrics) or "a corpus-level question"
        rationale.append(
            f"named terms ({names}) are looked up in accepted state and searched exactly"
        )
    if _MISMATCH.search(text):
        modes |= {RetrievalMode.STRUCTURED_ONLY, RetrievalMode.STRUCTURED_SEMANTIC}
        rationale.append(
            "terminology-mismatch cue: structured filters first, then semantic similarity"
        )
    if _ACKNOWLEDGE.search(text):
        modes |= {RetrievalMode.FTS_SECTION, RetrievalMode.STRUCTURED_SEMANTIC}
        sections.extend(CONCLUSION_SECTIONS)
        rationale.append("acknowledgement cue: constrained to " + "/".join(CONCLUSION_SECTIONS))
    if _CHALLENGE.search(text):
        modes |= {
            RetrievalMode.CLAIM_GRAPH_SEMANTIC,
            RetrievalMode.CITATION_NEIGHBORHOOD,
            RetrievalMode.STRUCTURED_SEMANTIC,
        }
        rationale.append(
            "challenge cue: claim/evidence relations, then the citation neighbourhood, "
            "then semantic search"
        )
    if claim is not None and RetrievalMode.CLAIM_GRAPH_SEMANTIC not in modes:
        modes.add(RetrievalMode.CLAIM_GRAPH_SEMANTIC)
        rationale.append(f"{claim} named: its accepted evidence relations are consulted first")
    if not modes:
        modes = {
            RetrievalMode.STRUCTURED_ONLY,
            RetrievalMode.FTS_SECTION,
            RetrievalMode.STRUCTURED_SEMANTIC,
        }
        rationale.append("no classifying cue: the local ladder is walked in order")

    if hint.modes:
        modes = set(hint.modes)
        rationale.append("modes were requested by the caller")

    ordered = tuple(mode for mode in LADDER if mode in modes)
    structured = _structured_query(hint, claim=claim, work=work, identifiers=named, metrics=metrics)
    if structured is not None and RetrievalMode.STRUCTURED_ONLY not in ordered:
        rationale.append("a structural filter is available but no structured rung was planned")
    return RetrievalPlan(
        text=text,
        modes=ordered,
        structured=structured,
        terms=search_terms(text) or None,
        sections=tuple(dict.fromkeys(sections)),
        semantic_query=text.strip() or None,
        claim=claim,
        work=work,
        identifiers=named,
        works_question=works_question,
        intent=hint.intent or infer_intent(text),
        synonyms=hint.synonyms,
        rationale=tuple(rationale),
    )


def _structured_query(
    hint: QueryHints,
    *,
    claim: ClaimId | None,
    work: WorkId | None,
    identifiers: tuple[str, ...],
    metrics: tuple[str, ...],
) -> StructuredQuery | None:
    """The lookup to run at the top rung, or ``None`` when nothing structural was asked.

    A structured query with no filter would return the first page of a table, which looks
    like an answer and is not one; it is better to say the rung had nothing to do.
    """
    if hint.entity is not None:
        return StructuredQuery(entity=hint.entity, filters=dict(hint.filters))
    if claim is not None:
        return StructuredQuery(entity="claim", filters={"id": str(claim)})
    filters: dict[str, str | int | Sequence[str]] = {}
    if identifiers:
        filters["dataset"] = identifiers[0]
    elif metrics:
        filters["metric"] = metrics[0]
    if not filters:
        if work is not None:
            return StructuredQuery(entity="evidence", filters={"work": str(work)})
        return None
    filters["status"] = EvidenceStatus.ACCEPTED.value
    if work is not None:
        filters["work"] = str(work)
    return StructuredQuery(entity="evidence", filters=filters)


def identifiers(text: str) -> tuple[str, ...]:
    """Dataset/model-like tokens (`CICIDS2017`, `F1`), excluding harness ids, first seen first."""
    harness = set(_HARNESS_ID.findall(text))
    found = [
        token
        for token in _IDENTIFIER.findall(text)
        if token not in harness and not _HARNESS_ID.fullmatch(token)
    ]
    return tuple(dict.fromkeys(found))


def _metrics(text: str) -> tuple[str, ...]:
    found = [word for word in _WORD.findall(text) if word.lower() in METRIC_WORDS]
    return tuple(dict.fromkeys(found))


def _claim_in(text: str) -> ClaimId | None:
    return _first_id(_CLAIM_ID.findall(text), ClaimId)


def _work_in(text: str) -> WorkId | None:
    return _first_id(_WORK_ID.findall(text), WorkId)


def _first_id[T: (ClaimId, WorkId)](found: Iterable[str], id_type: type[T]) -> T | None:
    for value in found:
        try:
            return id_type(value)
        except DomainValidationError:  # pragma: no cover - the pattern already matched
            continue
    return None

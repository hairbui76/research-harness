"""Counter-evidence retrieval: look for what would break a claim, and propose nothing else.

A claim audit needs the opposite of a support search. Product SS11 and P5 make the reason
explicit: not finding a contradiction is not the same as there being none, so the search
has to be deliberate, ordered, and honest about what it consulted. This module implements
`research_harness.claims.audit.CounterEvidenceFinder` over the local retrieval service, in
the order Product SS15.3 requires:

1. **the claim's own relations** — Evidence already accepted as `contradicts` or
   `qualifies`. The project has already decided this evidence bears against the claim;
   nothing an index finds outranks that.
2. **structured and lexical search over evidence and blocks**, built from the claim's
   semantics (subject, object, qualifier values) plus negation cues, so a paragraph that
   says "however, performance degrades" is reachable by exact terms.
3. **semantic search** for the same thing worded differently.

Everything it returns is a :class:`~research_harness.claims.audit.RetrievalCandidate`: a
pointer, with no anchor, no acceptance, and no authority. Turning one into Evidence is
extraction followed by human review (ADR-003, ADR-007); this module cannot and must not do
it.
"""

from __future__ import annotations

import logging

from research_harness.claims.audit import (
    DEFAULT_COUNTER_LIMIT,
    CounterEvidenceFinder,
    RetrievalCandidate,
)
from research_harness.domain.claim import Claim
from research_harness.domain.enums import ClaimEvidenceRelationType, EvidenceStatus
from research_harness.retrieval.planner import (
    Intent,
    RetrievalHit,
    RetrievalMode,
    RetrievalPlan,
    identifiers,
    search_terms,
)
from research_harness.retrieval.service import RetrievalService
from research_harness.retrieval.structured import StructuredQuery

__all__ = [
    "COUNTER_RELATIONS",
    "NEGATION_CUES",
    "OVERSAMPLE",
    "RetrievalCounterEvidenceFinder",
    "counter_terms",
    "plan_counter_evidence",
]

logger = logging.getLogger(__name__)

COUNTER_RELATIONS: frozenset[str] = frozenset(
    {
        ClaimEvidenceRelationType.CONTRADICTS.value,
        ClaimEvidenceRelationType.QUALIFIES.value,
    }
)
"""Relations that already bear against a claim (Product SS10.4). `contextualizes` and
`incomparable_under_current_evidence` are deliberately not here: neither says the claim is
wrong, and treating them as counter-evidence would overstate what the record holds."""

NEGATION_CUES: tuple[str, ...] = (
    "however",
    "contrast",
    "contrary",
    "unlike",
    "whereas",
    "although",
    "fails",
    "failed",
    "degrades",
    "degradation",
    "worse",
    "unable",
    "cannot",
    "did not",
    "does not",
    "no improvement",
)
"""Words a paper uses when it is about to disagree. They are cheap OR-terms: `bm25` gives
them little weight on their own, so they raise recall on contradicting prose without
letting "however" alone answer the query."""

OVERSAMPLE = 3
"""How much wider than ``limit`` the ladder walk runs. The service stops early once a rung
has produced enough hits, and a claim with three recorded contradictions should still get a
lexical and semantic sweep — the point of the search is to find what is *not* recorded."""


def counter_terms(claim: Claim) -> str:
    """The lexical query for ``claim``: its semantics, then the negation cues.

    Subject, predicate, object, and qualifier values give the vocabulary the claim is about;
    the cues give the vocabulary disagreement is written in. Both are OR-joined, so a
    paragraph matching several rare claim terms outranks one that merely says "however".
    """
    semantics = claim.semantics
    parts = [
        semantics.subject,
        semantics.predicate,
        semantics.object,
        *(value for _, value in sorted(semantics.qualifier.items())),
    ]
    terms = search_terms(" ".join(parts))
    cues = " OR ".join(f'"{cue}"' if " " in cue else cue for cue in NEGATION_CUES)
    return f"{terms} OR {cues}" if terms else cues


def plan_counter_evidence(claim: Claim, *, limit: int = DEFAULT_COUNTER_LIMIT) -> RetrievalPlan:
    """The plan a counter-evidence search runs: claim graph, then lexical, then semantic.

    The modes are fixed rather than classified. A counter-evidence search is not a question
    somebody typed; it is a fixed procedure the audit is entitled to expect, and a plan
    that varied with wording would make an audit's coverage unreproducible.
    """
    terms = counter_terms(claim)
    named = identifiers(" ".join([claim.semantics.object, *claim.semantics.qualifier.values()]))
    structured = (
        StructuredQuery(
            entity="evidence",
            filters={"status": EvidenceStatus.ACCEPTED.value, "dataset": named[0]},
            limit=max(limit, 1),
        )
        if named
        else None
    )
    modes = [
        RetrievalMode.CLAIM_GRAPH_SEMANTIC,
        RetrievalMode.FTS_SECTION,
        RetrievalMode.STRUCTURED_SEMANTIC,
    ]
    if structured is not None:
        modes.insert(0, RetrievalMode.STRUCTURED_ONLY)
    return RetrievalPlan(
        text=claim.statement,
        modes=tuple(modes),
        structured=structured,
        terms=terms,
        semantic_query=claim.statement,
        claim=claim.id,
        identifiers=named,
        intent=Intent.FIND_COUNTER_EVIDENCE,
        rationale=(
            "counter-evidence: accepted contradicting and qualifying relations first, then "
            "exact search over evidence and blocks using the claim's own terms plus "
            "negation cues, then semantic search for the same thing worded differently",
        ),
    )


class RetrievalCounterEvidenceFinder:
    """`CounterEvidenceFinder` over local retrieval; returns proposals, never Evidence."""

    def __init__(self, service: RetrievalService) -> None:
        self._service = service

    def find_counter_evidence(
        self, claim: Claim, *, limit: int = DEFAULT_COUNTER_LIMIT
    ) -> list[RetrievalCandidate]:
        """Candidates that might bear against ``claim``, strongest first.

        Evidence the claim already records as `supports` is excluded — it is the claim's
        own support, not a challenge to it — and so is the claim itself. Everything else is
        offered for a researcher to look at, including hits the audit will end up
        classifying as `incomparable_under_current_evidence`.
        """
        if limit < 1:
            return []
        plan = plan_counter_evidence(claim, limit=limit)
        response = self._service.search(claim.statement, k=limit * OVERSAMPLE, plan=plan)
        excluded = {str(evidence) for evidence in claim.supporting} | {str(claim.id)}
        candidates = [_candidate(hit) for hit in response.hits if hit.ref not in excluded]
        return candidates[:limit]


def _candidate(hit: RetrievalHit) -> RetrievalCandidate:
    return RetrievalCandidate(
        ref=hit.ref,
        work=hit.work,
        text=hit.snippet,
        score=hit.score,
        source=hit.provenance,
        location=_location(hit),
    )


def _location(hit: RetrievalHit) -> str:
    """Placement in plain words, e.g. ``block B0081, page 3, section 3 Experiments``."""
    location = hit.location
    parts: list[str] = []
    if location.block is not None:
        parts.append(f"block {location.block}")
    if location.page is not None:
        parts.append(f"page {location.page}")
    if location.section_path:
        parts.append("section " + "/".join(location.section_path))
    return ", ".join(parts)


def _assert_protocol(finder: RetrievalCounterEvidenceFinder) -> CounterEvidenceFinder:
    """Static proof that the implementation still satisfies the audit's Protocol."""
    return finder

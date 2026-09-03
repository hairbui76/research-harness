"""Claim scope ladder and maximum-defensible wording (Product 10.2, 10.5, 42.G; ADR-007).

The engine answers one question: what is the strongest wording this evidence and this
search coverage actually defend? It is a pure, deterministic function of accepted
evidence, coverage counts, and the recorded search effort. Model confidence is not an
input and no function here accepts one (Product P6): a model can be certain about a single
paper while the corpus evidence still supports only "among the papers examined".

The ladder is a table (:data:`LEVEL_REQUIREMENTS`) rather than a chain of conditionals so
that a researcher can read what each level demands and an audit can name the exact
requirement that failed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import Field

from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.claim import Claim, Coverage
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    OverturnRisk,
    StaleState,
)
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import EvidenceId, WorkId

__all__ = [
    "ABSENCE_PHRASE",
    "AUTHOR_ORIGINS",
    "CONTRADICTING_RELATIONS",
    "CONTRADICTION_TOLERANCE_DIVISOR",
    "FIELD_WORDING",
    "INDIVIDUAL_WORDING",
    "L2_MIN_EXAMINED_RATIO",
    "L2_MIN_INDEPENDENT_WORKS",
    "L3_ACCEPTABLE_OVERTURN_RISK",
    "L3_MAX_UNRESOLVED_RATIO",
    "L3_MIN_EXAMINED_RATIO",
    "L3_MIN_INDEPENDENT_WORKS",
    "LEVEL_REQUIREMENTS",
    "MAJORITY_RATIO",
    "MAJORITY_WORDING",
    "MIN_SUPPORT",
    "OBSERVED_SUBSET_WORDING",
    "QUALIFYING_RELATIONS",
    "SEVERAL_WORDING",
    "SUPPORTING_RELATIONS",
    "SUPPORT_WEIGHTS",
    "UNIVERSAL_WORDING",
    "EvidenceSummary",
    "LevelRequirement",
    "StrengthAssessment",
    "StrengthFacts",
    "StrengthInput",
    "assess_strength",
    "build_facts",
    "summarize",
    "wording_for",
]

# --- policy constants -------------------------------------------------------

#: Support weight per evidence strength. A derived or indirect reading is worth half a
#: direct one: Product 12 lets abstract- or snippet-only sources establish existence and
#: direction, never a measured value, so they may contribute but never carry a level alone.
SUPPORT_WEIGHTS: Mapping[EvidenceStrength, float] = MappingProxyType(
    {
        EvidenceStrength.DIRECT: 1.0,
        EvidenceStrength.INDIRECT: 0.5,
        EvidenceStrength.DERIVED: 0.5,
    }
)

#: Relations that count as support.
SUPPORTING_RELATIONS: frozenset[ClaimEvidenceRelationType] = frozenset(
    {ClaimEvidenceRelationType.SUPPORTS}
)
#: Relations that count against the claim. `incomparable_under_current_evidence` is
#: deliberately absent: differing outcomes under different conditions are a caveat, not a
#: contradiction (ROADMAP Task 7.4).
CONTRADICTING_RELATIONS: frozenset[ClaimEvidenceRelationType] = frozenset(
    {ClaimEvidenceRelationType.CONTRADICTS}
)
#: Relations that narrow the claim without opposing it.
QUALIFYING_RELATIONS: frozenset[ClaimEvidenceRelationType] = frozenset(
    {
        ClaimEvidenceRelationType.QUALIFIES,
        ClaimEvidenceRelationType.INCOMPARABLE_UNDER_CURRENT_EVIDENCE,
    }
)

#: Origins that report what the authors assert rather than what the source shows. They
#: cannot become a verified experimental result on their own (Product 42.E).
AUTHOR_ORIGINS: frozenset[EvidenceOrigin] = frozenset(
    {EvidenceOrigin.AUTHOR_CLAIMED, EvidenceOrigin.AUTHOR_INTERPRETED}
)

#: Weighted support a claim needs before it says anything at all.
MIN_SUPPORT = 1.0
#: Independent works an L2 corpus-level statement needs.
L2_MIN_INDEPENDENT_WORKS = 3
#: Independent works an L3 field-level statement needs.
L3_MIN_INDEPENDENT_WORKS = 5
#: Share of the relevant corpus that must have been examined for L2 and for L3.
L2_MIN_EXAMINED_RATIO = 0.5
L3_MIN_EXAMINED_RATIO = 0.8
#: Share of the relevant corpus that may remain unresolved at L3.
L3_MAX_UNRESOLVED_RATIO = 0.1
#: At L2, contradictions may not exceed support divided by this.
CONTRADICTION_TOLERANCE_DIVISOR = 3.0
#: Share of the examined corpus above which "most" replaces "several".
MAJORITY_RATIO = 0.5
#: Overturn risks compatible with a field-level generalization.
L3_ACCEPTABLE_OVERTURN_RISK: frozenset[OverturnRisk] = frozenset(
    {OverturnRisk.LOW, OverturnRisk.LOW_MODERATE}
)

# --- wording vocabulary (Product 10.5) --------------------------------------

INDIVIDUAL_WORDING = "in the work examined"
OBSERVED_SUBSET_WORDING = "among the papers examined"
SEVERAL_WORDING = "several existing approaches"
MAJORITY_WORDING = "most systems in the reviewed corpus"
FIELD_WORDING = "existing work generally"
UNIVERSAL_WORDING = "existing work without exception"
#: The only sentence opening an absence claim may use. "No work exists" is never produced.
ABSENCE_PHRASE = "we identified no work that"


# --- inputs -----------------------------------------------------------------


class EvidenceSummary(DomainModel):
    """The facts about one claim-evidence link that the ladder is allowed to look at.

    Everything the engine needs and nothing it must not see: no confidence, no prose, no
    model identity.
    """

    evidence: EvidenceId
    work: WorkId
    origin: EvidenceOrigin
    strength: EvidenceStrength
    evidence_type: EvidenceType
    status: EvidenceStatus
    stale: StaleState
    relation: ClaimEvidenceRelationType
    aspect: str | None = None

    @property
    def counts(self) -> bool:
        """True when the evidence is accepted and fresh, the only state that counts."""
        return self.status is EvidenceStatus.ACCEPTED and self.stale is StaleState.FRESH

    @property
    def weight(self) -> float:
        """Support weight of this evidence; derived and indirect are worth half."""
        return SUPPORT_WEIGHTS[self.strength]


def summarize(claim: Claim, evidence: Mapping[EvidenceId, Evidence]) -> tuple[EvidenceSummary, ...]:
    """Summarize a claim's evidence relations, in declaration order.

    Links whose evidence is not in ``evidence`` are skipped: an unresolvable id cannot
    support anything, and inventing a summary for it would silently inflate support.
    """
    summaries: list[EvidenceSummary] = []
    for link in claim.relations:
        item = evidence.get(link.evidence)
        if item is None:
            continue
        summaries.append(
            EvidenceSummary(
                evidence=item.id,
                work=item.source.work,
                origin=item.origin,
                strength=item.strength,
                evidence_type=item.evidence_type,
                status=item.status,
                stale=item.stale,
                relation=link.relation,
                aspect=link.aspect,
            )
        )
    return tuple(summaries)


class StrengthInput(DomainModel):
    """Everything the ladder may consider. Model confidence is deliberately not a field."""

    claim_type: ClaimType
    requested: ClaimScope
    summaries: tuple[EvidenceSummary, ...] = ()
    coverage: Coverage = Coverage()
    search_runs_recorded: int = Field(default=0, ge=0)
    independent_works: int | None = Field(default=None, ge=0)
    """Override for independent support, e.g. when the auditor merges works that share
    authors, systems, or datasets. Defaults to the distinct supporting Work ids."""
    numeric: bool = False
    """True when the claim rests on measured values (Product 12)."""

    @classmethod
    def from_claim(
        cls,
        claim: Claim,
        evidence: Mapping[EvidenceId, Evidence],
        *,
        search_runs_recorded: int | None = None,
        independent_works: int | None = None,
        numeric: bool | None = None,
    ) -> StrengthInput:
        """Build the input from a claim and the evidence objects it links to.

        ``numeric`` defaults to True when any supporting evidence carries a
        :class:`~research_harness.domain.evidence.NumericValue`, and
        ``search_runs_recorded`` to the number of runs recorded on the claim's coverage.
        """
        summaries = summarize(claim, evidence)
        if numeric is None:
            numeric = any(
                item.content.numeric is not None
                for link in claim.relations
                if link.relation in SUPPORTING_RELATIONS
                for item in (evidence.get(link.evidence),)
                if item is not None
            )
        if search_runs_recorded is None:
            search_runs_recorded = len(claim.coverage.search_runs)
        return cls(
            claim_type=claim.type,
            requested=claim.assessment.requested_strength,
            summaries=summaries,
            coverage=claim.coverage,
            search_runs_recorded=search_runs_recorded,
            independent_works=independent_works,
            numeric=numeric,
        )


# --- derived facts ----------------------------------------------------------


class StrengthFacts(DomainModel):
    """Counts and ratios derived from the input; the only thing requirements read."""

    claim_type: ClaimType
    numeric: bool
    support_count: float = 0.0
    """Weighted support: direct evidence counts 1, derived and indirect count 0.5."""
    direct_support_count: int = 0
    independent_support: int = 0
    contradiction_count: int = 0
    unqualified_contradictions: int = 0
    """Contradictions recorded without an aspect, i.e. against the claim as a whole."""
    qualifier_count: int = 0
    ignored_count: int = 0
    """Linked evidence that is not accepted or is stale, and therefore counts for nothing."""
    coverage: Coverage = Coverage()
    search_runs_recorded: int = 0
    examined_ratio: float = 0.0
    unresolved_ratio: float = 0.0
    support_ratio: float = 0.0
    """Independent supporting works as a share of the examined corpus."""
    notes: tuple[str, ...] = ()
    """Plain-words notes about evidence that was demoted or ignored."""


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    """``numerator / denominator``, falling back to ``empty`` for an empty corpus.

    With no relevant works there is nothing left to examine (``empty=1.0``) and nothing
    unresolved (``empty=0.0``); a non-zero numerator over an empty corpus is incoherent
    coverage and scores 1.0 so it can never look better than a real count.
    """
    if denominator > 0:
        return numerator / denominator
    return empty if numerator == 0 else 1.0


def build_facts(request: StrengthInput) -> StrengthFacts:
    """Reduce the input to the counts the ladder reads. Pure and order-independent."""
    support = 0.0
    direct = 0
    works: set[WorkId] = set()
    contradictions = 0
    unqualified = 0
    qualifiers = 0
    ignored = 0
    notes: list[str] = []

    for summary in request.summaries:
        if not summary.counts:
            ignored += 1
            continue
        if summary.relation in CONTRADICTING_RELATIONS:
            contradictions += 1
            if summary.aspect is None:
                unqualified += 1
            continue
        if summary.relation in QUALIFYING_RELATIONS:
            qualifiers += 1
            continue
        if summary.relation not in SUPPORTING_RELATIONS:
            continue
        if _is_author_report(summary, numeric=request.numeric):
            qualifiers += 1
            notes.append(_author_report_note(summary, numeric=request.numeric))
            continue
        support += summary.weight
        if summary.strength is EvidenceStrength.DIRECT:
            direct += 1
        works.add(summary.work)

    if ignored:
        notes.append(
            f"{_plural(ignored, 'linked evidence object')} are not accepted or are stale "
            "and were not counted"
        )

    coverage = request.coverage
    independent = request.independent_works if request.independent_works is not None else len(works)
    examined_ratio = _ratio(coverage.examined_works, coverage.relevant_works, empty=1.0)
    unresolved_ratio = _ratio(coverage.unresolved_works, coverage.relevant_works, empty=0.0)
    support_ratio = independent / coverage.examined_works if coverage.examined_works else 0.0
    return StrengthFacts(
        claim_type=request.claim_type,
        numeric=request.numeric,
        support_count=support,
        direct_support_count=direct,
        independent_support=independent,
        contradiction_count=contradictions,
        unqualified_contradictions=unqualified,
        qualifier_count=qualifiers,
        ignored_count=ignored,
        coverage=coverage,
        search_runs_recorded=request.search_runs_recorded,
        examined_ratio=examined_ratio,
        unresolved_ratio=unresolved_ratio,
        support_ratio=support_ratio,
        notes=tuple(notes),
    )


def _is_author_report(summary: EvidenceSummary, *, numeric: bool) -> bool:
    """True when the evidence is the authors' own report of a result it cannot establish."""
    if summary.origin not in AUTHOR_ORIGINS:
        return False
    return numeric or summary.evidence_type is EvidenceType.EXPERIMENTAL_RESULT


def _author_report_note(summary: EvidenceSummary, *, numeric: bool) -> str:
    subject = "a measured value" if numeric else "an experimental result"
    return (
        f"{summary.evidence} is {summary.origin.value} and cannot directly support "
        f"{subject}; it was counted as a qualifier (Product 12, 42.E)"
    )


# --- the ladder -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LevelRequirement:
    """One condition a scope level places on evidence, coverage, or the search record."""

    key: str
    requirement: str
    """What the level demands, in plain words, independent of any particular claim."""
    check: Callable[[StrengthFacts], bool]
    explain: Callable[[StrengthFacts], str]
    """Why it failed for these facts, in plain words."""

    def failure(self, facts: StrengthFacts) -> str | None:
        """The failure explanation, or ``None`` when the requirement holds."""
        return None if self.check(facts) else self.explain(facts)


def _percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _plural(count: float, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural if plural is not None else f"{singular}s")
    return f"{count:g} {word}"


LEVEL_REQUIREMENTS: Mapping[ClaimScope, tuple[LevelRequirement, ...]] = MappingProxyType(
    {
        ClaimScope.INDIVIDUAL: (
            LevelRequirement(
                key="l0.support",
                requirement="at least one accepted, non-stale supporting evidence object",
                check=lambda facts: facts.support_count >= MIN_SUPPORT,
                explain=lambda facts: (
                    "no accepted, non-stale evidence supports the claim "
                    f"(weighted support {facts.support_count:g})"
                ),
            ),
        ),
        ClaimScope.OBSERVED_SUBSET: (
            LevelRequirement(
                key="l1.support",
                requirement="at least one accepted, non-stale supporting evidence object",
                check=lambda facts: facts.support_count >= MIN_SUPPORT,
                explain=lambda facts: (
                    "a statement about the papers examined still needs accepted supporting "
                    f"evidence (weighted support {facts.support_count:g})"
                ),
            ),
        ),
        ClaimScope.CORPUS_PATTERN: (
            LevelRequirement(
                key="l2.independent_support",
                requirement=f"at least {L2_MIN_INDEPENDENT_WORKS} independent supporting works",
                check=lambda facts: facts.independent_support >= L2_MIN_INDEPENDENT_WORKS,
                explain=lambda facts: (
                    f"a corpus-level pattern needs {L2_MIN_INDEPENDENT_WORKS} independent "
                    f"supporting works; {facts.independent_support} were counted"
                ),
            ),
            LevelRequirement(
                key="l2.relevant_works",
                requirement="a coverage record with at least one relevant work",
                check=lambda facts: facts.coverage.relevant_works > 0,
                explain=lambda _facts: (
                    "the coverage record names no relevant works, so there is no corpus to "
                    "generalize over"
                ),
            ),
            LevelRequirement(
                key="l2.examined_ratio",
                requirement=(
                    f"at least {_percent(L2_MIN_EXAMINED_RATIO)} of the relevant works examined"
                ),
                check=lambda facts: facts.examined_ratio >= L2_MIN_EXAMINED_RATIO,
                explain=lambda facts: (
                    f"only {facts.coverage.examined_works} of "
                    f"{facts.coverage.relevant_works} relevant works were examined "
                    f"({_percent(facts.examined_ratio)}), below the "
                    f"{_percent(L2_MIN_EXAMINED_RATIO)} a corpus-level claim needs"
                ),
            ),
            LevelRequirement(
                key="l2.contradictions",
                requirement=(
                    "contradictions no greater than support divided by "
                    f"{CONTRADICTION_TOLERANCE_DIVISOR:g}"
                ),
                check=lambda facts: (
                    facts.contradiction_count
                    <= facts.support_count / CONTRADICTION_TOLERANCE_DIVISOR
                ),
                explain=lambda facts: (
                    f"{_plural(facts.contradiction_count, 'contradiction')} against weighted "
                    f"support {facts.support_count:g} is too much disagreement for a "
                    "corpus-level claim"
                ),
            ),
        ),
        ClaimScope.FIELD_GENERALIZATION: (
            LevelRequirement(
                key="l3.independent_support",
                requirement=f"at least {L3_MIN_INDEPENDENT_WORKS} independent supporting works",
                check=lambda facts: facts.independent_support >= L3_MIN_INDEPENDENT_WORKS,
                explain=lambda facts: (
                    f"a field-level generalization needs {L3_MIN_INDEPENDENT_WORKS} "
                    f"independent supporting works; {facts.independent_support} were counted"
                ),
            ),
            LevelRequirement(
                key="l3.examined_ratio",
                requirement=(
                    f"at least {_percent(L3_MIN_EXAMINED_RATIO)} of the relevant works examined"
                ),
                check=lambda facts: facts.examined_ratio >= L3_MIN_EXAMINED_RATIO,
                explain=lambda facts: (
                    f"{_percent(facts.examined_ratio)} of the relevant works were examined, "
                    f"below the {_percent(L3_MIN_EXAMINED_RATIO)} a field-level claim needs"
                ),
            ),
            LevelRequirement(
                key="l3.unresolved_ratio",
                requirement=(
                    f"at most {_percent(L3_MAX_UNRESOLVED_RATIO)} of the relevant works unresolved"
                ),
                check=lambda facts: facts.unresolved_ratio <= L3_MAX_UNRESOLVED_RATIO,
                explain=lambda facts: (
                    f"{facts.coverage.unresolved_works} of "
                    f"{facts.coverage.relevant_works} relevant works are unresolved "
                    f"({_percent(facts.unresolved_ratio)}), above the "
                    f"{_percent(L3_MAX_UNRESOLVED_RATIO)} a field-level claim allows"
                ),
            ),
            LevelRequirement(
                key="l3.overturn_risk",
                requirement="an estimated overturn risk of low or low_moderate",
                check=lambda facts: facts.coverage.overturn_risk in L3_ACCEPTABLE_OVERTURN_RISK,
                explain=lambda facts: (
                    f"the estimated overturn risk is {facts.coverage.overturn_risk.value}; a "
                    "field-level claim needs low or low_moderate"
                ),
            ),
            LevelRequirement(
                key="l3.search_runs",
                requirement="at least one recorded search run",
                check=lambda facts: facts.search_runs_recorded >= 1,
                explain=lambda _facts: (
                    "no search run is recorded, so the corpus behind the generalization is "
                    "not reproducible"
                ),
            ),
            LevelRequirement(
                key="l3.unqualified_contradiction",
                requirement="no contradiction against the claim as a whole",
                check=lambda facts: facts.unqualified_contradictions == 0,
                explain=lambda facts: (
                    f"{_plural(facts.unqualified_contradictions, 'contradiction')} apply to the "
                    "claim as a whole rather than to a named aspect"
                ),
            ),
        ),
        ClaimScope.UNIVERSAL_OR_ABSENCE: (
            LevelRequirement(
                key="l4.overturn_risk",
                requirement="an estimated overturn risk of low",
                check=lambda facts: facts.coverage.overturn_risk is OverturnRisk.LOW,
                explain=lambda facts: (
                    f"the estimated overturn risk is {facts.coverage.overturn_risk.value}; "
                    "universal or absence wording needs low"
                ),
            ),
            LevelRequirement(
                key="l4.unresolved",
                requirement="no unresolved relevant works",
                check=lambda facts: facts.coverage.unresolved_works == 0,
                explain=lambda facts: (
                    f"{_plural(facts.coverage.unresolved_works, 'relevant work')} are "
                    "unresolved; a universal or absence statement cannot leave any"
                ),
            ),
            LevelRequirement(
                key="l4.cutoff",
                requirement="a publication cutoff on the coverage record",
                check=lambda facts: facts.coverage.cutoff is not None,
                explain=lambda _facts: (
                    "the coverage record has no publication cutoff, so the claim has no "
                    "honest boundary in time"
                ),
            ),
            LevelRequirement(
                key="l4.absence_search_run",
                requirement="at least one recorded search run behind an absence claim",
                check=lambda facts: (
                    facts.claim_type is not ClaimType.ABSENCE or facts.search_runs_recorded >= 1
                ),
                explain=lambda _facts: (
                    "an absence claim needs at least one recorded search run; a partial, "
                    "unrecorded search can never show that no work exists"
                ),
            ),
        ),
    }
)


# --- wording ----------------------------------------------------------------


def wording_for(level: ClaimScope, claim_type: ClaimType, coverage: Coverage, ratio: float) -> str:
    """Maximum defensible wording for a level (Product 10.5).

    Absence claims always get the hedged "we identified no work that ..." form, at every
    level and with whatever scope and cutoff the coverage record supports. The unqualified
    "no work exists" is not in this module's vocabulary.
    """
    if claim_type is ClaimType.ABSENCE:
        return _absence_wording(coverage)
    if level is ClaimScope.INDIVIDUAL:
        return INDIVIDUAL_WORDING
    if level is ClaimScope.OBSERVED_SUBSET:
        return OBSERVED_SUBSET_WORDING
    if level is ClaimScope.CORPUS_PATTERN:
        return MAJORITY_WORDING if ratio >= MAJORITY_RATIO else SEVERAL_WORDING
    if level is ClaimScope.FIELD_GENERALIZATION:
        return FIELD_WORDING
    return UNIVERSAL_WORDING


def _absence_wording(coverage: Coverage) -> str:
    scope = "within the reviewed corpus"
    if coverage.cutoff is not None:
        scope = f"{scope} up to {coverage.cutoff.isoformat()}"
    return f"{scope}, {ABSENCE_PHRASE} ..."


# --- assessment -------------------------------------------------------------


class StrengthAssessment(DomainModel):
    """What the evidence allows, how to word it, and why anything stronger was refused."""

    requested: ClaimScope
    allowed: ClaimScope
    wording: NonEmptyStr
    status: ClaimStatus
    reasons: tuple[str, ...] = ()
    """Plain-words explanation of every failed requirement between allowed and requested."""
    blocked_by: tuple[str, ...] = ()
    """Keys of the failed requirements, e.g. ``l3.independent_support``."""
    support_count: float = 0.0
    independent_support: int = 0
    contradiction_count: int = 0
    qualifier_count: int = 0
    support_ratio: float = 0.0

    @property
    def escalated(self) -> bool:
        """True when the researcher asked for more than the evidence allows."""
        return self.allowed < self.requested


def _status_for(facts: StrengthFacts, *, allowed: ClaimScope, requested: ClaimScope) -> ClaimStatus:
    if facts.support_count <= 0:
        return ClaimStatus.UNSUPPORTED
    if facts.contradiction_count >= facts.support_count:
        return ClaimStatus.CONTESTED
    if allowed < requested or facts.qualifier_count > 0 or facts.contradiction_count > 0:
        return ClaimStatus.QUALIFIED
    return ClaimStatus.SUPPORTED


def assess_strength(request: StrengthInput) -> StrengthAssessment:
    """Audit a claim's requested scope against the evidence and coverage it actually has.

    ``allowed`` is the highest ladder level whose requirements hold at that level *and at
    every level below it*, capped by the requested scope: an audit lowers strength and
    never raises it (Product 42.G). When even L0 fails, the ladder floor L0 is reported
    with status ``unsupported``; there is no scope below it.
    """
    facts = build_facts(request)
    failures: dict[ClaimScope, tuple[LevelRequirement, ...]] = {}
    for level in range(len(ClaimScope)):
        scope = ClaimScope.from_level(level)
        failures[scope] = tuple(item for item in LEVEL_REQUIREMENTS[scope] if not item.check(facts))

    attained: int | None = None
    for level in range(len(ClaimScope)):
        if failures[ClaimScope.from_level(level)]:
            break
        attained = level

    allowed = min(request.requested, ClaimScope.from_level(attained if attained is not None else 0))

    reasons = list(facts.notes)
    blocked: list[str] = []
    first_failed = 0 if attained is None else attained + 1
    for level in range(first_failed, request.requested.level + 1):
        scope = ClaimScope.from_level(level)
        for item in failures[scope]:
            reasons.append(f"{scope.label}: {item.explain(facts)}")
            blocked.append(item.key)

    return StrengthAssessment(
        requested=request.requested,
        allowed=allowed,
        wording=wording_for(allowed, request.claim_type, facts.coverage, facts.support_ratio),
        status=_status_for(facts, allowed=allowed, requested=request.requested),
        reasons=tuple(reasons),
        blocked_by=tuple(blocked),
        support_count=facts.support_count,
        independent_support=facts.independent_support,
        contradiction_count=facts.contradiction_count,
        qualifier_count=facts.qualifier_count,
        support_ratio=facts.support_ratio,
    )

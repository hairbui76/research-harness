"""Negative-evidence discipline: absence states and the audited road to `absent`.

Product 11 and principle P5: `not_found`, `not_reported`, `not_applicable`, `unclear`, and
`absent` are five different things, and a missing keyword is none of them but the first.
Product 42.F and ADR-007: `not_reported` becomes `absent` only through an explicit review
path carrying a human actor, an accepted `Decision`, and recorded search coverage.

Nothing in this module can produce `absent` by itself. :func:`classify_absence` reads a
search effort and returns the weakest honest state; :func:`check_promotion` says whether an
audited promotion is permitted and why not; :func:`promote_absence` delegates the object
change to :func:`research_harness.domain.transitions.promote_negative_state`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from pydantic import Field

from research_harness.claims.strength import ABSENCE_PHRASE
from research_harness.domain.base import DomainModel
from research_harness.domain.claim import ClaimScopeSpec, Coverage
from research_harness.domain.enums import DecisionStatus, NegativeEvidenceState
from research_harness.domain.errors import (
    AuthorityError,
    DomainValidationError,
    TransitionError,
)
from research_harness.domain.evidence import Evidence
from research_harness.domain.research import Decision, SearchRun
from research_harness.domain.transitions import (
    is_human_actor,
    negative_state_from_search,
    promote_negative_state,
)

__all__ = [
    "BROAD_EFFORT_REQUIREMENTS",
    "PromotionCheck",
    "SearchEffort",
    "absence_wording",
    "check_promotion",
    "classify_absence",
    "promote_absence",
]

#: What a search must cover before "not found" may become "the paper does not report it"
#: (Product 11). Supplementary material is searched when available and strengthens the
#: result, but a paper without supplementary material must not be blocked by its absence.
BROAD_EFFORT_REQUIREMENTS: tuple[str, ...] = (
    "relevant sections",
    "tables",
    "synonyms and semantic variants",
    "structured paper fields",
)


class SearchEffort(DomainModel):
    """What was actually searched inside one work, and what it returned.

    The effort is the evidence for the absence state: a state is never stronger than the
    search that produced it.
    """

    sections_searched: tuple[str, ...] = ()
    tables_searched: bool = False
    supplementary_searched: bool = False
    synonyms: tuple[str, ...] = ()
    structured_fields_checked: tuple[str, ...] = ()
    lexical_hits: int = Field(default=0, ge=0)
    semantic_hits: int = Field(default=0, ge=0)

    @property
    def hits(self) -> int:
        """Total lexical and semantic hits; any hit means something must be read."""
        return self.lexical_hits + self.semantic_hits

    @property
    def searched(self) -> bool:
        """True when any real search happened; nothing searched is not a negative result."""
        return bool(
            self.sections_searched
            or self.tables_searched
            or self.supplementary_searched
            or self.synonyms
            or self.structured_fields_checked
        )

    @property
    def is_broad(self) -> bool:
        """True when sections, tables, synonyms, and structured fields were all covered."""
        return bool(
            self.sections_searched
            and self.tables_searched
            and self.synonyms
            and self.structured_fields_checked
        )

    @property
    def gaps(self) -> tuple[str, ...]:
        """The broad-effort requirements this search did not meet."""
        covered = (
            bool(self.sections_searched),
            self.tables_searched,
            bool(self.synonyms),
            bool(self.structured_fields_checked),
        )
        return tuple(
            name for name, done in zip(BROAD_EFFORT_REQUIREMENTS, covered, strict=True) if not done
        )


def classify_absence(effort: SearchEffort) -> NegativeEvidenceState:
    """The weakest honest absence state for a search effort. Never returns `absent`.

    Any hit means the passage still has to be read, so the state is `unclear` rather than
    any flavour of absence. Zero hits from a search that covered nothing is also `unclear`.
    Zero hits from a real but narrow search is `not_found`; zero hits after sections,
    tables, synonyms, and structured fields have all been covered is `not_reported`.
    """
    if effort.hits > 0:
        return NegativeEvidenceState.UNCLEAR
    state = negative_state_from_search(0, exhaustive=effort.searched)
    if state is NegativeEvidenceState.NOT_FOUND and effort.is_broad:
        return NegativeEvidenceState.NOT_REPORTED
    return state


class PromotionCheck(DomainModel):
    """Whether an audited promotion to `absent` is permitted, and every reason it is not."""

    allowed: bool
    reasons: tuple[str, ...] = ()


def check_promotion(
    from_state: NegativeEvidenceState,
    to_state: NegativeEvidenceState,
    *,
    decision: Decision | None,
    actor: str,
    coverage: Coverage | None,
    search_runs_recorded: int,
) -> PromotionCheck:
    """Policy gate for `not_reported` -> `absent` (Product 42.F).

    Only `not_reported` may be promoted, and only with a human actor, an accepted
    `Decision`, and coverage carrying a publication cutoff and at least one recorded search
    run. `not_found` must first become `not_reported` through a broader search; `unclear`
    and `not_applicable` never promote at all. Every failing condition is reported, not
    just the first, so the researcher sees the whole gap in one pass.
    """
    if to_state is not NegativeEvidenceState.ABSENT:
        return PromotionCheck(
            allowed=False,
            reasons=(
                f"only promotion to 'absent' is audited; '{to_state.value}' is recorded by "
                "the search that produced it",
            ),
        )
    if from_state is NegativeEvidenceState.NOT_FOUND:
        return PromotionCheck(
            allowed=False,
            reasons=(
                "'not_found' is a missing lexical hit, not an absence: broaden the search "
                "across sections, tables, synonyms, and structured fields until it is "
                "'not_reported' before auditing it to 'absent'",
            ),
        )
    if from_state is not NegativeEvidenceState.NOT_REPORTED:
        return PromotionCheck(
            allowed=False,
            reasons=(f"'{from_state.value}' can never be promoted to 'absent'",),
        )

    reasons: list[str] = []
    if not is_human_actor(actor):
        reasons.append(f"promotion to 'absent' requires a human actor, not {actor!r}")
    if decision is None:
        reasons.append("promotion to 'absent' requires a Decision recording the rationale")
    elif decision.status is not DecisionStatus.ACCEPTED:
        reasons.append(
            f"decision {decision.id} is {decision.status.value}; it must be accepted before "
            "it authorises an absence conclusion"
        )
    if coverage is None:
        reasons.append("promotion to 'absent' requires a coverage record")
    elif coverage.cutoff is None:
        reasons.append("the coverage record has no publication cutoff")
    if search_runs_recorded < 1:
        reasons.append(
            "no search run is recorded; a partial, unrecorded search can never establish absence"
        )
    return PromotionCheck(allowed=not reasons, reasons=tuple(reasons))


def promote_absence(
    evidence: Evidence,
    *,
    decision: Decision,
    actor: str,
    coverage: Coverage,
    search_runs_recorded: int | None = None,
    rationale: str | None = None,
) -> Evidence:
    """Promote `not_reported` evidence to `absent` once the audited path is satisfied.

    The policy check lives here; the object change is delegated to
    :func:`research_harness.domain.transitions.promote_negative_state`, which records the
    authorising decision on the evidence. ``search_runs_recorded`` defaults to the number
    of runs on ``coverage``.
    """
    state = evidence.content.negative_state
    if state is None:
        raise TransitionError(f"{evidence.id} does not record a negative state")
    recorded = len(coverage.search_runs) if search_runs_recorded is None else search_runs_recorded
    check = check_promotion(
        state,
        NegativeEvidenceState.ABSENT,
        decision=decision,
        actor=actor,
        coverage=coverage,
        search_runs_recorded=recorded,
    )
    if not check.allowed:
        message = "; ".join(check.reasons)
        if not is_human_actor(actor):
            raise AuthorityError(message)
        raise TransitionError(message)
    return promote_negative_state(
        evidence,
        to_state=NegativeEvidenceState.ABSENT,
        actor=actor,
        decision=decision.id,
        rationale=rationale or decision.rationale,
    )


def absence_wording(
    scope: ClaimScopeSpec, coverage: Coverage, search_runs: Sequence[SearchRun]
) -> str:
    """The only sentence an absence claim may open with (Product 10.5, ROADMAP 12.5).

    The result names the corpus, the cutoff, and the size of the search behind it, so the
    reader can see what "no work" was measured against. Without recorded search runs there
    is nothing honest to say and the call raises.
    """
    if not coverage.search_runs or not search_runs:
        raise DomainValidationError("absence wording requires recorded search coverage")
    corpus = f"the {scope.corpus} corpus" if scope.corpus else "the reviewed corpus"
    sources = {source for run in search_runs for source in run.sources}
    queries = {query for run in search_runs for query in run.queries}
    return (
        f"Within {corpus} up to {_cutoff_label(scope, coverage, search_runs)} "
        f"({_plural(len(sources), 'source')}, {_plural(len(queries), 'query', 'queries')} "
        f"across {_plural(len(search_runs), 'recorded search run')}), {ABSENCE_PHRASE} ..."
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural if plural is not None else f"{singular}s")
    return f"{count} {word}"


def _cutoff_label(
    scope: ClaimScopeSpec, coverage: Coverage, search_runs: Sequence[SearchRun]
) -> str:
    """The most authoritative cutoff available: claim scope, coverage, then the runs."""
    if scope.publication_until is not None:
        return scope.publication_until
    if coverage.cutoff is not None:
        return coverage.cutoff.isoformat()
    run_cutoffs = [run.cutoff for run in search_runs if run.cutoff is not None]
    if run_cutoffs:
        return max(run_cutoffs).isoformat()
    executed: list[date] = [run.executed_at.date() for run in search_runs]
    return max(executed).isoformat()

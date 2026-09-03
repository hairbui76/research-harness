"""Search coverage, overturn risk, and the guards that stand in front of absence claims.

Product 18 and ROADMAP 12.4/12.5. Coverage is what separates "we identified no work
that ..." from "no work exists": a defined universe, a cutoff, the discovery funnel, and
an honest account of what the search could not finish.

Every function here is deterministic. :func:`estimate_overturn_risk` is a fixed table over
the funnel ratios, the number of sources, and the failures recorded on the search runs, so
two researchers reading the same record get the same risk. :func:`absence_permitted` and
:func:`matrix_cell_absence_guard` are the two places the product refuses to turn silence
into a finding: an empty synthesis cell means "not recorded", and model agreement is not
evidence of anything (Product 42.F, ROADMAP 12.5).
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Sequence
from datetime import date

from pydantic import model_validator

from research_harness.domain.base import DomainModel, NonEmptyStr, YearMonth
from research_harness.domain.claim import Coverage
from research_harness.domain.enums import OverturnRisk
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import SearchRunId
from research_harness.domain.research import SearchRun

__all__ = [
    "HIGH_UNRESOLVED_RATIO",
    "LOW_EXAMINED_RATIO",
    "LOW_MODERATE_EXAMINED_RATIO",
    "MIN_EXAMINED_RATIO",
    "MIN_INDEPENDENT_SOURCES",
    "MODERATE_UNRESOLVED_RATIO",
    "UNSAFE_ABSENCE_RISK",
    "CoverageLedger",
    "CoverageReport",
    "CoverageUniverse",
    "absence_permitted",
    "build_coverage_report",
    "compute_coverage",
    "estimate_overturn_risk",
    "incomplete_runs",
    "matrix_cell_absence_guard",
    "parse_cutoff",
    "run_is_incomplete",
    "searched_sources",
    "uncompleted_sources",
]

#: Unresolved share above which a claim is one identification away from being wrong.
HIGH_UNRESOLVED_RATIO = 0.25
#: Unresolved share above which the risk is at least moderate.
MODERATE_UNRESOLVED_RATIO = 0.1
#: Examined share below which the corpus is barely read.
MIN_EXAMINED_RATIO = 0.5
#: Examined share needed before the risk can drop below moderate.
LOW_MODERATE_EXAMINED_RATIO = 0.8
#: Examined share needed for the lowest risk.
LOW_EXAMINED_RATIO = 0.95
#: One source is one source's blind spots.
MIN_INDEPENDENT_SOURCES = 2
#: Risks under which no absence claim is permitted.
UNSAFE_ABSENCE_RISK: frozenset[OverturnRisk] = frozenset({OverturnRisk.HIGH, OverturnRisk.UNKNOWN})

_YEAR_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_cutoff(value: str | date) -> date:
    """Resolve a coverage cutoff to a date.

    ``YYYY-MM`` resolves to the last day of that month, because "published up to 2026-08"
    includes all of August. ``YYYY-MM-DD`` is taken as written.
    """
    if isinstance(value, date):
        return value
    text = value.strip()
    match = _YEAR_MONTH.match(text)
    if match is not None:
        year, month = int(match.group(1)), int(match.group(2))
        return date(year, month, calendar.monthrange(year, month)[1])
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise DomainValidationError(
            f"coverage cutoff must be YYYY-MM or YYYY-MM-DD, got {value!r}"
        ) from error


class CoverageUniverse(DomainModel):
    """The corpus a coverage claim is measured against: what, until when, from where."""

    definition: NonEmptyStr
    cutoff: YearMonth | str
    """``YYYY-MM`` (preferred, as in `ClaimScopeSpec.publication_until`) or ``YYYY-MM-DD``."""
    sources: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _cutoff_is_a_date(self) -> CoverageUniverse:
        parse_cutoff(self.cutoff)
        return self

    @property
    def cutoff_date(self) -> date:
        """The cutoff as a date; ``YYYY-MM`` ends on the last day of the month."""
        return parse_cutoff(self.cutoff)


class CoverageLedger(DomainModel):
    """The discovery funnel by work id or candidate key (Product 18).

    The sets nest: screened come from discovered, relevant from screened, and full text,
    examined, and unresolved are all subsets of relevant. Enforcing the funnel is what
    makes examined/relevant and unresolved/relevant meaningful ratios rather than two
    numbers that happen to divide.
    """

    discovered: frozenset[str] = frozenset()
    screened: frozenset[str] = frozenset()
    relevant: frozenset[str] = frozenset()
    full_text_available: frozenset[str] = frozenset()
    examined: frozenset[str] = frozenset()
    unresolved: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def _funnel_nests(self) -> CoverageLedger:
        for name, subset, container in (
            ("screened", self.screened, self.discovered),
            ("relevant", self.relevant, self.screened),
            ("full_text_available", self.full_text_available, self.relevant),
            ("examined", self.examined, self.relevant),
            ("unresolved", self.unresolved, self.relevant),
        ):
            extra = sorted(subset - container)
            if extra:
                raise ValueError(f"{name} works are outside the previous funnel stage: {extra}")
        return self

    @property
    def examined_ratio(self) -> float:
        """Share of the relevant corpus that was examined; 1.0 when nothing is relevant."""
        if not self.relevant:
            return 1.0
        return len(self.examined) / len(self.relevant)

    @property
    def unresolved_ratio(self) -> float:
        """Share of the relevant corpus still unresolved; 0.0 when nothing is relevant."""
        if not self.relevant:
            return 0.0
        return len(self.unresolved) / len(self.relevant)

    @property
    def unexamined(self) -> frozenset[str]:
        """Relevant works nobody has read yet."""
        return self.relevant - self.examined


def run_is_incomplete(run: SearchRun) -> bool:
    """True when a run stopped early: an incomplete failure or a source left paging."""
    return any(failure.incomplete for failure in run.failures) or any(
        not cursor.exhausted for cursor in run.cursors
    )


def incomplete_runs(search_runs: Sequence[SearchRun]) -> tuple[SearchRunId, ...]:
    """Ids of the runs that stopped before their sources were exhausted."""
    return tuple(run.id for run in search_runs if run_is_incomplete(run))


def searched_sources(search_runs: Sequence[SearchRun]) -> tuple[str, ...]:
    """Distinct sources named by the recorded runs, sorted."""
    return tuple(sorted({source for run in search_runs for source in run.sources}))


def uncompleted_sources(search_runs: Sequence[SearchRun]) -> tuple[str, ...]:
    """Sources that failed or stopped paging in some run and were never completed in another.

    A rerun that finishes the same source repairs the gap; nothing else does.
    """
    gaps: set[str] = set()
    completed: set[str] = set()
    for run in search_runs:
        failed = {failure.source for failure in run.failures}
        stopped = {cursor.source for cursor in run.cursors if not cursor.exhausted}
        gaps |= failed | stopped
        completed |= {
            source for source in run.sources if source not in failed and source not in stopped
        }
    return tuple(sorted(gaps - completed))


def estimate_overturn_risk(
    ledger: CoverageLedger, search_runs: Sequence[SearchRun], universe: CoverageUniverse
) -> OverturnRisk:
    """Deterministic overturn-risk estimate from the funnel and the search record.

    ``unknown`` without a recorded run; ``high`` when too much is unresolved, too little
    read, or a source was never finished; ``moderate`` when the corpus is thin, single
    sourced, or a declared source was never searched; ``low`` only for a near-complete,
    multi-source, fully resolved corpus.
    """
    if not search_runs:
        return OverturnRisk.UNKNOWN
    examined = ledger.examined_ratio
    unresolved = ledger.unresolved_ratio
    sources = searched_sources(search_runs)
    unsearched = tuple(source for source in universe.sources if source not in sources)
    if (
        unresolved > HIGH_UNRESOLVED_RATIO
        or examined < MIN_EXAMINED_RATIO
        or incomplete_runs(search_runs)
        or uncompleted_sources(search_runs)
    ):
        return OverturnRisk.HIGH
    if (
        unresolved > MODERATE_UNRESOLVED_RATIO
        or examined < LOW_MODERATE_EXAMINED_RATIO
        or len(sources) < MIN_INDEPENDENT_SOURCES
        or unsearched
    ):
        return OverturnRisk.MODERATE
    if examined >= LOW_EXAMINED_RATIO and not ledger.unresolved:
        return OverturnRisk.LOW
    return OverturnRisk.LOW_MODERATE


def compute_coverage(
    universe: CoverageUniverse, ledger: CoverageLedger, search_runs: Sequence[SearchRun]
) -> Coverage:
    """Build the canonical :class:`Coverage` a claim carries, with its overturn risk."""
    run_ids: list[SearchRunId] = []
    for run in search_runs:
        if run.id not in run_ids:
            run_ids.append(run.id)
    return Coverage(
        relevant_works=len(ledger.relevant),
        examined_works=len(ledger.examined),
        unresolved_works=len(ledger.unresolved),
        overturn_risk=estimate_overturn_risk(ledger, search_runs, universe),
        search_runs=tuple(run_ids),
        cutoff=universe.cutoff_date,
    )


class CoverageReport(DomainModel):
    """Coverage plus the universe and ledger it came from, and what is still missing."""

    coverage: Coverage
    universe: CoverageUniverse
    ledger: CoverageLedger
    notes: tuple[str, ...] = ()


def build_coverage_report(
    universe: CoverageUniverse, ledger: CoverageLedger, search_runs: Sequence[SearchRun]
) -> CoverageReport:
    """Compute coverage and say, in plain words, what would move the overturn risk."""
    coverage = compute_coverage(universe, ledger, search_runs)
    notes: list[str] = []
    if not search_runs:
        notes.append("no search run is recorded, so coverage cannot be reproduced")
    if ledger.unexamined:
        notes.append(f"{len(ledger.unexamined)} relevant works have not been examined")
    if ledger.unresolved:
        notes.append(f"{len(ledger.unresolved)} relevant works are unresolved")
    missing_full_text = ledger.relevant - ledger.full_text_available
    if missing_full_text:
        notes.append(
            f"{len(missing_full_text)} relevant works have no full text, so only existence "
            "or direction can be read from them (Product 12)"
        )
    stalled = incomplete_runs(search_runs)
    if stalled:
        notes.append(f"search runs stopped before exhausting their sources: {', '.join(stalled)}")
    gaps = uncompleted_sources(search_runs)
    if gaps:
        notes.append(f"sources never completed by any run: {', '.join(gaps)}")
    sources = searched_sources(search_runs)
    unsearched = tuple(source for source in universe.sources if source not in sources)
    if unsearched:
        notes.append(f"declared sources never searched: {', '.join(unsearched)}")
    if len(sources) < MIN_INDEPENDENT_SOURCES:
        notes.append(
            f"{len(sources)} source(s) searched; a single source's blind spots become the "
            "claim's blind spots"
        )
    return CoverageReport(coverage=coverage, universe=universe, ledger=ledger, notes=tuple(notes))


def absence_permitted(
    coverage: Coverage, search_runs: Sequence[SearchRun]
) -> tuple[bool, tuple[str, ...]]:
    """Whether the record supports an absence claim at all, and every reason it does not.

    Refused when no search run is recorded, when a run stopped early and no rerun finished
    it, or when the overturn risk is high or unknown. Passing this check licenses the
    hedged "we identified no work that ..." wording, never "no work exists".
    """
    reasons: list[str] = []
    if not coverage.search_runs and not search_runs:
        reasons.append(
            "no search run is recorded; a partial, unrecorded search can never show that "
            "no work exists"
        )
    gaps = uncompleted_sources(search_runs)
    if gaps:
        reasons.append(
            f"these sources were never completed by any run: {', '.join(gaps)}; the missing "
            "results are exactly where the counter-example would be"
        )
    stalled = incomplete_runs(search_runs)
    if stalled and not gaps:
        reasons.append(f"search runs stopped before exhausting their sources: {', '.join(stalled)}")
    if coverage.overturn_risk in UNSAFE_ABSENCE_RISK:
        reasons.append(
            f"the estimated overturn risk is {coverage.overturn_risk.value}; an absence claim "
            "needs coverage that would have found the work if it existed"
        )
    return not reasons, tuple(reasons)


def matrix_cell_absence_guard(
    cell_empty: bool, models_agree: bool, coverage: Coverage
) -> tuple[bool, str]:
    """Refuse to turn an empty synthesis cell or model agreement into an absence claim.

    An empty cell means "not recorded" (Product 7.1, `SynthesisMatrix`) and agreeing models
    are still models (ADR-007, Product 24.4). Neither is ever the reason an absence claim is
    permitted: the only thing that permits one is recorded search coverage, so this returns
    True only when :func:`absence_permitted` already does, and says so.
    """
    permitted, reasons = absence_permitted(coverage, ())
    basis = []
    if cell_empty:
        basis.append("an empty synthesis cell means 'not recorded', not 'the work lacks it'")
    if models_agree:
        basis.append("agreement between models is not evidence of absence")
    if not permitted:
        refusal = "; ".join([*basis, *reasons])
        return False, f"absence is not permitted here: {refusal}"
    if basis:
        return True, (
            "recorded search coverage permits an absence claim; "
            + "; ".join(basis)
            + ", so the coverage must be the stated basis"
        )
    return True, "recorded search coverage permits an absence claim"

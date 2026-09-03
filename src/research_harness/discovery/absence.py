"""Coverage from recorded search runs, and the audit that stands in front of absence claims.

`claims.coverage` decides what a coverage ledger permits; this module decides what the
*search record* actually is. It reads the discovery funnel off the candidates a `SearchRun`
persisted, so "relevant" means "the researcher included it", "examined" means "accepted
evidence from it bears on this claim", and "unresolved" means "identity unsettled, or no
full text to read" -- each read off canonical state instead of asserted.

The audit refuses three things (Product 11, 42.F/G; ROADMAP 12.5):

* **"No work exists" from a partial or unrecorded search.** Without a recorded run, or with
  a run that stopped before exhausting its sources, no absence wording is permitted at all.
* **An empty synthesis cell.** An empty cell means "not recorded", never "the work lacks
  it", and it is never the basis on which an absence claim is permitted.
* **Model agreement.** Agreeing models are still models; agreement is not coverage.

What it does permit, when the record supports it, is the hedged form: *"we identified no
work that ..."* with the corpus and the cutoff named, plus the unresolved works and the
overturn risk stated out loud rather than rounded away.

A rerun supersedes what it reproduces. Coverage is measured against the runs of record --
the runs no later run reproduces -- while the ledger keeps every screening decision ever
made, because including a work is a decision about the work, not about the run.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Literal

from pydantic import Field

from research_harness.claims.coverage import (
    CoverageLedger,
    CoverageReport,
    CoverageUniverse,
    absence_permitted,
    build_coverage_report,
    incomplete_runs,
    matrix_cell_absence_guard,
)
from research_harness.claims.negative_evidence import absence_wording
from research_harness.claims.strength import ABSENCE_PHRASE, StrengthInput, assess_strength
from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.claim import Claim
from research_harness.domain.enums import (
    ClaimScope,
    ClaimType,
    EvidenceStatus,
    IdentityResolutionOutcome,
    OverturnRisk,
    StaleState,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ClaimId, EvidenceId, SearchRunId, WorkId
from research_harness.domain.research import SearchCandidate, SearchRun
from research_harness.domain.work import Work

__all__ = [
    "BASELINE_AXES",
    "NO_EVIDENCE",
    "NO_WORK_EXISTS_REFUSAL",
    "AbsenceAuditReport",
    "BaselineAxis",
    "BaselineRecommendation",
    "audit_absence_claim",
    "baseline_comparison",
    "coverage_for",
    "effective_runs",
    "examined_works",
    "latest_candidates",
    "ledger_for",
    "superseded_runs",
]

logger = logging.getLogger(__name__)

NO_WORK_EXISTS_REFUSAL = (
    "'no work exists' is not available from this record: a search is evidence about what "
    f"was looked for, not about what exists, so the strongest honest form is '{ABSENCE_PHRASE} "
    "...' with the corpus and cutoff named"
)

#: Stateless empty mapping, so a caller with no evidence to hand needs no sentinel of its own.
NO_EVIDENCE: Mapping[EvidenceId, Evidence] = MappingProxyType({})

BASELINE_AXES: tuple[str, ...] = (
    "task",
    "data",
    "metric",
    "compute",
    "deployment",
    "reproducibility",
)
"""The axes a baseline recommendation must compare explicitly (ROADMAP 12.5)."""


# -- the runs of record ------------------------------------------------------


def superseded_runs(runs: Sequence[SearchRun]) -> frozenset[SearchRunId]:
    """Ids of runs a later run in ``runs`` reproduces.

    A rerun re-executes the same queries against the same sources; when it finishes what
    the earlier attempt could not, the earlier attempt is history rather than a permanent
    hole in coverage. It is still canonical, still linked, and still readable -- it just
    stops being the search of record.
    """
    present = {run.id for run in runs}
    return frozenset(
        run.reproduces for run in runs if run.reproduces is not None and run.reproduces in present
    )


def effective_runs(runs: Sequence[SearchRun]) -> tuple[SearchRun, ...]:
    """The runs coverage is measured against: everything no later run reproduces."""
    replaced = superseded_runs(runs)
    return tuple(run for run in runs if run.id not in replaced)


# -- the funnel --------------------------------------------------------------


def latest_candidates(runs: Sequence[SearchRun]) -> dict[str, SearchCandidate]:
    """Candidate key -> the most recent record of it, screening decisions preferred.

    Runs are read oldest first, and a later run that merely rediscovered a work does not
    erase the screening decision an earlier run recorded: screening is a decision about the
    work, not about the run that happened to surface it.
    """
    latest: dict[str, SearchCandidate] = {}
    for run in sorted(runs, key=lambda item: (item.executed_at, str(item.id))):
        for entry in run.candidates:
            previous = latest.get(entry.key)
            if previous is None or entry.screened or not previous.screened:
                latest[entry.key] = entry
    return latest


def examined_works(claim: Claim, evidence: Mapping[EvidenceId, Evidence]) -> frozenset[WorkId]:
    """Works this claim actually rests on: those with accepted, fresh evidence linked to it.

    A candidate nobody has read is not examined however many times it was discovered, and a
    stale or rejected evidence object does not make its work examined either.
    """
    works: set[WorkId] = set()
    for link in claim.relations:
        item = evidence.get(link.evidence)
        if item is None:
            continue
        if item.status is EvidenceStatus.ACCEPTED and item.stale is StaleState.FRESH:
            works.add(item.source.work)
    return frozenset(works)


def ledger_for(
    claim: Claim,
    runs: Sequence[SearchRun],
    *,
    works: Mapping[WorkId, Work],
    evidence: Mapping[EvidenceId, Evidence] = NO_EVIDENCE,
) -> CoverageLedger:
    """The discovery funnel behind ``claim``, read off the recorded search candidates.

    Unresolved is deliberately wide: a relevant work whose identity is unsettled *and* a
    relevant work with no full text both belong there, because neither can be ruled out. A
    work you cannot open is a work you cannot say anything absent about (Product 12, 18).
    """
    latest = latest_candidates(runs)
    unresolved_by_run = {key for run in runs for key in run.unresolved_keys}
    read = examined_works(claim, evidence)

    discovered = frozenset(latest)
    screened = frozenset(key for key, entry in latest.items() if entry.screened)
    relevant = frozenset(key for key, entry in latest.items() if entry.included)
    full_text = frozenset(key for key in relevant if latest[key].full_text_available is True)
    examined = frozenset(
        key
        for key in relevant
        if (matched := latest[key].matched_work) is not None
        and matched in works
        and matched in read
    )
    unresolved = frozenset(
        key
        for key in relevant
        if key in unresolved_by_run
        or latest[key].identity is IdentityResolutionOutcome.UNRESOLVED
        or latest[key].full_text_available is not True
    )
    return CoverageLedger(
        discovered=discovered,
        screened=screened,
        relevant=relevant,
        full_text_available=full_text,
        examined=examined,
        unresolved=unresolved,
    )


def coverage_for(
    claim: Claim,
    runs: Sequence[SearchRun],
    universe: CoverageUniverse,
    *,
    works: Mapping[WorkId, Work],
    evidence: Mapping[EvidenceId, Evidence] = NO_EVIDENCE,
) -> CoverageReport:
    """Coverage for ``claim``: the funnel from every run, the risk from the runs of record."""
    ledger = ledger_for(claim, runs, works=works, evidence=evidence)
    report = build_coverage_report(universe, ledger, effective_runs(runs))
    replaced = superseded_runs(runs)
    if not replaced:
        return report
    reruns = ", ".join(sorted(str(run_id) for run_id in replaced))
    return report.touch(
        notes=(*report.notes, f"superseded by a later rerun and not counted again: {reruns}")
    )


# -- the audit ---------------------------------------------------------------


class AbsenceAuditReport(DomainModel):
    """What the search record permits an absence claim to say, and every reason it does not."""

    claim: ClaimId
    permitted: bool
    wording: str | None = None
    """The hedged sentence the record supports; ``None`` whenever nothing is permitted."""
    coverage: CoverageReport
    overturn_risk: OverturnRisk
    unresolved: tuple[str, ...] = ()
    """Relevant works whose identity is unsettled or whose full text nobody could read."""
    incomplete_runs: tuple[SearchRunId, ...] = ()
    allowed_scope: ClaimScope = ClaimScope.INDIVIDUAL
    """Highest ladder level the evidence and coverage defend, never above what was asked."""
    reasons: tuple[str, ...] = ()


def audit_absence_claim(
    claim: Claim,
    runs: Sequence[SearchRun],
    universe: CoverageUniverse,
    works: Mapping[WorkId, Work],
    evidence: Mapping[EvidenceId, Evidence],
    *,
    matrix_cell_empty: bool = False,
    models_agree: bool = False,
) -> AbsenceAuditReport:
    """Decide what ``claim`` may say about absence, given the searches actually recorded.

    Permission needs three things at once: a recorded search, sources that were finished,
    and an overturn risk the coverage can carry. Missing any of them, the report is
    ``permitted=False`` with the reasons spelled out and no wording at all -- there is no
    weaker sentence to fall back to, because the problem is the search, not the phrasing.
    An empty synthesis cell and agreeing models are refused as bases on their own; when
    coverage independently permits the claim they are still not the reason it does.
    """
    report = coverage_for(claim, runs, universe, works=works, evidence=evidence)
    coverage = report.coverage
    of_record = effective_runs(runs)
    permitted, refusals = absence_permitted(coverage, of_record)
    reasons = list(refusals)

    if claim.type not in (ClaimType.ABSENCE, ClaimType.PREVALENCE):
        reasons.append(
            f"claim type is {claim.type.value!r}; absence and prevalence are the types this "
            "audit is written for, and the coverage below is reported for information"
        )
    if matrix_cell_empty or models_agree:
        allowed, note = matrix_cell_absence_guard(matrix_cell_empty, models_agree, coverage)
        reasons.append(note)
        permitted = permitted and allowed

    assessment = assess_strength(
        StrengthInput.from_claim(claim, evidence, search_runs_recorded=len(of_record))
    )
    if assessment.escalated:
        reasons.extend(assessment.reasons)

    wording: str | None = None
    if permitted:
        try:
            wording = absence_wording(claim.scope, coverage, of_record)
        except DomainValidationError as error:
            permitted = False
            reasons.append(str(error))
    if not permitted:
        reasons.insert(0, NO_WORK_EXISTS_REFUSAL)

    logger.info(
        "%s absence audit: permitted=%s risk=%s unresolved=%d",
        claim.id,
        permitted,
        coverage.overturn_risk.value,
        len(report.ledger.unresolved),
    )
    return AbsenceAuditReport(
        claim=claim.id,
        permitted=permitted,
        wording=wording,
        coverage=report,
        overturn_risk=coverage.overturn_risk,
        unresolved=tuple(sorted(report.ledger.unresolved)),
        incomplete_runs=incomplete_runs(of_record),
        allowed_scope=assessment.allowed,
        reasons=tuple(reasons),
    )


# -- baseline comparison -----------------------------------------------------


class BaselineAxis(DomainModel):
    """One baseline described on the six axes a comparison has to make explicit.

    Named for the axes rather than for the baseline because that is the point: a
    recommendation that does not say what task, data, metric, compute budget, deployment
    setting, and reproducibility it assumes is not comparable to anything.
    """

    name: NonEmptyStr
    task: NonEmptyStr
    data: NonEmptyStr
    metric: NonEmptyStr
    compute: NonEmptyStr
    deployment: NonEmptyStr
    reproducibility: NonEmptyStr

    def axis(self, name: str) -> str:
        """This baseline's value on one of :data:`BASELINE_AXES`."""
        if name not in BASELINE_AXES:
            raise DomainValidationError(f"unknown baseline axis {name!r}")
        value: str = getattr(self, name)
        return value


class BaselineRecommendation(DomainModel):
    """A reviewable baseline comparison. Never accepted state, and never a model's opinion."""

    candidates: tuple[BaselineAxis, ...] = ()
    axes: tuple[str, ...] = BASELINE_AXES
    agreements: dict[str, str] = Field(default_factory=dict)
    """Axis -> the single value every candidate shares on it."""
    differences: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    """Axis -> the distinct values, sorted; every one of these must be stated when used."""
    comparability: dict[str, int] = Field(default_factory=dict)
    """Baseline name -> how many axes it matches the most common value on."""
    recommended: str | None = None
    text: NonEmptyStr
    reviewable: Literal[True] = True
    """Pinned: a baseline recommendation is a candidate for review, never a finding."""


def baseline_comparison(candidates: Sequence[BaselineAxis]) -> BaselineRecommendation:
    """Compare baselines on the explicit axes and propose one, deterministically.

    No model is called and no similarity is scored: the comparison is the axis values the
    researcher wrote down, the proposal is the baseline that matches the most common value
    on the most axes (ties broken by name), and every axis the baselines disagree on is
    listed so it can be stated wherever the recommendation is used.
    """
    entries = tuple(candidates)
    if not entries:
        return BaselineRecommendation(
            text=(
                "No baseline candidates were supplied, so there is nothing to compare; a "
                "baseline recommendation needs at least one described baseline."
            )
        )
    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        raise DomainValidationError(
            "a baseline comparison names each baseline once; two rows with one name cannot "
            "be told apart in the recommendation"
        )
    values = {axis: [entry.axis(axis) for entry in entries] for axis in BASELINE_AXES}
    agreements = {axis: seen[0] for axis, seen in values.items() if len(set(seen)) == 1}
    differences = {
        axis: tuple(sorted(set(seen))) for axis, seen in values.items() if len(set(seen)) > 1
    }
    modal = {axis: _modal(seen) for axis, seen in values.items()}
    comparability = {
        entry.name: sum(1 for axis in BASELINE_AXES if entry.axis(axis) == modal[axis])
        for entry in entries
    }
    recommended = min(entries, key=lambda entry: (-comparability[entry.name], entry.name)).name
    return BaselineRecommendation(
        candidates=entries,
        agreements=agreements,
        differences=differences,
        comparability=comparability,
        recommended=recommended,
        text=_baseline_text(entries, agreements, differences, comparability, recommended),
    )


def _modal(values: Sequence[str]) -> str:
    """The most common value; ties broken by sort order so the result is reproducible."""
    counts = Counter(values)
    top = max(counts.values())
    return min(value for value, count in counts.items() if count == top)


def _baseline_text(
    entries: Sequence[BaselineAxis],
    agreements: Mapping[str, str],
    differences: Mapping[str, Sequence[str]],
    comparability: Mapping[str, int],
    recommended: str,
) -> str:
    """The reviewable paragraph: what agrees, what differs, and what is being proposed."""
    names = ", ".join(entry.name for entry in entries)
    lines = [
        "Baseline comparison candidate for review (produced by comparing the recorded "
        "axes; no model was consulted).",
        f"Baselines compared: {names}.",
    ]
    for axis in BASELINE_AXES:
        if axis in agreements:
            lines.append(f"  {axis}: all baselines state {agreements[axis]!r}.")
            continue
        stated = "; ".join(f"{entry.name}={entry.axis(axis)!r}" for entry in entries)
        lines.append(f"  {axis}: differs -- {stated}.")
    matched = comparability[recommended]
    unmatched = [axis for axis in BASELINE_AXES if axis in differences]
    lines.append(
        f"Proposed baseline: {recommended}, comparable on {matched} of {len(BASELINE_AXES)} axes."
    )
    if unmatched:
        lines.append(
            "The baselines differ on "
            + ", ".join(unmatched)
            + "; every use of this recommendation must state those differences rather than "
            "compare across them silently."
        )
    lines.append("This is a candidate for review, not an accepted recommendation.")
    return "\n".join(lines)

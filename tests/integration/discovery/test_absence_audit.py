"""Coverage read off recorded runs, and the audit that refuses what the record cannot carry.

These are the Task 12.5 rules in isolation: "no work exists" is never available from a
partial or unrecorded search, an empty synthesis cell and model agreement are never the
basis for an absence claim, and a baseline recommendation compares the six explicit axes
without consulting anything.
"""

from __future__ import annotations

import datetime

import pytest

from research_harness.claims.coverage import CoverageUniverse
from research_harness.discovery.absence import (
    NO_WORK_EXISTS_REFUSAL,
    BaselineAxis,
    audit_absence_claim,
    baseline_comparison,
    coverage_for,
    effective_runs,
    ledger_for,
    superseded_runs,
)
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    IdentityResolutionOutcome,
    OverturnRisk,
    ScreeningState,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import (
    ArtifactId,
    BlockId,
    ClaimId,
    EvidenceId,
    SearchRunId,
    VersionId,
    WorkId,
)
from research_harness.domain.research import (
    SearchCandidate,
    SearchResultCounts,
    SearchRun,
    SourceCursor,
    SourceFailure,
)
from research_harness.domain.work import Work, WorkCandidate

SYSTEM = Provenance.system()
HUMAN = Provenance.human()
UNIVERSE = CoverageUniverse(
    definition="structured traffic representation", cutoff="2026-08", sources=("openalex",)
)
HASH = "sha256:" + "a" * 64
SCREENED_AT = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)


def candidate(
    key: str,
    *,
    state: ScreeningState = ScreeningState.DISCOVERED,
    work: WorkId | None = None,
    full_text: bool | None = True,
    identity: IdentityResolutionOutcome | None = IdentityResolutionOutcome.DISTINCT_WORK,
    reason: str | None = None,
) -> SearchCandidate:
    return SearchCandidate(
        key=key,
        candidate=WorkCandidate(provenance=SYSTEM),
        sources=("openalex",),
        ranks={"openalex": 1},
        screening=state,
        exclusion_reason=reason,
        screened_by=None if state is ScreeningState.DISCOVERED else "human",
        screened_at=None if state is ScreeningState.DISCOVERED else SCREENED_AT,
        identity=identity,
        matched_work=work,
        full_text_available=full_text,
    )


def run(
    run_id: str,
    candidates: tuple[SearchCandidate, ...] = (),
    *,
    exhausted: bool = True,
    failures: tuple[SourceFailure, ...] = (),
    reproduces: str | None = None,
    minute: int = 0,
    **extra: object,
) -> SearchRun:
    return SearchRun(
        id=SearchRunId(run_id),
        question="does anything represent traffic at protocol-field level",
        sources=("openalex", "crossref"),
        queries=("protocol field traffic",),
        results=SearchResultCounts(
            discovered=len(candidates),
            screened=sum(1 for entry in candidates if entry.screened),
            included=sum(1 for entry in candidates if entry.included),
        ),
        executed_at=datetime.datetime(2026, 8, 1, 12, minute, tzinfo=datetime.UTC),
        cutoff=datetime.date(2026, 8, 31),
        cursors=(
            SourceCursor(source="openalex", pages_fetched=1, exhausted=exhausted),
            SourceCursor(source="crossref", pages_fetched=1, exhausted=True),
        ),
        failures=failures,
        candidates=candidates,
        reproduces=None if reproduces is None else SearchRunId(reproduces),
        provenance=SYSTEM,
        **extra,
    )


def work_record(work: WorkId) -> Work:
    return Work(id=work, title="A surveyed system", provenance=HUMAN)


def accepted(evidence_id: str, work: WorkId) -> Evidence:
    return Evidence(
        id=EvidenceId(evidence_id),
        source=SourceAnchor(
            work=work,
            version=VersionId(f"V{work.number:04d}-1"),
            artifact=ArtifactId(f"A{work.number:04d}-1"),
            file_hash=HASH,
            block=BlockId("B0001"),
            text_hash=HASH,
        ),
        content=EvidenceContent(exact_text="No protocol-field representation is reported."),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.AUTHOR_CONCLUSION,
        strength=EvidenceStrength.DIRECT,
        verification=VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by="human"),
        provenance=HUMAN,
    )


def absence_claim(*evidence: str) -> Claim:
    return Claim(
        id=ClaimId("C0001"),
        statement="No surveyed system represents traffic at the protocol-field level.",
        type=ClaimType.ABSENCE,
        semantics=ClaimSemantics(
            subject="surveyed systems", predicate="represent", object="protocol fields"
        ),
        scope=ClaimScopeSpec(
            level=ClaimScope.UNIVERSAL_OR_ABSENCE,
            corpus="structured traffic representation",
            publication_until="2026-08",
        ),
        relations=tuple(
            ClaimEvidenceRelation(
                evidence=EvidenceId(item), relation=ClaimEvidenceRelationType.SUPPORTS
            )
            for item in evidence
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.UNIVERSAL_OR_ABSENCE,
            allowed_strength=ClaimScope.INDIVIDUAL,
        ),
        provenance=HUMAN,
    )


# -- the funnel --------------------------------------------------------------


def test_the_ledger_is_read_off_the_recorded_candidates() -> None:
    work = WorkId("W0001")
    runs = [
        run(
            "SR0001",
            (
                candidate("doi:a", state=ScreeningState.INCLUDED, work=work),
                candidate("doi:b", state=ScreeningState.EXCLUDED, reason="different field"),
                candidate("doi:c"),
            ),
        )
    ]

    ledger = ledger_for(
        absence_claim("E0001"),
        runs,
        works={work: work_record(work)},
        evidence={EvidenceId("E0001"): accepted("E0001", work)},
    )

    assert ledger.discovered == frozenset({"doi:a", "doi:b", "doi:c"})
    assert ledger.screened == frozenset({"doi:a", "doi:b"})
    assert ledger.relevant == frozenset({"doi:a"})
    assert ledger.examined == frozenset({"doi:a"})
    assert ledger.unresolved == frozenset()


def test_a_relevant_work_nobody_can_read_counts_as_unresolved() -> None:
    """Product 12: only existence or direction can be read from a work with no full text."""
    work = WorkId("W0001")
    runs = [
        run(
            "SR0001",
            (candidate("doi:a", state=ScreeningState.INCLUDED, work=work, full_text=False),),
            full_text_unavailable_keys=("doi:a",),
        )
    ]

    ledger = ledger_for(absence_claim(), runs, works={work: work_record(work)})

    assert ledger.unresolved == frozenset({"doi:a"})
    assert ledger.full_text_available == frozenset()
    assert ledger.examined == frozenset()


def test_a_later_run_does_not_erase_an_earlier_screening_decision() -> None:
    work = WorkId("W0001")
    first = run("SR0001", (candidate("doi:a", state=ScreeningState.INCLUDED, work=work),), minute=0)
    second = run("SR0002", (candidate("doi:a"),), minute=5)

    ledger = ledger_for(absence_claim(), [first, second], works={work: work_record(work)})

    assert ledger.relevant == frozenset({"doi:a"})


def test_a_rerun_supersedes_the_run_it_reproduces() -> None:
    first = run("SR0001", exhausted=False)
    second = run("SR0002", reproduces="SR0001", minute=5)

    assert superseded_runs([first, second]) == frozenset({SearchRunId("SR0001")})
    assert [record.id for record in effective_runs([first, second])] == ["SR0002"]
    assert effective_runs([first]) == (first,)


# -- the audit ---------------------------------------------------------------


def test_no_work_exists_is_refused_when_nothing_was_recorded() -> None:
    report = audit_absence_claim(absence_claim(), [], UNIVERSE, {}, {})

    assert report.permitted is False
    assert report.wording is None
    assert report.reasons[0] == NO_WORK_EXISTS_REFUSAL
    assert any("no search run is recorded" in reason for reason in report.reasons)
    assert report.overturn_risk is OverturnRisk.UNKNOWN


def test_a_run_that_stopped_early_refuses_the_claim() -> None:
    work = WorkId("W0001")
    runs = [
        run(
            "SR0001",
            (candidate("doi:a", state=ScreeningState.INCLUDED, work=work),),
            exhausted=False,
            failures=(SourceFailure(source="openalex", reason="rate_limit: throttled"),),
        )
    ]

    report = audit_absence_claim(
        absence_claim("E0001"),
        runs,
        UNIVERSE,
        {work: work_record(work)},
        {EvidenceId("E0001"): accepted("E0001", work)},
    )

    assert report.permitted is False
    assert report.incomplete_runs == (SearchRunId("SR0001"),)
    assert report.overturn_risk is OverturnRisk.HIGH
    assert any("never completed" in reason for reason in report.reasons)


def test_a_complete_record_permits_the_hedged_wording_and_nothing_stronger() -> None:
    work = WorkId("W0001")
    runs = [run("SR0001", (candidate("doi:a", state=ScreeningState.INCLUDED, work=work),))]

    report = audit_absence_claim(
        absence_claim("E0001"),
        runs,
        UNIVERSE,
        {work: work_record(work)},
        {EvidenceId("E0001"): accepted("E0001", work)},
    )

    assert report.permitted is True
    assert report.wording is not None
    assert "we identified no work that" in report.wording
    assert "2026-08" in report.wording
    assert "no work exists" not in report.wording
    assert report.overturn_risk is OverturnRisk.LOW
    assert report.allowed_scope < ClaimScope.UNIVERSAL_OR_ABSENCE
    assert report.coverage.coverage.search_runs == (SearchRunId("SR0001"),)


def test_an_empty_cell_or_agreeing_models_are_never_the_basis() -> None:
    """ROADMAP 12.5: neither promotes to an absence claim, whatever the coverage says."""
    work = WorkId("W0001")
    runs = [run("SR0001", (candidate("doi:a", state=ScreeningState.INCLUDED, work=work),))]
    evidence = {EvidenceId("E0001"): accepted("E0001", work)}

    refused = audit_absence_claim(
        absence_claim(), [], UNIVERSE, {}, {}, matrix_cell_empty=True, models_agree=True
    )
    permitted = audit_absence_claim(
        absence_claim("E0001"),
        runs,
        UNIVERSE,
        {work: work_record(work)},
        evidence,
        matrix_cell_empty=True,
        models_agree=True,
    )

    assert refused.permitted is False
    assert any("absence is not permitted here" in reason for reason in refused.reasons)
    assert permitted.permitted is True
    assert any("coverage must be the stated basis" in reason for reason in permitted.reasons)
    assert any("not 'the work lacks it'" in reason for reason in permitted.reasons)


def test_coverage_notes_say_which_runs_a_rerun_replaced() -> None:
    work = WorkId("W0001")
    entry = candidate("doi:a", state=ScreeningState.INCLUDED, work=work)
    runs = [run("SR0001", (entry,), exhausted=False), run("SR0002", (entry,), reproduces="SR0001")]

    report = coverage_for(absence_claim(), runs, UNIVERSE, works={work: work_record(work)})

    assert any("superseded by a later rerun" in note for note in report.notes)
    assert report.coverage.search_runs == (SearchRunId("SR0002"),)


# -- baseline comparison -----------------------------------------------------


def axis(name: str, **overrides: str) -> BaselineAxis:
    fields = {
        "name": name,
        "task": "encrypted traffic classification",
        "data": "CICIDS2017",
        "metric": "macro F1",
        "compute": "1 GPU-hour",
        "deployment": "offline batch",
        "reproducibility": "code and weights released",
    }
    return BaselineAxis(**{**fields, **overrides})


def test_a_baseline_recommendation_compares_the_explicit_axes_and_stays_a_candidate() -> None:
    result = baseline_comparison(
        [
            axis("flow-transformer"),
            axis("packet-cnn", compute="40 GPU-hours"),
            axis("bytes-lstm", compute="40 GPU-hours", reproducibility="no code released"),
        ]
    )

    assert result.reviewable is True
    assert result.recommended == "packet-cnn"
    assert result.agreements["task"] == "encrypted traffic classification"
    assert result.differences["compute"] == ("1 GPU-hour", "40 GPU-hours")
    assert result.comparability == {
        "flow-transformer": 5,
        "packet-cnn": 6,
        "bytes-lstm": 5,
    }
    assert "candidate for review" in result.text
    assert "compute: differs" in result.text
    assert result == baseline_comparison(list(result.candidates))


def test_a_baseline_comparison_with_nothing_to_compare_says_so() -> None:
    result = baseline_comparison([])

    assert result.recommended is None
    assert "nothing to compare" in result.text


def test_two_baselines_may_not_share_one_name() -> None:
    with pytest.raises(DomainValidationError, match="names each baseline once"):
        baseline_comparison([axis("flow-transformer"), axis("flow-transformer", data="UNSW")])


def test_an_unknown_baseline_axis_is_refused() -> None:
    with pytest.raises(DomainValidationError, match="unknown baseline axis"):
        axis("flow-transformer").axis("vibes")

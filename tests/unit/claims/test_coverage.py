"""Coverage funnel, overturn risk, and the guards in front of absence claims (Product 18)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from research_harness.claims import (
    CoverageLedger,
    CoverageUniverse,
    absence_permitted,
    build_coverage_report,
    compute_coverage,
    estimate_overturn_risk,
    incomplete_runs,
    matrix_cell_absence_guard,
    parse_cutoff,
    run_is_incomplete,
    searched_sources,
    uncompleted_sources,
)
from research_harness.domain import (
    Coverage,
    DomainValidationError,
    OverturnRisk,
    SearchRun,
    SearchRunId,
    SourceCursor,
    SourceFailure,
)
from tests.unit.domain import strategies as sty

#: Increasing order of risk, used to state monotonicity.
RISK_ORDER = (
    OverturnRisk.LOW,
    OverturnRisk.LOW_MODERATE,
    OverturnRisk.MODERATE,
    OverturnRisk.HIGH,
    OverturnRisk.UNKNOWN,
)

SOURCES = ("semantic_scholar", "openalex")


def universe(**overrides: Any) -> CoverageUniverse:
    fields: dict[str, Any] = {
        "definition": "LLM-based network traffic analysis",
        "cutoff": "2026-08",
        "sources": SOURCES,
    }
    return CoverageUniverse(**{**fields, **overrides})


def keys(prefix: str, count: int) -> frozenset[str]:
    return frozenset(f"{prefix}{index:04d}" for index in range(count))


def ledger(relevant: int = 20, examined: int = 20, unresolved: int = 0) -> CoverageLedger:
    """A nested funnel: everything discovered, relevant a prefix, examined a prefix of that."""
    all_works = keys("W", 40)
    relevant_works = keys("W", relevant)
    return CoverageLedger(
        discovered=all_works,
        screened=all_works,
        relevant=relevant_works,
        full_text_available=relevant_works,
        examined=keys("W", examined),
        unresolved=frozenset(sorted(relevant_works)[relevant - unresolved :])
        if unresolved
        else frozenset(),
    )


def run(**overrides: Any) -> SearchRun:
    fields: dict[str, Any] = {"sources": SOURCES}
    return sty.make_search_run(**{**fields, **overrides})


def exhausted_run(**overrides: Any) -> SearchRun:
    fields: dict[str, Any] = {
        "cursors": tuple(SourceCursor(source=source, exhausted=True) for source in SOURCES),
    }
    return run(**{**fields, **overrides})


# --- cutoffs ----------------------------------------------------------------


def test_a_year_month_cutoff_covers_the_whole_month() -> None:
    assert parse_cutoff("2026-08") == date(2026, 8, 31)
    assert parse_cutoff("2026-02") == date(2026, 2, 28)
    assert parse_cutoff("2026-08-14") == date(2026, 8, 14)
    assert parse_cutoff(date(2026, 8, 14)) == date(2026, 8, 14)


def test_an_unparseable_cutoff_is_refused() -> None:
    with pytest.raises(DomainValidationError, match="YYYY-MM"):
        parse_cutoff("August 2026")
    with pytest.raises(ValidationError):
        universe(cutoff="August 2026")


def test_the_universe_exposes_its_cutoff_as_a_date() -> None:
    assert universe().cutoff_date == date(2026, 8, 31)


# --- the funnel -------------------------------------------------------------


def test_the_funnel_must_nest() -> None:
    with pytest.raises(ValidationError, match="outside the previous funnel stage"):
        CoverageLedger(discovered=keys("W", 2), screened=keys("W", 3))
    with pytest.raises(ValidationError, match="outside the previous funnel stage"):
        CoverageLedger(
            discovered=keys("W", 3),
            screened=keys("W", 3),
            relevant=keys("W", 1),
            examined=keys("W", 3),
        )


def test_an_empty_corpus_is_vacuously_examined_and_fully_resolved() -> None:
    empty = CoverageLedger()

    assert empty.examined_ratio == 1.0
    assert empty.unresolved_ratio == 0.0
    assert empty.unexamined == frozenset()


def test_compute_coverage_fills_counts_runs_and_cutoff() -> None:
    coverage = compute_coverage(
        universe(), ledger(relevant=17, examined=14, unresolved=3), (run(),)
    )

    assert coverage.relevant_works == 17
    assert coverage.examined_works == 14
    assert coverage.unresolved_works == 3
    assert coverage.cutoff == date(2026, 8, 31)
    assert coverage.search_runs == (SearchRunId("SR0019"),)
    assert coverage.overturn_risk is OverturnRisk.MODERATE


def test_compute_coverage_records_each_run_once() -> None:
    coverage = compute_coverage(universe(), ledger(), (exhausted_run(), exhausted_run()))

    assert coverage.search_runs == (SearchRunId("SR0019"),)


# --- overturn risk ----------------------------------------------------------


def test_risk_is_unknown_without_a_recorded_run() -> None:
    assert estimate_overturn_risk(ledger(), (), universe()) is OverturnRisk.UNKNOWN


def test_risk_is_high_when_more_than_a_quarter_is_unresolved() -> None:
    thin = ledger(relevant=8, examined=8, unresolved=3)

    assert estimate_overturn_risk(thin, (exhausted_run(),), universe()) is OverturnRisk.HIGH


def test_risk_is_high_when_less_than_half_the_corpus_was_examined() -> None:
    thin = ledger(relevant=10, examined=4)

    assert estimate_overturn_risk(thin, (exhausted_run(),), universe()) is OverturnRisk.HIGH


def test_risk_is_high_when_a_run_stopped_before_exhausting_a_source() -> None:
    stalled = run(cursors=(SourceCursor(source="openalex", exhausted=False),))

    assert run_is_incomplete(stalled)
    assert incomplete_runs((stalled,)) == (SearchRunId("SR0019"),)
    assert estimate_overturn_risk(ledger(), (stalled,), universe()) is OverturnRisk.HIGH


def test_risk_is_high_when_a_failed_source_is_never_completed() -> None:
    failed = run(
        failures=(SourceFailure(source="openalex", reason="429 rate limited", incomplete=True),)
    )

    assert uncompleted_sources((failed,)) == ("openalex",)
    assert estimate_overturn_risk(ledger(), (failed,), universe()) is OverturnRisk.HIGH


def test_a_rerun_that_finishes_the_source_repairs_the_gap() -> None:
    failed = run(failures=(SourceFailure(source="openalex", reason="429", incomplete=True),))
    rerun = exhausted_run(id=SearchRunId("SR0020"))

    assert uncompleted_sources((failed, rerun)) == ()
    assert estimate_overturn_risk(ledger(), (failed, rerun), universe()) is OverturnRisk.HIGH
    assert estimate_overturn_risk(ledger(), (rerun,), universe()) is OverturnRisk.LOW


def test_risk_is_moderate_with_a_single_source() -> None:
    single = exhausted_run(sources=("openalex",), cursors=())

    assert estimate_overturn_risk(ledger(), (single,), universe(sources=("openalex",))) is (
        OverturnRisk.MODERATE
    )


def test_risk_is_moderate_when_a_declared_source_was_never_searched() -> None:
    declared = universe(sources=(*SOURCES, "dblp"))

    assert estimate_overturn_risk(ledger(), (exhausted_run(),), declared) is OverturnRisk.MODERATE


def test_risk_is_moderate_when_a_tenth_of_the_corpus_is_unresolved() -> None:
    partial = ledger(relevant=20, examined=20, unresolved=3)

    assert estimate_overturn_risk(partial, (exhausted_run(),), universe()) is OverturnRisk.MODERATE


def test_risk_is_low_moderate_for_broad_but_incomplete_reading() -> None:
    broad = ledger(relevant=10, examined=9, unresolved=1)

    assert estimate_overturn_risk(broad, (exhausted_run(),), universe()) is (
        OverturnRisk.LOW_MODERATE
    )


def test_risk_is_low_only_for_a_complete_multi_source_corpus() -> None:
    assert estimate_overturn_risk(ledger(), (exhausted_run(),), universe()) is OverturnRisk.LOW


@given(
    relevant=st.integers(min_value=1, max_value=20),
    examined=st.integers(min_value=0, max_value=20),
    extra=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=50)
def test_examining_more_works_never_raises_the_overturn_risk(
    relevant: int, examined: int, extra: int
) -> None:
    runs = (exhausted_run(),)
    thin = estimate_overturn_risk(ledger(relevant, min(examined, relevant)), runs, universe())
    thick = estimate_overturn_risk(
        ledger(relevant, min(examined + extra, relevant)), runs, universe()
    )

    assert RISK_ORDER.index(thick) <= RISK_ORDER.index(thin)


# --- reports ----------------------------------------------------------------


def test_the_report_names_every_gap_that_would_move_the_risk() -> None:
    failed = run(
        sources=("openalex",),
        failures=(SourceFailure(source="openalex", reason="429", incomplete=True),),
    )

    report = build_coverage_report(
        universe(sources=(*SOURCES, "dblp")),
        ledger(relevant=20, examined=12, unresolved=4),
        (failed,),
    )

    joined = " | ".join(report.notes)
    assert "8 relevant works have not been examined" in joined
    assert "4 relevant works are unresolved" in joined
    assert "sources never completed by any run: openalex" in joined
    assert "declared sources never searched: semantic_scholar, dblp" in joined
    assert report.coverage.overturn_risk is OverturnRisk.HIGH


def test_the_report_flags_relevant_works_without_full_text() -> None:
    thin = CoverageLedger(
        discovered=keys("W", 5),
        screened=keys("W", 5),
        relevant=keys("W", 5),
        full_text_available=keys("W", 2),
        examined=keys("W", 5),
    )

    report = build_coverage_report(universe(), thin, (exhausted_run(),))

    assert any("3 relevant works have no full text" in note for note in report.notes)


def test_an_empty_record_reports_the_missing_search_run() -> None:
    report = build_coverage_report(universe(), CoverageLedger(), ())

    assert report.coverage.overturn_risk is OverturnRisk.UNKNOWN
    assert any("no search run is recorded" in note for note in report.notes)


# --- absence guards ---------------------------------------------------------


def complete_coverage() -> Coverage:
    return compute_coverage(universe(), ledger(), (exhausted_run(),))


def test_absence_needs_a_recorded_search_run() -> None:
    permitted, reasons = absence_permitted(Coverage(overturn_risk=OverturnRisk.LOW), ())

    assert not permitted
    assert any("no search run is recorded" in reason for reason in reasons)


def test_absence_is_refused_under_high_or_unknown_risk() -> None:
    for risk in (OverturnRisk.HIGH, OverturnRisk.UNKNOWN):
        coverage = complete_coverage().touch(overturn_risk=risk)
        permitted, reasons = absence_permitted(coverage, (exhausted_run(),))

        assert not permitted
        assert any(risk.value in reason for reason in reasons)


def test_absence_is_refused_while_a_source_is_unfinished() -> None:
    failed = run(failures=(SourceFailure(source="openalex", reason="429", incomplete=True),))

    permitted, reasons = absence_permitted(complete_coverage(), (failed,))

    assert not permitted
    assert any("never completed by any run" in reason for reason in reasons)


def test_absence_is_refused_when_a_run_stopped_paging_a_source_it_did_not_declare() -> None:
    stalled = run(sources=(), cursors=(SourceCursor(source="openalex", exhausted=False),))

    permitted, reasons = absence_permitted(complete_coverage(), (stalled,))

    assert not permitted
    assert reasons


def test_absence_is_permitted_by_complete_low_risk_coverage() -> None:
    permitted, reasons = absence_permitted(complete_coverage(), (exhausted_run(),))

    assert permitted
    assert reasons == ()


def test_an_empty_matrix_cell_is_never_an_absence_claim() -> None:
    permitted, explanation = matrix_cell_absence_guard(
        cell_empty=True, models_agree=False, coverage=Coverage()
    )

    assert not permitted
    assert "not recorded" in explanation


def test_model_agreement_is_never_an_absence_claim() -> None:
    permitted, explanation = matrix_cell_absence_guard(
        cell_empty=False, models_agree=True, coverage=Coverage()
    )

    assert not permitted
    assert "agreement between models is not evidence of absence" in explanation


def test_an_empty_cell_with_strong_coverage_rests_on_the_coverage() -> None:
    permitted, explanation = matrix_cell_absence_guard(
        cell_empty=True, models_agree=True, coverage=complete_coverage()
    )

    assert permitted
    assert "coverage must be the stated basis" in explanation


def test_the_matrix_guard_refuses_whenever_coverage_does() -> None:
    unknown = Coverage(search_runs=(SearchRunId("SR0019"),), overturn_risk=OverturnRisk.UNKNOWN)

    permitted, explanation = matrix_cell_absence_guard(
        cell_empty=False, models_agree=False, coverage=unknown
    )

    assert not permitted
    assert "unknown" in explanation


def test_searched_sources_are_distinct_and_sorted() -> None:
    assert searched_sources((run(), run(sources=("dblp", "openalex")))) == (
        "dblp",
        "openalex",
        "semantic_scholar",
    )

"""Claim structure: scope ladder, evidence relations, coverage, and assessment."""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from research_harness.domain import (
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimScopeSpec,
    ClaimStatus,
    Coverage,
    EvidenceId,
    OverturnRisk,
    SearchRunId,
    SynthesisId,
)
from tests.unit.domain import strategies as sty


def test_requested_and_allowed_strength_are_separate_fields() -> None:
    claim = sty.make_claim()
    assert claim.requested_strength is ClaimScope.FIELD_GENERALIZATION
    assert claim.allowed_strength is ClaimScope.INDIVIDUAL
    assert "requested_strength" in ClaimAssessment.model_fields
    assert "allowed_strength" in ClaimAssessment.model_fields


def test_allowed_strength_can_never_exceed_the_requested_strength() -> None:
    with pytest.raises(ValidationError, match="may not exceed"):
        ClaimAssessment(
            requested_strength=ClaimScope.CORPUS_PATTERN,
            allowed_strength=ClaimScope.UNIVERSAL_OR_ABSENCE,
        )


def test_an_assessment_starts_unverified() -> None:
    assessment = ClaimAssessment(
        requested_strength=ClaimScope.CORPUS_PATTERN,
        allowed_strength=ClaimScope.INDIVIDUAL,
    )
    assert assessment.status is ClaimStatus.UNVERIFIED
    assert assessment.audited_at is None
    assert assessment.maximum_defensible_wording is None


def test_claim_relations_are_many_to_many_and_aspect_scoped() -> None:
    """The same evidence may support one aspect of a claim and qualify another."""
    claim = sty.make_claim(
        relations=(
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0132"),
                relation=ClaimEvidenceRelationType.SUPPORTS,
                aspect="tokenization",
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0132"),
                relation=ClaimEvidenceRelationType.QUALIFIES,
                aspect="encryption",
            ),
        )
    )
    assert claim.supporting == ("E0132",)
    assert claim.qualifying == ("E0132",)
    assert claim.contradicting == ()


def test_relation_helpers_read_the_relation_list() -> None:
    claim = sty.make_claim(
        relations=(
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0001"), relation=ClaimEvidenceRelationType.CONTRADICTS
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0002"), relation=ClaimEvidenceRelationType.EXEMPLIFIES
            ),
        )
    )
    assert claim.contradicting == ("E0001",)
    assert claim.evidence_with_relation(ClaimEvidenceRelationType.EXEMPLIFIES) == ("E0002",)
    assert claim.supporting == ()


def test_scope_spec_validates_the_publication_cutoff_format() -> None:
    assert ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, publication_until="2026-08")
    for bad in ["2026-13", "2026", "26-08", "2026-8"]:
        with pytest.raises(ValidationError):
            ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, publication_until=bad)


def test_coverage_records_the_universe_behind_an_absence_claim() -> None:
    coverage = Coverage(
        relevant_works=17,
        examined_works=14,
        unresolved_works=3,
        overturn_risk=OverturnRisk.LOW_MODERATE,
        search_runs=(SearchRunId("SR0019"),),
        cutoff=datetime.date(2026, 8, 31),
    )
    assert coverage.search_runs == ("SR0019",)
    assert coverage.cutoff == datetime.date(2026, 8, 31)


def test_coverage_defaults_to_unknown_overturn_risk() -> None:
    coverage = Coverage()
    assert coverage.overturn_risk is OverturnRisk.UNKNOWN
    assert coverage.search_runs == ()
    counts = (coverage.relevant_works, coverage.examined_works, coverage.unresolved_works)
    assert counts == (0, 0, 0)


def test_coverage_counts_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        Coverage(relevant_works=-1)


def test_claims_carry_semantics_not_just_prose() -> None:
    claim = sty.make_claim()
    assert claim.semantics.subject == "existing_systems"
    assert claim.semantics.qualifier == {"property": "heterogeneous"}
    assert claim.statement


def test_claims_are_fresh_and_undecided_by_default() -> None:
    claim = sty.make_claim()
    assert claim.decisions == ()
    assert claim.derived_from == ()
    assert claim.status is ClaimStatus.UNVERIFIED
    assert claim.stale.value == "fresh"


def test_a_synthesis_claim_records_the_matrices_it_derives_from() -> None:
    """Product 37: the matrix a claim was read off is canonical, so staleness can reach it."""
    claim = sty.make_claim(derived_from=(SynthesisId("S0007"), SynthesisId("S0009")))
    assert claim.derived_from == ("S0007", "S0009")

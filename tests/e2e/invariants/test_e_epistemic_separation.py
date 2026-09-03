"""Product §42.E - Epistemic separation.

"An author claim cannot automatically become a verified experimental result."

Two independent gates have to hold at once, and both are exercised end to end here:

* the **ladder** never counts an `author_claimed` object as support for a measured value,
  so a numeric Claim leaning only on the authors' own report is not supported at all
  (`claims.strength`, Product §12);
* the **transition table** has no path that turns a model proposal into a source
  observation, and every other origin change needs the researcher and a rationale
  (`domain.transitions.reclassify_origin`, ADR-003).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import AcceptEvidenceRequest
from research_harness.capabilities.handlers import accept_evidence
from research_harness.claims.service import ClaimService
from research_harness.claims.strength import (
    AUTHOR_ORIGINS,
    StrengthInput,
    assess_strength,
)
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
    Coverage,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import AuthorityError, TransitionError
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    NumericValue,
    SourceAnchor,
)
from research_harness.domain.ids import BlockId, EvidenceId
from research_harness.domain.transitions import reclassify_origin
from research_harness.roles.schemas import EXTRACTOR_ALLOWED_ORIGINS, EvidenceCandidateOutput
from tests.e2e.invariants.workstation import (
    HUMAN,
    MEASURED_VALUE,
    MODEL_ACTOR,
    WORK,
    Workstation,
    init_and_ingest,
)

AUTHOR_TEXT = "The pretrained encoder improves F1 by 2.57 points over the strongest baseline"


def author_reported_number(ctx: CapabilityContext, evidence_id: str) -> Evidence:
    """What the *authors say* their system scores: a claim about a result, not the result.

    Anchored in the real prose block that makes the assertion, so the object is a genuine
    `author_claimed` reading rather than a hand-built strawman.
    """
    artifact = ctx.repo.get_artifact(next(iter(ctx.repo.list_artifacts(WORK))).id, work=WORK)
    block = next(
        item
        for item in ctx.repo.iter_blocks(artifact.id, work=WORK)
        if "The pretrained encoder improves F1" in item.text
    )
    start = block.text.index("The pretrained encoder")
    end = start + len(AUTHOR_TEXT)
    return Evidence(
        id=EvidenceId(evidence_id),
        source=SourceAnchor(
            work=WORK,
            version=artifact.version,
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId(str(block.id)),
            text_hash=block.text_hash,
            page=block.page,
            char_start=start,
            char_end=end,
        ),
        content=EvidenceContent(
            exact_text=block.text[start:end],
            numeric=NumericValue(
                raw=MEASURED_VALUE,
                parsed=94.32,
                metric="F1",
                dataset="CICIDS2017",
                source_table="Table 1",
            ),
            field="metric_result",
        ),
        origin=EvidenceOrigin.AUTHOR_CLAIMED,
        evidence_type=EvidenceType.AUTHOR_CONCLUSION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        provenance=Provenance.model(MODEL_ACTOR),
    )


@pytest.fixture(scope="module")
def author_claim(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A numeric Claim whose only support is the authors' own report of the number."""
    ctx = init_and_ingest(tmp_path_factory.mktemp("epistemic") / "project", name="epistemic")
    candidate = author_reported_number(ctx, "E0001")
    accept_evidence(
        ctx,
        AcceptEvidenceRequest(
            candidate=candidate,
            verdict=VerificationVerdict.SUPPORTED,
            rationale="the authors do assert this in the prose",
        ),
    )
    claim, _ = ClaimService(ctx).create(
        f"TrafficLM reaches an F1 of {MEASURED_VALUE} on CICIDS2017",
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="TrafficLM", predicate="reaches", object="an F1 of 94.32"),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL, corpus="encrypted traffic classifiers"),
        requested_strength=ClaimScope.INDIVIDUAL,
        relations=(
            ClaimEvidenceRelation(
                evidence=candidate.id, relation=ClaimEvidenceRelationType.SUPPORTS
            ),
        ),
        coverage=Coverage(relevant_works=1, examined_works=1),
    )
    return ctx.root, str(claim.id)


# ---------------------------------------------------------------- the ladder demotes it


def test_an_author_report_of_a_number_is_counted_as_a_qualifier_not_as_support(
    author_claim: tuple[Path, str],
) -> None:
    """Product §12: a measured value needs the source's own record, not the authors' word."""
    root, claim_id = author_claim
    from research_harness.capabilities.context import open_context

    ctx = open_context(root, HUMAN)
    claim = ctx.repo.get_claim(ctx.repo.list_claims()[0].id)
    evidence = {item.id: item for item in ctx.repo.iter_evidence(WORK)}

    assessment = assess_strength(StrengthInput.from_claim(claim, evidence))

    assert str(claim.id) == claim_id
    assert assessment.support_count == 0.0
    assert assessment.qualifier_count == 1
    assert assessment.status is ClaimStatus.UNSUPPORTED
    assert any("cannot directly support a measured value" in item for item in assessment.reasons)
    assert any("42.E" in item for item in assessment.reasons)


def test_the_audit_records_the_floor_rather_than_the_requested_strength(
    author_claim: tuple[Path, str],
) -> None:
    """The whole audit path, not just the ladder: the Claim on disk says `unsupported`."""
    from research_harness.capabilities.context import open_context

    root, claim_id = author_claim
    ctx = open_context(root, HUMAN)
    service = ClaimService(ctx)

    audited, result, _ = service.audit(ctx.repo.list_claims()[0].id)

    assert str(audited.id) == claim_id
    assert audited.status is ClaimStatus.UNSUPPORTED
    assert audited.allowed_strength is ClaimScope.INDIVIDUAL
    # The relation the researcher declared is still reported as declared; what the audit
    # refuses is to let it *count*, which is where §42.E actually bites.
    assert result.support == (EvidenceId("E0001"),)
    assert result.assessment.support_count == 0.0
    assert result.assessment.qualifier_count == 1
    assert result.assessment.status is ClaimStatus.UNSUPPORTED


def test_author_origins_are_named_by_the_engine_rather_than_inferred() -> None:
    """The rule is a table a researcher can read, not a condition buried in a branch."""
    assert (
        frozenset({EvidenceOrigin.AUTHOR_CLAIMED, EvidenceOrigin.AUTHOR_INTERPRETED})
        == AUTHOR_ORIGINS
    )


# ----------------------------------------------------------------- the transition refuses


def _candidate(origin: EvidenceOrigin, evidence_id: str = "E0009") -> Evidence:
    """A minimal proposed candidate; only its origin matters to these tests."""
    return Evidence(
        id=EvidenceId(evidence_id),
        source=SourceAnchor(
            work=WORK,
            version="V0001-1",
            artifact="A0001-1",
            file_hash=f"sha256:{'a' * 64}",
            block=BlockId("B0007"),
            text_hash=f"sha256:{'b' * 64}",
            page=3,
        ),
        content=EvidenceContent(exact_text=AUTHOR_TEXT),
        origin=origin,
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
        strength=EvidenceStrength.DIRECT,
        provenance=Provenance.model(MODEL_ACTOR),
    )


def test_model_proposed_can_never_become_source_observed() -> None:
    """There is no automatic promotion, and none for a researcher either (Product §42.E)."""
    candidate = _candidate(EvidenceOrigin.MODEL_PROPOSED)

    with pytest.raises(TransitionError, match="may never become source_observed"):
        reclassify_origin(
            candidate,
            EvidenceOrigin.SOURCE_OBSERVED,
            actor=HUMAN,
            rationale="I read the span myself",
        )


def test_a_model_actor_may_not_reclassify_any_origin() -> None:
    candidate = _candidate(EvidenceOrigin.AUTHOR_CLAIMED)

    with pytest.raises(AuthorityError, match="only a human actor"):
        reclassify_origin(
            candidate,
            EvidenceOrigin.SOURCE_OBSERVED,
            actor=MODEL_ACTOR,
            rationale="the table says so",
        )


def test_a_reclassification_without_a_rationale_is_refused() -> None:
    """An invisible epistemic change is the failure mode; the rationale is what prevents it."""
    from research_harness.domain.errors import DomainValidationError

    candidate = _candidate(EvidenceOrigin.AUTHOR_CLAIMED)

    with pytest.raises(DomainValidationError, match="rationale"):
        reclassify_origin(candidate, EvidenceOrigin.SOURCE_OBSERVED, actor=HUMAN, rationale="   ")


def test_a_researcher_reclassification_is_recorded_on_the_object() -> None:
    """When it is allowed it is still visible: the rationale travels with the evidence."""
    candidate = _candidate(EvidenceOrigin.AUTHOR_CLAIMED)

    reclassified = reclassify_origin(
        candidate,
        EvidenceOrigin.SOURCE_OBSERVED,
        actor=HUMAN,
        rationale="Table 1 prints the value; the prose only repeats it",
    )

    assert reclassified.origin is EvidenceOrigin.SOURCE_OBSERVED
    assert reclassified.verification.rationale == (
        "Table 1 prints the value; the prose only repeats it"
    )
    assert reclassified.verification.reviewed_at is not None


def test_a_role_may_not_assign_a_model_proposed_origin_to_quoted_text() -> None:
    """The other end of the same rule: an extractor cannot label its own reading either."""
    assert EvidenceOrigin.MODEL_PROPOSED not in EXTRACTOR_ALLOWED_ORIGINS

    with pytest.raises(ValueError, match="may not assign origin"):
        EvidenceCandidateOutput(
            exact_text=AUTHOR_TEXT,
            block="B0007",
            char_start=0,
            char_end=len(AUTHOR_TEXT),
            origin=EvidenceOrigin.MODEL_PROPOSED,
            evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
            strength=EvidenceStrength.DIRECT,
            field="metric_result",
        )


def test_the_workstation_loop_accepts_only_source_observed_numeric_evidence(
    workstation: Workstation,
) -> None:
    """The loop's own numeric object is `source_observed`, read from the table itself."""
    ctx = workstation.context()
    numeric = next(
        record
        for record in ctx.repo.iter_evidence(workstation.work)
        if record.content.numeric is not None
    )

    assert numeric.origin is EvidenceOrigin.SOURCE_OBSERVED
    assert numeric.evidence_type is EvidenceType.EXPERIMENTAL_RESULT

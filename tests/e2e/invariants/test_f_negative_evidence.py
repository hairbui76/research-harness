"""Product §42.F - Negative-evidence discipline.

"`not_reported` cannot be converted to `absent` without an explicit review path."

Absence has two failure modes and this file covers both. The first is the *state*: a
search that found nothing records `not_found` or `not_reported`, and only an audited human
decision with recorded coverage turns that into `absent` (Product §11). The second is the
*wording*: even a permitted absence claim opens with "we identified no work that ...", and
the audit refuses to hand anyone the sentence "no work exists" (ROADMAP 12.5).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    AcceptEvidenceRequest,
    CreateClaimRequest,
    RecordSearchRunRequest,
)
from research_harness.capabilities.handlers import (
    accept_decision,
    accept_evidence,
    create_claim,
    record_search_run,
)
from research_harness.claims.negative_evidence import (
    absence_wording,
    check_promotion,
    classify_absence,
    promote_absence,
)
from research_harness.claims.strength import ABSENCE_PHRASE
from research_harness.cli.app import app
from research_harness.discovery.absence import NO_WORK_EXISTS_REFUSAL
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimScopeSpec,
    ClaimSemantics,
    Coverage,
)
from research_harness.domain.enums import (
    ClaimScope,
    ClaimType,
    DecisionStatus,
    DecisionType,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    NegativeEvidenceState,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import AuthorityError, TransitionError
from research_harness.domain.evidence import Evidence, EvidenceContent, SourceAnchor
from research_harness.domain.ids import (
    BlockId,
    ClaimId,
    DecisionId,
    EvidenceId,
    SearchRunId,
)
from research_harness.domain.research import Decision, SearchRun
from research_harness.domain.transitions import (
    negative_state_from_search,
    promote_negative_state,
)
from research_harness.roles.schemas import (
    EXTRACTOR_ALLOWED_NEGATIVE_STATES,
    EvidenceCandidateOutput,
)
from tests.e2e.invariants.workstation import HUMAN, MODEL_ACTOR, WORK, init_and_ingest

ABSENCE_EVIDENCE = EvidenceId("E0001")
ABSENCE_CLAIM = ClaimId("C0001")
DECISION = DecisionId("D0001")
SEARCH_RUN = SearchRunId("SR0001")
UNIVERSE = "peer-reviewed work on protocol-field traffic representation"
CUTOFF = "2026-08"

runner = CliRunner()


def not_reported_evidence(ctx: CapabilityContext) -> Evidence:
    """Accepted evidence recording that the source does not report the property.

    Anchored in a real block: an absence record still says *where* nobody looked in vain.
    """
    artifact = next(iter(ctx.repo.list_artifacts(WORK)))
    block = next(iter(ctx.repo.iter_blocks(artifact.id, work=WORK)))
    return Evidence(
        id=ABSENCE_EVIDENCE,
        source=SourceAnchor(
            work=WORK,
            version=artifact.version,
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId(str(block.id)),
            text_hash=block.text_hash,
            page=block.page,
        ),
        content=EvidenceContent(
            exact_text="",
            negative_state=NegativeEvidenceState.NOT_REPORTED,
            field="protocol_field_representation",
        ),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.LIMITATION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_2,
        provenance=Provenance.human(HUMAN),
    )


def search_run(*, cutoff: date = date(2026, 8, 1)) -> SearchRun:
    """One recorded, completed search run: the only thing that licenses an absence claim."""
    return SearchRun(
        id=SEARCH_RUN,
        question="does any surveyed system represent traffic at the protocol-field level?",
        sources=("openalex",),
        queries=("protocol field traffic representation",),
        executed_at=datetime(2026, 8, 20, tzinfo=UTC),
        cutoff=cutoff,
        provenance=Provenance.human(HUMAN),
    )


def absence_decision(status: DecisionStatus) -> Decision:
    return Decision(
        id=DECISION,
        type=DecisionType.METHODOLOGY,
        status=status,
        title="the corpus is complete enough to report an absence",
        rationale="every declared source was searched to exhaustion and rerun once",
        claim=ABSENCE_CLAIM,
        provenance=Provenance.human(HUMAN),
    )


def absence_claim(*, search_runs: tuple[SearchRunId, ...] = (SEARCH_RUN,)) -> Claim:
    return Claim(
        id=ABSENCE_CLAIM,
        statement="No surveyed system represents traffic at the protocol-field level",
        type=ClaimType.ABSENCE,
        semantics=ClaimSemantics(
            subject="surveyed_systems",
            predicate="represent",
            object="traffic at the protocol-field level",
        ),
        scope=ClaimScopeSpec(
            level=ClaimScope.UNIVERSAL_OR_ABSENCE, corpus=UNIVERSE, publication_until=CUTOFF
        ),
        coverage=Coverage(
            relevant_works=1,
            examined_works=1,
            cutoff=date(2026, 8, 1),
            search_runs=search_runs,
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.UNIVERSAL_OR_ABSENCE,
            allowed_strength=ClaimScope.INDIVIDUAL,
        ),
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture(scope="module")
def absence_workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A workspace holding one `not_reported` evidence object, a run, and an absence claim."""
    ctx = init_and_ingest(tmp_path_factory.mktemp("absence") / "project", name="absence")
    accept_evidence(
        ctx,
        AcceptEvidenceRequest(
            candidate=not_reported_evidence(ctx),
            verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
            rationale="the paper says nothing about protocol-field representation",
        ),
    )
    record_search_run(ctx, RecordSearchRunRequest(search_run=search_run()))
    create_claim(ctx, CreateClaimRequest(claim=absence_claim()))
    yield ctx.root


# ------------------------------------------------------------------- the state transition


def test_a_search_with_no_hits_never_produces_absent() -> None:
    """Product §11: zero hits is a fact about the search, not about the world."""
    assert negative_state_from_search(0, exhaustive=True) is NegativeEvidenceState.NOT_FOUND
    assert negative_state_from_search(0, exhaustive=False) is NegativeEvidenceState.UNCLEAR
    assert NegativeEvidenceState.ABSENT not in {
        negative_state_from_search(0, exhaustive=flag) for flag in (True, False)
    }


def test_the_absence_classifier_never_returns_absent_either() -> None:
    """The strongest state a search inside one work can reach is `not_reported`."""
    from research_harness.claims.negative_evidence import SearchEffort

    broad = SearchEffort(
        sections_searched=("Method", "Results"),
        tables_searched=True,
        synonyms=("field-level", "header-field"),
        structured_fields_checked=("representation",),
    )
    narrow = SearchEffort(sections_searched=("Method",))
    nothing = SearchEffort()

    assert broad.hits == 0 and broad.is_broad
    assert classify_absence(broad) is NegativeEvidenceState.NOT_REPORTED
    assert classify_absence(narrow) is NegativeEvidenceState.NOT_FOUND
    assert classify_absence(nothing) is NegativeEvidenceState.UNCLEAR


def test_not_found_must_become_not_reported_before_it_can_be_audited() -> None:
    """`not_found` is a missing lexical hit; broadening the search is the next step."""
    check = check_promotion(
        NegativeEvidenceState.NOT_FOUND,
        NegativeEvidenceState.ABSENT,
        decision=absence_decision(DecisionStatus.ACCEPTED),
        actor=HUMAN,
        coverage=absence_claim().coverage,
        search_runs_recorded=1,
    )

    assert check.allowed is False
    assert any("not an absence" in reason for reason in check.reasons)
    assert any("'not_reported' before auditing it" in reason for reason in check.reasons)


def test_a_model_actor_may_not_promote_an_absence(absence_workspace: Path) -> None:
    from research_harness.capabilities.context import open_context

    ctx = open_context(absence_workspace, MODEL_ACTOR)
    evidence = next(iter(ctx.repo.iter_evidence(WORK)))

    with pytest.raises(AuthorityError, match="human actor"):
        promote_absence(
            evidence,
            decision=absence_decision(DecisionStatus.ACCEPTED),
            actor=MODEL_ACTOR,
            coverage=absence_claim().coverage,
        )


@pytest.mark.parametrize(
    ("decision_status", "coverage", "runs", "expected"),
    [
        pytest.param(
            DecisionStatus.PROPOSED,
            absence_claim().coverage,
            1,
            "accepted",
            id="a proposed decision authorises nothing",
        ),
        pytest.param(
            DecisionStatus.ACCEPTED,
            Coverage(relevant_works=1, examined_works=1),
            1,
            "publication cutoff",
            id="coverage with no cutoff",
        ),
        pytest.param(
            DecisionStatus.ACCEPTED,
            absence_claim(search_runs=()).coverage,
            0,
            "no search run is recorded",
            id="no recorded search",
        ),
    ],
)
def test_every_missing_piece_of_the_audited_path_refuses_the_promotion(
    absence_workspace: Path,
    decision_status: DecisionStatus,
    coverage: Coverage,
    runs: int,
    expected: str,
) -> None:
    """Human actor, accepted Decision, cutoff, and a recorded run: all four, or nothing."""
    from research_harness.capabilities.context import open_context

    ctx = open_context(absence_workspace, HUMAN)
    evidence = next(iter(ctx.repo.iter_evidence(WORK)))

    with pytest.raises(TransitionError, match=expected):
        promote_absence(
            evidence,
            decision=absence_decision(decision_status),
            actor=HUMAN,
            coverage=coverage,
            search_runs_recorded=runs,
        )


def test_the_complete_audited_path_promotes_and_records_the_decision(
    absence_workspace: Path,
) -> None:
    """The one way through: a researcher, an accepted Decision, and recorded coverage."""
    from research_harness.capabilities.context import open_context

    ctx = open_context(absence_workspace, HUMAN)
    evidence = next(iter(ctx.repo.iter_evidence(WORK)))

    promoted = promote_absence(
        evidence,
        decision=absence_decision(DecisionStatus.ACCEPTED),
        actor=HUMAN,
        coverage=absence_claim().coverage,
        search_runs_recorded=1,
    )

    assert promoted.content.negative_state is NegativeEvidenceState.ABSENT
    assert DECISION in promoted.decisions
    assert promoted.verification.rationale


def test_promotion_to_anything_but_absent_is_not_an_audited_transition(
    absence_workspace: Path,
) -> None:
    from research_harness.capabilities.context import open_context

    ctx = open_context(absence_workspace, HUMAN)
    evidence = next(iter(ctx.repo.iter_evidence(WORK)))

    with pytest.raises(TransitionError, match="only promotion to 'absent'"):
        promote_negative_state(
            evidence,
            to_state=NegativeEvidenceState.NOT_FOUND,
            actor=HUMAN,
            decision=DECISION,
        )


def test_a_model_may_not_even_report_absent_as_an_extraction_result() -> None:
    """The audited conclusion is not in the extractor's vocabulary at all (ADR-003)."""
    assert NegativeEvidenceState.ABSENT not in EXTRACTOR_ALLOWED_NEGATIVE_STATES

    with pytest.raises(ValueError, match="audited conclusion"):
        EvidenceCandidateOutput(
            block="B0007",
            origin=EvidenceOrigin.SOURCE_OBSERVED,
            evidence_type=EvidenceType.LIMITATION,
            strength=EvidenceStrength.DIRECT,
            field="protocol_field_representation",
            negative_state=NegativeEvidenceState.ABSENT,
        )


# ------------------------------------------------------------------------- the wording


def run_cli(*args: str) -> Result:
    return runner.invoke(app, list(args))


def test_the_coverage_audit_refuses_no_work_exists_when_nothing_was_searched(
    tmp_path: Path,
) -> None:
    """The CLI path a researcher takes, with the search record that does not support it."""
    ctx = init_and_ingest(tmp_path / "unsearched", name="unsearched")
    create_claim(ctx, CreateClaimRequest(claim=absence_claim(search_runs=())))

    result = run_cli(
        "coverage",
        str(ABSENCE_CLAIM),
        "--workspace",
        str(ctx.root),
        "--universe",
        UNIVERSE,
        "--cutoff",
        CUTOFF,
        "--json",
    )

    assert result.exit_code == 0, result.stdout
    report: dict[str, Any] = json.loads(result.stdout)
    assert report["permitted"] is False
    assert report["wording"] is None
    assert NO_WORK_EXISTS_REFUSAL in report["reasons"]
    assert any("no search run is recorded" in reason for reason in report["reasons"])


def test_the_refusal_names_the_strongest_honest_form() -> None:
    """A refusal that does not say what *is* available just gets worked around."""
    assert "'no work exists' is not available" in NO_WORK_EXISTS_REFUSAL
    assert ABSENCE_PHRASE in NO_WORK_EXISTS_REFUSAL


def test_permitted_absence_wording_is_hedged_and_names_the_bound() -> None:
    """Even when the record permits it, the sentence is bounded by corpus and cutoff."""
    claim = absence_claim()

    wording = absence_wording(claim.scope, claim.coverage, (search_run(),))

    assert wording.startswith(f"Within the {UNIVERSE} corpus up to {CUTOFF}")
    assert ABSENCE_PHRASE in wording
    assert "no work exists" not in wording.lower()
    assert "1 source" in wording and "1 recorded search run" in wording


def test_absence_wording_without_recorded_coverage_raises_rather_than_hedging() -> None:
    from research_harness.domain.errors import DomainValidationError

    claim = absence_claim(search_runs=())

    with pytest.raises(DomainValidationError, match="recorded search coverage"):
        absence_wording(claim.scope, claim.coverage, ())


def test_an_accepted_decision_is_what_the_audited_path_costs(
    absence_workspace: Path, tmp_path: Path
) -> None:
    """The Decision is canonical, so the absence conclusion stays inspectable (Product §38)."""
    from research_harness.capabilities.context import open_context

    ctx = open_context(absence_workspace, HUMAN)
    accept_decision(ctx, AcceptDecisionRequest(decision=absence_decision(DecisionStatus.PROPOSED)))

    stored = ctx.repo.get_decision(DECISION)
    assert stored.status is DecisionStatus.ACCEPTED
    assert stored.claim == ABSENCE_CLAIM
    assert stored.provenance.actor == HUMAN

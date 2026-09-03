"""Product §42.G - Claim-strength discipline.

"A claim with incomplete coverage is prevented from silently escalating from corpus-level
to universal wording."

Three things have to be true at once, and each is checked against a workspace the loop
really built: an L3 ask over thin coverage is *capped*, universal wording needs coverage
nobody in this fixture has, and the researcher can still overrule the auditor - but only by
leaving an accepted `epistemic_override` Decision behind (Product §38, ADR-007).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.claims.service import ClaimService
from research_harness.claims.strength import (
    FIELD_WORDING,
    L3_MIN_INDEPENDENT_WORKS,
    UNIVERSAL_WORDING,
)
from research_harness.cli.app import app
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
    DecisionStatus,
    DecisionType,
)
from research_harness.domain.errors import AuthorityError, TransitionError
from research_harness.domain.ids import ClaimId, DecisionId, EvidenceId
from research_harness.domain.research import Decision
from research_harness.domain.transitions import override_claim_strength
from tests.e2e.invariants.workstation import (
    HUMAN,
    MODEL_ACTOR,
    WORK,
    Workstation,
    build_workstation,
)

runner = CliRunner()

OVERREACHING = "Existing work generally tokenizes encrypted traffic heterogeneously"
UNIVERSAL = "No existing system, without exception, tokenizes encrypted traffic uniformly"


def run(*args: str) -> Result:
    return runner.invoke(app, list(args))


def make_claim(
    ctx: CapabilityContext, statement: str, requested: ClaimScope, evidence: tuple[EvidenceId, ...]
) -> ClaimId:
    """A Claim asking for ``requested`` over exactly the evidence this workspace holds."""
    service = ClaimService(ctx)
    claim, _ = service.create(
        statement,
        type=ClaimType.PREVALENCE,
        semantics=ClaimSemantics(
            subject="existing_systems", predicate="use", object="traffic_tokenization"
        ),
        scope=ClaimScopeSpec(level=requested, corpus="structured-traffic-llm"),
        requested_strength=requested,
        relations=tuple(
            ClaimEvidenceRelation(evidence=item, relation=ClaimEvidenceRelationType.SUPPORTS)
            for item in evidence
        ),
        coverage=Coverage(relevant_works=12, examined_works=1, unresolved_works=11),
    )
    return claim.id


@pytest.fixture(scope="module")
def thin(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, ClaimId, ClaimId]]:
    """One workspace, two overreaching Claims: one asking L3, one asking L4."""
    station: Workstation = build_workstation(tmp_path_factory.mktemp("strength") / "project")
    ctx = open_context(station.root, HUMAN)
    field_level = make_claim(ctx, OVERREACHING, ClaimScope.FIELD_GENERALIZATION, station.evidence)
    universal = make_claim(ctx, UNIVERSAL, ClaimScope.UNIVERSAL_OR_ABSENCE, station.evidence)
    yield station.root, field_level, universal


# --------------------------------------------------------------------------- the cap


def test_an_l3_ask_over_one_examined_work_is_capped(
    thin: tuple[Path, ClaimId, ClaimId],
) -> None:
    """Incomplete coverage is measured, not judged: one work out of twelve is not a field."""
    root, field_level, _ = thin
    audited = json.loads(
        run("claim", "audit", str(field_level), "--workspace", str(root), "--json").stdout
    )

    assert audited["requested_strength"] == ClaimScope.FIELD_GENERALIZATION.value
    assert audited["allowed_level"] < audited["requested_level"]
    assert audited["escalation_prevented"] is True
    assert audited["status"] == ClaimStatus.QUALIFIED.value


def test_the_audit_names_the_requirement_that_failed(
    thin: tuple[Path, ClaimId, ClaimId],
) -> None:
    """A refusal a researcher can argue with names the level and the count it needed."""
    root, field_level, _ = thin
    audited = json.loads(
        run("claim", "audit", str(field_level), "--workspace", str(root), "--json").stdout
    )

    assert audited["reasons"], "the audit must say why the requested scope was refused"
    assert any(str(L3_MIN_INDEPENDENT_WORKS) in reason for reason in audited["reasons"])


def test_the_recorded_wording_is_weaker_than_the_wording_that_was_asked_for(
    thin: tuple[Path, ClaimId, ClaimId],
) -> None:
    """The point of §42.G: the sentence the Claim licenses moves down the ladder with it."""
    root, field_level, _ = thin
    audited = json.loads(
        run("claim", "audit", str(field_level), "--workspace", str(root), "--json").stdout
    )

    assert audited["maximum_defensible_wording"] not in {FIELD_WORDING, UNIVERSAL_WORDING}


def test_universal_wording_needs_coverage_this_record_does_not_have(
    thin: tuple[Path, ClaimId, ClaimId],
) -> None:
    """L4 is the strictest rung; a claim asking for it lands at the same measured floor."""
    root, _, universal = thin
    audited = json.loads(
        run("claim", "audit", str(universal), "--workspace", str(root), "--json").stdout
    )

    assert audited["requested_strength"] == ClaimScope.UNIVERSAL_OR_ABSENCE.value
    assert audited["allowed_strength"] != ClaimScope.UNIVERSAL_OR_ABSENCE.value
    assert audited["maximum_defensible_wording"] != UNIVERSAL_WORDING
    assert audited["escalation_prevented"] is True


def test_an_audit_never_raises_a_modest_ask(tmp_path: Path) -> None:
    """The ladder caps; it does not promote. Good evidence for L0 stays L0."""
    station = build_workstation(tmp_path / "modest")
    ctx = open_context(station.root, HUMAN)
    modest = make_claim(
        ctx, "TrafficLM reports F1 on CICIDS2017", ClaimScope.INDIVIDUAL, station.evidence
    )

    audited = json.loads(
        run("claim", "audit", str(modest), "--workspace", str(station.root), "--json").stdout
    )

    assert audited["allowed_strength"] == ClaimScope.INDIVIDUAL.value
    assert audited["escalation_prevented"] is False


# ----------------------------------------------------------------------- the override


def test_an_override_writes_an_accepted_decision_and_only_then_moves_the_claim(
    tmp_path: Path,
) -> None:
    """Product §38: the researcher keeps authority, and the override stays visible."""
    station = build_workstation(tmp_path / "override")
    ctx = open_context(station.root, HUMAN)
    claim_id = make_claim(ctx, OVERREACHING, ClaimScope.FIELD_GENERALIZATION, station.evidence)
    service = ClaimService(ctx)
    before, _, _ = service.audit(claim_id)

    overridden, decision, mutation = service.override(
        claim_id,
        selected=ClaimScope.FIELD_GENERALIZATION,
        rationale="the eleven unresolved works are out of scope for this survey",
    )

    assert decision.type is DecisionType.EPISTEMIC_OVERRIDE
    assert decision.status is DecisionStatus.ACCEPTED
    assert decision.auditor_recommendation is before.allowed_strength
    assert decision.researcher_selected is ClaimScope.FIELD_GENERALIZATION
    assert overridden.allowed_strength is ClaimScope.FIELD_GENERALIZATION
    assert decision.id in overridden.decisions
    assert mutation.event.event.value == "claim.overridden"
    assert ctx.repo.get_decision(decision.id).status is DecisionStatus.ACCEPTED


def test_a_model_actor_may_not_override_the_auditor(tmp_path: Path) -> None:
    station = build_workstation(tmp_path / "model-override")
    human = open_context(station.root, HUMAN)
    claim_id = make_claim(human, OVERREACHING, ClaimScope.FIELD_GENERALIZATION, station.evidence)
    ClaimService(human).audit(claim_id)

    model = open_context(station.root, MODEL_ACTOR)
    with pytest.raises(AuthorityError, match="only a human actor"):
        ClaimService(model).override(
            claim_id, selected=ClaimScope.FIELD_GENERALIZATION, rationale="the corpus is fine"
        )


def test_an_override_without_a_rationale_is_refused(tmp_path: Path) -> None:
    """An invisible override is the failure this Decision exists to prevent."""
    from research_harness.domain.errors import DomainValidationError

    station = build_workstation(tmp_path / "no-rationale")
    ctx = open_context(station.root, HUMAN)
    claim_id = make_claim(ctx, OVERREACHING, ClaimScope.FIELD_GENERALIZATION, station.evidence)
    ClaimService(ctx).audit(claim_id)

    with pytest.raises(DomainValidationError, match="rationale"):
        ClaimService(ctx).override(
            claim_id, selected=ClaimScope.FIELD_GENERALIZATION, rationale="   "
        )


def _override_decision(
    claim_id: ClaimId,
    *,
    status: DecisionStatus,
    kind: DecisionType,
    recommendation: ClaimScope,
    selected: ClaimScope,
    provenance: Provenance,
) -> Decision:
    return Decision(
        id=DecisionId("D0099"),
        type=kind,
        status=status,
        title="hand-built override",
        rationale="a decision that should not take effect",
        claim=claim_id,
        auditor_recommendation=recommendation,
        researcher_selected=selected,
        provenance=provenance,
    )


@pytest.mark.parametrize(
    ("status", "kind", "provenance", "expected"),
    [
        pytest.param(
            DecisionStatus.PROPOSED,
            DecisionType.EPISTEMIC_OVERRIDE,
            Provenance.human(HUMAN),
            "must be accepted",
            id="a proposed decision is not authority",
        ),
        pytest.param(
            DecisionStatus.ACCEPTED,
            DecisionType.EPISTEMIC_OVERRIDE,
            Provenance.model(MODEL_ACTOR),
            "authored by the researcher",
            id="a decision a model wrote",
        ),
    ],
)
def test_the_transition_refuses_an_override_that_is_not_a_researcher_decision(
    thin: tuple[Path, ClaimId, ClaimId],
    status: DecisionStatus,
    kind: DecisionType,
    provenance: Provenance,
    expected: str,
) -> None:
    """Escalation always costs an accepted, human-authored `epistemic_override`."""
    root, field_level, _ = thin
    ctx = open_context(root, HUMAN)
    claim = ctx.repo.get_claim(field_level)
    decision = _override_decision(
        claim.id,
        status=status,
        kind=kind,
        recommendation=claim.allowed_strength,
        selected=ClaimScope.FIELD_GENERALIZATION,
        provenance=provenance,
    )

    with pytest.raises((TransitionError, AuthorityError), match=expected):
        override_claim_strength(claim, decision)


def test_a_decision_of_the_wrong_type_cannot_override_a_claim(
    thin: tuple[Path, ClaimId, ClaimId],
) -> None:
    """Two gates, both closed: the domain refuses the shape, the transition refuses the type."""
    root, field_level, _ = thin
    ctx = open_context(root, HUMAN)
    claim = ctx.repo.get_claim(field_level)

    with pytest.raises(ValueError, match="belong to epistemic_override"):
        _override_decision(
            claim.id,
            status=DecisionStatus.ACCEPTED,
            kind=DecisionType.METHODOLOGY,
            recommendation=claim.allowed_strength,
            selected=ClaimScope.FIELD_GENERALIZATION,
            provenance=Provenance.human(HUMAN),
        )

    methodology = Decision(
        id=DecisionId("D0098"),
        type=DecisionType.METHODOLOGY,
        status=DecisionStatus.ACCEPTED,
        title="a methodology note",
        rationale="not an override",
        claim=claim.id,
        provenance=Provenance.human(HUMAN),
    )
    with pytest.raises(TransitionError, match="epistemic_override"):
        override_claim_strength(claim, methodology)


def test_an_override_may_not_exceed_what_was_requested(
    thin: tuple[Path, ClaimId, ClaimId],
) -> None:
    """The researcher may overrule the auditor, not their own recorded ask."""
    root, field_level, _ = thin
    ctx = open_context(root, HUMAN)
    claim = ctx.repo.get_claim(field_level)
    decision = _override_decision(
        claim.id,
        status=DecisionStatus.ACCEPTED,
        kind=DecisionType.EPISTEMIC_OVERRIDE,
        recommendation=claim.allowed_strength,
        selected=ClaimScope.UNIVERSAL_OR_ABSENCE,
        provenance=Provenance.human(HUMAN),
    )

    with pytest.raises(TransitionError, match="exceeds the requested"):
        override_claim_strength(claim, decision)


def test_the_corpus_holds_one_decision_per_override(tmp_path: Path) -> None:
    """Overrides accumulate as history rather than replacing one another."""
    station = build_workstation(tmp_path / "history")
    ctx = open_context(station.root, HUMAN)
    claim_id = make_claim(ctx, OVERREACHING, ClaimScope.FIELD_GENERALIZATION, station.evidence)
    service = ClaimService(ctx)
    service.audit(claim_id)
    service.override(
        claim_id,
        selected=ClaimScope.FIELD_GENERALIZATION,
        rationale="the eleven unresolved works are out of scope",
    )

    decisions = service.override_history(claim_id)
    assert [decision.type for decision in decisions] == [DecisionType.EPISTEMIC_OVERRIDE]
    assert len(list((station.root / "decisions").glob("*.yaml"))) == 1


def test_the_workspace_never_carried_a_universal_claim(
    thin: tuple[Path, ClaimId, ClaimId],
) -> None:
    """Nothing in the loop, in the audit, or in the override reaches L4 (Product §42.G)."""
    root, _, _ = thin
    ctx = open_context(root, HUMAN)

    allowed = {claim.allowed_strength for claim in ctx.repo.list_claims()}
    assert ClaimScope.UNIVERSAL_OR_ABSENCE not in allowed
    assert WORK in {work.id for work in ctx.repo.list_works()}

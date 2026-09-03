"""Product §42.I - Stale propagation.

"Changing an accepted taxonomy marks dependent matrices/Claims/manuscript anchors stale."

Product §37 draws the chain `Taxonomy Decision -> classifications -> matrix -> Claim ->
manuscript §3.1`, and ADR-008 says the downstream objects are *marked*, never rewritten.
Both halves are checked here on a workspace the loop built: the revision's own stale set,
the same set recomputed from canonical files after a rebuild, and a byte-for-byte
comparison proving nothing downstream moved.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.claims.service import ClaimService
from research_harness.domain.claim import (
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
    Coverage,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    StaleState,
)
from research_harness.domain.ids import ClaimId, SynthesisId
from research_harness.manuscript.attach import ManuscriptService
from research_harness.projection.dependencies import (
    StaleMark,
    StalePriority,
    load_stale_marks,
)
from research_harness.projection.rebuild import rebuild_workspace
from research_harness.projection.rows import manuscript_anchor_key
from research_harness.projection.schema import create_engine_for
from research_harness.synthesis import ClassificationRule, SynthesisService
from research_harness.workspace.events import object_digest
from tests.e2e.invariants.workstation import (
    HUMAN,
    SUPPORTED_LINE,
    Workstation,
    build_workstation,
    canonical_bytes_digest,
)

FIELD = "representation"
FIRST_TERMS = ("raw_sequential", "field_based")
SECOND_TERMS = ("raw_sequential", "field_based", "behaviour_aware")
MATRIX = SynthesisId("S0001")
SYNTHESIS_CLAIM = ClaimId("C0003")

RULES: tuple[ClassificationRule, ...] = (
    ClassificationRule(term="raw_sequential", field=FIELD, any_of=("CICIDS2017", "held-out")),
    ClassificationRule(term="field_based", field=FIELD, any_of=("header field",)),
    ClassificationRule(term="behaviour_aware", field=FIELD, any_of=("flow behaviour",)),
)


def read_off_the_matrix(ctx: CapabilityContext) -> ClaimId:
    """A synthesis Claim derived from the matrix, so the chain reaches a Claim."""
    matrix = ctx.repo.get_matrix(MATRIX)
    cited = tuple(
        ClaimEvidenceRelation(evidence=value, relation=ClaimEvidenceRelationType.SUPPORTS)
        for cell in matrix.cells
        for value in cell.evidence
    )
    claim, _ = ClaimService(ctx).create(
        "The examined corpus classifies as raw-sequential under the current taxonomy",
        type=ClaimType.SYNTHESIS,
        semantics=ClaimSemantics(
            subject="examined_systems", predicate="classify_as", object="raw_sequential"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.OBSERVED_SUBSET, corpus="structured-traffic"),
        requested_strength=ClaimScope.OBSERVED_SUBSET,
        relations=cited,
        coverage=Coverage(relevant_works=1, examined_works=1),
        derived_from=(matrix.id,),
    )
    return claim.id


@pytest.fixture
def chain(tmp_path: Path) -> Iterator[tuple[Workstation, CapabilityContext, str]]:
    """Taxonomy -> matrix -> synthesis Claim -> manuscript anchor, all accepted and fresh."""
    station = build_workstation(tmp_path / "project")
    ctx = open_context(station.root, HUMAN)
    service = SynthesisService(ctx)
    service.revise_taxonomy(FIELD, FIRST_TERMS, "two families to start")
    service.build(FIELD, FIELD, tuple(rule for rule in RULES if rule.term in FIRST_TERMS))
    claim_id = read_off_the_matrix(ctx)
    anchor, _ = ManuscriptService(ctx).attach(("main.tex", SUPPORTED_LINE), claim_id)
    yield station, ctx, manuscript_anchor_key(anchor.file, anchor.sentence_fingerprint)


def stale_set(ctx: CapabilityContext) -> set[StaleMark]:
    """The stale set a rebuild derives from canonical files alone."""
    report = rebuild_workspace(ctx.repo)
    assert report.ok, report.invalid_files
    engine = create_engine_for(ctx.repo.layout.database_file)
    try:
        with engine.connect() as connection:
            return set(load_stale_marks(connection))
    finally:
        engine.dispose()


# ------------------------------------------------------------------------- the marking


def test_a_fresh_chain_has_nothing_stale(
    chain: tuple[Workstation, CapabilityContext, str],
) -> None:
    """Everything derived is newer than what it derives from, so nothing is marked."""
    _, ctx, _ = chain

    assert stale_set(ctx) == set()
    assert ctx.repo.get_matrix(MATRIX).stale is StaleState.FRESH
    assert all(claim.stale is StaleState.FRESH for claim in ctx.repo.list_claims())


def test_a_taxonomy_revision_marks_the_matrix_the_claim_and_the_anchor(
    chain: tuple[Workstation, CapabilityContext, str],
) -> None:
    """The whole Product §37 chain, in one mutation's own stale set."""
    _, ctx, anchor_key = chain
    revised = SynthesisService(ctx).revise_taxonomy(
        FIELD, SECOND_TERMS, "behaviour-aware systems no longer fit either family"
    )

    marked = {mark.object_id: mark for mark in revised.stale}
    assert str(MATRIX) in marked
    assert any(key.startswith("C") for key in marked)
    assert anchor_key in marked


def test_the_stale_set_is_ordered_by_scientific_impact(
    chain: tuple[Workstation, CapabilityContext, str],
) -> None:
    """Product §37: manuscript first, then Claim, then synthesis, then classification."""
    _, ctx, anchor_key = chain
    revised = SynthesisService(ctx).revise_taxonomy(FIELD, SECOND_TERMS, "a third family")

    marked = {mark.object_id: mark for mark in revised.stale}
    priorities = [mark.priority for mark in revised.stale]

    assert priorities == sorted(priorities, reverse=True)
    assert marked[anchor_key].priority is StalePriority.MANUSCRIPT_ANCHOR
    assert marked[str(MATRIX)].priority is StalePriority.SYNTHESIS
    assert {mark.priority for key, mark in marked.items() if key.startswith("C")} == {
        StalePriority.CLAIM
    }


def test_a_rebuild_from_canonical_files_reaches_the_same_conclusion(
    chain: tuple[Workstation, CapabilityContext, str],
) -> None:
    """The stale set is derived, not stored: deleting `.research/` cannot lose it."""
    _, ctx, anchor_key = chain
    SynthesisService(ctx).revise_taxonomy(FIELD, SECOND_TERMS, "a third family")

    recomputed = {mark.object_id for mark in stale_set(ctx)}

    assert str(MATRIX) in recomputed
    assert anchor_key in recomputed
    assert any(key.startswith("C") for key in recomputed)


# ---------------------------------------------------------------------- nothing rewritten


def test_the_revision_rewrites_nothing_downstream(
    chain: tuple[Workstation, CapabilityContext, str],
) -> None:
    """ADR-008: a stale object is an invitation to look, not a silent recomputation."""
    _, ctx, _ = chain
    matrix_before = ctx.repo.layout.matrix_file(MATRIX).read_bytes()
    claims_before = {claim.id: object_digest(claim) for claim in ctx.repo.list_claims()}
    anchors_before = [object_digest(anchor) for anchor in ctx.repo.iter_anchors()]

    SynthesisService(ctx).revise_taxonomy(FIELD, SECOND_TERMS, "a third family")

    assert ctx.repo.layout.matrix_file(MATRIX).read_bytes() == matrix_before
    assert {claim.id: object_digest(claim) for claim in ctx.repo.list_claims()} == claims_before
    assert [object_digest(anchor) for anchor in ctx.repo.iter_anchors()] == anchors_before


def test_the_superseded_decision_stays_readable(
    chain: tuple[Workstation, CapabilityContext, str],
) -> None:
    """The record of why the project once classified things differently is the point."""
    _, ctx, _ = chain
    revised = SynthesisService(ctx).revise_taxonomy(FIELD, SECOND_TERMS, "a third family")

    assert revised.decision.supersedes is not None
    previous = ctx.repo.get_decision(revised.decision.supersedes)
    assert previous.taxonomy_terms == FIRST_TERMS
    assert ctx.repo.layout.decision_file(previous.id).is_file()


def test_reading_the_stale_set_changes_nothing(
    chain: tuple[Workstation, CapabilityContext, str],
) -> None:
    """Answering "what must I look at?" is a read, however many times it is asked."""
    station, ctx, _ = chain
    SynthesisService(ctx).revise_taxonomy(FIELD, SECOND_TERMS, "a third family")
    before = canonical_bytes_digest(station.root)

    first = stale_set(ctx)
    second = stale_set(ctx)

    assert first == second
    assert canonical_bytes_digest(station.root) == before

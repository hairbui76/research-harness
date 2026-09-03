"""Dogfood F2: `research coverage` computed a funnel that never reached the Claim.

From `docs/plans/dogfood-2026-09-03.md`:

    $ research coverage C0003 --universe "..." --cutoff 2025-08 ...
      funnel   discovered 515 -> screened 8 -> relevant 5 -> full_text_available 5 -> examined 5
    $ research claim audit C0003
      coverage: 0 of 0 relevant works examined, 0 unresolved; estimated overturn risk unknown
      reasons: - L2 corpus_pattern: the coverage record names no relevant works, so there is
        no corpus to generalize over

Two commands computed the same quantity and disagreed; the one the audit read was always
zero, so *every* literature-wide claim in that session was capped at L1 for a plumbing
reason. The fix is authoritative in both directions: `research coverage` persists the funnel
through `claim.update_coverage`, and an audit of a claim that records none derives one from
the claim's own search runs rather than reading zeros and refusing.

The scenario below is the dogfood's, shrunk to the same shape: five relevant works, five
examined, one recorded run.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import RecordSearchRunRequest
from research_harness.capabilities.handlers import record_search_run
from research_harness.claims.service import ClaimService
from research_harness.domain.base import Provenance
from research_harness.domain.claim import ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    IdentityResolutionOutcome,
    ScreeningState,
)
from research_harness.domain.ids import EvidenceId, SearchRunId, WorkId
from research_harness.domain.research import SearchCandidate, SearchResultCounts, SearchRun
from research_harness.domain.work import WorkCandidate
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.claims.conftest import make_evidence

HUMAN = "human:alice"
CUTOFF = "2025-08"
RELEVANT = 5

STATEMENT = "Reviewed pre-trained transformer systems do not share a tokenisation vocabulary"


def candidate_for(number: int) -> SearchCandidate:
    """One included, resolved, readable candidate that matched a corpus Work."""
    from research_harness.domain.base import utc_now

    return SearchCandidate(
        key=f"doi:10.5555/traffic-{number}",
        candidate=WorkCandidate(
            provenance=Provenance.system(actor="ingest"),
            resolution=IdentityResolutionOutcome.SAME_WORK,
            matched_work=WorkId.make(number),
            screening=ScreeningState.INCLUDED,
        ),
        sources=("arxiv", "openalex"),
        ranks={"arxiv": number, "openalex": number},
        screening=ScreeningState.INCLUDED,
        screened_by=HUMAN,
        screened_at=utc_now(),
        identity=IdentityResolutionOutcome.SAME_WORK,
        matched_work=WorkId.make(number),
        full_text_available=True,
    )


def dogfood_run() -> SearchRun:
    """The session's funnel, shrunk: five relevant works, all screened, all readable."""
    candidates = tuple(candidate_for(number) for number in range(1, RELEVANT + 1))
    return SearchRun(
        id=SearchRunId("SR0001"),
        question="pre-trained transformer encrypted traffic classification",
        sources=("arxiv", "openalex"),
        queries=("all:transformer AND all:traffic",),
        results=SearchResultCounts(
            discovered=len(candidates), screened=len(candidates), included=len(candidates)
        ),
        candidates=candidates,
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[CapabilityContext]:
    """Five works, five accepted evidence objects, one recorded search run, one claim."""
    root = tmp_path / "traffic"
    WorkspaceRepository.init(root, "dogfood-f2")
    ctx = open_context(root, HUMAN)
    _seed_corpus(ctx)
    record_search_run(ctx, RecordSearchRunRequest(search_run=dogfood_run()))
    yield ctx


def _seed_corpus(ctx: CapabilityContext) -> None:
    """Write five Works with one accepted Evidence each, straight into canonical state.

    Hand-built on purpose: this test is about what the audit *reads*, and ingesting five
    PDFs to prove a coverage rule would test the parser instead.
    """
    from research_harness.domain.enums import ResearchEventType
    from research_harness.domain.ids import ArtifactId, VersionId
    from research_harness.domain.research import ResearchEvent
    from research_harness.domain.work import Work
    from tests.unit.domain import strategies as sty

    event = ResearchEvent(
        event=ResearchEventType.WORK_INGESTED,
        subjects=(),
        actor=ctx.actor,
        occurred_at=ctx.now(),
        summary="test fixture: five works with one accepted evidence each",
    )
    with ctx.repo.transaction(event, ctx.actor) as tx:
        for number in range(1, RELEVANT + 1):
            work = WorkId.make(number)
            version = VersionId.make(number, 1)
            artifact = ArtifactId.make(number, 1)
            tx.put(
                Work(
                    id=work,
                    title=f"Traffic system {number}",
                    authors=(f"Author {number}",),
                    year=2022,
                    versions=(version,),
                    artifacts=(artifact,),
                    provenance=Provenance.human(HUMAN),
                )
            )
            tx.put(sty.make_version(id=version, work=work))
            tx.put(sty.make_artifact(id=artifact, work=work, version=version))
            tx.append_evidence(make_evidence(number, number))


def make_claim(ctx: CapabilityContext, requested: ClaimScope) -> str:
    """One claim over the five works, relating each work's evidence as support."""
    service = ClaimService(ctx)
    claim, _ = service.create(
        STATEMENT,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="reviewed systems", predicate="do not share", object="a tokenisation vocabulary"
        ),
        scope=ClaimScopeSpec(level=requested, corpus="pre-trained transformer traffic classifiers"),
        requested_strength=requested,
    )
    for number in range(1, RELEVANT + 1):
        service.relate(claim.id, EvidenceId.make(number), ClaimEvidenceRelationType.SUPPORTS)
    return str(claim.id)


# -- the defect, as the dogfood met it ---------------------------------------


def test_a_claim_with_no_recorded_coverage_still_audits_against_the_search_record(
    workspace: CapabilityContext,
) -> None:
    """The regression: `0 of 0 relevant works examined` is not what the record says."""
    from research_harness.domain.ids import ClaimId

    claim_id = ClaimId(make_claim(workspace, ClaimScope.CORPUS_PATTERN))
    service = ClaimService(workspace)

    _, result, _ = service.audit(claim_id)

    assert "0 of 0 relevant works" not in result.coverage_state
    assert f"{RELEVANT} of {RELEVANT} relevant works examined" in result.coverage_state
    assert "overturn risk unknown" not in result.coverage_state


def test_the_audit_reaches_l2_wording_instead_of_refusing_on_zero_of_zero(
    workspace: CapabilityContext,
) -> None:
    """The consequence F2 caused: every literature-wide claim capped at L1."""
    from research_harness.domain.ids import ClaimId

    claim_id = ClaimId(make_claim(workspace, ClaimScope.CORPUS_PATTERN))

    claim, result, _ = ClaimService(workspace).audit(claim_id)

    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert claim.allowed_strength is ClaimScope.CORPUS_PATTERN
    assert claim.status is not ClaimStatus.UNVERIFIED
    assert "l2.coverage_record" not in result.assessment.blocked_by
    assert not [
        reason
        for reason in result.assessment.reasons
        if "coverage record names no relevant works" in reason
    ], "the L2 refusal the dogfood hit was a plumbing artefact, not a finding"


def test_the_audit_names_the_runs_the_funnel_was_derived_from(
    workspace: CapabilityContext,
) -> None:
    """A derived number is honest only if the record says where it came from."""
    from research_harness.domain.ids import ClaimId

    claim_id = ClaimId(make_claim(workspace, ClaimScope.CORPUS_PATTERN))

    _, result, _ = ClaimService(workspace).audit(claim_id)

    derived = [warning for warning in result.warnings if warning.startswith("coverage:")]
    assert derived, "the audit must say the coverage was derived rather than recorded"
    assert "SR0001" in derived[0]
    assert "research coverage" in derived[0], "and say how to make it authoritative"


def test_a_derived_funnel_invents_no_publication_cutoff(
    workspace: CapabilityContext,
) -> None:
    """L4 asks for a cutoff; a search's own date is not the researcher's declaration."""
    from research_harness.domain.ids import ClaimId

    claim_id = ClaimId(make_claim(workspace, ClaimScope.CORPUS_PATTERN))
    claim = workspace.repo.get_claim(claim_id)

    derived = ClaimService(workspace).derived_coverage(claim)

    assert derived is not None
    coverage, runs = derived
    assert coverage.relevant_works == RELEVANT
    assert coverage.examined_works == RELEVANT
    assert coverage.cutoff is None
    assert [str(run) for run in runs] == ["SR0001"]


def test_deriving_never_overwrites_a_coverage_the_researcher_recorded(
    workspace: CapabilityContext,
) -> None:
    """`claim.update_coverage` is authoritative; derivation only fills a hole."""
    from research_harness.domain.claim import Coverage
    from research_harness.domain.enums import OverturnRisk
    from research_harness.domain.ids import ClaimId

    claim_id = ClaimId(make_claim(workspace, ClaimScope.CORPUS_PATTERN))
    service = ClaimService(workspace)
    recorded = Coverage(
        relevant_works=8,
        examined_works=2,
        unresolved_works=6,
        overturn_risk=OverturnRisk.HIGH,
        search_runs=(SearchRunId("SR0001"),),
    )
    service.record_coverage(claim_id, recorded)

    claim = workspace.repo.get_claim(claim_id)
    assert service.derived_coverage(claim) is None

    _, result, _ = service.audit(claim_id)
    assert "2 of 8 relevant works examined" in result.coverage_state
    assert not [warning for warning in result.warnings if warning.startswith("coverage:")]


def test_recording_coverage_is_what_the_audit_then_reads(
    workspace: CapabilityContext,
) -> None:
    """The other half of the fix: `research coverage` writes what `claim audit` reads."""
    from research_harness.domain.ids import ClaimId

    claim_id = ClaimId(make_claim(workspace, ClaimScope.CORPUS_PATTERN))
    service = ClaimService(workspace)
    claim = workspace.repo.get_claim(claim_id)
    derived = service.derived_coverage(claim)
    assert derived is not None

    stored, mutation = service.record_coverage(claim_id, derived[0])

    assert mutation.capability == "claim.update_coverage"
    assert stored.coverage.relevant_works == RELEVANT
    assert [str(run) for run in stored.coverage.search_runs] == ["SR0001"]
    _, result, _ = service.audit(claim_id)
    assert f"{RELEVANT} of {RELEVANT} relevant works examined" in result.coverage_state

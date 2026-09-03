"""Task 7.5: the researcher overrules the auditor, and the override stays visible.

Product 38 allows the override and forbids it being invisible: it exists as an accepted
`epistemic_override` Decision carrying the recommendation it overrode, the scope the
researcher chose, and the reason. ADR-008 adds the second half — the objects resting on the
old ceiling are marked stale rather than quietly rewritten.

The audit that precedes the override is the real one: two supporting works against a
requested field-level generalization, which the ladder caps well below the ask.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    AttachManuscriptAnchorRequest,
    CreateQuestionRequest,
    InitProjectRequest,
    PutMatrixRequest,
    RegisterWorkRequest,
)
from research_harness.capabilities.handlers import (
    accept_evidence,
    attach_manuscript_anchor,
    create_question,
    init_project,
    put_matrix,
    register_work,
)
from research_harness.claims.service import ClaimService
from research_harness.domain.base import Provenance
from research_harness.domain.claim import ClaimScopeSpec, ClaimSemantics, Coverage
from research_harness.domain.enums import (
    ArtifactKind,
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DecisionStatus,
    DecisionType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
    ReviewTier,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.errors import AuthorityError, DomainValidationError, TransitionError
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import (
    BlockId,
    ClaimId,
    EvidenceId,
    QuestionId,
    SynthesisId,
    WorkId,
)
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.research import MatrixCell, ResearchQuestion, SynthesisMatrix
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import CandidateMetadata, IdentifierField, WorkCandidate
from research_harness.projection.rows import node_id_for

RELATION = ClaimEvidenceRelationType
MODEL_ACTOR = "vendor-a/model-x"
SENTENCE = "Existing work generally tokenizes traffic heterogeneously."
QUESTION = QuestionId("RQ0001")
MATRIX = SynthesisId("S0001")


# -- workspace ---------------------------------------------------------------


def _register(ctx: CapabilityContext, tmp_path: Path, name: str, title: str) -> WorkId:
    path = tmp_path / "sources" / f"{name}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"%PDF-1.7\n% {name}\n".encode())
    external = ProvenanceSource.EXTERNAL_METADATA
    register_work(
        ctx,
        RegisterWorkRequest(
            candidate=WorkCandidate(
                provenance=Provenance.system(actor="ingest"),
                metadata=CandidateMetadata(
                    title=IdentifierField(value=title, source=external, confidence=0.9),
                    authors=(IdentifierField(value=f"{name.title()} Author", source=external),),
                    year=IdentifierField(value="2026", source=external),
                ),
                candidate_file_hash=f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
                original_filename=path.name,
            ),
            artifact_path=path,
            version_kind=VersionKind.PREPRINT,
            version_label="v1",
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    return next(work.id for work in ctx.repo.list_works() if work.title == title)


def _accept(ctx: CapabilityContext, work: WorkId, evidence_id: str, text: str) -> EvidenceId:
    record = ctx.repo.get_work(work)
    artifact = ctx.repo.get_artifact(record.artifacts[0], work=work)
    candidate = Evidence(
        id=EvidenceId(evidence_id),
        source=SourceAnchor(
            work=work,
            version=artifact.version,
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId("B0007"),
            text_hash=f"sha256:{hashlib.sha256(text.encode()).hexdigest()}",
            page=2,
            section_path=("Method",),
            char_start=0,
            char_end=len(text),
        ),
        content=EvidenceContent(exact_text=text),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.EXPERIMENTAL_SETUP,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        verification=VerificationRecord(
            status=EvidenceStatus.VERIFIED,
            verdict=VerificationVerdict.SUPPORTED,
            verifier="human:alice",
        ),
        provenance=Provenance.model(MODEL_ACTOR),
    )
    accept_evidence(ctx, AcceptEvidenceRequest(candidate=candidate))
    return candidate.id


def _anchor(claim_id: ClaimId) -> ManuscriptAnchor:
    return ManuscriptAnchor(
        file="paper/main.tex",
        line_start=12,
        line_end=12,
        char_start=0,
        char_end=len(SENTENCE),
        sentence=SENTENCE,
        sentence_fingerprint=f"sha256:{hashlib.sha256(SENTENCE.encode()).hexdigest()}",
        claim=claim_id,
        provenance=Provenance.human("human:alice"),
    )


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """Two Works, two accepted Evidence objects, and nothing audited yet."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="claim-override"))
    ctx = open_context(result.root, HUMAN_ACTOR)
    first = _register(ctx, tmp_path, "first", "Byte-level traffic tokenization")
    second = _register(ctx, tmp_path, "second", "Flow-level traffic tokenization")
    _accept(ctx, first, "E0001", "We tokenize traffic at byte granularity.")
    _accept(ctx, second, "E0002", "We tokenize traffic at flow granularity.")
    yield ctx


@pytest.fixture
def claims(project: CapabilityContext) -> ClaimService:
    return ClaimService(project)


@pytest.fixture
def claim_id(claims: ClaimService) -> ClaimId:
    """A claim requested at L3 with two independent supports: deliberately over-asked."""
    claim, _ = claims.create(
        SENTENCE,
        type=ClaimType.PREVALENCE,
        semantics=ClaimSemantics(
            subject="existing_systems", predicate="use", object="traffic_tokenization"
        ),
        scope=ClaimScopeSpec(
            level=ClaimScope.FIELD_GENERALIZATION, corpus="structured-traffic-llm"
        ),
        requested_strength=ClaimScope.FIELD_GENERALIZATION,
        coverage=Coverage(relevant_works=10, examined_works=6, unresolved_works=2),
    )
    claims.relate(claim.id, EvidenceId("E0001"), RELATION.SUPPORTS)
    claims.relate(claim.id, EvidenceId("E0002"), RELATION.SUPPORTS)
    return claim.id


@pytest.fixture
def downstream(project: CapabilityContext, claim_id: ClaimId) -> ManuscriptAnchor:
    """A manuscript sentence and a research question that both rest on the claim."""
    anchor = _anchor(claim_id)
    attach_manuscript_anchor(project, AttachManuscriptAnchorRequest(anchor=anchor))
    create_question(
        project,
        CreateQuestionRequest(
            question=ResearchQuestion(
                id=QUESTION,
                question="Which systems retain protocol field semantics?",
                claims=(claim_id,),
                provenance=Provenance.human("human:alice"),
            )
        ),
    )
    return anchor


# -- the audit that precedes the override ------------------------------------


def test_the_audit_lowers_the_allowed_strength_below_the_request(
    claims: ClaimService, claim_id: ClaimId
) -> None:
    """Product 42.G: two supporting works do not defend a field-level generalization."""
    claim, result, mutation = claims.audit(claim_id)

    assert claim.requested_strength is ClaimScope.FIELD_GENERALIZATION
    assert claim.allowed_strength < claim.requested_strength
    assert claim.status is ClaimStatus.QUALIFIED
    assert result.escalation_prevented
    assert mutation.event.event.value == "claim.qualified"
    assert claim.assessment.maximum_defensible_wording == result.maximum_defensible_wording


# -- the override ------------------------------------------------------------


def test_the_override_creates_a_visible_accepted_decision(
    project: CapabilityContext, claims: ClaimService, claim_id: ClaimId
) -> None:
    """Product 38: the researcher keeps authority, and the record keeps the override."""
    audited, _, _ = claims.audit(claim_id)
    recommendation = audited.allowed_strength

    claim, decision, mutation = claims.override(
        claim_id,
        selected=ClaimScope.FIELD_GENERALIZATION,
        rationale="The unresolved works are all out of scope; the corpus is complete enough.",
    )

    assert decision.type is DecisionType.EPISTEMIC_OVERRIDE
    assert decision.status is DecisionStatus.ACCEPTED
    assert decision.claim == claim_id
    assert decision.auditor_recommendation is recommendation
    assert decision.researcher_selected is ClaimScope.FIELD_GENERALIZATION
    assert decision.provenance.source is ProvenanceSource.HUMAN
    assert claim.allowed_strength is ClaimScope.FIELD_GENERALIZATION
    assert decision.id in claim.decisions
    assert mutation.event.event.value == "claim.overridden"
    assert project.repo.get_decision(decision.id).status is DecisionStatus.ACCEPTED


def test_the_override_shows_up_in_the_claim_view_and_its_history(
    claims: ClaimService, claim_id: ClaimId
) -> None:
    claims.audit(claim_id)
    _, decision, _ = claims.override(
        claim_id, selected=ClaimScope.FIELD_GENERALIZATION, rationale="Corpus is complete enough."
    )

    view = claims.show(claim_id)

    assert [item.id for item in view.decisions] == [decision.id]
    assert view.overrides == (decision,)
    assert claims.override_history(claim_id) == (decision,)
    assert "claim.overridden" in [event.event.value for event in view.history]


def test_the_override_marks_downstream_objects_stale_rather_than_rewriting_them(
    claims: ClaimService, claim_id: ClaimId, downstream: ManuscriptAnchor
) -> None:
    """ADR-008: the manuscript sentence and the question resting on the claim go stale."""
    claims.audit(claim_id)
    _, _, mutation = claims.override(
        claim_id, selected=ClaimScope.FIELD_GENERALIZATION, rationale="Corpus is complete enough."
    )

    stale_ids = {mark.object_id for mark in mutation.stale}

    assert node_id_for(downstream) in stale_ids
    assert str(QUESTION) in stale_ids
    assert str(claim_id) not in stale_ids
    assert {mark.object_id for mark in claims.show(claim_id).stale} == stale_ids


def test_a_matrix_a_claim_derives_from_is_upstream_of_it_not_downstream(
    project: CapabilityContext, claims: ClaimService
) -> None:
    """`derived_from` runs matrix -> claim: the matrix stales the claim, never the reverse."""
    put_matrix(
        project,
        PutMatrixRequest(
            matrix=SynthesisMatrix(
                id=MATRIX,
                name="tokenization",
                fields=("tokenizer",),
                works=(WorkId("W0001"),),
                cells=(
                    MatrixCell(
                        work=WorkId("W0001"),
                        field="tokenizer",
                        labels=("byte-level",),
                        evidence=(EvidenceId("E0001"),),
                    ),
                ),
                provenance=Provenance.human("human:alice"),
            )
        ),
    )
    claim, _ = claims.create(
        "Tokenization schemes differ across the reviewed corpus.",
        type=ClaimType.SYNTHESIS,
        semantics=ClaimSemantics(subject="corpus", predicate="shows", object="heterogeneity"),
        scope=ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN),
        requested_strength=ClaimScope.CORPUS_PATTERN,
        derived_from=(MATRIX,),
    )
    claims.relate(claim.id, EvidenceId("E0001"), RELATION.SUPPORTS)
    claims.audit(claim.id)

    _, _, mutation = claims.override(
        claim.id, selected=ClaimScope.INDIVIDUAL, rationale="Being deliberately conservative."
    )

    assert str(MATRIX) not in {mark.object_id for mark in mutation.stale}
    assert claim.id in [item.id for item in claims.list()]


# -- refusals ----------------------------------------------------------------


def test_a_model_actor_cannot_override_the_auditor(
    project: CapabilityContext, claims: ClaimService, claim_id: ClaimId
) -> None:
    """ADR-007: overriding the epistemic ceiling is a researcher act, never a model's."""
    claims.audit(claim_id)
    as_model = ClaimService(open_context(project.root, MODEL_ACTOR))

    with pytest.raises(AuthorityError, match="human actor"):
        as_model.override(
            claim_id, selected=ClaimScope.FIELD_GENERALIZATION, rationale="I am confident."
        )

    assert project.repo.list_decisions() == []
    assert project.repo.get_claim(claim_id).allowed_strength < ClaimScope.FIELD_GENERALIZATION


def test_an_override_without_a_rationale_is_refused(
    project: CapabilityContext, claims: ClaimService, claim_id: ClaimId
) -> None:
    claims.audit(claim_id)

    with pytest.raises(DomainValidationError, match="rationale"):
        claims.override(claim_id, selected=ClaimScope.FIELD_GENERALIZATION, rationale="   ")

    assert project.repo.list_decisions() == []


def test_an_override_that_changes_nothing_is_refused(
    claims: ClaimService, claim_id: ClaimId
) -> None:
    audited, _, _ = claims.audit(claim_id)

    with pytest.raises(TransitionError, match="nothing to override"):
        claims.override(claim_id, selected=audited.allowed_strength, rationale="No change.")


def test_an_override_cannot_exceed_the_requested_strength(
    claims: ClaimService, claim_id: ClaimId
) -> None:
    """The ask is the ceiling of the ceiling: an override raises to it, never past it."""
    claims.audit(claim_id)

    with pytest.raises(TransitionError, match="exceeds the requested"):
        claims.override(
            claim_id,
            selected=ClaimScope.UNIVERSAL_OR_ABSENCE,
            rationale="The search was exhaustive.",
        )


# -- after the override ------------------------------------------------------


def test_a_re_audit_after_an_override_returns_to_the_evidence_and_keeps_the_decision_visible(
    claims: ClaimService, claim_id: ClaimId
) -> None:
    """A later audit re-reads the evidence; what it cannot do is erase the override's record."""
    audited, _, _ = claims.audit(claim_id)
    _, decision, _ = claims.override(
        claim_id, selected=ClaimScope.FIELD_GENERALIZATION, rationale="Corpus is complete enough."
    )

    re_audited, _, mutation = claims.audit(claim_id)
    view = claims.show(claim_id)

    assert re_audited.allowed_strength is audited.allowed_strength
    assert decision.id in re_audited.decisions
    assert view.overrides == (decision,)
    assert mutation.event.event.value in {"claim.audited", "claim.qualified"}
    assert [event.event.value for event in view.history].count("claim.overridden") == 1

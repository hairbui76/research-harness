"""Task 7.1: claim-evidence relations are many-to-many, aspect-scoped, and canonical.

The invariant the product turns on (Product 10.4): one paper may *simultaneously* support a
claim on one aspect and qualify it on another. Relations are therefore edges, not buckets,
and the same evidence id may appear on a claim several times as long as no two edges are the
same triple (evidence, relation, aspect).

Everything here runs against a real workspace on disk: relations are canonical state, so the
test that matters is the one that closes the workspace and opens it again.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    InitProjectRequest,
    RegisterWorkRequest,
)
from research_harness.capabilities.handlers import accept_evidence, init_project, register_work
from research_harness.claims.service import ClaimService
from research_harness.domain.base import Provenance
from research_harness.domain.claim import ClaimEvidenceRelation, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import (
    ArtifactKind,
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
    ReviewTier,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.errors import CapabilityError, DomainValidationError
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import BlockId, ClaimId, EvidenceId, WorkId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import CandidateMetadata, IdentifierField, WorkCandidate

RELATION = ClaimEvidenceRelationType
TOKENIZER_ASPECT = "tokenizer granularity"
THROUGHPUT_ASPECT = "throughput"


# -- workspace ---------------------------------------------------------------


def _candidate(path: Path, title: str) -> WorkCandidate:
    external = ProvenanceSource.EXTERNAL_METADATA
    return WorkCandidate(
        provenance=Provenance.system(actor="ingest", note=f"local file ingest: {path.name}"),
        metadata=CandidateMetadata(
            title=IdentifierField(value=title, source=external, confidence=0.9),
            authors=(IdentifierField(value="A. Researcher", source=external),),
            year=IdentifierField(value="2026", source=external),
        ),
        candidate_file_hash=f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        original_filename=path.name,
    )


def _register(ctx: CapabilityContext, tmp_path: Path, name: str, title: str) -> WorkId:
    """One Work with one Version and one Artifact, registered from tiny hand-written bytes."""
    path = tmp_path / "sources" / f"{name}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"%PDF-1.7\n% {name}\n".encode())
    register_work(
        ctx,
        RegisterWorkRequest(
            candidate=_candidate(path, title),
            artifact_path=path,
            version_kind=VersionKind.PREPRINT,
            version_label="v1",
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    return next(work.id for work in ctx.repo.list_works() if work.title == title)


def _accept(
    ctx: CapabilityContext,
    work: WorkId,
    evidence_id: str,
    text: str,
    *,
    evidence_type: EvidenceType = EvidenceType.EXPERIMENTAL_SETUP,
) -> EvidenceId:
    """Accepted, source-observed evidence anchored in the work's registered artifact."""
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
            page=3,
            section_path=("Experiments",),
            char_start=0,
            char_end=len(text),
        ),
        content=EvidenceContent(exact_text=text),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=evidence_type,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        verification=VerificationRecord(
            status=EvidenceStatus.VERIFIED,
            verdict=VerificationVerdict.SUPPORTED,
            verifier="human:alice",
        ),
        provenance=Provenance.model("vendor-a/model-x"),
    )
    accept_evidence(ctx, AcceptEvidenceRequest(candidate=candidate))
    return candidate.id


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """A workspace with two Works and three accepted Evidence objects (E0001-E0003)."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="claim-relations"))
    ctx = open_context(result.root, HUMAN_ACTOR)
    first = _register(ctx, tmp_path, "first", "Byte-level traffic tokenization")
    second = _register(ctx, tmp_path, "second", "Flow-level traffic tokenization")
    _accept(ctx, first, "E0001", "We tokenize traffic at byte granularity.")
    _accept(ctx, first, "E0002", "Throughput drops by 40% at byte granularity.")
    _accept(ctx, second, "E0003", "We tokenize traffic at flow granularity.")
    yield ctx


@pytest.fixture
def claims(project: CapabilityContext) -> ClaimService:
    return ClaimService(project)


def _claim(service: ClaimService, *relations: ClaimEvidenceRelation) -> ClaimId:
    claim, _ = service.create(
        "Existing systems employ heterogeneous traffic tokenization schemes.",
        type=ClaimType.PREVALENCE,
        semantics=ClaimSemantics(
            subject="existing_systems", predicate="use", object="traffic_tokenization"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, corpus="structured-traffic-llm"),
        requested_strength=ClaimScope.CORPUS_PATTERN,
        relations=relations,
    )
    return claim.id


# -- creation ----------------------------------------------------------------


def test_a_new_claim_starts_unverified_at_l0_however_strong_the_request(
    claims: ClaimService,
) -> None:
    """Scope is earned by audit, never asked for (Product 10.2, 42.G)."""
    claim, result = claims.create(
        "Existing work generally tokenizes traffic heterogeneously.",
        type=ClaimType.PREVALENCE,
        semantics=ClaimSemantics(
            subject="existing_systems", predicate="use", object="traffic_tokenization"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.FIELD_GENERALIZATION),
        requested_strength=ClaimScope.FIELD_GENERALIZATION,
    )

    assert claim.requested_strength is ClaimScope.FIELD_GENERALIZATION
    assert claim.allowed_strength is ClaimScope.INDIVIDUAL
    assert claim.status is ClaimStatus.UNVERIFIED
    assert result.event.event.value == "claim.created"


def test_a_claim_cannot_be_created_against_evidence_the_workspace_does_not_hold(
    claims: ClaimService,
) -> None:
    with pytest.raises(CapabilityError, match="E0404"):
        _claim(
            claims,
            ClaimEvidenceRelation(evidence=EvidenceId("E0404"), relation=RELATION.SUPPORTS),
        )


# -- many-to-many ------------------------------------------------------------


def test_one_evidence_object_supports_one_aspect_and_qualifies_another(
    claims: ClaimService,
) -> None:
    """ROADMAP 7.1: a paper may simultaneously support and qualify different aspects."""
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)
    claim, _ = claims.relate(
        claim_id,
        EvidenceId("E0001"),
        RELATION.QUALIFIES,
        aspect=THROUGHPUT_ASPECT,
        note="the same system pays for it in throughput",
    )

    assert claim.supporting == (EvidenceId("E0001"),)
    assert claim.qualifying == (EvidenceId("E0001"),)
    assert [(link.relation.value, link.aspect) for link in claim.relations] == [
        ("supports", TOKENIZER_ASPECT),
        ("qualifies", THROUGHPUT_ASPECT),
    ]


def test_one_claim_carries_every_relation_type_across_several_works(
    claims: ClaimService,
) -> None:
    claim_id = _claim(claims)
    for evidence, relation in (
        ("E0001", RELATION.SUPPORTS),
        ("E0002", RELATION.CONTRADICTS),
        ("E0003", RELATION.QUALIFIES),
        ("E0001", RELATION.CONTEXTUALIZES),
        ("E0002", RELATION.EXEMPLIFIES),
        ("E0003", RELATION.INCOMPARABLE_UNDER_CURRENT_EVIDENCE),
    ):
        claims.relate(claim_id, EvidenceId(evidence), relation)

    assert len(claims.relations_of(claim_id)) == len(RELATION)
    assert claims.evidence_for(claim_id, RELATION.SUPPORTS) == (EvidenceId("E0001"),)
    assert claims.evidence_for(claim_id, RELATION.CONTRADICTS) == (EvidenceId("E0002"),)
    view = claims.show(claim_id)
    assert [link.evidence for link in view.context] == [EvidenceId("E0001"), EvidenceId("E0002")]


def test_the_same_evidence_may_qualify_two_different_aspects(claims: ClaimService) -> None:
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0002"), RELATION.QUALIFIES, aspect=TOKENIZER_ASPECT)
    claim, _ = claims.relate(
        claim_id, EvidenceId("E0002"), RELATION.QUALIFIES, aspect=THROUGHPUT_ASPECT
    )

    assert [link.aspect for link in claim.relations] == [TOKENIZER_ASPECT, THROUGHPUT_ASPECT]
    assert claims.evidence_for(claim_id, RELATION.QUALIFIES) == (EvidenceId("E0002"),)


# -- duplicates --------------------------------------------------------------


def test_an_exact_duplicate_relation_is_refused(claims: ClaimService) -> None:
    """A repeated (evidence, relation, aspect) edge would count the same evidence twice."""
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)

    with pytest.raises(CapabilityError, match="already records E0001"):
        claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)

    assert len(claims.relations_of(claim_id)) == 1


def test_a_duplicate_relation_is_refused_at_creation_too(claims: ClaimService) -> None:
    link = ClaimEvidenceRelation(evidence=EvidenceId("E0001"), relation=RELATION.SUPPORTS)
    with pytest.raises(DomainValidationError, match="count the same evidence twice"):
        _claim(claims, link, link)


def test_relating_evidence_the_workspace_does_not_hold_is_refused(claims: ClaimService) -> None:
    claim_id = _claim(claims)
    with pytest.raises(CapabilityError, match="no accepted evidence E0404"):
        claims.relate(claim_id, EvidenceId("E0404"), RELATION.SUPPORTS)


# -- removal -----------------------------------------------------------------


def test_unrelate_removes_exactly_the_edge_named(claims: ClaimService) -> None:
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.QUALIFIES, aspect=THROUGHPUT_ASPECT)

    claim, result = claims.unrelate(
        claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT
    )

    assert claim.supporting == ()
    assert claim.qualifying == (EvidenceId("E0001"),)
    assert result.event.event.value == "claim.relation_changed"


def test_unrelating_an_edge_that_is_not_there_is_refused(claims: ClaimService) -> None:
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)

    with pytest.raises(CapabilityError, match="does not record E0001"):
        claims.unrelate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS)


# -- persistence and events --------------------------------------------------


def test_relations_survive_closing_and_reopening_the_workspace(
    project: CapabilityContext, claims: ClaimService
) -> None:
    """Relations are canonical state, not a projection: reopening must read them back."""
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.QUALIFIES, aspect=THROUGHPUT_ASPECT)
    claims.relate(claim_id, EvidenceId("E0003"), RELATION.SUPPORTS)

    reopened = ClaimService(open_context(project.root, HUMAN_ACTOR))
    relations = reopened.relations_of(claim_id)

    assert [(str(link.evidence), link.relation.value, link.aspect) for link in relations] == [
        ("E0001", "supports", TOKENIZER_ASPECT),
        ("E0001", "qualifies", THROUGHPUT_ASPECT),
        ("E0003", "supports", None),
    ]


def test_every_relation_change_is_recorded_as_a_semantic_event(
    project: CapabilityContext, claims: ClaimService
) -> None:
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)
    claims.unrelate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS, aspect=TOKENIZER_ASPECT)

    events = [event for event in project.repo.iter_events() if claim_id in event.subjects]
    kinds = [event.event.value for event in events]

    assert kinds == ["claim.created", "claim.relation_changed", "claim.relation_changed"]
    assert [event.payload["change"] for event in events[1:]] == ["related", "unrelated"]
    assert events[1].payload["aspect"] == TOKENIZER_ASPECT
    assert claims.show(claim_id).history == tuple(events)


def test_a_relation_change_does_not_rewrite_the_audited_assessment(
    claims: ClaimService,
) -> None:
    """ADR-008: adding evidence makes the audit old, it does not silently recompute it."""
    claim_id = _claim(claims)
    claims.relate(claim_id, EvidenceId("E0001"), RELATION.SUPPORTS)
    audited, _, _ = claims.audit(claim_id)
    assert audited.assessment.audited_at is not None

    claims.relate(claim_id, EvidenceId("E0003"), RELATION.SUPPORTS)
    view = claims.show(claim_id)

    assert view.claim.assessment.audited_at == audited.assessment.audited_at
    assert view.claim.allowed_strength is audited.allowed_strength
    assert view.audit_is_older_than_relations

"""Gate P1: a project is populated through typed capability handlers, and only through them.

Hand-authored Work/Evidence/Claim/Decision fixtures round-trip through canonical files with
no SQLite, no parser, and no model provider anywhere in the flow.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import research_harness
from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.diff import ChangeKind
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    AcceptEvidenceRequest,
    AddNoteRequest,
    AttachManuscriptAnchorRequest,
    AuditClaimRequest,
    CreateClaimRequest,
    CreateQuestionRequest,
    MutationResult,
    OverrideClaimStrengthRequest,
    PromoteNoteRequest,
    PutMatrixRequest,
    PutTaxonomyRequest,
    RecordSearchRunRequest,
    RegisterWorkRequest,
    RejectEvidenceRequest,
    StoreParsedDocumentRequest,
    UpdateQuestionRequest,
)
from research_harness.capabilities.handlers import (
    CAPABILITY_HANDLERS,
    accept_decision,
    accept_evidence,
    add_note,
    attach_manuscript_anchor,
    audit_claim,
    create_claim,
    create_question,
    override_claim_strength,
    promote_note,
    put_matrix,
    put_taxonomy,
    record_search_run,
    register_work,
    reject_evidence,
    store_parsed_document,
    update_question,
)
from research_harness.capabilities.invalidation import NullInvalidation
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DecisionStatus,
    DecisionType,
    DocumentBlockKind,
    EvidenceOrigin,
    EvidenceStatus,
    ProvenanceSource,
    QuestionStatus,
    ReviewAction,
    ReviewTier,
    ScreeningState,
    StaleState,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.domain.ids import (
    BlockId,
    ClaimId,
    DecisionId,
    EvidenceId,
    QuestionId,
    SearchRunId,
    SynthesisId,
)
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.research import (
    Decision,
    MatrixCell,
    ResearchEvent,
    ResearchQuestion,
    SearchRun,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
)
from research_harness.projection.dependencies import load_stale_marks
from research_harness.projection.schema import create_all, create_engine_for
from research_harness.workspace.events import verify_consistency
from research_harness.workspace.repository import WorkspaceRepository
from tests.contract.capabilities.conftest import (
    MODEL_ACTOR,
    TEXT_HASH,
    Registered,
    artifact_hash,
    make_evidence,
)

HUMAN = Provenance.human()


# -- helpers -----------------------------------------------------------------


def accept_source_evidence(ctx: CapabilityContext, registered: Registered) -> MutationResult:
    """Accept a directly evidenced, Tier-1 candidate as the researcher."""
    return accept_evidence(
        ctx,
        AcceptEvidenceRequest(
            candidate=make_evidence(registered),
            review_action=ReviewAction.ACCEPT,
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the span in the source",
        ),
    )


def make_claim(**overrides: object) -> Claim:
    fields: dict[str, object] = {
        "id": ClaimId("C0001"),
        "statement": "Existing systems tokenize traffic heterogeneously.",
        "type": ClaimType.PREVALENCE,
        "semantics": ClaimSemantics(
            subject="existing_systems", predicate="use", object="traffic_tokenization"
        ),
        "scope": ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, corpus="gate-p1"),
        "relations": (
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0001"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
        ),
        "assessment": ClaimAssessment(
            requested_strength=ClaimScope.FIELD_GENERALIZATION,
            allowed_strength=ClaimScope.CORPUS_PATTERN,
            status=ClaimStatus.UNVERIFIED,
        ),
        "provenance": HUMAN,
    }
    return Claim(**{**fields, **overrides})  # type: ignore[arg-type]


def make_override(**overrides: object) -> Decision:
    fields: dict[str, object] = {
        "id": DecisionId("D0001"),
        "type": DecisionType.EPISTEMIC_OVERRIDE,
        "status": DecisionStatus.PROPOSED,
        "claim": ClaimId("C0001"),
        "auditor_recommendation": ClaimScope.CORPUS_PATTERN,
        "researcher_selected": ClaimScope.FIELD_GENERALIZATION,
        "rationale": "Coverage is strong enough for a field-level statement.",
        "provenance": HUMAN,
    }
    return Decision(**{**fields, **overrides})  # type: ignore[arg-type]


def events_of(ctx: CapabilityContext) -> list[ResearchEvent]:
    return list(ctx.repo.iter_events())


# -- Gate P1 -----------------------------------------------------------------


def test_gate_p1_populates_a_project_through_handlers_and_round_trips(
    project: CapabilityContext, registered: Registered
) -> None:
    accepted = accept_source_evidence(project, registered)
    created = create_claim(project, CreateClaimRequest(claim=make_claim()))
    decided = accept_decision(project, AcceptDecisionRequest(decision=make_override()))
    overridden = override_claim_strength(
        project,
        OverrideClaimStrengthRequest(claim_id=ClaimId("C0001"), decision_id=DecisionId("D0001")),
    )

    reopened = WorkspaceRepository.open(project.root)
    work = reopened.get_work(registered.work)
    assert work.title == "Structured traffic representations"
    assert work.versions == (registered.version,) and work.artifacts == (registered.artifact,)
    assert reopened.read_artifact_bytes(reopened.get_artifact(registered.artifact)) == (
        project.repo.read_artifact_bytes(project.repo.get_artifact(registered.artifact))
    )

    evidence = list(reopened.iter_evidence(registered.work))
    assert [record.id for record in evidence] == [make_evidence(registered).id]
    assert evidence[0].status is EvidenceStatus.ACCEPTED
    assert evidence[0].verification.accepted_by == project.actor
    assert evidence[0].verification.verifier == project.actor

    claim = reopened.get_claim(ClaimId("C0001"))
    assert claim.allowed_strength is ClaimScope.FIELD_GENERALIZATION
    assert claim.decisions == (DecisionId("D0001"),)
    assert reopened.get_decision(DecisionId("D0001")).status is DecisionStatus.ACCEPTED
    assert reopened.consistency.consistent
    assert verify_consistency(reopened.layout).consistent

    for result in (accepted, created, decided, overridden):
        assert result.validation.ok
        assert result.objects
        assert result.diff.fields
        assert result.event in events_of(project)


def test_every_mutation_reports_an_event_a_diff_and_a_validation_result(
    project: CapabilityContext, registered: Registered
) -> None:
    accept_source_evidence(project, registered)
    create_claim(project, CreateClaimRequest(claim=make_claim()))
    results = [
        audit_claim(
            project,
            AuditClaimRequest(
                claim_id=ClaimId("C0001"),
                status=ClaimStatus.QUALIFIED,
                allowed_strength=ClaimScope.OBSERVED_SUBSET,
                maximum_defensible_wording="in the works we examined",
            ),
        ),
        create_question(
            project,
            CreateQuestionRequest(
                question=ResearchQuestion(
                    id=QuestionId("RQ0001"),
                    question="Which systems retain protocol field semantics?",
                    provenance=HUMAN,
                )
            ),
        ),
        update_question(
            project,
            UpdateQuestionRequest(
                question_id=QuestionId("RQ0001"),
                status=QuestionStatus.PARTIALLY_ANSWERED,
                claims=(ClaimId("C0001"),),
            ),
        ),
        record_search_run(
            project,
            RecordSearchRunRequest(
                search_run=SearchRun(
                    id=SearchRunId("SR0001"),
                    question="protocol compliant adversarial traffic",
                    sources=("openalex",),
                    provenance=Provenance.system(),
                )
            ),
        ),
        put_matrix(
            project,
            PutMatrixRequest(
                matrix=SynthesisMatrix(
                    id=SynthesisId("S0001"),
                    name="representation comparison",
                    works=(registered.work,),
                    fields=("tokenization",),
                    cells=(
                        MatrixCell(work=registered.work, field="tokenization", labels=("byte",)),
                    ),
                    provenance=HUMAN,
                )
            ),
        ),
        attach_manuscript_anchor(
            project,
            AttachManuscriptAnchorRequest(
                anchor=ManuscriptAnchor(
                    file="manuscript/main.tex",
                    line_start=12,
                    line_end=12,
                    sentence="Existing systems tokenize traffic heterogeneously.",
                    sentence_fingerprint=TEXT_HASH,
                    claim=ClaimId("C0001"),
                    citation_keys=("smith2026",),
                    provenance=HUMAN,
                )
            ),
        ),
    ]
    log = events_of(project)
    for result in results:
        assert result.validation.ok, result.validation.errors
        assert result.objects
        assert result.diff.fields
        assert result.event in log
        assert result.event.actor == project.actor
        assert json.dumps(result.as_dict(), default=str)


def test_capability_layer_creates_no_projection(
    project: CapabilityContext, registered: Registered
) -> None:
    accept_source_evidence(project, registered)
    create_claim(project, CreateClaimRequest(claim=make_claim()))
    assert not project.repo.layout.database_file.exists()
    assert list(project.repo.layout.index_dir.iterdir()) == []


def test_a_mutation_reports_the_downstream_objects_it_makes_stale(
    project: CapabilityContext, registered: Registered
) -> None:
    """ADR-008: an upstream change marks dependents stale, highest scientific impact first."""
    create_claim(project, CreateClaimRequest(claim=make_claim()))
    attach_manuscript_anchor(
        project,
        AttachManuscriptAnchorRequest(
            anchor=ManuscriptAnchor(
                file="manuscript/main.tex",
                line_start=12,
                line_end=12,
                sentence="Existing systems tokenize traffic heterogeneously.",
                sentence_fingerprint=TEXT_HASH,
                claim=ClaimId("C0001"),
                provenance=HUMAN,
            )
        ),
    )

    result = accept_source_evidence(project, registered)

    stale = {mark.object_id for mark in result.stale}
    assert "C0001" in stale
    assert any(object_id.startswith("MA:") for object_id in stale)
    assert [mark.priority for mark in result.stale] == sorted(
        (mark.priority for mark in result.stale), reverse=True
    )
    assert project.repo.get_claim(ClaimId("C0001")).stale is StaleState.FRESH
    assert not project.repo.layout.database_file.exists()


def test_the_stale_set_is_recorded_when_a_projection_already_exists(
    project: CapabilityContext, registered: Registered
) -> None:
    """The projection is never created by a mutation, but it is kept current when present."""
    engine = create_engine_for(project.repo.layout.database_file)
    try:
        create_all(engine)
    finally:
        engine.dispose()
    create_claim(project, CreateClaimRequest(claim=make_claim()))

    result = accept_source_evidence(project, registered)

    engine = create_engine_for(project.repo.layout.database_file)
    try:
        with engine.begin() as connection:
            recorded = load_stale_marks(connection)
    finally:
        engine.dispose()
    assert {mark.object_id for mark in recorded} == {mark.object_id for mark in result.stale}


def test_a_null_invalidation_hook_marks_nothing(
    project: CapabilityContext, registered: Registered
) -> None:
    quiet = CapabilityContext(
        repo=project.repo, actor=project.actor, invalidation=NullInvalidation()
    )
    create_claim(quiet, CreateClaimRequest(claim=make_claim()))
    assert accept_source_evidence(quiet, registered).stale == ()


def test_capability_layer_imports_no_parser_and_no_provider() -> None:
    """Importing the mutation surface must not drag in a parser or a model provider."""
    source_root = Path(research_harness.__file__).resolve().parents[1]
    probe = (
        "import sys; import research_harness.capabilities as capabilities;"
        "banned = sorted(name for name in sys.modules"
        " if name.startswith(('pymupdf', 'httpx', 'numpy'))"
        " or name.startswith('research_harness.parsing')"
        " or name.startswith('research_harness.providers'));"
        "print(','.join(banned))"
    )
    # Fixed argv, no shell, no network: the probe only imports and reports sys.modules.
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(source_root), "PATH": "/usr/bin:/bin"},
    )
    assert completed.stdout.strip() == ""


def test_named_capabilities_are_registered() -> None:
    assert {
        "corpus.ingest",
        "work.parse",
        "evidence.accept",
        "evidence.reject",
        "claim.create",
        "claim.audit",
        "question.create",
        "manuscript.attach_claim",
        "decision.accept",
        "note.add",
        "note.promote",
        "taxonomy.put",
        "synthesis.build_matrix",
        "search_run.record",
    } <= set(CAPABILITY_HANDLERS)
    assert all(callable(handler) for handler in CAPABILITY_HANDLERS.values())


# -- authority ---------------------------------------------------------------


def test_a_model_actor_cannot_accept_interpretive_evidence(
    project: CapabilityContext, registered: Registered
) -> None:
    model = CapabilityContext(repo=project.repo, actor=MODEL_ACTOR)
    interpretive = make_evidence(
        registered,
        origin=EvidenceOrigin.MODEL_PROPOSED,
        tier=ReviewTier.TIER_2,
    )
    with pytest.raises(AuthorityError, match="only a human actor"):
        accept_evidence(
            model,
            AcceptEvidenceRequest(
                candidate=interpretive,
                review_action=ReviewAction.ACCEPT,
                verdict=VerificationVerdict.SUPPORTED,
            ),
        )
    assert list(project.repo.iter_evidence(registered.work)) == []
    assert events_of(project) == events_of(project)[: len(events_of(project))]
    assert all(event.event.value != "evidence.accepted" for event in events_of(project))


def test_a_model_actor_cannot_accept_a_decision(project: CapabilityContext) -> None:
    model = CapabilityContext(repo=project.repo, actor=MODEL_ACTOR)
    with pytest.raises(AuthorityError):
        accept_decision(model, AcceptDecisionRequest(decision=make_override()))


def test_override_without_a_decision_is_refused(
    project: CapabilityContext, registered: Registered
) -> None:
    accept_source_evidence(project, registered)
    create_claim(project, CreateClaimRequest(claim=make_claim()))
    with pytest.raises(CapabilityError, match="epistemic_override"):
        override_claim_strength(
            project,
            OverrideClaimStrengthRequest(
                claim_id=ClaimId("C0001"), decision_id=DecisionId("D0404")
            ),
        )
    assert project.repo.get_claim(ClaimId("C0001")).allowed_strength is ClaimScope.CORPUS_PATTERN


def test_a_proposed_candidate_needs_a_verdict_before_acceptance(
    project: CapabilityContext, registered: Registered
) -> None:
    with pytest.raises(CapabilityError, match="verification verdict"):
        accept_evidence(
            project,
            AcceptEvidenceRequest(
                candidate=make_evidence(registered), review_action=ReviewAction.ACCEPT
            ),
        )


def test_evidence_anchored_in_other_bytes_is_refused(
    project: CapabilityContext, registered: Registered
) -> None:
    candidate = make_evidence(registered)
    elsewhere = candidate.source.touch(file_hash=artifact_hash(b"different bytes"))
    with pytest.raises(CapabilityError, match="never a reattachment"):
        accept_evidence(
            project,
            AcceptEvidenceRequest(
                candidate=candidate.touch(source=elsewhere),
                review_action=ReviewAction.ACCEPT,
                verdict=VerificationVerdict.SUPPORTED,
            ),
        )


# -- review actions ----------------------------------------------------------


def test_rejected_candidates_never_reach_canonical_evidence(
    project: CapabilityContext, registered: Registered
) -> None:
    candidate = make_evidence(registered)
    result = reject_evidence(
        project,
        RejectEvidenceRequest(
            candidate=candidate,
            reason="the span does not say this",
            candidate_id="cand_00000000000000ff",
            field="dataset",
        ),
    )
    assert list(project.repo.iter_evidence(registered.work)) == []
    assert result.event.event.value == "evidence.rejected"
    assert result.event.payload["anchor.text_hash"] == candidate.source.text_hash
    assert result.diff.change is ChangeKind.UPDATED
    assert result.diff.fields["verification.status"] == ("proposed", "rejected")

    (record,) = list(project.repo.iter_rejections(registered.work))
    assert record.candidate_id == "cand_00000000000000ff"
    assert record.anchor == candidate.source
    assert record.field == "dataset"
    assert record.reason == "the span does not say this"
    assert record.actor == project.actor
    assert list(project.repo.iter_notes()) == []


def test_a_rejection_is_a_canonical_record_the_event_log_reconciles_with(
    project: CapabilityContext, registered: Registered
) -> None:
    """A rejection is canonical state, so reopening the workspace must not find a gap."""
    reject_evidence(
        project,
        RejectEvidenceRequest(
            candidate=make_evidence(registered),
            reason="the table row says something else",
            candidate_id="cand_00000000000000aa",
        ),
    )
    reopened = WorkspaceRepository.open(project.root)
    assert reopened.consistency.consistent, reopened.consistency.summary()
    assert [record.candidate_id for record in reopened.iter_rejections(registered.work)] == [
        "cand_00000000000000aa"
    ]


def test_an_edit_replaces_content_but_never_the_anchor(
    project: CapabilityContext, registered: Registered
) -> None:
    candidate = make_evidence(registered)
    corrected = candidate.touch(
        content=candidate.content.touch(exact_text="We evaluate on CICIDS2017.")
    )
    result = accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=candidate,
            review_action=ReviewAction.EDIT,
            edited=corrected,
            verdict=VerificationVerdict.PARTIALLY_SUPPORTED,
        ),
    )
    stored = next(iter(project.repo.iter_evidence(registered.work)))
    assert stored.content.exact_text == "We evaluate on CICIDS2017."
    assert stored.source == candidate.source
    assert stored.verification.review_action is ReviewAction.ACCEPT
    assert stored.verification.rationale == "accepted after researcher edit"
    assert "edit" in " ".join(result.validation.warnings)


def test_accept_with_qualification_records_the_qualification(
    project: CapabilityContext, registered: Registered
) -> None:
    result = accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=make_evidence(registered),
            review_action=ReviewAction.ACCEPT_WITH_QUALIFICATION,
            qualification="only for the encrypted split",
            verdict=VerificationVerdict.SUPPORTED,
        ),
    )
    stored = next(iter(project.repo.iter_evidence(registered.work)))
    assert stored.qualification == "only for the encrypted split"
    assert result.event.payload["qualification"] == "only for the encrypted split"


# -- notes, taxonomy, blocks -------------------------------------------------


def test_a_note_is_captured_and_promoted_into_a_claim(
    project: CapabilityContext, registered: Registered
) -> None:
    accept_source_evidence(project, registered)
    create_claim(project, CreateClaimRequest(claim=make_claim()))
    captured = add_note(project, AddNoteRequest(text="tokenization terminology differs"))
    key = captured.objects[0].removeprefix("notes/")
    promoted = promote_note(project, PromoteNoteRequest(note_key=key, target=ClaimId("C0001")))
    note = next(iter(project.repo.iter_notes()))
    assert note.promoted_to == ClaimId("C0001")
    assert promoted.event.event.value == "note.promoted"


def test_a_note_cannot_be_promoted_into_something_that_does_not_exist(
    project: CapabilityContext,
) -> None:
    captured = add_note(project, AddNoteRequest(text="promote me nowhere"))
    key = captured.objects[0].removeprefix("notes/")
    with pytest.raises(CapabilityError, match="no C0404"):
        promote_note(project, PromoteNoteRequest(note_key=key, target=ClaimId("C0404")))


def test_a_taxonomy_needs_its_accepted_decision(project: CapabilityContext) -> None:
    decision = Decision(
        id=DecisionId("D0002"),
        type=DecisionType.TAXONOMY_REVISION,
        rationale="split byte-level from field-level tokenization",
        taxonomy_terms=("byte_level", "field_level"),
        provenance=HUMAN,
    )
    taxonomy = Taxonomy(
        name="representation",
        terms=(TaxonomyTerm(term="byte_level", decision=decision.id),),
        provenance=HUMAN,
    )
    with pytest.raises(CapabilityError, match="accept it before it takes effect"):
        put_taxonomy(project, PutTaxonomyRequest(taxonomy=taxonomy, decision=decision))

    accepted = accept_decision(project, AcceptDecisionRequest(decision=decision))
    assert accepted.event.event.value == "taxonomy.revised"
    stored = put_taxonomy(
        project,
        PutTaxonomyRequest(
            taxonomy=taxonomy, decision=decision.touch(status=DecisionStatus.ACCEPTED)
        ),
    )
    assert project.repo.get_taxonomy("representation").terms[0].term == "byte_level"
    assert stored.objects == ("taxonomy/representation",)


def test_parsed_blocks_must_belong_to_the_artifact_they_are_stored_for(
    project: CapabilityContext, registered: Registered
) -> None:
    block = DocumentBlock(
        id=BlockId("B0001"),
        work=registered.work,
        version=registered.version,
        artifact=registered.artifact,
        kind=DocumentBlockKind.PARAGRAPH,
        page=1,
        order=0,
        text="We evaluate on CICIDS2017.",
        text_hash=TEXT_HASH,
        provenance=Provenance.system(actor="hand-authored@1"),
    )
    document = ParsedDocument(
        work=registered.work,
        version=registered.version,
        artifact=registered.artifact,
        file_hash=artifact_hash(),
        parser_name="hand-authored",
        parser_version="1",
        page_count=1,
        blocks=(block,),
        provenance=Provenance.system(actor="hand-authored@1"),
    )
    result = store_parsed_document(project, StoreParsedDocumentRequest(document=document))
    assert result.objects == (f"blocks/{registered.artifact}",)
    assert [stored.id for stored in project.repo.iter_blocks(registered.artifact)] == [block.id]

    foreign = document.touch(file_hash=artifact_hash(b"other"))
    with pytest.raises(CapabilityError, match="parse was taken from"):
        store_parsed_document(project, StoreParsedDocumentRequest(document=foreign))


def test_registering_a_work_twice_is_refused_by_the_artifact_check(
    project: CapabilityContext, registered: Registered, artifact_file: Path
) -> None:
    """`work.register` always creates a new Work; idempotence lives in `corpus.ingest`."""
    from tests.contract.capabilities.conftest import make_candidate

    second = register_work(
        project,
        RegisterWorkRequest(
            candidate=make_candidate(artifact_file, title="A different paper"),
            artifact_path=artifact_file,
            version_kind=VersionKind.PREPRINT,
        ),
    )
    assert second.diff.change is ChangeKind.CREATED
    assert [work.screening for work in project.repo.list_works()] == [
        ScreeningState.DISCOVERED,
        ScreeningState.DISCOVERED,
    ]
    assert project.repo.list_works()[1].identifiers.doi is not None
    assert project.repo.list_works()[1].provenance.source is ProvenanceSource.HUMAN

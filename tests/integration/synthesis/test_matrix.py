"""Task 8.2: a synthesis matrix is derived state, multi-label, and evidence-linked.

Three product rules are under test here. A cell carries every term that matched, because
forcing exclusivity would make the table tidy and the science wrong. A cell links the
accepted Evidence that justified it, because a comparison nobody can reopen is not
evidence of anything. And an unmatched work keeps an empty cell, which says "not
recorded" and never "absent" (Product 7.1, 11, 33, 42.F).
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
from research_harness.capabilities.invalidation import canonical_objects
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    ArtifactKind,
    DecisionStatus,
    DecisionType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    NegativeEvidenceState,
    ProvenanceSource,
    ReviewAction,
    ReviewTier,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import (
    ArtifactId,
    BlockId,
    DecisionId,
    EvidenceId,
    SynthesisId,
    VersionId,
    WorkId,
)
from research_harness.domain.research import (
    Decision,
    MatrixCell,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
)
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.projection.dependencies import DependencyGraph, affected_by
from research_harness.projection.rows import taxonomy_node_id
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.roles.schemas import CellProposal, SynthesisOutput
from research_harness.synthesis import (
    ClassificationRule,
    SynthesisService,
    apply_proposals,
    build_matrix,
    compare_field,
    matrix_diff,
)

FIELD = "representation"
TERMS = ("raw_sequential", "field_based", "behavior_aware")
TAXONOMY_DECISION = DecisionId("D0001")

RULES = (
    ClassificationRule(
        term="raw_sequential", field=FIELD, any_of=("byte-level", "raw packet bytes")
    ),
    ClassificationRule(term="field_based", field=FIELD, any_of=("header field", "field-based")),
    ClassificationRule(
        term="behavior_aware", field=FIELD, any_of=("flow behaviour", "behavioural")
    ),
    ClassificationRule(term="field_based", field="tokenization", any_of=("byte-level",)),
)


def taxonomy() -> Taxonomy:
    return Taxonomy(
        name=FIELD,
        terms=tuple(TaxonomyTerm(term=term, decision=TAXONOMY_DECISION) for term in TERMS),
        provenance=Provenance.human(),
    )


def taxonomy_decision(status: DecisionStatus = DecisionStatus.ACCEPTED) -> Decision:
    return Decision(
        id=TAXONOMY_DECISION,
        type=DecisionType.TAXONOMY_REVISION,
        status=status,
        rationale="the project compares representations along these three families",
        taxonomy_terms=TERMS,
        provenance=Provenance.human(),
    )


def evidence_for(
    evidence_id: str,
    work: str,
    text: str,
    *,
    field: str | None = FIELD,
    status: EvidenceStatus = EvidenceStatus.ACCEPTED,
    negative_state: NegativeEvidenceState | None = None,
    labels: tuple[str, ...] = (),
) -> Evidence:
    """An evidence object with a complete anchor, at whichever status the test needs."""
    number = WorkId(work).number
    return Evidence(
        id=EvidenceId(evidence_id),
        source=SourceAnchor(
            work=WorkId(work),
            version=VersionId.make(number, 1),
            artifact=ArtifactId.make(number, 1),
            file_hash=_digest(work),
            block=BlockId("B0001"),
            text_hash=_digest(text),
            page=2,
        ),
        content=EvidenceContent(
            exact_text=text, field=field, negative_state=negative_state, labels=labels
        ),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.METHOD_DESCRIPTION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        verification=VerificationRecord(
            status=status,
            verdict=VerificationVerdict.SUPPORTED,
            accepted_by=HUMAN_ACTOR if status is EvidenceStatus.ACCEPTED else None,
            review_action=ReviewAction.ACCEPT if status is EvidenceStatus.ACCEPTED else None,
        ),
        provenance=Provenance.human(),
    )


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def build(
    evidence: tuple[Evidence, ...],
    works: tuple[str, ...],
    *,
    rules: tuple[ClassificationRule, ...] = RULES,
    decision: Decision | None = None,
) -> SynthesisMatrix:
    return build_matrix(
        taxonomy(),
        decision or taxonomy_decision(),
        evidence,
        tuple(WorkId(work) for work in works),
        FIELD,
        rules,
        matrix_id=SynthesisId("S0001"),
        provenance=Provenance.human(),
    )


# -- multi-label cells -------------------------------------------------------


def test_a_cell_carries_every_term_whose_rule_matched() -> None:
    """Multi-label by design: a hybrid system is both, and the table must say so."""
    hybrid = evidence_for(
        "E0001", "W0001", "We serialize raw packet bytes alongside each header field."
    )

    matrix = build((hybrid,), ("W0001",))

    cell = matrix.cells[0]
    assert cell.labels == ("raw_sequential", "field_based")
    assert matrix.taxonomy == FIELD and matrix.fields == (FIELD,)


def test_a_label_the_evidence_itself_declares_fills_a_cell_no_rule_matched() -> None:
    """Dogfood F13: a classification was only ever as good as a substring match.

    The extractor answering a categorical question now states the category beside the span
    it quoted, checked against the schema's vocabulary; the keyword rules stay as the
    reproducible cross-check rather than the only way a cell can be filled.
    """
    declared = evidence_for(
        "E0001",
        "W0001",
        "The detector scores each host on its outbound behaviour profile.",
        labels=("behavior aware",),
    )

    matrix = build((declared,), ("W0001",))

    cell = matrix.cells[0]
    assert cell.labels == ("behavior_aware",), "punctuation is not part of a category"
    assert cell.evidence == (EvidenceId("E0001"),)


def test_a_declared_label_never_fills_a_cell_from_an_absence_record() -> None:
    """`not_reported` is the reason a cell stays empty, label or no label (Product 11)."""
    absent = evidence_for(
        "E0001",
        "W0001",
        "",
        negative_state=NegativeEvidenceState.NOT_REPORTED,
        labels=("behavior_aware",),
    )

    matrix = build((absent,), ("W0001",))

    assert matrix.cells[0].labels == ()


def test_a_cell_links_the_accepted_evidence_that_justified_it() -> None:
    raw = evidence_for("E0001", "W0001", "The encoder consumes raw packet bytes.")
    fields = evidence_for("E0002", "W0001", "Each header field is embedded separately.")

    matrix = build((raw, fields), ("W0001",))

    cell = matrix.cells[0]
    assert cell.labels == ("raw_sequential", "field_based")
    assert cell.evidence == (EvidenceId("E0001"), EvidenceId("E0002"))


def test_an_unclassified_work_keeps_an_empty_cell_and_is_never_an_absence() -> None:
    """An empty cell means "not recorded"; reading absence out of it is the §2 failure."""
    silent = evidence_for("E0001", "W0002", "We evaluate on a proprietary corpus.")

    matrix = build((silent,), ("W0001", "W0002"))

    empty = {str(cell.work): cell for cell in matrix.cells}
    assert empty["W0001"].labels == () and empty["W0001"].evidence == ()
    assert empty["W0002"].labels == ()
    assert compare_field(matrix, FIELD).unclassified == (WorkId("W0001"), WorkId("W0002"))


def test_an_absence_record_never_produces_a_label() -> None:
    absent = evidence_for(
        "E0001",
        "W0001",
        "",
        negative_state=NegativeEvidenceState.NOT_REPORTED,
    )

    matrix = build((absent,), ("W0001",))

    assert matrix.cells[0].labels == ()


def test_evidence_recorded_for_another_field_does_not_classify_this_one() -> None:
    """An answer about the dataset is not an answer about representation, however worded."""
    elsewhere = evidence_for(
        "E0001", "W0001", "The dataset is stored as raw packet bytes.", field="dataset"
    )

    matrix = build((elsewhere,), ("W0001",))

    assert matrix.cells[0].labels == ()


def test_a_rule_for_another_field_is_not_applied() -> None:
    """`RULES` contains a `tokenization` rule; building `representation` must ignore it."""
    byte_level = evidence_for("E0001", "W0001", "We use byte-level tokenization.")

    matrix = build((byte_level,), ("W0001",))

    assert matrix.cells[0].labels == ("raw_sequential",)


# -- refusals ----------------------------------------------------------------


def test_a_matrix_is_built_from_accepted_evidence_only() -> None:
    proposed = evidence_for(
        "E0001", "W0001", "byte-level everything", status=EvidenceStatus.PROPOSED
    )

    with pytest.raises(DomainValidationError, match="accepted evidence only"):
        build((proposed,), ("W0001",))


def test_a_rule_may_only_name_a_term_the_taxonomy_approved() -> None:
    invented = (ClassificationRule(term="graph_based", field=FIELD, any_of=("graph",)),)

    with pytest.raises(DomainValidationError, match="outside the approved taxonomy"):
        build((), ("W0001",), rules=invented)


def test_a_matrix_needs_an_accepted_taxonomy_revision_decision() -> None:
    with pytest.raises(DomainValidationError, match="accept it before"):
        build((), ("W0001",), decision=taxonomy_decision(DecisionStatus.PROPOSED))


def test_a_rule_without_a_token_or_phrase_is_refused() -> None:
    empty = (ClassificationRule(term="field_based", field=FIELD, any_of=()),)

    with pytest.raises(DomainValidationError, match="at least one token"):
        build((), ("W0001",), rules=empty)


# -- proposals ---------------------------------------------------------------


def test_model_proposals_are_staged_beside_the_matrix_and_never_written_into_it() -> None:
    """A cell gains a label from a researcher, never from a model (ADR-007)."""
    matrix = build((), ("W0001",))
    proposals = SynthesisOutput(
        cells=[CellProposal(work="W0001", field=FIELD, labels=["field_based"], evidence=["E0001"])],
        notes="W0001 reads as field-based to me",
    )

    unchanged, staged = apply_proposals(matrix, proposals, terms=TERMS, actor="vendor-a/model-x")

    assert unchanged == matrix
    assert unchanged.cells[0].labels == ()
    assert staged.cells[0].labels == ("field_based",)
    assert staged.cells[0].evidence == (EvidenceId("E0001"),)
    assert staged.actor == "vendor-a/model-x"
    assert staged.notes == "W0001 reads as field-based to me"


def test_a_proposal_outside_the_matrix_or_the_taxonomy_is_rejected_not_dropped() -> None:
    matrix = build((), ("W0001",))
    proposals = SynthesisOutput(
        cells=[
            CellProposal(work="W0404", field=FIELD, labels=["field_based"]),
            CellProposal(work="W0001", field=FIELD, labels=["graph_based"]),
        ]
    )

    _, staged = apply_proposals(matrix, proposals, terms=TERMS)

    assert staged.cells == ()
    reasons = [rejected.reason for rejected in staged.rejected]
    assert any("not a row" in reason for reason in reasons)
    assert any("outside the approved taxonomy" in reason for reason in reasons)


# -- comparison and diff -----------------------------------------------------


def test_compare_field_reports_a_row_per_work_including_the_gaps() -> None:
    classified = evidence_for("E0001", "W0001", "We embed each header field separately.")

    table = compare_field(build((classified,), ("W0001", "W0002")), FIELD)

    assert [str(row.work) for row in table.rows] == ["W0001", "W0002"]
    assert table.rows[0].labels == ("field_based",)
    assert table.rows[0].evidence == (EvidenceId("E0001"),)
    assert table.rows[1].labels == () and not table.rows[1].classified
    assert table.label_counts() == {"field_based": 1}
    assert table.as_dict()["unclassified"] == ["W0002"]


def test_comparing_a_field_the_matrix_does_not_hold_is_refused() -> None:
    with pytest.raises(DomainValidationError, match="does not compare"):
        compare_field(build((), ("W0001",)), "tokenization")


def test_matrix_diff_reports_added_removed_and_changed_cells() -> None:
    before = build((evidence_for("E0001", "W0001", "raw packet bytes"),), ("W0001",))
    after = build(
        (
            evidence_for("E0001", "W0001", "raw packet bytes"),
            evidence_for("E0002", "W0001", "and each header field"),
            evidence_for("E0003", "W0002", "behavioural features only"),
        ),
        ("W0001", "W0002"),
    )

    diff = matrix_diff(before, after)

    assert [str(cell.work) for cell in diff.added] == ["W0002"]
    assert diff.removed == ()
    assert diff.changed[0].added_labels == ("field_based",)
    assert diff.changed[0].added_evidence == (EvidenceId("E0002"),)
    assert not diff.is_empty


def test_a_matrix_diffed_against_itself_is_empty() -> None:
    matrix = build((evidence_for("E0001", "W0001", "byte-level encoder"),), ("W0001",))

    assert matrix_diff(matrix, matrix).is_empty


# -- the service over a real workspace ---------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """A workspace with two registered works and one accepted evidence object each."""
    created = init_project(InitProjectRequest(root=tmp_path / "project", name="task-8-2"))
    ctx = open_context(created.root, HUMAN_ACTOR)
    register_corpus(ctx, tmp_path, count=2)
    accept(ctx, "E0001", "W0001", "The encoder consumes raw packet bytes.")
    accept(ctx, "E0002", "W0002", "Each header field is embedded separately.")
    yield ctx


def register_corpus(ctx: CapabilityContext, tmp_path: Path, *, count: int) -> None:
    """Register ``count`` works, each with its own bytes so no artifact check trips."""
    for index in range(1, count + 1):
        path = tmp_path / "sources" / f"paper-{index}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"%PDF-1.7\n% hand-authored source {index}\n".encode())
        external = ProvenanceSource.EXTERNAL_METADATA
        register_work(
            ctx,
            RegisterWorkRequest(
                candidate=WorkCandidate(
                    provenance=Provenance.system(actor="ingest"),
                    metadata=CandidateMetadata(
                        title=IdentifierField(value=f"Paper {index}", source=external),
                        identifiers=WorkIdentifiers(
                            doi=IdentifierField(value=f"10.1234/task-8-2-{index}", source=external)
                        ),
                    ),
                    candidate_file_hash=_digest_bytes(path.read_bytes()),
                    original_filename=path.name,
                ),
                artifact_path=path,
                version_kind=VersionKind.PREPRINT,
                mime_type="application/pdf",
                artifact_kind=ArtifactKind.PDF,
            ),
        )


def accept(ctx: CapabilityContext, evidence_id: str, work: str, text: str) -> None:
    """Accept one hand-authored candidate anchored in the registered artifact."""
    artifact = ctx.repo.list_artifacts(WorkId(work))[0]
    candidate = evidence_for(evidence_id, work, text, status=EvidenceStatus.PROPOSED).touch(
        source=SourceAnchor(
            work=WorkId(work),
            version=artifact.version,
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId("B0001"),
            text_hash=_digest(text),
            page=2,
        )
    )
    accept_evidence(
        ctx,
        AcceptEvidenceRequest(
            candidate=candidate,
            review_action=ReviewAction.ACCEPT,
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the span in the source",
        ),
    )


def test_the_service_classifies_accepted_evidence_and_persists_the_matrix(
    project: CapabilityContext,
) -> None:
    service = SynthesisService(project)
    service.revise_taxonomy(FIELD, TERMS, "three representation families")

    matrix, result = service.build(FIELD, FIELD, RULES)

    stored = project.repo.get_matrix(matrix.id)
    labels = {str(cell.work): cell.labels for cell in stored.cells}
    assert labels == {"W0001": ("raw_sequential",), "W0002": ("field_based",)}
    assert stored.cells[0].evidence == (EvidenceId("E0001"),)
    assert result.event.event.value == "matrix.built"
    assert stored.provenance.note is not None and "D0001" in stored.provenance.note


def test_rebuilding_the_same_field_reuses_the_matrix_id(project: CapabilityContext) -> None:
    service = SynthesisService(project)
    service.revise_taxonomy(FIELD, TERMS, "three representation families")
    first, _ = service.build(FIELD, FIELD, RULES)

    second, _ = service.build(FIELD, FIELD, RULES)

    assert first.id == second.id
    assert [str(matrix.id) for matrix in project.repo.list_matrices()] == [str(first.id)]


def test_compare_reads_the_persisted_matrix(project: CapabilityContext) -> None:
    service = SynthesisService(project)
    service.revise_taxonomy(FIELD, TERMS, "three representation families")
    service.build(FIELD, FIELD, RULES)

    table = service.compare(FIELD)

    assert table.label_counts() == {"field_based": 1, "raw_sequential": 1}
    assert table.unclassified == ()


def test_a_model_proposal_is_staged_and_the_matrix_is_left_alone(
    project: CapabilityContext,
) -> None:
    service = SynthesisService(project)
    service.revise_taxonomy(FIELD, TERMS, "three representation families")
    built, _ = service.build(FIELD, FIELD, RULES)
    provider = ScriptedProvider(
        [
            SynthesisOutput(
                cells=[
                    CellProposal(
                        work="W0002",
                        field=FIELD,
                        labels=["behavior_aware"],
                        evidence=["E0002"],
                    )
                ],
                notes="W0002 also reads as behaviour-aware",
            )
        ]
    )

    proposal = service.propose_with_model(FIELD, provider)

    assert proposal.cells[0].labels == ("behavior_aware",)
    assert (service.staging_dir / f"{built.id}.json").is_file()
    assert service.staged(built.id) == proposal
    stored = project.repo.get_matrix(built.id)
    assert {str(cell.work): cell.labels for cell in stored.cells}["W0002"] == ("field_based",)


def test_the_synthesizer_is_never_shown_unaccepted_evidence(
    project: CapabilityContext,
) -> None:
    service = SynthesisService(project)
    service.revise_taxonomy(FIELD, TERMS, "three representation families")
    service.build(FIELD, FIELD, RULES)
    provider = ScriptedProvider([SynthesisOutput(cells=[])])

    service.propose_with_model(FIELD, provider)

    envelopes = provider.requests[0].inputs
    shown = {envelope.object_id for envelope in envelopes if envelope.kind == "accepted_evidence"}
    assert shown == {"E0001", "E0002"}


def _digest_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def test_matrix_cells_never_carry_a_negative_state_field() -> None:
    """`MatrixCell` has labels and evidence only: there is no place to record an absence."""
    assert set(MatrixCell.model_fields) == {"work", "field", "labels", "evidence"}


def test_the_dependency_graph_reaches_the_matrix_from_its_decision_and_its_evidence(
    project: CapabilityContext,
) -> None:
    """Product 37's chain has to be derivable from canonical fields alone (ADR-008)."""
    service = SynthesisService(project)
    revision = service.revise_taxonomy(FIELD, TERMS, "three representation families")
    matrix, _ = service.build(FIELD, FIELD, RULES)

    graph = DependencyGraph.from_objects(canonical_objects(project.repo))

    assert str(matrix.id) in affected_by(graph, str(revision.decision.id))
    assert str(matrix.id) in affected_by(graph, "E0001")
    assert taxonomy_node_id(FIELD) in affected_by(graph, str(revision.decision.id))

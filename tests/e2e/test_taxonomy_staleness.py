"""Gate P8: revising an accepted taxonomy makes the matrix and its Claim stale.

The chain Product 37 draws is `Taxonomy Decision -> classifications -> matrix -> Claim`.
This walks the whole thing through the real CLI: capture the corpus, accept a taxonomy
Decision, build the matrix, read a Claim off it, and then revise the taxonomy. What has to
be true afterwards is that the downstream objects are *marked*, not rewritten (ADR-008):

* the mutation reports the matrix and the Claim as stale, ordered by scientific impact;
* a full projection rebuild from canonical files alone agrees with that report;
* the superseded Decision, its taxonomy revision events, and the matrix file itself are
  all still exactly as they were, so the old conclusion stays inspectable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    CreateClaimRequest,
    InitProjectRequest,
    RegisterWorkRequest,
)
from research_harness.capabilities.handlers import (
    accept_evidence,
    create_claim,
    init_project,
    register_work,
)
from research_harness.cli.commands.research import register
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.enums import (
    ArtifactKind,
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    DecisionStatus,
    DecisionType,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
    ResearchEventType,
    ReviewAction,
    ReviewTier,
    StaleState,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.evidence import Evidence, EvidenceContent, SourceAnchor
from research_harness.domain.ids import (
    BlockId,
    ClaimId,
    DecisionId,
    EvidenceId,
    SynthesisId,
    WorkId,
)
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.projection.dependencies import (
    StalePriority,
    StaleSet,
    load_stale_marks,
)
from research_harness.projection.rebuild import rebuild_workspace
from research_harness.projection.schema import create_engine_for
from research_harness.synthesis import ClassificationRule, SynthesisService

FIELD = "representation"
FIRST_TERMS = ("raw_sequential", "field_based")
SECOND_TERMS = ("raw_sequential", "field_based", "behavior_aware")
MATRIX = SynthesisId("S0001")
CLAIM = ClaimId("C0001")

SOURCES: dict[str, str] = {
    "W0001": "The encoder consumes raw packet bytes with no field parsing.",
    "W0002": "Each header field is embedded separately before the transformer.",
}

RULES: tuple[ClassificationRule, ...] = (
    ClassificationRule(
        term="raw_sequential", field=FIELD, any_of=("raw packet bytes", "byte-level")
    ),
    ClassificationRule(term="field_based", field=FIELD, any_of=("header field", "field-based")),
    ClassificationRule(
        term="behavior_aware", field=FIELD, any_of=("flow behaviour", "behavioural")
    ),
)

app = typer.Typer()
register(app)
runner = CliRunner()


# -- workspace ---------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """Two hand-authored works, each with one accepted Evidence object. No parser, no model."""
    created = init_project(InitProjectRequest(root=tmp_path / "project", name="gate-p8"))
    ctx = open_context(created.root, HUMAN_ACTOR)
    for index, (work, text) in enumerate(SOURCES.items(), start=1):
        _register(ctx, tmp_path, index)
        _accept_evidence(ctx, f"E{index:04d}", WorkId(work), text)
    yield ctx


def write_rules(tmp_path: Path, terms: tuple[str, ...]) -> Path:
    """A rules file covering exactly ``terms``; a rule may only name an approved term."""
    path = tmp_path / f"rules-{len(terms)}.json"
    chosen = [
        {"term": rule.term, "field": rule.field, "any_of": list(rule.any_of)}
        for rule in RULES
        if rule.term in terms
    ]
    path.write_text(json.dumps(chosen), encoding="utf-8")
    return path


def _register(ctx: CapabilityContext, tmp_path: Path, index: int) -> None:
    path = tmp_path / "sources" / f"paper-{index}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"%PDF-1.7\n% gate p8 source {index}\n".encode())
    external = ProvenanceSource.EXTERNAL_METADATA
    register_work(
        ctx,
        RegisterWorkRequest(
            candidate=WorkCandidate(
                provenance=Provenance.system(actor="ingest"),
                metadata=CandidateMetadata(
                    title=IdentifierField(value=f"Paper {index}", source=external),
                    identifiers=WorkIdentifiers(
                        doi=IdentifierField(value=f"10.1234/gate-p8-{index}", source=external)
                    ),
                ),
                candidate_file_hash=_digest(path.read_bytes()),
                original_filename=path.name,
            ),
            artifact_path=path,
            version_kind=VersionKind.PREPRINT,
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )


def _accept_evidence(ctx: CapabilityContext, evidence_id: str, work: WorkId, text: str) -> None:
    artifact = ctx.repo.list_artifacts(work)[0]
    accept_evidence(
        ctx,
        AcceptEvidenceRequest(
            candidate=Evidence(
                id=EvidenceId(evidence_id),
                source=SourceAnchor(
                    work=work,
                    version=artifact.version,
                    artifact=artifact.id,
                    file_hash=artifact.file_hash,
                    block=BlockId("B0001"),
                    text_hash=_digest(text.encode()),
                    page=3,
                ),
                content=EvidenceContent(exact_text=text, field=FIELD),
                origin=EvidenceOrigin.SOURCE_OBSERVED,
                evidence_type=EvidenceType.METHOD_DESCRIPTION,
                strength=EvidenceStrength.DIRECT,
                review_tier=ReviewTier.TIER_1,
                provenance=Provenance.human(),
            ),
            review_action=ReviewAction.ACCEPT,
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the span in the source",
        ),
    )


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


# -- the gate flow -----------------------------------------------------------


def run(*args: str) -> Result:
    """Invoke the research capture commands the way a researcher would."""
    return runner.invoke(app, list(args))


def set_taxonomy(root: Path, terms: tuple[str, ...], rationale: str) -> Result:
    return run(
        "taxonomy",
        "set",
        FIELD,
        "--terms",
        ",".join(terms),
        "--rationale",
        rationale,
        "--workspace",
        str(root),
    )


def build_matrix_cli(root: Path, rules_file: Path) -> Result:
    return run(
        "matrix",
        "build",
        FIELD,
        "--taxonomy",
        FIELD,
        "--rules",
        str(rules_file),
        "--workspace",
        str(root),
    )


def read_off_the_matrix(ctx: CapabilityContext) -> Claim:
    """A synthesis Claim: read off the matrix, supported by the evidence in its cells."""
    matrix = ctx.repo.get_matrix(MATRIX)
    cited = tuple(
        ClaimEvidenceRelation(evidence=value, relation=ClaimEvidenceRelationType.SUPPORTS)
        for cell in matrix.cells
        for value in cell.evidence
    )
    claim = Claim(
        id=CLAIM,
        statement="The examined systems split between raw-sequential and field-based framing.",
        type=ClaimType.SYNTHESIS,
        semantics=ClaimSemantics(
            subject="examined_systems", predicate="split_between", object="representation_families"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.OBSERVED_SUBSET, corpus="gate-p8"),
        relations=cited,
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.OBSERVED_SUBSET,
            allowed_strength=ClaimScope.OBSERVED_SUBSET,
        ),
        derived_from=(matrix.id,),
        provenance=Provenance.human(),
    )
    create_claim(ctx, CreateClaimRequest(claim=claim))
    return claim


def rebuild_and_load(ctx: CapabilityContext) -> StaleSet:
    """Rebuild the projection from canonical files alone and read its stale marks back."""
    report = rebuild_workspace(ctx.repo)
    assert report.ok, report.invalid_files
    engine = create_engine_for(ctx.repo.layout.database_file)
    try:
        with engine.begin() as connection:
            return load_stale_marks(connection)
    finally:
        engine.dispose()


def test_gate_p8_a_taxonomy_revision_makes_the_matrix_and_its_claim_stale(
    project: CapabilityContext, tmp_path: Path
) -> None:
    root = project.root
    assert set_taxonomy(root, FIRST_TERMS, "two families to start").exit_code == 0
    assert build_matrix_cli(root, write_rules(tmp_path, FIRST_TERMS)).exit_code == 0
    read_off_the_matrix(project)

    # Nothing has moved yet: every derived object is newer than what it depends on.
    assert not rebuild_and_load(project)
    before = project.repo.layout.matrix_file(MATRIX).read_bytes()
    assert project.repo.get_matrix(MATRIX).stale is StaleState.FRESH
    assert project.repo.get_claim(CLAIM).stale is StaleState.FRESH

    revised = SynthesisService(project).revise_taxonomy(
        FIELD, SECOND_TERMS, "behaviour-aware systems no longer fit either family"
    )

    # 1. The mutation reports what it reached, ordered by scientific impact (Product 37).
    stale = {mark.object_id: mark for mark in revised.stale}
    assert str(MATRIX) in stale
    assert str(CLAIM) in stale
    assert stale[str(CLAIM)].priority is StalePriority.CLAIM
    assert stale[str(MATRIX)].priority is StalePriority.SYNTHESIS
    assert [mark.priority for mark in revised.stale] == sorted(
        (mark.priority for mark in revised.stale), reverse=True
    )

    # 2. A rebuild from canonical files alone reaches the same conclusion (ADR-001).
    recomputed = rebuild_and_load(project)
    assert {str(MATRIX), str(CLAIM)} <= {mark.object_id for mark in recomputed}

    # 3. Nothing downstream was rewritten: the matrix file is byte-for-byte what it was.
    assert project.repo.layout.matrix_file(MATRIX).read_bytes() == before
    assert project.repo.get_matrix(MATRIX).cells[0].labels == ("raw_sequential",)


def test_gate_p8_the_superseded_taxonomy_records_stay_inspectable(
    project: CapabilityContext, tmp_path: Path
) -> None:
    root = project.root
    set_taxonomy(root, FIRST_TERMS, "two families to start")
    build_matrix_cli(root, write_rules(tmp_path, FIRST_TERMS))
    read_off_the_matrix(project)

    revised = SynthesisService(project).revise_taxonomy(
        FIELD, SECOND_TERMS, "behaviour-aware systems no longer fit either family"
    )

    first, second = DecisionId("D0001"), DecisionId("D0002")
    assert revised.decision.id == second
    assert revised.decision.supersedes == first

    # The superseded Decision file is still there, still readable, still accepted.
    old = project.repo.get_decision(first)
    assert project.repo.layout.decision_file(first).is_file()
    assert old.status is DecisionStatus.ACCEPTED
    assert old.type is DecisionType.TAXONOMY_REVISION
    assert old.taxonomy_terms == FIRST_TERMS

    # Both revisions are in the event log, each naming its own Decision.
    revisions = [
        event
        for event in project.repo.iter_events()
        if event.event is ResearchEventType.TAXONOMY_REVISED
    ]
    subjects = {str(subject) for event in revisions for subject in event.subjects}
    assert {str(first), str(second)} <= subjects
    assert [event.payload.get("decision") for event in revisions].count(str(first)) == 1
    assert [event.payload.get("decision") for event in revisions].count(str(second)) == 1


def test_gate_p8_the_stale_matrix_is_reported_and_never_recomputed(
    project: CapabilityContext, tmp_path: Path
) -> None:
    """`stale_matrices` answers "what must I look at", and changes nothing by answering."""
    root = project.root
    set_taxonomy(root, FIRST_TERMS, "two families to start")
    build_matrix_cli(root, write_rules(tmp_path, FIRST_TERMS))
    read_off_the_matrix(project)
    service = SynthesisService(project)
    rebuild_and_load(project)
    assert service.stale_matrices() == ()

    service.revise_taxonomy(FIELD, SECOND_TERMS, "a third family is needed")

    reported = {mark.object_id for mark in service.stale_matrices()}
    assert str(MATRIX) in reported
    assert all(mark.object_id.startswith(str(MATRIX)) for mark in service.stale_matrices())
    assert project.repo.get_matrix(MATRIX).cells[0].labels == ("raw_sequential",)


def test_gate_p8_the_revised_taxonomy_reclassifies_only_when_asked(
    project: CapabilityContext, tmp_path: Path
) -> None:
    """Staleness is an invitation to rebuild, not a rebuild (Product 19.2)."""
    root = project.root
    set_taxonomy(root, FIRST_TERMS, "two families to start")
    build_matrix_cli(root, write_rules(tmp_path, FIRST_TERMS))
    read_off_the_matrix(project)
    SynthesisService(project).revise_taxonomy(FIELD, SECOND_TERMS, "a third family is needed")

    # Dogfood F16: a matrix a Claim was read off is not overwritten by accident.
    with pytest.raises(CapabilityError, match="was read off by C0001"):
        SynthesisService(project).build(FIELD, FIELD, RULES)

    rebuilt, _ = SynthesisService(project).build(FIELD, FIELD, RULES, force=True)

    assert rebuilt.id == MATRIX
    assert {str(cell.work): cell.labels for cell in rebuilt.cells} == {
        "W0001": ("raw_sequential",),
        "W0002": ("field_based",),
    }
    assert project.repo.get_claim(CLAIM).derived_from == (MATRIX,)


def test_rebuilding_a_matrix_prints_the_cells_that_moved(
    project: CapabilityContext, tmp_path: Path
) -> None:
    """Dogfood F16: a rule fix silently reclassified a work and printed `classified 5 of 5`."""
    root = project.root
    assert set_taxonomy(root, FIRST_TERMS, "two families to start").exit_code == 0

    first = build_matrix_cli(root, write_rules(tmp_path, ("field_based",)))
    assert first.exit_code == 0, first.stdout
    assert "changes" not in first.stdout, "a first build has nothing to diff against"

    second = build_matrix_cli(root, write_rules(tmp_path, FIRST_TERMS))

    assert second.exit_code == 0, second.stdout
    assert "changes" in second.stdout
    assert "W0001" in second.stdout and "raw_sequential" in second.stdout

    third = build_matrix_cli(root, write_rules(tmp_path, FIRST_TERMS))
    assert "none; this rebuild classifies the corpus identically" in third.stdout


def test_gate_p8_the_cli_reports_the_stale_set_to_the_researcher(
    project: CapabilityContext, tmp_path: Path
) -> None:
    root = project.root
    set_taxonomy(root, FIRST_TERMS, "two families to start")
    build_matrix_cli(root, write_rules(tmp_path, FIRST_TERMS))
    read_off_the_matrix(project)

    revised = set_taxonomy(root, SECOND_TERMS, "a third family is needed")

    assert revised.exit_code == 0, revised.stdout
    assert "D0002 accepted" in revised.stdout
    assert str(MATRIX) in revised.stdout and str(CLAIM) in revised.stdout

    compared = run("compare", FIELD, "--workspace", str(root), "--json")
    assert compared.exit_code == 0, compared.stdout
    table = json.loads(compared.stdout)
    assert table["label_counts"] == {"field_based": 1, "raw_sequential": 1}
    assert table["unclassified"] == []

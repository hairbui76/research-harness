"""Product §42.K - Atomic accepted-state mutation.

"Interrupting a multi-file canonical mutation leaves either the complete prior state or the
complete new state with its matching event and invalidation set; recovery rejects any
mismatch."

Two shapes of mutation are interrupted at every journal phase:

* **one unit, several files.** `work.register` writes a Work, a Version, an Artifact, the
  artifact bytes, the id counter in `research.yaml`, and the event - six files that are one
  scientific fact (ADR-002). Either all six or none.
* **one session, two units.** Accepting Evidence and creating a Claim are two mutations, so
  interrupting the second leaves the first standing and the second absent - which is the
  right answer, not a half-session.

The last section is the other half of the sentence: an event whose digest disagrees with
the canonical file it describes makes the workspace fail closed on open (Product §8.2).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    CreateClaimRequest,
    RegisterWorkRequest,
)
from research_harness.capabilities.handlers import (
    accept_evidence,
    create_claim,
    register_work,
)
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
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.evidence import Evidence, EvidenceContent, SourceAnchor
from research_harness.domain.ids import BlockId, ClaimId, EvidenceId, WorkId
from research_harness.domain.work import CandidateMetadata, IdentifierField, WorkCandidate
from research_harness.workspace.events import object_digest
from research_harness.workspace.repository import (
    ObjectNotFoundError,
    WorkspaceInconsistentError,
    WorkspaceRepository,
)
from tests.e2e.crash.interrupts import (
    JOURNAL_CRASH_POINTS,
    PowerCutError,
    crash_at,
    leftover_journal,
    reopen,
)
from tests.e2e.invariants.workstation import (
    HUMAN,
    WORK,
    canonical_bytes_digest,
    init_and_ingest,
)

SECOND_WORK = WorkId("W0002")
CLAIM = ClaimId("C0001")
EVIDENCE = EvidenceId("E0001")

CRASH_IDS = [f"{method}@{call}" for method, call in JOURNAL_CRASH_POINTS]


def second_paper(root: Path) -> Path:
    path = root / ".research" / "cache" / "second.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n% a second paper, registered as one atomic unit\n")
    return path


def register_request(path: Path) -> RegisterWorkRequest:
    """`work.register`: one unit that writes a Work, a Version, an Artifact, and bytes."""
    import hashlib

    external = ProvenanceSource.EXTERNAL_METADATA
    return RegisterWorkRequest(
        candidate=WorkCandidate(
            provenance=Provenance.system(actor="ingest"),
            metadata=CandidateMetadata(
                title=IdentifierField(value="Flow-level tokenization", source=external),
                authors=(IdentifierField(value="Z. Other", source=external),),
                year=IdentifierField(value="2025", source=external),
            ),
            candidate_file_hash=f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
            original_filename=path.name,
        ),
        artifact_path=path,
        version_kind=VersionKind.PREPRINT,
        mime_type="application/pdf",
        artifact_kind=ArtifactKind.PDF,
    )


def one_evidence(ctx: CapabilityContext) -> Evidence:
    """A candidate anchored in the ingested paper, ready to be accepted."""
    artifact = next(iter(ctx.repo.list_artifacts(WORK)))
    block = next(iter(ctx.repo.iter_blocks(artifact.id, work=WORK)))
    return Evidence(
        id=EVIDENCE,
        source=SourceAnchor(
            work=WORK,
            version=artifact.version,
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId(str(block.id)),
            text_hash=block.text_hash,
            page=block.page,
        ),
        content=EvidenceContent(exact_text=block.text[:80], field="dataset"),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
        strength=EvidenceStrength.DIRECT,
        provenance=Provenance.human(HUMAN),
    )


def one_claim() -> Claim:
    return Claim(
        id=CLAIM,
        statement="The paper names its evaluation corpus",
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="paper", predicate="names", object="its corpus"),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL, corpus="structured-traffic"),
        relations=(
            ClaimEvidenceRelation(evidence=EVIDENCE, relation=ClaimEvidenceRelationType.SUPPORTS),
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.INDIVIDUAL, allowed_strength=ClaimScope.INDIVIDUAL
        ),
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """A parsed workspace with one Work; the crash happens on what comes after."""
    yield init_and_ingest(tmp_path / "project", name="atomicity")


# ------------------------------------------------------- one unit, six files, every phase


@pytest.mark.parametrize(("method", "on_call"), JOURNAL_CRASH_POINTS, ids=CRASH_IDS)
def test_a_crash_in_any_journal_phase_leaves_the_whole_unit_or_none_of_it(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch, method: str, on_call: int
) -> None:
    """The §42.K sentence, checked at every point the unit can be cut in half."""
    root = project.root
    crash_at(monkeypatch, method, on_call=on_call)
    with pytest.raises(PowerCutError):
        register_work(project, register_request(second_paper(root)))
    monkeypatch.undo()

    recovered = reopen(root)
    repo = recovered.repo
    landed = _work_exists(repo, SECOND_WORK)

    if landed:
        work = repo.get_work(SECOND_WORK)
        assert work.versions and work.artifacts
        assert repo.list_versions(SECOND_WORK) and repo.list_artifacts(SECOND_WORK)
        artifact = repo.list_artifacts(SECOND_WORK)[0]
        assert repo.read_artifact_bytes(artifact)
        assert recovered.summaries("work.ingested") == [
            f"registered {WORK} from synthetic_research_paper.pdf",
            f"registered {SECOND_WORK} from second.pdf",
        ]
    else:
        assert repo.list_versions(SECOND_WORK) == []
        assert repo.list_artifacts(SECOND_WORK) == []
        assert recovered.summaries("work.ingested") == [
            f"registered {WORK} from synthetic_research_paper.pdf"
        ]

    assert recovered.consistency.consistent, recovered.consistency.summary()
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()
    assert recovered.journal == ()


@pytest.mark.parametrize(("method", "on_call"), JOURNAL_CRASH_POINTS, ids=CRASH_IDS)
def test_no_crash_leaves_a_duplicate_or_a_skipped_id(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch, method: str, on_call: int
) -> None:
    """Id allocation is inside the unit, so a rolled-back unit gives its number back."""
    root = project.root
    crash_at(monkeypatch, method, on_call=on_call)
    with pytest.raises(PowerCutError):
        register_work(project, register_request(second_paper(root)))
    monkeypatch.undo()

    recovered = reopen(root)
    repo = recovered.repo
    ids = [str(work.id) for work in repo.list_works()]

    assert len(ids) == len(set(ids))
    if str(SECOND_WORK) not in ids:
        # The number was never consumed: the retry gets it, rather than skipping to W0003.
        retried = register_work(open_context(root, HUMAN), register_request(second_paper(root)))
        assert str(SECOND_WORK) in retried.objects
    assert [str(work.id) for work in WorkspaceRepository.open(root).list_works()] == [
        str(WORK),
        str(SECOND_WORK),
    ]


@pytest.mark.parametrize(("method", "on_call"), JOURNAL_CRASH_POINTS, ids=CRASH_IDS)
def test_a_transient_crash_is_finished_in_process(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch, method: str, on_call: int
) -> None:
    """`WorkspaceTransaction.commit` recovers before it re-raises, so a caller sees whole state."""
    root = project.root
    crash_at(monkeypatch, method, on_call=on_call, once=True)
    with pytest.raises(PowerCutError):
        register_work(project, register_request(second_paper(root)))
    monkeypatch.undo()

    recovered = reopen(root)

    assert recovered.consistency.consistent
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()
    assert recovered.journal == ()


# ---------------------------------------------------- one session, two units, one crash


def test_two_units_in_one_session_commit_independently(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accepting Evidence and creating a Claim are two mutations, not one session."""
    root = project.root
    accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=one_evidence(project),
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the span",
        ),
    )
    crash_at(monkeypatch, "_commit_record")
    with pytest.raises(PowerCutError):
        create_claim(project, CreateClaimRequest(claim=one_claim()))
    monkeypatch.undo()

    recovered = reopen(root)
    repo = recovered.repo

    assert [record.id for record in repo.iter_evidence(WORK)] == [EVIDENCE]
    assert recovered.summaries("evidence.accepted")
    assert recovered.consistency.consistent
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()


def test_the_interrupted_claim_is_either_absent_or_complete_with_its_event(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whichever side of the commit point the crash landed on, the two agree."""
    root = project.root
    accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=one_evidence(project),
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the span",
        ),
    )
    crash_at(monkeypatch, "_write_record")
    with pytest.raises(PowerCutError):
        create_claim(project, CreateClaimRequest(claim=one_claim()))
    monkeypatch.undo()

    recovered = reopen(root)
    created = recovered.summaries("claim.created")

    with pytest.raises(ObjectNotFoundError):
        recovered.repo.get_claim(CLAIM)
    assert created == []
    assert recovered.consistency.consistent


def test_an_interrupted_mutation_writes_no_orphan_event(
    project: CapabilityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event without its mutation is never a valid workspace state (Product §8.2)."""
    root = project.root
    before = len(list(project.repo.iter_events()))
    crash_at(monkeypatch, "_write_record")
    with pytest.raises(PowerCutError):
        create_claim(project, CreateClaimRequest(claim=one_claim()))
    monkeypatch.undo()

    recovered = reopen(root)

    assert len(recovered.events) == before
    assert leftover_journal(recovered.repo.layout) == []


# ------------------------------------------------------------------ recovery fails closed


@pytest.fixture
def tampered(project: CapabilityContext) -> Path:
    """A workspace whose newest event records a digest its canonical file does not have."""
    create_claim(project, CreateClaimRequest(claim=one_claim().touch()))
    events_file = project.repo.layout.events_file
    lines = events_file.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    payload["objects"][str(CLAIM)] = f"sha256:{'0' * 64}"
    lines[-1] = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    events_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return project.root


def test_a_mismatched_event_fails_the_workspace_closed(tampered: Path) -> None:
    """An event and its canonical mutation that disagree make the workspace inconsistent."""
    with pytest.raises(WorkspaceInconsistentError) as raised:
        WorkspaceRepository.open(tampered)

    assert str(CLAIM) in str(raised.value)
    assert "inconsistent" in str(raised.value)


def test_the_report_names_the_object_and_repairs_nothing(tampered: Path) -> None:
    """`repair=True` hands the researcher the report; it never rewrites the science."""
    before = canonical_bytes_digest(tampered)

    repo = WorkspaceRepository.open(tampered, repair=True)

    assert repo.consistency.consistent is False
    assert [issue.key for issue in repo.consistency.issues] == [str(CLAIM)]
    assert "does not match the digest" in repo.consistency.issues[0].reason
    assert canonical_bytes_digest(tampered) == before


def test_the_canonical_claim_is_still_the_one_the_researcher_wrote(tampered: Path) -> None:
    """Failing closed protects the file: the Claim on disk is untouched by the bad event."""
    repo = WorkspaceRepository.open(tampered, repair=True)
    claim = repo.get_claim(CLAIM)

    assert claim.statement == one_claim().statement
    assert object_digest(claim) != f"sha256:{'0' * 64}"


def _work_exists(repo: WorkspaceRepository, work: WorkId) -> bool:
    try:
        repo.get_work(work)
    except ObjectNotFoundError:
        return False
    return True

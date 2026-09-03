"""Gate P13: two providers disagree, and the researcher gets one explicit conflict.

    deliberately feed a fixture where two provider results disagree and verify the user
    receives one explicit conflict rather than one provider silently overwriting the
    other.  -- ROADMAP Gate P13

The fixture is fed twice, at the two places Phase 13 puts a second provider. On the
evidence side, two scripted verifiers read the same numeric candidate and answer
differently; on the claim side, two auditors recommend different scopes for the same
claim. Both runs must end the same way: exactly one open `ConflictRecord`, the first
provider's answer still on record, the queue showing the disagreement first, and not one
byte of canonical state moved until a person decides.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from research_harness.capabilities import extra_handlers as capability_extras
from research_harness.capabilities import handlers as capability_handlers
from research_harness.claims.audit import ClaimAuditInput
from research_harness.domain.base import Provenance
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    ArtifactKind,
    ClaimScope,
    ResearchEventType,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.errors import AuthorityError
from research_harness.domain.ids import ClaimId
from research_harness.domain.research import ResearchEvent
from research_harness.domain.work import Artifact, Version, Work
from research_harness.evidence.conflicts import ConflictKind, ConflictStore
from research_harness.evidence.extraction import extract_candidates
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.evidence.review import ReviewCategory, build_inbox
from research_harness.evidence.staging import (
    CandidateStatus,
    EvidenceCandidate,
    StagingStore,
)
from research_harness.providers.models.cross_verify import (
    DEFAULT_POLICY,
    CrossVerificationGate,
)
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workflows import claim_audit as claim_audit_module
from research_harness.workflows.claim_audit import CROSS_VERIFY_STAGE, run_claim_audit
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.models import RunStatus
from research_harness.workflows.verify import run_verification
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore
from tests.integration.claims.conftest import (
    CLAIM_ID,
    FakeModel,
    auditor_answer,
    gate_p7_claim,
    gate_p7_evidence,
    gate_p7_search_runs,
    gate_p7_works,
    skeptic_answer,
)
from tests.integration.evidence.conftest import (
    ACTOR,
    ARTIFACT,
    FILE_HASH,
    PDF_BYTES,
    VERSION,
    WORK,
    canonical_digest,
    extraction_dict,
    metric_candidate,
    parse_fixture,
)

RUN_ID = "run_20260101T000000Z_deadbeef"
MODEL_ACTOR = "vendor-a/model-x"
HUMAN = "human:alice"

MEASURED = "94.32"
TABLE_QUOTE = "TrafficLM | CICIDS2017 | 94.32 | 93.10"
FIRST_RATIONALE = "The table cell states the value."
SECOND_RATIONALE = "The row is another split entirely."


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def doc() -> ParsedDocument:
    """The synthetic paper parsed by the real parser, once for this module."""
    return parse_fixture()


@pytest.fixture
def workspace(tmp_path: Path, doc: ParsedDocument) -> WorkspaceRepository:
    """An initialised workspace with the fixture ingested through a real transaction."""
    repo = WorkspaceRepository.init(tmp_path / "project", "cross-verify-gate")
    system = Provenance.system(actor="test-fixture", workflow="ingest")
    work = Work(
        id=WORK,
        title="Deep Representations for Encrypted Network Traffic",
        authors=("A. Researcher",),
        year=2024,
        versions=(VERSION,),
        artifacts=(ARTIFACT,),
        provenance=system,
    )
    version = Version(id=VERSION, work=WORK, kind=VersionKind.PREPRINT, provenance=system)
    artifact = Artifact(
        id=ARTIFACT,
        work=WORK,
        version=VERSION,
        kind=ArtifactKind.PDF,
        file_hash=FILE_HASH,
        original_filename="synthetic_research_paper.pdf",
        mime_type="application/pdf",
        size_bytes=len(PDF_BYTES),
        provenance=system,
    )
    event = ResearchEvent(
        event=ResearchEventType.WORK_INGESTED,
        subjects=(WORK,),
        actor=ACTOR,
        summary="ingest the synthetic fixture",
    )
    with repo.transaction(event, actor=ACTOR) as tx:
        tx.put(work)
        tx.put(version)
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)
        tx.put_blocks(doc, work=WORK)
    return repo


@pytest.fixture
def staging(workspace: WorkspaceRepository) -> StagingStore:
    return StagingStore(workspace.layout.research_dir)


@pytest.fixture
def conflicts(workspace: WorkspaceRepository) -> ConflictStore:
    return ConflictStore(workspace.layout.research_dir)


@pytest.fixture
def engine(workspace: WorkspaceRepository) -> WorkflowEngine:
    return WorkflowEngine(RunStore(workspace.layout.research_dir))


@pytest.fixture
def claim_project(tmp_path: Path) -> Path:
    """A canonical claim beside a `.research/` directory; the audit must not move a byte."""
    root = tmp_path / "claim-project"
    (root / "claims").mkdir(parents=True)
    (root / "corpus").mkdir(parents=True)
    (root / ".research").mkdir(parents=True)
    (root / "claims" / f"{CLAIM_ID}.yaml").write_text(
        "id: C0041\nstatement: accepted state\n", encoding="utf-8"
    )
    (root / "corpus" / "evidence.jsonl").write_text('{"id": "E0001"}\n', encoding="utf-8")
    return root


# ---------------------------------------------------------------------------- helpers


def verdict_dict(verdict: VerificationVerdict, rationale: str) -> dict[str, Any]:
    """One `VerificationOutput` payload as a verifier would emit it."""
    return {
        "verdict": verdict.value,
        "rationale": rationale,
        "quoted_support": TABLE_QUOTE,
        "discrepancies": [],
    }


def stage_numeric(doc: ParsedDocument, staging: StagingStore) -> EvidenceCandidate:
    """The numeric candidate, produced by the real extraction path."""
    provider = ScriptedProvider(
        [extraction_dict([metric_candidate(doc)])], name="scripted-x", model="model-x"
    )
    result = extract_candidates(
        doc,
        DEFAULT_SCHEMA,
        provider,
        run_id=RUN_ID,
        fields=["metric_result"],
        staging=staging,
    )
    (candidate,) = result.candidates
    return candidate


def disagreeing_verifiers() -> tuple[ScriptedProvider, ScriptedProvider]:
    """Provider A says supported, provider B says contradicted, about the same number.

    A answers twice: once as the verifier of record, once as the first side of the
    cross-check, so both calls are real provider calls rather than a replayed answer.
    """
    first = ScriptedProvider(
        [verdict_dict(VerificationVerdict.SUPPORTED, FIRST_RATIONALE)] * 2,
        name="scripted-a",
        model="model-a",
    )
    second = ScriptedProvider(
        [verdict_dict(VerificationVerdict.CONTRADICTED, SECOND_RATIONALE)],
        name="scripted-b",
        model="model-b",
    )
    return first, second


def disagreeing_audit() -> ClaimAuditInput:
    """One claim audit whose two auditors recommend different scopes."""
    return ClaimAuditInput(
        claim=gate_p7_claim(),
        evidence=gate_p7_evidence(),
        works=gate_p7_works(),
        search_runs=gate_p7_search_runs(),
        skeptic=FakeModel("vendor-a", skeptic_answer(), model="model-x"),
        auditor=FakeModel("vendor-a", auditor_answer(ClaimScope.CORPUS_PATTERN), model="model-x"),
        cross_verify_providers=(
            (
                FakeModel("vendor-a", auditor_answer(ClaimScope.CORPUS_PATTERN), model="model-x"),
                "model-x",
            ),
            (
                FakeModel("vendor-b", auditor_answer(ClaimScope.OBSERVED_SUBSET), model="model-y"),
                "model-y",
            ),
        ),
    )


def agreeing_audit() -> ClaimAuditInput:
    """The same audit, with both auditors recommending the same scope."""
    return ClaimAuditInput(
        claim=gate_p7_claim(),
        evidence=gate_p7_evidence(),
        works=gate_p7_works(),
        search_runs=gate_p7_search_runs(),
        skeptic=FakeModel("vendor-a", skeptic_answer(), model="model-x"),
        auditor=FakeModel("vendor-a", auditor_answer(ClaimScope.CORPUS_PATTERN), model="model-x"),
        cross_verify_providers=(
            (
                FakeModel("vendor-a", auditor_answer(ClaimScope.CORPUS_PATTERN), model="model-x"),
                "model-x",
            ),
            (
                FakeModel("vendor-b", auditor_answer(ClaimScope.CORPUS_PATTERN), model="model-y"),
                "model-y",
            ),
        ),
    )


def tree_digest(root: Path, *, skip: str) -> dict[str, str]:
    """Path -> content digest for every file under `root`, ignoring one subtree."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and skip not in path.relative_to(root).parts
    }


def forbid_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every capability handler explode, so a stage that calls one fails loudly."""

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("a cross-verification stage must not call a capability")

    for module in (capability_handlers, capability_extras):
        for name in getattr(module, "__all__", ()):
            value = getattr(module, name, None)
            if callable(value) and not isinstance(value, type):
                monkeypatch.setattr(module, name, refuse)


# ------------------------------------------------- provider A versus provider B: evidence


def test_two_verifiers_that_disagree_leave_one_conflict_and_no_overwrite(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
    conflicts: ConflictStore,
) -> None:
    candidate = stage_numeric(doc, staging)
    before = canonical_digest(workspace.root)
    first, second = disagreeing_verifiers()

    report = run_verification(
        engine,
        staging,
        workspace,
        WORK,
        first,
        cross_verify_providers=[first, second],
        policy=DEFAULT_POLICY,
    )

    # One explicit conflict, on disk, under the disposable research tree.
    stored = conflicts.list(status="open")
    assert len(stored) == 1
    (record,) = stored
    assert record.subject == candidate.candidate_id
    assert record.kind is ConflictKind.PROVIDER_DISAGREEMENT
    assert record.gate is CrossVerificationGate.NUMERIC_HIGH_IMPACT
    assert record.differing_fields == ("verdict",)
    assert record.labels == ("scripted-a/model-a", "scripted-b/model-b")
    assert conflicts.root == workspace.layout.research_dir / "staging" / "conflicts"
    assert conflicts.path_for(record.subject, record.conflict_id).is_file()
    assert report.conflicts == stored

    # Neither provider overwrote the other: the verdict of record is still the first one.
    staged = staging.get(candidate.candidate_id)
    assert staged.verification is not None
    assert staged.verification.verdict is VerificationVerdict.SUPPORTED
    assert staged.verification.rationale == FIRST_RATIONALE
    assert staged.verifier == "scripted-a/model-a"
    assert staged.status is CandidateStatus.VERIFIED
    assert canonical_digest(workspace.root) == before


def test_the_researcher_sees_the_disagreement_first_with_both_positions(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    candidate = stage_numeric(doc, staging)
    first, second = disagreeing_verifiers()
    run_verification(
        engine, staging, workspace, WORK, first, cross_verify_providers=[first, second]
    )

    queue = build_inbox(staging, workspace)

    item = queue.next()
    assert item is not None
    assert item.candidate_id == candidate.candidate_id
    assert item.category is ReviewCategory.CONFLICT
    assert item.priority == 0
    conflict = item.provider_conflict
    assert conflict is not None
    assert [position.label for position in conflict.positions] == [
        "scripted-a/model-a",
        "scripted-b/model-b",
    ]
    assert [position.decision["verdict"] for position in conflict.positions] == [
        "supported",
        "contradicted",
    ]
    assert item.as_dict()["exact_text"] == MEASURED
    assert [change["to"] for change in item.proposed_changes] == ["supported", "contradicted"]


# ---------------------------------------------------- provider A versus provider B: claim


def test_two_auditors_that_disagree_leave_one_conflict_and_the_claim_untouched(
    claim_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    research_dir = claim_project / ".research"
    engine = WorkflowEngine(RunStore(research_dir))
    conflicts = ConflictStore(research_dir)
    data = disagreeing_audit()
    before = tree_digest(claim_project, skip=".research")
    forbid_capabilities(monkeypatch)

    run, result = run_claim_audit(
        engine, research_dir, lambda: data, ClaimId(CLAIM_ID), policy=DEFAULT_POLICY
    )

    assert run.status is RunStatus.succeeded
    stored = conflicts.list(status="open")
    assert len(stored) == 1
    (record,) = stored
    assert record.subject == CLAIM_ID
    assert record.kind is ConflictKind.PROVIDER_DISAGREEMENT
    assert record.gate is CrossVerificationGate.NUMERIC_HIGH_IMPACT
    assert record.labels == ("vendor-a/model-x", "vendor-b/model-y")
    assert [change["from"] for change in record.proposed_changes] == [
        ClaimScope.CORPUS_PATTERN.value
    ] * 2

    checkpoint = engine.store.load_checkpoint(run.run_id, CROSS_VERIFY_STAGE)
    assert checkpoint is not None
    assert checkpoint["conflict"] is True
    assert checkpoint["conflict_id"] == record.conflict_id

    # Nobody won: the recommendation is still the deterministic engine's own.
    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert tree_digest(claim_project, skip=".research") == before


def test_the_claim_stays_untouched_until_a_person_resolves_the_conflict(
    claim_project: Path,
) -> None:
    research_dir = claim_project / ".research"
    engine = WorkflowEngine(RunStore(research_dir))
    conflicts = ConflictStore(research_dir)
    run_claim_audit(
        engine,
        research_dir,
        disagreeing_audit,
        ClaimId(CLAIM_ID),
        policy=DEFAULT_POLICY,
    )
    (record,) = conflicts.list()
    before = tree_digest(claim_project, skip=".research")

    with pytest.raises(AuthorityError):
        conflicts.resolve(record.conflict_id, "accept", "the wider scope reads better", MODEL_ACTOR)
    assert conflicts.get(record.conflict_id).is_open

    resolved = conflicts.resolve(
        record.conflict_id, "reject", "the narrower reading is the defensible one", HUMAN
    )

    assert resolved.status == "resolved"
    assert resolved.resolution is not None
    assert resolved.resolution.actor == HUMAN
    assert conflicts.list(status="open") == []
    # Closing a conflict is not itself a canonical mutation: writing the audit back to the
    # claim is a separate researcher act through the capability layer (ADR-001, ADR-004).
    assert tree_digest(claim_project, skip=".research") == before


def test_two_auditors_that_agree_leave_nothing_behind(
    claim_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agreement is not acceptance, so it is not even a record (ADR-007, Task 13.2)."""
    research_dir = claim_project / ".research"
    engine = WorkflowEngine(RunStore(research_dir))
    conflicts = ConflictStore(research_dir)
    before = tree_digest(claim_project, skip=".research")
    forbid_capabilities(monkeypatch)

    run, result = run_claim_audit(
        engine, research_dir, agreeing_audit, ClaimId(CLAIM_ID), policy=DEFAULT_POLICY
    )

    assert run.status is RunStatus.succeeded
    assert result.cross_verification is not None
    assert result.cross_verification.agreement is True
    assert result.conflict is None
    assert conflicts.list() == []
    assert not conflicts.root.exists()

    checkpoint = engine.store.load_checkpoint(run.run_id, CROSS_VERIFY_STAGE)
    assert checkpoint is not None
    assert checkpoint["agreement"] is True
    assert checkpoint["conflict_id"] is None
    assert tree_digest(claim_project, skip=".research") == before


def test_the_cross_verify_stage_imports_no_capability(claim_project: Path) -> None:
    """The stage cannot call a capability because it never imported one (ADR-004)."""
    modules = {
        getattr(value, "__module__", "") or "" for value in vars(claim_audit_module).values()
    }

    assert not [name for name in modules if name.startswith("research_harness.capabilities")]

"""Gate P9: sentence -> Claim -> Evidence -> exact PDF span, plus the six audit findings.

The fixture in `conftest.py` is built so that each of the six Product 30.3 finding kinds has
exactly one cause, which makes the assertions here about *locations* rather than counts: a
regression that moves a finding to the wrong sentence fails just as loudly as one that
drops it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.domain.enums import (
    FindingSeverity,
    ManuscriptAnchorStatus,
    ManuscriptFindingKind,
)
from research_harness.domain.ids import ClaimId, EvidenceId
from research_harness.manuscript import LatexProject
from research_harness.manuscript.anchors import anchor_key
from research_harness.manuscript.audit import (
    AuditContext,
    ManuscriptAuditReport,
    audit_manuscript,
)
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.manuscript_audit import (
    AUDIT_STAGE,
    LOAD_STAGE,
    MANUSCRIPT_AUDIT_WORKFLOW,
    REPORT_STAGE,
    REVALIDATE_STAGE,
    build_manuscript_audit_workflow,
    report_path,
    run_manuscript_audit,
)
from research_harness.workflows.models import RunStatus, StageStatus
from research_harness.workspace.runs import RunStore
from tests.e2e.conftest import (
    ANCHOR_LINES,
    MEASURED_PAGE,
    MEASURED_VALUE,
    UNANCHORED_LINE,
    ResearchGraph,
    sentence_on_line,
)

KINDS = tuple(ManuscriptFindingKind)


@pytest.fixture(scope="module")
def report(audit_context: AuditContext) -> ManuscriptAuditReport:
    return audit_manuscript(audit_context)


def line_of(finding_message: str) -> int:
    """The 1-based line every finding message opens with, as `main.tex:<line>: ...`."""
    return int(finding_message.split(":")[1])


def only(report: ManuscriptAuditReport, kind: ManuscriptFindingKind) -> str:
    found = report.of_kind(kind)
    assert len(found) == 1, f"expected exactly one {kind.value}, got {[f.message for f in found]}"
    return found[0].message


# -- the audit ------------------------------------------------------------------------


def test_every_product_30_3_finding_kind_fires_exactly_once(
    report: ManuscriptAuditReport,
) -> None:
    assert {kind: len(report.of_kind(kind)) for kind in KINDS} == dict.fromkeys(KINDS, 1)
    assert len(report.findings) == len(KINDS)


def test_findings_are_reported_in_document_order(report: ManuscriptAuditReport) -> None:
    lines = [line_of(finding.message) for finding in report.findings]
    assert lines == sorted(lines)


def test_an_unanchored_substantive_sentence_is_an_unregistered_claim(
    report: ManuscriptAuditReport,
) -> None:
    message = only(report, ManuscriptFindingKind.UNREGISTERED_CLAIM)
    assert line_of(message) == UNANCHORED_LINE
    # The message says what the kind does not. It used to read "substantive sentence is
    # attached to no Claim", which is `unregistered_claim` spelled out a second time: every
    # client prints the kind beside it — the cockpit's card reads "Unregistered claim -
    # <message>" — so one fact was stated twice and no next step was offered at all.
    assert "attached to no Claim" not in message
    assert "the sentence" in message
    assert "anchor it to a Claim" in message
    assert report.unanchored_substantive == 1
    assert report.anchored_sentences == len(ANCHOR_LINES)
    assert report.sentences_checked == len(ANCHOR_LINES) + 1


def test_universal_wording_over_a_corpus_level_claim_is_flagged(
    report: ManuscriptAuditReport, audit_graph: ResearchGraph
) -> None:
    finding = report.of_kind(ManuscriptFindingKind.OVER_STRONG_WORDING)[0]
    assert line_of(finding.message) == ANCHOR_LINES[ClaimId("C0001")]
    assert "L4 universal_or_absence" in finding.message
    assert "L2 corpus_pattern" in finding.message
    assert finding.severity is FindingSeverity.WARNING
    assert finding.related == (ClaimId("C0001"),)
    assert finding.anchor is not None
    assert finding.anchor.claim == ClaimId("C0001")
    assert audit_graph.claims[ClaimId("C0001")].allowed_strength.label == "L2 corpus_pattern"


def test_a_resolvable_citation_whose_work_supports_nothing_is_a_mismatch(
    report: ManuscriptAuditReport,
) -> None:
    finding = report.of_kind(ManuscriptFindingKind.CITATION_MISMATCH)[0]
    assert line_of(finding.message) == ANCHOR_LINES[ClaimId("C0002")]
    assert "'ostrom2020'" in finding.message
    assert "citation existence is not evidence support" in finding.message
    assert finding.severity is FindingSeverity.ERROR
    assert ClaimId("C0002") in finding.related


def test_a_number_no_evidence_measures_is_reported_and_the_measured_one_is_not(
    report: ManuscriptAuditReport,
) -> None:
    finding = report.of_kind(ManuscriptFindingKind.UNSUPPORTED_NUMERIC)[0]
    assert line_of(finding.message) == ANCHOR_LINES[ClaimId("C0003")]
    assert "'71.40'" in finding.message
    assert MEASURED_VALUE not in finding.message
    assert finding.severity is FindingSeverity.WARNING


def test_a_stale_claim_reaches_the_manuscript_as_a_finding(
    report: ManuscriptAuditReport,
) -> None:
    finding = report.of_kind(ManuscriptFindingKind.STALE_CLAIM)[0]
    assert line_of(finding.message) == ANCHOR_LINES[ClaimId("C0004")]
    assert "marked stale" in finding.message
    assert finding.related == (ClaimId("C0004"),)


def test_supporting_evidence_whose_artifact_changed_invalidates_the_provenance(
    report: ManuscriptAuditReport,
) -> None:
    finding = report.of_kind(ManuscriptFindingKind.INVALID_EVIDENCE_ANCHOR)[0]
    assert line_of(finding.message) == ANCHOR_LINES[ClaimId("C0005")]
    assert "no longer opens at its source" in finding.message
    assert "artifact bytes changed" in finding.message
    assert finding.severity is FindingSeverity.ERROR
    assert set(finding.related) == {ClaimId("C0005"), EvidenceId("E0003")}


def test_every_anchor_still_resolves_to_its_sentence(report: ManuscriptAuditReport) -> None:
    assert len(report.revalidations) == len(ANCHOR_LINES)
    assert {result.status for result in report.revalidations} == {ManuscriptAnchorStatus.VALID}


# -- Gate P9: sentence -> Claim -> Evidence -> exact PDF span --------------------------


def test_the_supported_sentence_traces_to_the_exact_pdf_span(
    report: ManuscriptAuditReport, audit_project: LatexProject, audit_graph: ResearchGraph
) -> None:
    sentence = sentence_on_line(audit_project, ANCHOR_LINES[ClaimId("C0006")])
    anchor = next(item for item in audit_graph.anchors if item.claim == ClaimId("C0006"))
    link = report.trace_for(anchor_key(anchor))

    assert link is not None
    assert link.sentence.fingerprint == sentence.fingerprint
    assert link.claim == ClaimId("C0006")
    assert link.evidence == (EvidenceId("E0001"),)
    assert len(link.spans) == 1
    span = link.spans[0]
    assert span.page == MEASURED_PAGE == 4
    assert span.text == MEASURED_VALUE == "94.32"
    assert span.bbox is not None


def test_a_broken_evidence_anchor_yields_a_trace_link_with_no_span(
    report: ManuscriptAuditReport, audit_graph: ResearchGraph
) -> None:
    anchor = next(item for item in audit_graph.anchors if item.claim == ClaimId("C0005"))
    link = report.trace_for(anchor_key(anchor))
    assert link is not None
    assert link.evidence == (EvidenceId("E0003"),)
    assert link.spans == ()


def test_the_audit_is_deterministic(audit_context: AuditContext) -> None:
    first = audit_manuscript(audit_context)
    second = audit_manuscript(audit_context)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


# -- the durable workflow -------------------------------------------------------------


def tree_digest(root: Path, *, skip: str) -> str:
    """Hash of every file under `root` except the regenerable directory `skip`."""
    digest = hashlib.sha256()
    for path in sorted(_files(root)):
        if skip in path.relative_to(root).parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _files(root: Path) -> Iterator[Path]:
    return (path for path in root.rglob("*") if path.is_file())


@pytest.fixture
def workspace(tmp_path: Path, audit_project: LatexProject) -> Path:
    """A workspace with canonical-looking files beside a regenerable `.research/`."""
    canonical = tmp_path / "corpus"
    canonical.mkdir()
    (canonical / "claims.yaml").write_text("# accepted state\n", encoding="utf-8")
    (canonical / "manuscript.tex").write_text(
        audit_project.file(audit_project.main).text
        if audit_project.file(audit_project.main)
        else "",
        encoding="utf-8",
    )
    (tmp_path / ".research").mkdir()
    return tmp_path


def test_the_workflow_runs_all_four_stages_and_writes_its_report(
    workspace: Path, audit_context: AuditContext
) -> None:
    research_dir = workspace / ".research"
    engine = WorkflowEngine(RunStore(research_dir))
    before = tree_digest(workspace, skip=".research")

    run, report = run_manuscript_audit(engine, research_dir, lambda: audit_context)

    assert run.workflow == MANUSCRIPT_AUDIT_WORKFLOW
    assert run.status is RunStatus.succeeded
    assert [stage.name for stage in run.stages] == [
        LOAD_STAGE,
        REVALIDATE_STAGE,
        AUDIT_STAGE,
        REPORT_STAGE,
    ]
    assert len(report.findings) == len(KINDS)

    written = report_path(research_dir, run.run_id)
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert len(payload["findings"]) == len(KINDS)
    assert {finding["kind"] for finding in payload["findings"]} == {kind.value for kind in KINDS}

    assert tree_digest(workspace, skip=".research") == before, "the audit wrote canonical state"
    assert written.is_relative_to(research_dir / "staging")


def test_rerunning_the_workflow_reuses_every_checkpoint(
    workspace: Path, audit_context: AuditContext
) -> None:
    research_dir = workspace / ".research"
    engine = WorkflowEngine(RunStore(research_dir))
    run, _ = run_manuscript_audit(engine, research_dir, lambda: audit_context)

    resumed, again = run_manuscript_audit(
        engine, research_dir, lambda: audit_context, run_id=run.run_id
    )

    assert resumed.run_id == run.run_id
    assert resumed.status is RunStatus.succeeded
    assert [stage.status for stage in resumed.stages] == [StageStatus.skipped_cached] * 4
    assert len(again.findings) == len(KINDS)
    assert build_manuscript_audit_workflow(lambda: audit_context).name == (
        MANUSCRIPT_AUDIT_WORKFLOW
    )


def test_editing_the_manuscript_invalidates_the_load_checkpoint(
    workspace: Path, audit_context: AuditContext, tmp_path: Path
) -> None:
    research_dir = workspace / ".research"
    engine = WorkflowEngine(RunStore(research_dir))
    run, _ = run_manuscript_audit(engine, research_dir, lambda: audit_context)
    before = run.stage(LOAD_STAGE).input_fingerprint

    edited = tmp_path / "edited"
    edited.mkdir()
    source = audit_context.project.file(audit_context.project.main)
    assert source is not None
    (edited / "main.tex").write_text(source.text.replace("94.32", "94.31"), encoding="utf-8")
    reworded = AuditContext(
        project=LatexProject.load(edited / "main.tex"),
        bib=audit_context.bib,
        anchors=audit_context.anchors,
        claims=audit_context.claims,
        evidence=audit_context.evidence,
        works=audit_context.works,
        parsed=audit_context.parsed,
    )

    resumed, report = run_manuscript_audit(
        engine, research_dir, lambda: reworded, run_id=run.run_id
    )
    assert resumed.stage(LOAD_STAGE).input_fingerprint != before
    assert resumed.stage(LOAD_STAGE).status is StageStatus.succeeded
    # The reword changed a sentence fingerprint, so its anchor goes stale rather than
    # silently following the edit (ADR-008).
    assert ManuscriptAnchorStatus.STALE in {result.status for result in report.revalidations}

"""Gate P9 through the CLI: a real PDF, a real LaTeX project, and one terminal session.

`tests/e2e/test_manuscript_audit.py` proves the auditor over a hand-built context. This
file proves the same chain the way a researcher meets it - `research init`, `ingest`,
`parse`, then `manuscript attach`, `manuscript audit`, `manuscript trace`, `draft` - over a
workspace whose Evidence is anchored in the bytes the ingest actually stored.

The manuscript is four sentences and each one is there for a reason:

===== ========================================================= ========================
line  sentence                                                  expected
===== ========================================================= ========================
15    "Every encrypted traffic classifier ... no prior work"     `over_strong_wording`
18    "The corrected split we adopt ..."                         `citation_mismatch`
21    "TrafficLM reaches an F1 of 94.32 on CICIDS2017 ..."       the Gate P9 trace
24    "Our sweep shows ..." (unanchored)                         `unregistered_claim`
===== ========================================================= ========================

Both citations resolve; the mismatch is the Product 42.J case where a key exists, names a
corpus Work, and still supports nothing the sentence's Claim leans on.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import AcceptEvidenceRequest, CreateClaimRequest
from research_harness.capabilities.handlers import accept_evidence, create_claim
from research_harness.cli.app import app
from research_harness.cli.commands import manuscript as manuscript_commands
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
    Coverage,
)
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DocumentBlockKind,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ManuscriptFindingKind,
    VerificationVerdict,
)
from research_harness.domain.evidence import Evidence, EvidenceContent, NumericValue
from research_harness.domain.ids import ArtifactId, ClaimId, EvidenceId, VersionId, WorkId
from research_harness.manuscript.draft import DRAFT_SUFFIX, NEEDS_SOURCE
from research_harness.parsing import ParseTarget, PyMuPdfParser, build_anchor, cell_span
from tests.fixtures.make_synthetic_paper import GROUND_TRUTH

PAPER = GROUND_TRUTH["synthetic_research_paper"]
MEASURED_VALUE = "94.32"
MEASURED_PAGE = PAPER["table"]["page"]

WORK = WorkId("W0001")
VERSION = VersionId("V0001-1")
ARTIFACT = ArtifactId("A0001-1")
MEASURED = EvidenceId("E0001")
DATASET_EVIDENCE = EvidenceId("E0002")
SUPPORTED_CLAIM = ClaimId("C0001")
UNSUPPORTED_CLAIM = ClaimId("C0002")

HUMAN = "human:alice"
BIB_KEY = "traffic2024"

OVER_STRONG_LINE = 15
MISMATCH_LINE = 18
MEASURED_LINE = 21
UNANCHORED_LINE = 24

MAIN_TEX = f"""% Gate P9 CLI fixture. No number here is a real measurement of anything but the
% synthetic paper in tests/fixtures/, whose Table 1 records {MEASURED_VALUE}.
\\documentclass[11pt]{{article}}
\\usepackage{{natbib}}

\\title{{Encrypted Traffic Classification Under Sustained Load}}
\\author{{R. Hale}}

\\begin{{document}}
\\maketitle

\\section{{Introduction}}
\\label{{sec:intro}}

Every encrypted traffic classifier fails under sustained load, and no prior work reports
the size of the gap \\citep{{{BIB_KEY}}}.

The corrected split we adopt for evaluation follows the protocol of the cited release
\\citep{{{BIB_KEY}}}.

TrafficLM reaches an F1 of {MEASURED_VALUE} on CICIDS2017 under the held-out protocol
\\citep{{{BIB_KEY}}}.

Our sweep shows that detection quality degrades as the offered load grows.

\\bibliographystyle{{plainnat}}
\\bibliography{{references}}

\\end{{document}}
"""

REFERENCES_BIB = f"""% One entry, matched to the corpus Work by its normalized title. It
% exists, it resolves, and it still supports only the Claim whose evidence comes from that
% Work - which is the Product 42.J case.

@inproceedings{{{BIB_KEY},
  author    = {{Researcher, A. and Collaborator, B. and Advisor, C.}},
  title     = {{Deep Representations for Encrypted Network Traffic}},
  booktitle = {{Proceedings of the Example Conference on Networking}}
}}
"""

WRITER_SCRIPT: dict[str, Any] = {
    "draft": (
        "TrafficLM reaches an F1 of 94.32 on CICIDS2017 under the held-out protocol. "
        "Deployment cost halves in production settings."
    ),
    "claim_refs": [str(SUPPORTED_CLAIM)],
    "evidence_refs": [str(MEASURED)],
    "unsupported_statements": ["Deployment cost halves in production settings."],
    "needs_source": [],
}

runner = CliRunner()


def _ensure_registered() -> None:
    """Mount the manuscript family if the CLI has not been wired to it yet.

    `cli/commands/__init__.py` lists the registered families and is owned by whoever
    assembles the release; this test exercises the real `research` app either way, so it
    registers the module itself only when it is not already there.
    """
    groups = {info.name for info in app.registered_groups}
    commands = {info.name for info in app.registered_commands}
    if "manuscript" not in groups or "draft" not in commands:
        manuscript_commands.register(app)


_ensure_registered()


# -- the session ------------------------------------------------------------------------


def run(*args: str) -> Result:
    """Invoke the real `research` app with ``args``."""
    return runner.invoke(app, list(args))


def ok(*args: str) -> Result:
    result = run(*args)
    assert result.exit_code == 0, f"`research {' '.join(args)}` failed:\n{result.stdout}"
    return result


def payload(result: Result) -> Any:
    return json.loads(result.stdout)


def tree_digest(root: Path) -> str:
    """Hash of every canonical file: everything outside the regenerable `.research/` tree."""
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        if ".research" in path.relative_to(root).parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def source_parse(ctx: CapabilityContext) -> ParsedDocument:
    """Re-parse the ingested artifact from the fixture bytes, with the workspace's ids."""
    artifact = ctx.repo.get_artifact(ARTIFACT, work=WORK)
    return PyMuPdfParser().parse(
        ParseTarget(
            work=WORK,
            version=VERSION,
            artifact=ARTIFACT,
            file_hash=artifact.file_hash,
            path=PAPER["path"],
            mime_type=artifact.mime_type,
        )
    )


def block_containing(doc: ParsedDocument, needle: str) -> DocumentBlock:
    return next(block for block in doc.blocks if needle in block.text)


def accepted(
    evidence_id: EvidenceId,
    doc: ParsedDocument,
    block: DocumentBlock,
    span: tuple[int, int],
    *,
    evidence_type: EvidenceType,
    numeric: NumericValue | None = None,
) -> Evidence:
    """A source-observed, direct candidate anchored in the real parse of the real bytes."""
    return Evidence(
        id=evidence_id,
        source=build_anchor(doc, block, span[0], span[1]),
        content=EvidenceContent(exact_text=block.text[span[0] : span[1]], numeric=numeric),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=evidence_type,
        strength=EvidenceStrength.DIRECT,
        provenance=Provenance.human(HUMAN),
    )


def make_claim(
    claim_id: ClaimId,
    statement: str,
    *,
    allowed: ClaimScope,
    supports: tuple[EvidenceId, ...] = (),
    status: ClaimStatus = ClaimStatus.SUPPORTED,
) -> Claim:
    return Claim(
        id=claim_id,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="TrafficLM", predicate="reports", object=statement[:60]),
        scope=ClaimScopeSpec(level=allowed, corpus="encrypted traffic classifiers"),
        relations=tuple(
            ClaimEvidenceRelation(evidence=item, relation=ClaimEvidenceRelationType.SUPPORTS)
            for item in supports
        ),
        coverage=Coverage(relevant_works=1, examined_works=1),
        assessment=ClaimAssessment(
            requested_strength=allowed,
            allowed_strength=allowed,
            status=status,
            maximum_defensible_wording="most systems in the reviewed corpus",
        ),
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A workspace built the way a researcher builds one, then wired to a manuscript."""
    root = tmp_path_factory.mktemp("gate-p9") / "project"
    ok("init", str(root), "--name", "gate-p9")
    ok("ingest", str(PAPER["path"]), "-w", str(root))
    ok("parse", "W0001", "-w", str(root))

    ctx = open_context(root, HUMAN)
    doc = source_parse(ctx)
    table = next(block for block in doc.blocks if block.kind is DocumentBlockKind.TABLE)
    cell = PAPER["table"]["numeric_cell"]
    measured = accepted(
        MEASURED,
        doc,
        table,
        cell_span(table, cell["row"], cell["col"]),
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
        numeric=NumericValue(
            raw=MEASURED_VALUE,
            parsed=94.32,
            metric="F1",
            dataset="CICIDS2017",
            condition={"split": "held-out"},
            source_table="Table 1",
            source_row="TrafficLM",
            source_column="F1",
        ),
    )
    dataset_block = block_containing(doc, "All experiments use CICIDS2017")
    offset = dataset_block.text.index("All experiments use CICIDS2017")
    dataset = accepted(
        DATASET_EVIDENCE,
        doc,
        dataset_block,
        (offset, offset + 70),
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
    )
    for candidate in (measured, dataset):
        accept_evidence(
            ctx,
            AcceptEvidenceRequest(
                candidate=candidate,
                verdict=VerificationVerdict.SUPPORTED,
                rationale="read from the source by the researcher",
            ),
        )

    create_claim(
        ctx,
        CreateClaimRequest(
            claim=make_claim(
                SUPPORTED_CLAIM,
                "TrafficLM reaches an F1 of 94.32 on CICIDS2017 in the reviewed corpus",
                allowed=ClaimScope.CORPUS_PATTERN,
                supports=(MEASURED, DATASET_EVIDENCE),
            )
        ),
    )
    create_claim(
        ctx,
        CreateClaimRequest(
            claim=make_claim(
                UNSUPPORTED_CLAIM,
                "The corrected split changes the reported operating point",
                allowed=ClaimScope.INDIVIDUAL,
                status=ClaimStatus.UNVERIFIED,
            )
        ),
    )

    manuscript = root / "manuscript"
    (manuscript / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (manuscript / "references.bib").write_text(REFERENCES_BIB, encoding="utf-8")

    ok(
        "manuscript",
        "attach",
        f"main.tex:{OVER_STRONG_LINE}",
        str(SUPPORTED_CLAIM),
        "-w",
        str(root),
    )
    ok(
        "manuscript",
        "attach",
        f"main.tex:{MISMATCH_LINE}",
        str(UNSUPPORTED_CLAIM),
        "-w",
        str(root),
    )
    ok(
        "manuscript",
        "attach-text",
        f"TrafficLM reaches an F1 of {MEASURED_VALUE} on CICIDS2017",
        str(SUPPORTED_CLAIM),
        "-w",
        str(root),
    )
    yield root


# -- attachment through the CLI ---------------------------------------------------------


def test_the_three_attachments_are_the_stored_anchors(workspace: Path) -> None:
    listed = payload(ok("manuscript", "anchors", "-w", str(workspace), "--json"))
    anchors = {item["line_start"]: item for item in listed["anchors"]}

    assert set(anchors) == {OVER_STRONG_LINE, MISMATCH_LINE, MEASURED_LINE}
    assert anchors[OVER_STRONG_LINE]["claim"] == str(SUPPORTED_CLAIM)
    assert anchors[MISMATCH_LINE]["claim"] == str(UNSUPPORTED_CLAIM)
    assert anchors[MEASURED_LINE]["claim"] == str(SUPPORTED_CLAIM)
    assert all(item["citation_keys"] == [BIB_KEY] for item in anchors.values())
    assert all(item["status"] == "valid" for item in anchors.values())


def test_attaching_prints_the_anchor_for_a_human(workspace: Path) -> None:
    text = ok("manuscript", "anchors", "-w", str(workspace)).stdout
    assert f"main.tex:{MEASURED_LINE}" in text
    assert str(SUPPORTED_CLAIM) in text


def test_attaching_to_a_heading_is_one_error_line_and_exit_code_one(workspace: Path) -> None:
    result = run("manuscript", "attach", "main.tex:12", str(SUPPORTED_CLAIM), "-w", str(workspace))
    assert result.exit_code == 1
    assert (result.stdout + result.stderr).count("error:") == 1


def test_revalidating_an_unedited_manuscript_reports_every_anchor_valid(workspace: Path) -> None:
    report = payload(ok("manuscript", "revalidate", "-w", str(workspace), "--dry-run", "--json"))
    assert report["checked"] == 3
    assert report["valid"] == 3
    assert report["stale"] == 0 and report["missing"] == 0
    assert report["dry_run"] is True and report["applied"] == []

    # Applying an all-valid verdict is a no-op, so it is safe to run over the shared
    # workspace and still proves the non-dry-run path serializes.
    applied = payload(ok("manuscript", "revalidate", "-w", str(workspace), "--json"))
    assert applied["applied"] == [] and applied["mutations"] == []
    assert "3 anchors" in ok("manuscript", "revalidate", "-w", str(workspace)).stdout


# -- Gate P9: the audit ------------------------------------------------------------------


@pytest.fixture(scope="module")
def audit(workspace: Path) -> Any:
    return payload(ok("manuscript", "audit", "-w", str(workspace), "--json"))


def kinds(audit: Any) -> dict[str, int]:
    return {kind: count for kind, count in audit["counts"].items() if count}


def test_the_audit_reports_over_strong_wording_and_a_citation_mismatch(audit: Any) -> None:
    assert audit["counts"][ManuscriptFindingKind.OVER_STRONG_WORDING.value] >= 1
    assert audit["counts"][ManuscriptFindingKind.CITATION_MISMATCH.value] >= 1
    assert audit["counts"][ManuscriptFindingKind.UNREGISTERED_CLAIM.value] >= 1
    assert kinds(audit) == {
        ManuscriptFindingKind.UNREGISTERED_CLAIM.value: 1,
        ManuscriptFindingKind.OVER_STRONG_WORDING.value: 1,
        ManuscriptFindingKind.CITATION_MISMATCH.value: 1,
    }


def test_universal_wording_over_a_corpus_level_claim_names_both_levels(audit: Any) -> None:
    finding = _only(audit, ManuscriptFindingKind.OVER_STRONG_WORDING)
    assert f"main.tex:{OVER_STRONG_LINE}" in finding["message"]
    assert "L4 universal_or_absence" in finding["message"]
    assert "L2 corpus_pattern" in finding["message"]
    assert finding["related"] == [str(SUPPORTED_CLAIM)]


def test_a_resolvable_key_that_supports_nothing_is_a_citation_mismatch(audit: Any) -> None:
    finding = _only(audit, ManuscriptFindingKind.CITATION_MISMATCH)
    assert f"main.tex:{MISMATCH_LINE}" in finding["message"]
    assert f"'{BIB_KEY}'" in finding["message"]
    assert "citation existence is not evidence support" in finding["message"]
    assert finding["severity"] == "error"
    assert str(UNSUPPORTED_CLAIM) in finding["related"]


def test_the_unanchored_sentence_is_an_unregistered_claim(audit: Any) -> None:
    finding = _only(audit, ManuscriptFindingKind.UNREGISTERED_CLAIM)
    assert f"main.tex:{UNANCHORED_LINE}" in finding["message"]
    assert audit["unanchored_substantive"] == 1
    assert audit["anchored_sentences"] == 3
    assert audit["sentences_checked"] == 4


def test_the_measured_number_raises_nothing(audit: Any) -> None:
    assert audit["counts"][ManuscriptFindingKind.UNSUPPORTED_NUMERIC.value] == 0
    assert MEASURED_VALUE not in json.dumps(audit["findings"])


def test_the_human_readable_audit_says_the_same_thing(workspace: Path) -> None:
    text = ok("manuscript", "audit", "-w", str(workspace)).stdout
    assert "over_strong_wording" in text
    assert "citation_mismatch" in text
    assert "unregistered_claim" in text
    assert "4 substantive sentences" in text


def test_skipping_the_source_parse_still_audits_the_prose(workspace: Path) -> None:
    report = payload(ok("manuscript", "audit", "-w", str(workspace), "--no-parse", "--json"))
    assert report["counts"][ManuscriptFindingKind.OVER_STRONG_WORDING.value] == 1
    assert report["counts"][ManuscriptFindingKind.CITATION_MISMATCH.value] == 1
    assert all(link["spans"] == [] for link in report["trace"]), "no parse, no source spans"


# -- Gate P9: sentence -> Claim -> Evidence -> exact PDF span ----------------------------


def test_the_measured_sentence_traces_to_the_exact_pdf_span(workspace: Path) -> None:
    link = payload(
        ok("manuscript", "trace", f"main.tex:{MEASURED_LINE}", "-w", str(workspace), "--json")
    )

    assert link["location"] == f"main.tex:{MEASURED_LINE}"
    assert MEASURED_VALUE in link["sentence"]
    assert link["claim"] == str(SUPPORTED_CLAIM)
    assert str(MEASURED) in link["evidence"]

    spans = {span["text"]: span for span in link["spans"]}
    assert MEASURED_VALUE in spans, f"expected a {MEASURED_VALUE!r} span, got {list(spans)}"
    span = spans[MEASURED_VALUE]
    assert span["page"] == MEASURED_PAGE == 4
    assert span["bbox"] is not None and len(span["bbox"]) == 4


def test_the_trace_reads_as_a_chain_for_a_human(workspace: Path) -> None:
    text = ok("manuscript", "trace", f"main.tex:{MEASURED_LINE}", "-w", str(workspace)).stdout
    assert str(SUPPORTED_CLAIM) in text
    assert str(MEASURED) in text
    assert "page 4" in text
    assert MEASURED_VALUE in text


def test_tracing_an_unanchored_sentence_says_so_rather_than_guessing(workspace: Path) -> None:
    link = payload(
        ok("manuscript", "trace", f"main.tex:{UNANCHORED_LINE}", "-w", str(workspace), "--json")
    )
    assert link["claim"] is None
    assert link["evidence"] == [] and link["spans"] == []


# -- drafting ----------------------------------------------------------------------------


def test_drafting_stages_a_candidate_flagged_needs_source_and_changes_nothing(
    workspace: Path, tmp_path: Path
) -> None:
    script = tmp_path / "writer.json"
    script.write_text(json.dumps(WRITER_SCRIPT), encoding="utf-8")
    before = tree_digest(workspace)

    result = payload(
        ok(
            "draft",
            "Results paragraph reporting the held-out operating point",
            "--claims",
            str(SUPPORTED_CLAIM),
            "--provider",
            "scripted",
            "--script",
            str(script),
            "-w",
            str(workspace),
            "--json",
        )
    )

    assert result["claim_refs"] == [str(SUPPORTED_CLAIM)]
    assert result["evidence_refs"] == [str(MEASURED)]
    assert result["needs_source"] == WRITER_SCRIPT["unsupported_statements"]
    assert f"% {NEEDS_SOURCE}:" in result["marked_text"]
    assert result["provenance"]["source"] == "model"

    staged = Path(result["path"])
    assert staged.is_file()
    assert staged.name.endswith(DRAFT_SUFFIX)
    assert staged.is_relative_to(workspace / ".research" / "staging" / "drafts")
    assert NEEDS_SOURCE in staged.read_text(encoding="utf-8")

    assert tree_digest(workspace) == before, "drafting wrote canonical state"
    assert not any((workspace / "manuscript").glob("*.json"))


def test_the_draft_protects_the_numbers_and_citations_it_copied(
    workspace: Path, tmp_path: Path
) -> None:
    script = tmp_path / "writer.json"
    script.write_text(json.dumps(WRITER_SCRIPT), encoding="utf-8")

    result = payload(
        ok(
            "draft",
            "Results paragraph",
            "--claims",
            str(SUPPORTED_CLAIM),
            "--script",
            str(script),
            "-w",
            str(workspace),
            "--json",
        )
    )
    protected = {span["text"] for span in result["protected_spans"]}
    assert MEASURED_VALUE in protected


def test_a_draft_may_not_cite_a_claim_it_was_not_given(workspace: Path, tmp_path: Path) -> None:
    script = tmp_path / "overreach.json"
    script.write_text(
        json.dumps({**WRITER_SCRIPT, "claim_refs": [str(SUPPORTED_CLAIM), "C0404"]}),
        encoding="utf-8",
    )

    result = run(
        "draft",
        "Results paragraph",
        "--claims",
        str(SUPPORTED_CLAIM),
        "--script",
        str(script),
        "-w",
        str(workspace),
    )
    assert result.exit_code == 1
    assert "C0404" in result.stdout + result.stderr


def test_drafting_without_a_claim_is_refused(workspace: Path, tmp_path: Path) -> None:
    script = tmp_path / "writer.json"
    script.write_text(json.dumps(WRITER_SCRIPT), encoding="utf-8")
    result = run(
        "draft", "Results paragraph", "--claims", " ", "--script", str(script), "-w", str(workspace)
    )
    assert result.exit_code == 1


# -- the command family is wired the way the PM expects ----------------------------------


def test_the_module_registers_the_documented_command_names() -> None:
    names = {command.name for command in manuscript_commands.manuscript_app.registered_commands}
    assert names == {"attach", "attach-text", "anchors", "revalidate", "audit", "trace"}
    assert callable(manuscript_commands.register)


def _only(audit: Any, kind: ManuscriptFindingKind) -> Any:
    found = [finding for finding in audit["findings"] if finding["kind"] == kind.value]
    assert len(found) == 1, f"expected one {kind.value}, got {[item['message'] for item in found]}"
    return found[0]

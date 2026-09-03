"""The auditor's rules, one at a time, over hand-built manuscripts and graphs.

The end-to-end fixture in `tests/e2e/test_manuscript_audit.py` proves the six findings fire
together on a real project against a real PDF parse; this module pins each rule's edges.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    FindingSeverity,
    ManuscriptAnchorStatus,
    ManuscriptFindingKind,
    StaleState,
)
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    NumericValue,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import (
    ArtifactId,
    BlockId,
    ClaimId,
    EvidenceId,
    VersionId,
    WorkId,
)
from research_harness.domain.work import IdentifierField, Work, WorkIdentifiers
from research_harness.manuscript import LatexProject, Sentence, build_anchor, parse_bibtex
from research_harness.manuscript.audit import (
    MIN_SUBSTANTIVE_WORDS,
    AuditContext,
    ManuscriptAuditReport,
    audit_manuscript,
    is_substantive,
)

HUMAN = Provenance.human("human:alice")
WORK = WorkId("W0001")
OTHER = WorkId("W0002")
CLAIM = ClaimId("C0001")
HASH = f"sha256:{'a' * 64}"
TEXT_HASH = f"sha256:{'b' * 64}"

DOCUMENT = "\\documentclass{article}\n\\begin{document}\n\\section{Body}\n\nBODY\n\\end{document}\n"
BIB = "@article{cited, title={Deep Representations}, doi={10.1000/xyz123}, year={2023}}\n"


# ------------------------------------------------------------------------------ builders


#: A body sentence that is substantive (a claim verb, enough words) and scores L0.
SUBSTANTIVE = "The encoder improves detection of encrypted attacks under load."


def project(tmp_path: Path, body: str) -> LatexProject:
    tmp_path.mkdir(parents=True, exist_ok=True)
    main = tmp_path / "main.tex"
    main.write_text(DOCUMENT.replace("BODY", body), encoding="utf-8")
    return LatexProject.load(main)


def only_sentence(loaded: LatexProject) -> Sentence:
    assert len(loaded.sentences) == 1, [s.normalized_text for s in loaded.sentences]
    return loaded.sentences[0]


def corpus() -> dict[WorkId, Work]:
    return {
        WORK: Work(
            id=WORK,
            title="Deep Representations",
            year=2023,
            identifiers=WorkIdentifiers(
                doi=IdentifierField(value="10.1000/xyz123", source=HUMAN.source)
            ),
            provenance=HUMAN,
        ),
        OTHER: Work(id=OTHER, title="Something Else", year=2020, provenance=HUMAN),
    }


def source_anchor(work: WorkId = WORK, *, file_hash: str = HASH) -> SourceAnchor:
    return SourceAnchor(
        work=work,
        version=VersionId("V0001-1"),
        artifact=ArtifactId("A0001-1"),
        file_hash=file_hash,
        block=BlockId("B0001"),
        text_hash=TEXT_HASH,
        page=4,
    )


def evidence(
    evidence_id: str = "E0001",
    *,
    work: WorkId = WORK,
    stale: StaleState = StaleState.FRESH,
    numeric: NumericValue | None = None,
) -> Evidence:
    return Evidence(
        id=EvidenceId(evidence_id),
        source=source_anchor(work),
        content=EvidenceContent(exact_text="94.32", numeric=numeric),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
        strength=EvidenceStrength.DIRECT,
        verification=VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by="human:alice"),
        stale=stale,
        provenance=HUMAN,
    )


def claim(
    *,
    allowed: ClaimScope = ClaimScope.UNIVERSAL_OR_ABSENCE,
    status: ClaimStatus = ClaimStatus.SUPPORTED,
    stale: StaleState = StaleState.FRESH,
    supports: tuple[str, ...] = (),
    statement: str = "The encoder detects encrypted attacks",
) -> Claim:
    return Claim(
        id=CLAIM,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="encoder", predicate="detects", object="attacks"),
        scope=ClaimScopeSpec(level=allowed),
        relations=tuple(
            ClaimEvidenceRelation(
                evidence=EvidenceId(item), relation=ClaimEvidenceRelationType.SUPPORTS
            )
            for item in supports
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.UNIVERSAL_OR_ABSENCE,
            allowed_strength=allowed,
            status=status,
        ),
        stale=stale,
        provenance=HUMAN,
    )


def audit(
    tmp_path: Path,
    body: str,
    *,
    attach: bool = True,
    bib_text: str | None = BIB,
    **claim_kwargs: Any,
) -> ManuscriptAuditReport:
    """Audit a one-sentence manuscript, optionally attaching it to one claim."""
    loaded = project(tmp_path, body)
    subject = claim(**claim_kwargs)
    anchors = (build_anchor(only_sentence(loaded), CLAIM, HUMAN),) if attach else ()
    items = {EvidenceId(item): evidence(item) for item in claim_kwargs.get("supports", ())}
    return audit_manuscript(
        AuditContext(
            project=loaded,
            bib=None if bib_text is None else parse_bibtex(bib_text),
            anchors=anchors,
            claims={CLAIM: subject},
            evidence=items,
            works=corpus(),
        )
    )


def kinds(report: ManuscriptAuditReport) -> list[ManuscriptFindingKind]:
    return [finding.kind for finding in report.findings]


# -- what counts as substantive --------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "substantive"),
    [
        ("The encoder outperforms the tuned baseline on held-out flows.", True),
        ("The encoder improves recall on short encrypted flows.", True),
        ("We employ frozen bucket boundaries throughout every experiment.", True),
        ("Most detectors in this family degrade under offered load.", True),
        ("The offered load was swept to 94.32 of link capacity.", True),
        ("The setup follows the protocol of Section 3 \\citep{cited}.", True),
        ("The remainder of the paper is organized as follows.", False),
        ("We now turn to the evaluation.", False),
        ("Let x denote the batch size.", False),
    ],
)
def test_substantive_sentences_are_the_ones_that_assert_something(
    tmp_path: Path, body: str, substantive: bool
) -> None:
    assert is_substantive(only_sentence(project(tmp_path, body))) is substantive


def test_a_sentence_shorter_than_the_threshold_is_never_substantive(tmp_path: Path) -> None:
    short = "Most systems degrade badly."
    assert len(short.split()) < MIN_SUBSTANTIVE_WORDS
    assert not is_substantive(only_sentence(project(tmp_path, short)))


def test_abstract_prose_is_audited_but_float_contents_are_not(tmp_path: Path) -> None:
    body = (
        "\\begin{abstract}\nMost detectors degrade under sustained offered load.\n"
        "\\end{abstract}\n\n"
        "\\begin{table}\n\\caption{Most detectors degrade under sustained offered load.}\n"
        "\\end{table}\n"
    )
    report = audit(tmp_path, body, attach=False)
    assert kinds(report) == [ManuscriptFindingKind.UNREGISTERED_CLAIM]
    assert report.sentences_checked == 1


# -- the six findings ------------------------------------------------------------------


def test_an_unattached_substantive_sentence_is_unregistered(tmp_path: Path) -> None:
    report = audit(tmp_path, "The encoder outperforms every tuned baseline.", attach=False)
    assert kinds(report) == [ManuscriptFindingKind.UNREGISTERED_CLAIM]
    assert report.unanchored_substantive == 1
    assert report.anchored_sentences == 0
    assert report.findings[0].severity is FindingSeverity.WARNING
    assert report.findings[0].anchor is None


def test_an_anchor_naming_an_unknown_claim_is_an_error(tmp_path: Path) -> None:
    loaded = project(tmp_path, "The encoder outperforms the tuned baseline everywhere.")
    report = audit_manuscript(
        AuditContext(project=loaded, anchors=(build_anchor(only_sentence(loaded), CLAIM, HUMAN),))
    )
    assert kinds(report) == [ManuscriptFindingKind.UNREGISTERED_CLAIM]
    assert report.findings[0].severity is FindingSeverity.ERROR
    assert "not in the research graph" in report.findings[0].message


def test_wording_above_the_allowed_strength_is_flagged(tmp_path: Path) -> None:
    report = audit(
        tmp_path,
        "All existing detectors ignore offered load entirely.",
        allowed=ClaimScope.CORPUS_PATTERN,
    )
    assert kinds(report) == [ManuscriptFindingKind.OVER_STRONG_WORDING]
    assert "L4 universal_or_absence" in report.findings[0].message


def test_wording_at_or_below_the_allowed_strength_is_silent(tmp_path: Path) -> None:
    report = audit(
        tmp_path,
        "Most detectors in the corpus ignore offered load.",
        allowed=ClaimScope.FIELD_GENERALIZATION,
    )
    assert report.is_clean


def test_a_citation_key_missing_from_the_bibliography_is_an_error(tmp_path: Path) -> None:
    report = audit(tmp_path, f"{SUBSTANTIVE[:-1]} \\citep{{ghost}}.")
    assert kinds(report) == [ManuscriptFindingKind.CITATION_MISMATCH]
    assert "'ghost'" in report.findings[0].message
    assert report.findings[0].severity is FindingSeverity.ERROR


def test_a_missing_key_is_reported_once_not_twice(tmp_path: Path) -> None:
    """Closure and support both see the key; only closure reports it."""
    report = audit(tmp_path, f"{SUBSTANTIVE[:-1]} \\citep{{ghost}}.")
    assert len(report.of_kind(ManuscriptFindingKind.CITATION_MISMATCH)) == 1


def test_a_resolvable_citation_that_supports_nothing_is_a_mismatch(tmp_path: Path) -> None:
    report = audit(tmp_path, f"{SUBSTANTIVE[:-1]} \\citep{{cited}}.")
    finding = report.of_kind(ManuscriptFindingKind.CITATION_MISMATCH)[0]
    assert "citation existence is not evidence support" in finding.message
    assert WORK in finding.related


def test_a_number_with_no_evidence_is_a_warning(tmp_path: Path) -> None:
    report = audit(tmp_path, "The encoder reaches an F1 of 94.32 on the held-out split.")
    assert kinds(report) == [ManuscriptFindingKind.UNSUPPORTED_NUMERIC]
    assert report.findings[0].severity is FindingSeverity.WARNING


def test_a_number_whose_metric_moved_is_an_error(tmp_path: Path) -> None:
    """Product 12: metric, unit, dataset, and condition never change silently."""
    loaded = project(tmp_path, "The detector reaches 94.32 in production deployments.")
    measured = evidence(
        numeric=NumericValue(
            raw="94.32",
            parsed=94.32,
            unit=None,
            metric="F1",
            dataset="CICIDS2017",
            source_table="Table 1",
        )
    )
    report = audit_manuscript(
        AuditContext(
            project=loaded,
            anchors=(build_anchor(only_sentence(loaded), CLAIM, HUMAN),),
            claims={CLAIM: claim(supports=("E0001",), statement="The detector is accurate")},
            evidence={measured.id: measured},
        )
    )
    finding = report.of_kind(ManuscriptFindingKind.UNSUPPORTED_NUMERIC)[0]
    assert finding.severity is FindingSeverity.ERROR
    assert "may change silently" in finding.message
    assert "F1" in finding.message and "CICIDS2017" in finding.message


def test_a_stale_claim_is_reported(tmp_path: Path) -> None:
    report = audit(tmp_path, SUBSTANTIVE, stale=StaleState.STALE)
    assert kinds(report) == [ManuscriptFindingKind.STALE_CLAIM]
    assert "marked stale" in report.findings[0].message


@pytest.mark.parametrize(
    "status", [ClaimStatus.SUPERSEDED, ClaimStatus.UNSUPPORTED, ClaimStatus.CONTESTED]
)
def test_a_claim_in_a_questionable_status_is_reported(tmp_path: Path, status: ClaimStatus) -> None:
    report = audit(tmp_path, SUBSTANTIVE, status=status)
    assert kinds(report) == [ManuscriptFindingKind.STALE_CLAIM]
    assert status.value in report.findings[0].message


def test_stale_supporting_evidence_invalidates_the_provenance(tmp_path: Path) -> None:
    loaded = project(tmp_path, SUBSTANTIVE)
    item = evidence(stale=StaleState.STALE)
    report = audit_manuscript(
        AuditContext(
            project=loaded,
            anchors=(build_anchor(only_sentence(loaded), CLAIM, HUMAN),),
            claims={CLAIM: claim(supports=("E0001",))},
            evidence={item.id: item},
        )
    )
    assert kinds(report) == [ManuscriptFindingKind.INVALID_EVIDENCE_ANCHOR]
    assert report.findings[0].severity is FindingSeverity.ERROR
    assert "marked stale" in report.findings[0].message


def test_an_unloaded_artifact_parse_is_not_a_broken_anchor(tmp_path: Path) -> None:
    """ "This parse was not loaded" is not "this provenance is broken"."""
    report = audit(tmp_path, SUBSTANTIVE, supports=("E0001",))
    assert report.of_kind(ManuscriptFindingKind.INVALID_EVIDENCE_ANCHOR) == ()


# -- revalidation ----------------------------------------------------------------------


def test_a_reworded_sentence_leaves_a_stale_anchor_behind(tmp_path: Path) -> None:
    original = project(tmp_path / "before", SUBSTANTIVE)
    anchor = build_anchor(only_sentence(original), CLAIM, HUMAN)
    reworded = project(
        tmp_path / "after", "The encoder improves detection of most encrypted attacks."
    )
    report = audit_manuscript(
        AuditContext(project=reworded, anchors=(anchor,), claims={CLAIM: claim()})
    )
    assert [result.status for result in report.revalidations] == [ManuscriptAnchorStatus.STALE]
    stale = report.of_kind(ManuscriptFindingKind.STALE_CLAIM)
    assert len(stale) == 1
    assert "is stale" in stale[0].message
    assert report.of_kind(ManuscriptFindingKind.UNREGISTERED_CLAIM), "the new sentence is orphaned"


def test_a_moved_sentence_keeps_its_anchor(tmp_path: Path) -> None:
    body = SUBSTANTIVE
    original = project(tmp_path / "before", body)
    anchor = build_anchor(only_sentence(original), CLAIM, HUMAN)
    moved = project(tmp_path / "after", f"A new opening paragraph goes here first.\n\n{body}")
    report = audit_manuscript(
        AuditContext(project=moved, anchors=(anchor,), claims={CLAIM: claim()})
    )
    assert [result.status for result in report.revalidations] == [ManuscriptAnchorStatus.VALID]
    assert report.of_kind(ManuscriptFindingKind.STALE_CLAIM) == ()


# -- the trace and the report ----------------------------------------------------------


def test_an_anchored_claim_yields_a_trace_link_even_without_a_parse(tmp_path: Path) -> None:
    report = audit(tmp_path, SUBSTANTIVE, supports=("E0001",))
    assert len(report.trace) == 1
    link = report.trace[0]
    assert link.claim == CLAIM
    assert link.evidence == (EvidenceId("E0001"),)
    assert link.spans == ()
    assert report.trace_for(link.anchor_key) is link
    assert report.trace_for("main.tex#nothing") is None


def test_an_audit_without_a_bibliography_checks_no_citations(tmp_path: Path) -> None:
    report = audit(tmp_path, f"{SUBSTANTIVE[:-1]} \\citep{{ghost}}.", bib_text=None)
    assert report.of_kind(ManuscriptFindingKind.CITATION_MISMATCH) == ()


def test_a_clean_manuscript_produces_nothing(tmp_path: Path) -> None:
    report = audit(tmp_path, SUBSTANTIVE)
    assert report.is_clean
    assert report.errors == ()
    assert report.sentences_checked == 1
    assert report.anchored_sentences == 1

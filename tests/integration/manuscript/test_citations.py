"""Citation closure over the fixture manuscript: keys must exist, and existence is not support."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.domain.enums import FindingSeverity, ManuscriptFindingKind
from research_harness.manuscript import (
    BibDatabase,
    CitationClosureReport,
    LatexProject,
    citation_closure,
    findings_for_missing,
    parse_bibtex,
    parse_bibtex_file,
)
from research_harness.manuscript import citations as citations_module

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "manuscript"

DOCUMENT = "\\documentclass{article}\n\\begin{document}\nBODY\n\\end{document}\n"


@pytest.fixture(scope="module")
def project() -> LatexProject:
    return LatexProject.load(FIXTURE / "main.tex")


@pytest.fixture(scope="module")
def bib() -> BibDatabase:
    return parse_bibtex_file(FIXTURE / "references.bib")


@pytest.fixture(scope="module")
def report(project: LatexProject, bib: BibDatabase) -> CitationClosureReport:
    return citation_closure(project, bib)


def build(tmp_path: Path, body: str) -> LatexProject:
    main = tmp_path / "main.tex"
    main.write_text(DOCUMENT.replace("BODY", body), encoding="utf-8")
    return LatexProject.load(main)


def test_closure_lists_every_key_the_manuscript_cites(report: CitationClosureReport) -> None:
    assert report.cited_keys == (
        "kraus2019",
        "ostrom2020",
        "voss2021",
        "nguyen2022",
        "hart2018",
    )


def test_a_cited_key_absent_from_the_bibliography_is_reported_with_its_sentence(
    report: CitationClosureReport,
) -> None:
    assert report.missing_key_names == ("voss2021",)
    assert not report.is_closed
    missing = report.missing_keys[0]
    assert missing.key == "voss2021"
    assert missing.sentence.file == "sections/intro.tex"
    assert missing.sentence.line_start == 12
    assert missing.sentence.normalized_text == (
        "A follow-up study reports a 12.8% degradation at saturation."
    )


def test_entries_that_nothing_cites_are_listed(report: CitationClosureReport) -> None:
    assert report.unused_entries == ("ivanov2023",)


def test_every_resolvable_key_is_absent_from_the_missing_list(
    report: CitationClosureReport, bib: BibDatabase
) -> None:
    resolved = set(report.cited_keys) - set(report.missing_key_names)
    assert resolved == {"kraus2019", "ostrom2020", "nguyen2022", "hart2018"}
    assert all(key in bib for key in resolved)


def test_missing_keys_become_error_severity_citation_findings(
    report: CitationClosureReport,
) -> None:
    findings = findings_for_missing(report)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind is ManuscriptFindingKind.CITATION_MISMATCH
    assert finding.severity is FindingSeverity.ERROR
    assert "voss2021" in finding.message
    assert "sections/intro.tex:12" in finding.message
    assert finding.anchor is None


def test_each_citing_sentence_of_a_missing_key_is_reported_separately(
    tmp_path: Path, bib: BibDatabase
) -> None:
    project = build(
        tmp_path,
        "First mention \\citep{voss2021}.\n\nSecond mention \\citet{voss2021} again.\n",
    )
    report = citation_closure(project, bib)
    assert [(m.key, m.sentence.line_start) for m in report.missing_keys] == [
        ("voss2021", 3),
        ("voss2021", 5),
    ]
    assert report.missing_key_names == ("voss2021",)
    assert len(findings_for_missing(report)) == 2


def test_a_closed_manuscript_produces_no_findings(tmp_path: Path, bib: BibDatabase) -> None:
    report = citation_closure(build(tmp_path, "Well cited \\citep{kraus2019}.\n"), bib)
    assert report.is_closed
    assert report.missing_keys == ()
    assert findings_for_missing(report) == []


def test_an_empty_bibliography_makes_every_cited_key_missing(tmp_path: Path) -> None:
    report = citation_closure(build(tmp_path, "Cited \\citep{a,b}.\n"), parse_bibtex(""))
    assert report.missing_key_names == ("a", "b")
    assert report.unused_entries == ()


def test_closure_never_claims_that_a_resolved_citation_supports_a_claim() -> None:
    # Product 30.2: support verification is a separate step over accepted Claim-Evidence
    # relations; closure only proves the key exists. Keep that written down where the
    # next task will read it.
    module_doc = citations_module.__doc__ or ""
    closure_doc = citations_module.citation_closure.__doc__ or ""
    assert "Citation existence is not evidence support" in module_doc
    assert "Claim-Evidence" in module_doc
    assert "says only that the entry exists" in closure_doc
    assert not hasattr(citations_module, "verify_support")

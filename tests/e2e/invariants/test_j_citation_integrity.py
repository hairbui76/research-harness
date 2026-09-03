"""Product §42.J - Citation integrity.

"A manuscript citation that exists but does not support the attached Claim is flagged."

Three keys, three outcomes, one audit of the manuscript the loop wrote:

* `traffic2024` resolves to the corpus Work whose Evidence the Claim leans on - clean;
* `split2020` resolves to a real bibliography entry and supports nothing the attached
  Claim records - the §42.J case, an error;
* `phantom2099` is cited and never defined - an unresolved key, also an error.

The distinction that matters is the middle one: existence is not support (Product §30.2).
"""

from __future__ import annotations

import pytest

from research_harness.domain.enums import FindingSeverity, ManuscriptFindingKind
from research_harness.domain.manuscript import ManuscriptAuditFinding
from research_harness.manuscript.attach import ManuscriptService
from research_harness.manuscript.audit import ManuscriptAuditReport
from research_harness.manuscript.citations import citation_closure
from research_harness.manuscript.support import citation_support, match_bib_to_works
from tests.e2e.invariants.workstation import (
    GHOST_KEY,
    GHOST_LINE,
    MISMATCH_LINE,
    OTHER_WORK,
    SUPPORTED_LINE,
    SUPPORTING_KEY,
    UNSUPPORTED_KEY,
    Workstation,
)


@pytest.fixture(scope="module")
def audit(workstation: Workstation) -> ManuscriptAuditReport:
    """The manuscript audited against the accepted graph the loop built."""
    return ManuscriptService(workstation.context()).audit()


def at(line: int) -> str:
    """How a finding names a location: `main.tex:<line>`, inside its own message."""
    return f"main.tex:{line}"


def findings_on(report: ManuscriptAuditReport, line: int) -> list[ManuscriptAuditFinding]:
    """Every finding the audit raised about one manuscript line."""
    return [finding for finding in report.findings if at(line) in finding.message]


def citation_mismatches_on(
    report: ManuscriptAuditReport, line: int
) -> list[ManuscriptAuditFinding]:
    return [
        finding
        for finding in report.of_kind(ManuscriptFindingKind.CITATION_MISMATCH)
        if at(line) in finding.message
    ]


# ------------------------------------------------------------------- the supporting key


def test_a_key_whose_work_carries_the_claims_evidence_is_not_flagged(
    audit: ManuscriptAuditReport,
) -> None:
    """The clean case exists so the other two mean something."""
    assert findings_on(audit, SUPPORTED_LINE) == []


def test_the_supporting_key_resolves_to_the_corpus_work(workstation: Workstation) -> None:
    """Support is a graph fact: the key names a Work, the Work carries the Evidence."""
    service = ManuscriptService(workstation.context())
    bib = service.bibliography()
    assert bib is not None

    works = {work.id: work for work in workstation.context().repo.list_works()}
    mapping = match_bib_to_works(bib, works)

    assert mapping.work_for(SUPPORTING_KEY) == workstation.work
    assert mapping.is_known_entry(SUPPORTING_KEY)
    assert mapping.work_for(UNSUPPORTED_KEY) == OTHER_WORK


# --------------------------------------------------------------------- the mismatch


def test_a_resolvable_key_that_supports_nothing_is_flagged(
    audit: ManuscriptAuditReport,
) -> None:
    """Product §42.J: the key exists, it resolves, and it still supports no Claim here."""
    mismatches = citation_mismatches_on(audit, MISMATCH_LINE)

    assert len(mismatches) == 1
    assert f"'{UNSUPPORTED_KEY}'" in mismatches[0].message
    assert mismatches[0].severity is FindingSeverity.ERROR


def test_the_mismatch_says_why_existence_is_not_support(
    audit: ManuscriptAuditReport,
) -> None:
    """A message a researcher can act on names the rule it applied."""
    (mismatch,) = citation_mismatches_on(audit, MISMATCH_LINE)

    assert "citation existence is not evidence support" in mismatch.message


def test_the_support_check_reports_the_mismatch_directly(workstation: Workstation) -> None:
    """The same verdict from the checker itself, without the auditor in between."""
    ctx = workstation.context()
    service = ManuscriptService(ctx)
    bib = service.bibliography()
    assert bib is not None
    works = {work.id: work for work in ctx.repo.list_works()}
    evidence = {
        record.id: record
        for work in ctx.repo.list_works()
        for record in ctx.repo.iter_evidence(work.id)
    }
    anchor = next(item for item in ctx.repo.iter_anchors() if item.line_start == MISMATCH_LINE)
    claim = ctx.repo.get_claim(anchor.claim)

    report = citation_support(anchor, claim, evidence, match_bib_to_works(bib, works))

    assert report.is_supported is False
    assert [check.key for check in report.mismatches] == [UNSUPPORTED_KEY]


# ------------------------------------------------------------------ the missing key


def test_a_citation_key_the_bibliography_never_defines_is_flagged(
    audit: ManuscriptAuditReport,
) -> None:
    missing = citation_mismatches_on(audit, GHOST_LINE)

    assert len(missing) == 1
    assert f"{GHOST_KEY!r} is not defined in the bibliography" in missing[0].message
    assert missing[0].severity is FindingSeverity.ERROR


def test_citation_closure_names_the_unresolved_key(workstation: Workstation) -> None:
    service = ManuscriptService(workstation.context())
    bib = service.bibliography()
    assert bib is not None

    closure = citation_closure(service.load_project(), bib)

    assert closure.is_closed is False
    assert closure.missing_key_names == (GHOST_KEY,)


# ------------------------------------------------------------------------ altogether


def test_the_audit_flags_exactly_the_two_bad_citations(
    audit: ManuscriptAuditReport,
) -> None:
    """No false positive on the good key, and no silence on either bad one."""
    flagged = audit.of_kind(ManuscriptFindingKind.CITATION_MISMATCH)

    assert len(citation_mismatches_on(audit, MISMATCH_LINE)) == 1
    assert len(citation_mismatches_on(audit, GHOST_LINE)) == 1
    assert len(citation_mismatches_on(audit, SUPPORTED_LINE)) == 0
    assert len(flagged) == 2


def test_the_audit_writes_nothing(workstation: Workstation) -> None:
    """Auditing reports; it never repairs a citation or invents one (Product §30.2)."""
    from tests.e2e.invariants.workstation import canonical_bytes_digest

    before = canonical_bytes_digest(workstation.root)
    ManuscriptService(workstation.context()).audit()

    assert canonical_bytes_digest(workstation.root) == before


def test_a_flagged_citation_never_becomes_a_fabricated_one(
    audit: ManuscriptAuditReport, workstation: Workstation
) -> None:
    """`NEEDS SOURCE` beats a plausible key: the manuscript still cites the ghost."""
    text = (workstation.manuscript_dir / "main.tex").read_text(encoding="utf-8")

    assert f"\\citep{{{GHOST_KEY}}}" in text
    assert GHOST_KEY not in (workstation.manuscript_dir / "references.bib").read_text("utf-8")
    assert audit.is_clean is False

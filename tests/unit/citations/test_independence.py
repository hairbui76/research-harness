"""Independent-support accounting: what counts once, what counts separately, and why."""

from __future__ import annotations

from research_harness.citations.graph import CitationEdge, CitationGraph
from research_harness.citations.independence import (
    double_counting_risks,
    independent_support,
)
from research_harness.domain.claim import Claim, ClaimEvidenceRelation
from research_harness.domain.enums import ClaimEvidenceRelationType, EvidenceStatus
from research_harness.domain.evidence import Evidence, VerificationRecord
from research_harness.domain.ids import ArtifactId, EvidenceId, VersionId, WorkId
from research_harness.domain.work import Work
from tests.unit.domain import strategies as sty

ACCEPTED = VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by="human")


def evidence(number: int, work: str, *, version: str, accepted: bool = True) -> Evidence:
    """One accepted evidence object anchored in a named Work/Version/Artifact."""
    suffix = version.rsplit("-", 1)[1]
    return sty.make_evidence(
        id=EvidenceId(f"E{number:04d}"),
        source=sty.make_anchor(
            work=WorkId(work),
            version=VersionId(version),
            artifact=ArtifactId(f"A{work[1:]}-{suffix}"),
        ),
        verification=ACCEPTED if accepted else VerificationRecord(),
    )


def work(work_id: str, *authors: str) -> Work:
    return sty.make_work(id=WorkId(work_id), title=f"Paper {work_id}", authors=authors)


def claim_supported_by(*items: Evidence) -> Claim:
    return sty.make_claim(
        relations=tuple(
            ClaimEvidenceRelation(evidence=item.id, relation=ClaimEvidenceRelationType.SUPPORTS)
            for item in items
        )
    )


def by_id(*items: Evidence) -> dict[EvidenceId, Evidence]:
    return {item.id: item for item in items}


def corpus(*works: Work) -> dict[WorkId, Work]:
    return {item.id: item for item in works}


def cites(citing: str, cited: str) -> CitationGraph:
    graph = CitationGraph()
    graph.add_edge(CitationEdge(citing=citing, cited=cited, source="fake_source"))
    return graph


# -- same work ---------------------------------------------------------------


def test_two_versions_of_one_work_support_a_claim_once() -> None:
    """ADR-002: a revision is not a second paper, so it is not a second source."""
    first = evidence(1, "W0001", version="V0001-1")
    second = evidence(2, "W0001", version="V0001-2")

    report = independent_support(
        claim_supported_by(first, second),
        by_id(first, second),
        corpus(work("W0001", "Jane Doe")),
        CitationGraph(),
    )

    assert report.effective_support == 1
    assert report.independent_works == ()
    assert [group.kind for group in report.dependent_groups] == ["same_work"]
    assert report.dependent_groups[0].members == ("V0001-1", "V0001-2")
    assert any("same_work" in warning for warning in report.warnings)


def test_two_node_keys_resolved_to_one_work_support_it_once() -> None:
    first = evidence(1, "W0001", version="V0001-1")
    second = evidence(2, "W0002", version="V0002-1")

    report = independent_support(
        claim_supported_by(first, second),
        by_id(first, second),
        corpus(work("W0001", "Jane Doe"), work("W0002", "Jane Doe")),
        CitationGraph(),
        same_work={"W0002": "W0001"},
    )

    assert report.effective_support == 1
    assert report.dependent_groups[0].kind == "same_work"
    assert report.dependent_groups[0].members == ("W0001", "W0002")


# -- shared authors ----------------------------------------------------------


def test_works_sharing_most_of_their_authors_count_once() -> None:
    first = evidence(1, "W0001", version="V0001-1")
    second = evidence(2, "W0002", version="V0002-1")

    report = independent_support(
        claim_supported_by(first, second),
        by_id(first, second),
        corpus(work("W0001", "Jane Doe", "John Roe"), work("W0002", "Jane Doe", "Ann Poe")),
        CitationGraph(),
    )

    assert report.effective_support == 1
    assert report.dependent_groups[0].kind == "same_authors"
    assert report.dependent_groups[0].members == ("W0001", "W0002")


def test_one_shared_author_out_of_many_is_not_enough_to_group() -> None:
    first = evidence(1, "W0001", version="V0001-1")
    second = evidence(2, "W0002", version="V0002-1")

    report = independent_support(
        claim_supported_by(first, second),
        by_id(first, second),
        corpus(
            work("W0001", "Jane Doe", "John Roe", "Kim Lee", "Sam Ray"),
            work("W0002", "Jane Doe", "Ann Poe", "Bo Qin", "Cy Tan"),
        ),
        CitationGraph(),
    )

    assert report.effective_support == 2
    assert report.dependent_groups == ()


# -- citation chains ---------------------------------------------------------


def test_citing_a_supporting_work_while_sharing_an_author_is_derivative_support() -> None:
    first = evidence(1, "W0001", version="V0001-1")
    second = evidence(2, "W0002", version="V0002-1")

    report = independent_support(
        claim_supported_by(first, second),
        by_id(first, second),
        corpus(
            work("W0001", "Jane Doe", "John Roe", "Kim Lee", "Sam Ray"),
            work("W0002", "Jane Doe", "Ann Poe", "Bo Qin", "Cy Tan"),
        ),
        cites("W0002", "W0001"),
    )

    assert report.effective_support == 1
    assert report.dependent_groups[0].kind == "citation_chain"
    assert report.dependent_groups[0].members == ("W0001", "W0002")
    assert "derivative" in report.dependent_groups[0].note


def test_citing_a_supporting_work_by_other_authors_stays_independent() -> None:
    """A citation alone is not dependence: unrelated groups build on each other."""
    first = evidence(1, "W0001", version="V0001-1")
    second = evidence(2, "W0002", version="V0002-1")

    report = independent_support(
        claim_supported_by(first, second),
        by_id(first, second),
        corpus(work("W0001", "Jane Doe"), work("W0002", "Ann Poe")),
        cites("W0002", "W0001"),
    )

    assert report.effective_support == 2
    assert report.dependent_groups == ()


# -- counting ----------------------------------------------------------------


def test_unrelated_works_each_count_as_their_own_support() -> None:
    items = (
        evidence(1, "W0001", version="V0001-1"),
        evidence(2, "W0002", version="V0002-1"),
        evidence(3, "W0003", version="V0003-1"),
    )

    report = independent_support(
        claim_supported_by(*items),
        by_id(*items),
        corpus(work("W0001", "Jane Doe"), work("W0002", "Ann Poe"), work("W0003", "Bo Qin")),
        CitationGraph(),
    )

    assert report.independent_works == ("W0001", "W0002", "W0003")
    assert report.effective_support == 3


def test_effective_support_is_the_number_of_groups() -> None:
    items = (
        evidence(1, "W0001", version="V0001-1"),
        evidence(2, "W0001", version="V0001-2"),
        evidence(3, "W0002", version="V0002-1"),
        evidence(4, "W0003", version="V0003-1"),
        evidence(5, "W0004", version="V0004-1"),
    )

    report = independent_support(
        claim_supported_by(*items),
        by_id(*items),
        corpus(
            work("W0001", "Jane Doe"),
            work("W0002", "Ann Poe", "Bo Qin"),
            work("W0003", "Ann Poe", "Cy Tan"),
            work("W0004", "Di Vos"),
        ),
        CitationGraph(),
    )

    assert report.effective_support == len(report.independent_works) + len(report.dependent_groups)
    assert report.effective_support == 3
    assert report.independent_works == ("W0004",)
    assert sorted(group.kind for group in report.dependent_groups) == [
        "same_authors",
        "same_work",
    ]


def test_a_claim_with_no_supporting_evidence_has_no_support() -> None:
    report = independent_support(sty.make_claim(relations=()), {}, {}, CitationGraph())
    assert report.effective_support == 0
    assert report.independent_works == ()


# -- honesty about what could not be checked ---------------------------------


def test_unsupplied_evidence_is_warned_about_rather_than_counted() -> None:
    present = evidence(1, "W0001", version="V0001-1")
    claim = sty.make_claim(
        relations=(
            ClaimEvidenceRelation(evidence=present.id, relation=ClaimEvidenceRelationType.SUPPORTS),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0999"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
        )
    )

    report = independent_support(
        claim, by_id(present), corpus(work("W0001", "Jane Doe")), CitationGraph()
    )

    assert report.effective_support == 1
    assert any("E0999" in warning and "uncounted" in warning for warning in report.warnings)


def test_unaccepted_evidence_counts_but_is_named() -> None:
    proposed = evidence(1, "W0001", version="V0001-1", accepted=False)

    report = independent_support(
        claim_supported_by(proposed),
        by_id(proposed),
        corpus(work("W0001", "Jane Doe")),
        CitationGraph(),
    )

    assert report.effective_support == 1
    assert any("not accepted" in warning for warning in report.warnings)


def test_a_work_with_no_known_authors_is_flagged_as_uncheckable() -> None:
    item = evidence(1, "W0001", version="V0001-1")

    report = independent_support(claim_supported_by(item), by_id(item), {}, CitationGraph())

    assert report.effective_support == 1
    assert any("author-independence" in warning for warning in report.warnings)


# -- double counting risks ---------------------------------------------------


def test_double_counting_risks_report_what_a_merge_collapsed() -> None:
    graph = CitationGraph()
    graph.add_edge(CitationEdge(citing="doi:10.1/a", cited="W0002", source="fake_source"))
    merged = graph.merge_nodes({"doi:10.1/a": "W0001"})

    risks = double_counting_risks(merged, ("W0001", "W0002"))

    assert [risk.members for risk in risks] == [("W0001", "doi:10.1/a")]
    assert risks[0].kind == "same_work"
    assert "doi:10.1/a" in risks[0].note


def test_an_unmerged_graph_reports_no_double_counting_risk() -> None:
    assert double_counting_risks(CitationGraph(), ("W0001",)) == ()

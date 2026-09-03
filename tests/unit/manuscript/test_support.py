"""Citation support and numeric compatibility: Product 12, 30.2, and 42.J as unit rules."""

from __future__ import annotations

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
    ClaimType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
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
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.work import IdentifierField, Work, WorkIdentifiers
from research_harness.manuscript.bibtex import parse_bibtex
from research_harness.manuscript.support import (
    BibWorkMap,
    NumberMention,
    citation_support,
    match_bib_to_works,
    numbers_in_sentence,
    numeric_support,
)

HUMAN = Provenance.human("human:alice")
CLAIM = ClaimId("C0001")
HASH = f"sha256:{'a' * 64}"
TEXT_HASH = f"sha256:{'b' * 64}"


# ------------------------------------------------------------------------------ builders


def work(
    work_id: str,
    title: str,
    *,
    year: int | None = None,
    doi: str | None = None,
    arxiv: str | None = None,
    authors: tuple[str, ...] = (),
) -> Work:
    identifiers = WorkIdentifiers(
        doi=None
        if doi is None
        else IdentifierField(value=doi, source=ProvenanceSource.EXTERNAL_METADATA),
        arxiv=None
        if arxiv is None
        else IdentifierField(value=arxiv, source=ProvenanceSource.EXTERNAL_METADATA),
    )
    return Work(
        id=WorkId(work_id),
        title=title,
        year=year,
        authors=authors,
        identifiers=identifiers,
        provenance=HUMAN,
    )


def works(*items: Work) -> dict[WorkId, Work]:
    return {item.id: item for item in items}


def anchor_for(work_id: str) -> SourceAnchor:
    number = work_id[1:]
    return SourceAnchor(
        work=WorkId(work_id),
        version=VersionId(f"V{number}-1"),
        artifact=ArtifactId(f"A{number}-1"),
        file_hash=HASH,
        block=BlockId("B0001"),
        text_hash=TEXT_HASH,
        page=4,
    )


def evidence(
    evidence_id: str,
    work_id: str = "W0001",
    *,
    status: EvidenceStatus = EvidenceStatus.ACCEPTED,
    stale: StaleState = StaleState.FRESH,
    origin: EvidenceOrigin = EvidenceOrigin.SOURCE_OBSERVED,
    strength: EvidenceStrength = EvidenceStrength.DIRECT,
    numeric: NumericValue | None = None,
) -> Evidence:
    return Evidence(
        id=EvidenceId(evidence_id),
        source=anchor_for(work_id),
        content=EvidenceContent(exact_text="94.32", numeric=numeric),
        origin=origin,
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
        strength=strength,
        verification=VerificationRecord(
            status=status,
            accepted_by="human:alice" if status is EvidenceStatus.ACCEPTED else None,
        ),
        stale=stale,
        provenance=HUMAN,
    )


def numeric_value(
    *,
    parsed: float = 94.32,
    raw: str = "94.32",
    unit: str | None = None,
    metric: str = "F1",
    dataset: str | None = "CICIDS2017",
) -> NumericValue:
    return NumericValue(
        raw=raw,
        parsed=parsed,
        unit=unit,
        metric=metric,
        dataset=dataset,
        source_table="Table 1",
        source_row="TrafficLM",
        source_column=metric,
    )


def claim(
    *relations: tuple[str, ClaimEvidenceRelationType],
    statement: str = "TrafficLM detects encrypted attacks",
) -> Claim:
    return Claim(
        id=CLAIM,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="TrafficLM", predicate="detects", object="attacks"),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL),
        relations=tuple(
            ClaimEvidenceRelation(evidence=EvidenceId(item), relation=relation)
            for item, relation in relations
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.INDIVIDUAL,
            allowed_strength=ClaimScope.INDIVIDUAL,
        ),
        provenance=HUMAN,
    )


def anchor(*keys: str) -> ManuscriptAnchor:
    return ManuscriptAnchor(
        file="main.tex",
        line_start=1,
        line_end=1,
        sentence="TrafficLM detects encrypted attacks.",
        sentence_fingerprint=TEXT_HASH,
        claim=CLAIM,
        citation_keys=keys,
        provenance=HUMAN,
    )


def mention(text: str, value: float, unit: str | None, context: str) -> NumberMention:
    return NumberMention(
        text=text,
        value=value,
        unit=unit,
        char_start=0,
        char_end=len(text),
        context=context,
    )


# -- bibliography -> corpus ------------------------------------------------------------


def test_a_doi_resolves_a_key_even_when_the_title_disagrees() -> None:
    bib = parse_bibtex(
        "@article{a2023, title={Wildly Different Title}, doi={https://DOI.org/10.1000/XYZ123}, "
        "year={2023}}"
    )
    corpus = works(work("W0001", "Deep Representations", doi="10.1000/xyz123"))
    assert match_bib_to_works(bib, corpus).by_key == {"a2023": WorkId("W0001")}


def test_an_arxiv_eprint_matches_across_revisions() -> None:
    bib = parse_bibtex(
        "@misc{a2024, title={Anything}, archivePrefix={arXiv}, eprint={2401.12345v3}}"
    )
    corpus = works(work("W0002", "Deep Representations", arxiv="arXiv:2401.12345"))
    assert match_bib_to_works(bib, corpus).by_key == {"a2024": WorkId("W0002")}


def test_a_title_and_year_resolve_a_key_with_no_identifiers() -> None:
    bib = parse_bibtex(
        "@inproceedings{o2020, title={A Corrected {Split} for Structured Traffic Corpora}, "
        "year={2020}}"
    )
    corpus = works(work("W0003", "A Corrected Split for Structured Traffic Corpora", year=2020))
    assert match_bib_to_works(bib, corpus).by_key == {"o2020": WorkId("W0003")}


def test_a_pdf_derived_year_two_off_does_not_defeat_a_title_the_authors_corroborate() -> None:
    """Dogfood F4: NetGPT is W0002; its ingested year came from an arXiv v3 banner.

    The bibliography correctly says 2023 and the corpus recorded 2025, and the strict
    ``work.year == year`` filter threw the exact title match away, which is what produced
    three false `citation_mismatch` ERRORs against `meng2023netgpt`.
    """
    bib = parse_bibtex(
        "@article{meng2023netgpt, "
        "title={NetGPT: Generative Pretrained Transformer for Network Traffic}, "
        "author={Xuying Meng and Chungang Lin and Yequan Wang and Yujun Zhang}, "
        "journal={arXiv preprint arXiv:2304.09513}, year={2023}}"
    )
    corpus = works(
        work(
            "W0002",
            "NetGPT: Generative Pretrained Transformer for Network Traffic",
            year=2025,
            authors=("Xuying Meng", "Chungang Lin", "Yequan Wang", "Yujun Zhang"),
        )
    )

    assert match_bib_to_works(bib, corpus).by_key == {"meng2023netgpt": WorkId("W0002")}


def test_an_arxiv_identifier_still_outranks_a_year_disagreement() -> None:
    """An identifier match is never reached by the year rule at all (dogfood F4)."""
    bib = parse_bibtex(
        "@article{meng2023netgpt, title={Something Else Entirely}, "
        "journal={arXiv preprint arXiv:2304.09513}, year={2023}}"
    )
    corpus = works(work("W0002", "NetGPT", year=2025, arxiv="arXiv:2304.09513v3"))

    assert match_bib_to_works(bib, corpus).by_key == {"meng2023netgpt": WorkId("W0002")}


def test_a_year_two_off_without_corroborating_authors_still_does_not_resolve() -> None:
    """The wider tolerance is bought by the author lists agreeing, not given away."""
    bib = parse_bibtex(
        "@inproceedings{o2020, title={A Corrected Split}, author={Someone Else}, year={2018}}"
    )
    corpus = works(work("W0003", "A Corrected Split", year=2020, authors=("Jane Roe",)))

    assert match_bib_to_works(bib, corpus).unmatched_keys == ("o2020",)


def test_a_matching_title_with_the_wrong_year_does_not_resolve() -> None:
    bib = parse_bibtex("@inproceedings{o2020, title={A Corrected Split}, year={2015}}")
    corpus = works(work("W0003", "A Corrected Split", year=2020))
    result = match_bib_to_works(bib, corpus)
    assert result.by_key == {}
    assert result.unmatched_keys == ("o2020",)


def test_identifiers_outrank_titles() -> None:
    bib = parse_bibtex("@article{a, title={Shared Title}, doi={10.1/one}, year={2020}}")
    corpus = works(
        work("W0001", "Shared Title", year=2020, doi="10.1/one"),
        work("W0002", "Something Else", year=2020, doi="10.1/two"),
    )
    assert match_bib_to_works(bib, corpus).by_key == {"a": WorkId("W0001")}


def test_a_title_matching_two_works_is_ambiguous_and_never_guessed() -> None:
    bib = parse_bibtex("@article{a, title={Shared Title}, year={2020}}")
    corpus = works(work("W0001", "Shared Title", year=2020), work("W0002", "Shared Title"))
    result = match_bib_to_works(bib, corpus)
    assert result.by_key == {}
    assert result.ambiguous == {"a": (WorkId("W0001"), WorkId("W0002"))}
    assert result.work_for("a") is None
    assert result.is_known_entry("a")


def test_an_entry_naming_no_corpus_work_is_unmatched() -> None:
    bib = parse_bibtex("@misc{ghost, title={Nobody Has This}, year={2024}}")
    result = match_bib_to_works(bib, works(work("W0001", "Something Else")))
    assert result.unmatched_keys == ("ghost",)
    assert result.is_known_entry("ghost")
    assert not result.is_known_entry("absent")


# -- citation support ------------------------------------------------------------------


BIBMAP = BibWorkMap(
    by_key={"cited": WorkId("W0001"), "other": WorkId("W0002")},
    unmatched_keys=("unregistered",),
)


def test_an_accepted_supporting_relation_from_the_cited_work_is_support() -> None:
    items = {EvidenceId("E0001"): evidence("E0001")}
    report = citation_support(
        anchor("cited"), claim(("E0001", ClaimEvidenceRelationType.SUPPORTS)), items, BIBMAP
    )
    assert [check.status for check in report.per_key] == ["supports"]
    assert report.per_key[0].evidence_ids == (EvidenceId("E0001"),)
    assert report.is_supported


def test_an_exemplifies_relation_also_counts_as_support() -> None:
    items = {EvidenceId("E0001"): evidence("E0001")}
    report = citation_support(
        anchor("cited"), claim(("E0001", ClaimEvidenceRelationType.EXEMPLIFIES)), items, BIBMAP
    )
    assert report.per_key[0].status == "supports"


def test_a_resolvable_key_whose_work_backs_nothing_is_a_mismatch() -> None:
    """Product 42.J: the citation exists, resolves, and still supports nothing."""
    items = {EvidenceId("E0001"): evidence("E0001", "W0001")}
    report = citation_support(
        anchor("other"), claim(("E0001", ClaimEvidenceRelationType.SUPPORTS)), items, BIBMAP
    )
    check = report.per_key[0]
    assert check.status == "no_relation"
    assert check.work == WorkId("W0002")
    assert check.is_mismatch
    assert report.mismatches == (check,)


def test_a_work_that_only_contradicts_is_its_own_kind_of_mismatch() -> None:
    items = {EvidenceId("E0001"): evidence("E0001")}
    report = citation_support(
        anchor("cited"), claim(("E0001", ClaimEvidenceRelationType.CONTRADICTS)), items, BIBMAP
    )
    check = report.per_key[0]
    assert check.status == "contradicts"
    assert check.is_mismatch
    assert check.evidence_ids == (EvidenceId("E0001"),)


def test_a_qualifying_citation_is_reported_and_is_not_a_mismatch() -> None:
    items = {EvidenceId("E0001"): evidence("E0001")}
    report = citation_support(
        anchor("cited"), claim(("E0001", ClaimEvidenceRelationType.QUALIFIES)), items, BIBMAP
    )
    assert report.per_key[0].status == "qualifies"
    assert report.is_supported


def test_support_outranks_a_contradiction_from_the_same_work() -> None:
    items = {
        EvidenceId("E0001"): evidence("E0001"),
        EvidenceId("E0002"): evidence("E0002"),
    }
    report = citation_support(
        anchor("cited"),
        claim(
            ("E0002", ClaimEvidenceRelationType.CONTRADICTS),
            ("E0001", ClaimEvidenceRelationType.SUPPORTS),
        ),
        items,
        BIBMAP,
    )
    assert report.per_key[0].status == "supports"


@pytest.mark.parametrize(
    ("status", "stale"),
    [
        (EvidenceStatus.PROPOSED, StaleState.FRESH),
        (EvidenceStatus.VERIFIED, StaleState.FRESH),
        (EvidenceStatus.ACCEPTED, StaleState.STALE),
    ],
)
def test_only_accepted_non_stale_evidence_decides_support(
    status: EvidenceStatus, stale: StaleState
) -> None:
    items = {EvidenceId("E0001"): evidence("E0001", status=status, stale=stale)}
    report = citation_support(
        anchor("cited"), claim(("E0001", ClaimEvidenceRelationType.SUPPORTS)), items, BIBMAP
    )
    check = report.per_key[0]
    assert check.status == "no_relation"
    assert "not accepted or is stale" in check.reason


def test_a_key_absent_from_the_bibliography_is_missing_not_unmatched() -> None:
    report = citation_support(anchor("nowhere"), claim(), {}, BIBMAP)
    assert report.per_key[0].status == "missing_key"
    assert report.per_key[0].work is None


def test_a_bibliography_entry_with_no_corpus_work_cannot_be_traced() -> None:
    report = citation_support(anchor("unregistered"), claim(), {}, BIBMAP)
    assert report.per_key[0].status == "unmatched_work"
    assert "not registered as a corpus work" in report.per_key[0].reason


def test_every_key_of_a_sentence_is_checked_in_order() -> None:
    report = citation_support(anchor("cited", "other", "nowhere"), claim(), {}, BIBMAP)
    assert [check.key for check in report.per_key] == ["cited", "other", "nowhere"]


# -- numbers in prose ------------------------------------------------------------------


def test_numbers_are_found_with_their_units_and_offsets() -> None:
    text = "Latency fell to 120 ms and the model used 3.5 GB."
    found = numbers_in_sentence(text)
    assert [(item.text, item.value, item.unit) for item in found] == [
        ("120 ms", 120.0, "ms"),
        ("3.5 GB", 3.5, "GB"),
    ]
    assert text[found[0].char_start : found[0].char_end] == "120 ms"
    assert found[0].context == text


def test_precision_is_the_precision_the_author_wrote() -> None:
    (whole,) = numbers_in_sentence("The score is 94 F1.")
    (tenths,) = numbers_in_sentence("The score is 94.3 F1.")
    (hundredths,) = numbers_in_sentence("The score is 94.32 F1.")
    assert (whole.precision, tenths.precision, hundredths.precision) == (0, 1, 2)


@pytest.mark.parametrize(
    "text",
    [
        "The gap was reported by Kraus in 2019.",
        "See Section 3.1 for the protocol.",
        "Table 2 lists the sweep.",
        "The loss is defined in Eq. 1 above.",
        "Figure 4 plots the result.",
        "The bound follows from (1) directly.",
        "The setup follows \\citep{kraus2019} exactly.",
        "The identifier is \\ref{tab:results} in this file.",
        "The formula $x = 12.5$ is inline math.",
        "See \\url{https://example.org/v2/94.32} for the release.",
    ],
)
def test_structural_numbers_are_not_measurements(text: str) -> None:
    assert numbers_in_sentence(text) == ()


def test_a_percentage_keeps_its_latex_escaped_unit() -> None:
    (found,) = numbers_in_sentence("Offered load reached 94.32\\% of capacity.")
    assert found.unit == "\\%"
    assert found.value == 94.32


# -- numeric support -------------------------------------------------------------------

CONTEXT = "TrafficLM reaches an F1 of 94.32 on CICIDS2017."


def supported_claim() -> Claim:
    return claim(("E0001", ClaimEvidenceRelationType.SUPPORTS))


def test_a_value_its_evidence_measured_under_the_same_metric_and_dataset_is_supported() -> None:
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value())}
    check = numeric_support(mention("94.32", 94.32, None, CONTEXT), supported_claim(), items)
    assert check.status == "supported"
    assert check.evidence == EvidenceId("E0001")
    assert check.is_supported


def test_a_value_matched_at_the_authors_precision_is_supported() -> None:
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value(parsed=94.3178))}
    assert (
        numeric_support(mention("94.32", 94.32, None, CONTEXT), supported_claim(), items).status
        == "supported"
    )
    assert (
        numeric_support(mention("94.3178", 94.3178, None, CONTEXT), supported_claim(), items).status
        == "supported"
    )


def test_a_changed_unit_is_incompatible_not_merely_unsupported() -> None:
    """Product 12: the writer must never silently change the unit."""
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value(unit="ms"))}
    check = numeric_support(
        mention("94.32\\%", 94.32, "\\%", "Offered load reached 94.32\\% under F1 on CICIDS2017."),
        supported_claim(),
        items,
    )
    assert check.status == "incompatible"
    assert check.evidence == EvidenceId("E0001")
    assert any("percent" in reason and "ms" in reason for reason in check.reasons)


def test_percent_and_fraction_are_reconciled_rather_than_flagged() -> None:
    items = {
        EvidenceId("E0001"): evidence(
            "E0001", numeric=numeric_value(parsed=0.9432, unit="fraction")
        )
    }
    check = numeric_support(mention("94.32\\%", 94.32, "\\%", CONTEXT), supported_claim(), items)
    assert check.status == "supported"


def test_a_number_reused_without_its_dataset_is_incompatible() -> None:
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value())}
    check = numeric_support(
        mention("94.32", 94.32, None, "The detector reaches an F1 of 94.32 in deployment."),
        supported_claim(),
        items,
    )
    assert check.status == "incompatible"
    assert any("CICIDS2017" in reason for reason in check.reasons)


def test_a_number_reused_without_its_metric_is_incompatible() -> None:
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value())}
    check = numeric_support(
        mention("94.32", 94.32, None, "The detector reaches 94.32 on CICIDS2017."),
        supported_claim(),
        items,
    )
    assert check.status == "incompatible"
    assert any("F1" in reason for reason in check.reasons)


def test_the_claim_semantics_may_carry_the_metric_and_dataset_the_sentence_drops() -> None:
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value())}
    stated = claim(
        ("E0001", ClaimEvidenceRelationType.SUPPORTS),
        statement="TrafficLM reaches an F1 of 94.32 on CICIDS2017",
    )
    check = numeric_support(
        mention("94.32", 94.32, None, "The detector reaches 94.32 in deployment."), stated, items
    )
    assert check.status == "supported"


def test_a_value_nothing_measured_is_unsupported() -> None:
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value())}
    check = numeric_support(mention("71.40", 71.4, None, CONTEXT), supported_claim(), items)
    assert check.status == "unsupported"
    assert check.evidence is None
    assert "no accepted, source-observed evidence" in check.reasons[0]


def test_a_claim_with_no_numeric_evidence_supports_no_value() -> None:
    items = {EvidenceId("E0001"): evidence("E0001")}
    assert (
        numeric_support(mention("94.32", 94.32, None, CONTEXT), supported_claim(), items).status
        == "unsupported"
    )


def test_an_author_claimed_number_cannot_support_a_specific_value() -> None:
    """Product 12: abstract-level and author-reported sources give direction, not values."""
    items = {
        EvidenceId("E0001"): evidence(
            "E0001", origin=EvidenceOrigin.AUTHOR_CLAIMED, numeric=numeric_value()
        )
    }
    check = numeric_support(mention("94.32", 94.32, None, CONTEXT), supported_claim(), items)
    assert check.status == "unsupported"
    assert any("author_claimed" in reason for reason in check.reasons)


def test_an_indirect_reading_cannot_support_a_specific_value() -> None:
    items = {
        EvidenceId("E0001"): evidence(
            "E0001", strength=EvidenceStrength.INDIRECT, numeric=numeric_value()
        )
    }
    check = numeric_support(mention("94.32", 94.32, None, CONTEXT), supported_claim(), items)
    assert check.status == "unsupported"
    assert any("indirect" in reason for reason in check.reasons)


def test_a_stale_numeric_evidence_cannot_support_a_value() -> None:
    items = {
        EvidenceId("E0001"): evidence("E0001", stale=StaleState.STALE, numeric=numeric_value())
    }
    check = numeric_support(mention("94.32", 94.32, None, CONTEXT), supported_claim(), items)
    assert check.status == "unsupported"
    assert any("stale" in reason for reason in check.reasons)


def test_a_contradicting_relation_never_backs_a_number() -> None:
    items = {EvidenceId("E0001"): evidence("E0001", numeric=numeric_value())}
    contradicted = claim(("E0001", ClaimEvidenceRelationType.CONTRADICTS))
    assert (
        numeric_support(mention("94.32", 94.32, None, CONTEXT), contradicted, items).status
        == "unsupported"
    )

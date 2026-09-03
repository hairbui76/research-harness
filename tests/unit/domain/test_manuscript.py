"""Manuscript anchors and audit findings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_harness.domain import (
    ClaimId,
    EvidenceId,
    FindingSeverity,
    ManuscriptAnchor,
    ManuscriptAnchorStatus,
    ManuscriptAuditFinding,
    ManuscriptFindingKind,
    StaleState,
)
from tests.unit.domain import strategies as sty


def anchor(**overrides: object) -> ManuscriptAnchor:
    fields: dict[str, object] = {
        "file": "manuscript/main.tex",
        "line_start": 118,
        "line_end": 119,
        "char_start": 0,
        "char_end": 96,
        "sentence": "Existing systems employ heterogeneous tokenization schemes.",
        "sentence_fingerprint": sty.HASH_C,
        "claim": ClaimId("C0041"),
        "citation_keys": ("smith2026", "lee2025"),
        "provenance": sty.HUMAN,
    }
    return ManuscriptAnchor(**{**fields, **overrides})


def test_an_anchor_maps_a_sentence_to_a_claim() -> None:
    mapped = anchor()
    assert mapped.claim == "C0041"
    assert mapped.citation_keys == ("smith2026", "lee2025")
    assert mapped.status is ManuscriptAnchorStatus.VALID
    assert mapped.stale is StaleState.FRESH


def test_anchor_spans_are_ordered_and_one_based() -> None:
    with pytest.raises(ValidationError, match="line_end"):
        anchor(line_start=120, line_end=119)
    with pytest.raises(ValidationError, match="char_end"):
        anchor(char_start=90, char_end=10)
    with pytest.raises(ValidationError):
        anchor(line_start=0)


def test_the_sentence_fingerprint_is_a_sha256_digest() -> None:
    with pytest.raises(ValidationError):
        anchor(sentence_fingerprint="not-a-hash")


def test_an_anchor_can_go_stale_or_missing_without_reattaching_itself() -> None:
    stale = anchor().touch(
        status=ManuscriptAnchorStatus.STALE,
        stale=StaleState.STALE,
    )
    assert stale.status is ManuscriptAnchorStatus.STALE
    missing = anchor().touch(status=ManuscriptAnchorStatus.MISSING)
    assert missing.claim == anchor().claim


def test_findings_name_the_problem_and_the_objects_involved() -> None:
    finding = ManuscriptAuditFinding(
        kind=ManuscriptFindingKind.OVER_STRONG_WORDING,
        severity=FindingSeverity.ERROR,
        message="Sentence asserts a field-level generalization the claim does not allow.",
        anchor=anchor(),
        related=(ClaimId("C0041"), EvidenceId("E0132")),
    )
    assert finding.kind is ManuscriptFindingKind.OVER_STRONG_WORDING
    assert finding.anchor is not None
    assert finding.related == ("C0041", "E0132")


def test_findings_default_to_a_warning_and_may_have_no_anchor() -> None:
    finding = ManuscriptAuditFinding(
        kind=ManuscriptFindingKind.UNREGISTERED_CLAIM,
        message="Substantive sentence with no registered claim.",
    )
    assert finding.severity is FindingSeverity.WARNING
    assert finding.anchor is None


@pytest.mark.parametrize("kind", list(ManuscriptFindingKind))
def test_every_product_30_3_finding_kind_is_expressible(kind: ManuscriptFindingKind) -> None:
    assert ManuscriptAuditFinding(kind=kind, message="detected").kind is kind

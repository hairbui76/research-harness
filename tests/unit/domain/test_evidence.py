"""Evidence anchoring, numeric provenance, verification, and interpretations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_harness.domain import (
    BlockId,
    BoundingBox,
    EvidenceContent,
    EvidenceId,
    EvidenceOrigin,
    EvidenceStatus,
    Interpretation,
    InterpretationId,
    NegativeEvidenceState,
    NumericValue,
    ReviewTier,
    SourceAnchor,
    StaleState,
    VerificationRecord,
    VerificationVerdict,
)
from tests.unit.domain import strategies as sty

REQUIRED_ANCHOR_FIELDS = ["work", "version", "artifact", "file_hash", "block", "text_hash"]


@pytest.mark.parametrize("missing", REQUIRED_ANCHOR_FIELDS)
def test_evidence_cannot_exist_without_its_source_reference(missing: str) -> None:
    """Product 42.D: accepted evidence always reopens at the exact source it came from."""
    fields = sty.make_anchor().model_dump()
    del fields[missing]
    with pytest.raises(ValidationError):
        SourceAnchor.model_validate(fields)


def test_evidence_requires_a_source_anchor() -> None:
    fields = sty.make_evidence().model_dump()
    del fields["source"]
    with pytest.raises(ValidationError):
        type(sty.make_evidence()).model_validate(fields)


def test_anchor_keeps_page_section_offsets_and_geometry() -> None:
    anchor = sty.make_anchor(bbox=BoundingBox(x0=10, y0=20, x1=110, y1=60))
    assert anchor.page == 8
    assert anchor.section_path == ("Experiments", "Dataset")
    assert (anchor.char_start, anchor.char_end) == (284, 516)
    assert anchor.bbox is not None
    assert anchor.bbox.as_tuple() == (10.0, 20.0, 110.0, 60.0)


def test_char_offsets_come_as_a_pair_and_in_order() -> None:
    with pytest.raises(ValidationError, match="together"):
        sty.make_anchor(char_end=None)
    with pytest.raises(ValidationError, match="precede"):
        sty.make_anchor(char_start=500, char_end=10)


def test_block_id_must_be_a_block() -> None:
    with pytest.raises(ValidationError):
        sty.make_anchor(block=EvidenceId("E0482"))
    assert sty.make_anchor(block=BlockId("B0002")).block == "B0002"


def test_numeric_evidence_is_never_a_naked_number() -> None:
    """Product 12: metric, dataset or condition, and table provenance always travel along."""
    complete = sty.make_numeric()
    assert complete.parsed == pytest.approx(94.32)
    with pytest.raises(ValidationError):
        NumericValue(raw="94.32", parsed=94.32, dataset="CICIDS2017", source_table="T004")
    with pytest.raises(ValidationError, match="dataset or an experimental condition"):
        sty.make_numeric(dataset=None, condition={})
    with pytest.raises(ValidationError):
        sty.make_numeric(source_table="")
    with pytest.raises(ValidationError):
        sty.make_numeric(metric="")


def test_numeric_evidence_keeps_condition_and_table_coordinates() -> None:
    numeric = sty.make_numeric(condition={"model": "ours", "split": "test"})
    assert numeric.condition == {"model": "ours", "split": "test"}
    assert (numeric.source_table, numeric.source_row, numeric.source_column) == (
        "T004",
        "ours",
        "F1",
    )
    assert numeric.unit == "percent"


def test_a_condition_alone_satisfies_the_numeric_policy() -> None:
    assert sty.make_numeric(dataset=None, condition={"split": "test"}).dataset is None


def test_content_requires_text_unless_it_records_absence() -> None:
    with pytest.raises(ValidationError, match="exact_text"):
        EvidenceContent(exact_text="   ")
    absence = EvidenceContent(exact_text="", negative_state=NegativeEvidenceState.NOT_REPORTED)
    assert absence.negative_state is NegativeEvidenceState.NOT_REPORTED


def test_content_can_name_the_interrogation_field() -> None:
    assert EvidenceContent(exact_text="TCP flows", field="traffic_unit").field == "traffic_unit"


def test_new_evidence_starts_as_a_fresh_proposal() -> None:
    evidence = sty.make_evidence()
    assert evidence.verification.status is EvidenceStatus.PROPOSED
    assert evidence.status is EvidenceStatus.PROPOSED
    assert evidence.stale is StaleState.FRESH
    assert evidence.review_tier is ReviewTier.TIER_1
    assert evidence.qualification is None
    assert evidence.decisions == ()


def test_verification_holds_no_model_confidence() -> None:
    """Product 43: categorical status is primary; confidence is never an acceptance input."""
    assert not set(VerificationRecord.model_fields) & {"confidence", "score", "probability"}


def test_verification_records_who_did_what() -> None:
    record = VerificationRecord(
        status=EvidenceStatus.ACCEPTED,
        verdict=VerificationVerdict.SUPPORTED,
        extractor="vendor-a/model-x",
        verifier="vendor-b/model-y",
        accepted_by="human",
    )
    assert record.extractor != record.verifier
    assert record.accepted_by == "human"


def test_stale_status_and_stale_flag_agree() -> None:
    with pytest.raises(ValidationError, match="marked stale"):
        sty.make_evidence(
            verification=VerificationRecord(status=EvidenceStatus.STALE),
            stale=StaleState.FRESH,
        )


@pytest.mark.parametrize(
    ("origin", "tier", "interpretive"),
    [
        (EvidenceOrigin.SOURCE_OBSERVED, ReviewTier.TIER_0, False),
        (EvidenceOrigin.AUTHOR_CLAIMED, ReviewTier.TIER_1, False),
        (EvidenceOrigin.SOURCE_OBSERVED, ReviewTier.TIER_2, True),
        (EvidenceOrigin.MODEL_PROPOSED, ReviewTier.TIER_0, True),
        (EvidenceOrigin.RESEARCHER_INFERRED, ReviewTier.TIER_1, True),
        (EvidenceOrigin.AUTHOR_INTERPRETED, ReviewTier.TIER_0, True),
    ],
)
def test_interpretive_candidates_are_recognised(
    origin: EvidenceOrigin, tier: ReviewTier, interpretive: bool
) -> None:
    assert sty.make_evidence(origin=origin, review_tier=tier).is_interpretive is interpretive


def test_interpretations_need_at_least_one_evidence_object() -> None:
    with pytest.raises(ValidationError):
        Interpretation(
            id=InterpretationId("I0004"),
            evidence=(),
            text="A reading with nothing under it.",
            origin=EvidenceOrigin.RESEARCHER_INFERRED,
            provenance=sty.HUMAN,
        )


@pytest.mark.parametrize(
    "origin",
    [
        EvidenceOrigin.SOURCE_OBSERVED,
        EvidenceOrigin.AUTHOR_CLAIMED,
        EvidenceOrigin.EXTERNAL_METADATA,
    ],
)
def test_interpretations_cannot_pose_as_observations(origin: EvidenceOrigin) -> None:
    with pytest.raises(ValidationError, match="interpretation origin"):
        Interpretation(
            id=InterpretationId("I0004"),
            evidence=(EvidenceId("E0482"),),
            text="The authors imply generality.",
            origin=origin,
            provenance=sty.HUMAN,
        )


def test_interpretations_default_to_deep_review() -> None:
    interpretation = Interpretation(
        id=InterpretationId("I0004"),
        evidence=(EvidenceId("E0482"), EvidenceId("E0483")),
        text="Both systems treat packets as tokens.",
        origin=EvidenceOrigin.MODEL_PROPOSED,
        provenance=sty.MODEL,
    )
    assert interpretation.review_tier is ReviewTier.TIER_2
    assert interpretation.is_interpretive
    assert interpretation.status is EvidenceStatus.PROPOSED

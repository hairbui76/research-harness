"""The interrogation contract: tiers follow the question, and the default schema is neutral."""

from __future__ import annotations

import pytest

from research_harness.domain.enums import EvidenceType, ReviewTier
from research_harness.evidence.interrogation import (
    DEFAULT_SCHEMA,
    InterrogationField,
    InterrogationSchema,
    UnknownFieldError,
    ValueKind,
)

VENDOR_WORDS = ("openai", "anthropic", "claude", "chatgpt", "mcp", "gpt")
DOMAIN_WORDS = ("traffic", "intrusion", "packet", "encrypted", "detector", "cicids")


def make_field(**overrides: object) -> InterrogationField:
    payload: dict[str, object] = {
        "name": "dataset",
        "question": "Which dataset is used?",
        "evidence_types": (EvidenceType.DATASET_DESCRIPTION,),
    }
    return InterrogationField(**{**payload, **overrides})  # type: ignore[arg-type]


# ------------------------------------------------------------------------- fields


def test_a_field_must_allow_at_least_one_evidence_type() -> None:
    with pytest.raises(ValueError, match="at least one evidence type"):
        make_field(evidence_types=())


def test_a_categorical_field_must_list_its_categories() -> None:
    with pytest.raises(ValueError, match="must list its categories"):
        make_field(value_kind=ValueKind.CATEGORICAL)


def test_categories_are_only_meaningful_on_a_categorical_field() -> None:
    with pytest.raises(ValueError, match="not categorical"):
        make_field(value_kind=ValueKind.TEXT, categories=("a", "b"))


def test_a_low_risk_text_field_is_triage_depth() -> None:
    assert make_field(risk=ReviewTier.TIER_1).review_tier is ReviewTier.TIER_1


def test_a_high_risk_field_is_deep_review() -> None:
    assert make_field(risk=ReviewTier.TIER_2).review_tier is ReviewTier.TIER_2


def test_a_number_is_deep_review_however_the_field_is_labelled() -> None:
    """PRODUCT §12: a measured value carries provenance that quick triage cannot check."""
    numeric = make_field(value_kind=ValueKind.NUMERIC, risk=ReviewTier.TIER_1)
    assert numeric.review_tier is ReviewTier.TIER_2


def test_a_field_only_allows_the_evidence_types_it_declares() -> None:
    field = make_field(evidence_types=(EvidenceType.DATASET_DESCRIPTION,))
    assert field.allows(EvidenceType.DATASET_DESCRIPTION)
    assert not field.allows(EvidenceType.LIMITATION)


# ------------------------------------------------------------------------ schemas


def test_a_schema_needs_a_field() -> None:
    with pytest.raises(ValueError, match="at least one field"):
        InterrogationSchema(name="empty", version="1.0.0", fields=())


def test_duplicate_field_names_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate interrogation fields: dataset"):
        InterrogationSchema(
            name="dupe", version="1.0.0", fields=(make_field(), make_field(question="Again?"))
        )


def test_an_unknown_field_names_what_the_schema_does_ask() -> None:
    with pytest.raises(UnknownFieldError, match="has no field 'tokenization'"):
        DEFAULT_SCHEMA.field("tokenization")


def test_select_returns_schema_order_not_caller_order() -> None:
    selected = DEFAULT_SCHEMA.select(["baseline", "dataset"])
    assert [item.name for item in selected] == ["dataset", "baseline"]


def test_select_without_names_returns_every_field() -> None:
    assert DEFAULT_SCHEMA.select(None) == DEFAULT_SCHEMA.fields


def test_select_rejects_a_field_the_schema_does_not_have() -> None:
    with pytest.raises(UnknownFieldError):
        DEFAULT_SCHEMA.select(["dataset", "nonsense"])


def test_the_fingerprint_covers_every_part_of_the_contract() -> None:
    baseline = DEFAULT_SCHEMA.fingerprint()
    assert baseline.startswith("sha256:")
    assert DEFAULT_SCHEMA.model_copy(update={"version": "1.0.1"}).fingerprint() != baseline
    reworded = DEFAULT_SCHEMA.fields[0].touch(question="Which corpus?")
    changed = DEFAULT_SCHEMA.touch(fields=(reworded, *DEFAULT_SCHEMA.fields[1:]))
    assert changed.fingerprint() != baseline


def test_the_fingerprint_is_stable_across_equal_schemas() -> None:
    copy = InterrogationSchema.model_validate(DEFAULT_SCHEMA.model_dump(mode="json"))
    assert copy.fingerprint() == DEFAULT_SCHEMA.fingerprint()


# ------------------------------------------------------------------ default schema


def test_the_default_schema_asks_the_five_generic_questions() -> None:
    assert DEFAULT_SCHEMA.names == (
        "dataset",
        "metric_result",
        "method_summary",
        "author_limitation",
        "baseline",
    )


def test_the_default_schema_names_no_vendor_and_no_domain() -> None:
    """Domain-specific fields arrive through plugins (Product §32.2), never from here."""
    text = DEFAULT_SCHEMA.model_dump_json().lower()
    for word in (*VENDOR_WORDS, *DOMAIN_WORDS):
        assert word not in text


def test_the_default_schema_puts_numbers_and_interpretation_in_deep_review() -> None:
    tiers = {item.name: item.review_tier for item in DEFAULT_SCHEMA.fields}
    assert tiers["metric_result"] is ReviewTier.TIER_2
    assert tiers["author_limitation"] is ReviewTier.TIER_2
    assert tiers["dataset"] is ReviewTier.TIER_1

"""The interrogation contract: which questions a document is asked, and how risky each is.

A schema is the *only* thing that decides what extraction looks for, so adding a question is
configuration rather than code, and a domain plugin contributes fields without touching the
pipeline (Product §32.2). `DEFAULT_SCHEMA` is deliberately generic: dataset, metric, method,
limitation, baseline are questions any empirical paper can be asked, and nothing here knows
about traffic, detection, or any other domain.

Each field also carries its review tier, because review depth is a property of the question,
not of the answer (Product §24.1). A number is Tier 2 whatever the field says: a measured
value carries metric, unit, dataset, and condition that a quick triage cannot check
(Product §12). It also carries `multi_label`, because whether two answers to one question
compete is a property of the question too, and only the schema knows it (dogfood F7).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import field_validator, model_validator

from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.enums import EvidenceType, ReviewTier
from research_harness.domain.errors import DomainValidationError
from research_harness.workflows.fingerprints import fingerprint

__all__ = [
    "DEFAULT_SCHEMA",
    "InterrogationField",
    "InterrogationSchema",
    "UnknownFieldError",
    "ValueKind",
]


class ValueKind(StrEnum):
    """The shape of the answer a field expects.

    `negative` marks a question whose useful answer is often an absence state; it never
    licenses `absent`, which stays an audited researcher conclusion (Product §11).
    """

    TEXT = "text"
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    NEGATIVE = "negative"


class UnknownFieldError(DomainValidationError):
    """A field name is not part of the interrogation schema being used."""


class InterrogationField(DomainModel):
    """One question put to a document, with the evidence it may answer with."""

    name: NonEmptyStr
    question: NonEmptyStr
    evidence_types: tuple[EvidenceType, ...]
    value_kind: ValueKind = ValueKind.TEXT
    risk: ReviewTier = ReviewTier.TIER_1
    """`TIER_1` for a directly evidenced fact, `TIER_2` for anything interpretive."""
    required: bool = False
    categories: tuple[str, ...] = ()
    multi_label: bool = False
    """True when one Work may answer this question several times without contradicting itself.

    Three stated limitations, six baselines, and a hybrid representation that is both
    `field-based` and `behavior-aware` are additional answers, not competing values. The
    schema that asks the question is the only thing that knows which it is, and until this
    flag existed `evidence.conflicts` had to guess from the field name and the question
    wording -- which read 89% of a real review queue as disagreement (dogfood F7). It
    mirrors `plugins.spi.VocabularyField.multi_label`, so a plugin declares the same fact
    once about its vocabulary field and once about the question that fills it.

    Part of the contract, so it is part of `InterrogationSchema.fingerprint()`: changing it
    changes what a conflict means for that field and the field re-extracts (Product 19.1).
    """

    @field_validator("evidence_types")
    @classmethod
    def _at_least_one_evidence_type(
        cls, value: tuple[EvidenceType, ...]
    ) -> tuple[EvidenceType, ...]:
        if not value:
            raise ValueError("an interrogation field must allow at least one evidence type")
        return value

    @model_validator(mode="after")
    def _categories_belong_to_categorical_fields(self) -> InterrogationField:
        if self.value_kind is ValueKind.CATEGORICAL and not self.categories:
            raise ValueError(f"categorical field {self.name!r} must list its categories")
        if self.value_kind is not ValueKind.CATEGORICAL and self.categories:
            raise ValueError(f"field {self.name!r} lists categories but is not categorical")
        return self

    @property
    def review_tier(self) -> ReviewTier:
        """Tier the evidence for this field is staged at; a number is never Tier 1."""
        if self.value_kind is ValueKind.NUMERIC:
            return ReviewTier.TIER_2
        return self.risk

    def allows(self, evidence_type: EvidenceType) -> bool:
        """True when this field may be answered with that kind of evidence."""
        return evidence_type in self.evidence_types


class InterrogationSchema(DomainModel):
    """A named, versioned set of interrogation fields.

    `version` and `fingerprint()` both appear in stage fingerprints: a changed question must
    re-extract the field it changed, and only that field (Product §19.1).
    """

    name: NonEmptyStr
    version: NonEmptyStr
    fields: tuple[InterrogationField, ...]

    @field_validator("fields")
    @classmethod
    def _names_are_unique(
        cls, value: tuple[InterrogationField, ...]
    ) -> tuple[InterrogationField, ...]:
        if not value:
            raise ValueError("an interrogation schema needs at least one field")
        names = [item.name for item in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate interrogation fields: {', '.join(duplicates)}")
        return value

    @property
    def names(self) -> tuple[str, ...]:
        """Field names in declaration order."""
        return tuple(item.name for item in self.fields)

    def field(self, name: str) -> InterrogationField:
        """The field called `name`; raises `UnknownFieldError` when the schema has none."""
        for item in self.fields:
            if item.name == name:
                return item
        raise UnknownFieldError(
            f"schema {self.name}@{self.version} has no field {name!r}; "
            f"it asks: {', '.join(self.names)}"
        )

    def select(self, names: tuple[str, ...] | list[str] | None) -> tuple[InterrogationField, ...]:
        """The named fields in schema order, or every field when `names` is None."""
        if names is None:
            return self.fields
        requested = list(names)
        for name in requested:
            self.field(name)
        return tuple(item for item in self.fields if item.name in set(requested))

    def fingerprint(self) -> str:
        """`sha256:<hex>` over the whole contract: identity, version, and every field."""
        return fingerprint(self.model_dump(mode="json"))


DEFAULT_SCHEMA = InterrogationSchema(
    name="generic-empirical",
    version="1.0.0",
    fields=(
        InterrogationField(
            name="dataset",
            question=(
                "Which dataset or corpus do the reported experiments use? Quote the sentence "
                "that names it."
            ),
            evidence_types=(EvidenceType.DATASET_DESCRIPTION, EvidenceType.EXPERIMENTAL_SETUP),
            value_kind=ValueKind.TEXT,
            risk=ReviewTier.TIER_1,
            required=True,
            multi_label=True,
        ),
        InterrogationField(
            name="metric_result",
            question=(
                "Which measured result does the paper report for its own system? Quote the "
                "exact value with the metric, dataset, and table it comes from."
            ),
            evidence_types=(EvidenceType.EXPERIMENTAL_RESULT, EvidenceType.ABLATION_RESULT),
            value_kind=ValueKind.NUMERIC,
            risk=ReviewTier.TIER_2,
            required=True,
            multi_label=True,
        ),
        InterrogationField(
            name="method_summary",
            question=(
                "How does the paper describe its own method or representation? Quote the "
                "sentence that states it."
            ),
            evidence_types=(
                EvidenceType.METHOD_DESCRIPTION,
                EvidenceType.REPRESENTATION_DESCRIPTION,
            ),
            value_kind=ValueKind.TEXT,
            risk=ReviewTier.TIER_1,
        ),
        InterrogationField(
            name="author_limitation",
            question=(
                "Which limitation, threat to validity, or scope restriction do the authors "
                "state themselves? Quote it."
            ),
            evidence_types=(EvidenceType.LIMITATION, EvidenceType.AUTHOR_CONCLUSION),
            value_kind=ValueKind.TEXT,
            risk=ReviewTier.TIER_2,
            multi_label=True,
        ),
        InterrogationField(
            name="baseline",
            question="Which baselines or comparison systems does the paper evaluate against?",
            evidence_types=(EvidenceType.BASELINE_DESCRIPTION, EvidenceType.EXPERIMENTAL_SETUP),
            value_kind=ValueKind.TEXT,
            risk=ReviewTier.TIER_1,
            multi_label=True,
        ),
    ),
)
"""The plugin-neutral baseline contract; domain plugins contribute their own schemas.

Four of the five questions declare `multi_label`: a paper evaluates on several datasets,
reports several measured values, states several limitations, and compares against several
baselines, and none of those is a contradiction. `method_summary` does not: a paper
describes one method, and two different descriptions of it are worth a reviewer's eye.
"""

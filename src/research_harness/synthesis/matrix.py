"""Pure synthesis-matrix construction, comparison, and diffing (Product 7.1, 33, 37).

Nothing here touches a workspace, a provider, or a projection: a matrix is a *function* of
an accepted taxonomy Decision, the accepted Evidence in the corpus, and the classification
rules the researcher wrote down. That is what makes a matrix reproducible and what lets
the dependency graph say honestly which change made it stale (ADR-008).

Three rules shape everything in this module:

* **Multi-label, never exclusive.** A work can be several things at once; forcing one
  label per cell would make the table tidy and the science wrong.
* **An empty cell is "not recorded", never "absent".** Unclassified works keep an empty
  label tuple and are reported as unclassified; turning that into an absence claim needs
  search coverage and an audited Decision (Product 11, 42.F).
* **A model proposes, a researcher labels.** `apply_proposals` returns a separate
  :class:`MatrixProposal`; it never writes a model's labels into the matrix (ADR-007).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from research_harness.domain.base import (
    DomainModel,
    NonEmptyStr,
    Provenance,
    UtcDatetime,
    utc_now,
)
from research_harness.domain.enums import DecisionStatus, DecisionType, EvidenceStatus
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import Evidence, normalize_label
from research_harness.domain.ids import EvidenceId, SynthesisId, WorkId
from research_harness.domain.research import Decision, MatrixCell, SynthesisMatrix, Taxonomy
from research_harness.roles.schemas import CellProposal, SynthesisOutput

__all__ = [
    "CellChange",
    "ClassificationRule",
    "ComparisonRow",
    "ComparisonTable",
    "MatrixDiff",
    "MatrixProposal",
    "ProposedCell",
    "RejectedProposal",
    "apply_proposals",
    "build_matrix",
    "classification_text",
    "compare_field",
    "declares_label",
    "matrix_diff",
    "matrix_name_for",
]


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    """One deterministic reason to put ``term`` in the ``field`` cell of a work.

    ``any_of`` holds the tokens or phrases that justify the label. Matching is
    case-insensitive and bounded by word edges, so ``byte`` matches "byte-level" and not
    "bytes"; nothing here is fuzzy, because a rule a researcher cannot replay by hand is
    not a rule they can defend.
    """

    term: str
    field: str
    any_of: tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        """True when any token or phrase of this rule occurs in ``text``."""
        if not text:
            return False
        return any(_contains(text, needle) for needle in self.any_of if needle)


class ProposedCell(DomainModel):
    """One model-proposed cell: candidate labels that are not in the matrix."""

    work: WorkId
    field: NonEmptyStr
    labels: tuple[str, ...] = ()
    evidence: tuple[EvidenceId, ...] = ()


class RejectedProposal(DomainModel):
    """A proposed cell the matrix cannot accept, and why it was refused."""

    work: str
    field: str
    labels: tuple[str, ...] = ()
    reason: NonEmptyStr


class MatrixProposal(DomainModel):
    """Model-proposed labels for one matrix, staged for review and never applied.

    A proposal has no authority: it is regenerable state under `.research/staging/`, and
    the cells it names gain labels only when a researcher rebuilds the matrix with rules
    that say so, or edits it deliberately (ADR-003, ADR-007).
    """

    matrix: SynthesisId
    taxonomy: str | None = None
    fields: tuple[str, ...] = ()
    cells: tuple[ProposedCell, ...] = ()
    rejected: tuple[RejectedProposal, ...] = ()
    notes: str | None = None
    actor: str | None = None
    """The model that proposed the cells; never a host or a provider brand."""
    proposed_at: UtcDatetime = Field(default_factory=utc_now)

    @property
    def is_empty(self) -> bool:
        """True when nothing usable was proposed."""
        return not self.cells


@dataclass(frozen=True, slots=True)
class CellChange:
    """How one cell's labels and evidence moved between two versions of a matrix."""

    work: WorkId
    field: str
    added_labels: tuple[str, ...] = ()
    removed_labels: tuple[str, ...] = ()
    added_evidence: tuple[EvidenceId, ...] = ()
    removed_evidence: tuple[EvidenceId, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when nothing about the cell changed."""
        return not (
            self.added_labels or self.removed_labels or self.added_evidence or self.removed_evidence
        )


@dataclass(frozen=True, slots=True)
class MatrixDiff:
    """What changed between two matrices, cell by cell."""

    added: tuple[MatrixCell, ...] = ()
    removed: tuple[MatrixCell, ...] = ()
    changed: tuple[CellChange, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when the two matrices classify the corpus identically."""
        return not (self.added or self.removed or self.changed)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for transports and `--json` output."""
        return {
            "added": [_cell_dict(cell) for cell in self.added],
            "removed": [_cell_dict(cell) for cell in self.removed],
            "changed": [
                {
                    "work": str(change.work),
                    "field": change.field,
                    "added_labels": list(change.added_labels),
                    "removed_labels": list(change.removed_labels),
                    "added_evidence": [str(value) for value in change.added_evidence],
                    "removed_evidence": [str(value) for value in change.removed_evidence],
                }
                for change in self.changed
            ],
        }


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    """One work's row of a `research compare <field>` table."""

    work: WorkId
    labels: tuple[str, ...] = ()
    evidence: tuple[EvidenceId, ...] = ()

    @property
    def classified(self) -> bool:
        """True when the corpus records a classification for this work."""
        return bool(self.labels)


@dataclass(frozen=True, slots=True)
class ComparisonTable:
    """One field across the corpus: a row per work, with its labels and their evidence."""

    matrix: SynthesisId
    field: str
    taxonomy: str | None = None
    rows: tuple[ComparisonRow, ...] = ()

    @property
    def unclassified(self) -> tuple[WorkId, ...]:
        """Works with no recorded label. Not recorded is not the same as not present."""
        return tuple(row.work for row in self.rows if not row.classified)

    def label_counts(self) -> dict[str, int]:
        """How many works carry each label, most frequent first, then alphabetical."""
        counts: dict[str, int] = {}
        for row in self.rows:
            for label in row.labels:
                counts[label] = counts.get(label, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for transports and `--json` output."""
        return {
            "matrix": str(self.matrix),
            "field": self.field,
            "taxonomy": self.taxonomy,
            "rows": [
                {
                    "work": str(row.work),
                    "labels": list(row.labels),
                    "evidence": [str(value) for value in row.evidence],
                }
                for row in self.rows
            ],
            "unclassified": [str(work) for work in self.unclassified],
            "label_counts": self.label_counts(),
        }


# -- building ----------------------------------------------------------------


def matrix_name_for(taxonomy: Taxonomy, field: str) -> str:
    """Default matrix name: the field, compared under a named taxonomy."""
    return f"{field} under {taxonomy.name}"


def classification_text(evidence: Evidence) -> str:
    """The text a rule reads: the exact quote plus the categorical values around a number.

    An absence record contributes nothing: `not_reported` is the reason a cell stays
    empty, never a reason to put a label in it (Product 11, 42.F).
    """
    if evidence.content.negative_state is not None:
        return ""
    parts: list[str] = [evidence.content.exact_text]
    numeric = evidence.content.numeric
    if numeric is not None:
        parts.extend(
            [
                numeric.raw,
                numeric.metric,
                numeric.dataset or "",
                numeric.unit or "",
                numeric.source_table,
                numeric.source_row or "",
                numeric.source_column or "",
                *numeric.condition.values(),
            ]
        )
    return "\n".join(part for part in parts if part)


def build_matrix(
    taxonomy: Taxonomy,
    decision: Decision,
    evidence: Sequence[Evidence],
    works: Sequence[WorkId],
    field: str,
    rules: Sequence[ClassificationRule],
    *,
    matrix_id: SynthesisId,
    provenance: Provenance,
    name: str | None = None,
) -> SynthesisMatrix:
    """Classify ``works`` under ``taxonomy`` for one ``field``, from accepted evidence only.

    Every work gets a cell. A cell carries every term whose rule matched, together with
    the accepted Evidence ids that justified the match; a work no rule matched keeps an
    empty label tuple, which means "not recorded" and never "the work lacks the property".

    Raises `DomainValidationError` when the decision does not authorise the taxonomy, a
    rule names a term the taxonomy does not define, or a non-accepted Evidence object is
    offered as a basis for classification.
    """
    if not field.strip():
        raise DomainValidationError("a synthesis matrix is built for a named field")
    _check_decision(taxonomy, decision)
    terms = tuple(term.term for term in taxonomy.terms)
    field_rules = tuple(rule for rule in rules if rule.field == field)
    _check_rules(field_rules, terms)
    accepted = _accepted_only(evidence)

    ordered_works = tuple(dict.fromkeys(works))
    by_work = _evidence_by_work(accepted, field)
    cells = tuple(
        _cell_for(work, field, terms, field_rules, by_work.get(work, ())) for work in ordered_works
    )
    return SynthesisMatrix(
        id=matrix_id,
        name=name or matrix_name_for(taxonomy, field),
        taxonomy=taxonomy.name,
        works=ordered_works,
        fields=(field,),
        cells=cells,
        provenance=_with_decision_note(provenance, taxonomy, decision),
    )


def declares_label(evidence: Evidence, term: str) -> bool:
    """True when this evidence itself names ``term`` as its category (dogfood F13).

    An extractor answering a categorical question may state the category beside the span
    it quoted, checked at extraction against the schema's declared vocabulary. The label
    and the keyword rules are read together: a rule is the reproducible cross-check, not
    the only way a cell can be filled. Spellings are compared with `_`, `-` and spaces
    collapsed, so a taxonomy term and a schema category need not agree on punctuation.
    """
    if evidence.content.negative_state is not None:
        return False
    wanted = normalize_label(term)
    return any(normalize_label(label) == wanted for label in evidence.content.labels)


def _cell_for(
    work: WorkId,
    field: str,
    terms: Sequence[str],
    rules: Sequence[ClassificationRule],
    evidence: Sequence[Evidence],
) -> MatrixCell:
    """One multi-label cell, listing the evidence that justified each label it carries."""
    labels: list[str] = []
    justifying: list[EvidenceId] = []
    for term in terms:
        term_rules = [rule for rule in rules if rule.term == term]
        matched = [
            item.id
            for item in evidence
            if declares_label(item, term)
            or any(rule.matches(classification_text(item)) for rule in term_rules)
        ]
        if not matched:
            continue
        labels.append(term)
        justifying.extend(value for value in matched if value not in justifying)
    return MatrixCell(
        work=work,
        field=field,
        labels=tuple(labels),
        evidence=tuple(justifying),
    )


def _evidence_by_work(
    evidence: Sequence[Evidence], field: str
) -> dict[WorkId, tuple[Evidence, ...]]:
    """Accepted evidence per work, keeping only what can speak to ``field``.

    Evidence produced for a different interrogation field is left out: an answer about the
    dataset is not an answer about tokenization, however suggestive its wording.
    """
    grouped: dict[WorkId, list[Evidence]] = {}
    for item in evidence:
        recorded = item.content.field
        if recorded is not None and recorded != field:
            continue
        grouped.setdefault(item.source.work, []).append(item)
    return {
        work: tuple(sorted(items, key=lambda item: str(item.id))) for work, items in grouped.items()
    }


def _check_decision(taxonomy: Taxonomy, decision: Decision) -> None:
    if decision.type is not DecisionType.TAXONOMY_REVISION:
        raise DomainValidationError(
            f"{decision.id} is a {decision.type.value} decision; a matrix is classified under "
            "an accepted taxonomy_revision"
        )
    if decision.status is not DecisionStatus.ACCEPTED:
        raise DomainValidationError(
            f"{decision.id} is {decision.status.value}; accept it before classifying under it"
        )
    unknown = sorted(set(decision.taxonomy_terms) - {term.term for term in taxonomy.terms})
    if unknown:
        raise DomainValidationError(
            f"{decision.id} approves terms the taxonomy {taxonomy.name!r} does not define: "
            + ", ".join(unknown)
        )


def _check_rules(rules: Sequence[ClassificationRule], terms: Sequence[str]) -> None:
    known = set(terms)
    unknown = sorted({rule.term for rule in rules} - known)
    if unknown:
        raise DomainValidationError(
            "classification rules name terms outside the approved taxonomy: " + ", ".join(unknown)
        )
    empty = sorted({rule.term for rule in rules if not any(rule.any_of)})
    if empty:
        raise DomainValidationError(
            "a classification rule needs at least one token or phrase: " + ", ".join(empty)
        )


def _accepted_only(evidence: Sequence[Evidence]) -> tuple[Evidence, ...]:
    unaccepted = [item for item in evidence if item.status is not EvidenceStatus.ACCEPTED]
    if unaccepted:
        listed = ", ".join(f"{item.id} ({item.status.value})" for item in unaccepted[:5])
        raise DomainValidationError(
            f"a synthesis matrix is built from accepted evidence only; refused: {listed}"
        )
    return tuple(evidence)


def _with_decision_note(
    provenance: Provenance, taxonomy: Taxonomy, decision: Decision
) -> Provenance:
    """Record the authorising Decision on the matrix's provenance.

    `SynthesisMatrix` records the taxonomy by name but has no field for the Decision that
    approved it, so the id goes here rather than being lost; the dependency graph still
    reaches the matrix through `decision -> taxonomy -> matrix`.
    """
    if provenance.note:
        return provenance
    return provenance.touch(note=f"classified under taxonomy {taxonomy.name!r} by {decision.id}")


# -- proposals ---------------------------------------------------------------


def apply_proposals(
    matrix: SynthesisMatrix,
    proposals: SynthesisOutput,
    *,
    terms: Sequence[str] | None = None,
    actor: str | None = None,
) -> tuple[SynthesisMatrix, MatrixProposal]:
    """Stage model-proposed cells beside ``matrix``; the matrix itself is returned unchanged.

    Nothing is merged into the matrix: a proposal is a candidate label, and a cell gains a
    label only when a researcher accepts it (ADR-007). Proposals that name a work, field,
    or term the matrix cannot host are reported in `rejected` rather than dropped, so a
    model that invented a label is visible instead of silently ignored.
    """
    known_works = set(matrix.works)
    known_fields = set(matrix.fields)
    vocabulary = None if terms is None else set(terms)
    accepted: list[ProposedCell] = []
    rejected: list[RejectedProposal] = []
    for proposal in proposals.cells:
        reason = _proposal_refusal(proposal, known_works, known_fields, vocabulary)
        if reason is not None:
            rejected.append(
                RejectedProposal(
                    work=proposal.work,
                    field=proposal.field,
                    labels=tuple(proposal.labels),
                    reason=reason,
                )
            )
            continue
        accepted.append(
            ProposedCell(
                work=WorkId(proposal.work),
                field=proposal.field,
                labels=tuple(dict.fromkeys(proposal.labels)),
                evidence=tuple(EvidenceId(value) for value in dict.fromkeys(proposal.evidence)),
            )
        )
    staged = MatrixProposal(
        matrix=matrix.id,
        taxonomy=matrix.taxonomy,
        fields=matrix.fields,
        cells=tuple(accepted),
        rejected=tuple(rejected),
        notes=proposals.notes,
        actor=actor,
    )
    return matrix, staged


def _proposal_refusal(
    proposal: CellProposal,
    works: set[WorkId],
    fields: set[str],
    vocabulary: set[str] | None,
) -> str | None:
    if proposal.work not in {str(work) for work in works}:
        return f"{proposal.work} is not a row of this matrix"
    if fields and proposal.field not in fields:
        return f"{proposal.field!r} is not a column of this matrix"
    if vocabulary is not None:
        invented = sorted(set(proposal.labels) - vocabulary)
        if invented:
            return "labels outside the approved taxonomy: " + ", ".join(invented)
    return None


# -- comparison and diffing --------------------------------------------------


def compare_field(matrix: SynthesisMatrix, field: str) -> ComparisonTable:
    """One row per work in ``matrix`` for ``field``, in the matrix's declared work order.

    A work with no cell for the field is still a row, with no labels: the table's job is
    to show what the corpus records, including where it records nothing.
    """
    if matrix.fields and field not in matrix.fields:
        known = ", ".join(matrix.fields) or "none"
        raise DomainValidationError(
            f"matrix {matrix.id} does not compare {field!r}; it holds: {known}"
        )
    cells = {cell.work: cell for cell in matrix.cells if cell.field == field}
    rows = tuple(
        ComparisonRow(
            work=work,
            labels=cells[work].labels if work in cells else (),
            evidence=cells[work].evidence if work in cells else (),
        )
        for work in matrix.works
    )
    return ComparisonTable(matrix=matrix.id, field=field, taxonomy=matrix.taxonomy, rows=rows)


def matrix_diff(old: SynthesisMatrix, new: SynthesisMatrix) -> MatrixDiff:
    """Cells added, cells removed, and cells whose labels or evidence moved."""
    before = _cells_by_key(old)
    after = _cells_by_key(new)
    added = tuple(after[key] for key in sorted(set(after) - set(before)))
    removed = tuple(before[key] for key in sorted(set(before) - set(after)))
    changed: list[CellChange] = []
    for key in sorted(set(before) & set(after)):
        change = _cell_change(before[key], after[key])
        if not change.is_empty:
            changed.append(change)
    return MatrixDiff(added=added, removed=removed, changed=tuple(changed))


def _cell_change(before: MatrixCell, after: MatrixCell) -> CellChange:
    return CellChange(
        work=after.work,
        field=after.field,
        added_labels=_missing(after.labels, before.labels),
        removed_labels=_missing(before.labels, after.labels),
        added_evidence=_missing(after.evidence, before.evidence),
        removed_evidence=_missing(before.evidence, after.evidence),
    )


def _cells_by_key(matrix: SynthesisMatrix) -> dict[tuple[str, str], MatrixCell]:
    return {(str(cell.work), cell.field): cell for cell in matrix.cells}


def _missing[T: str](values: Sequence[T], other: Sequence[T]) -> tuple[T, ...]:
    absent = set(other)
    return tuple(value for value in values if value not in absent)


def _cell_dict(cell: MatrixCell) -> Mapping[str, Any]:
    return {
        "work": str(cell.work),
        "field": cell.field,
        "labels": list(cell.labels),
        "evidence": [str(value) for value in cell.evidence],
    }


def _contains(text: str, needle: str) -> bool:
    pattern = rf"(?<!\w){re.escape(needle.strip())}(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None

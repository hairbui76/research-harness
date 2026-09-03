"""Synthesis over one workspace: taxonomy revisions, matrices, proposals, staleness.

The service is the thin part. It reads accepted state through the repository, calls the
pure functions in :mod:`~research_harness.synthesis.matrix` to decide what the matrix
says, and writes through the capability layer so the canonical file, the semantic event,
and the stale set commit as one unit (ADR-001, ADR-004).

Two things it deliberately does *not* do: it never recomputes a matrix because something
upstream moved — that is what `stale_matrices` is for (ADR-008) — and it never writes a
model's labels into a matrix; `propose_with_model` stages a `MatrixProposal` under
`.research/staging/synthesis/` and stops there (ADR-007).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    MutationResult,
    PutMatrixRequest,
    PutTaxonomyRequest,
)
from research_harness.capabilities.handlers import accept_decision, put_matrix, put_taxonomy
from research_harness.domain.enums import (
    DecisionStatus,
    DecisionType,
    EvidenceStatus,
    StaleState,
)
from research_harness.domain.errors import CapabilityError, DomainValidationError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ClaimId, DecisionId, SynthesisId, WorkId, parse_id
from research_harness.domain.research import (
    Decision,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
)
from research_harness.projection.dependencies import (
    StaleMark,
    StaleSet,
    load_stale_marks,
    priority_for,
)
from research_harness.projection.rows import NODE_SEPARATOR
from research_harness.projection.schema import create_engine_for
from research_harness.providers.models.base import ModelProvider
from research_harness.roles import SYNTHESIZER, InputKind, RoleInput, build_request
from research_harness.roles.schemas import SynthesisOutput
from research_harness.synthesis.matrix import (
    ClassificationRule,
    ComparisonTable,
    MatrixProposal,
    apply_proposals,
    build_matrix,
    compare_field,
)
from research_harness.workspace.atomic import atomic_write_text
from research_harness.workspace.repository import ObjectNotFoundError, WorkspaceRepository

__all__ = [
    "STAGING_SYNTHESIS_DIRNAME",
    "SynthesisService",
    "TaxonomyRevision",
    "next_decision_id",
    "next_matrix_id",
]

STAGING_SYNTHESIS_DIRNAME = "staging/synthesis"
"""Where model proposals live: regenerable, deletable, and never scientific authority."""


@dataclass(frozen=True, slots=True)
class TaxonomyRevision:
    """One taxonomy revision: the Decision that approved it and the taxonomy it wrote."""

    taxonomy: Taxonomy
    decision: Decision
    accepted: MutationResult
    written: MutationResult

    @property
    def mutations(self) -> tuple[MutationResult, MutationResult]:
        """The decision acceptance and the taxonomy write, in commit order."""
        return (self.accepted, self.written)

    @property
    def stale(self) -> tuple[StaleMark, ...]:
        """Everything the revision made stale, highest scientific impact first."""
        return tuple(StaleSet([*self.accepted.stale, *self.written.stale]))


class SynthesisService:
    """Build, compare, and stage synthesis matrices for one workspace."""

    def __init__(self, ctx: CapabilityContext) -> None:
        self._ctx = ctx

    @property
    def ctx(self) -> CapabilityContext:
        """The capability context every mutation runs through."""
        return self._ctx

    @property
    def staging_dir(self) -> Path:
        """`.research/staging/synthesis/`; created on first use, safe to delete."""
        return self._ctx.repo.layout.research_dir / STAGING_SYNTHESIS_DIRNAME

    # -- taxonomy ------------------------------------------------------------

    def revise_taxonomy(
        self,
        name: str,
        terms: Sequence[str],
        rationale: str,
        *,
        definitions: dict[str, str] | None = None,
    ) -> TaxonomyRevision:
        """Accept a `taxonomy_revision` Decision and write the taxonomy it approves.

        A taxonomy is a researcher decision, never a fact a tool discovered (Product 33),
        so the Decision comes first and the taxonomy file names it on every term. A later
        revision supersedes the previous Decision by reference; the old Decision file stays
        exactly where it is, because the record of why the project once classified things
        differently is the point (ADR-008).
        """
        previous = self._accepted_taxonomy_decision(name)
        decision = Decision(
            id=next_decision_id(self._ctx.repo),
            type=DecisionType.TAXONOMY_REVISION,
            status=DecisionStatus.PROPOSED,
            title=f"taxonomy {name}",
            rationale=rationale,
            taxonomy_terms=tuple(dict.fromkeys(terms)),
            supersedes=None if previous is None else previous.id,
            provenance=self._ctx.provenance(workflow="taxonomy"),
        )
        accepted = accept_decision(self._ctx, AcceptDecisionRequest(decision=decision))
        stored = self._ctx.repo.get_decision(decision.id)
        taxonomy = Taxonomy(
            name=name,
            terms=tuple(
                TaxonomyTerm(
                    term=term,
                    definition=(definitions or {}).get(term),
                    decision=stored.id,
                )
                for term in dict.fromkeys(terms)
            ),
            provenance=self._ctx.provenance(workflow="taxonomy"),
        )
        written = put_taxonomy(self._ctx, PutTaxonomyRequest(taxonomy=taxonomy, decision=stored))
        return TaxonomyRevision(
            taxonomy=self._ctx.repo.get_taxonomy(name),
            decision=stored,
            accepted=accepted,
            written=written,
        )

    def taxonomy_decision(self, taxonomy: Taxonomy) -> Decision:
        """The accepted Decision a taxonomy's terms were approved under."""
        decision = self._accepted_taxonomy_decision(taxonomy.name)
        if decision is None:
            raise CapabilityError(
                f"taxonomy {taxonomy.name!r} names no accepted taxonomy_revision decision; "
                "run `research taxonomy set` before building a matrix"
            )
        return decision

    def _accepted_taxonomy_decision(self, name: str) -> Decision | None:
        """The newest accepted taxonomy Decision the stored taxonomy points at.

        Read from the taxonomy's own terms first, so the answer is the decision the file
        was written under rather than whichever decision happens to be newest on disk.
        """
        decisions = {decision.id: decision for decision in self._ctx.repo.list_decisions()}
        referenced: list[Decision] = []
        try:
            taxonomy: Taxonomy | None = self._ctx.repo.get_taxonomy(name)
        except ObjectNotFoundError:
            taxonomy = None
        if taxonomy is not None:
            referenced = [
                decisions[term.decision]
                for term in taxonomy.terms
                if term.decision is not None and term.decision in decisions
            ]
        candidates = [
            decision
            for decision in (referenced or decisions.values())
            if decision.type is DecisionType.TAXONOMY_REVISION
            and decision.status is DecisionStatus.ACCEPTED
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda decision: (decision.updated_at, str(decision.id)))

    # -- matrices ------------------------------------------------------------

    def existing_matrix(
        self, field: str, taxonomy_name: str, *, matrix_id: SynthesisId | None = None
    ) -> SynthesisMatrix | None:
        """The matrix a :meth:`build` with these arguments would overwrite, if one exists.

        Read before the build so the caller can diff what moved: rebuilding after a rule
        fix printed only `classified 5 of 5` and said nothing about the work that changed
        family (dogfood F16).
        """
        target = matrix_id or self._matrix_id_for(taxonomy_name, field)
        try:
            return self._ctx.repo.get_matrix(target)
        except ObjectNotFoundError:
            return None

    def dependent_claims(self, matrix_id: SynthesisId) -> tuple[ClaimId, ...]:
        """Claims that were read off this matrix, in id order (`Claim.derived_from`)."""
        return tuple(
            sorted(
                claim.id
                for claim in self._ctx.repo.list_claims()
                if matrix_id in claim.derived_from
            )
        )

    def build(
        self,
        field: str,
        taxonomy_name: str,
        rules: Sequence[ClassificationRule],
        *,
        matrix_id: SynthesisId | None = None,
        works: Sequence[WorkId] | None = None,
        name: str | None = None,
        force: bool = False,
    ) -> tuple[SynthesisMatrix, MutationResult]:
        """Classify the corpus for one field and persist the matrix.

        The matrix is derived from the accepted taxonomy Decision and the accepted
        Evidence behind each cell, which is exactly the shape the dependency graph reads:
        `decision -> taxonomy -> matrix -> claim`, and `evidence -> cell -> matrix`.

        A rebuild that would overwrite a matrix a Claim was read off is refused without
        ``force``: the claim's support can move under it, and a silent overwrite makes the
        claim say something the record no longer shows (dogfood F16).
        """
        previous = self.existing_matrix(field, taxonomy_name, matrix_id=matrix_id)
        if previous is not None and not force:
            dependents = self.dependent_claims(previous.id)
            if dependents:
                named = ", ".join(str(claim) for claim in dependents)
                raise CapabilityError(
                    f"synthesis.build_matrix: {previous.id} was read off by {named}; "
                    "rebuilding it can move the labels those claims rest on. Re-run with "
                    "force to overwrite it and re-audit them."
                )
        taxonomy = self._ctx.repo.get_taxonomy(taxonomy_name)
        decision = self.taxonomy_decision(taxonomy)
        rows = tuple(works) if works is not None else self.corpus_works()
        matrix = build_matrix(
            taxonomy,
            decision,
            self.accepted_evidence(rows),
            rows,
            field,
            rules,
            matrix_id=matrix_id or self._matrix_id_for(taxonomy_name, field),
            provenance=self._ctx.provenance(workflow="synthesis"),
            name=name,
        )
        result = put_matrix(self._ctx, PutMatrixRequest(matrix=matrix))
        return self._ctx.repo.get_matrix(matrix.id), result

    def compare(self, field: str, *, matrix_id: SynthesisId | None = None) -> ComparisonTable:
        """The `research compare <field>` table: one row per work, labels and evidence."""
        return compare_field(self.matrix_for(field, matrix_id=matrix_id), field)

    def matrix_for(self, field: str, *, matrix_id: SynthesisId | None = None) -> SynthesisMatrix:
        """The matrix that compares ``field``, by id or by the field it declares."""
        if matrix_id is not None:
            return self._ctx.repo.get_matrix(matrix_id)
        found = [
            matrix
            for matrix in sorted(self._ctx.repo.list_matrices(), key=lambda item: str(item.id))
            if field in matrix.fields
        ]
        if not found:
            raise CapabilityError(
                f"no synthesis matrix compares {field!r} in {self._ctx.root}; run "
                "`research matrix build` first"
            )
        return found[-1]

    # -- model proposals -----------------------------------------------------

    def propose_with_model(
        self,
        field: str,
        provider: ModelProvider,
        *,
        matrix_id: SynthesisId | None = None,
    ) -> MatrixProposal:
        """Ask the synthesizer role for candidate labels and stage them for review.

        The proposal is written under `.research/staging/synthesis/`; the matrix on disk is
        not touched, and no cell gains a label until a researcher says so (ADR-007).
        """
        matrix = self.matrix_for(field, matrix_id=matrix_id)
        taxonomy = self._ctx.repo.get_taxonomy(matrix.taxonomy) if matrix.taxonomy else None
        evidence = self.accepted_evidence(matrix.works)
        inputs = [
            RoleInput(InputKind.ACCEPTED_EVIDENCE, str(item.id), _evidence_payload(item))
            for item in evidence
        ]
        if taxonomy is not None:
            inputs.append(RoleInput(InputKind.TAXONOMY, taxonomy.name, taxonomy))
        built = build_request(
            SYNTHESIZER,
            inputs,
            extra_instructions=f"Classify the field {field!r} for every work you were given.",
        )
        response = provider.complete(built.request)
        output = response.parsed
        if not isinstance(output, SynthesisOutput):  # pragma: no cover - schema-enforced
            raise CapabilityError(
                f"the synthesizer role returned {type(output).__name__}, not SynthesisOutput"
            )
        _, proposal = apply_proposals(
            matrix,
            output,
            terms=None if taxonomy is None else [term.term for term in taxonomy.terms],
            actor=f"{response.provider}/{response.model}",
        )
        self.stage(proposal)
        return proposal

    def stage(self, proposal: MatrixProposal) -> Path:
        """Write ``proposal`` under `.research/staging/synthesis/`, atomically."""
        directory = self.staging_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{proposal.matrix}.json"
        atomic_write_text(path, proposal.model_dump_json(indent=2) + "\n")
        return path

    def staged(self, matrix_id: SynthesisId) -> MatrixProposal | None:
        """The staged proposal for ``matrix_id``, if one was written."""
        path = self.staging_dir / f"{matrix_id}.json"
        if not path.is_file():
            return None
        return MatrixProposal.model_validate(json.loads(path.read_text(encoding="utf-8")))

    # -- staleness -----------------------------------------------------------

    def stale_matrices(self) -> tuple[StaleMark, ...]:
        """Matrices and matrix cells currently marked stale, highest impact first.

        The projection is consulted when it exists and canonical `stale` flags when it does
        not, because deleting `.research/` must never lose the fact that a conclusion moved
        (ADR-001, ADR-006).
        """
        marks = [mark for mark in self._stale_marks() if _is_matrix_node(mark.object_id)]
        return tuple(StaleSet(marks))

    def _stale_marks(self) -> tuple[StaleMark, ...]:
        recorded = self._recorded_stale_marks()
        canonical = tuple(
            StaleMark(
                object_id=str(matrix.id),
                reason="the matrix is marked stale in canonical state",
                priority=priority_for(str(matrix.id)),
                source_change=str(matrix.id),
            )
            for matrix in self._ctx.repo.list_matrices()
            if matrix.stale is StaleState.STALE
        )
        return tuple(StaleSet([*recorded, *canonical]))

    def _recorded_stale_marks(self) -> tuple[StaleMark, ...]:
        database = self._ctx.repo.layout.database_file
        if not database.is_file():
            return ()
        engine = create_engine_for(database)
        try:
            with engine.begin() as connection:
                return tuple(load_stale_marks(connection))
        except SQLAlchemyError:
            return ()
        finally:
            engine.dispose()

    # -- reads ---------------------------------------------------------------

    def corpus_works(self) -> tuple[WorkId, ...]:
        """Every Work in the corpus, in id order, so a rebuild reproduces the row order."""
        return tuple(sorted((work.id for work in self._ctx.repo.list_works()), key=str))

    def accepted_evidence(self, works: Sequence[WorkId]) -> tuple[Evidence, ...]:
        """Accepted Evidence for ``works``, in id order; nothing unaccepted is classified."""
        found = [
            item
            for work in works
            for item in self._ctx.repo.iter_evidence(work)
            if item.status is EvidenceStatus.ACCEPTED
        ]
        return tuple(sorted(found, key=lambda item: str(item.id)))

    def _matrix_id_for(self, taxonomy_name: str, field: str) -> SynthesisId:
        """Reuse the matrix already comparing this field under this taxonomy, else a new id."""
        for matrix in sorted(self._ctx.repo.list_matrices(), key=lambda item: str(item.id)):
            if matrix.taxonomy == taxonomy_name and field in matrix.fields:
                return matrix.id
        return next_matrix_id(self._ctx.repo)


def next_matrix_id(repo: WorkspaceRepository) -> SynthesisId:
    """The id the next `synthesis.build_matrix` will write, ids on disk included."""
    on_disk = SynthesisId.next(str(matrix.id) for matrix in repo.list_matrices())
    return SynthesisId.make(max(on_disk.number, repo.config.counter(SynthesisId.prefix) + 1))


def next_decision_id(repo: WorkspaceRepository) -> DecisionId:
    """The id the next `decision.accept` will write, ids on disk included."""
    on_disk = DecisionId.next(str(decision.id) for decision in repo.list_decisions())
    return DecisionId.make(max(on_disk.number, repo.config.counter(DecisionId.prefix) + 1))


def _is_matrix_node(object_id: str) -> bool:
    """True for a matrix id or one of its `<matrix>#<work>#<field>` cell nodes."""
    head = object_id.split(NODE_SEPARATOR)[0]
    try:
        return isinstance(parse_id(head), SynthesisId)
    except DomainValidationError:
        return False


def _evidence_payload(evidence: Evidence) -> dict[str, str | None]:
    """What the synthesizer is shown about one accepted evidence object.

    Its exact text, where it came from, and its epistemic classification - never a prior
    role's rationale, which `build_request` would strip anyway (ADR-003).
    """
    return {
        "id": str(evidence.id),
        "work": str(evidence.source.work),
        "field": evidence.content.field,
        "exact_text": evidence.content.exact_text,
        "origin": evidence.origin.value,
        "evidence_type": evidence.evidence_type.value,
        "strength": evidence.strength.value,
    }

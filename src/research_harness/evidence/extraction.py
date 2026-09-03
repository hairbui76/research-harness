"""Candidate evidence extraction: model proposals turned into anchored staging objects.

The extractor is asked one interrogation field at a time and answers with spans of the
document it was given. Nothing it says is taken on trust:

* the quoted text must equal the block text at the offsets it named, compared after
  `normalize_text`, or the candidate is rejected as a span mismatch;
* the anchor built from those offsets must replay `valid` against the same parse, or the
  candidate is rejected — a candidate with no valid source anchor is invalid (Task 6.1);
* a number must arrive with its metric, dataset or condition, and table provenance, which
  the `NumericValue` domain validator enforces before anything reaches staging (§12);
* `absent` and `researcher_inferred` never survive the role schema, so a model cannot report
  an audited conclusion or a researcher's act as an extraction (§11, §9.1).

Everything that survives is written to `.research/staging/`. This module opens no workspace
transaction and writes no canonical file: an extraction run, however wrong, leaves the
scientific record exactly as it was (ADR-001, ADR-003).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from research_harness.domain.base import Provenance
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import DocumentBlockKind, EvidenceStatus
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    VerificationRecord,
    normalize_label,
)
from research_harness.evidence.interrogation import (
    InterrogationField,
    InterrogationSchema,
    ValueKind,
)
from research_harness.evidence.staging import (
    PROVISIONAL_EVIDENCE_ID,
    CandidateStatus,
    EvidenceCandidate,
    ExtractionProvenance,
    StagingStore,
    candidate_id_for,
)
from research_harness.parsing.anchors import (
    AnchorError,
    AnchorValidationStatus,
    build_anchor,
    validate_anchor,
)
from research_harness.parsing.tables import cell_span
from research_harness.parsing.text import normalize_text
from research_harness.providers.models import BackendInfo, describe_backend
from research_harness.providers.models.base import (
    ModelProvider,
    StructuredOutputError,
)
from research_harness.providers.models.router import ModelRouter
from research_harness.roles.contracts import (
    InputKind,
    RoleContract,
    RoleInput,
    WriteScope,
    assert_can_write,
    build_request,
)
from research_harness.roles.extractor import EXTRACTOR
from research_harness.roles.schemas import EvidenceCandidateOutput, ExtractionOutput

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_BLOCKS_PER_REQUEST",
    "BackendInfo",
    "ExtractionResult",
    "ModelClient",
    "RejectedOutput",
    "backend_label",
    "block_payload",
    "chunk_blocks",
    "extract_candidates",
    "resolve_backend",
    "resolve_labels",
    "salvage_candidates",
]

DEFAULT_MAX_BLOCKS_PER_REQUEST = 60
"""Blocks per request before the document is chunked by section group."""

ModelClient = ModelProvider | ModelRouter
"""Anything that can run a `ModelRequest`: one provider, or a capability router."""


# --------------------------------------------------------------------- backend identity
#
# `providers.models.describe_backend` is the one implementation; the names below are the
# ones this package has always exported and stay importable from here.


def resolve_backend(client: ModelClient, contract: RoleContract) -> BackendInfo:
    """The provider/model a request would go to, without sending it (Product §19.1)."""
    return describe_backend(client, contract)


def backend_label(client: ModelClient, contract: RoleContract) -> str:
    """`provider/model` for the backend `contract` would route to."""
    return describe_backend(client, contract).label


# ------------------------------------------------------------------------- results


@dataclass(frozen=True, slots=True)
class RejectedOutput:
    """One model proposal that did not survive validation, kept for the run report.

    A rejection is a normal, reportable outcome, not an error: the point of staging is that
    a wrong proposal costs nothing. `raw` holds what the model actually said.
    """

    reason: str
    raw: dict[str, Any]
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Everything one extraction produced: candidates, rejections, gaps, and call count."""

    candidates: list[EvidenceCandidate] = field(default_factory=list)
    rejected: list[RejectedOutput] = field(default_factory=list)
    fields_not_found: list[str] = field(default_factory=list)
    requests: int = 0

    @property
    def candidate_ids(self) -> list[str]:
        """Staged candidate ids in the order they were proposed."""
        return [candidate.candidate_id for candidate in self.candidates]

    def by_field(self, name: str) -> list[EvidenceCandidate]:
        """Candidates answering one interrogation field."""
        return [candidate for candidate in self.candidates if candidate.field == name]


# ---------------------------------------------------------------------- role inputs


def block_payload(block: DocumentBlock) -> dict[str, Any]:
    """One block as the extractor sees it: id, page, section path, text — and table cells.

    A table is one block whose text is its flattened rows, so the cell offsets given here are
    exactly the offsets `cell_span` computes: a number quoted from a cell anchors to the
    table block and to the characters of the measured value (§12, §16).
    """
    payload: dict[str, Any] = {
        "block": str(block.id),
        "kind": block.kind.value,
        "page": block.page,
        "section_path": list(block.section_path),
        "text": block.text,
    }
    if block.caption:
        payload["caption"] = block.caption
    if block.kind is DocumentBlockKind.TABLE and block.cells:
        payload["cells"] = [
            {
                "row": cell.row,
                "col": cell.col,
                "text": cell.text,
                "char_start": span[0],
                "char_end": span[1],
            }
            for cell in sorted(block.cells, key=lambda item: (item.row, item.col))
            for span in [cell_span(block, cell.row, cell.col)]
        ]
    return payload


def chunk_blocks(
    blocks: Sequence[DocumentBlock], max_blocks: int = DEFAULT_MAX_BLOCKS_PER_REQUEST
) -> list[list[DocumentBlock]]:
    """Split a document into request-sized groups without splitting a section where possible.

    Sections are kept whole because a claim and the sentence that qualifies it usually live
    in the same one; only a section larger than `max_blocks` is cut, and then in reading
    order so the surviving pieces are still contiguous.
    """
    if max_blocks < 1:
        raise ValueError("max_blocks_per_request must be at least 1")
    groups: list[list[DocumentBlock]] = []
    for block in blocks:
        if groups and groups[-1][-1].section_path == block.section_path:
            groups[-1].append(block)
        else:
            groups.append([block])

    chunks: list[list[DocumentBlock]] = []
    current: list[DocumentBlock] = []
    for group in groups:
        for start in range(0, len(group), max_blocks):
            piece = group[start : start + max_blocks]
            if current and len(current) + len(piece) > max_blocks:
                chunks.append(current)
                current = []
            current.extend(piece)
    if current:
        chunks.append(current)
    return chunks


def _field_payload(item: InterrogationField, schema: InterrogationSchema) -> dict[str, Any]:
    return {
        "schema": f"{schema.name}@{schema.version}",
        "field": item.name,
        "question": item.question,
        "value_kind": item.value_kind.value,
        "evidence_types": [kind.value for kind in item.evidence_types],
        "categories": list(item.categories),
        "required": item.required,
    }


def _role_inputs(
    doc: ParsedDocument,
    blocks: Sequence[DocumentBlock],
    item: InterrogationField,
    schema: InterrogationSchema,
) -> list[RoleInput]:
    return [
        RoleInput(
            kind=InputKind.INTERROGATION_SCHEMA,
            object_id=f"{schema.name}@{schema.version}",
            content=_field_payload(item, schema),
        ),
        RoleInput(
            kind=InputKind.DOCUMENT_BLOCKS,
            object_id=str(doc.artifact),
            content={"artifact": str(doc.artifact), "blocks": [block_payload(b) for b in blocks]},
        ),
    ]


# -------------------------------------------------------------------------- extraction


def extract_candidates(
    doc: ParsedDocument,
    schema: InterrogationSchema,
    provider: ModelClient,
    *,
    run_id: str,
    fields: Sequence[str] | None = None,
    max_blocks_per_request: int = DEFAULT_MAX_BLOCKS_PER_REQUEST,
    staging: StagingStore | None = None,
) -> ExtractionResult:
    """Ask the extractor for each requested field and stage every candidate that validates.

    One request per (field, block chunk): a field is answered from the whole document but
    never mixed with another field's question, so re-running one field is a self-contained
    unit of work (§19.1). Passing `staging` writes the surviving candidates; without it the
    result is returned and nothing is persisted.
    """
    assert_can_write(EXTRACTOR, WriteScope.STAGING_EVIDENCE)

    requested = schema.select(list(fields) if fields is not None else None)
    chunks = chunk_blocks(doc.blocks, max_blocks_per_request)
    candidates: list[EvidenceCandidate] = []
    rejected: list[RejectedOutput] = []
    not_found: set[str] = set()
    requests = 0

    for item in requested:
        for blocks in chunks:
            built = build_request(EXTRACTOR, _role_inputs(doc, blocks, item, schema))
            if built.stripped_fields:  # pragma: no cover - our own inputs carry no reasoning
                logger.warning(
                    "dropped hidden-reasoning fields from an extraction request: %s",
                    ", ".join(built.stripped_fields),
                )
            requests += 1
            fingerprint = built.request.fingerprint()
            try:
                response = provider.complete(built.request)
            except StructuredOutputError as exc:
                proposals, salvage_rejections = salvage_candidates(exc, field=item.name)
                rejected.extend(salvage_rejections)
                backend = resolve_backend(provider, EXTRACTOR)
                answers = proposals
            else:
                output = response.parsed
                if not isinstance(output, ExtractionOutput):  # pragma: no cover - schema is fixed
                    raise TypeError(
                        f"extractor returned {type(output).__name__}, not ExtractionOutput"
                    )
                not_found.update(name for name in output.fields_not_found if name == item.name)
                backend = BackendInfo(provider=response.provider, model=response.model)
                answers = list(output.candidates)
                fingerprint = response.request_fingerprint
            for proposal in answers:
                outcome = _build_candidate(
                    proposal,
                    doc,
                    item,
                    schema,
                    backend,
                    run_id=run_id,
                    request_fingerprint=fingerprint,
                )
                if isinstance(outcome, RejectedOutput):
                    rejected.append(outcome)
                else:
                    candidates.append(outcome)

    answered = {candidate.field for candidate in candidates}
    if staging is not None:
        staging.put_all(candidates)
    return ExtractionResult(
        candidates=candidates,
        rejected=rejected,
        fields_not_found=sorted(not_found - answered),
        requests=requests,
    )


def resolve_labels(
    proposed: Sequence[str], item: InterrogationField
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Match proposed labels to the field's declared categories; return the kept and the rest.

    A categorical answer carried no category at all, so the label was re-derived by keyword
    rules long afterwards (dogfood F13). A label is kept only when the schema declares it,
    compared under `normalize_label` so `raw_sequential`, `raw sequential` and
    `Raw Sequential` are the one category the schema spells one way. The declared spelling
    is what is stored; a field that declares no categories accepts no labels.
    """
    declared = {normalize_label(name): name for name in item.categories}
    kept: list[str] = []
    unknown: list[str] = []
    for name in proposed:
        match = declared.get(normalize_label(name))
        if match is None:
            unknown.append(name)
        elif match not in kept:
            kept.append(match)
    return tuple(kept), tuple(unknown)


def salvage_candidates(
    error: StructuredOutputError, *, field: str
) -> tuple[list[EvidenceCandidateOutput], list[RejectedOutput]]:
    """Recover the candidates of a reply that failed whole-object validation (dogfood F18).

    `ExtractionOutput` validates all-or-nothing per (field, chunk), so one malformed
    `rationale` threw away the two valid candidates beside it -- routine, and expensive,
    with a real model. The provider contract is unchanged: it still refuses to return a
    partial object, because unvalidated model text must never be mistaken for a result.
    This is the extraction layer re-reading that refused text *candidate by candidate*,
    validating each against the same schema and recording the ones that fail as ordinary
    rejections, which is exactly what `RejectedOutput` is for.

    Anything that is not a JSON object with a `candidates` list is not salvageable, and the
    whole reply is reported as one rejection, as before.
    """
    raw_text = error.raw_text or ""
    try:
        body = json.loads(raw_text)
    except ValueError:
        return [], [_whole_reply_rejection(error, field=field, raw_text=raw_text)]
    if not isinstance(body, dict) or not isinstance(body.get("candidates"), list):
        return [], [_whole_reply_rejection(error, field=field, raw_text=raw_text)]

    proposals: list[EvidenceCandidateOutput] = []
    rejected: list[RejectedOutput] = []
    for entry in body["candidates"]:
        try:
            proposals.append(EvidenceCandidateOutput.model_validate(entry))
        except ValidationError as exc:
            raw = entry if isinstance(entry, dict) else {"value": entry}
            named = raw.get("field") if isinstance(raw.get("field"), str) else field
            rejected.append(
                RejectedOutput(reason=f"invalid candidate: {exc}", raw=raw, field=named)
            )
    if not proposals and not rejected:
        return [], [_whole_reply_rejection(error, field=field, raw_text=raw_text)]
    logger.info(
        "recovered %d of %d candidate(s) from an extraction reply that failed validation",
        len(proposals),
        len(proposals) + len(rejected),
    )
    return proposals, rejected


def _whole_reply_rejection(
    error: StructuredOutputError, *, field: str, raw_text: str
) -> RejectedOutput:
    """The pre-existing all-or-nothing rejection, for a reply with no candidates to recover."""
    return RejectedOutput(
        reason=f"invalid structured output: {error.message}",
        raw={"raw_text": raw_text},
        field=field,
    )


def _build_candidate(
    proposal: EvidenceCandidateOutput,
    doc: ParsedDocument,
    item: InterrogationField,
    schema: InterrogationSchema,
    backend: BackendInfo,
    *,
    run_id: str,
    request_fingerprint: str,
) -> EvidenceCandidate | RejectedOutput:
    """Validate one proposal against the source and turn it into a staged candidate."""
    raw = proposal.model_dump(mode="json")

    def reject(reason: str) -> RejectedOutput:
        return RejectedOutput(reason=reason, raw=raw, field=proposal.field)

    if proposal.field != item.name:
        return reject(f"answered field {proposal.field!r} while asked about {item.name!r}")
    if not item.allows(proposal.evidence_type):
        allowed = ", ".join(sorted(kind.value for kind in item.evidence_types))
        return reject(
            f"evidence type {proposal.evidence_type.value!r} is not allowed for field "
            f"{item.name!r} (allowed: {allowed})"
        )
    wants_number = item.value_kind is ValueKind.NUMERIC and proposal.negative_state is None
    if wants_number and proposal.numeric is None:
        return reject(f"field {item.name!r} expects a measured value with its provenance")
    labels, unknown = resolve_labels(proposal.labels, item)
    if unknown:
        declared = ", ".join(item.categories) or "none"
        return reject(
            f"label(s) {', '.join(repr(name) for name in unknown)} are not categories of field "
            f"{item.name!r} (declared: {declared})"
        )

    block = next((entry for entry in doc.blocks if str(entry.id) == proposal.block), None)
    if block is None:
        return reject(f"block {proposal.block!r} is not part of this document")

    start, end = _span_of(proposal, block)
    if end > len(block.text):
        return reject(
            f"span [{start}, {end}) exceeds block {block.id} ({len(block.text)} characters)"
        )
    if proposal.negative_state is None and normalize_text(proposal.exact_text) != normalize_text(
        block.text[start:end]
    ):
        return reject("span mismatch")

    try:
        anchor = build_anchor(doc, block, start, end)
    except AnchorError as exc:
        return reject(f"anchor could not be built: {exc}")
    validation = validate_anchor(anchor, doc)
    if validation.status is not AnchorValidationStatus.VALID:
        return reject(f"anchor is {validation.status.value}: {validation.reason}")

    try:
        evidence = Evidence(
            id=PROVISIONAL_EVIDENCE_ID,
            source=anchor,
            content=EvidenceContent(
                exact_text=proposal.exact_text,
                numeric=proposal.numeric,
                negative_state=proposal.negative_state,
                field=item.name,
                labels=labels,
            ),
            origin=proposal.origin,
            evidence_type=proposal.evidence_type,
            strength=proposal.strength,
            verification=VerificationRecord(
                status=EvidenceStatus.PROPOSED, extractor=backend.label
            ),
            review_tier=item.review_tier,
            provenance=Provenance.model(
                actor=backend.label,
                workflow="interrogate",
                run_id=run_id,
                template_version=EXTRACTOR.template_version,
            ),
        )
    except (ValidationError, DomainValidationError, ValueError) as exc:
        return reject(f"invalid evidence: {exc}")

    return EvidenceCandidate(
        candidate_id=candidate_id_for(
            block.work,
            block.artifact,
            item.name,
            block.id,
            start,
            end,
            anchor.text_hash,
            proposal.negative_state.value if proposal.negative_state else "",
        ),
        work=block.work,
        artifact=block.artifact,
        field=item.name,
        evidence=evidence,
        extraction=ExtractionProvenance(
            run_id=run_id,
            provider=backend.provider,
            model=backend.model,
            template_version=EXTRACTOR.template_version,
            request_fingerprint=request_fingerprint,
            response_schema_fingerprint=ExtractionOutput.json_schema_fingerprint(),
            rationale=proposal.rationale,
        ),
        anchor_status=validation.status,
        status=CandidateStatus.PROPOSED,
    )


def _span_of(proposal: EvidenceCandidateOutput, block: DocumentBlock) -> tuple[int, int]:
    """The character span a proposal names; an absence record anchors the whole block."""
    if proposal.char_start is None or proposal.char_end is None:
        return 0, len(block.text)
    return proposal.char_start, proposal.char_end

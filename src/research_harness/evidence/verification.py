"""Independent verification: a second reader, given the source and the candidate only.

Agreement between extraction and verification carries information only when the second reader
did not see the first one's reasoning, so `build_source_context` hands the verifier the
anchored block and its neighbours plus the candidate's exact text, field, number, and absence
state — and nothing else. The extractor's rationale, its origin/type/strength judgements, and
its provenance stay behind (ADR-003, Product §43). `RoleContract` enforces the same rule from
the other side: the verifier's contract does not list the inputs that would carry them.

One check is deterministic rather than delegated. A verdict of `supported` or
`partially_supported` must quote a span that actually occurs in the context the verifier was
given; when it does not, the verdict is downgraded to `insufficient_evidence` with a recorded
discrepancy. That is the concrete form of "a paper name or a dataset name alone cannot
establish a property the source does not state" (Task 6.2): a model that recognises
`CICIDS2017` and answers from memory produces a quote the source does not contain, and the
guard catches it without asking another model.
"""

from __future__ import annotations

import logging
from typing import Any

from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import DocumentBlockKind, VerificationVerdict
from research_harness.evidence.extraction import ModelClient, block_payload, resolve_backend
from research_harness.evidence.staging import EvidenceCandidate, apply_verification
from research_harness.parsing.text import normalize_text
from research_harness.roles.contracts import (
    InputKind,
    RoleInput,
    WriteScope,
    assert_can_write,
    build_request,
)
from research_harness.roles.schemas import VerificationOutput
from research_harness.roles.verifier import VERIFIER

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_NEIGHBOURS",
    "QUOTE_NOT_IN_SOURCE",
    "SUPPORTING_VERDICTS",
    "build_source_context",
    "candidate_payload",
    "context_blocks",
    "enforce_quoted_support",
    "verify_candidate",
]

DEFAULT_NEIGHBOURS = 1
"""Blocks of context on each side of the anchored one, in reading order."""

QUOTE_NOT_IN_SOURCE = "quoted support not found in source context"
"""Discrepancy recorded when a supporting verdict quotes text the source does not contain."""

SUPPORTING_VERDICTS: frozenset[VerificationVerdict] = frozenset(
    {VerificationVerdict.SUPPORTED, VerificationVerdict.PARTIALLY_SUPPORTED}
)
"""Verdicts that assert the source establishes the candidate, and so require a real quote."""


def candidate_payload(candidate: EvidenceCandidate) -> dict[str, Any]:
    """What the verifier learns about the candidate: the assertion, never its author.

    Deliberately excludes `extraction.rationale`, the extractor's origin/type/strength
    judgements, its provenance, and the review tier. The verifier decides from the span.
    """
    content = candidate.evidence.content
    anchor = candidate.evidence.source
    payload: dict[str, Any] = {
        "field": candidate.field,
        "exact_text": content.exact_text,
        "block": str(anchor.block),
        "page": anchor.page,
        "char_start": anchor.char_start,
        "char_end": anchor.char_end,
    }
    if content.numeric is not None:
        payload["numeric"] = content.numeric.model_dump(mode="json")
    if content.negative_state is not None:
        payload["negative_state"] = content.negative_state.value
    return payload


def context_blocks(
    doc: ParsedDocument, candidate: EvidenceCandidate, *, neighbors: int = DEFAULT_NEIGHBOURS
) -> list[DocumentBlock]:
    """The anchored block and `neighbors` blocks either side of it, in reading order.

    Neighbours are included because a sentence is often qualified by the one before or after
    it, and a verifier that cannot see the qualification will over-report support.
    """
    if neighbors < 0:
        raise ValueError("neighbors must not be negative")
    blocks = list(doc.blocks)
    index = next(
        (
            position
            for position, block in enumerate(blocks)
            if block.id == candidate.evidence.source.block
        ),
        None,
    )
    if index is None:
        return []
    start = max(0, index - neighbors)
    return blocks[start : index + neighbors + 1]


def build_source_context(
    doc: ParsedDocument, candidate: EvidenceCandidate, *, neighbors: int = DEFAULT_NEIGHBOURS
) -> list[RoleInput]:
    """The verifier's whole world: one candidate assertion and the source spans around it.

    Table blocks keep their cells, so a number can be checked against its row, column, and
    header rather than against a flattened string (§12).
    """
    blocks = context_blocks(doc, candidate, neighbors=neighbors)
    return [
        RoleInput(
            kind=InputKind.CANDIDATE_EVIDENCE,
            object_id=candidate.candidate_id,
            content=candidate_payload(candidate),
        ),
        RoleInput(
            kind=InputKind.DOCUMENT_BLOCKS,
            object_id=str(candidate.artifact),
            content={
                "artifact": str(candidate.artifact),
                "blocks": [block_payload(block) for block in blocks],
            },
        ),
    ]


def enforce_quoted_support(
    output: VerificationOutput, blocks: list[DocumentBlock]
) -> VerificationOutput:
    """Downgrade a supporting verdict whose quote does not occur in the supplied context.

    Comparison is on normalized text, so line wrapping, ligatures, and collapsed whitespace do
    not cause a false alarm; recognising a name and answering from memory still does.
    """
    if output.verdict not in SUPPORTING_VERDICTS:
        return output
    quote = normalize_text(output.quoted_support or "")
    haystack = "\n".join(normalize_text(_context_text(block)) for block in blocks)
    if quote and quote in haystack:
        return output
    logger.info(
        "downgrading %s to insufficient_evidence: %s", output.verdict.value, QUOTE_NOT_IN_SOURCE
    )
    return output.model_copy(
        update={
            "verdict": VerificationVerdict.INSUFFICIENT_EVIDENCE,
            "discrepancies": [*output.discrepancies, QUOTE_NOT_IN_SOURCE],
        }
    )


def verify_candidate(
    candidate: EvidenceCandidate,
    doc: ParsedDocument,
    provider: ModelClient,
    *,
    neighbors: int = DEFAULT_NEIGHBOURS,
) -> EvidenceCandidate:
    """Verify one candidate against its source spans and return the verified candidate.

    Returns a new object; persisting it is the caller's job, and no canonical file is written
    here or anywhere downstream of here. A verified candidate is still a candidate.
    """
    assert_can_write(VERIFIER, WriteScope.VERIFICATION_RESULT)
    blocks = context_blocks(doc, candidate, neighbors=neighbors)
    built = build_request(VERIFIER, build_source_context(doc, candidate, neighbors=neighbors))
    if built.stripped_fields:  # pragma: no cover - the payload carries no reasoning fields
        logger.warning(
            "dropped hidden-reasoning fields from a verification request: %s",
            ", ".join(built.stripped_fields),
        )
    response = provider.complete(built.request)
    output = response.parsed
    if not isinstance(output, VerificationOutput):  # pragma: no cover - schema is fixed
        raise TypeError(f"verifier returned {type(output).__name__}, not VerificationOutput")
    checked = enforce_quoted_support(output, blocks)
    backend = resolve_backend(provider, VERIFIER)
    verifier = f"{response.provider}/{response.model}" if response.provider else backend.label
    return apply_verification(candidate, checked, verifier)


def _context_text(block: DocumentBlock) -> str:
    """Everything of a block a quote may legitimately come from, cells included."""
    if block.kind is DocumentBlockKind.TABLE and block.cells:
        cells = " ".join(cell.text for cell in block.cells)
        return f"{block.text}\n{cells}\n{block.caption or ''}"
    return f"{block.text}\n{block.caption or ''}" if block.caption else block.text

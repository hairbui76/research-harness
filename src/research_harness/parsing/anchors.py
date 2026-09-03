"""Evidence anchors: build, fingerprint, validate, and resolve (Product 9, 16; ADR-008).

An anchor is the promise that a piece of evidence can be reopened at the exact bytes it
was accepted from. Validation therefore never repairs an anchor. When the artifact bytes
differ it reports `stale` and stops; when a re-parse renumbered blocks it reports the
block it *would* match and leaves the rewrite to the caller, who is accountable for it.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from research_harness.domain.base import DomainModel, NonEmptyStr, Sha256
from research_harness.domain.document import BoundingBox, DocumentBlock, ParsedDocument
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.evidence import SourceAnchor
from research_harness.domain.ids import BlockId
from research_harness.parsing.base import document_file_hash
from research_harness.parsing.text import text_sha256

__all__ = [
    "AnchorError",
    "AnchorValidationResult",
    "AnchorValidationStatus",
    "ResolvedSpan",
    "anchor_fingerprint",
    "build_anchor",
    "resolve_anchor",
    "validate_anchor",
]


class AnchorError(ResearchHarnessError):
    """An anchor could not be built or resolved against the document it names."""


class AnchorValidationStatus(StrEnum):
    """Outcome of replaying an anchor against a parsed document (Roadmap Task 2.4)."""

    VALID = "valid"
    STALE = "stale"
    MISSING = "missing"


class AnchorValidationResult(DomainModel):
    """Why an anchor is valid, stale, or missing, and what it would match.

    `matched_block` is set only on `valid`. When it differs from ``anchor.block`` a
    re-parse renumbered the blocks and the caller must decide whether to rewrite the
    anchor; nothing here rewrites it.
    """

    status: AnchorValidationStatus
    reason: NonEmptyStr
    anchor: SourceAnchor
    matched_block: BlockId | None = None
    exact_text: str | None = None

    @property
    def is_valid(self) -> bool:
        """True when the anchor still resolves to its source span."""
        return self.status is AnchorValidationStatus.VALID

    @property
    def renumbered(self) -> bool:
        """True when the anchor resolves only through a different block id."""
        return (
            self.is_valid
            and self.matched_block is not None
            and self.matched_block != self.anchor.block
        )


class ResolvedSpan(DomainModel):
    """Where an anchor points right now: page, geometry, and the exact text."""

    block: BlockId
    page: int
    bbox: BoundingBox | None
    text: str


def _document_hash(doc: ParsedDocument, file_hash: Sha256 | None) -> Sha256:
    """The hash to compare an anchor against: the caller's override, else `doc.file_hash`.

    The override is kept so a caller replaying against bytes it hashed itself can say so.
    """
    return file_hash if file_hash is not None else document_file_hash(doc)


def _span_text(anchor: SourceAnchor, block: DocumentBlock) -> str:
    if anchor.char_start is None or anchor.char_end is None:
        return block.text
    return block.text[anchor.char_start : anchor.char_end]


def _offsets_fit(anchor: SourceAnchor, block: DocumentBlock) -> bool:
    if anchor.char_start is None or anchor.char_end is None:
        return True
    return anchor.char_end <= len(block.text)


def build_anchor(
    doc: ParsedDocument,
    block: DocumentBlock,
    char_start: int,
    char_end: int,
    *,
    file_hash: Sha256 | None = None,
) -> SourceAnchor:
    """Anchor a character span of ``block`` to the artifact bytes ``doc`` was parsed from.

    Offsets are validated against the block text, so an anchor can never be created for a
    span the source does not contain. ``file_hash`` overrides ``doc.file_hash``.
    """
    if all(candidate.id != block.id for candidate in doc.blocks):
        raise AnchorError(f"block {block.id} does not belong to the parsed document")
    if char_start < 0 or char_end < char_start:
        raise AnchorError(f"invalid character span [{char_start}, {char_end})")
    if char_end > len(block.text):
        raise AnchorError(
            f"character span [{char_start}, {char_end}) exceeds block {block.id} "
            f"({len(block.text)} characters)"
        )
    return SourceAnchor(
        work=block.work,
        version=block.version,
        artifact=block.artifact,
        file_hash=_document_hash(doc, file_hash),
        block=block.id,
        text_hash=block.text_hash,
        page=block.page,
        section_path=block.section_path,
        char_start=char_start,
        char_end=char_end,
        bbox=block.bbox,
    )


def anchor_fingerprint(anchor: SourceAnchor) -> Sha256:
    """Stable hash over artifact hash, page, block, text hash, offsets, and bbox (ADR-002).

    Identity only: work/version ids are excluded so the fingerprint follows the bytes, not
    the catalogue.
    """
    payload: dict[str, Any] = {
        "file_hash": anchor.file_hash,
        "page": anchor.page,
        "block": str(anchor.block),
        "text_hash": anchor.text_hash,
        "char_start": anchor.char_start,
        "char_end": anchor.char_end,
        "bbox": None if anchor.bbox is None else list(anchor.bbox.as_tuple()),
    }
    return text_sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def validate_anchor(
    anchor: SourceAnchor,
    doc: ParsedDocument,
    *,
    file_hash: Sha256 | None = None,
) -> AnchorValidationResult:
    """Replay ``anchor`` against ``doc`` and report `valid`, `stale`, or `missing`.

    A different artifact hash ends the check immediately: changed bytes make the anchor
    stale and reattachment is never attempted (ADR-002, ADR-008).
    """

    def result(
        status: AnchorValidationStatus,
        reason: str,
        *,
        block: DocumentBlock | None = None,
    ) -> AnchorValidationResult:
        return AnchorValidationResult(
            status=status,
            reason=reason,
            anchor=anchor,
            matched_block=None if block is None else block.id,
            exact_text=None if block is None else _span_text(anchor, block),
        )

    document_hash = _document_hash(doc, file_hash)
    if document_hash != anchor.file_hash:
        return result(
            AnchorValidationStatus.STALE,
            f"artifact bytes changed: anchor was taken from {anchor.file_hash}, "
            f"document was parsed from {document_hash}",
        )
    if anchor.artifact != doc.artifact:
        return result(
            AnchorValidationStatus.STALE,
            f"anchor points at artifact {anchor.artifact}, document parses {doc.artifact}",
        )
    if anchor.page is not None and anchor.page > doc.page_count:
        return result(
            AnchorValidationStatus.MISSING,
            f"page {anchor.page} is beyond the {doc.page_count} pages of this document",
        )

    def on_anchor_page(block: DocumentBlock) -> bool:
        return block.text_hash == anchor.text_hash and (
            anchor.page is None or block.page == anchor.page
        )

    named = next((block for block in doc.blocks if block.id == anchor.block), None)
    if named is not None and on_anchor_page(named):
        if not _offsets_fit(anchor, named):
            return result(
                AnchorValidationStatus.STALE,
                f"character span [{anchor.char_start}, {anchor.char_end}) falls outside "
                f"block {named.id}",
            )
        return result(
            AnchorValidationStatus.VALID,
            "block id, page, and text hash all match",
            block=named,
        )
    candidate = next((block for block in doc.blocks if on_anchor_page(block)), None)
    if candidate is not None:
        if not _offsets_fit(anchor, candidate):
            return result(
                AnchorValidationStatus.STALE,
                f"character span [{anchor.char_start}, {anchor.char_end}) falls outside "
                f"block {candidate.id}",
            )
        return result(
            AnchorValidationStatus.VALID,
            f"block id changed from {anchor.block} to {candidate.id}; text hash unchanged "
            "on the same page, so the anchor needs explicit reconciliation",
            block=candidate,
        )
    moved = next((block for block in doc.blocks if block.text_hash == anchor.text_hash), None)
    if moved is not None:
        return result(
            AnchorValidationStatus.STALE,
            f"anchored text now appears on page {moved.page}, not page {anchor.page}",
        )
    return result(
        AnchorValidationStatus.STALE,
        f"no block in this parse carries text hash {anchor.text_hash}",
    )


def resolve_anchor(
    anchor: SourceAnchor,
    doc: ParsedDocument,
    *,
    file_hash: Sha256 | None = None,
) -> ResolvedSpan:
    """Resolve a persisted anchor back to its exact page and span (Gate P2).

    Raises `AnchorError` when the anchor is stale or missing: a caller must never receive
    a span that is not the one the evidence was accepted from.
    """
    outcome = validate_anchor(anchor, doc, file_hash=file_hash)
    if outcome.status is not AnchorValidationStatus.VALID or outcome.matched_block is None:
        raise AnchorError(f"anchor is {outcome.status.value}: {outcome.reason}")
    block = next(candidate for candidate in doc.blocks if candidate.id == outcome.matched_block)
    return ResolvedSpan(
        block=block.id,
        page=block.page,
        bbox=block.bbox,
        text=_span_text(anchor, block),
    )

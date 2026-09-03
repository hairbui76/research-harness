"""Artifact parsing and evidence anchoring: the document IR and its replayable anchors.

Parsing turns immutable artifact bytes into a structural `ParsedDocument` (Product 16);
anchoring binds a character span of one block to those exact bytes so evidence can be
reopened, or reported stale, later (ADR-002, ADR-008). Nothing in this package writes.
"""

from __future__ import annotations

from research_harness.parsing.anchors import (
    AnchorError,
    AnchorValidationResult,
    AnchorValidationStatus,
    ResolvedSpan,
    anchor_fingerprint,
    build_anchor,
    resolve_anchor,
    validate_anchor,
)
from research_harness.parsing.base import (
    BlockIdAllocator,
    BlockQuality,
    DocumentParser,
    ParseDiagnostics,
    ParseError,
    ParseTarget,
    UnsupportedArtifactError,
    diagnostics_summary,
    document_diagnostics,
    document_file_hash,
    document_fingerprint,
    parse_provenance,
    select_parser,
)
from research_harness.parsing.pymupdf_parser import PDF_MIME_TYPES, PyMuPdfParser
from research_harness.parsing.quality import (
    assess_text,
    detect_offset,
    english_score,
    shift_text,
    word_is_plausible,
)
from research_harness.parsing.tables import (
    CELL_SEPARATOR,
    ROW_SEPARATOR,
    cell_span,
    cell_text,
    column_headers,
    find_cell,
    flatten_cells,
    row_label,
)
from research_harness.parsing.text import normalize_text, text_sha256

__all__ = [
    "CELL_SEPARATOR",
    "PDF_MIME_TYPES",
    "ROW_SEPARATOR",
    "AnchorError",
    "AnchorValidationResult",
    "AnchorValidationStatus",
    "BlockIdAllocator",
    "BlockQuality",
    "DocumentParser",
    "ParseDiagnostics",
    "ParseError",
    "ParseTarget",
    "PyMuPdfParser",
    "ResolvedSpan",
    "UnsupportedArtifactError",
    "anchor_fingerprint",
    "assess_text",
    "build_anchor",
    "cell_span",
    "cell_text",
    "column_headers",
    "detect_offset",
    "diagnostics_summary",
    "document_diagnostics",
    "document_file_hash",
    "document_fingerprint",
    "english_score",
    "find_cell",
    "flatten_cells",
    "normalize_text",
    "parse_provenance",
    "resolve_anchor",
    "row_label",
    "select_parser",
    "shift_text",
    "text_sha256",
    "validate_anchor",
    "word_is_plausible",
]

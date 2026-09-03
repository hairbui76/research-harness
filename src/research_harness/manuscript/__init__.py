"""Manuscript layer: LaTeX parsing, sentence anchors, citation support, and the auditor.

The manuscript is downstream of the accepted research graph (Product 30), and this package
reads it in two passes. The structural pass answers what is written - which sentences
exist, where they are, what they cite, which spans a style pass must preserve, and whether
an anchor still resolves (:mod:`~research_harness.manuscript.latex`,
:mod:`~research_harness.manuscript.anchors`,
:mod:`~research_harness.manuscript.protected`,
:mod:`~research_harness.manuscript.bibtex`,
:mod:`~research_harness.manuscript.citations`). The epistemic pass answers whether it is
defensible - whether a cited work actually supports the attached Claim, whether a number
still means what the source measured, and how strong the sentence reads on the claim scope
ladder (:mod:`~research_harness.manuscript.support`,
:mod:`~research_harness.manuscript.wording`), which
:mod:`~research_harness.manuscript.audit` assembles into the Product 30.3 finding list plus
the sentence -> Claim -> Evidence -> page-span trace of Product 30.1.

Since Phase 21 the package also *writes* manuscript files - and only in the two ways a
researcher can see. :mod:`~research_harness.manuscript.files` saves a file the caller
names, with the hash it believed it was editing, and refuses when somebody else changed it
first. :mod:`~research_harness.manuscript.suggest` turns a model or humanizer rewrite into
a staged candidate diff under `.research/staging/manuscript/` and applies it only through
an explicit, audited acceptance. There is no third path: no function here edits prose on
the harness's own initiative, and a candidate whose protected spans moved, whose
propositions moved, or whose wording outruns its anchored Claim is refused rather than
merged (Product 30.4, 42.L; LaTeX spec 4).

Compilation is the other addition and is deliberately not an edit at all:
:mod:`~research_harness.manuscript.toolchain` finds an engine already on `PATH`,
:mod:`~research_harness.manuscript.compile` runs it in a bounded, confined process writing
only into `.research/build/`, :mod:`~research_harness.manuscript.synctex` reads back the
map it produced, and :mod:`~research_harness.manuscript.workspace` composes all of it into
one view in which the compiler's diagnostics and the scientific audit's findings stay two
different lists.

Nothing here repairs a finding, and no write happens without the caller naming the file and
the version: citation existence is never treated as evidence support, an unresolved one is
reported for a researcher rather than papered over, and a stale anchor is never quietly
reattached (Product 30.2, ADR-008).
"""

from __future__ import annotations

from research_harness.manuscript.anchors import (
    STALE_SIMILARITY_THRESHOLD,
    AnchorRevalidation,
    anchor_key,
    apply_revalidation,
    build_anchor,
    revalidate_all,
    revalidate_anchor,
)
from research_harness.manuscript.attach import (
    BIBLIOGRAPHY_FILENAME,
    DEFAULT_MAIN_TEX,
    ManuscriptError,
    ManuscriptService,
    RevalidationReport,
    SentenceRef,
)
from research_harness.manuscript.audit import (
    CLAIM_VERBS_PATTERN,
    MIN_SUBSTANTIVE_WORDS,
    QUESTIONABLE_CLAIM_STATUSES,
    AuditContext,
    ManuscriptAuditReport,
    TraceLink,
    audit_manuscript,
    is_substantive,
)
from research_harness.manuscript.bibtex import (
    MONTH_MACROS,
    BibDatabase,
    BibEntry,
    BibtexError,
    parse_bibtex,
    parse_bibtex_file,
)
from research_harness.manuscript.citations import (
    CitationClosureReport,
    MissingCitation,
    citation_closure,
    findings_for_missing,
)
from research_harness.manuscript.draft import (
    DRAFT_SUFFIX,
    NEEDS_SOURCE,
    STAGING_DRAFTS_DIRNAME,
    DraftCandidate,
    draft_section,
    staged_draft,
)
from research_harness.manuscript.latex import (
    BLOCK_ENVIRONMENTS,
    Block,
    BlockKind,
    Heading,
    LatexError,
    LatexFile,
    LatexProject,
    Sentence,
    citation_keys,
    normalize_sentence,
    sentence_fingerprint,
    strip_comments,
)
from research_harness.manuscript.protected import (
    ProtectedSpan,
    ProtectedSpanKind,
    find_protected_spans,
)
from research_harness.manuscript.support import (
    CITATION_MISMATCH_STATUSES,
    SUPPORTING_RELATIONS,
    BibWorkMap,
    CitationKeyCheck,
    CitationStatus,
    CitationSupportReport,
    NumberMention,
    NumericCheck,
    NumericStatus,
    canonical_unit,
    citation_support,
    match_bib_to_works,
    numbers_in_sentence,
    numeric_support,
)
from research_harness.manuscript.wording import (
    CUE_TABLE,
    HEDGE_CUES,
    WordingEstimate,
    stronger_than,
    wording_level,
)

__all__ = [
    "BIBLIOGRAPHY_FILENAME",
    "BLOCK_ENVIRONMENTS",
    "CITATION_MISMATCH_STATUSES",
    "CLAIM_VERBS_PATTERN",
    "CUE_TABLE",
    "DEFAULT_MAIN_TEX",
    "DRAFT_SUFFIX",
    "HEDGE_CUES",
    "MIN_SUBSTANTIVE_WORDS",
    "MONTH_MACROS",
    "NEEDS_SOURCE",
    "QUESTIONABLE_CLAIM_STATUSES",
    "STAGING_DRAFTS_DIRNAME",
    "STALE_SIMILARITY_THRESHOLD",
    "SUPPORTING_RELATIONS",
    "AnchorRevalidation",
    "AuditContext",
    "BibDatabase",
    "BibEntry",
    "BibWorkMap",
    "BibtexError",
    "Block",
    "BlockKind",
    "CitationClosureReport",
    "CitationKeyCheck",
    "CitationStatus",
    "CitationSupportReport",
    "DraftCandidate",
    "Heading",
    "LatexError",
    "LatexFile",
    "LatexProject",
    "ManuscriptAuditReport",
    "ManuscriptError",
    "ManuscriptService",
    "MissingCitation",
    "NumberMention",
    "NumericCheck",
    "NumericStatus",
    "ProtectedSpan",
    "ProtectedSpanKind",
    "RevalidationReport",
    "Sentence",
    "SentenceRef",
    "TraceLink",
    "WordingEstimate",
    "anchor_key",
    "apply_revalidation",
    "audit_manuscript",
    "build_anchor",
    "canonical_unit",
    "citation_closure",
    "citation_keys",
    "citation_support",
    "draft_section",
    "find_protected_spans",
    "findings_for_missing",
    "is_substantive",
    "match_bib_to_works",
    "normalize_sentence",
    "numbers_in_sentence",
    "numeric_support",
    "parse_bibtex",
    "parse_bibtex_file",
    "revalidate_all",
    "revalidate_anchor",
    "sentence_fingerprint",
    "staged_draft",
    "strip_comments",
    "stronger_than",
    "wording_level",
]

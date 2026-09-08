"""Citation closure: every cited key must exist in the bibliography (Product 30.2).

Closure is the cheap half of the citation policy and it answers exactly one question: does
the key resolve? **Citation existence is not evidence support.** A key that parses, exists,
and renders can still fail to support the sentence it decorates; deciding that is a
separate, later step that consumes accepted Claim-Evidence relations (ROADMAP Task 9.3) and
reports its own findings. Nothing in this module should ever be read as support.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from research_harness.domain.enums import FindingSeverity, ManuscriptFindingKind
from research_harness.domain.manuscript import ManuscriptAuditFinding
from research_harness.manuscript.bibtex import BibDatabase
from research_harness.manuscript.latex import LatexProject, Sentence

__all__ = [
    "CitationClosureReport",
    "MissingCitation",
    "citation_closure",
    "findings_for_missing",
]


class MissingCitation(BaseModel):
    """One cited key with no bibliography entry, with the sentence that cites it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    sentence: Sentence


class CitationClosureReport(BaseModel):
    """Which cited keys resolve, which do not, and which entries nothing cites."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cited_keys: tuple[str, ...] = ()
    missing_keys: tuple[MissingCitation, ...] = ()
    unused_entries: tuple[str, ...] = ()

    @property
    def missing_key_names(self) -> tuple[str, ...]:
        """The distinct unresolved keys, in document order."""
        names: list[str] = []
        for missing in self.missing_keys:
            if missing.key not in names:
                names.append(missing.key)
        return tuple(names)

    @property
    def is_closed(self) -> bool:
        """True when every cited key resolves to an entry."""
        return not self.missing_keys


def citation_closure(project: LatexProject, bib: BibDatabase) -> CitationClosureReport:
    """Match the manuscript's citation keys against ``bib``.

    Every *occurrence* of an unresolved key is reported, not just the key, because the unit
    a researcher fixes is a sentence. Resolving a key here says only that the entry exists.
    """
    missing: list[MissingCitation] = []
    for sentence in project.sentences:
        for key in sentence.citation_keys:
            if key not in bib:
                missing.append(MissingCitation(key=key, sentence=sentence))
    cited = project.cited_keys()
    used = set(cited)
    return CitationClosureReport(
        cited_keys=cited,
        missing_keys=tuple(missing),
        unused_entries=tuple(key for key in bib.entries if key not in used),
    )


def findings_for_missing(report: CitationClosureReport) -> list[ManuscriptAuditFinding]:
    """Audit findings for unresolved citation keys, one per citing sentence.

    The domain vocabulary has no ``missing_citation_key`` kind, so these use
    :attr:`ManuscriptFindingKind.CITATION_MISMATCH` - the key does not match anything in
    the bibliography - at ``ERROR`` severity, since the manuscript cannot compile or be
    submitted with a dangling key.
    """
    return [
        ManuscriptAuditFinding(
            kind=ManuscriptFindingKind.CITATION_MISMATCH,
            severity=FindingSeverity.ERROR,
            message=(
                f"citation key {missing.key!r} is not defined in the bibliography "
                f"({missing.sentence.file}:{missing.sentence.line_start})"
            ),
            sentence=missing.sentence.normalized_text,
        )
        for missing in report.missing_keys
    ]

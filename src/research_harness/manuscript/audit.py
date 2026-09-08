"""The manuscript auditor: every substantive sentence, against the accepted research graph.

Product 30.3 lists what an audit must detect, and this module detects exactly that list and
nothing else:

===========================  ===========================================================
``UNREGISTERED_CLAIM``       a substantive sentence that is attached to no Claim
``OVER_STRONG_WORDING``      a sentence that reads stronger than its Claim allows (42.G)
``CITATION_MISMATCH``        a key that does not exist, or that does not support (42.J)
``UNSUPPORTED_NUMERIC``      a number no accepted, source-observed Evidence measures
``STALE_CLAIM``              a Claim or anchor the research state moved out from under
``INVALID_EVIDENCE_ANCHOR``  supporting Evidence that no longer opens at its source (42.D)
===========================  ===========================================================

The audit is a pure function of the context it is handed: it opens no repository, writes no
canonical state, and calls no provider. Findings are *reported*, never corrected -
unresolved support becomes a visible warning rather than a fabricated citation (Product
30.2), and a stale anchor is never quietly reattached (ADR-008).

:func:`audit_manuscript` also returns the traceability chain of Product 30.1 -
sentence -> Claim -> Claim-Evidence relation -> Evidence -> page and span - resolved down
to the exact PDF span wherever a :class:`~research_harness.domain.document.ParsedDocument`
is available. That chain is what makes provenance clickable (Product 42.D, Gate P9).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.claim import Claim
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    ClaimStatus,
    FindingSeverity,
    ManuscriptAnchorStatus,
    ManuscriptFindingKind,
    StaleState,
)
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ArtifactId, ClaimId, EvidenceId, ResearchId, WorkId
from research_harness.domain.manuscript import (
    FindingLocation,
    ManuscriptAnchor,
    ManuscriptAuditFinding,
)
from research_harness.domain.work import Work
from research_harness.manuscript.anchors import AnchorRevalidation, anchor_key, revalidate_all
from research_harness.manuscript.bibtex import BibDatabase
from research_harness.manuscript.citations import citation_closure
from research_harness.manuscript.latex import LatexProject, Sentence
from research_harness.manuscript.support import (
    SUPPORTING_RELATIONS,
    BibWorkMap,
    CitationKeyCheck,
    NumberMention,
    citation_support,
    match_bib_to_works,
    numbers_in_sentence,
    numeric_support,
)
from research_harness.manuscript.wording import WordingEstimate, stronger_than, wording_level
from research_harness.parsing.anchors import (
    AnchorValidationStatus,
    ResolvedSpan,
    resolve_anchor,
    validate_anchor,
)

__all__ = [
    "CLAIM_VERBS_PATTERN",
    "MIN_SUBSTANTIVE_WORDS",
    "QUESTIONABLE_CLAIM_STATUSES",
    "AuditContext",
    "AuditScope",
    "ManuscriptAuditReport",
    "TraceLink",
    "audit_manuscript",
    "is_substantive",
    "narrow_report",
    "sentence_location",
]


# --------------------------------------------------------------------------------------
# what counts as a claim in prose
# --------------------------------------------------------------------------------------

MIN_SUBSTANTIVE_WORDS = 6
"""Shorter than this a sentence is a signpost ("See Table 2."), not a research assertion."""

CLAIM_VERBS_PATTERN = (
    r"\b(?:outperform|improve|show|demonstrate|use|employ|rely|reli|reduce|increase|achieve)"
    r"(?:s|es|d|ed|ing|n)?\b"
)
"""Verbs with which a sentence asserts something about the world rather than about itself."""

_CLAIM_VERB_RE = re.compile(CLAIM_VERBS_PATTERN, re.IGNORECASE)
_COMPARATIVE_RE = re.compile(
    r"\b(?:all|always|never|every|most|many|several|some|majority|typically|commonly|"
    r"generally|universally|better|worse|higher|lower|faster|slower|more|less|fewer|"
    r"than|compared|outperforms|state[- ]of[- ]the[- ]art|literature)\b",
    re.IGNORECASE,
)

#: Claim statuses whose manuscript sentences need a second look before submission.
QUESTIONABLE_CLAIM_STATUSES: frozenset[ClaimStatus] = frozenset(
    {ClaimStatus.SUPERSEDED, ClaimStatus.UNSUPPORTED, ClaimStatus.CONTESTED}
)

#: Anchor verdicts that mean the sentence the Claim was attached to has moved or gone.
_BROKEN_ANCHOR_STATUSES: frozenset[ManuscriptAnchorStatus] = frozenset(
    {ManuscriptAnchorStatus.STALE, ManuscriptAnchorStatus.MISSING}
)

#: Report order within one sentence: the Product 30.3 list, top to bottom.
_KIND_ORDER: dict[ManuscriptFindingKind, int] = {
    kind: index
    for index, kind in enumerate(
        (
            ManuscriptFindingKind.UNREGISTERED_CLAIM,
            ManuscriptFindingKind.OVER_STRONG_WORDING,
            ManuscriptFindingKind.CITATION_MISMATCH,
            ManuscriptFindingKind.UNSUPPORTED_NUMERIC,
            ManuscriptFindingKind.STALE_CLAIM,
            ManuscriptFindingKind.INVALID_EVIDENCE_ANCHOR,
        )
    )
}


def is_substantive(sentence: Sentence) -> bool:
    """True when a sentence asserts something the research graph should account for.

    A substantive sentence is body prose (the abstract counts; material inside a figure,
    table, or other float never becomes a sentence in the first place) of at least
    :data:`MIN_SUBSTANTIVE_WORDS` words that also carries at least one of: a citation, a
    number, a comparative or quantifier cue, or a claim verb. Everything else - transitions,
    signposts, definitions of notation - is prose the audit has no opinion about.
    """
    text = sentence.normalized_text
    if len(text.split()) < MIN_SUBSTANTIVE_WORDS:
        return False
    if sentence.citation_keys:
        return True
    if numbers_in_sentence(text):
        return True
    return bool(_COMPARATIVE_RE.search(text) or _CLAIM_VERB_RE.search(text))


# --------------------------------------------------------------------------------------
# inputs and outputs
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditContext:
    """Everything the audit reads. Handed in, never fetched: the auditor owns no I/O."""

    project: LatexProject
    bib: BibDatabase | None = None
    anchors: Sequence[ManuscriptAnchor] = ()
    claims: Mapping[ClaimId, Claim] = field(default_factory=dict)
    evidence: Mapping[EvidenceId, Evidence] = field(default_factory=dict)
    works: Mapping[WorkId, Work] = field(default_factory=dict)
    parsed: Mapping[ArtifactId, ParsedDocument] = field(default_factory=dict)
    """Parsed source artifacts, keyed by artifact id. Evidence anchors are only validated
    and resolved for artifacts present here; an absent artifact is not a finding, because
    "this parse was not loaded" is not "this provenance is broken"."""


class TraceLink(BaseModel):
    """One resolved link of the Product 30.1 chain, from a sentence down to a page span."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sentence: Sentence
    anchor_key: str
    claim: ClaimId
    evidence: tuple[EvidenceId, ...] = ()
    spans: tuple[ResolvedSpan, ...] = ()
    """Exact source spans, one per supporting Evidence whose artifact parse was supplied
    and whose anchor still resolves. Empty when no parse was available."""


class ManuscriptAuditReport(BaseModel):
    """What the audit found, what it checked, and the trace it could resolve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[ManuscriptAuditFinding, ...] = ()
    sentences_checked: int = Field(default=0, ge=0)
    anchored_sentences: int = Field(default=0, ge=0)
    unanchored_substantive: int = Field(default=0, ge=0)
    revalidations: tuple[AnchorRevalidation, ...] = ()
    trace: tuple[TraceLink, ...] = ()

    def of_kind(self, kind: ManuscriptFindingKind) -> tuple[ManuscriptAuditFinding, ...]:
        """Findings of one kind, in report order."""
        return tuple(finding for finding in self.findings if finding.kind is kind)

    @property
    def errors(self) -> tuple[ManuscriptAuditFinding, ...]:
        """Findings that must be resolved before the manuscript is submittable."""
        return tuple(
            finding for finding in self.findings if finding.severity is FindingSeverity.ERROR
        )

    @property
    def is_clean(self) -> bool:
        """True when the manuscript raised nothing at all."""
        return not self.findings

    def trace_for(self, key: str) -> TraceLink | None:
        """The trace link for one anchor key, or ``None`` when the anchor did not resolve."""
        return next((link for link in self.trace if link.anchor_key == key), None)


# --------------------------------------------------------------------------------------
# the audit
# --------------------------------------------------------------------------------------


def audit_manuscript(ctx: AuditContext) -> ManuscriptAuditReport:
    """Audit a manuscript against the accepted research graph (Product 30.3).

    Findings are emitted in document order and, within a sentence, in the order of the
    table at the top of this module, so two runs over the same inputs produce byte-identical
    reports. Nothing is written and nothing is repaired.
    """
    return _Auditor(ctx).run()


class _Auditor:
    """One audit pass. Holds the derived indexes so each check stays a small function."""

    def __init__(self, ctx: AuditContext) -> None:
        self.ctx = ctx
        self.pending: list[tuple[tuple[int, int, int], ManuscriptAuditFinding]] = []
        self.trace: list[TraceLink] = []
        self.revalidations = revalidate_all(list(ctx.anchors), ctx.project)
        self.by_fingerprint: dict[tuple[str, str], ManuscriptAnchor] = {
            (anchor.file, anchor.sentence_fingerprint): anchor for anchor in ctx.anchors
        }
        self.verdict: dict[str, AnchorRevalidation] = {
            anchor_key(result.anchor): result for result in self.revalidations
        }
        self.position: dict[tuple[str, int, int], int] = {
            _where(sentence): index for index, sentence in enumerate(ctx.project.sentences)
        }
        self.bibmap: BibWorkMap = (
            match_bib_to_works(ctx.bib, ctx.works) if ctx.bib is not None else BibWorkMap()
        )

    # -- driver ----------------------------------------------------------------

    def run(self) -> ManuscriptAuditReport:
        substantive = 0
        anchored = 0
        unanchored = 0
        self._missing_citation_keys()

        for sentence in self.ctx.project.sentences:
            if not is_substantive(sentence):
                continue
            substantive += 1
            anchor = self.by_fingerprint.get((sentence.file, sentence.fingerprint))
            if anchor is None:
                unanchored += 1
                self._unregistered(sentence)
                continue
            anchored += 1
            self._audit_anchored(sentence, anchor)

        for result in self.revalidations:
            if result.status in _BROKEN_ANCHOR_STATUSES:
                self._broken_anchor(result)

        ordered = sorted(self.pending, key=lambda item: item[0])
        return ManuscriptAuditReport(
            findings=tuple(finding for _, finding in ordered),
            sentences_checked=substantive,
            anchored_sentences=anchored,
            unanchored_substantive=unanchored,
            revalidations=self.revalidations,
            trace=tuple(self.trace),
        )

    def _audit_anchored(self, sentence: Sentence, anchor: ManuscriptAnchor) -> None:
        claim = self.ctx.claims.get(anchor.claim)
        if claim is None:
            self._orphan_claim(sentence, anchor)
            return
        self._wording(sentence, anchor, claim)
        self._citations(sentence, anchor, claim)
        self._numbers(sentence, anchor, claim)
        self._staleness(sentence, anchor, claim)
        self._evidence_anchors(sentence, anchor, claim)
        self._trace(sentence, anchor, claim)

    # -- checks ----------------------------------------------------------------

    def _unregistered(self, sentence: Sentence) -> None:
        """Say why this sentence is one the graph should account for, not what it is called.

        The message used to read "substantive sentence is attached to no Claim", which is
        the finding's own kind said a second time: a client that names the kind - the
        cockpit prints "Unregistered claim - <message>" - then stated one fact twice and
        added nothing a researcher could act on. What only the auditor knows is which cue
        made the sentence substantive (:func:`is_substantive`) and what would clear the
        finding, so that is what it says.
        """
        self._add(
            ManuscriptFindingKind.UNREGISTERED_CLAIM,
            FindingSeverity.WARNING,
            sentence,
            f"{_substantive_cue(sentence)}; anchor it to a Claim so the manuscript stays "
            "downstream of accepted state",
        )

    def _orphan_claim(self, sentence: Sentence, anchor: ManuscriptAnchor) -> None:
        self._add(
            ManuscriptFindingKind.UNREGISTERED_CLAIM,
            FindingSeverity.ERROR,
            sentence,
            f"anchor names {anchor.claim}, which is not in the research graph",
            anchor=anchor,
            related=(anchor.claim,),
        )

    def _wording(self, sentence: Sentence, anchor: ManuscriptAnchor, claim: Claim) -> None:
        estimate: WordingEstimate = wording_level(sentence.normalized_text)
        allowed = claim.assessment.allowed_strength
        if not stronger_than(estimate.level, allowed):
            return
        cues = ", ".join(repr(cue) for cue in estimate.cues) or "its phrasing"
        self._add(
            ManuscriptFindingKind.OVER_STRONG_WORDING,
            FindingSeverity.WARNING,
            sentence,
            (
                f"sentence reads {estimate.level.label} via {cues}, but {claim.id} allows "
                f"only {allowed.label}; the defensible wording is "
                f"{claim.assessment.maximum_defensible_wording or allowed.value!r}"
            ),
            anchor=anchor,
            related=(claim.id,),
        )

    def _citations(self, sentence: Sentence, anchor: ManuscriptAnchor, claim: Claim) -> None:
        report = citation_support(anchor, claim, self.ctx.evidence, self.bibmap)
        for check in report.mismatches:
            if check.status == "missing_key":
                continue  # already reported once per citing sentence by citation closure
            self._add(
                ManuscriptFindingKind.CITATION_MISMATCH,
                FindingSeverity.ERROR,
                sentence,
                _citation_message(check, claim),
                anchor=anchor,
                related=_citation_related(check, claim),
            )

    def _numbers(self, sentence: Sentence, anchor: ManuscriptAnchor, claim: Claim) -> None:
        for mention in numbers_in_sentence(sentence.normalized_text):
            check = numeric_support(mention, claim, self.ctx.evidence)
            if check.is_supported:
                continue
            incompatible = check.status == "incompatible"
            self._add(
                ManuscriptFindingKind.UNSUPPORTED_NUMERIC,
                FindingSeverity.ERROR if incompatible else FindingSeverity.WARNING,
                sentence,
                _numeric_message(mention, claim, check.reasons, incompatible=incompatible),
                anchor=anchor,
                related=(claim.id, *(() if check.evidence is None else (check.evidence,))),
            )

    def _staleness(self, sentence: Sentence, anchor: ManuscriptAnchor, claim: Claim) -> None:
        reasons: list[str] = []
        if claim.stale is StaleState.STALE:
            reasons.append("the claim is marked stale by an upstream change")
        if claim.status in QUESTIONABLE_CLAIM_STATUSES:
            reasons.append(f"the claim status is {claim.status.value}")
        result = self.verdict.get(anchor_key(anchor))
        if result is not None and result.status in _BROKEN_ANCHOR_STATUSES:
            reasons.append(f"the anchor is {result.status.value}: {result.reason}")
        if anchor.stale is StaleState.STALE and not reasons:
            reasons.append("the anchor is marked stale and awaits review")
        if not reasons:
            return
        self._add(
            ManuscriptFindingKind.STALE_CLAIM,
            FindingSeverity.WARNING,
            sentence,
            f"{claim.id} needs review before this sentence ships: {'; '.join(reasons)}",
            anchor=anchor,
            related=(claim.id,),
        )

    def _evidence_anchors(self, sentence: Sentence, anchor: ManuscriptAnchor, claim: Claim) -> None:
        for item in self._supporting(claim):
            reason = self._anchor_problem(item)
            if reason is None:
                continue
            self._add(
                ManuscriptFindingKind.INVALID_EVIDENCE_ANCHOR,
                FindingSeverity.ERROR,
                sentence,
                f"{item.id} no longer opens at its source, so {claim.id} is unprovenanced: "
                f"{reason}",
                anchor=anchor,
                related=(claim.id, item.id),
            )

    def _trace(self, sentence: Sentence, anchor: ManuscriptAnchor, claim: Claim) -> None:
        supporting = self._supporting(claim)
        spans: list[ResolvedSpan] = []
        for item in supporting:
            doc = self.ctx.parsed.get(item.source.artifact)
            if doc is None:
                continue
            if validate_anchor(item.source, doc).status is not AnchorValidationStatus.VALID:
                continue
            spans.append(resolve_anchor(item.source, doc))
        self.trace.append(
            TraceLink(
                sentence=sentence,
                anchor_key=anchor_key(anchor),
                claim=claim.id,
                evidence=tuple(item.id for item in supporting),
                spans=tuple(spans),
            )
        )

    def _broken_anchor(self, result: AnchorRevalidation) -> None:
        """A stale or missing anchor no longer has a sentence, so it is reported on its own.

        Revalidation only reports ``valid`` when the exact fingerprint is still in the file,
        so nothing here duplicates a finding already raised against a live sentence.
        """
        anchor = result.anchor
        rank = _KIND_ORDER[ManuscriptFindingKind.STALE_CLAIM]
        self.pending.append(
            (
                (len(self.position), rank, len(self.pending)),
                ManuscriptAuditFinding(
                    kind=ManuscriptFindingKind.STALE_CLAIM,
                    severity=FindingSeverity.WARNING,
                    message=(
                        f"{anchor.file}:{anchor.line_start}: the sentence anchored to "
                        f"{anchor.claim} is {result.status.value}: {result.reason}"
                    ),
                    anchor=anchor,
                    related=(anchor.claim,),
                    sentence=anchor.sentence,
                ),
            )
        )

    # -- helpers ---------------------------------------------------------------

    def _missing_citation_keys(self) -> None:
        """Report every unresolved citation key, once per citing sentence (closure)."""
        if self.ctx.bib is None:
            return
        for item in citation_closure(self.ctx.project, self.ctx.bib).missing_keys:
            sentence = item.sentence
            self._add(
                ManuscriptFindingKind.CITATION_MISMATCH,
                FindingSeverity.ERROR,
                sentence,
                f"citation key {item.key!r} is not defined in the bibliography",
                anchor=self.by_fingerprint.get((sentence.file, sentence.fingerprint)),
            )

    def _supporting(self, claim: Claim) -> tuple[Evidence, ...]:
        """Evidence the claim leans on, in declaration order; unresolvable ids are skipped."""
        found: list[Evidence] = []
        for link in claim.relations:
            if link.relation not in SUPPORTING_RELATIONS:
                continue
            item = self.ctx.evidence.get(link.evidence)
            if item is not None:
                found.append(item)
        return tuple(found)

    def _anchor_problem(self, item: Evidence) -> str | None:
        """Why this evidence no longer opens at its source, or ``None`` when it does."""
        if item.stale is StaleState.STALE:
            return "the evidence is marked stale and must be reviewed before it is cited"
        doc = self.ctx.parsed.get(item.source.artifact)
        if doc is None:
            return None
        result = validate_anchor(item.source, doc)
        if result.status is AnchorValidationStatus.VALID:
            return None
        return f"anchor validation reports {result.status.value} - {result.reason}"

    def _add(
        self,
        kind: ManuscriptFindingKind,
        severity: FindingSeverity,
        sentence: Sentence,
        message: str,
        *,
        anchor: ManuscriptAnchor | None = None,
        related: tuple[ResearchId, ...] = (),
    ) -> None:
        """Queue a finding at its sentence's position, so the report reads in document order."""
        where = self.position.get(_where(sentence), len(self.position))
        self.pending.append(
            (
                (where, _KIND_ORDER[kind], len(self.pending)),
                ManuscriptAuditFinding(
                    kind=kind,
                    severity=severity,
                    message=f"{sentence.file}:{sentence.line_start}: {message}",
                    anchor=anchor,
                    related=related,
                    location=sentence_location(sentence),
                    sentence=sentence.normalized_text,
                ),
            )
        )


# --------------------------------------------------------------------------------------
# messages
# --------------------------------------------------------------------------------------


def _where(sentence: Sentence) -> tuple[str, int, int]:
    return (sentence.file, sentence.char_start, sentence.char_end)


def _substantive_cue(sentence: Sentence) -> str:
    """Which of :func:`is_substantive`'s four cues made this sentence an assertion.

    The cues are tested in that function's own order, so the sentence a researcher reads
    names the same reason the audit acted on. Every branch is reachable: a sentence that
    reaches this function passed one of them.
    """
    text = sentence.normalized_text
    if sentence.citation_keys:
        keys = ", ".join(sorted(sentence.citation_keys))
        return f"the sentence cites {keys}"
    numbers = numbers_in_sentence(text)
    if numbers:
        return f"the sentence states {numbers[0].text}"
    if _COMPARATIVE_RE.search(text):
        return "the sentence compares or quantifies"
    return "the sentence states a result"


# --------------------------------------------------------------------------------------
# narrowing an audit to a range of the manuscript
# --------------------------------------------------------------------------------------


def sentence_location(sentence: Sentence) -> FindingLocation:
    """The structured location of ``sentence``, as a finding records it."""
    return FindingLocation(
        file=sentence.file,
        line_start=sentence.line_start,
        line_end=sentence.line_end,
        char_start=sentence.char_start,
        char_end=sentence.char_end,
    )


class AuditScope(DomainModel):
    """One file, and optionally one line range inside it, an audit is asked about.

    A whole-project audit re-parses every source artifact behind the manuscript, which is
    the expensive half; an editor asking about the lines on screen should not pay for it
    (Product 28). The scope narrows *what is reported*, never what the rules are: a
    sentence inside the range is audited exactly as it would be in a full run.
    """

    file: NonEmptyStr
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _lines_are_ordered(self) -> AuditScope:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must not precede line_start")
        return self

    @property
    def first_line(self) -> int:
        """First line in scope; 1 when the caller named no start."""
        return self.line_start if self.line_start is not None else 1

    @property
    def last_line(self) -> int:
        """Last line in scope; unbounded when the caller named no end."""
        return self.line_end if self.line_end is not None else _UNBOUNDED_LINE

    def covers_file(self, file: str) -> bool:
        """True when ``file`` is the file this scope names."""
        return file == self.file

    def covers(self, location: FindingLocation | None) -> bool:
        """True when ``location`` is inside this scope; an absent location never is."""
        if location is None:
            return False
        if not self.covers_file(location.file):
            return False
        return location.overlaps(line_start=self.first_line, line_end=self.last_line)

    def covers_sentence(self, sentence: Sentence) -> bool:
        """True when ``sentence`` lies inside this scope."""
        return self.covers(sentence_location(sentence))

    def covers_anchor(self, anchor: ManuscriptAnchor) -> bool:
        """True when a stored anchor's recorded span lies inside this scope."""
        if not self.covers_file(anchor.file):
            return False
        return anchor.line_start <= self.last_line and self.first_line <= anchor.line_end


_UNBOUNDED_LINE = 1_000_000_000
"""Stand-in for "no end line". A LaTeX file with more lines than this is not a manuscript."""


def narrow_report(
    report: ManuscriptAuditReport, scope: AuditScope, project: LatexProject
) -> ManuscriptAuditReport:
    """The same audit, reported only for the sentences and anchors inside ``scope``.

    The counts are recomputed over the in-scope sentences rather than carried over, so
    ``sentences_checked`` answers "how many sentences in this range" rather than "how many
    in the project" — an editor showing three findings out of four sentences must not be
    told it checked forty.
    """
    in_scope = [
        sentence
        for sentence in project.sentences
        if scope.covers_sentence(sentence) and is_substantive(sentence)
    ]
    anchored = {
        (result.anchor.file, result.anchor.sentence_fingerprint) for result in report.revalidations
    }
    checked = len(in_scope)
    attached = sum(1 for sentence in in_scope if (sentence.file, sentence.fingerprint) in anchored)
    return ManuscriptAuditReport(
        findings=tuple(
            finding
            for finding in report.findings
            if scope.covers(finding.location)
            or (
                finding.location is None
                and finding.anchor is not None
                and scope.covers_anchor(finding.anchor)
            )
        ),
        sentences_checked=checked,
        anchored_sentences=attached,
        unanchored_substantive=checked - attached,
        revalidations=tuple(
            result for result in report.revalidations if scope.covers_anchor(result.anchor)
        ),
        trace=tuple(link for link in report.trace if scope.covers_sentence(link.sentence)),
    )


def _citation_message(check: CitationKeyCheck, claim: Claim) -> str:
    if check.status == "contradicts":
        return (
            f"citation {check.key!r} is attached to {claim.id}, but the accepted evidence "
            f"from {check.work} contradicts it: {check.reason}"
        )
    if check.status == "unmatched_work":
        return f"citation {check.key!r} cannot be traced to a corpus work: {check.reason}"
    return (
        f"citation {check.key!r} exists but does not support {claim.id}; citation existence "
        f"is not evidence support ({check.reason})"
    )


def _citation_related(check: CitationKeyCheck, claim: Claim) -> tuple[ResearchId, ...]:
    related: list[ResearchId] = [claim.id]
    if check.work is not None:
        related.append(check.work)
    related.extend(check.evidence_ids)
    return tuple(related)


def _numeric_message(
    mention: NumberMention,
    claim: Claim,
    reasons: tuple[str, ...],
    *,
    incompatible: bool,
) -> str:
    detail = "; ".join(reasons)
    if incompatible:
        return (
            f"the value {mention.text!r} matches evidence of {claim.id} but not its "
            f"metric, dataset, or unit, and none of those may change silently: {detail}"
        )
    return f"the value {mention.text!r} is not backed by source-observed evidence: {detail}"

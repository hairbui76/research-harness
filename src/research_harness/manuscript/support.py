"""Citation *support* and numeric compatibility: the expensive half of Product 30.2.

:mod:`research_harness.manuscript.citations` answers whether a citation key resolves.
This module answers the question that actually matters: does the cited work carry accepted
Evidence that supports the attached Claim, and does a number written in the manuscript
still mean what the source measured?

Two rules drive everything here.

* **Citation existence is not evidence support.** A key that parses, resolves, and renders
  is a bibliography fact; support is a Claim-Evidence fact. A key whose Work has no
  accepted ``supports``/``exemplifies`` relation with the Claim is a mismatch, and a key
  whose Work only contradicts it is a mismatch of a different and louder kind (Product
  42.J).
* **A number never travels alone.** Product 12 forbids silently changing metric, unit,
  dataset, experimental condition, rounding, or denominator, and abstract-only or
  author-reported sources may establish existence or direction but never a specific
  measured value. A manuscript number is therefore supported only by accepted,
  source-observed, direct Evidence whose metric, dataset, and unit the sentence still
  carries.

Nothing here writes, and nothing here repairs: an unresolved support is reported so it can
become a visible ``NEEDS SOURCE`` warning rather than a fabricated citation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from research_harness.claims.strength import AUTHOR_ORIGINS
from research_harness.domain.claim import Claim
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    StaleState,
)
from research_harness.domain.evidence import Evidence, NumericValue
from research_harness.domain.ids import EvidenceId, WorkId
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.work import Work
from research_harness.ingest.identity import (
    AUTHOR_OVERLAP_THRESHOLD,
    YEAR_TOLERANCE,
    YEAR_TOLERANCE_WITH_AUTHORS,
    arxiv_base_id,
    author_surnames,
    normalize_doi,
    normalize_title,
    surname_overlap,
)
from research_harness.manuscript.bibtex import BibDatabase, BibEntry
from research_harness.manuscript.protected import ProtectedSpanKind, find_protected_spans

__all__ = [
    "CITATION_MISMATCH_STATUSES",
    "CONTRADICTING_RELATIONS",
    "FRACTION_UNITS",
    "PERCENT_UNITS",
    "QUALIFYING_RELATIONS",
    "REFERENCE_CUES",
    "SUPPORTING_RELATIONS",
    "SUPPORT_ORIGINS",
    "SUPPORT_STRENGTHS",
    "YEAR_MAX",
    "YEAR_MIN",
    "BibWorkMap",
    "CitationKeyCheck",
    "CitationStatus",
    "CitationSupportReport",
    "NumberMention",
    "NumericCheck",
    "NumericStatus",
    "canonical_unit",
    "citation_support",
    "match_bib_to_works",
    "numbers_in_sentence",
    "numeric_support",
]


# --------------------------------------------------------------------------------------
# policy vocabularies
# --------------------------------------------------------------------------------------

#: Relations under which a cited work actually backs the claim (Product 10.4).
SUPPORTING_RELATIONS: frozenset[ClaimEvidenceRelationType] = frozenset(
    {ClaimEvidenceRelationType.SUPPORTS, ClaimEvidenceRelationType.EXEMPLIFIES}
)
#: Relations that narrow or situate a claim. Reported, never a mismatch: a citation that
#: qualifies the sentence it decorates is doing honest work.
QUALIFYING_RELATIONS: frozenset[ClaimEvidenceRelationType] = frozenset(
    {
        ClaimEvidenceRelationType.QUALIFIES,
        ClaimEvidenceRelationType.CONTEXTUALIZES,
        ClaimEvidenceRelationType.INCOMPARABLE_UNDER_CURRENT_EVIDENCE,
    }
)
#: Relations under which the cited work argues against the claim it is cited for.
CONTRADICTING_RELATIONS: frozenset[ClaimEvidenceRelationType] = frozenset(
    {ClaimEvidenceRelationType.CONTRADICTS}
)

#: Origins that may back a *specific measured value*. Author-reported and model-proposed
#: evidence establishes existence or direction only (Product 12, 42.E).
SUPPORT_ORIGINS: frozenset[EvidenceOrigin] = frozenset({EvidenceOrigin.SOURCE_OBSERVED})
#: Strengths that may back a specific measured value; an indirect or derived reading
#: cannot, because the number was not read off the source.
SUPPORT_STRENGTHS: frozenset[EvidenceStrength] = frozenset({EvidenceStrength.DIRECT})

CitationStatus = Literal[
    "missing_key",
    "unmatched_work",
    "no_relation",
    "supports",
    "qualifies",
    "contradicts",
]
"""Verdict on one citation key of one anchored sentence."""

#: Verdicts the auditor reports as a citation mismatch. ``qualifies`` is deliberately
#: absent, and ``supports`` is the only clean outcome.
CITATION_MISMATCH_STATUSES: frozenset[str] = frozenset(
    {"missing_key", "unmatched_work", "no_relation", "contradicts"}
)

NumericStatus = Literal["supported", "incompatible", "unsupported"]
"""Verdict on one number written in the manuscript."""


# --------------------------------------------------------------------------------------
# bibliography -> corpus
# --------------------------------------------------------------------------------------


class BibWorkMap(BaseModel):
    """Which bibliography keys name works in the corpus, and which cannot be resolved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    by_key: dict[str, WorkId] = {}
    unmatched_keys: tuple[str, ...] = ()
    """Entries that exist in the ``.bib`` but name no work in the corpus."""
    ambiguous: dict[str, tuple[WorkId, ...]] = {}
    """Entries whose identifiers or title match more than one work; never guessed."""

    def work_for(self, key: str) -> WorkId | None:
        """The work a key resolves to, or ``None`` when it is unmatched or ambiguous."""
        return self.by_key.get(key)

    def is_known_entry(self, key: str) -> bool:
        """True when the bibliography defines ``key``, whether or not it resolved."""
        return key in self.by_key or key in self.ambiguous or key in self.unmatched_keys


_BRACES_RE = re.compile(r"[{}]")
_LATEX_ESCAPE_RE = re.compile(r"\\([%&#_$])")
_LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+\s*")
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b")
#: BibTeX joins authors with a literal ``and``; ``&`` and ``;`` show up in hand-written files.
_BIB_AUTHOR_SEPARATOR = re.compile(r"\s+and\s+|[;&]", re.IGNORECASE)


def _plain(value: str) -> str:
    """Strip the LaTeX a BibTeX value carries so two titles compare as prose."""
    text = _BRACES_RE.sub(" ", value)
    text = _LATEX_ESCAPE_RE.sub(r"\1", text)
    return _LATEX_COMMAND_RE.sub(" ", text)


def _entry_doi(entry: BibEntry) -> str | None:
    for name in ("doi", "DOI"):
        value = entry.field(name)
        if value:
            return normalize_doi(_plain(value))
    url = entry.field("url") or ""
    if "doi.org/" in url:
        return normalize_doi(url)
    return None


def _entry_arxiv(entry: BibEntry) -> str | None:
    for name in ("eprint", "arxiv", "archiveprefix"):
        value = entry.field(name)
        if not value:
            continue
        if name == "archiveprefix":
            continue
        if name == "eprint":
            prefix = (entry.field("archiveprefix") or "arxiv").strip().casefold()
            if prefix and prefix != "arxiv":
                continue
        return arxiv_base_id(_plain(value))
    for name in ("url", "note", "journal"):
        value = entry.field(name) or ""
        if "arxiv" in value.casefold():
            return arxiv_base_id(_plain(value))
    return None


def _entry_year(entry: BibEntry) -> int | None:
    raw = entry.field("year") or ""
    match = _YEAR_RE.search(raw)
    return int(match.group(0)) if match else None


def _entry_surnames(entry: BibEntry) -> frozenset[str]:
    """Surnames of a BibTeX ``author`` field, which separates names with ``and``."""
    raw = _plain(entry.field("author") or "")
    return author_surnames(name for name in _BIB_AUTHOR_SEPARATOR.split(raw) if name.strip())


def _work_doi(work: Work) -> str | None:
    field = work.identifiers.doi
    return normalize_doi(field.value) if field is not None else None


def _work_arxiv(work: Work) -> str | None:
    field = work.identifiers.arxiv
    return arxiv_base_id(field.value) if field is not None else None


def match_bib_to_works(bib: BibDatabase, works: Mapping[WorkId, Work]) -> BibWorkMap:
    """Resolve bibliography keys to corpus works by DOI, then arXiv id, then title.

    Identifiers win over prose because they are exact: a DOI match is the same work, an
    arXiv base id (``v``-suffix removed) is the same work across revisions, and only when
    neither exists is a normalized title compared. Authors and the publication year are
    *tiebreakers* among works that share a title, never disqualifiers, because a Work's
    year is read off a PDF: an arXiv v3 banner made a 2023 paper look like a 2025 one and
    a correct bibliography entry stopped resolving (dogfood F4). The tolerance mirrors
    `ingest.identity`: one year on a bare title match, two once the author lists agree.

    A key that matches several works is recorded as ambiguous rather than resolved to the
    first candidate: identity is never guessed (Product 13, ADR-002).
    """
    by_doi: dict[str, list[WorkId]] = {}
    by_arxiv: dict[str, list[WorkId]] = {}
    by_title: dict[str, list[WorkId]] = {}
    for work_id, work in works.items():
        doi = _work_doi(work)
        if doi:
            by_doi.setdefault(doi, []).append(work_id)
        arxiv = _work_arxiv(work)
        if arxiv:
            by_arxiv.setdefault(arxiv, []).append(work_id)
        title = normalize_title(work.title)
        if title:
            by_title.setdefault(title, []).append(work_id)

    resolved: dict[str, WorkId] = {}
    unmatched: list[str] = []
    ambiguous: dict[str, tuple[WorkId, ...]] = {}

    for key, entry in bib.entries.items():
        candidates = _candidates_for(entry, works, by_doi, by_arxiv, by_title)
        if not candidates:
            unmatched.append(key)
        elif len(candidates) == 1:
            resolved[key] = candidates[0]
        else:
            ambiguous[key] = tuple(candidates)
    return BibWorkMap(
        by_key=resolved,
        unmatched_keys=tuple(unmatched),
        ambiguous=ambiguous,
    )


def _candidates_for(
    entry: BibEntry,
    works: Mapping[WorkId, Work],
    by_doi: Mapping[str, list[WorkId]],
    by_arxiv: Mapping[str, list[WorkId]],
    by_title: Mapping[str, list[WorkId]],
) -> list[WorkId]:
    """Works this entry could name, at the strongest identifier the entry carries."""
    doi = _entry_doi(entry)
    if doi and doi in by_doi:
        return list(by_doi[doi])
    arxiv = _entry_arxiv(entry)
    if arxiv and arxiv in by_arxiv:
        return list(by_arxiv[arxiv])
    title = normalize_title(_plain(entry.field("title") or ""))
    if not title or title not in by_title:
        return []
    year = _entry_year(entry)
    surnames = _entry_surnames(entry)
    return [
        work_id
        for work_id in by_title[title]
        if _title_match_survives(works[work_id], entry_year=year, entry_surnames=surnames)
    ]


def _title_match_survives(
    work: Work, *, entry_year: int | None, entry_surnames: frozenset[str]
) -> bool:
    """Whether an exact title match survives the year, mirroring `ingest.identity`.

    A Work's year is read off a PDF and drifts: an arXiv v3 banner put a 2023 paper into
    the corpus as 2025, and a bibliography that correctly said 2023 stopped resolving
    (dogfood F4). So the year is a tiebreaker with a tolerance, not an equality test -
    one year on a bare title match, two once the author lists agree, exactly the
    `YEAR_TOLERANCE`/`YEAR_TOLERANCE_WITH_AUTHORS` rule identity resolution uses. A side
    that records no year cannot disagree with one that does.
    """
    if entry_year is None or work.year is None:
        return True
    overlap = surname_overlap(entry_surnames, author_surnames(work.authors))
    tolerance = (
        YEAR_TOLERANCE_WITH_AUTHORS if overlap >= AUTHOR_OVERLAP_THRESHOLD else YEAR_TOLERANCE
    )
    return abs(work.year - entry_year) <= tolerance


# --------------------------------------------------------------------------------------
# citation support
# --------------------------------------------------------------------------------------


class CitationKeyCheck(BaseModel):
    """What one citation key of one sentence turned out to be worth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    work: WorkId | None = None
    status: CitationStatus
    evidence_ids: tuple[EvidenceId, ...] = ()
    """Accepted, non-stale evidence from this work that decided the status."""
    reason: str = ""

    @property
    def is_mismatch(self) -> bool:
        """True when this citation does not support the claim it decorates."""
        return self.status in CITATION_MISMATCH_STATUSES


class CitationSupportReport(BaseModel):
    """Per-key verdicts for one anchored sentence, and the subset that are mismatches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    per_key: tuple[CitationKeyCheck, ...] = ()
    mismatches: tuple[CitationKeyCheck, ...] = ()

    @property
    def is_supported(self) -> bool:
        """True when every cited key resolves to a work that supports or qualifies."""
        return not self.mismatches


def citation_support(
    anchor: ManuscriptAnchor,
    claim: Claim,
    evidence: Mapping[EvidenceId, Evidence],
    bibmap: BibWorkMap,
) -> CitationSupportReport:
    """Check every key on ``anchor`` against the claim's accepted Claim-Evidence relations.

    **Citation existence is not evidence support.** A key that exists in the BibTeX file
    but whose Work carries no accepted, non-stale ``supports``/``exemplifies`` relation
    with the Claim is a mismatch; a key whose Work only contradicts the Claim is a
    mismatch of a different kind, because citing a paper that argues the opposite is worse
    than citing nothing. A ``qualifies`` relation is reported and is not a mismatch: a
    citation may legitimately narrow the sentence it appears in.

    Only accepted, non-stale evidence decides a verdict (ADR-003, ADR-008); a proposed or
    stale relation is named in ``reason`` and counts for nothing.
    """
    checks: list[CitationKeyCheck] = []
    for key in anchor.citation_keys:
        checks.append(_check_key(key, claim, evidence, bibmap))
    return CitationSupportReport(
        per_key=tuple(checks),
        mismatches=tuple(check for check in checks if check.is_mismatch),
    )


def _check_key(
    key: str,
    claim: Claim,
    evidence: Mapping[EvidenceId, Evidence],
    bibmap: BibWorkMap,
) -> CitationKeyCheck:
    work = bibmap.work_for(key)
    if work is None:
        if key in bibmap.ambiguous:
            names = ", ".join(str(candidate) for candidate in bibmap.ambiguous[key])
            return CitationKeyCheck(
                key=key,
                status="unmatched_work",
                reason=f"bibliography entry {key!r} matches several corpus works ({names})",
            )
        if key in bibmap.unmatched_keys:
            return CitationKeyCheck(
                key=key,
                status="unmatched_work",
                reason=(
                    f"bibliography entry {key!r} is not registered as a corpus work, so no "
                    "evidence can be traced to it"
                ),
            )
        return CitationKeyCheck(
            key=key,
            status="missing_key",
            reason=f"citation key {key!r} is not defined in the bibliography",
        )

    counted: dict[ClaimEvidenceRelationType, list[EvidenceId]] = {}
    ignored: list[EvidenceId] = []
    for link in claim.relations:
        item = evidence.get(link.evidence)
        if item is None or item.source.work != work:
            continue
        if _counts(item):
            counted.setdefault(link.relation, []).append(item.id)
        else:
            ignored.append(item.id)

    note = ""
    if ignored:
        listed = ", ".join(str(item) for item in ignored)
        note = f"; {listed} is linked but not accepted or is stale, so it was not counted"

    outcomes: tuple[tuple[frozenset[ClaimEvidenceRelationType], CitationStatus], ...] = (
        (SUPPORTING_RELATIONS, "supports"),
        (QUALIFYING_RELATIONS, "qualifies"),
        (CONTRADICTING_RELATIONS, "contradicts"),
    )
    for relations, status in outcomes:
        ids = [item for relation in relations for item in counted.get(relation, ())]
        if ids:
            listed = ", ".join(str(item) for item in ids)
            return CitationKeyCheck(
                key=key,
                work=work,
                status=status,
                evidence_ids=tuple(ids),
                reason=f"{work} {status} {claim.id} through {listed}{note}",
            )
    return CitationKeyCheck(
        key=key,
        work=work,
        status="no_relation",
        reason=(
            f"{key!r} resolves to {work}, but no accepted evidence from that work is "
            f"related to {claim.id}{note}"
        ),
    )


def _counts(item: Evidence) -> bool:
    """Accepted and fresh: the only state a relation is allowed to be read from."""
    return item.status is EvidenceStatus.ACCEPTED and item.stale is StaleState.FRESH


# --------------------------------------------------------------------------------------
# numbers in prose
# --------------------------------------------------------------------------------------


class NumberMention(BaseModel):
    """One number written in a manuscript sentence, with the text it was read from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    value: float
    unit: str | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    context: str
    """The sentence this number was read from; support checks look for metric and dataset
    tokens in it."""

    @property
    def precision(self) -> int:
        """Decimal places the author wrote, which is the rounding a match must survive.

        Rounding is part of a number's meaning (Product 12): ``94.3`` and ``94.32`` are the
        same measurement written to different precision, so a match is judged at the
        precision the manuscript states and never at the evidence's.
        """
        match = _VALUE_RE.match(self.text)
        mantissa = _EXPONENT_RE.split(match.group(0) if match else self.text)[0]
        _, _, fraction = mantissa.partition(".")
        return len(fraction)


#: Words that make the following number a pointer into the document rather than a result.
REFERENCE_CUES: frozenset[str] = frozenset(
    {
        "algorithm",
        "appendix",
        "chapter",
        "eq",
        "eqn",
        "eqs",
        "equation",
        "fig",
        "figs",
        "figure",
        "item",
        "line",
        "listing",
        "no",
        "note",
        "page",
        "part",
        "ref",
        "refs",
        "section",
        "sec",
        "step",
        "table",
        "tab",
        "version",
    }
)

#: Bare integers in this range read as publication years, not measurements.
YEAR_MIN = 1500
YEAR_MAX = 2099

_VALUE_RE = re.compile(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_EXPONENT_RE = re.compile(r"[eE]")
_TRAILING_WORD_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*|\\?%)\s*$")


def numbers_in_sentence(sentence_text: str) -> tuple[NumberMention, ...]:
    """Numbers a reader would take as measurements, in order, with their offsets.

    The number spans are exactly the ``number_with_unit`` protected spans of Product 30.4
    (:func:`~research_harness.manuscript.protected.find_protected_spans`), so a digit
    inside a citation, a cross-reference, math, a URL, a research identifier, a quotation,
    or code is never mistaken for a claim. Four further exclusions keep the audit quiet
    about structure rather than science: a bare integer that reads as a year, a number
    introduced by a cue such as ``Section``/``Table``/``Eq.``, an equation label in bare
    parentheses, and a number that is only part of a section number.
    """
    mentions: list[NumberMention] = []
    for span in find_protected_spans(sentence_text):
        if span.kind is not ProtectedSpanKind.NUMBER_WITH_UNIT:
            continue
        if _is_structural(sentence_text, span.char_start, span.char_end, span.text):
            continue
        value = _VALUE_RE.match(span.text)
        if value is None:  # pragma: no cover - the pattern always starts with a number
            continue
        mentions.append(
            NumberMention(
                text=span.text,
                value=float(value.group(0)),
                unit=_unit_of(span.text, value.end()),
                char_start=span.char_start,
                char_end=span.char_end,
                context=sentence_text,
            )
        )
    return tuple(mentions)


def _unit_of(text: str, offset: int) -> str | None:
    tail = text[offset:].strip()
    return tail or None


def _is_structural(sentence: str, start: int, end: int, text: str) -> bool:
    """True when this number points at the document instead of reporting a measurement."""
    stripped = text.strip()
    if _YEAR_RE.fullmatch(stripped):
        return True
    before = sentence[:start]
    cue = _TRAILING_WORD_RE.search(before.rstrip(" ~.").rstrip())
    if cue is not None and cue.group(1).casefold().rstrip(".") in REFERENCE_CUES:
        return True
    opened = before.rstrip().endswith("(")
    closed = sentence[end:].lstrip().startswith(")")
    return opened and closed and stripped.isdigit()


# --------------------------------------------------------------------------------------
# numeric compatibility
# --------------------------------------------------------------------------------------

#: Unit spellings that all mean "out of a hundred".
PERCENT_UNITS: frozenset[str] = frozenset({"%", "\\%", "pct", "percent", "percentage", "points"})
#: Unit spellings that mean "out of one".
FRACTION_UNITS: frozenset[str] = frozenset({"fraction", "proportion", "ratio"})


def canonical_unit(unit: str | None) -> str | None:
    """One spelling per unit, so ``\\%``, ``%``, and ``percent`` compare equal."""
    if unit is None:
        return None
    text = unit.strip().casefold()
    if not text:
        return None
    if text in PERCENT_UNITS:
        return "percent"
    if text in FRACTION_UNITS:
        return "fraction"
    return text


class NumericCheck(BaseModel):
    """Whether a manuscript number is backed by evidence, incompatible with it, or bare."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: NumericStatus
    evidence: EvidenceId | None = None
    reasons: tuple[str, ...] = ()

    @property
    def is_supported(self) -> bool:
        """True only when accepted, source-observed evidence carries this exact value."""
        return self.status == "supported"


def numeric_support(
    mention: NumberMention,
    claim: Claim,
    evidence: Mapping[EvidenceId, Evidence],
) -> NumericCheck:
    """Decide whether ``mention`` is a value the claim's evidence actually measured.

    ``supported`` requires all of: accepted, non-stale, source-observed, direct Evidence in
    a supporting relation with the claim; a :class:`NumericValue` equal to the mention
    after rounding to the precision the author wrote; a compatible unit (percent and
    fraction are reconciled, everything else must agree); and a sentence - or claim
    semantics - that still names the metric and the dataset the value was measured on.

    ``incompatible`` is the Product 12 guard and is the loud case: the number matches but
    its metric, dataset, or unit does not, which is exactly the silent substitution the
    writer may never make. ``unsupported`` covers everything else, including a value that
    only author-reported or abstract-level evidence carries: such a source may establish
    existence or direction, never a specific measured value.
    """
    reasons: list[str] = []
    incompatible: NumericCheck | None = None
    for link in claim.relations:
        if link.relation not in SUPPORTING_RELATIONS:
            continue
        item = evidence.get(link.evidence)
        if item is None or item.content.numeric is None:
            continue
        numeric = item.content.numeric
        if not _same_number(mention, numeric):
            continue
        if not _counts(item):
            reasons.append(
                f"{item.id} carries {numeric.raw} but is {item.status.value}"
                f"{' and stale' if item.stale is StaleState.STALE else ''}, "
                "so it cannot back a measured value"
            )
            continue
        if item.origin in AUTHOR_ORIGINS or item.origin not in SUPPORT_ORIGINS:
            reasons.append(
                f"{item.id} carries {numeric.raw} but is {item.origin.value}; Product 12 "
                "lets such a source establish existence or direction, never a specific "
                "measured value"
            )
            continue
        if item.strength not in SUPPORT_STRENGTHS:
            reasons.append(
                f"{item.id} carries {numeric.raw} but is {item.strength.value} evidence; a "
                "specific value needs a direct reading of the source"
            )
            continue
        problems = _compatibility_problems(mention, claim, numeric)
        if not problems:
            return NumericCheck(
                status="supported",
                evidence=item.id,
                reasons=(
                    f"{item.id} measured {numeric.raw} for {numeric.metric}"
                    f"{_on_dataset(numeric)} and the sentence still carries it",
                ),
            )
        if incompatible is None:
            incompatible = NumericCheck(
                status="incompatible", evidence=item.id, reasons=tuple(problems)
            )
    if incompatible is not None:
        return incompatible
    if not reasons:
        reasons.append(
            f"no accepted, source-observed evidence of {claim.id} measures {mention.text}"
        )
    return NumericCheck(status="unsupported", evidence=None, reasons=tuple(reasons))


def _on_dataset(numeric: NumericValue) -> str:
    return f" on {numeric.dataset}" if numeric.dataset else ""


def _same_number(mention: NumberMention, numeric: NumericValue) -> bool:
    """Equal after rounding to the precision the author wrote, percent scaling applied."""
    written = canonical_unit(mention.unit)
    measured = canonical_unit(numeric.unit)
    value = numeric.parsed
    if written == "percent" and measured == "fraction":
        value = value * 100.0
    elif written == "fraction" and measured == "percent":
        value = value / 100.0
    places = mention.precision
    return round(mention.value, places) == round(value, places)


def _compatibility_problems(
    mention: NumberMention, claim: Claim, numeric: NumericValue
) -> tuple[str, ...]:
    """Every way this sentence changes what the number means (Product 12)."""
    problems: list[str] = []
    written = canonical_unit(mention.unit)
    measured = canonical_unit(numeric.unit)
    scaled = {written, measured} == {"percent", "fraction"}
    if written is not None and measured is not None and written != measured and not scaled:
        problems.append(
            f"the sentence writes {mention.text!r} in {written}, but the evidence "
            f"measured {numeric.raw} in {measured}"
        )
    haystack = _haystack(mention, claim)
    if not _mentions(haystack, numeric.metric):
        problems.append(
            f"neither the sentence nor {claim.id} names the metric {numeric.metric!r} the "
            "value was measured for"
        )
    if numeric.dataset and not _mentions(haystack, numeric.dataset):
        problems.append(
            f"neither the sentence nor {claim.id} names the dataset {numeric.dataset!r} the "
            "value was measured on"
        )
    return tuple(problems)


def _haystack(mention: NumberMention, claim: Claim) -> str:
    """Everywhere a metric or dataset token may legitimately appear."""
    semantics = claim.semantics
    parts = [
        mention.context,
        claim.statement,
        semantics.subject,
        semantics.predicate,
        semantics.object,
        " ".join(semantics.qualifier.values()),
        claim.scope.corpus or "",
    ]
    return " ".join(parts).casefold()


_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _mentions(haystack: str, token: str) -> bool:
    """Case-insensitive whole-token search; ``F1`` must not match ``F10``."""
    needle = token.casefold().strip()
    if not needle:
        return False
    if needle in haystack:
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])")
        if pattern.search(haystack):
            return True
    parts = [part for part in _TOKEN_SPLIT_RE.split(needle) if part]
    return bool(parts) and all(
        re.search(rf"(?<![a-z0-9]){re.escape(part)}(?![a-z0-9])", haystack) for part in parts
    )

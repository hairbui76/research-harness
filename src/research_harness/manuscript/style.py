"""Style passes over manuscript *candidates*, and the semantic diff that bounds them.

Product 30.4 lets a humanization, venue-formatting, or copy-editing pass rewrite prose and
forbids it from changing what the prose claims. Product 42.L turns that into an acceptance
test: a pass that alters a protected span or strengthens/weakens a proposition may not
replace accepted manuscript text until semantic audit and human review succeed. This module
is the enforcement point for both.

Three deliberate limits are what make it enforceable rather than advisory:

* **Nothing here writes.** :func:`run_style_pass` computes a candidate and a diff;
  :func:`accept_style_pass` returns a *string* for the capability layer to persist. No
  function in this module opens a file, so a style pass cannot become an edit by accident.
* **The rewriter is someone else's.** A model, an editor, or a human paste supplies
  ``after``; the core only measures the distance between ``before`` and ``after``. A
  rewriter that never runs is the identity, and the identity is meaning-preserving.
* **The diff is a documented cue table, not a model.** Scope comes from
  :mod:`~research_harness.manuscript.wording`, numbers from
  :mod:`~research_harness.manuscript.support`, and protected spans from
  :mod:`~research_harness.manuscript.protected` - the same three readers the auditor uses,
  so a researcher can argue with a verdict by reading the table that produced it.

The bias is toward refusing. Merging two sentences reads as one proposition removed and one
added, a reordered number reads as an altered protected span, and a changed absence wording
reads as an escalation unless the counts say otherwise. Each of those *can* be an innocent
edit; each of them is also exactly how meaning drifts out of a manuscript one style pass at
a time, so the cheap error is the one that asks a researcher.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_harness.domain.enums import ClaimScope
from research_harness.domain.errors import AuthorityError
from research_harness.manuscript.latex import (
    SENTENCE_ABBREVIATIONS,
    citation_keys,
    normalize_sentence,
)
from research_harness.manuscript.protected import (
    ProtectedSpan,
    ProtectedSpanKind,
    find_protected_spans,
)
from research_harness.manuscript.support import numbers_in_sentence
from research_harness.manuscript.wording import HEDGE_CUES, wording_level

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported for annotations alone: `manuscript` must not depend on `plugins` at
    # runtime, because `plugins.spi` already reads `manuscript.protected`. A policy is
    # plain data, so reading one needs no import.
    from research_harness.plugins.spi import WritingPolicyContribution

__all__ = [
    "CORE_PROTECTED_SPAN_KINDS",
    "EPISTEMIC_QUALIFIERS",
    "NEGATIVE_EVIDENCE_CUES",
    "ChangeDirection",
    "ChangeReason",
    "Proposition",
    "PropositionChange",
    "ProtectedViolation",
    "SemanticDiff",
    "StyleFinding",
    "StylePassCandidate",
    "StylePolicy",
    "StyleReport",
    "StyleRule",
    "StyleSeverity",
    "TextSpan",
    "accept_style_pass",
    "apply_style_rules",
    "extract_propositions",
    "run_style_pass",
    "semantic_diff",
    "split_sentences",
]

CORE_PROTECTED_SPAN_KINDS: frozenset[ProtectedSpanKind] = frozenset(ProtectedSpanKind)
"""Every span a style pass must leave byte-identical; a policy may add, never subtract."""


# --------------------------------------------------------------------------------------
# cue vocabularies
# --------------------------------------------------------------------------------------

_MODAL_QUALIFIERS: tuple[str, ...] = (
    "appear to",
    "appears to",
    "arguably",
    "can be",
    "could",
    "in principle",
    "is expected to",
    "likely",
    "may",
    "might",
    "our results suggest",
    "possibly",
    "potentially",
    "presumably",
    "probably",
    "seem to",
    "seems to",
    "suggest",
    "suggests",
    "tend to",
    "tends to",
    "we believe",
    "we expect",
)
"""Epistemic modality a rewrite must not quietly drop (Product 30.4, "epistemic
qualifiers"). Deliberately narrow: only words that change how certain the sentence is."""

EPISTEMIC_QUALIFIERS: tuple[str, ...] = tuple(sorted({*_MODAL_QUALIFIERS, *HEDGE_CUES}))
"""Modality plus the coverage hedges of Product 10.5. Removing one strengthens a sentence
whether or not the scope ladder moved, which is what "hedge removed" means here."""

NEGATIVE_EVIDENCE_CUES: tuple[str, ...] = (
    "absent",
    "did not find",
    "do not exist",
    "does not exist",
    "has never been",
    "no evidence",
    "no existing work",
    "no prior work",
    "no published work",
    "no study",
    "no work exists",
    "none of",
    "not applicable",
    "not found",
    "not reported",
)
"""Bare absence wording. Product 11 keeps "we did not find" apart from "it does not
exist"; a rewrite that trades the first for the second has changed the claim, not the
prose, so any change to this set is reported (Product 42.F)."""

_BOUNDED_ABSENCE_CUES: frozenset[str] = frozenset(HEDGE_CUES)
"""The subset of absence wording that names the search actually performed."""


def _boundaries(phrase: str) -> re.Pattern[str]:
    return _compiled(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])")


def _contains(haystack: str, phrase: str) -> bool:
    """Whole-phrase match, so ``may`` never fires inside ``Mayer``."""
    return _boundaries(phrase).search(haystack) is not None


# --------------------------------------------------------------------------------------
# sentence splitting
# --------------------------------------------------------------------------------------

_PARAGRAPH_RE = re.compile(r"\n[ \t]*\n")
_TERMINATORS = ".?!"
_CLOSERS = ".?!\"')\u2019\u201d]"
_ABBREVIATION_TAIL_RE = re.compile(r"[A-Za-z][A-Za-z.]*\.$")
_ABBREVIATIONS: frozenset[str] = frozenset(item.casefold() for item in SENTENCE_ABBREVIATIONS)


def split_sentences(text: str) -> tuple[str, ...]:
    """Sentence-sized chunks of manuscript prose, protected spans kept whole.

    A terminator inside a citation, a quotation, math, a URL, or an identifier does not end
    a sentence, and neither does a known abbreviation (``et al.``, ``e.g.``). This is the
    style pass's own reader: :class:`~research_harness.manuscript.latex.LatexProject` needs
    a project on disk, and a candidate rewrite is a string that is not on disk yet.
    """
    sentences: list[str] = []
    for paragraph in _PARAGRAPH_RE.split(text):
        sentences.extend(_split_paragraph(paragraph))
    return tuple(sentences)


def _split_paragraph(text: str) -> list[str]:
    spans = find_protected_spans(text)
    sentences: list[str] = []
    start = 0
    index = 0
    span_index = 0
    length = len(text)
    while index < length:
        while span_index < len(spans) and spans[span_index].char_end <= index:
            span_index += 1
        span = spans[span_index] if span_index < len(spans) else None
        if span is not None and span.char_start <= index < span.char_end:
            index = span.char_end
            continue
        if text[index] not in _TERMINATORS:
            index += 1
            continue
        end = index + 1
        while end < length and text[end] in _CLOSERS:
            end += 1
        if (end >= length or text[end].isspace()) and not _is_abbreviation(text, index):
            chunk = text[start:end].strip()
            if chunk:
                sentences.append(chunk)
            start = end
        index = end
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_abbreviation(text: str, dot: int) -> bool:
    match = _ABBREVIATION_TAIL_RE.search(text[: dot + 1])
    return match is not None and match.group(0).casefold() in _ABBREVIATIONS


# --------------------------------------------------------------------------------------
# propositions
# --------------------------------------------------------------------------------------


class Proposition(BaseModel):
    """One sentence reduced to what a style pass may not change.

    ``text`` is the normalized sentence, so re-wrapping, ``~`` ties, and font wrappers are
    not differences. ``scope_level`` is ``None`` when the sentence carries no scope cue at
    all: "the model uses packet headers" asserts nothing about the literature, and that is
    different from asserting something at L0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    scope_level: ClaimScope | None = None
    numbers: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    qualifiers: tuple[str, ...] = ()
    negations: tuple[str, ...] = ()

    @property
    def effective_scope(self) -> ClaimScope:
        """Ladder level for comparison; a scopeless sentence sits on the L0 floor."""
        return self.scope_level or ClaimScope.INDIVIDUAL


def extract_propositions(sentence_text: str) -> tuple[Proposition, ...]:
    """One :class:`Proposition` per sentence of ``sentence_text``, in document order."""
    return tuple(_proposition(sentence) for sentence in split_sentences(sentence_text))


def _proposition(sentence: str) -> Proposition:
    normalized = normalize_sentence(sentence)
    haystack = normalized.casefold()
    estimate = wording_level(sentence)
    return Proposition(
        text=normalized,
        scope_level=estimate.level if estimate.cues else None,
        numbers=tuple(mention.text for mention in numbers_in_sentence(sentence)),
        citations=citation_keys(sentence),
        qualifiers=tuple(item for item in EPISTEMIC_QUALIFIERS if _contains(haystack, item)),
        negations=tuple(item for item in _ABSENCE_CUES if _contains(haystack, item)),
    )


_ABSENCE_CUES: tuple[str, ...] = tuple(sorted({*NEGATIVE_EVIDENCE_CUES, *HEDGE_CUES}))


# --------------------------------------------------------------------------------------
# the semantic diff
# --------------------------------------------------------------------------------------


class ChangeDirection(StrEnum):
    """Which way a rewritten proposition moved."""

    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"


class ChangeReason(StrEnum):
    """Why a rewritten proposition counts as a change of meaning."""

    SCOPE_ESCALATION = "scope_escalation"
    SCOPE_REDUCTION = "scope_reduction"
    HEDGE_REMOVED = "hedge_removed"
    HEDGE_ADDED = "hedge_added"
    NEGATIVE_EVIDENCE_WORDING = "negative_evidence_wording"


_STRENGTHENING: frozenset[ChangeReason] = frozenset(
    {ChangeReason.SCOPE_ESCALATION, ChangeReason.HEDGE_REMOVED}
)
_WEAKENING: frozenset[ChangeReason] = frozenset(
    {ChangeReason.SCOPE_REDUCTION, ChangeReason.HEDGE_ADDED}
)


class PropositionChange(BaseModel):
    """One aligned pair whose meaning moved, with every reason it moved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    before: Proposition
    after: Proposition
    direction: ChangeDirection
    reasons: tuple[ChangeReason, ...]

    @property
    def touches_negative_evidence(self) -> bool:
        """True when the rewrite changed absence wording (Product 11, 42.F)."""
        return ChangeReason.NEGATIVE_EVIDENCE_WORDING in self.reasons


class ProtectedViolation(BaseModel):
    """A protected span that the rewrite dropped, added, or altered (Product 30.4).

    ``before`` is ``None`` for a span the rewrite invented - adding a citation is as much
    a violation as losing one, because a style pass has no authority to cite anything.
    ``after`` is ``None`` for a span it lost.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProtectedSpanKind
    before: str | None = None
    after: str | None = None


class SemanticDiff(BaseModel):
    """What a rewrite did to the meaning of a passage (Product 30.4, 42.L)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    added: tuple[Proposition, ...] = ()
    removed: tuple[Proposition, ...] = ()
    strengthened: tuple[PropositionChange, ...] = ()
    weakened: tuple[PropositionChange, ...] = ()
    protected_violations: tuple[ProtectedViolation, ...] = ()
    unchanged: int = Field(default=0, ge=0)

    @property
    def is_meaning_preserving(self) -> bool:
        """True when nothing was added, removed, re-scoped, re-hedged, or altered."""
        return not (
            self.added
            or self.removed
            or self.strengthened
            or self.weakened
            or self.protected_violations
        )

    @property
    def negative_evidence_changes(self) -> tuple[PropositionChange, ...]:
        """Changes that rewrote an absence statement, whichever way they moved."""
        return tuple(
            change
            for change in (*self.strengthened, *self.weakened)
            if change.touches_negative_evidence
        )

    def summary(self) -> str:
        """One line naming what a researcher has to look at."""
        return (
            f"{len(self.added)} added, {len(self.removed)} removed, "
            f"{len(self.strengthened)} strengthened, {len(self.weakened)} weakened, "
            f"{len(self.protected_violations)} protected span(s) altered, "
            f"{self.unchanged} unchanged"
        )


def semantic_diff(before: str, after: str) -> SemanticDiff:
    """Compare two versions of the same passage proposition by proposition.

    Sentences are aligned with :mod:`difflib` over their normalized text, so a pure
    re-wrap aligns everything and a rewrite aligns sentence *n* with sentence *n*. An
    aligned pair is then read for scope, hedges, and absence wording; unaligned sentences
    are reported as added or removed rather than guessed at. Protected spans are compared
    across the whole passage, because moving a citation from one sentence into the next is
    not a loss and dropping it is.
    """
    left = extract_propositions(before)
    right = extract_propositions(after)
    matcher = difflib.SequenceMatcher(
        a=[item.text for item in left], b=[item.text for item in right], autojunk=False
    )
    added: list[Proposition] = []
    removed: list[Proposition] = []
    strengthened: list[PropositionChange] = []
    weakened: list[PropositionChange] = []
    unchanged = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
            continue
        if tag == "delete":
            removed.extend(left[i1:i2])
            continue
        if tag == "insert":
            added.extend(right[j1:j2])
            continue
        aligned = min(i2 - i1, j2 - j1)
        for offset in range(aligned):
            source, target = left[i1 + offset], right[j1 + offset]
            change = _compare(source, target)
            if change is None:
                unchanged += int(_survived(source, target))
            elif change.direction is ChangeDirection.STRENGTHENED:
                strengthened.append(change)
            else:
                weakened.append(change)
        removed.extend(left[i1 + aligned : i2])
        added.extend(right[j1 + aligned : j2])
    return SemanticDiff(
        added=tuple(added),
        removed=tuple(removed),
        strengthened=tuple(strengthened),
        weakened=tuple(weakened),
        protected_violations=_protected_violations(before, after),
        unchanged=unchanged,
    )


def _survived(before: Proposition, after: Proposition) -> bool:
    """True when a reworded sentence still carries the same numbers and citations.

    A pair whose meaning did not move but whose number did is not "unchanged"; its report
    is the protected violation, so it is counted in no bucket at all rather than in a
    bucket that reads like a clean bill of health.
    """
    return before.numbers == after.numbers and before.citations == after.citations


def _compare(before: Proposition, after: Proposition) -> PropositionChange | None:
    """Direction and reasons for one aligned pair, or ``None`` when only wording moved."""
    reasons: list[ChangeReason] = []
    if after.effective_scope > before.effective_scope:
        reasons.append(ChangeReason.SCOPE_ESCALATION)
    elif after.effective_scope < before.effective_scope:
        reasons.append(ChangeReason.SCOPE_REDUCTION)
    if set(before.qualifiers) - set(after.qualifiers):
        reasons.append(ChangeReason.HEDGE_REMOVED)
    if set(after.qualifiers) - set(before.qualifiers):
        reasons.append(ChangeReason.HEDGE_ADDED)
    absence = _absence_direction(before, after)
    if absence is not None:
        reasons.append(ChangeReason.NEGATIVE_EVIDENCE_WORDING)
    if not reasons:
        return None
    return PropositionChange(
        before=before,
        after=after,
        direction=_direction(reasons, absence),
        reasons=tuple(reasons),
    )


def _direction(reasons: Sequence[ChangeReason], absence: ChangeDirection | None) -> ChangeDirection:
    """Strengthening wins a tie: either bucket blocks acceptance, so err upward."""
    if any(reason in _STRENGTHENING for reason in reasons):
        return ChangeDirection.STRENGTHENED
    if any(reason in _WEAKENING for reason in reasons):
        return ChangeDirection.WEAKENED
    return absence or ChangeDirection.STRENGTHENED


def _absence_direction(before: Proposition, after: Proposition) -> ChangeDirection | None:
    """How an absence statement moved, or ``None`` when its wording is unchanged.

    Losing the bound on the search performed, or gaining a bare "does not exist", reads as
    an escalation; the reverse reads as a retreat. A change that does neither is still a
    change to an absence claim, and is reported as an escalation until a researcher says
    otherwise (Product 11).
    """
    if before.negations == after.negations:
        return None
    bounded_before = sum(1 for cue in before.negations if cue in _BOUNDED_ABSENCE_CUES)
    bounded_after = sum(1 for cue in after.negations if cue in _BOUNDED_ABSENCE_CUES)
    bare_before = len(before.negations) - bounded_before
    bare_after = len(after.negations) - bounded_after
    if bounded_after < bounded_before or bare_after > bare_before:
        return ChangeDirection.STRENGTHENED
    if bounded_after > bounded_before or bare_after < bare_before:
        return ChangeDirection.WEAKENED
    return ChangeDirection.STRENGTHENED


def _protected_violations(before: str, after: str) -> tuple[ProtectedViolation, ...]:
    """Every protected span the rewrite failed to carry over byte-identically."""
    left = _spans_by_kind(before)
    right = _spans_by_kind(after)
    violations: list[ProtectedViolation] = []
    for kind in ProtectedSpanKind:
        source = left.get(kind, ())
        target = right.get(kind, ())
        if source == target:
            continue
        matcher = difflib.SequenceMatcher(a=list(source), b=list(target), autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            aligned = min(i2 - i1, j2 - j1)
            violations.extend(
                ProtectedViolation(kind=kind, before=source[i1 + off], after=target[j1 + off])
                for off in range(aligned)
            )
            violations.extend(
                ProtectedViolation(kind=kind, before=text, after=None)
                for text in source[i1 + aligned : i2]
            )
            violations.extend(
                ProtectedViolation(kind=kind, before=None, after=text)
                for text in target[j1 + aligned : j2]
            )
    return tuple(violations)


def _spans_by_kind(text: str) -> Mapping[ProtectedSpanKind, tuple[str, ...]]:
    grouped: dict[ProtectedSpanKind, list[str]] = {}
    for span in find_protected_spans(text):
        grouped.setdefault(span.kind, []).append(span.text)
    return {kind: tuple(items) for kind, items in grouped.items()}


# --------------------------------------------------------------------------------------
# style rules
# --------------------------------------------------------------------------------------


class StyleSeverity(StrEnum):
    """How a style finding should be treated. Neither value blocks acceptance."""

    ERROR = "error"
    WARNING = "warning"


class TextSpan(BaseModel):
    """Where in the passage a finding sits, and what it matched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    text: str


@lru_cache(maxsize=1024)
def _compiled(pattern: str) -> re.Pattern[str]:
    """Compile once per distinct pattern; policies are re-applied per paragraph."""
    return re.compile(pattern)


class StyleRule(BaseModel):
    """One deterministic prose check: a regex, what it means, and what to do instead.

    Case sensitivity is the pattern's own business - write ``(?i)`` where a rule needs it -
    because some rules (title case, curly quotes) are *about* case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    pattern: str
    message: str
    suggestion: str = ""
    severity: StyleSeverity = StyleSeverity.WARNING

    @field_validator("pattern")
    @classmethod
    def _is_a_regex(cls, value: str) -> str:
        try:
            _compiled(value)
        except re.error as exc:
            raise ValueError(f"style rule pattern {value!r} is not a valid regex: {exc}") from exc
        return value


class StyleFinding(BaseModel):
    """One place a rule fired, outside every protected span."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    span: TextSpan
    message: str
    suggestion: str = ""
    severity: StyleSeverity = StyleSeverity.WARNING


class StyleReport(BaseModel):
    """What a policy found in one passage, in document order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: str
    findings: tuple[StyleFinding, ...] = ()

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Rules that fired at least once, in first-appearance order."""
        seen: list[str] = []
        for finding in self.findings:
            if finding.rule_id not in seen:
                seen.append(finding.rule_id)
        return tuple(seen)

    @property
    def errors(self) -> tuple[StyleFinding, ...]:
        """Error-severity findings. They inform review; they never block acceptance."""
        return tuple(item for item in self.findings if item.severity is StyleSeverity.ERROR)

    def of_rule(self, rule_id: str) -> tuple[StyleFinding, ...]:
        """Findings raised by one rule."""
        return tuple(item for item in self.findings if item.rule_id == rule_id)


class StylePolicy(BaseModel):
    """A loaded writing policy: rules to apply and spans to leave alone.

    ``authority`` is one-valued, mirroring
    :class:`~research_harness.plugins.spi.WritingPolicyContribution`. A policy proposes
    wording; it never upgrades scientific authority (ROADMAP Task 15.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str = "-"
    authority: Literal["candidate_only"] = "candidate_only"
    protected_spans: frozenset[ProtectedSpanKind] = CORE_PROTECTED_SPAN_KINDS
    rules: tuple[StyleRule, ...] = ()
    notes: tuple[str, ...] = ()
    """Guidance a person reads: the rules a regex cannot express, kept where the policy is."""

    @model_validator(mode="after")
    def _keeps_every_core_protection(self) -> StylePolicy:
        dropped = CORE_PROTECTED_SPAN_KINDS - self.protected_spans
        if dropped:
            names = ", ".join(sorted(kind.value for kind in dropped))
            raise ValueError(
                f"style policy {self.name!r} drops core protected spans: {names}; a style "
                "pass may change wording, never a protected span (Product 30.4)"
            )
        return self

    @classmethod
    def from_contribution(cls, contribution: WritingPolicyContribution) -> StylePolicy:
        """Load a policy from a plugin's ``WritingPolicyContribution``.

        ``style_rules`` carries prose guidance. An entry written ``"<rule name>: <text>"``
        whose key is one of this policy's wording constraints becomes that rule's
        suggestion; every other entry is kept verbatim in :attr:`notes`. The SPI has no
        per-rule suggestion field, and inventing one here would put the plugin contract in
        two places, so the convention lives in the plugin's README beside the YAML.
        """
        names = {constraint.name for constraint in contribution.wording_constraints}
        suggestions, notes = _split_guidance(contribution.style_rules, names)
        return cls(
            name=contribution.name,
            description=contribution.description,
            protected_spans=frozenset(contribution.protected_spans),
            rules=tuple(
                StyleRule(
                    rule_id=constraint.name,
                    pattern=constraint.pattern,
                    message=constraint.message,
                    suggestion=suggestions.get(constraint.name, ""),
                    severity=StyleSeverity(str(constraint.severity)),
                )
                for constraint in contribution.wording_constraints
            ),
            notes=notes,
        )


def _split_guidance(
    lines: Sequence[str], rule_names: set[str]
) -> tuple[Mapping[str, str], tuple[str, ...]]:
    suggestions: dict[str, str] = {}
    notes: list[str] = []
    for line in lines:
        key, separator, text = line.partition(":")
        name = key.strip()
        if separator and name in rule_names:
            suggestions[name] = text.strip()
        else:
            notes.append(line)
    return suggestions, tuple(notes)


def apply_style_rules(text: str, policy: StylePolicy) -> StyleReport:
    """Run every rule of ``policy`` over ``text``; deterministic, offline, no model.

    A match that overlaps a protected span is dropped rather than reported: humanizer §14
    already says "do not change a protected span merely to remove it", and a finding a
    writer is forbidden to act on is noise.
    """
    guarded = tuple(
        span for span in find_protected_spans(text) if span.kind in policy.protected_spans
    )
    findings: list[StyleFinding] = []
    for rule in policy.rules:
        for match in _compiled(rule.pattern).finditer(text):
            if match.end() == match.start() or _overlaps(guarded, match.start(), match.end()):
                continue
            findings.append(
                StyleFinding(
                    rule_id=rule.rule_id,
                    span=TextSpan(
                        char_start=match.start(), char_end=match.end(), text=match.group(0)
                    ),
                    message=rule.message,
                    suggestion=rule.suggestion,
                    severity=rule.severity,
                )
            )
    findings.sort(key=lambda item: (item.span.char_start, item.span.char_end, item.rule_id))
    return StyleReport(policy=policy.name, findings=tuple(findings))


def _overlaps(spans: Sequence[ProtectedSpan], start: int, end: int) -> bool:
    return any(span.char_start < end and start < span.char_end for span in spans)


# --------------------------------------------------------------------------------------
# the style pass
# --------------------------------------------------------------------------------------


class StylePassCandidate(BaseModel):
    """A proposed rewrite, the distance it travelled, and what that costs to accept.

    Candidate, not text: holding the before, the after, and the diff together is what lets
    review see the rewrite and the reason it needs reviewing at the same time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    before: str
    after: str
    diff: SemanticDiff
    report: StyleReport
    requires_review: bool
    audit_required: bool

    @model_validator(mode="after")
    def _gates_cannot_be_waived_by_construction(self) -> StylePassCandidate:
        if not self.diff.is_meaning_preserving and not self.requires_review:
            raise ValueError(
                "a candidate whose semantic diff is not meaning-preserving always requires "
                "human review (Product 42.L)"
            )
        if self.before != self.after and not self.audit_required:
            raise ValueError(
                "a changed candidate always requires manuscript audit before it can "
                "replace accepted manuscript text (Product 30.4)"
            )
        return self

    @property
    def changed(self) -> bool:
        """True when the rewriter proposed anything at all."""
        return self.before != self.after


def run_style_pass(
    text: str,
    policy: StylePolicy,
    *,
    rewriter: Callable[[str], str] | None = None,
) -> StylePassCandidate:
    """Apply ``policy`` to ``text`` and measure whatever ``rewriter`` proposed.

    The rewriter is a model, an editor, or a human paste - anything that turns a passage
    into a passage. It is *not* trusted: whatever it returns is measured against the
    original, and the result is a candidate. With no rewriter the pass is a read-only
    report on the text as it stands.

    Nothing is written. The returned ``after`` reaches a manuscript only through
    :func:`accept_style_pass` and the capability that persists it.
    """
    after = rewriter(text) if rewriter is not None else text
    diff = semantic_diff(text, after)
    return StylePassCandidate(
        before=text,
        after=after,
        diff=diff,
        report=apply_style_rules(after, policy),
        requires_review=not diff.is_meaning_preserving,
        audit_required=text != after,
    )


def accept_style_pass(
    candidate: StylePassCandidate,
    *,
    human_approved: bool = False,
    audit_ok: bool = False,
) -> str:
    """Return the text that may replace the passage, or refuse (Product 42.L).

    A meaning-preserving rewrite passes on its own: nothing was added, removed, re-scoped,
    re-hedged, or altered, so there is nothing for a researcher to decide. Anything else
    needs *both* an explicit human acceptance and a clean manuscript audit - a human
    waving through an unaudited rewrite and an audit standing in for a human are the two
    ways this gate is usually lost.

    Returning a string rather than writing one is deliberate: acceptance is still a
    capability call, and this function has no way to reach canonical state.
    """
    if candidate.diff.is_meaning_preserving and not candidate.requires_review:
        return candidate.after
    if human_approved and audit_ok:
        return candidate.after
    missing = ", ".join(
        name
        for name, given in (("human acceptance", human_approved), ("manuscript audit", audit_ok))
        if not given
    )
    raise AuthorityError(
        f"style pass under policy {candidate.report.policy!r} changed meaning "
        f"({candidate.diff.summary()}) and may not replace manuscript text without "
        f"{missing}"
    )

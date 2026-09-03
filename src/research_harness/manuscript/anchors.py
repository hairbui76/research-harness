"""Manuscript sentence -> Claim anchors, and the revalidation that keeps them honest.

Anchors are the first link of the traceability chain in Product 30.1. Following ADR-008,
revalidation never reattaches an anchor on its own: a moved sentence is reported with the
new location so the caller can decide, a reworded sentence goes ``stale`` for review, and a
vanished sentence goes ``missing``. Nothing here rewrites the manuscript or the anchor.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.base import Provenance
from research_harness.domain.enums import ManuscriptAnchorStatus, StaleState
from research_harness.domain.ids import ClaimId
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.manuscript.latex import LatexProject, Sentence

__all__ = [
    "STALE_SIMILARITY_THRESHOLD",
    "AnchorRevalidation",
    "anchor_key",
    "apply_revalidation",
    "build_anchor",
    "revalidate_all",
    "revalidate_anchor",
]

STALE_SIMILARITY_THRESHOLD = 0.75
"""Below this ``difflib`` ratio a rewritten sentence is a different sentence, not an edit."""


def build_anchor(
    sentence: Sentence,
    claim: ClaimId,
    provenance: Provenance,
) -> ManuscriptAnchor:
    """Anchor ``sentence`` to ``claim``: location, normalized text, fingerprint, citations.

    The normalized sentence is stored rather than the raw source, so that whitespace,
    comments, and citation-command churn do not present as content changes.
    """
    return ManuscriptAnchor(
        file=sentence.file,
        line_start=sentence.line_start,
        line_end=sentence.line_end,
        char_start=sentence.char_start,
        char_end=sentence.char_end,
        sentence=sentence.normalized_text,
        sentence_fingerprint=sentence.fingerprint,
        claim=claim,
        citation_keys=sentence.citation_keys,
        status=ManuscriptAnchorStatus.VALID,
        provenance=provenance,
    )


def anchor_key(anchor: ManuscriptAnchor) -> str:
    """``<file>#<sentence fingerprint>`` - the workspace's key for a stored anchor.

    Line and character offsets are deliberately absent: an anchor that only moved keeps
    its key, so re-running the parser after an edit elsewhere does not orphan it.
    """
    return f"{anchor.file}#{anchor.sentence_fingerprint}"


class AnchorRevalidation(BaseModel):
    """The verdict on one anchor after re-parsing the manuscript.

    ``relocated`` is set when the sentence was found somewhere other than the recorded
    span - for a ``VALID`` result it is the same sentence at a new location, for a
    ``STALE`` result it is the best rewrite candidate. Applying it is the caller's choice.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ManuscriptAnchorStatus
    anchor: ManuscriptAnchor
    relocated: Sentence | None = None
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str


def revalidate_anchor(anchor: ManuscriptAnchor, project: LatexProject) -> AnchorRevalidation:
    """Re-find ``anchor``'s sentence in ``project`` and report valid, stale, or missing.

    An exact fingerprint match anywhere in the same file is ``VALID`` (with ``relocated``
    set when the span moved). Otherwise the closest sentence in that file by
    :class:`difflib.SequenceMatcher` ratio decides: at or above
    :data:`STALE_SIMILARITY_THRESHOLD` the anchor is ``STALE`` and carries the candidate
    and its similarity; below it the anchor is ``MISSING``. A stale anchor is never
    silently retained and never silently moved (ADR-008).
    """
    candidates = project.sentences_for_file(anchor.file)
    if not candidates:
        return AnchorRevalidation(
            status=ManuscriptAnchorStatus.MISSING,
            anchor=anchor,
            reason=f"{anchor.file} is no longer part of the manuscript, or has no sentences",
        )

    for sentence in candidates:
        if sentence.fingerprint == anchor.sentence_fingerprint:
            moved = (
                sentence.char_start != anchor.char_start or sentence.line_start != anchor.line_start
            )
            return AnchorRevalidation(
                status=ManuscriptAnchorStatus.VALID,
                anchor=anchor,
                relocated=sentence if moved else None,
                similarity=1.0,
                reason=(
                    f"sentence unchanged; moved to lines {sentence.line_start}-{sentence.line_end}"
                    if moved
                    else "sentence unchanged at the recorded span"
                ),
            )

    best, ratio = _closest(anchor.sentence, candidates)
    if best is not None and ratio >= STALE_SIMILARITY_THRESHOLD:
        return AnchorRevalidation(
            status=ManuscriptAnchorStatus.STALE,
            anchor=anchor,
            relocated=best,
            similarity=ratio,
            reason=(
                f"sentence was reworded (similarity {ratio:.2f} at lines "
                f"{best.line_start}-{best.line_end}); the anchor needs revalidation"
            ),
        )
    return AnchorRevalidation(
        status=ManuscriptAnchorStatus.MISSING,
        anchor=anchor,
        reason=(
            f"no sentence in {anchor.file} resembles the anchored text "
            f"(best similarity {ratio:.2f})"
        ),
    )


def revalidate_all(
    anchors: tuple[ManuscriptAnchor, ...] | list[ManuscriptAnchor],
    project: LatexProject,
) -> tuple[AnchorRevalidation, ...]:
    """Revalidate every anchor against one parse of the manuscript, in the given order."""
    return tuple(revalidate_anchor(anchor, project) for anchor in anchors)


def apply_revalidation(result: AnchorRevalidation) -> ManuscriptAnchor:
    """The anchor updated to record ``result``; an explicit caller action, never automatic.

    A ``VALID`` relocation adopts the new span (the sentence is provably the same text). A
    ``STALE`` or ``MISSING`` result only records the status and marks the anchor stale: the
    text it points at is a question for a human, so the fingerprint is left alone.
    """
    anchor = result.anchor
    if result.status is ManuscriptAnchorStatus.VALID:
        moved = result.relocated
        if moved is None:
            return (
                anchor
                if anchor.status is ManuscriptAnchorStatus.VALID
                else anchor.touch(status=ManuscriptAnchorStatus.VALID)
            )
        return anchor.touch(
            status=ManuscriptAnchorStatus.VALID,
            line_start=moved.line_start,
            line_end=moved.line_end,
            char_start=moved.char_start,
            char_end=moved.char_end,
        )
    return anchor.touch(status=result.status, stale=StaleState.STALE)


def _closest(text: str, candidates: tuple[Sentence, ...]) -> tuple[Sentence | None, float]:
    matcher = SequenceMatcher(a=text, autojunk=False)
    best: Sentence | None = None
    best_ratio = 0.0
    for sentence in candidates:
        matcher.set_seq2(sentence.normalized_text)
        if matcher.real_quick_ratio() < best_ratio or matcher.quick_ratio() < best_ratio:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best, best_ratio = sentence, ratio
    return best, best_ratio

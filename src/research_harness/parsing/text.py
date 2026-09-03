"""Text normalization and hashing shared by every parser (Product 16).

Anchors are replayed by comparing content hashes, so the exact normalization applied to
extracted text is part of the parser contract: the same bytes and the same parser version
must always produce the same string, and therefore the same ``text_hash``.
"""

from __future__ import annotations

import hashlib
import re

from research_harness.domain.base import Sha256

__all__ = [
    "LIGATURES",
    "collapse_whitespace",
    "join_hyphenation",
    "normalize_text",
    "text_sha256",
]

LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}

#: Characters that carry no textual meaning once extracted from a PDF.
_INVISIBLE = str.maketrans(dict.fromkeys("\u00ad\u200b\u200c\u200d\ufeff"))

#: Space-like characters PDFs use that must collapse into a plain space.
_SPACE_LIKE = re.compile("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\t\v\f]")

#: A word broken across a line end: the hyphen disappears only when the continuation is
#: lowercase. A capitalized continuation keeps the hyphen ("Trans-\nAtlantic" ->
#: "Trans-Atlantic"), because there the hyphen is part of the compound.
_HYPHENATION = re.compile("(?<=[A-Za-z])[-\u2010\u00ad]\n(?=[a-z])")
_HYPHEN_LINE_BREAK = re.compile("(?<=[A-Za-z][-\u2010])\n(?=[A-Za-z])")

_WHITESPACE = re.compile(r"\s+")


def join_hyphenation(text: str) -> str:
    """Join words split by a hyphen at a line end (``represen-\\ntation`` -> ``representation``)."""
    return _HYPHEN_LINE_BREAK.sub("", _HYPHENATION.sub("", text))


def collapse_whitespace(text: str) -> str:
    """Collapse every whitespace run, newlines included, into a single space, then strip."""
    return _WHITESPACE.sub(" ", text).strip()


def normalize_text(text: str) -> str:
    """Canonical form of extracted text: ligatures expanded, hyphenation joined, space collapsed.

    Deliberately conservative: it never changes dashes, quotes, or letter case, because an
    anchor's ``exact_text`` must still be quotable as the source wrote it.
    """
    for ligature, replacement in LIGATURES.items():
        text = text.replace(ligature, replacement)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE_LIKE.sub(" ", text)
    text = join_hyphenation(text)
    text = text.translate(_INVISIBLE)
    return collapse_whitespace(text)


def text_sha256(text: str) -> Sha256:
    """``sha256:<hex>`` over the UTF-8 bytes of ``text`` exactly as given.

    Callers pass text that is already normalized; hashing raw extractor output would make
    anchors depend on incidental PDF layout.
    """
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

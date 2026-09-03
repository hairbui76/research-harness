"""Decodability scoring and constant-offset recovery for fonts with no usable ToUnicode map.

A subsetted publisher font shipped without a ToUnicode CMap makes an extractor hand back
raw character codes, so its text arrives as a constant-offset cipher: ``VHUYLFH`` for
``SERVICE``, ``3ODLQWH[W`` for ``Plaintext``. The text is not corrupt, it is displaced, and
the displacement is the same for every code point the font draws.

The rules here are dictionary-free and purely statistical, so the same bytes always yield
the same verdict and the same recovery (Product 16, Product 43 "parser instability"):

* a word is *plausible* English when its vowel ratio is in range, it has no long consonant
  run, and most of its letter pairs are common English bigrams (`COMMON_BIGRAMS`);
* text is *decodable* when plausible words carry at least `DECODABLE_SCORE` of its letters,
  or when it holds too few Latin letters to judge at all - silence, never a guess;
* an offset is *recovered* only from a sample of at least `MIN_LETTERS_TO_FIT` letters, only
  when shifting by it lifts `RECOVERY_SCORE` of that font's words to plausible - the
  ">= 80 percent of the font's words" bar - and only when it turns codes into letters rather
  than into symbols; among the offsets that qualify, the best-reading one is applied.

Nothing here rewrites text on its own: `shift_text` is applied by the parser to the spans of
the one font an offset was validated for, and text that cannot be recovered is kept exactly
as extracted and reported through `ParseDiagnostics` instead.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence

from research_harness.parsing.base import BlockQuality

__all__ = [
    "BIGRAM_HIT_RATIO",
    "COMMON_BIGRAMS",
    "DECODABLE_SCORE",
    "MAX_CONSONANT_RUN",
    "MIN_LETTERS_TO_FIT",
    "MIN_LETTERS_TO_JUDGE",
    "OFFSET_LIMIT",
    "RECOVERY_SCORE",
    "ascii_letters",
    "assess_text",
    "detect_offset",
    "english_score",
    "letter_share",
    "offset_qualifies",
    "recovery_score",
    "shift_text",
    "unreadable_ratio",
    "verify_offset",
    "word_is_plausible",
]

#: Written as one run-on table rather than 280 quoted strings, so it reads as a table.
_BIGRAM_TABLE = """
    ab ac ad af ag ai al am an ap ar as at au av aw ax ay ba bb be bi bj bl bo br bs bu by
    ca cc ce ch ci ck cl co cr ct cu cy da dd de di do dr ds du dg ea eb ec ed ee ef eg el
    em en ep eq er es et eu ev ew ex ey fa fe ff fi fl fo fr ft fu fy ga ge gg gh gi gl gn
    go gr gu ha he hi hm hn ho hr hu hy ia ib ic id ie if ig il im in io ip ir is it iu iv
    ix iz je ka ke ki kl kn ks ky la lb lc ld le lf lg li lk ll lm lo lp ls lt lu lv ly ma
    mb me mi ml mm mn mo mp ms mu my na nc nd ne nf ng ni nj nk nl nn no ns nt nu nv ob oa
    oc od oe og oi oj ol om on oo op or os ot ou ov ow oy pa pe ph pi pl po pp pr pt pu py
    qu ra rb rc rd re rf rg rh ri rk rl rm rn ro rp rr rs rt ru rv ry sa sc se sh si sk sl
    sm sn so sp sq ss st su sw sy ta tc te th ti tl to tr ts tt tu tw ty ua ub uc ud ue ug
    ui ul um un up ur us ut uv va ve vi vo vs wa we wh wi wl wn wo wr ws xi xp xt ya ye yl
    ym yn yo yp yr ys za ze zi zo zz
"""
COMMON_BIGRAMS = frozenset(_BIGRAM_TABLE.split())
"""Letter pairs covering ~98 percent of running English text.

Membership, not frequency, is what the score uses: a cipher scrambles which pairs occur, so
the hit rate collapses even where the vowel ratio survives.
"""

_VOWELS = frozenset("aeiouy")
_ASCII_WORD = re.compile(r"[A-Za-z]{2,}")

#: Below this share of letters carried by plausible words, text is reported undecodable.
DECODABLE_SCORE = 0.5
#: A font's offset is accepted only when the shifted text reaches this score.
RECOVERY_SCORE = 0.8
#: Fewer Latin letters than this and no verdict is passed: absence of evidence, not evidence.
MIN_LETTERS_TO_JUDGE = 8
#: Fewer Latin letters than this and no offset is fitted: a handful of letters can be made
#: to read like English by some shift or other, so a short sample is left alone.
MIN_LETTERS_TO_FIT = 48
#: Longest run of consonants an English word is allowed before it is called implausible.
MAX_CONSONANT_RUN = 4
#: Share of a word's letter pairs that must be common English bigrams. Half is not enough:
#: a shifted word lands that many by chance.
BIGRAM_HIT_RATIO = 0.6
#: Offsets searched in both directions; a font's codes stay inside printable ASCII, so an
#: offset larger than the printable range cannot be the one that produced them.
OFFSET_LIMIT = 94
#: Above this share of control or private-use characters, no word test is needed.
UNREADABLE_RATIO = 0.2

_LONG_CONSONANTS = re.compile(f"[^aeiouy]{{{MAX_CONSONANT_RUN + 1},}}")

#: Codes a displaced font draws, and therefore the codes a shift is applied to. A shift may
#: land on a space - in these fonts the space glyph sits at the bottom of the range - but a
#: space is never shifted, because the layout's own spaces are not the font's codes.
_VISIBLE_ASCII = range(0x21, 0x7F)
_PRINTABLE_ASCII = range(0x20, 0x7F)


def _is_unreadable(char: str) -> bool:
    """True for a control code, a private-use code point, or an unassigned surrogate."""
    code = ord(char)
    return (
        code < 0x20
        or code == 0x7F
        or 0xE000 <= code <= 0xF8FF
        or 0xF0000 <= code <= 0x10FFFD
        or 0xD800 <= code <= 0xDFFF
    )


def unreadable_ratio(text: str) -> float:
    """Share of the non-space characters that no font could legitimately have drawn."""
    dense = [char for char in text if not char.isspace()]
    if not dense:
        return 0.0
    return sum(1 for char in dense if _is_unreadable(char)) / len(dense)


def shift_text(text: str, offset: int) -> str:
    """Add ``offset`` to every visible-ASCII code point, leaving everything else alone.

    Whitespace and non-ASCII characters are untouched, because a displaced font displaces
    the codes it draws, not the whitespace the layout inserted between them. A control code
    that is not whitespace becomes a space: in these fonts it is the space glyph's own code.
    """
    out: list[str] = []
    for char in text:
        code = ord(char)
        if code in _VISIBLE_ASCII:
            shifted = code + offset
            out.append(chr(shifted) if shifted in _PRINTABLE_ASCII else char)
        elif char.isspace():
            out.append(char)
        elif code < 0x20 or code == 0x7F:
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def word_is_plausible(word: str) -> bool:
    """True when an ASCII word could be English: vowels in range, no long consonant run,
    and at least `BIGRAM_HIT_RATIO` of its letter pairs among `COMMON_BIGRAMS`.

    A displaced word keeps a believable vowel ratio - `vhuylfh` has two vowels in seven -
    so the bigrams are what decides; half of them landing by chance is not enough.
    """
    lowered = word.lower()
    if len(lowered) < 2:
        return False
    vowels = sum(1 for char in lowered if char in _VOWELS)
    ratio = vowels / len(lowered)
    if not 0.15 <= ratio <= 0.85:
        return False
    if _LONG_CONSONANTS.search(lowered):
        return False
    if "q" in lowered and "qu" not in lowered:
        return False
    pairs = [lowered[index : index + 2] for index in range(len(lowered) - 1)]
    hits = sum(1 for pair in pairs if pair in COMMON_BIGRAMS)
    return hits >= math.ceil(BIGRAM_HIT_RATIO * len(pairs))


def english_score(text: str) -> float:
    """Share of the ASCII-word letters in ``text`` that sit inside a plausible English word.

    Letter-weighted on purpose: one implausible acronym ("SFTP", "CCS") must not outvote the
    long words around it, and a cipher makes long words implausible first.
    """
    words = _ASCII_WORD.findall(text)
    letters = sum(len(word) for word in words)
    if not letters:
        return 0.0
    return sum(len(word) for word in words if word_is_plausible(word)) / letters


def letter_share(text: str) -> float:
    """Share of the non-space characters that are ASCII letters at all.

    `english_score` only sees the letter runs it can find, so a wrong offset that leaves
    `&<BAB/2` scores well on the accidental `BAB`. This is the counterweight: the right
    offset for a displaced font turns almost every code into a letter, a wrong one does not.
    """
    dense = [char for char in text if not char.isspace()]
    if not dense:
        return 0.0
    return sum(1 for char in dense if char.isascii() and char.isalpha()) / len(dense)


def recovery_score(text: str) -> float:
    """How much of ``text`` reads as English: plausible words weighted by letter density.

    `offset_qualifies` decides which offsets are admissible; this is what ranks them, so the
    winner is the one that reads best over the whole string rather than over the fragments
    of it that happen to be letters.
    """
    return english_score(text) * letter_share(text)


def ascii_letters(text: str) -> int:
    """Count of ASCII letters: the evidence available to judge text by."""
    return sum(len(word) for word in _ASCII_WORD.findall(text))


def offset_qualifies(raw: str, offset: int, *, minimum: float = RECOVERY_SCORE) -> bool:
    """True when shifting ``raw`` by ``offset`` clears the bar for rewriting a font's text.

    Two conditions, both necessary: at least ``minimum`` of the shifted letters form
    plausible words - the ">= 80 percent of that font's words" rule - and the shift must not
    turn letters into symbols, which is what every near-miss offset does.
    """
    shifted = shift_text(raw, offset)
    return english_score(shifted) >= minimum and letter_share(shifted) >= letter_share(raw)


def detect_offset(texts: Iterable[str], *, minimum: float = RECOVERY_SCORE) -> int | None:
    """The single code-point offset that turns ``texts`` into English, or None.

    Returns None when the text already reads as English, when there is less of it than
    `MIN_LETTERS_TO_FIT` (too little to fit an offset against without inventing one), or
    when no offset qualifies. Among qualifying offsets the best-reading one wins, ties going
    to the smallest shift, so the answer never depends on iteration order.
    """
    joined = "\n".join(texts)
    if ascii_letters(joined) < MIN_LETTERS_TO_FIT:
        return None
    if english_score(joined) >= DECODABLE_SCORE:
        return None
    ranked = [
        (round(recovery_score(shift_text(joined, offset)), 6), -abs(offset), -offset, offset)
        for offset in _candidate_offsets()
        if offset_qualifies(joined, offset, minimum=minimum)
    ]
    return max(ranked)[3] if ranked else None


def verify_offset(texts: Iterable[str], offset: int, *, minimum: float = RECOVERY_SCORE) -> bool:
    """True when ``offset`` - found elsewhere in the document - also reads here.

    This is how a font with too little text on one page borrows the offset validated for the
    same font on another: the offset is never re-fitted, only re-checked.
    """
    joined = "\n".join(texts)
    if ascii_letters(joined) < MIN_LETTERS_TO_JUDGE:
        return False
    return offset_qualifies(joined, offset, minimum=minimum)


def _candidate_offsets() -> Sequence[int]:
    """Every non-zero offset within `OFFSET_LIMIT`, nearest first, negative before positive."""
    offsets: list[int] = []
    for size in range(1, OFFSET_LIMIT + 1):
        offsets.extend((-size, size))
    return offsets


def assess_text(text: str) -> BlockQuality:
    """Judge one block's text: readable, unreadable, or too little evidence to say.

    A block is never called undecodable for being short, numeric, or non-Latin; only the
    presence of characters no font draws, or words that no shift of the alphabet would make
    English, condemns it.
    """
    if not text.strip():
        return BlockQuality(decodable=True, confidence=0.0, reason=None)
    unreadable = unreadable_ratio(text)
    if unreadable >= UNREADABLE_RATIO:
        return BlockQuality(
            decodable=False,
            confidence=round(min(1.0, unreadable), 3),
            reason=f"{unreadable:.0%} of the characters are control or private-use codes",
        )
    letters = ascii_letters(text)
    if letters < MIN_LETTERS_TO_JUDGE:
        return BlockQuality(
            decodable=True,
            confidence=0.0,
            reason=f"only {letters} Latin letters: too little text to judge",
        )
    score = english_score(text)
    evidence = min(1.0, letters / 40)
    confidence = round(evidence * abs(score - DECODABLE_SCORE) * 2, 3)
    if score >= DECODABLE_SCORE:
        return BlockQuality(decodable=True, confidence=confidence, reason=None)
    return BlockQuality(
        decodable=False,
        confidence=confidence,
        reason=f"{score:.0%} of the letters form plausible words; no offset recovered them",
    )

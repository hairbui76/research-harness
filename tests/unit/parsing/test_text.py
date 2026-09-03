"""Text normalization is part of the parser contract: same bytes, same string, same hash."""

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from research_harness.domain.base import SHA256_PATTERN
from research_harness.parsing.text import (
    collapse_whitespace,
    join_hyphenation,
    normalize_text,
    text_sha256,
)


def test_ligatures_are_expanded_to_ascii_letters() -> None:
    assert normalize_text("classiﬁcation of trafﬁc ﬂows") == "classification of traffic flows"


def test_hyphenation_at_a_line_end_is_joined() -> None:
    assert normalize_text("represen-\ntation learning") == "representation learning"


def test_a_soft_hyphen_line_break_is_joined_too() -> None:
    assert normalize_text("classi\u00ad\nfication") == "classification"


def test_a_genuine_compound_keeps_its_hyphen() -> None:
    assert normalize_text("Trans-\nAtlantic capture") == "Trans-Atlantic capture"
    assert normalize_text("state-of-the-art detector") == "state-of-the-art detector"


def test_whitespace_including_newlines_and_nbsp_collapses() -> None:
    raw = "  one\n two\u00a0\u2009three\t\n\n four "
    assert normalize_text(raw) == "one two three four"


def test_zero_width_characters_are_dropped() -> None:
    assert normalize_text("CICIDS\u200b2017") == "CICIDS2017"


def test_dashes_and_case_are_preserved() -> None:
    text = "F1 \u2013 the harmonic mean \u2014 of Precision and Recall"
    assert normalize_text(text) == text


def test_join_hyphenation_and_collapse_whitespace_are_usable_alone() -> None:
    assert join_hyphenation("flow-\nlevel") == "flowlevel"
    assert collapse_whitespace(" a \n b ") == "a b"


def test_text_sha256_is_a_canonical_digest() -> None:
    digest = text_sha256("94.32")
    assert re.fullmatch(SHA256_PATTERN, digest)
    assert digest == text_sha256("94.32")
    assert digest != text_sha256("94.33")


def test_text_sha256_hashes_the_string_it_is_given_not_a_normalized_form() -> None:
    assert text_sha256("a  b") != text_sha256("a b")


@given(st.text())
def test_normalization_is_idempotent(raw: str) -> None:
    once = normalize_text(raw)
    assert normalize_text(once) == once


@given(st.text())
def test_normalized_text_always_hashes(raw: str) -> None:
    assert re.fullmatch(SHA256_PATTERN, text_sha256(normalize_text(raw)))

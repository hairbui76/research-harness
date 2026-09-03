"""Decodability scoring and offset recovery: the rules that decide whether text is readable.

These are the heuristics a reviewer has to trust, so each test states the property it holds
rather than a threshold: English survives, ciphers do not, and no verdict is passed on text
too short to judge.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_harness.parsing.quality import (
    MIN_LETTERS_TO_FIT,
    assess_text,
    detect_offset,
    english_score,
    letter_share,
    offset_qualifies,
    recovery_score,
    shift_text,
    unreadable_ratio,
    verify_offset,
    word_is_plausible,
)

ENGLISH = (
    "The major limitation of existing solutions is that they highly rely on the deep "
    "features, which are overly dependent on data size and hard to generalize on unseen data."
)
LABELS = (
    "Plaintext Features Statistical Features service certificate Raw Traffic arrival time "
    "Unsupervised Pre-training Supervised Fine-tuning"
)
#: The same labels without punctuation, so a large shift of them stays inside printable
#: ASCII and the displacement is exactly reversible - as it is in a real subsetted font.
SHIFTABLE = (
    "Plaintext Features Statistical Features service certificate Raw Traffic arrival time "
    "Unsupervised Pretraining Supervised Finetuning"
)
APP_LABELS = (
    ":PVUVCF\x01 7JNFP\x01 5PSSFOU\x01 4QPUJGZ\x01 /FUGMJY\x01 7PJQCVTUFS\x01 4LZQF\x01 "
    "'BDFCPPL\x01 *OTUBHSBN\x01 5XJUUFS\x01 8IBUTBQQ\x01 5FMFHSBN"
)


def caesar(text: str, shift: int) -> str:
    """Displace every visible ASCII code point, the way a broken subset font does."""
    return "".join(
        chr(ord(char) + shift) if 0x21 <= ord(char) + shift <= 0x7E else char for char in text
    )


# -- word plausibility ---------------------------------------------------------------


@pytest.mark.parametrize(
    "word", ["service", "fingerprint", "classification", "traffic", "encrypted", "burst", "the"]
)
def test_ordinary_english_words_are_plausible(word: str) -> None:
    assert word_is_plausible(word)


@pytest.mark.parametrize("word", ["vhuylfh", "ilqjhusulqw", "ncuukhkecvkqp", "zxqj", "vkpf"])
def test_shifted_and_vowelless_words_are_not_plausible(word: str) -> None:
    assert not word_is_plausible(word)


def test_case_never_changes_the_verdict() -> None:
    assert word_is_plausible("SERVICE") == word_is_plausible("service")
    assert not word_is_plausible("VHUYLFH")


def test_english_score_is_letter_weighted_so_one_acronym_does_not_outvote_a_sentence() -> None:
    assert english_score(ENGLISH) > 0.9
    assert english_score("CCS CONCEPTS") > 0.5
    assert english_score(caesar(ENGLISH, 3)) < 0.5


def test_letter_share_separates_text_from_symbol_soup() -> None:
    assert letter_share("Youtube Torrent Netflix") == 1.0
    assert letter_share("&<BAB/2 %$#") < 0.5
    assert recovery_score("&<BAB/2 %$#") < recovery_score(ENGLISH)


# -- shifting ------------------------------------------------------------------------


def test_shifting_recovers_a_displaced_font_including_its_spaces() -> None:
    """`#` is what a `+3` font draws for a space, so the shift must give the space back."""
    assert shift_text("VHUYLFH", -3) == "SERVICE"
    assert shift_text("Vhuylfh#Ilqjhusulqw", -3) == "Service Fingerprint"
    assert shift_text("3ODLQWH[W\x03)HDWXUHV", 29) == "Plaintext Features"


def test_shifting_leaves_whitespace_and_non_ascii_alone() -> None:
    assert shift_text("a b\nc", 1) == "b c\nd"
    assert shift_text("中文 abc", 1) == "中文 bcd"


def test_a_control_code_becomes_a_space_at_any_offset() -> None:
    assert shift_text("a\x03b", 0) == "a b"
    assert shift_text("\x01\x02", 7) == "  "


@given(st.text(alphabet=st.characters(min_codepoint=0x22, max_codepoint=0x7D), max_size=40))
def test_shifting_by_an_offset_and_back_is_the_identity(text: str) -> None:
    """Only true while every code stays inside printable ASCII, which is where fonts live."""
    assert shift_text(shift_text(text, 1), -1) == text


# -- offset detection ----------------------------------------------------------------


def test_a_consistent_shift_is_detected_and_recovers_the_text() -> None:
    offset = detect_offset([caesar(LABELS, 3)])
    assert offset == -3
    assert shift_text(caesar(LABELS, 3), offset) == LABELS


@pytest.mark.parametrize("offset", [-3, 3, 5, 29, 31])
def test_any_constant_displacement_is_found_and_undone(offset: int) -> None:
    """``offset`` is what recovery adds back, so the font displaced its codes by ``-offset``."""
    displaced = caesar(SHIFTABLE, -offset)
    assert shift_text(displaced, offset) == SHIFTABLE, "sample must be exactly reversible"
    assert detect_offset([displaced]) == offset


def test_text_that_already_reads_as_english_is_never_shifted() -> None:
    assert detect_offset([ENGLISH]) is None
    assert detect_offset([LABELS]) is None


def test_a_sample_too_short_to_validate_against_is_left_alone() -> None:
    """A handful of letters can be made to read like English by some shift or other."""
    short = "4.1.1 DatasetsandDownstreamTasks."
    assert len([c for c in short if c.isalpha()]) < MIN_LETTERS_TO_FIT
    assert detect_offset([short]) is None


def test_an_offset_that_turns_letters_into_symbols_never_qualifies() -> None:
    """`:PVUVCF` is `Youtube` at +31; the near-miss -20 leaves `&<BAB/2` and must lose."""
    assert not offset_qualifies(APP_LABELS, -20)
    assert english_score(shift_text(APP_LABELS, -20)) > 0.5, "the near-miss reads well by words"
    assert letter_share(shift_text(APP_LABELS, -20)) < letter_share(APP_LABELS)
    assert detect_offset([APP_LABELS]) == 31
    assert "Youtube" in shift_text(APP_LABELS, 31)


def test_random_letters_are_not_recovered_into_english() -> None:
    assert detect_offset(["Zxqj Vkpf Wbtn Zxqj Vkpf Wbtn Zxqj Vkpf Wbtn Zxqj Vkpf Wbtn"]) is None


def test_a_borrowed_offset_is_re_checked_and_not_re_fitted() -> None:
    assert verify_offset([caesar("service fingerprint", 3)], -3)
    assert not verify_offset([caesar("service fingerprint", 3)], -4)
    assert not verify_offset(["12.5"], -3)


# -- block quality -------------------------------------------------------------------


def test_readable_text_is_decodable_with_a_reason_of_none() -> None:
    quality = assess_text(ENGLISH)
    assert quality.decodable and quality.reason is None
    assert quality.confidence > 0.5


def test_ciphered_text_is_undecodable_and_says_why() -> None:
    quality = assess_text(caesar(LABELS, 3))
    assert not quality.decodable
    assert quality.reason is not None and "plausible" in quality.reason


def test_control_and_private_use_characters_condemn_text_without_a_word_test() -> None:
    quality = assess_text("ś\x03ś\x03ś")
    assert not quality.decodable
    assert quality.reason is not None and "control" in quality.reason
    assert unreadable_ratio("ś\x03ś\x03ś") > 0.2


def test_numbers_short_labels_and_non_latin_text_are_never_condemned() -> None:
    """Absence of Latin letters is absence of evidence, not evidence of a broken font."""
    for text in ("94.32 | 93.10", "F1", "加密流量分类", ""):
        quality = assess_text(text)
        assert quality.decodable, text
        assert quality.confidence == 0.0


def test_confidence_grows_with_the_evidence_available() -> None:
    little = assess_text("The traffic is encrypted.")
    much = assess_text(ENGLISH)
    assert 0.0 < little.confidence < much.confidence <= 1.0

"""Spans a style pass may not touch, with offsets exact enough to diff against."""

from __future__ import annotations

from itertools import pairwise

import pytest

from research_harness.manuscript import (
    ProtectedSpan,
    ProtectedSpanKind,
    find_protected_spans,
)

SENTENCE = r"We report 94.3\% F1 \citep{kraus2019} on $x_i$ for claim C0041."


def kinds(text: str) -> list[ProtectedSpanKind]:
    return [span.kind for span in find_protected_spans(text)]


def only(text: str, kind: ProtectedSpanKind) -> ProtectedSpan:
    spans = [span for span in find_protected_spans(text) if span.kind is kind]
    assert len(spans) == 1, f"expected exactly one {kind} span in {text!r}, got {spans}"
    return spans[0]


def test_every_span_offset_slices_back_to_its_own_text() -> None:
    for span in find_protected_spans(SENTENCE):
        assert SENTENCE[span.char_start : span.char_end] == span.text


def test_a_citation_command_is_one_span_covering_its_optional_arguments() -> None:
    text = r"Evidence E0132 supports \citet[p.~3]{ostrom2020} at 95\%."
    span = only(text, ProtectedSpanKind.CITATION)
    assert span.text == r"\citet[p.~3]{ostrom2020}"
    assert (span.char_start, span.char_end) == (24, 48)


def test_cross_references_are_protected_separately_from_citations() -> None:
    text = r"See \eqref{eq:f1} and \cref{sec:intro}."
    spans = find_protected_spans(text)
    assert [span.kind for span in spans] == [ProtectedSpanKind.REFERENCE] * 2
    assert spans[0].text == r"\eqref{eq:f1}"


def test_inline_math_is_protected_in_both_delimiter_styles() -> None:
    assert only(r"the $n$-gram features", ProtectedSpanKind.MATH).text == "$n$"
    assert only(r"we set \(k = 3\) here", ProtectedSpanKind.MATH).text == r"\(k = 3\)"


def test_an_escaped_dollar_does_not_open_math() -> None:
    assert ProtectedSpanKind.MATH not in kinds(r"it costs \$5 per run")


def test_numbers_carry_their_unit_or_metric_token() -> None:
    text = r"They measure 120 ms at 3.5 GB and lose 4.2 F1 at 95\%."
    numbers = [
        span.text
        for span in find_protected_spans(text)
        if span.kind is ProtectedSpanKind.NUMBER_WITH_UNIT
    ]
    assert numbers == ["120 ms", "3.5 GB", "4.2 F1", r"95\%"]


def test_a_decimal_is_one_number_and_a_following_word_is_not_a_unit() -> None:
    assert only("we ran 94.32 experiments", ProtectedSpanKind.NUMBER_WITH_UNIT).text == "94.32"


def test_research_identifiers_dois_and_arxiv_ids_are_protected() -> None:
    text = "Claim C0041 cites 10.1145/3512345.3512399 and arXiv:2401.01234v2."
    found = [
        span.text
        for span in find_protected_spans(text)
        if span.kind is ProtectedSpanKind.IDENTIFIER
    ]
    assert found == ["C0041", "10.1145/3512345.3512399", "arXiv:2401.01234v2"]


def test_urls_are_protected_and_stop_before_sentence_punctuation() -> None:
    text = r"Fetch \url{https://example.org/a} or https://example.org/b, then stop."
    urls = [span.text for span in find_protected_spans(text) if span.kind is ProtectedSpanKind.URL]
    assert urls == [r"\url{https://example.org/a}", "https://example.org/b"]


def test_quotations_and_code_are_protected() -> None:
    text = r"They call it ``the load wall'' and run \verb|grep -n| on it."
    assert only(text, ProtectedSpanKind.QUOTATION).text == "``the load wall''"
    assert only(text, ProtectedSpanKind.CODE).text == r"\verb|grep -n|"


def test_the_enclosing_span_wins_so_a_number_inside_a_citation_is_not_split_out() -> None:
    text = r"as shown by \citep[table 3]{kraus2019} for 94.3\% load"
    spans = find_protected_spans(text)
    assert [span.kind for span in spans] == [
        ProtectedSpanKind.CITATION,
        ProtectedSpanKind.NUMBER_WITH_UNIT,
    ]
    assert spans[0].text == r"\citep[table 3]{kraus2019}"


def test_spans_are_ordered_and_never_overlap() -> None:
    spans = find_protected_spans(SENTENCE)
    assert kinds(SENTENCE) == [
        ProtectedSpanKind.NUMBER_WITH_UNIT,
        ProtectedSpanKind.CITATION,
        ProtectedSpanKind.MATH,
        ProtectedSpanKind.IDENTIFIER,
    ]
    for earlier, later in pairwise(spans):
        assert earlier.char_end <= later.char_start


def test_prose_without_protected_material_yields_no_spans() -> None:
    assert find_protected_spans("The degradation is rarely reported.") == ()


@pytest.mark.parametrize("kind", list(ProtectedSpanKind))
def test_every_span_kind_is_a_plain_string_value(kind: ProtectedSpanKind) -> None:
    assert kind == kind.value

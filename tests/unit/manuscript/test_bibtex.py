"""BibTeX reading: entry identity, value fidelity, macros, and located failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.domain.errors import ResearchHarnessError
from research_harness.manuscript import BibDatabase, BibtexError, parse_bibtex, parse_bibtex_file

REFERENCES = Path(__file__).resolve().parents[2] / "fixtures" / "manuscript" / "references.bib"


@pytest.fixture(scope="module")
def bib() -> BibDatabase:
    return parse_bibtex_file(REFERENCES)


def test_every_entry_of_the_fixture_bibliography_is_parsed(bib: BibDatabase) -> None:
    assert bib.keys() == ("kraus2019", "ostrom2020", "nguyen2022", "hart2018", "ivanov2023")
    assert bib.warnings == ()
    assert "kraus2019" in bib
    assert bib.get("voss2021") is None


def test_entry_types_are_lowercased_so_lookup_is_case_insensitive(bib: BibDatabase) -> None:
    # The fixture writes "@InProceedings".
    assert bib.entries["ostrom2020"].entry_type == "inproceedings"
    assert bib.entries["kraus2019"].entry_type == "article"


def test_inner_braces_and_escapes_survive_a_field_value(bib: BibDatabase) -> None:
    title = bib.entries["kraus2019"].fields["title"]
    assert title == r"Measuring {TCP} Fairness at 94.3\% Offered Load"


def test_a_month_macro_resolves_without_any_string_definition(bib: BibDatabase) -> None:
    assert bib.entries["ostrom2020"].field("month") == "July"
    assert "jul" not in bib.strings


def test_string_macros_are_substituted_and_concatenated(bib: BibDatabase) -> None:
    assert bib.strings["ieeetn"] == "IEEE/ACM Transactions on Networking"
    assert bib.entries["hart2018"].fields["series"] == (
        "IEEE/ACM Transactions on Networking, Selected Reprints"
    )


def test_doi_and_url_fields_are_kept_verbatim(bib: BibDatabase) -> None:
    entry = bib.entries["nguyen2022"]
    assert entry.field("doi") == "10.1145/3512345.3512399"
    assert entry.field("URL") == "https://example.org/papers/nguyen2022"


def test_quoted_values_are_read_like_braced_ones(bib: BibDatabase) -> None:
    assert bib.entries["ivanov2023"].fields["author"] == "Ivanov, Dmitri"
    assert bib.entries["ivanov2023"].fields["year"] == "2023"


def test_comment_and_preamble_blocks_are_not_entries(bib: BibDatabase) -> None:
    assert bib.preambles == (r"\newcommand{\noopsort}[1]{}",)
    assert not any(entry.entry_type in {"comment", "preamble"} for entry in bib.entries.values())


def test_a_multi_line_value_collapses_to_single_spaces() -> None:
    parsed = parse_bibtex("@article{a2019,\n  title = {A very\n     long title}\n}\n")
    assert parsed.entries["a2019"].fields["title"] == "A very long title"


def test_a_duplicate_key_warns_and_the_first_entry_wins() -> None:
    parsed = parse_bibtex("@article{a, year = {2019}}\n\n@article{a, year = {2020}}\n")
    assert parsed.entries["a"].fields["year"] == "2019"
    assert len(parsed.warnings) == 1
    assert "duplicate entry key 'a'" in parsed.warnings[0]
    assert "line 3" in parsed.warnings[0]


def test_an_undefined_macro_warns_instead_of_failing() -> None:
    parsed = parse_bibtex("@article{a, journal = unknownmacro}\n")
    assert parsed.entries["a"].fields["journal"] == "unknownmacro"
    assert "undefined macro" in parsed.warnings[0]


@pytest.mark.parametrize(
    ("text", "line", "reason"),
    [
        ("@article{a2019,\n  title = {Unbalanced {inner}\n", 2, "unterminated '{'"),
        ('@article{a2019,\n  author = "unterminated\n}\n', 2, "unterminated '\"'"),
        ("@article{a2019,\n  title  {no equals}\n}\n", 2, "expected '='"),
        ("@article{a2019,\n  title = ,\n}\n", 2, "expected a field value"),
        ("@article a2019, title = {x}}\n", 1, "expected '{' or '('"),
    ],
)
def test_malformed_input_raises_a_harness_error_naming_the_line(
    text: str, line: int, reason: str
) -> None:
    with pytest.raises(BibtexError) as caught:
        parse_bibtex(text)
    assert isinstance(caught.value, ResearchHarnessError)
    assert caught.value.line == line
    assert reason in str(caught.value)
    assert f"line {line}" in str(caught.value)


def test_text_outside_entries_is_ignored() -> None:
    parsed = parse_bibtex("% a comment line\nsome stray prose\n@misc{a, year = {2019}}\n")
    assert parsed.keys() == ("a",)


def test_an_empty_database_parses_to_nothing() -> None:
    assert parse_bibtex("").entries == {}

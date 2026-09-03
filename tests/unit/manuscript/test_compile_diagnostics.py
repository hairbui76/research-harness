"""Turning a TeX transcript into file/line diagnostics a researcher can click.

The recorded transcript and stderr under `tests/fixtures/latex/recorded/` are real output
from `tectonic 0.17` compiling `tests/fixtures/latex/project` with an undefined control
sequence added to the included section.
"""

from __future__ import annotations

from research_harness.manuscript.compile import (
    CompileDiagnostic,
    DiagnosticSeverity,
    parse_diagnostics,
)
from tests.fixtures.latex import RECORDED_DIR

RECORDED_LOG = (RECORDED_DIR / "tectonic-failure.log").read_text(encoding="utf-8")
RECORDED_STDERR = (RECORDED_DIR / "tectonic-failure.stderr").read_text(encoding="utf-8")


def only(found: tuple[CompileDiagnostic, ...], code: str) -> CompileDiagnostic:
    matches = [item for item in found if item.code == code]
    assert len(matches) == 1, f"expected exactly one {code} diagnostic, got {matches}"
    return matches[0]


def codes(found: tuple[CompileDiagnostic, ...]) -> list[str | None]:
    return [item.code for item in found]


# -- the classic error form -------------------------------------------------------------


def test_a_tex_error_is_placed_at_the_line_its_l_marker_names() -> None:
    log = (
        "(main.tex\n"
        "(sections/intro.tex\n"
        "! Undefined control sequence.\n"
        "l.9 \\badmacro\n"
        "             \n"
        "No pages of output.\n"
    )

    found = parse_diagnostics(log=log, entry_file="main.tex")

    error = only(found, "undefined-control-sequence")
    assert error.severity is DiagnosticSeverity.ERROR
    assert (error.file, error.line) == ("sections/intro.tex", 9)
    assert error.where() == "sections/intro.tex:9"


def test_an_error_after_a_closed_include_belongs_to_the_file_that_is_still_open() -> None:
    log = "(main.tex\n(sections/intro.tex\n)\n! Missing $ inserted.\nl.24 x_i\n"

    found = parse_diagnostics(log=log, entry_file="main.tex")

    assert only(found, "missing-math-shift").file == "main.tex"


def test_an_error_with_no_line_marker_still_names_its_file() -> None:
    log = "(main.tex\n! Emergency stop.\n"

    error = only(parse_diagnostics(log=log, entry_file="main.tex"), "emergency-stop")

    assert (error.file, error.line) == ("main.tex", None)
    assert error.where() == "main.tex"


def test_prose_in_parentheses_does_not_become_an_open_file() -> None:
    log = (
        "(main.tex\n"
        "(\\end occurred inside a group at level 1)\n"
        "! Undefined control sequence.\n"
        "l.3 \\nope\n"
    )

    found = parse_diagnostics(log=log, entry_file="main.tex")
    assert only(found, "undefined-control-sequence").file == "main.tex"


def test_a_missing_input_file_is_reported_as_a_file_not_found_error() -> None:
    log = "(main.tex\n! LaTeX Error: File `missing.sty' not found.\nl.4 \\usepackage{missing}\n"

    error = only(parse_diagnostics(log=log, entry_file="main.tex"), "file-not-found")

    assert error.severity is DiagnosticSeverity.ERROR
    assert error.line == 4


# -- the -file-line-error form ----------------------------------------------------------


def test_the_file_line_error_form_is_read_directly() -> None:
    log = "(main.tex\n./sections/intro.tex:12: Undefined control sequence.\n"

    error = only(parse_diagnostics(log=log, entry_file="main.tex"), "undefined-control-sequence")

    assert (error.file, error.line) == ("sections/intro.tex", 12)


def test_ordinary_log_chatter_is_not_mistaken_for_a_placed_error() -> None:
    log = (
        "(main.tex\n"
        "File: size11.clo 2021/10/04 v1.4n Standard LaTeX file (size option)\n"
        "Package: amsmath 2021/10/15 v2.17l AMS math features\n"
        "LaTeX Font Info:    Redeclaring font encoding OML on input line 743.\n"
        "LaTeX Info: Redefining \\frac on input line 234.\n"
        "\\c@part=\\count181\n"
    )

    assert parse_diagnostics(log=log, entry_file="main.tex") == ()


# -- warnings ---------------------------------------------------------------------------


def test_an_undefined_citation_is_a_warning_at_the_input_line() -> None:
    log = (
        "(main.tex\n"
        "(sections/intro.tex\n"
        "\nLaTeX Warning: Citation `kraus2019' on page 1 undefined on input line 5.\n"
    )

    warning = only(parse_diagnostics(log=log, entry_file="main.tex"), "citation-undefined")

    assert warning.severity is DiagnosticSeverity.WARNING
    assert (warning.file, warning.line) == ("sections/intro.tex", 5)


def test_a_package_error_in_the_log_is_an_error_and_a_package_warning_is_not() -> None:
    log = (
        "(main.tex\n"
        "Package natbib Warning: Citation `x' undefined on input line 12.\n"
        "Package hyperref Error: Wrong driver on input line 3.\n"
    )

    found = parse_diagnostics(log=log, entry_file="main.tex")

    assert {item.severity for item in found} == {
        DiagnosticSeverity.WARNING,
        DiagnosticSeverity.ERROR,
    }
    assert only(found, "package-error").line == 3


def test_a_wrapped_font_warning_keeps_its_continuation_and_its_line() -> None:
    log = (
        "(main.tex\n"
        "LaTeX Font Warning: Font shape `OT1/cmr/bx/sc' undefined\n"
        "(Font)              using `OT1/cmr/bx/n' instead on input line 12.\n"
    )

    warning = only(parse_diagnostics(log=log, entry_file="main.tex"), "latex-warning")

    assert "instead" in warning.message
    assert warning.line == 12


def test_overfull_and_underfull_boxes_are_warnings_at_their_first_line() -> None:
    log = (
        "(main.tex\n"
        "Overfull \\hbox (12.34pt too wide) in paragraph at lines 12--14\n"
        "Underfull \\vbox (badness 10000) has occurred while \\output is active [3]\n"
    )

    found = parse_diagnostics(log=log, entry_file="main.tex")

    assert codes(found) == ["overfull-hbox", "underfull-vbox"]
    assert only(found, "overfull-hbox").line == 12
    assert only(found, "underfull-vbox").line is None
    assert {item.severity for item in found} == {DiagnosticSeverity.WARNING}


def test_the_first_run_message_about_a_missing_aux_file_is_information() -> None:
    log = "(main.tex\nNo file main.aux.\n"

    absent = only(parse_diagnostics(log=log, entry_file="main.tex"), "no-file")

    assert absent.severity is DiagnosticSeverity.INFO


# -- the engine's own stream ------------------------------------------------------------


def test_a_wrapper_error_line_that_names_a_place_is_placed() -> None:
    stderr = "error: sections/intro.tex:9: Undefined control sequence\n"

    error = only(parse_diagnostics(stderr=stderr), "undefined-control-sequence")

    assert (error.file, error.line) == ("sections/intro.tex", 9)


def test_a_wrapper_error_without_a_place_is_still_reported() -> None:
    stderr = "error: the XeTeX engine had an unrecoverable error\ncaused by: halted\n"

    found = parse_diagnostics(stderr=stderr)

    assert [(item.severity, item.file) for item in found] == [(DiagnosticSeverity.ERROR, None)]


def test_wrapper_progress_notes_are_not_diagnostics() -> None:
    stdout = "note: Running TeX ...\nnote: Writing `main.pdf' (25.0 KiB)\n"

    assert parse_diagnostics(stdout=stdout) == ()


def test_the_same_error_from_the_log_and_the_wrapper_is_reported_once() -> None:
    log = "(main.tex\n(sections/intro.tex\n! Undefined control sequence.\nl.9 \\badmacro\n"
    stderr = "error: sections/intro.tex:9: Undefined control sequence\n"

    found = parse_diagnostics(log=log, stderr=stderr, entry_file="main.tex")

    assert codes(found) == ["undefined-control-sequence"]


# -- the recorded real run --------------------------------------------------------------


def test_a_real_failing_tectonic_run_yields_one_placed_error_and_the_citation_warning() -> None:
    found = parse_diagnostics(log=RECORDED_LOG, stderr=RECORDED_STDERR, entry_file="main.tex")

    error = only(found, "undefined-control-sequence")
    assert (error.file, error.line) == ("sections/intro.tex", 9)

    warning = only(found, "citation-undefined")
    assert (warning.file, warning.line) == ("sections/intro.tex", 5)
    assert warning.severity is DiagnosticSeverity.WARNING


def test_a_real_log_produces_no_diagnostic_without_a_severity_or_a_message() -> None:
    found = parse_diagnostics(log=RECORDED_LOG, stderr=RECORDED_STDERR, entry_file="main.tex")

    assert found
    assert all(item.message.strip() for item in found)
    assert all(item.line is None or item.line >= 1 for item in found)

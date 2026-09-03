"""Parsing a real LaTeX project into anchorable sentences, and re-finding them after edits."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.enums import ManuscriptAnchorStatus, StaleState
from research_harness.domain.ids import ClaimId
from research_harness.manuscript import (
    BlockKind,
    LatexError,
    LatexProject,
    Sentence,
    anchor_key,
    apply_revalidation,
    build_anchor,
    revalidate_all,
    revalidate_anchor,
    sentence_fingerprint,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "manuscript"
MAIN = FIXTURE / "main.tex"
CLAIM = ClaimId("C0041")
PROVENANCE = Provenance.human("human:alice")

DOCUMENT = (
    "\\documentclass{article}\n\\begin{document}\n"
    "\\section{Introduction}\n\nBODY\n\\end{document}\n"
)
ANCHORED = "Structured traffic classifiers degrade under sustained load."
REWORDED = "Structured traffic classifiers degrade badly under sustained load."
OTHER = "A second paragraph keeps this file from being trivial."


@pytest.fixture(scope="module")
def project() -> LatexProject:
    return LatexProject.load(MAIN)


def build(directory: Path, body: str) -> LatexProject:
    directory.mkdir(parents=True, exist_ok=True)
    main = directory / "main.tex"
    main.write_text(DOCUMENT.replace("BODY", body), encoding="utf-8")
    return LatexProject.load(main)


def sentence_at(project: LatexProject, file: str, line: int) -> Sentence:
    found = [s for s in project.sentences_for_file(file) if s.line_start == line]
    assert len(found) == 1, f"expected one sentence starting at {file}:{line}, got {found}"
    return found[0]


# -- the file graph ---------------------------------------------------------------------


def test_the_project_loads_input_and_include_targets_relative_to_the_main_file(
    project: LatexProject,
) -> None:
    assert [item.path for item in project.files] == [
        "main.tex",
        "sections/intro.tex",
        "sections/method.tex",
    ]
    assert project.main == "main.tex"
    assert project.warnings == ()


def test_an_unreadable_main_file_is_the_only_fatal_case(tmp_path: Path) -> None:
    with pytest.raises(LatexError, match="cannot read main LaTeX file"):
        LatexProject.load(tmp_path / "absent.tex")


def test_a_missing_include_is_a_recorded_warning_not_a_crash(tmp_path: Path) -> None:
    loaded = build(tmp_path / "missing", "Prose stands alone.\n\n\\input{sections/absent}\n")
    assert loaded.warnings == ("main.tex:7: cannot read included file 'sections/absent.tex'",)
    assert [s.normalized_text for s in loaded.sentences] == ["Prose stands alone."]


def test_an_include_cycle_terminates_with_a_warning(tmp_path: Path) -> None:
    root = tmp_path / "cycle"
    (root / "sections").mkdir(parents=True)
    (root / "sections" / "loop.tex").write_text(
        "A looping section.\n\\input{main}\n", encoding="utf-8"
    )
    loaded = build(root, "\\input{sections/loop}\n")
    assert [item.path for item in loaded.files] == ["main.tex", "sections/loop.tex"]
    assert any("include cycle at 'main.tex'" in warning for warning in loaded.warnings)
    assert [s.normalized_text for s in loaded.sentences] == ["A looping section."]


# -- the sentence stream ----------------------------------------------------------------


def test_the_preamble_contributes_no_sentences(project: LatexProject) -> None:
    text = " ".join(sentence.normalized_text for sentence in project.sentences)
    assert "Structured Traffic Classification Under Sustained Load" not in text
    assert "documentclass" not in text


def test_sentence_spans_slice_back_out_of_their_own_file(project: LatexProject) -> None:
    for sentence in project.sentences:
        source = project.file(sentence.file)
        assert source is not None
        assert source.text[sentence.char_start : sentence.char_end] == sentence.text
        assert source.lines[sentence.line_start - 1] in source.text
        assert sentence.line_end >= sentence.line_start


def test_a_specific_sentence_carries_its_file_line_range_and_environment(
    project: LatexProject,
) -> None:
    abstract = sentence_at(project, "main.tex", 15)
    assert abstract.normalized_text == (
        "We evaluate four classifiers at 94.32% offered load and observe a 4.2 F1 drop."
    )
    assert (abstract.line_start, abstract.line_end) == (15, 16)
    assert abstract.in_environment == "abstract"
    assert abstract.section_path == ()


def test_a_decimal_and_an_abbreviation_do_not_end_a_sentence(project: LatexProject) -> None:
    kraus = sentence_at(project, "sections/intro.tex", 5)
    assert kraus.normalized_text.startswith("Kraus et al. report an F1 of 94.32")
    assert kraus.normalized_text.endswith("under identical conditions.")
    assert (kraus.line_start, kraus.line_end) == (5, 7)
    assert "e.g. below 30%" in sentence_at(project, "sections/intro.tex", 4).normalized_text
    assert sentence_at(project, "sections/method.tex", 8).normalized_text.endswith("Eq. 1:")


def test_a_paragraph_break_always_ends_a_sentence(tmp_path: Path) -> None:
    loaded = build(tmp_path / "para", "one clause without punctuation\n\nand another\n")
    assert [s.normalized_text for s in loaded.sentences] == [
        "one clause without punctuation",
        "and another",
    ]


def test_math_float_and_verbatim_environments_become_blocks_not_sentences(
    project: LatexProject,
) -> None:
    assert [(block.kind, block.environment) for block in project.blocks] == [
        (BlockKind.EQUATION, "equation"),
        (BlockKind.TABLE, "table"),
        (BlockKind.TABULAR, "tabular"),
        (BlockKind.FIGURE, "figure"),
        (BlockKind.VERBATIM, "verbatim"),
    ]
    equation = project.blocks[0]
    assert (equation.file, equation.line_start, equation.line_end) == (
        "sections/method.tex",
        10,
        13,
    )
    prose = " ".join(sentence.text for sentence in project.sentences)
    assert "F_1 = 2" not in prose
    assert "research audit manuscript" not in prose
    assert "Sweep results" not in prose


def test_inline_math_stays_inside_its_sentence(project: LatexProject) -> None:
    scope = sentence_at(project, "sections/intro.tex", 16)
    assert "$n$-gram" in scope.normalized_text
    assert [span.text for span in scope.protected_spans if span.kind == "math"] == ["$n$"]


def test_display_math_ends_the_surrounding_sentence(tmp_path: Path) -> None:
    loaded = build(tmp_path / "display", "We define \\[ x = 1 \\] and stop here.\n")
    assert [s.normalized_text for s in loaded.sentences] == ["We define", "and stop here."]
    assert [b.kind for b in loaded.blocks] == [BlockKind.DISPLAY_MATH]


# -- citations and structure ------------------------------------------------------------


def test_citation_keys_include_multiple_keys_and_optional_arguments(
    project: LatexProject,
) -> None:
    assert sentence_at(project, "sections/intro.tex", 5).citation_keys == (
        "kraus2019",
        "ostrom2020",
    )
    assert sentence_at(project, "sections/intro.tex", 7).citation_keys == ("ostrom2020",)
    assert project.cited_keys() == (
        "kraus2019",
        "ostrom2020",
        "voss2021",
        "nguyen2022",
        "hart2018",
    )


def test_citation_commands_leave_the_normalized_sentence(project: LatexProject) -> None:
    cited = sentence_at(project, "sections/intro.tex", 7)
    assert cited.normalized_text == "The reproduction used the corrected split described in."
    assert r"\citep[p.~3]{ostrom2020}" in cited.text


def test_headings_give_each_sentence_a_section_path(project: LatexProject) -> None:
    assert [(h.file, h.line, h.section_path) for h in project.headings] == [
        ("sections/intro.tex", 1, ("Introduction",)),
        ("sections/intro.tex", 14, ("Introduction", "Scope")),
        ("sections/method.tex", 1, ("Method",)),
        ("sections/method.tex", 3, ("Method", "Setup")),
        ("main.tex", 23, ("Discussion",)),
    ]
    assert sentence_at(project, "sections/intro.tex", 4).section_path == ("Introduction",)
    assert sentence_at(project, "sections/intro.tex", 16).section_path == (
        "Introduction",
        "Scope",
    )
    assert sentence_at(project, "sections/method.tex", 5).section_path == ("Method", "Setup")
    assert sentence_at(project, "main.tex", 26).section_path == ("Discussion",)


# -- fingerprints -----------------------------------------------------------------------


def test_the_fingerprint_ignores_whitespace_and_comment_edits(tmp_path: Path) -> None:
    plain = build(tmp_path / "plain", f"{ANCHORED}\n")
    noisy = build(
        tmp_path / "noisy",
        "Structured   traffic classifiers degrade\n% an editing note nobody reads\n"
        "under    sustained load.\n",
    )
    assert plain.sentences[0].fingerprint == noisy.sentences[0].fingerprint
    assert noisy.sentences[0].normalized_text == ANCHORED


def test_the_fingerprint_is_the_hash_of_the_normalized_sentence(project: LatexProject) -> None:
    for sentence in project.sentences:
        assert sentence.fingerprint == sentence_fingerprint(sentence.text)
        assert sentence.fingerprint == sentence_fingerprint(sentence.normalized_text)
        assert sentence.fingerprint.startswith("sha256:")


def test_rewording_changes_the_fingerprint(tmp_path: Path) -> None:
    before = build(tmp_path / "before", f"{ANCHORED}\n")
    after = build(tmp_path / "after", f"{REWORDED}\n")
    assert before.sentences[0].fingerprint != after.sentences[0].fingerprint


# -- anchors ----------------------------------------------------------------------------


def test_an_anchor_records_the_sentence_it_was_built_from(project: LatexProject) -> None:
    sentence = sentence_at(project, "sections/intro.tex", 5)
    anchor = build_anchor(sentence, CLAIM, PROVENANCE)
    assert anchor.file == "sections/intro.tex"
    assert (anchor.line_start, anchor.line_end) == (5, 7)
    assert (anchor.char_start, anchor.char_end) == (sentence.char_start, sentence.char_end)
    assert anchor.sentence == sentence.normalized_text
    assert anchor.sentence_fingerprint == sentence.fingerprint
    assert anchor.citation_keys == ("kraus2019", "ostrom2020")
    assert anchor.claim == CLAIM
    assert anchor.status is ManuscriptAnchorStatus.VALID
    assert anchor_key(anchor) == f"sections/intro.tex#{sentence.fingerprint}"


def test_an_unchanged_sentence_revalidates_as_valid_without_relocation(
    project: LatexProject,
) -> None:
    anchor = build_anchor(sentence_at(project, "main.tex", 26), CLAIM, PROVENANCE)
    result = revalidate_anchor(anchor, LatexProject.load(MAIN))
    assert result.status is ManuscriptAnchorStatus.VALID
    assert result.relocated is None
    assert result.similarity == 1.0
    assert apply_revalidation(result) == anchor


def test_a_moved_sentence_is_valid_and_reports_where_it_went(tmp_path: Path) -> None:
    anchor = build_anchor(
        build(tmp_path / "was", f"{ANCHORED}\n\n{OTHER}\n").sentences[0], CLAIM, PROVENANCE
    )
    moved = build(tmp_path / "now", f"{OTHER}\n\n{OTHER}\n\n{ANCHORED}\n")

    result = revalidate_anchor(anchor, moved)
    assert result.status is ManuscriptAnchorStatus.VALID
    assert result.relocated is not None
    assert result.relocated.line_start > anchor.line_start
    assert "moved to lines" in result.reason
    # The caller decides; the anchor is only rewritten on request.
    assert anchor.line_start != result.relocated.line_start
    updated = apply_revalidation(result)
    assert updated.line_start == result.relocated.line_start
    assert updated.sentence_fingerprint == anchor.sentence_fingerprint
    assert anchor_key(updated) == anchor_key(anchor)


def test_a_reworded_sentence_is_stale_and_carries_the_best_match(tmp_path: Path) -> None:
    anchor = build_anchor(
        build(tmp_path / "was", f"{ANCHORED}\n\n{OTHER}\n").sentences[0], CLAIM, PROVENANCE
    )
    reworded = build(tmp_path / "now", f"{REWORDED}\n\n{OTHER}\n")

    result = revalidate_anchor(anchor, reworded)
    assert result.status is ManuscriptAnchorStatus.STALE
    assert result.relocated is not None
    assert result.relocated.normalized_text == REWORDED
    assert result.similarity is not None
    assert 0.75 <= result.similarity < 1.0
    assert "reworded" in result.reason
    updated = apply_revalidation(result)
    assert updated.status is ManuscriptAnchorStatus.STALE
    assert updated.stale is StaleState.STALE
    # ADR-008: the anchor is flagged for review, never silently repointed.
    assert updated.sentence_fingerprint == anchor.sentence_fingerprint
    assert updated.sentence == anchor.sentence


def test_a_deleted_sentence_is_missing(tmp_path: Path) -> None:
    anchor = build_anchor(
        build(tmp_path / "was", f"{ANCHORED}\n\n{OTHER}\n").sentences[0], CLAIM, PROVENANCE
    )
    result = revalidate_anchor(anchor, build(tmp_path / "now", f"{OTHER}\n"))
    assert result.status is ManuscriptAnchorStatus.MISSING
    assert result.relocated is None
    assert result.similarity is None
    assert apply_revalidation(result).stale is StaleState.STALE


def test_an_anchor_into_a_dropped_file_is_missing(tmp_path: Path) -> None:
    anchor = build_anchor(
        build(tmp_path / "was", f"{ANCHORED}\n").sentences[0], CLAIM, PROVENANCE
    ).touch(file="sections/gone.tex")
    result = revalidate_anchor(anchor, build(tmp_path / "now", f"{ANCHORED}\n"))
    assert result.status is ManuscriptAnchorStatus.MISSING
    assert "no longer part of the manuscript" in result.reason


def test_revalidate_all_preserves_the_order_it_was_given(project: LatexProject) -> None:
    anchors = tuple(build_anchor(sentence, CLAIM, PROVENANCE) for sentence in project.sentences[:3])
    results = revalidate_all(anchors, project)
    assert [result.anchor for result in results] == list(anchors)
    assert {result.status for result in results} == {ManuscriptAnchorStatus.VALID}

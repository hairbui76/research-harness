"""Parsing SyncTeX, mapping both ways, and saying so honestly when there is no map.

The recorded sample under `tests/fixtures/latex/recorded/main.synctex` is real output from
`tectonic 0.17 --synctex` compiling `tests/fixtures/latex/project`; only the compile's
absolute paths were rewritten (to `/home/researcher/manuscript`) so that the file is the
same on every machine.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from research_harness.manuscript.synctex import (
    SP_PER_PDF_POINT,
    SynctexIndex,
    SynctexUnavailableError,
    SynctexUnavailableReason,
)
from tests.fixtures.latex import RECORDED_DIR, RECORDED_SOURCE_ROOT

RECORDED = RECORDED_DIR / "main.synctex"

SYNTHETIC = """SyncTeX Version:1
Input:1:main.tex
Input:2:sections/intro.tex
Output:pdf
Magnification:1000
Unit:1
X Offset:0
Y Offset:0
Content:
!12
{1
[1,1:0,0:26673152,41484288,0
(1,4:6553600,13107200:19660800,655360,196608
h1,4:6553600,13107200:19660800,0,0
)
(2,7:6553600,19660800:13107200,655360,196608
h2,7:6553600,19660800:13107200,0,0
)
]
}1
Postamble:
Count:8
Post scriptum:
"""


@pytest.fixture(scope="module")
def recorded() -> SynctexIndex:
    return SynctexIndex.load(RECORDED, source_root=RECORDED_SOURCE_ROOT)


@pytest.fixture
def synthetic() -> SynctexIndex:
    return SynctexIndex.parse(SYNTHETIC)


# -- the recorded real file -------------------------------------------------------------


def test_a_real_synctex_file_yields_the_project_files_and_pages(recorded: SynctexIndex) -> None:
    assert recorded.available
    assert recorded.state is None
    assert recorded.files == ("main.tex", "sections/intro.tex")
    assert recorded.pages == (1,)


def test_forward_lookup_places_a_source_line_on_the_page(recorded: SynctexIndex) -> None:
    located = recorded.forward("sections/intro.tex", 4)

    assert located, "the fixture's introduction is typeset on page 1"
    assert {item.page for item in located} == {1}
    assert all(0 <= item.x <= 612 for item in located)
    assert all(0 <= item.y <= 792 for item in located)


def test_inverse_lookup_returns_the_source_line_a_point_came_from(
    recorded: SynctexIndex,
) -> None:
    box = recorded.forward("sections/intro.tex", 4)[0]

    found = recorded.inverse(box.page, box.x + box.width / 2, box.y + box.height / 2)

    assert found is not None
    assert found.file == "sections/intro.tex"
    assert found.line == 4


def test_forward_and_inverse_round_trip_for_the_main_file(recorded: SynctexIndex) -> None:
    for line in (10, 12, 14):
        for box in recorded.forward("main.tex", line):
            back = recorded.inverse(box.page, box.x + box.width / 2, box.y + box.height / 2)
            assert back is not None
            assert back.file in {"main.tex", "sections/intro.tex"}


def test_an_absolute_input_path_is_reported_relative_to_the_project_root() -> None:
    """The engine records where it ran; a client asks with the path it was listed with."""
    without_root = SynctexIndex.load(RECORDED)

    assert without_root.files == (
        "/home/researcher/manuscript/main.tex",
        "/home/researcher/manuscript/sections/intro.tex",
    )
    assert without_root.forward("sections/intro.tex", 4), "a suffix match still resolves it"


def test_a_gzipped_file_parses_the_same_as_the_plain_one(
    recorded: SynctexIndex, tmp_path: Path
) -> None:
    packed = tmp_path / "main.synctex.gz"
    packed.write_bytes(gzip.compress(RECORDED.read_bytes()))

    index = SynctexIndex.load(packed, source_root=RECORDED_SOURCE_ROOT)

    assert index.files == recorded.files
    assert index.forward("main.tex", 10) == recorded.forward("main.tex", 10)


# -- lookup semantics -------------------------------------------------------------------


def test_coordinates_are_pdf_points_measured_from_the_top_left(
    synthetic: SynctexIndex,
) -> None:
    box = synthetic.forward("main.tex", 4)[0]

    assert box.x == pytest.approx(6553600 / SP_PER_PDF_POINT)
    # y is the top edge: the recorded baseline minus the box's height above it.
    assert box.y == pytest.approx((13107200 - 655360) / SP_PER_PDF_POINT)
    assert box.width == pytest.approx(19660800 / SP_PER_PDF_POINT)
    assert box.height == pytest.approx((655360 + 196608) / SP_PER_PDF_POINT)


def test_a_line_that_produced_nothing_resolves_to_the_next_line_that_did(
    synthetic: SynctexIndex,
) -> None:
    """A blank line or a comment still answers "show me where I am"."""
    assert synthetic.forward("main.tex", 2) == synthetic.forward("main.tex", 4)
    assert synthetic.forward("main.tex", 99) == synthetic.forward("main.tex", 4)


def test_a_file_the_map_never_saw_resolves_to_nothing(synthetic: SynctexIndex) -> None:
    assert synthetic.forward("sections/method.tex", 1) == ()


def test_an_include_resolves_with_or_without_its_tex_suffix(synthetic: SynctexIndex) -> None:
    assert synthetic.forward("sections/intro", 7) == synthetic.forward("sections/intro.tex", 7)


def test_a_point_outside_every_box_resolves_to_the_nearest_one(
    synthetic: SynctexIndex,
) -> None:
    found = synthetic.inverse(1, 0.0, 0.0)

    assert found is not None
    assert found.file == "main.tex"


def test_a_page_the_document_does_not_have_resolves_to_nothing(
    synthetic: SynctexIndex,
) -> None:
    assert synthetic.inverse(9, 100.0, 100.0) is None


# -- honest unavailability --------------------------------------------------------------


def test_no_synctex_file_reports_a_missing_file(tmp_path: Path) -> None:
    index = SynctexIndex.load(tmp_path / "absent.synctex")

    assert not index.available
    assert index.state is not None
    assert index.state.reason is SynctexUnavailableReason.MISSING_FILE


def test_a_build_that_never_asked_for_synctex_says_so() -> None:
    index = SynctexIndex.load(None)

    assert index.state is not None
    assert index.state.reason is SynctexUnavailableReason.NOT_REQUESTED


def test_a_file_that_is_not_synctex_at_all_reports_an_unsupported_format(
    tmp_path: Path,
) -> None:
    path = tmp_path / "main.synctex"
    path.write_text("this is not a SyncTeX file\n", encoding="utf-8")

    index = SynctexIndex.load(path)

    assert index.state is not None
    assert index.state.reason is SynctexUnavailableReason.UNSUPPORTED_FORMAT


def test_an_interrupted_run_leaves_a_header_without_content(tmp_path: Path) -> None:
    path = tmp_path / "main.synctex"
    path.write_text("SyncTeX Version:1\nInput:1:main.tex\n", encoding="utf-8")

    index = SynctexIndex.load(path)

    assert index.state is not None
    assert index.state.reason is SynctexUnavailableReason.UNSUPPORTED_FORMAT


def test_a_map_with_no_positions_is_not_pretended_to_be_usable(tmp_path: Path) -> None:
    path = tmp_path / "main.synctex"
    path.write_text(
        "SyncTeX Version:1\nInput:1:main.tex\nOutput:pdf\nUnit:1\nContent:\nPostamble:\n",
        encoding="utf-8",
    )

    index = SynctexIndex.load(path)

    assert index.state is not None
    assert index.state.reason is SynctexUnavailableReason.NO_RECORDS


def test_looking_up_an_unavailable_map_raises_rather_than_guessing(tmp_path: Path) -> None:
    index = SynctexIndex.load(tmp_path / "absent.synctex")

    with pytest.raises(SynctexUnavailableError) as error:
        index.forward("main.tex", 1)
    assert error.value.state.reason is SynctexUnavailableReason.MISSING_FILE

    with pytest.raises(SynctexUnavailableError):
        index.inverse(1, 0.0, 0.0)

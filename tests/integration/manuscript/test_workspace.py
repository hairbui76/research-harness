"""The manuscript workspace as a client meets it: one view over four different questions.

`test_compile.py` proves the compile service against a real subprocess. This file proves
what a *workspace* adds on top of it - that the compiler's answer and the science's answer
arrive together and stay apart, that a failed build keeps the last good PDF and says it is
stale, and that a missing engine and a missing SyncTeX map are reported as themselves.

The engine is `tests/fixtures/latex/fake-latex` on a throwaway PATH, so argv, the process,
and the files it writes are all real; only the typesetting is not.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import CreateClaimRequest
from research_harness.capabilities.handlers import create_claim
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    ManuscriptFindingKind,
)
from research_harness.manuscript.attach import ManuscriptService
from research_harness.manuscript.compile import CompileError, CompileStatus, DiagnosticSeverity
from research_harness.manuscript.files import ManuscriptConflictError
from research_harness.manuscript.synctex import SynctexUnavailableReason
from research_harness.manuscript.workspace import ManuscriptWorkspace
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.latex import copy_project, install_fake_engine

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the fake engine is a POSIX executable script"
)

HUMAN = "human:alice"
CLAIM = "C0001"

#: The introduction the tests anchor a Claim in. Its first sentence is written at the top
#: of the ladder ("all", "no prior work") so that the Claim's allowed strength is what
#: decides whether the audit complains - the compiler has no opinion about either.
ANCHORED_FILE = "sections/intro.tex"
ANCHORED_LINE = 4

INTRO_TEX = """\\section{Introduction}
\\label{sec:intro}

All existing traffic classifiers degrade under sustained load, and no prior work reports
the size of the gap \\cite{kraus2019}.

We compile this manuscript from source that stays under the researcher's control.
"""


def make_claim(level: ClaimScope) -> Claim:
    from research_harness.domain.ids import ClaimId

    return Claim(
        id=ClaimId(CLAIM),
        statement="classifiers degrade under sustained load",
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="classifiers", predicate="degrade", object="under sustained load"
        ),
        scope=ClaimScopeSpec(level=level, corpus="traffic classifiers"),
        assessment=ClaimAssessment(
            requested_strength=level,
            allowed_strength=level,
            status=ClaimStatus.SUPPORTED,
            maximum_defensible_wording="the classifiers in the reviewed corpus",
        ),
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[CapabilityContext]:
    """A workspace whose `manuscript/` holds the fixture LaTeX project."""
    root = tmp_path / "project"
    repo = WorkspaceRepository.init(root, "manuscript-workspace")
    copy_project(repo.layout.manuscript_dir)
    (repo.layout.manuscript_dir / ANCHORED_FILE).write_text(INTRO_TEX, encoding="utf-8")
    yield open_context(root, HUMAN)


@pytest.fixture
def fake_path(tmp_path: Path) -> str:
    return str(install_fake_engine(tmp_path / "bin", "pdflatex"))


@pytest.fixture
def workspace(ctx: CapabilityContext, fake_path: str) -> ManuscriptWorkspace:
    return ManuscriptWorkspace(
        ctx,
        search_path=fake_path,
        environ={"PATH": fake_path, "HOME": str(ctx.repo.root)},
    )


@pytest.fixture
def bare(ctx: CapabilityContext, tmp_path: Path) -> ManuscriptWorkspace:
    """A workspace with no engine anywhere on its PATH."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    return ManuscriptWorkspace(ctx, search_path=str(empty), environ={"PATH": str(empty)})


def break_the_source(ctx: CapabilityContext) -> None:
    """Ask the fake engine to fail the way a syntax error fails: at its own line."""
    path = ctx.repo.layout.manuscript_dir / ANCHORED_FILE
    path.write_text(f"{path.read_text(encoding='utf-8')}\n% fake-latex: fail\n", encoding="utf-8")


def anchor_the_first_sentence(ctx: CapabilityContext, level: ClaimScope) -> None:
    create_claim(ctx, CreateClaimRequest(claim=make_claim(level)))
    ManuscriptService(ctx).attach((ANCHORED_FILE, ANCHORED_LINE), make_claim(level).id)


# -- files -------------------------------------------------------------------


def test_the_tree_lists_the_source_files_and_names_the_entry_point(
    workspace: ManuscriptWorkspace,
) -> None:
    tree = workspace.tree()

    assert tree.root == "manuscript"
    assert tree.entry_file == "main.tex"
    assert [item.path for item in tree.files] == [
        "main.tex",
        "references.bib",
        "sections/intro.tex",
    ]


def test_a_save_that_presents_the_current_hash_succeeds(
    workspace: ManuscriptWorkspace,
) -> None:
    snapshot = workspace.read("main.tex")

    saved = workspace.write("main.tex", snapshot.content + "\n% edited\n", snapshot.content_hash)

    assert saved.content.endswith("% edited\n")
    assert workspace.read("main.tex").content_hash == saved.content_hash


def test_a_save_against_a_hash_somebody_else_moved_is_refused_with_both_hashes(
    workspace: ManuscriptWorkspace,
) -> None:
    snapshot = workspace.read("main.tex")
    workspace.write("main.tex", snapshot.content + "% first\n", snapshot.content_hash)

    with pytest.raises(ManuscriptConflictError) as raised:
        workspace.write("main.tex", snapshot.content + "% second\n", snapshot.content_hash)

    assert raised.value.expected_hash == snapshot.content_hash
    assert raised.value.actual_hash == workspace.read("main.tex").content_hash


# -- compiling ---------------------------------------------------------------


def test_a_successful_compile_reports_a_pdf_and_no_compiler_errors(
    workspace: ManuscriptWorkspace,
) -> None:
    view = workspace.compile()

    assert view.status is CompileStatus.SUCCEEDED
    assert view.error_count == 0
    assert view.pdf is not None and not view.pdf_stale
    assert view.pdf_available
    assert workspace.pdf_path(view.build_id).read_bytes().startswith(b"%PDF")


def test_a_failed_compile_reports_file_and_line_and_keeps_the_last_good_pdf_as_stale(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    """LaTeX spec 5 and 9: the preview keeps the PDF that compiled, labelled stale."""
    good = workspace.compile()
    break_the_source(ctx)

    bad = workspace.compile()

    assert bad.status is CompileStatus.FAILED
    assert bad.build_id != good.build_id
    errors = [item for item in bad.diagnostics if item.severity is DiagnosticSeverity.ERROR]
    assert errors and errors[0].file == ANCHORED_FILE and errors[0].line is not None
    assert bad.pdf is None
    assert bad.pdf_available and bad.pdf_stale
    assert bad.last_good is not None and bad.last_good.build_id == good.build_id
    assert workspace.pdf_path(bad.build_id) == workspace.last_good_pdf()
    assert any("stale" in line for line in bad.guidance)


def test_a_failed_compile_changes_no_manuscript_file(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    break_the_source(ctx)
    before = {item.path: workspace.files.hash_of(item.path) for item in workspace.tree().files}

    workspace.compile()

    assert {
        item.path: workspace.files.hash_of(item.path) for item in workspace.tree().files
    } == before


def test_a_workspace_with_no_engine_answers_with_setup_guidance_and_touches_nothing(
    bare: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    from research_harness.manuscript.toolchain import ToolchainUnavailableError

    before = {item.path: bare.files.hash_of(item.path) for item in bare.tree().files}

    with pytest.raises(ToolchainUnavailableError) as raised:
        bare.compile()

    assert "Install one of: tectonic" in str(raised.value)
    assert {item.path: bare.files.hash_of(item.path) for item in bare.tree().files} == before
    view = bare.build()
    assert not view.compiled
    assert view.guidance == view.toolchain.guidance


def test_a_workspace_that_never_compiled_has_no_pdf_to_show(
    workspace: ManuscriptWorkspace,
) -> None:
    with pytest.raises(CompileError, match="no compiled PDF"):
        workspace.pdf_path()
    with pytest.raises(CompileError):
        workspace.last_good_pdf()


# -- diagnostics and audit stay apart ----------------------------------------


def test_a_compile_can_succeed_while_the_scientific_audit_fails(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    """Product 42 P: a successful compile does not imply scientific audit success."""
    anchor_the_first_sentence(ctx, ClaimScope.CORPUS_PATTERN)

    view = workspace.compile()

    assert view.status is CompileStatus.SUCCEEDED
    assert view.error_count == 0
    assert view.audit_ran
    assert ManuscriptFindingKind.OVER_STRONG_WORDING in {
        finding.kind for finding in view.audit_findings
    }


def test_a_compile_can_fail_while_the_audit_raises_nothing_about_that_sentence(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    """And the reverse: the compiler's failure is not a scientific finding."""
    anchor_the_first_sentence(ctx, ClaimScope.UNIVERSAL_OR_ABSENCE)
    break_the_source(ctx)

    view = workspace.compile()

    assert view.status is CompileStatus.FAILED
    assert view.error_count >= 1
    assert view.audit_ran
    assert ManuscriptFindingKind.OVER_STRONG_WORDING not in {
        finding.kind for finding in view.audit_findings
    }
    assert not any("fake-latex" in finding.message for finding in view.audit_findings)


def test_the_two_lists_are_never_merged(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    anchor_the_first_sentence(ctx, ClaimScope.CORPUS_PATTERN)
    break_the_source(ctx)

    view = workspace.compile()

    assert view.error_count == len(
        [item for item in view.diagnostics if item.severity is DiagnosticSeverity.ERROR]
    )
    assert all(hasattr(item, "severity") and hasattr(item, "line") for item in view.diagnostics)
    assert all(hasattr(finding, "kind") for finding in view.audit_findings)
    messages = {item.message for item in view.diagnostics}
    assert not any(finding.kind.value in messages for finding in view.audit_findings)


def test_the_build_view_can_be_asked_for_diagnostics_alone(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    anchor_the_first_sentence(ctx, ClaimScope.CORPUS_PATTERN)
    compiled = workspace.compile()

    view = workspace.build(compiled.build_id, audit=False)

    assert view.audit_findings == ()
    assert view.audit_ran is False
    assert view.diagnostics == compiled.diagnostics


def test_an_unreadable_manuscript_does_not_hide_the_compiler_diagnostics(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    compiled = workspace.compile()
    (ctx.repo.layout.manuscript_dir / "main.tex").unlink()

    view = workspace.build(compiled.build_id)

    assert view.audit_ran is False
    assert view.audit_unavailable_reason is not None
    assert view.build_id == compiled.build_id


# -- source and PDF navigation -----------------------------------------------


def test_forward_navigation_answers_with_pdf_rectangles(
    workspace: ManuscriptWorkspace,
) -> None:
    workspace.compile()

    view = workspace.forward(ANCHORED_FILE, ANCHORED_LINE)

    assert view.available and view.reason is None
    assert view.pdf_locations
    assert all(item.page >= 1 for item in view.pdf_locations)


def test_inverse_navigation_answers_with_a_source_line(
    workspace: ManuscriptWorkspace,
) -> None:
    workspace.compile()
    forward = workspace.forward(ANCHORED_FILE, ANCHORED_LINE)
    box = forward.pdf_locations[0]

    view = workspace.inverse(box.page, box.x + 1, box.y + 1)

    assert view.available
    assert view.source_location is not None
    assert view.source_location.file.endswith(".tex")


def test_an_engine_that_produced_no_map_is_reported_as_unavailable_not_as_empty(
    workspace: ManuscriptWorkspace, ctx: CapabilityContext
) -> None:
    """LaTeX spec 6: the interface explains that navigation is unavailable, never guesses."""
    path = ctx.repo.layout.manuscript_dir / ANCHORED_FILE
    path.write_text(
        f"{path.read_text(encoding='utf-8')}\n% fake-latex: no-synctex\n", encoding="utf-8"
    )
    built = workspace.compile()

    view = workspace.forward(ANCHORED_FILE, ANCHORED_LINE)

    assert built.synctex_available is False
    assert view.available is False
    assert view.reason is SynctexUnavailableReason.MISSING_FILE
    assert view.detail and "SyncTeX" in view.detail
    assert view.pdf_locations == ()


def test_navigation_before_the_first_compile_says_there_is_no_map(
    workspace: ManuscriptWorkspace,
) -> None:
    view = workspace.forward("main.tex", 1)

    assert view.available is False
    assert view.build_id is None
    assert view.detail is not None and "not been compiled" in view.detail

"""Gate P21: compile it, look at it, break it, navigate it, and edit it only by review.

The roadmap gate is five sentences and this file is those five sentences in order:

1. compile a real project and inspect its PDF - here, through the daemon's byte route;
2. retain the last good PDF on a new compile failure, labelled stale;
3. navigate source/PDF when the mapping exists, and say so honestly when it does not;
4. distinguish compiler errors from scientific errors on one build;
5. apply a model suggestion only through an explicit reviewed diff.

The engine is `tests/fixtures/latex/fake-latex` on a throwaway PATH: a real subprocess with
real argv writing real files, so everything except the typesetting is the production path.
The model is a scripted provider, which is what a rewriter is to this code - something that
turns a passage into a passage and is trusted with neither.

The manuscript is written so that the compiler and the audit disagree on purpose. Its first
sentence is anchored to `C0001`, which allows corpus-level wording, and reads at the top of
the ladder ("all", "no prior work"); so the document compiles cleanly *and* fails its
scientific audit, and adding a compiler error to the same file does not add a scientific
finding to it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import CreateClaimRequest
from research_harness.capabilities.handlers import create_claim
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.cli.app import app
from research_harness.cli.commands import manuscript as manuscript_commands
from research_harness.cli.context import CLI_ACTOR
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    ManuscriptFindingKind,
    ResearchEventType,
)
from research_harness.domain.ids import ClaimId
from research_harness.manuscript.attach import ManuscriptService
from research_harness.manuscript.files import ManuscriptFiles
from research_harness.server.app import create_app, ensure_token
from tests.fixtures.latex import copy_project, install_fake_engine

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the fake engine is a POSIX executable script"
)

HUMAN = "human:alice"
CLAIM = ClaimId("C0001")

ANCHORED_FILE = "sections/intro.tex"
ANCHORED_LINE = 4
SPAN = (4, 5)

INTRO_TEX = """\\section{Introduction}
\\label{sec:intro}

All existing traffic classifiers degrade under sustained load, and no prior work reports
the size of the gap \\cite{kraus2019}.

We compile this manuscript from source that stays under the researcher's control.
"""

#: A join of the two lines: byte-different, meaning-identical, citation untouched.
HUMANIZED = (
    "All existing traffic classifiers degrade under sustained load, and no prior work "
    "reports the size of the gap \\cite{kraus2019}.\n"
)

#: The same sentence with the citation dropped - a protected span a style pass may not move.
DROPS_CITATION = (
    "All existing traffic classifiers degrade under sustained load, and no prior work "
    "reports the size of the gap.\n"
)

#: A rewrite that keeps the citation and moves the proposition: "no prior work" becomes a
#: flat assertion that nobody has measured it, which is a strengthening, not a style edit.
STRENGTHENED = (
    "Traffic classifiers always collapse under sustained load, and the size of the gap "
    "has never been measured \\cite{kraus2019}.\n"
)

runner = CliRunner()


def _ensure_registered() -> None:
    """Mount the manuscript family if the CLI has not been wired to it yet."""
    groups = {info.name for info in app.registered_groups}
    if "manuscript" not in groups:
        manuscript_commands.register(app)


_ensure_registered()


# -- the workspace ----------------------------------------------------------------------


def make_claim() -> Claim:
    """`C0001`: corpus-level wording is all the evidence allows this sentence to use."""
    return Claim(
        id=CLAIM,
        statement="classifiers in the reviewed corpus degrade under sustained load",
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="classifiers", predicate="degrade", object="under sustained load"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, corpus="traffic classifiers"),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.CORPUS_PATTERN,
            allowed_strength=ClaimScope.CORPUS_PATTERN,
            status=ClaimStatus.SUPPORTED,
            maximum_defensible_wording="the classifiers in the reviewed corpus",
        ),
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A workspace with a LaTeX project, one Claim, one anchor, and a fake engine."""
    from research_harness.workspace.repository import WorkspaceRepository

    root = tmp_path / "project"
    repo = WorkspaceRepository.init(root, "gate-p21")
    copy_project(repo.layout.manuscript_dir)
    (repo.layout.manuscript_dir / ANCHORED_FILE).write_text(INTRO_TEX, encoding="utf-8")

    ctx = open_context(root, HUMAN)
    create_claim(ctx, CreateClaimRequest(claim=make_claim()))
    ManuscriptService(ctx).attach((ANCHORED_FILE, ANCHORED_LINE), CLAIM)

    binaries = install_fake_engine(tmp_path / "bin", "pdflatex")
    # Only the fake engine: a real `tectonic` on the developer's PATH would otherwise
    # win the discovery order and quietly turn this into a network-capable compile.
    monkeypatch.setenv("PATH", str(binaries))
    yield root


@pytest.fixture
def ctx(workspace: Path) -> CapabilityContext:
    return open_context(workspace, HUMAN)


@pytest.fixture
def files(ctx: CapabilityContext) -> ManuscriptFiles:
    return ManuscriptFiles(ctx.repo.layout)


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def client(workspace: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon as the local researcher."""
    with TestClient(create_app(workspace, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {ensure_token(workspace)}"
        yield test_client


def capability(
    registry: CapabilityRegistry,
    ctx: CapabilityContext,
    name: str,
    request: dict[str, Any] | None = None,
    *,
    principal: Principal | None = None,
) -> Any:
    return registry.invoke(name, ctx, request or {}, principal=principal or Principal.human(HUMAN))


def cli(*args: str) -> Result:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"`research {' '.join(args)}` failed:\n{result.stdout}"
    return result


def script(tmp_path: Path, draft: str) -> Path:
    """A one-reply writer script, which is how the gate runs a rewriter offline."""
    path = tmp_path / f"writer-{abs(hash(draft))}.json"
    path.write_text(json.dumps({"writer": [{"draft": draft}]}), encoding="utf-8")
    return path


def break_the_source(workspace: Path) -> None:
    """Introduce the compile-time failure a syntax error produces, at its own line."""
    path = workspace / "manuscript" / ANCHORED_FILE
    path.write_text(f"{path.read_text(encoding='utf-8')}\n% fake-latex: fail\n", encoding="utf-8")


# -- 1. compile a real project and inspect its PDF --------------------------------------


def test_compiling_produces_a_pdf_the_daemon_serves_as_pdf_bytes(
    workspace: Path, ctx: CapabilityContext, registry: CapabilityRegistry, client: TestClient
) -> None:
    view = capability(registry, ctx, "manuscript.compile")

    response = client.get(f"/manuscript/builds/{view.build_id}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.content.startswith(b"%PDF")
    assert response.content == (workspace / view.pdf).read_bytes()


def test_the_latest_alias_serves_the_same_bytes(
    ctx: CapabilityContext, registry: CapabilityRegistry, client: TestClient
) -> None:
    view = capability(registry, ctx, "manuscript.compile")

    assert (
        client.get("/manuscript/builds/latest/pdf").content
        == client.get(f"/manuscript/builds/{view.build_id}/pdf").content
    )


def test_a_workspace_that_never_compiled_answers_404_rather_than_an_empty_file(
    client: TestClient,
) -> None:
    assert client.get("/manuscript/builds/latest/pdf").status_code == 404


# -- 2. a failure keeps the last good PDF, labelled stale -------------------------------


def test_a_syntax_error_reports_file_and_line_and_keeps_the_last_good_pdf(
    workspace: Path, ctx: CapabilityContext, registry: CapabilityRegistry, client: TestClient
) -> None:
    good = capability(registry, ctx, "manuscript.compile")
    good_pdf = client.get(f"/manuscript/builds/{good.build_id}/pdf").content
    break_the_source(workspace)

    bad = capability(registry, ctx, "manuscript.compile")

    assert bad.status.value == "failed"
    error = next(item for item in bad.diagnostics if item.severity.value == "error")
    assert error.file == ANCHORED_FILE and error.line is not None
    assert bad.pdf is None and bad.pdf_stale and bad.pdf_available
    assert bad.last_good is not None and bad.last_good.build_id == good.build_id
    assert client.get(f"/manuscript/builds/{bad.build_id}/pdf").content == good_pdf
    assert client.get("/manuscript/builds/last-good/pdf").content == good_pdf


# -- 3. source and PDF navigation, honestly ---------------------------------------------


def test_synctex_navigates_forward_and_back_through_the_capability(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    capability(registry, ctx, "manuscript.compile")

    forward = capability(
        registry, ctx, "manuscript.synctex", {"file": ANCHORED_FILE, "line": ANCHORED_LINE}
    )
    box = forward.pdf_locations[0]
    inverse = capability(
        registry,
        ctx,
        "manuscript.synctex",
        {"page": box.page, "x": box.x + 1.0, "y": box.y + 1.0},
    )

    assert forward.available and forward.pdf_locations
    assert inverse.available and inverse.source_location is not None
    assert inverse.source_location.file.endswith(".tex")


def test_an_engine_that_wrote_no_map_says_so_instead_of_guessing(
    workspace: Path, ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    path = workspace / "manuscript" / ANCHORED_FILE
    path.write_text(
        f"{path.read_text(encoding='utf-8')}\n% fake-latex: no-synctex\n", encoding="utf-8"
    )
    view = capability(registry, ctx, "manuscript.compile")

    lookup = capability(
        registry, ctx, "manuscript.synctex", {"file": ANCHORED_FILE, "line": ANCHORED_LINE}
    )

    assert view.synctex_available is False
    assert lookup.available is False
    assert lookup.reason.value == "missing_file"
    assert lookup.pdf_locations == ()
    assert "SyncTeX" in lookup.detail


# -- 4. compiler errors and scientific errors are different lists -----------------------


def test_a_clean_compile_still_fails_the_scientific_audit(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """Product 42 P: a successful compile does not imply scientific audit success."""
    view = capability(registry, ctx, "manuscript.compile")

    assert view.status.value == "succeeded"
    assert view.error_count == 0
    assert all(item.severity.value != "error" for item in view.diagnostics)
    assert view.audit_ran
    assert ManuscriptFindingKind.OVER_STRONG_WORDING in {
        finding.kind for finding in view.audit_findings
    }
    over_strong = next(
        finding
        for finding in view.audit_findings
        if finding.kind is ManuscriptFindingKind.OVER_STRONG_WORDING
    )
    assert over_strong.location is not None and over_strong.location.file == ANCHORED_FILE
    assert str(CLAIM) in over_strong.message


def test_a_broken_compile_adds_a_compiler_error_and_no_scientific_finding(
    workspace: Path, ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """And the reverse: the two lists move independently on the same build."""
    clean = capability(registry, ctx, "manuscript.compile")
    break_the_source(workspace)

    broken = capability(registry, ctx, "manuscript.compile")

    assert clean.error_count == 0 and broken.error_count >= 1
    assert {finding.kind for finding in broken.audit_findings} == {
        finding.kind for finding in clean.audit_findings
    }
    assert not any("fake-latex" in finding.message for finding in broken.audit_findings)
    assert not any(item.message.startswith("sentence reads") for item in broken.diagnostics)


def test_the_cli_prints_the_two_lists_under_two_headings(workspace: Path) -> None:
    cli("manuscript", "compile", "-w", str(workspace))
    result = cli("manuscript", "build", "-w", str(workspace))

    assert "compiler           0 errors" in result.stdout
    assert "audit              " in result.stdout
    assert "over_strong_wording" in result.stdout


def test_the_terminal_reaches_every_capability_by_the_same_name(workspace: Path) -> None:
    """`research manuscript files|read|write|synctex` mirror the capabilities (plan §0.4)."""
    listed = cli("manuscript", "files", "-w", str(workspace), "--json")
    assert [item["path"] for item in json.loads(listed.stdout)["files"]] == [
        "main.tex",
        "references.bib",
        "sections/intro.tex",
    ]

    snapshot = json.loads(
        cli("manuscript", "read", ANCHORED_FILE, "-w", str(workspace), "--json").stdout
    )
    saved = json.loads(
        cli(
            "manuscript",
            "write",
            ANCHORED_FILE,
            "-w",
            str(workspace),
            "--expected-hash",
            snapshot["content_hash"],
            "--text",
            snapshot["content"] + "% saved from the terminal\n",
            "--json",
        ).stdout
    )
    assert saved["content"].endswith("% saved from the terminal\n")

    stale = runner.invoke(
        app,
        [
            "manuscript",
            "write",
            ANCHORED_FILE,
            "-w",
            str(workspace),
            "--expected-hash",
            snapshot["content_hash"],
            "--text",
            "clobbered",
        ],
    )
    assert stale.exit_code == 1
    assert "changed outside the harness" in stale.stderr

    cli("manuscript", "compile", "-w", str(workspace))
    forward = cli("manuscript", "synctex", f"{ANCHORED_FILE}:{ANCHORED_LINE}", "-w", str(workspace))
    assert forward.stdout.startswith("page ")
    inverse = cli(
        "manuscript", "synctex", "-w", str(workspace), "--page", "1", "--x", "80", "--y", "180"
    )
    assert ".tex:" in inverse.stdout


# -- 5. a model suggestion reaches source only through a reviewed diff -------------------


def test_a_suggestion_stages_a_diff_and_leaves_the_file_byte_identical(
    workspace: Path, tmp_path: Path, files: ManuscriptFiles
) -> None:
    """LaTeX spec 10.5: ask for a humanized paragraph, get a diff, keep your source."""
    before = files.hash_of(ANCHORED_FILE)

    result = cli(
        "manuscript",
        "suggest",
        f"{ANCHORED_FILE}:{SPAN[0]}-{SPAN[1]}",
        "-w",
        str(workspace),
        "--style",
        "humanize",
        "--script",
        str(script(tmp_path, HUMANIZED)),
        "--json",
    )
    candidate = json.loads(result.stdout)

    assert files.hash_of(ANCHORED_FILE) == before
    assert candidate["audit_status"] == "passed"
    assert candidate["changed"] is True and candidate["applicable"] is True
    assert candidate["path"].startswith(".research/staging/manuscript/")
    kinds = {line["kind"] for hunk in candidate["hunks"] for line in hunk["lines"]}
    assert {"added", "removed", "context"} <= kinds


def test_applying_a_reviewed_candidate_writes_the_source_and_records_the_event(
    workspace: Path, tmp_path: Path, ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    staged = json.loads(
        cli(
            "manuscript",
            "suggest",
            f"{ANCHORED_FILE}:{SPAN[0]}-{SPAN[1]}",
            "-w",
            str(workspace),
            "--style",
            "humanize",
            "--script",
            str(script(tmp_path, HUMANIZED)),
            "--json",
        ).stdout
    )

    applied = json.loads(
        cli("manuscript", "apply", staged["candidate_id"], "-w", str(workspace), "--json").stdout
    )

    assert files.read(ANCHORED_FILE).content == staged["proposed_content"]
    assert applied["event"]["event"] == ResearchEventType.MANUSCRIPT_SOURCE_WRITTEN.value
    assert applied["event"]["actor"] == CLI_ACTOR
    events = [
        item
        for item in ctx.repo.iter_events()
        if item.event is ResearchEventType.MANUSCRIPT_SOURCE_WRITTEN
    ]
    assert len(events) == 1
    assert events[0].payload["candidate_id"] == staged["candidate_id"]
    # This rewrite only rewrapped the lines, so the anchored sentence normalizes to the
    # same text and keeps its fingerprint: nothing to revalidate, and the audit says so.
    assert applied["anchors_to_revalidate"] == []
    assert [item["status"] for item in staged["anchor_impacts"]] == ["valid"]


@pytest.mark.parametrize(
    ("draft", "reason"),
    [(DROPS_CITATION, "protected span"), (STRENGTHENED, "not meaning-preserving")],
)
def test_a_candidate_that_changes_meaning_is_refused_and_says_which_rule_refused_it(
    workspace: Path, tmp_path: Path, files: ManuscriptFiles, draft: str, reason: str
) -> None:
    before = files.hash_of(ANCHORED_FILE)
    staged = json.loads(
        cli(
            "manuscript",
            "suggest",
            f"{ANCHORED_FILE}:{SPAN[0]}-{SPAN[1]}",
            "-w",
            str(workspace),
            "--style",
            "humanize",
            "--script",
            str(script(tmp_path, draft)),
            "--json",
        ).stdout
    )

    assert staged["audit_status"] == "failed"
    assert reason in staged["blocked_reason"]

    refused = runner.invoke(
        app, ["manuscript", "apply", staged["candidate_id"], "-w", str(workspace)]
    )

    assert refused.exit_code == 1
    assert files.hash_of(ANCHORED_FILE) == before


def test_applying_against_a_stale_hash_is_refused_and_changes_nothing(
    workspace: Path, tmp_path: Path, files: ManuscriptFiles
) -> None:
    staged = json.loads(
        cli(
            "manuscript",
            "suggest",
            f"{ANCHORED_FILE}:{SPAN[0]}-{SPAN[1]}",
            "-w",
            str(workspace),
            "--style",
            "humanize",
            "--script",
            str(script(tmp_path, HUMANIZED)),
            "--json",
        ).stdout
    )
    before = files.hash_of(ANCHORED_FILE)

    refused = runner.invoke(
        app,
        [
            "manuscript",
            "apply",
            staged["candidate_id"],
            "-w",
            str(workspace),
            "--expected-hash",
            f"sha256:{'0' * 64}",
        ],
    )

    assert refused.exit_code == 1
    assert "changed outside the harness" in refused.stderr
    assert files.hash_of(ANCHORED_FILE) == before


# -- the boundary: a read-only host --------------------------------------------


def test_an_agent_host_may_read_the_manuscript_but_not_write_it(
    ctx: CapabilityContext, registry: CapabilityRegistry, files: ManuscriptFiles
) -> None:
    from research_harness.capabilities.permissions import PermissionDenied

    host = Principal.agent_host("claude")
    before = files.hash_of(ANCHORED_FILE)

    assert capability(registry, ctx, "manuscript.files", principal=host).files
    for name, request in (
        ("manuscript.write_file", {"path": ANCHORED_FILE, "content": "x", "expected_hash": before}),
        ("manuscript.compile", {}),
        ("manuscript.apply_suggestion", {"candidate_id": "run_20260101T000000Z_deadbeef"}),
    ):
        with pytest.raises(PermissionDenied):
            capability(registry, ctx, name, request, principal=host)

    assert files.hash_of(ANCHORED_FILE) == before


def test_the_daemon_refuses_a_manuscript_write_to_a_caller_without_the_token(
    workspace: Path, registry: CapabilityRegistry, files: ManuscriptFiles
) -> None:
    before = files.hash_of(ANCHORED_FILE)
    with TestClient(create_app(workspace, registry=registry)) as host:
        response = host.post(
            "/capabilities/manuscript.write_file",
            json={"path": ANCHORED_FILE, "content": "x", "expected_hash": before},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert files.hash_of(ANCHORED_FILE) == before

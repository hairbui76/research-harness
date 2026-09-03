"""Compiling a manuscript for real: a process, its outputs, and what survives a failure.

The engine is `tests/fixtures/latex/fake-latex`, installed on a throwaway PATH under a real
engine name, so discovery, argv construction, the scrubbed environment, the process group,
and the output files are all exercised against a genuine subprocess. One test at the end
runs the machine's own toolchain and is opt-in, because a real engine may reach the network
for its support files and the rest of the suite must not.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from research_harness.manuscript.compile import (
    CompileResult,
    CompileService,
    CompileStatus,
    CompileTimeoutError,
    DiagnosticSeverity,
)
from research_harness.manuscript.files import (
    ManuscriptFileNotFoundError,
    ManuscriptFiles,
    ManuscriptPathError,
)
from research_harness.manuscript.synctex import SynctexUnavailableReason
from research_harness.manuscript.toolchain import (
    LatexEngine,
    ManuscriptSettings,
    ToolchainUnavailableError,
)
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.latex import copy_project, install_fake_engine

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the fake engine is a POSIX executable script"
)

REAL_LATEX = os.environ.get("RESEARCH_HARNESS_REAL_LATEX") == "1"
INSTALLED_ENGINE = next(
    (name for name in ("tectonic", "latexmk", "pdflatex", "xelatex") if shutil.which(name)),
    None,
)


@pytest.fixture
def repository(tmp_path: Path) -> WorkspaceRepository:
    """A real workspace whose `manuscript/` holds the fixture project."""
    repo = WorkspaceRepository.init(tmp_path / "project", "compile-fixture")
    copy_project(repo.layout.manuscript_dir)
    return repo


@pytest.fixture
def fake_path(tmp_path: Path) -> str:
    """A PATH holding only the fake engine, installed as every name discovery looks for."""
    return str(install_fake_engine(tmp_path / "bin", "pdflatex"))


@pytest.fixture
def service(repository: WorkspaceRepository, fake_path: str) -> CompileService:
    return CompileService(
        repository.layout,
        ManuscriptSettings(),
        search_path=fake_path,
        environ={"PATH": fake_path, "HOME": str(repository.root)},
    )


def mark(repository: WorkspaceRepository, mode: str) -> None:
    """Ask the fake engine for a behaviour the way a real document would trigger one."""
    path = repository.layout.manuscript_dir / "sections" / "intro.tex"
    path.write_text(f"{path.read_text(encoding='utf-8')}\n% fake-latex: {mode}\n", "utf-8")


def env_dump(service: CompileService, result: CompileResult) -> dict[str, object]:
    payload = (service.absolute(result.build_dir) / "fake-env.json").read_text(encoding="utf-8")
    parsed: dict[str, object] = json.loads(payload)
    return parsed


# -- a successful build -----------------------------------------------------------------


def test_a_compile_produces_a_pdf_a_log_and_a_synctex_map(service: CompileService) -> None:
    result = service.compile()

    assert result.status is CompileStatus.SUCCEEDED
    assert result.succeeded and result.exit_status == 0 and not result.timed_out
    assert result.pdf is not None and service.absolute(result.pdf).read_bytes().startswith(b"%PDF")
    assert result.log is not None and service.absolute(result.log).is_file()
    assert result.synctex is not None and service.absolute(result.synctex).is_file()
    assert result.pdf.startswith(".research/build/manuscript/")


def test_the_build_record_is_the_provenance_of_the_run(service: CompileService) -> None:
    result = service.compile()

    assert result.engine is LatexEngine.PDFLATEX
    assert result.executable.endswith("pdflatex")
    assert result.entry_file == "main.tex"
    assert result.inputs_fingerprint.startswith("sha256:")
    assert result.inputs_fingerprint == service.files.fingerprint()
    assert result.started_at <= result.finished_at
    assert result.duration_seconds >= 0
    assert result.timeout_seconds == 120
    assert result.build_id.startswith(result.started_at.strftime("%Y%m%dT%H%M%SZ"))
    assert result.inputs_fingerprint.removeprefix("sha256:").startswith(
        result.build_id.rsplit("-", 1)[-1]
    )


def test_the_build_record_is_written_beside_the_outputs_and_reloads(
    service: CompileService,
) -> None:
    result = service.compile()

    stored = json.loads(
        (service.absolute(result.build_dir) / "build.json").read_text(encoding="utf-8")
    )
    assert stored["build_id"] == result.build_id
    assert service.build(result.build_id) == result
    assert service.latest() == result
    assert service.build_ids() == (result.build_id,)


def test_the_compiler_diagnostics_of_a_successful_build_are_still_reported(
    service: CompileService,
) -> None:
    result = service.compile()

    codes = {item.code for item in result.diagnostics}
    assert "citation-undefined" in codes
    assert "overfull-hbox" in codes
    assert result.error_count == 0
    assert result.warning_count >= 2


# -- the command and the environment ----------------------------------------------------


def test_the_command_never_enables_shell_escape_and_writes_only_into_the_build_directory(
    service: CompileService,
) -> None:
    result = service.compile()

    assert "-no-shell-escape" in result.args
    escapes = [item for item in result.args if "shell-escape" in item]
    assert escapes == ["-no-shell-escape"]
    assert f"-output-directory={service.absolute(result.build_dir)}" in result.args
    assert result.args[-1] == "main.tex"


def test_tectonic_is_run_untrusted_and_never_with_the_shell_escape_option(
    repository: WorkspaceRepository, tmp_path: Path
) -> None:
    path = str(install_fake_engine(tmp_path / "tectonic-bin", "tectonic"))
    service = CompileService(
        repository.layout,
        ManuscriptSettings(),
        search_path=path,
        environ={"PATH": path, "HOME": str(repository.root)},
    )

    result = service.compile()

    assert result.engine is LatexEngine.TECTONIC
    assert "--untrusted" in result.args
    assert "-Z" not in result.args
    assert not [item for item in result.args if "shell-escape" in item]


def test_the_engine_runs_in_the_manuscript_directory_with_a_scrubbed_environment(
    repository: WorkspaceRepository, fake_path: str
) -> None:
    service = CompileService(
        repository.layout,
        ManuscriptSettings(),
        search_path=fake_path,
        environ={
            "PATH": fake_path,
            "HOME": str(repository.root),
            "TEXINPUTS": "/somewhere/evil:",
            "TEXMFHOME": "/somewhere/evil",
            "RESEARCH_HARNESS_SECRET": "hunter2",
        },
    )

    result = service.compile()
    dumped = env_dump(service, result)
    environment = dumped["env"]
    assert isinstance(environment, dict)

    assert dumped["cwd"] == str(repository.layout.manuscript_dir)
    assert environment["TEXINPUTS"] == f".{os.pathsep}"
    assert environment["TEXMFHOME"] is None
    assert environment["RESEARCH_HARNESS_SECRET"] is None
    assert environment["shell_escape"] == "f"
    assert environment["openout_any"] == "p"
    assert environment["TEXMFOUTPUT"] == str(service.absolute(result.build_dir))


# -- a failing build --------------------------------------------------------------------


def test_a_syntax_error_yields_file_and_line_while_the_last_good_pdf_survives_as_stale(
    service: CompileService, repository: WorkspaceRepository
) -> None:
    good = service.compile()
    assert good.status is CompileStatus.SUCCEEDED

    mark(repository, "fail")
    failed = service.compile()

    assert failed.status is CompileStatus.FAILED
    assert failed.pdf is None
    errors = failed.errors
    assert errors and errors[0].file == "sections/intro.tex"
    assert errors[0].line == 10
    assert errors[0].severity is DiagnosticSeverity.ERROR

    assert failed.last_good is not None
    assert failed.last_good.build_id == good.build_id
    assert failed.last_good.stale is True
    assert failed.last_good.compiled_at == good.finished_at
    assert service.absolute(failed.last_good.pdf).read_bytes().startswith(b"%PDF")


def test_a_failed_build_does_not_move_the_last_good_pointer(
    service: CompileService, repository: WorkspaceRepository
) -> None:
    good = service.compile()
    mark(repository, "fail")
    service.compile()

    pointer = service.last_good()

    assert pointer is not None
    assert pointer.build_id == good.build_id
    assert pointer.stale is False, "the pointer itself records the good build, not the verdict"


def test_a_successful_build_after_a_failure_takes_the_pointer_back(
    service: CompileService, repository: WorkspaceRepository
) -> None:
    service.compile()
    mark(repository, "fail")
    service.compile()

    files = ManuscriptFiles(repository.layout)
    snapshot = files.read("sections/intro.tex")
    files.write(
        "sections/intro.tex",
        snapshot.content.replace("% fake-latex: fail", ""),
        snapshot.content_hash,
    )
    recovered = service.compile()

    assert recovered.status is CompileStatus.SUCCEEDED
    assert recovered.last_good is not None
    assert recovered.last_good.build_id == recovered.build_id
    assert recovered.last_good.stale is False


def test_a_failure_raises_only_when_the_caller_asks_for_an_exception(
    service: CompileService, repository: WorkspaceRepository
) -> None:
    mark(repository, "fail")

    result = service.compile()

    from research_harness.manuscript.compile import CompileFailedError

    with pytest.raises(CompileFailedError) as error:
        result.raise_for_status()
    assert error.value.result is result
    assert "sections/intro.tex:10" in str(error.value)


# -- a hanging build --------------------------------------------------------------------


def test_a_timeout_kills_the_whole_process_group_and_keeps_the_diagnostics(
    service: CompileService, repository: WorkspaceRepository
) -> None:
    mark(repository, "timeout")

    result = service.compile(timeout_seconds=1.0)

    assert result.status is CompileStatus.TIMED_OUT
    assert result.timed_out is True
    assert result.diagnostics, "the log written before the hang is still parsed"

    pid_file = service.absolute(result.build_dir) / "fake-child.pid"
    assert pid_file.is_file(), "the fake engine started a child before hanging"
    child = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except (ProcessLookupError, PermissionError):
            break
        time.sleep(0.05)
    else:  # pragma: no cover - the group survived, which is the bug this test exists for
        pytest.fail(f"the engine's child {child} outlived the killed process group")

    with pytest.raises(CompileTimeoutError):
        result.raise_for_status()


# -- SyncTeX ----------------------------------------------------------------------------


def test_synctex_resolves_both_ways_for_a_build_that_produced_a_map(
    service: CompileService,
) -> None:
    result = service.compile()

    index = service.synctex(result.build_id)

    assert index.available
    assert index.files == ("main.tex", "sections/intro.tex")
    located = index.forward("main.tex", 4)
    assert located
    back = index.inverse(located[0].page, located[0].x + 1, located[0].y + 1)
    assert back is not None and back.file == "main.tex"


def test_an_engine_that_cannot_produce_synctex_is_reported_honestly(
    service: CompileService, repository: WorkspaceRepository
) -> None:
    mark(repository, "no-synctex")

    result = service.compile()

    assert result.status is CompileStatus.SUCCEEDED
    assert result.synctex is None
    index = service.synctex(result.build_id)
    assert not index.available
    assert index.state is not None
    assert index.state.reason is SynctexUnavailableReason.MISSING_FILE


def test_turning_synctex_off_in_research_yaml_neither_asks_for_it_nor_pretends(
    repository: WorkspaceRepository, fake_path: str
) -> None:
    service = CompileService(
        repository.layout,
        ManuscriptSettings(synctex=False),
        search_path=fake_path,
        environ={"PATH": fake_path, "HOME": str(repository.root)},
    )

    result = service.compile()

    assert "-synctex=1" not in result.args
    assert result.synctex is None
    state = service.synctex(result.build_id).state
    assert state is not None and state.reason is SynctexUnavailableReason.NOT_REQUESTED


# -- refusals ---------------------------------------------------------------------------


def test_a_missing_toolchain_gives_setup_guidance_and_changes_no_source_file(
    repository: WorkspaceRepository, tmp_path: Path
) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    service = CompileService(
        repository.layout, ManuscriptSettings(), search_path=str(empty), environ={}
    )
    before = service.files.fingerprint()

    with pytest.raises(ToolchainUnavailableError) as error:
        service.compile()

    assert "No LaTeX engine was found on PATH." in str(error.value)
    assert "No manuscript source was read or modified." in error.value.report.guidance
    assert service.files.fingerprint() == before
    assert not service.build_root.exists()


def test_an_entry_file_outside_the_manuscript_directory_is_refused(
    service: CompileService,
) -> None:
    with pytest.raises(ManuscriptPathError):
        service.compile(entry_file="../../etc/passwd.tex")

    assert not service.build_root.exists()


def test_an_entry_file_that_does_not_exist_says_which_setting_names_it(
    service: CompileService,
) -> None:
    with pytest.raises(ManuscriptFileNotFoundError) as error:
        service.compile(entry_file="paper.tex")

    assert "manuscript.entry_file" in str(error.value)


# -- disposability ----------------------------------------------------------------------


def test_deleting_the_build_directory_loses_only_build_outputs(
    service: CompileService, repository: WorkspaceRepository
) -> None:
    first = service.compile()
    sources = {item.path: service.files.read(item.path).content for item in service.files.tree()}

    shutil.rmtree(repository.layout.research_dir / "build")

    assert service.build_ids() == ()
    assert service.last_good() is None
    assert {
        item.path: service.files.read(item.path).content for item in service.files.tree()
    } == sources

    again = service.compile()
    assert again.status is CompileStatus.SUCCEEDED
    assert again.pdf is not None and service.absolute(again.pdf).is_file()
    assert again.inputs_fingerprint == first.inputs_fingerprint
    assert again.build_id.endswith(first.build_id.rsplit("-", 1)[-1]), (
        "the id is a timestamp plus the inputs fingerprint, so rebuilding the same source "
        "into an emptied build directory reproduces it"
    )


def test_two_builds_of_the_same_source_get_distinct_ids(service: CompileService) -> None:
    first = service.compile()
    second = service.compile()

    assert first.build_id != second.build_id
    assert service.build_ids() == (second.build_id, first.build_id)
    assert service.latest() == second


def test_a_last_good_pointer_whose_pdf_was_deleted_is_not_offered(
    service: CompileService,
) -> None:
    result = service.compile()
    assert result.pdf is not None
    service.absolute(result.pdf).unlink()

    assert service.last_good() is None


def test_settings_come_from_the_manuscript_section_of_research_yaml(
    tmp_path: Path, fake_path: str
) -> None:
    repo = WorkspaceRepository.init(tmp_path / "configured", "configured")
    copy_project(repo.layout.manuscript_dir)
    path = repo.layout.research_file
    path.write_text(
        path.read_text(encoding="utf-8")
        + "manuscript:\n  entry_file: main.tex\n  timeout_seconds: 30\n  synctex: false\n",
        encoding="utf-8",
    )
    reopened = WorkspaceRepository.open(repo.root)

    service = CompileService.for_repository(
        reopened, search_path=fake_path, environ={"PATH": fake_path}
    )

    assert service.settings.timeout_seconds == 30
    assert service.settings.synctex is False
    assert service.compile().timeout_seconds == 30


# -- the machine's own toolchain --------------------------------------------------------


@pytest.mark.skipif(
    not (REAL_LATEX and INSTALLED_ENGINE),
    reason="set RESEARCH_HARNESS_REAL_LATEX=1 with a LaTeX engine on PATH; a real engine "
    "may fetch its support files over the network, which the rest of the suite must not",
)
def test_the_installed_toolchain_compiles_the_fixture_project(
    repository: WorkspaceRepository,
) -> None:
    service = CompileService(repository.layout, ManuscriptSettings(timeout_seconds=600))

    result = service.compile()

    assert result.status is CompileStatus.SUCCEEDED, result.stderr_tail
    assert result.pdf is not None
    assert service.absolute(result.pdf).read_bytes().startswith(b"%PDF")
    index = service.synctex(result.build_id)
    assert index.available
    assert "sections/intro.tex" in index.files
    located = index.forward("sections/intro.tex", 4)
    assert located
    back = index.inverse(located[0].page, located[0].x + 1, located[0].y + 1)
    assert back is not None and back.file == "sections/intro.tex"

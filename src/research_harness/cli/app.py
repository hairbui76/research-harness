"""`research` command-line entry point.

The CLI is a thin client: it must never touch canonical files or projections
directly. Everything it does goes through application capabilities (ADR-004).

`app.py` owns the root callback, `research doctor`, and `research shell`; every command
family lives in `cli/commands/` and is mounted by `register_all`.

`research shell` is here rather than in a command module because it is about the entry
point itself: importing the harness costs about a second, and a review loop is dozens of
commands, so the loop that keeps one process alive belongs beside the application it
dispatches into (dogfood F20).
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from research_harness import __version__
from research_harness.cli.commands import register_all
from research_harness.cli.context import WORKSPACE_ENV

if TYPE_CHECKING:  # pragma: no cover - typing only; the checks import lazily
    from research_harness.workspace.repository import WorkspaceRepository

MIN_PYTHON = (3, 12)

#: Tools `research doctor` reports on but never requires: they build the Web cockpit and
#: the VS Code extension, neither of which the CLI or the daemon needs.
OPTIONAL_TOOLS: tuple[tuple[str, str], ...] = (
    ("node", "Web cockpit and VS Code extension builds"),
    ("pnpm", "Web cockpit and VS Code extension builds"),
)

app = typer.Typer(
    name="research",
    help="Local-first, provider-neutral research harness.",
    no_args_is_help=True,
    add_completion=False,
)


@dataclass(frozen=True)
class DoctorCheck:
    """One line of `research doctor` output."""

    name: str
    ok: bool
    detail: str

    note: bool = False
    """Informational: printed as `[note]` and never a reason to exit non-zero."""


def _check_python() -> DoctorCheck:
    current = sys.version_info[:2]
    ok = current >= MIN_PYTHON
    want = ".".join(map(str, MIN_PYTHON))
    return DoctorCheck("python", ok, f"{platform.python_version()} (requires >= {want})")


def _check_import(name: str) -> DoctorCheck:
    try:
        module = import_module(name)
    except ImportError as exc:
        return DoctorCheck(name, False, str(exc))
    found = getattr(module, "__version__", "present")
    return DoctorCheck(name, True, str(found))


def _check_fts5() -> DoctorCheck:
    """FTS5 is what exact-terminology search runs on; without it a rebuild cannot index."""
    try:
        from sqlalchemy import create_engine

        from research_harness.projection.schema import assert_fts5_available

        engine = create_engine("sqlite+pysqlite://")
        try:
            assert_fts5_available(engine)
        finally:
            engine.dispose()
    except Exception as exc:  # any failure here means no lexical index at all
        return DoctorCheck("sqlite-fts5", False, str(exc))
    return DoctorCheck("sqlite-fts5", True, "available")


def _check_tool(name: str, purpose: str) -> DoctorCheck:
    """Report an optional build tool without ever making its absence a failure."""
    found = shutil.which(name)
    detail = found if found else f"not installed (only needed for {purpose})"
    return DoctorCheck(name, True, detail, note=not found)


def _environment_checks() -> list[DoctorCheck]:
    """Checks that need no workspace: the interpreter, the packages, SQLite, the tooling."""
    return [
        DoctorCheck("research-harness", True, __version__),
        _check_python(),
        _check_import("pydantic"),
        _check_import("typer"),
        _check_fts5(),
        *(_check_tool(name, purpose) for name, purpose in OPTIONAL_TOOLS),
    ]


# -- workspace checks --------------------------------------------------------


def _found_workspace(explicit: Path | None) -> Path | None:
    """The workspace `-w`, `RESEARCH_WORKSPACE`, or the walk-up finds; `None` when none does."""
    from research_harness.cli.context import resolve_workspace
    from research_harness.domain.errors import ResearchHarnessError

    try:
        return resolve_workspace(explicit)
    except ResearchHarnessError:
        return None


def _marker_check(root: Path) -> DoctorCheck:
    """Whether a *regular* open would stand on `.research/consistency-check.json`.

    Read before `doctor` opens, because opening in full rewrites the marker and would make
    the answer trivially yes. It is a read of one small file and a `stat` per canonical
    file: nothing is opened, locked, or written. The line answers the question a researcher
    actually has — "has anything actually been verified lately, or has every open been
    quoting a cached verdict?" — which is what
    `ConsistencyReport.skipped_reason` says on an ordinary open.
    """
    from research_harness.workspace.events import read_consistency_marker
    from research_harness.workspace.layout import WorkspaceLayout

    layout = WorkspaceLayout(root)
    marker = read_consistency_marker(layout)
    if marker is None:
        return DoctorCheck(
            "verification", True, "no marker: every open verifies in full", note=True
        )
    if not marker.matches(layout):
        return DoctorCheck(
            "verification",
            True,
            "marker is stale; the next open verifies in full",
            note=True,
        )
    return DoctorCheck(
        "verification",
        True,
        f"a regular open skips the full check ({marker.reason}, "
        f"{marker.checked} objects); this run verifies in full anyway",
        note=True,
    )


def _workspace_checks(root: Path) -> list[DoctorCheck]:
    """Everything `doctor` can say about one workspace without changing it.

    The workspace is opened with ``repair=True`` so an inconsistent one is *reported* here
    rather than raising: telling a researcher what disagrees is the whole job of this
    command, and opening for a report writes nothing scientific (ADR-001).

    It is also opened with ``verify="full"``. An ordinary open may stand on
    `.research/consistency-check.json` and report a verdict it did not re-derive; `doctor`
    is the command whose entire job is the guarantee, so it re-derives every digest the
    event log names and says separately whether a regular open would have skipped it.
    """
    from research_harness.workspace.repository import WorkspaceRepository

    marker = _marker_check(root)
    try:
        repo = WorkspaceRepository.open(root, repair=True, verify="full")
    except Exception as exc:  # an unopenable workspace is the finding, not a crash
        return [DoctorCheck("workspace", False, f"{root}: {exc}"), marker]

    checks = [
        DoctorCheck(
            "workspace",
            True,
            f"{repo.root} (schema {repo.config.schema_version}, policy {repo.review_policy.value})",
        ),
        marker,
        _consistency_check(repo),
    ]
    if repo.recovery.changed:
        checks.append(DoctorCheck("journal", True, repo.recovery.summary(), note=True))
    checks.append(_projection_check(repo))
    checks.extend(_provider_checks(repo))
    checks.append(_egress_check(repo))
    checks.append(_token_check(repo.root))
    checks.append(_plugin_check(repo.root))
    return checks


def _consistency_check(repo: WorkspaceRepository) -> DoctorCheck:
    """Canonical files against the semantic event log (Product 8.2), re-derived in full.

    `doctor` opens with ``verify="full"``, so this report is never a cached verdict; a
    `skipped_reason` here would mean the guarantee was not actually taken and is reported
    as a failure rather than quietly printed as a pass.
    """
    report = repo.consistency
    if report.skipped_reason is not None:  # pragma: no cover - `verify="full"` cannot skip
        return DoctorCheck(
            "consistency", False, f"the full check did not run: {report.skipped_reason}"
        )
    return DoctorCheck("consistency", report.consistent, report.summary())


def _projection_check(repo: WorkspaceRepository) -> DoctorCheck:
    """Is `.research/research.db` there, and does it still agree with canonical state?"""
    from research_harness.projection.rebuild import verify_rebuild
    from research_harness.projection.schema import create_engine_for

    database = repo.layout.database_file
    if not database.is_file():
        return DoctorCheck("projection", True, "not built yet; run `research rebuild`", note=True)
    engine = create_engine_for(database)
    try:
        issues = verify_rebuild(repo, engine)
    except Exception as exc:  # an unreadable projection is the finding, not a crash
        return DoctorCheck("projection", False, f"{database.name}: {exc}")
    finally:
        engine.dispose()
    if issues:
        detail = "; ".join(issues[:3])
        more = "" if len(issues) <= 3 else f" (+{len(issues) - 3} more)"
        return DoctorCheck(
            "projection",
            False,
            f"{len(issues)} discrepancy(ies), run `research rebuild`: {detail}{more}",
        )
    return DoctorCheck("projection", True, f"{database.name} agrees with canonical state")


def _provider_checks(repo: WorkspaceRepository) -> list[DoctorCheck]:
    """Configured model providers and whether their key variables are set — names only."""
    from research_harness.privacy.egress import MODEL_KEY_ENV_VARS
    from research_harness.providers.models.router import RouterConfig

    try:
        config = RouterConfig.model_validate({"providers": list(repo.config.providers)})
    except Exception as exc:  # a bad `providers:` block is the finding, not a crash
        return [DoctorCheck("providers", False, f"research.yaml `providers:` is invalid: {exc}")]
    if not config.providers:
        return [
            DoctorCheck(
                "providers",
                True,
                "none configured; run offline with `--provider scripted --script <file>`",
                note=True,
            )
        ]

    lines: list[DoctorCheck] = [
        DoctorCheck("providers", True, f"{len(config.providers)} configured in research.yaml")
    ]
    for entry in config.providers:
        variable = entry.api_key_env or MODEL_KEY_ENV_VARS[entry.kind]
        # The *name* of the variable and a boolean, never a value (Product 34).
        present = bool(os.environ.get(variable, "").strip())
        state = "set" if present else "unset"
        enabled = "" if entry.enabled else ", disabled"
        lines.append(
            DoctorCheck(
                f"  {entry.name}",
                True,
                f"{entry.kind}/{entry.model}, {variable} {state}{enabled}",
                note=not present and entry.enabled,
            )
        )
    return lines


def _egress_check(repo: WorkspaceRepository) -> DoctorCheck:
    """One line of the project's egress policy; `research egress` prints the whole table."""
    policy = repo.config.privacy
    hosts = ", ".join(policy.allowed_hosts) if policy.allowed_hosts else "any declared host"
    return DoctorCheck(
        "egress policy",
        True,
        f"external models {policy.external_models}, search {policy.search_providers}, "
        f"hosts {hosts}, traces "
        f"{'redacted' if policy.redact_traces else 'verbatim'}",
        note=True,
    )


def _token_check(root: Path) -> DoctorCheck:
    """Whether the daemon token exists. Its path is reported; its content never is."""
    from research_harness.server.app import token_path

    path = token_path(root)
    if path.is_file():
        return DoctorCheck("daemon token", True, str(path), note=True)
    return DoctorCheck(
        "daemon token", True, "not created yet; `research serve` or `research token`", note=True
    )


def _plugin_check(root: Path) -> DoctorCheck:
    """Where plugins would be loaded from, and which ones are there."""
    from research_harness.cli.plugins import plugin_roots
    from research_harness.plugins import discover_plugins

    roots = plugin_roots(root)
    if not roots:
        return DoctorCheck("plugins", True, "no plugin directory found", note=True)
    found = sorted(directory.name for directory in discover_plugins(roots))
    listed = ", ".join(found) if found else "none"
    searched = ", ".join(str(directory) for directory in roots)
    return DoctorCheck("plugins", True, f"{listed} (in {searched})", note=True)


def run_doctor(workspace: Path | None = None) -> list[DoctorCheck]:
    """Collect environment checks, plus workspace checks when a workspace is found.

    Requires no network access and no API keys: every provider line reports the *name* of a
    credential variable and whether it is set, never a value (Product 34).
    """
    checks = _environment_checks()
    root = _found_workspace(workspace)
    if root is not None:
        checks.extend(_workspace_checks(root))
    return checks


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"research {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the harness version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Local-first, provider-neutral research harness."""


@app.command()
def doctor(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            envvar="RESEARCH_WORKSPACE",
            help="Workspace to check; defaults to the nearest research.yaml above the "
            "current directory. Environment checks run either way.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Check that the local environment can run the harness, and report on the workspace."""
    checks = run_doctor(workspace)
    width = max(len(check.name) for check in checks)
    for check in checks:
        mark = "note" if check.note else ("ok  " if check.ok else "FAIL")
        typer.echo(f"[{mark}] {check.name.ljust(width)}  {check.detail}")
    if not all(check.ok for check in checks):
        raise typer.Exit(code=1)


SHELL_PROMPT = "research> "

#: Words that end the shell. `exit` and `quit` are what people type; Ctrl-D also ends it.
SHELL_EXIT: frozenset[str] = frozenset({"exit", "quit"})

SHELL_BANNER = (
    "research shell — the harness stays loaded, so each command costs its own work and "
    "not another import.\nType a command without the leading `research`. `exit`, `quit`, "
    "or Ctrl-D to leave."
)


@app.command()
def shell(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            envvar="RESEARCH_WORKSPACE",
            help="Workspace every command in this session defaults to.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Run many commands in one process, so the interpreter is started once.

    Importing the harness costs about a second, and the review loop is dozens of commands:
    the dogfood session spent roughly 80 of 90 seconds importing rather than reviewing
    (dogfood F20). `research serve` already avoids that for a host; this is the same
    saving for the documented path, the CLI.

    Nothing else changes. Each line is dispatched through exactly the same Typer
    application in the same standalone mode a terminal uses, so every command behaves,
    prints, and refuses identically — the shell is a loop around the entry point, not a
    second entry point. State is not carried between commands either: each one opens the
    workspace itself, so a shell session and the same commands typed separately leave the
    same workspace behind. Like a shell, the session exits with the status of the last
    command it ran, so a piped script still fails loudly.
    """
    from typer.main import get_command

    command = get_command(app)
    typer.echo(SHELL_BANNER)
    status = 0
    # `-w` once rather than on every line; a command naming its own `--workspace` still
    # wins, because an explicit option beats an envvar. Scoped to the session: the variable
    # is put back on the way out, so a shell cannot change the process it ran in.
    with _session_workspace(workspace):
        for line in _shell_lines():
            if line.strip().casefold() in SHELL_EXIT:
                break
            argv = _shell_argv(line)
            if argv is None:
                continue
            if argv[0] == "shell":
                typer.secho("error: already in a shell", err=True, fg=typer.colors.RED)
                status = 1
                continue
            status = _run_line(command, argv)
    if status:
        raise typer.Exit(code=status)


@contextmanager
def _session_workspace(workspace: Path | None) -> Iterator[None]:
    """Set `RESEARCH_WORKSPACE` for the session, and restore whatever was there before."""
    if workspace is None:
        yield
        return
    previous = os.environ.get(WORKSPACE_ENV)
    os.environ[WORKSPACE_ENV] = str(workspace)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(WORKSPACE_ENV, None)
        else:
            os.environ[WORKSPACE_ENV] = previous


def _run_line(command: Any, argv: list[str]) -> int:
    """Run one command exactly as a terminal would, and report its exit code.

    Deliberately run in Click's *standalone* mode: it is what prints a usage error, a
    refusal, and a traceback-free `error: ...` line the way every other invocation prints
    them, so a command reads identically inside the shell and outside it. Standalone mode
    ends in `sys.exit`, which is a `SystemExit` here rather than the end of the process —
    the one difference the shell exists to make. Anything that is not an exit is a bug and
    is left to propagate.
    """
    try:
        command.main(args=argv, prog_name="research", standalone_mode=True)
    except SystemExit as exit_status:
        code = exit_status.code
        return code if isinstance(code, int) else int(bool(code))
    return 0


def _shell_lines() -> Iterator[str]:
    """Every line the researcher types, prompting when there is a terminal to prompt."""
    interactive = sys.stdin.isatty()
    while True:
        if interactive:
            typer.echo(SHELL_PROMPT, nl=False)
        line = sys.stdin.readline()
        if not line:  # Ctrl-D, or the end of a piped script
            if interactive:
                typer.echo("")
            return
        yield line


def _shell_argv(line: str) -> list[str] | None:
    """One typed line as an argument list; `None` for a blank line or an unclosed quote."""
    import shlex

    text = line.strip()
    if not text or text.startswith("#"):
        return None
    try:
        argv = shlex.split(text)
    except ValueError as exc:
        typer.secho(f"error: {exc}", err=True, fg=typer.colors.RED)
        return None
    return argv or None


register_all(app)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()

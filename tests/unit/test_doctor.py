"""`research doctor`: environment checks always, workspace checks when one is found.

The command is the first thing a new user runs and the first thing a stuck user runs, so
the properties under test are about what it is safe to print and when it is allowed to
fail: never a credential value, never a non-zero exit for a missing optional tool, and
always a non-zero exit for a workspace whose canonical state and event log disagree.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from research_harness.cli.app import DoctorCheck, app, run_doctor
from research_harness.cli.context import WORKSPACE_ENV
from research_harness.workspace.repository import WorkspaceRepository

runner = CliRunner()

BASE_CHECKS = {"research-harness", "python", "pydantic", "typer", "sqlite-fts5"}
WORKSPACE_CHECKS = {
    "workspace",
    "verification",
    "consistency",
    "projection",
    "providers",
    "egress policy",
}

KEY_VARIABLE = "RESEARCH_HARNESS_TEST_KEY"
SECRET = "sk-this-must-never-be-printed"


def named(checks: list[DoctorCheck]) -> dict[str, DoctorCheck]:
    return {check.name.strip(): check for check in checks}


@pytest.fixture
def elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory with no workspace at or above it, and no workspace in the environment."""
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    empty = tmp_path / "no-workspace"
    empty.mkdir()
    monkeypatch.chdir(empty)
    return empty


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An initialised workspace, with no workspace inherited from the environment."""
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    root = tmp_path / "project"
    WorkspaceRepository.init(root, "doctor-fixture")
    return root


# -- environment -------------------------------------------------------------


def test_without_a_workspace_only_the_environment_checks_run(elsewhere: Path) -> None:
    checks = named(run_doctor())

    assert set(checks) >= BASE_CHECKS
    assert not WORKSPACE_CHECKS & set(checks)
    assert all(check.ok for check in checks.values()), checks


def test_the_cli_reports_the_environment_and_exits_zero(elsewhere: Path) -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "[ok  ] python" in result.output
    assert "FAIL" not in result.output


def test_a_missing_optional_build_tool_is_a_note_and_not_a_failure(
    elsewhere: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`node`/`pnpm` build the Web cockpit and the extension; the CLI needs neither."""
    monkeypatch.setattr("research_harness.cli.app.shutil.which", lambda _name: None)

    checks = named(run_doctor())

    for tool in ("node", "pnpm"):
        assert checks[tool].note is True
        assert checks[tool].ok is True
        assert "not installed" in checks[tool].detail
    assert runner.invoke(app, ["doctor"]).exit_code == 0


# -- workspace ---------------------------------------------------------------


def test_a_workspace_adds_its_own_checks(workspace: Path) -> None:
    checks = named(run_doctor(workspace))

    assert set(checks) >= WORKSPACE_CHECKS
    assert str(workspace) in checks["workspace"].detail
    assert "schema 1" in checks["workspace"].detail
    assert "policy strict" in checks["workspace"].detail
    assert checks["consistency"].ok


def test_the_workspace_is_found_by_walking_up_like_every_other_command(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside = workspace / "corpus" / "works"
    monkeypatch.chdir(inside)

    checks = named(run_doctor())

    assert str(workspace) in checks["workspace"].detail


def test_the_workspace_env_var_is_honoured(
    workspace: Path, elsewhere: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert str(workspace) in result.output


def test_an_unbuilt_projection_is_a_note_rather_than_a_failure(workspace: Path) -> None:
    checks = named(run_doctor(workspace))

    assert checks["projection"].note is True
    assert "research rebuild" in checks["projection"].detail
    assert runner.invoke(app, ["doctor", "-w", str(workspace)]).exit_code == 0


def test_a_built_projection_that_agrees_with_canonical_state_passes(workspace: Path) -> None:
    from research_harness.projection.rebuild import rebuild_workspace

    rebuild_workspace(WorkspaceRepository.open(workspace))

    checks = named(run_doctor(workspace))

    assert checks["projection"].ok and not checks["projection"].note
    assert "agrees with canonical state" in checks["projection"].detail


def test_a_hand_edited_canonical_file_fails_the_consistency_check(workspace: Path) -> None:
    """Canonical files are authoritative; when the event log disagrees, doctor says so."""
    created = runner.invoke(
        app, ["claim", "create", "a claim to corrupt afterwards", "-w", str(workspace)]
    )
    assert created.exit_code == 0, created.output
    claim_file = workspace / "claims" / "C0001.yaml"
    claim_file.write_text(
        claim_file.read_text(encoding="utf-8").replace("a claim to corrupt", "something else"),
        encoding="utf-8",
    )

    checks = named(run_doctor(workspace))

    assert checks["consistency"].ok is False
    assert "C0001" in checks["consistency"].detail
    assert runner.invoke(app, ["doctor", "-w", str(workspace)]).exit_code == 1


# -- verification ------------------------------------------------------------


def test_doctor_verifies_in_full_even_when_a_regular_open_would_skip(workspace: Path) -> None:
    """`doctor` asks for the guarantee, not the cached verdict, and says which it got."""
    WorkspaceRepository.open(workspace)  # the first open verifies in full and leaves a marker
    regular = WorkspaceRepository.open(workspace)
    assert regular.consistency.skipped_reason is not None, "a settled workspace caches its verdict"

    checks = named(run_doctor(workspace))

    assert checks["verification"].note is True
    assert "a regular open skips the full check" in checks["verification"].detail
    assert checks["consistency"].ok
    assert "verification skipped" not in checks["consistency"].detail


def test_doctor_catches_the_hand_edit_a_marker_based_open_waves_through(
    workspace: Path,
) -> None:
    """The reason `doctor` may not use the marker: an edit that leaves size and mtime alone.

    `ConsistencyMarker` proves a tree unchanged with one `stat` per file, which is what makes
    it cheap; an edit that preserves both defeats it. A regular open therefore repeats a
    verdict that is no longer true, and only `verify="full"` re-derives the digest and sees
    that `C0001` no longer matches the event that recorded it.
    """
    created = runner.invoke(
        app,
        ["claim", "create", "a claim the marker must not hide an edit to", "-w", str(workspace)],
    )
    assert created.exit_code == 0, created.output
    claim_file = workspace / "claims" / "C0001.yaml"
    before = claim_file.stat()
    original = claim_file.read_bytes()
    edited = original.replace(b"must not", b"must NOT")
    assert len(edited) == len(original)
    claim_file.write_bytes(edited)
    os.utime(claim_file, ns=(before.st_atime_ns, before.st_mtime_ns))

    cached = WorkspaceRepository.open(workspace, repair=True)
    assert cached.consistency.skipped_reason is not None
    assert cached.consistency.consistent, "the cached verdict is stale, and says nothing is wrong"

    checks = named(run_doctor(workspace))

    assert checks["consistency"].ok is False
    assert "C0001" in checks["consistency"].detail
    assert runner.invoke(app, ["doctor", "-w", str(workspace)]).exit_code == 1


def test_a_workspace_with_no_marker_yet_says_every_open_verifies_in_full(
    workspace: Path,
) -> None:
    (workspace / ".research" / "consistency-check.json").unlink(missing_ok=True)

    checks = named(run_doctor(workspace))

    assert checks["verification"].note is True
    assert "no marker" in checks["verification"].detail
    assert checks["consistency"].ok


# -- providers and secrets ---------------------------------------------------


def test_a_workspace_with_no_providers_says_so_without_failing(workspace: Path) -> None:
    checks = named(run_doctor(workspace))

    assert checks["providers"].note is True
    assert "scripted" in checks["providers"].detail


def test_provider_lines_name_the_key_variable_and_never_its_value(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Product 34: the report is safe to paste into an issue."""
    monkeypatch.setenv(KEY_VARIABLE, SECRET)
    _write_providers(
        workspace,
        [{"name": "fast", "kind": "openai", "model": "gpt-x", "api_key_env": KEY_VARIABLE}],
    )

    checks = run_doctor(workspace)
    entry = named(checks)["fast"]
    result = runner.invoke(app, ["doctor", "-w", str(workspace)])

    assert entry.detail == f"openai/gpt-x, {KEY_VARIABLE} set"
    assert SECRET not in result.output
    assert KEY_VARIABLE in result.output


def test_an_unset_provider_key_is_a_note_rather_than_a_failure(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY_VARIABLE, raising=False)
    _write_providers(
        workspace,
        [{"name": "fast", "kind": "openai", "model": "gpt-x", "api_key_env": KEY_VARIABLE}],
    )

    entry = named(run_doctor(workspace))["fast"]

    assert entry.note is True and entry.ok is True
    assert f"{KEY_VARIABLE} unset" in entry.detail
    assert runner.invoke(app, ["doctor", "-w", str(workspace)]).exit_code == 0


def test_the_egress_policy_line_summarises_research_yaml(workspace: Path) -> None:
    entry = named(run_doctor(workspace))["egress policy"]

    assert entry.note is True
    assert "external models allowed" in entry.detail
    assert "traces verbatim" in entry.detail


def _write_providers(root: Path, providers: list[dict[str, object]]) -> None:
    """Add a `providers:` block the way a researcher would, by editing research.yaml."""
    path = root / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = providers
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

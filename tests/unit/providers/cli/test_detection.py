"""A scan is fresh, bounded, fault-isolated, ordered, and secret-free (spec §10, §21)."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from research_harness.providers.cli.detection import (
    DEFAULT_MODEL_OPTION,
    ScanCache,
    compatibility_of,
    detect,
    resolve_executable,
    scan,
)
from research_harness.providers.cli.types import (
    BoundedPosture,
    CliModelOption,
    CliRuntimeDef,
    Probe,
    ProbeOutcome,
)
from tests.fixtures.cli.fakes import FakeCli
from tests.unit.providers.cli.test_registry import definition


def classify_auth(outcome: ProbeOutcome) -> tuple[str, str]:
    # The exit code is half the evidence: "Not logged in" contains "logged in" too.
    if outcome.exit_code == 0 and "logged in" in outcome.stdout.lower():
        return "ok", ""
    return "missing", "run `fake login`"


def parse_models(outcome: ProbeOutcome) -> tuple[CliModelOption, ...] | None:
    ids = [line.strip() for line in outcome.stdout.splitlines() if line.strip()]
    return tuple(CliModelOption(id=item, label=item) for item in ids) or None


def full_definition(**overrides: object) -> CliRuntimeDef:
    values: dict[str, object] = {
        "auth_probe": Probe(args=("login", "status")),
        "classify_auth": classify_auth,
        "model_probe": Probe(args=("models",)),
        "parse_models": parse_models,
        "fallback_models": (CliModelOption(id="fallback-1", label="Fallback"),),
        "posture": BoundedPosture(
            kind="native_flags",
            help_probe=Probe(args=("exec", "--help")),
            required_help_flags=("--sandbox", "--json"),
        ),
        "verified_versions": ("1.2.3",),
        "blocked_versions": ("0.9.0",),
        "minimum_version": "1.0.0",
    }
    values.update(overrides)
    return definition(**values)


def installed(tmp_path: Path, **script: object) -> FakeCli:
    probes = [
        {"args": ["login", "status"], "stdout": "Logged in using Fake\n"},
        {"args": ["models"], "stdout": "fake-large\nfake-small\n"},
        {"args": ["exec", "--help"], "stdout": "Usage: fake exec [--sandbox MODE] [--json]\n"},
    ]
    # `**script` is `object`-typed on purpose so a caller can override any script field.
    return FakeCli.install(tmp_path, "fake", probes=probes, **script)  # type: ignore[arg-type]


# -- executables -------------------------------------------------------------


def test_the_executable_is_found_on_the_effective_path_and_fallbacks_are_tried(
    tmp_path: Path,
) -> None:
    fake = FakeCli.install(tmp_path, "fake-alt")
    assert resolve_executable(definition(), fake.env({"PATH": ""})) is None
    assert (
        resolve_executable(definition(fallback_executables=("fake-alt",)), fake.env({"PATH": ""}))
        == fake.executable
    )


def test_windows_resolution_uses_pathext(tmp_path: Path) -> None:
    (tmp_path / "fake.CMD").write_text("@echo off", encoding="utf-8")
    env = {"PATH": str(tmp_path), "PATHEXT": ".EXE;.CMD"}
    assert resolve_executable(definition(), env, platform="win32") == tmp_path / "fake.CMD"
    assert resolve_executable(definition(), env, platform="linux") is None


def test_a_non_executable_file_is_not_a_resolution(tmp_path: Path) -> None:
    plain = tmp_path / "fake"
    plain.write_text("x", encoding="utf-8")
    plain.chmod(plain.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    assert resolve_executable(definition(), {"PATH": str(tmp_path)}) is None


# -- one runtime ---------------------------------------------------------------


def test_a_missing_runtime_is_unavailable_and_probes_nothing_else(tmp_path: Path) -> None:
    status = detect(full_definition(), env={"PATH": str(tmp_path), "HOME": str(tmp_path)})
    assert not status.available and status.executable is None and status.version is None
    assert status.auth_status == "unknown" and status.bounded_mode == "unknown"
    assert status.compatibility == "unknown" and status.model_source == "fallback"
    assert status.diagnostics == ("fake is not installed: no 'fake' on PATH",)


def test_an_installed_logged_in_runtime_is_fully_described(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    status = detect(
        full_definition(),
        env=fake.env({"PATH": "", "HOME": str(tmp_path)}),
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )
    assert status.available and status.version == "fake 1.2.3"
    assert status.executable == "~/bin/fake" or status.executable == str(fake.executable), (
        "home is replaced by ~"
    )
    assert status.auth_status == "ok" and status.bounded_mode == "safe"
    assert [item.id for item in status.models] == ["default", "fake-large", "fake-small"]
    assert status.models[0] == DEFAULT_MODEL_OPTION.as_view()
    assert status.model_source == "live" and status.reasoning_choices == ()
    assert status.egress_kind == "external" and status.egress_host == "example.test"
    assert status.scanned_at == datetime(2026, 9, 4, tzinfo=UTC)


def test_a_rejected_version_flag_is_still_installed(tmp_path: Path) -> None:
    fake = installed(
        tmp_path, version_exit=2, version_stdout="", version_stderr="unknown flag --version"
    )
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert status.available and status.version is None
    assert status.compatibility == "unknown"
    assert any("--version" in line for line in status.diagnostics)


def test_a_logged_out_runtime_is_missing_auth_with_guidance(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script(
        {
            **fake.script(),
            "probes": [{"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1}],
        }
    )
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert status.auth_status == "missing" and status.auth_guidance == "run `fake login`"


def test_no_auth_probe_means_unknown_not_missing(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    status = detect(
        full_definition(auth_probe=None, classify_auth=None), env=fake.env({"PATH": ""})
    )
    assert status.auth_status == "unknown" and "first request" in status.auth_guidance


def test_bounded_mode_needs_every_required_flag_in_the_help_output(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script(
        {
            **fake.script(),
            "probes": [{"args": ["exec", "--help"], "stdout": "Usage: fake exec [--json]\n"}],
        }
    )
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert status.bounded_mode == "unsupported"
    assert any("--sandbox" in line for line in status.diagnostics)


def test_a_failed_help_probe_is_unknown_and_a_none_posture_is_unsupported(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script({**fake.script(), "probes": []})
    assert detect(full_definition(), env=fake.env({"PATH": ""})).bounded_mode == "unknown"
    status = detect(
        full_definition(posture=BoundedPosture(kind="none", note="no deny flag")),
        env=fake.env({"PATH": ""}),
    )
    assert status.bounded_mode == "unsupported"
    assert "fake: no deny flag" in status.diagnostics


def test_models_fall_back_and_say_so_when_the_probe_fails(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script({**fake.script(), "probes": [{"args": ["models"], "stdout": "", "exit": 1}]})
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert [item.id for item in status.models] == [
        "default",
        "fallback-1",
    ] and status.model_source == "fallback"


def test_compatibility_is_a_table_of_versions() -> None:
    d = full_definition()
    assert compatibility_of(d, "1.2.3") == "verified"
    assert compatibility_of(d, "1.3.0") == "warning"
    assert compatibility_of(d, "0.9.0") == "blocked"
    assert compatibility_of(d, "0.9.9") == "blocked", "below the minimum"
    assert compatibility_of(d, None) == "unknown"


def test_a_diagnostic_never_carries_a_home_path_or_a_token(tmp_path: Path) -> None:
    fake = installed(
        tmp_path,
        version_exit=1,
        version_stdout="",
        version_stderr=(
            f"token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 at {tmp_path}/home/.fake\n"
        ),
    )
    status = detect(full_definition(), env=fake.env({"PATH": "", "HOME": str(tmp_path / "home")}))
    joined = " ".join(status.diagnostics)
    assert "sk-proj" not in joined and str(tmp_path / "home") not in joined


# -- the scan ------------------------------------------------------------------


def test_scan_keeps_registry_order_and_isolates_a_broken_runtime(tmp_path: Path) -> None:
    good = installed(tmp_path / "good")
    env = good.env({"PATH": "", "HOME": str(tmp_path)})

    def exploding(outcome: ProbeOutcome) -> str | None:
        raise RuntimeError("boom")

    results = scan(
        [
            full_definition(id="broken", executable="fake", parse_version=exploding),
            full_definition(id="fake"),
        ],
        env=env,
        fresh=True,
        cache=ScanCache(),
    )
    assert [item.runtime for item in results] == ["broken", "fake"]
    assert not results[0].available and results[0].diagnostics == (
        "detection failed: RuntimeError: boom",
    )
    assert results[1].available


def test_scan_never_edits_the_workspace_or_makes_a_model_request(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    scan([full_definition()], env=fake.env({"PATH": ""}), fresh=True, cache=ScanCache())
    assert [call["kind"] for call in fake.calls()] == ["version", "probe", "probe", "probe"]
    assert fake.runs() == []


def test_the_cache_answers_repeat_scans_and_rescan_bypasses_it(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    cache = ScanCache(ttl_seconds=60)
    env = fake.env({"PATH": ""})
    first = scan([full_definition()], env=env, cache=cache)
    second = scan([full_definition()], env=env, cache=cache)
    assert first == second and len([c for c in fake.calls() if c["kind"] == "version"]) == 1
    scan([full_definition()], env=env, cache=cache, fresh=True)
    assert len([c for c in fake.calls() if c["kind"] == "version"]) == 2


def test_probes_run_from_a_neutral_cwd_with_a_bounded_environment(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    detect(full_definition(), env=fake.env({"PATH": "", "OPENAI_API_KEY": "sk-x"}))
    for call in fake.calls():
        assert "OPENAI_API_KEY" not in call["env"]
        assert not call["cwd"].startswith(os.getcwd()) or call["cwd"] != os.getcwd()

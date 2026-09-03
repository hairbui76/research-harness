"""The immutable CLI runtime contracts (CLI providers spec §8, §10)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    CliInvocation,
    CliModelView,
    CliRuntimeStatus,
    Probe,
    ProbeOutcome,
    unavailable_reason,
)


def status(**overrides: object) -> CliRuntimeStatus:
    values: dict[str, object] = {
        "runtime": "codex",
        "name": "Codex CLI",
        "available": True,
        "executable": "~/.local/bin/codex",
        "version": "0.150.1",
        "auth_status": "ok",
        "auth_guidance": "",
        "bounded_mode": "safe",
        "compatibility": "verified",
        "models": (CliModelView(id="default", label="Default (CLI configuration)"),),
        "model_source": "fallback",
        "reasoning_choices": ("low", "medium", "high"),
        "egress_kind": "external",
        "egress_host": "chatgpt.com",
        "diagnostics": (),
        "scanned_at": datetime(2026, 9, 4, tzinfo=UTC),
    }
    values.update(overrides)
    return CliRuntimeStatus.model_validate(values)


def test_a_probe_outcome_knows_whether_the_process_started() -> None:
    started = ProbeOutcome(argv=("codex", "--version"), exit_code=0, stdout="0.1", stderr="")
    missing = ProbeOutcome(
        argv=("codex", "--version"), exit_code=None, stdout="", stderr="", os_error="ENOENT"
    )
    assert started.started and not missing.started
    assert started.text == "0.1\n"


def test_a_probe_has_a_bounded_timeout() -> None:
    assert Probe(args=("--version",)).timeout_seconds == 5.0
    with pytest.raises(ValueError, match="timeout"):
        Probe(args=("--version",), timeout_seconds=0)


def test_an_invocation_is_frozen_data() -> None:
    invocation = CliInvocation(model=None, reasoning=None, cwd=Path("/tmp/x"), request_id="r1")
    with pytest.raises(AttributeError):
        invocation.model = "gpt"  # type: ignore[misc]


def test_a_routable_status_needs_every_gate() -> None:
    assert status().routable
    assert not status(available=False).routable
    assert not status(auth_status="missing").routable
    assert not status(bounded_mode="unsupported").routable
    assert not status(bounded_mode="unknown").routable
    assert not status(compatibility="blocked").routable
    assert status(auth_status="unknown").routable, "unknown auth is verified on first use"
    assert status(compatibility="warning").routable


def test_unavailable_reason_names_the_first_failing_gate() -> None:
    assert unavailable_reason(status()) is None
    assert (
        unavailable_reason(status(available=False)) == "codex is not installed on this workstation"
    )
    assert unavailable_reason(status(auth_status="missing", auth_guidance="run `codex login`")) == (
        "codex is not logged in: run `codex login`"
    )
    assert unavailable_reason(status(bounded_mode="unsupported")) == (
        "codex 0.150.1 has no tested bounded (no-tools, read-only) mode"
    )
    assert unavailable_reason(status(bounded_mode="unknown")) == (
        "codex 0.150.1 could not prove a bounded (no-tools, read-only) mode"
    )
    assert unavailable_reason(status(compatibility="blocked")) == (
        "codex 0.150.1 is a known-incompatible version"
    )


def test_the_routing_verdict_is_serialized_not_only_computed() -> None:
    dumped = status(available=False).model_dump()
    properties = CliRuntimeStatus.model_json_schema(mode="serialization")["properties"]
    assert dumped["routable"] is False
    assert dumped["unavailable_reason"] == "codex is not installed on this workstation"
    assert {"routable", "unavailable_reason"} <= set(properties)


def test_the_unknown_external_host_is_never_local() -> None:
    from research_harness.privacy.policy import is_local_endpoint

    assert not is_local_endpoint(UNKNOWN_EXTERNAL_HOST)

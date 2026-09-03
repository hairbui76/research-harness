"""Opt-in live smoke through the CLIs installed and logged in on this workstation.

Never part of CI: skipped unless `RESEARCH_HARNESS_LIVE_CLI_TESTS=1`, and per runtime
unless the CLI is installed, logged in, and bounded. One minimal schema-validated
request per runtime; no project file is read; on failure nothing raw is printed.

    RESEARCH_HARNESS_LIVE_CLI_TESTS=1 uv run pytest tests/contract/providers/test_live_cli_smoke.py

Set `RESEARCH_HARNESS_LIVE_CLI_CAPTURE=<dir>` to also write a sanitized JSONL capture of
the event stream per runtime, for the parser fixtures.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from research_harness.providers.cli.detection import detect
from research_harness.providers.cli.process import BoundedProcess
from research_harness.providers.cli.provider import CliModelProvider, SpawnFactory
from research_harness.providers.cli.registry import RUNTIMES
from research_harness.providers.cli.types import CliRuntimeStatus
from research_harness.providers.models import InputEnvelope, ModelRequest, ModelRequirements
from tests.contract.providers.conftest import SOURCE_TEXT, Verdict

LIVE_FLAG = "RESEARCH_HARNESS_LIVE_CLI_TESTS"
CAPTURE = "RESEARCH_HARNESS_LIVE_CLI_CAPTURE"

live_only = pytest.mark.skipif(
    os.environ.get(LIVE_FLAG) != "1",
    reason=f"set {LIVE_FLAG}=1 to run live CLI smoke tests",
)

_ID = re.compile(r"\b(?:sess|thread|msg|toolu|req|call|ses)[_-][A-Za-z0-9_-]+\b")
_HOME = re.compile(r"/home/[^/\s\"]+")
_VERSION_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _request() -> ModelRequest[Verdict]:
    return ModelRequest(
        role="evidence_verifier",
        requirements=ModelRequirements(
            structured_output=True,
            context_tokens=20_000,
            reasoning="low",
            max_output_tokens=512,
        ),
        instructions=(
            "Decide whether the source text states the throughput figure. "
            "Answer only with the required structured object."
        ),
        inputs=[InputEnvelope(object_id="work:live", kind="source_text", content=SOURCE_TEXT)],
        response_schema=Verdict,
        temperature=0.0,
    )


class _Capturing(BoundedProcess):
    """A bounded process that also keeps the stdout lines, for the sanitized capture.

    The buffer is class-level because `spawn` is what the provider is handed: the test
    never sees the instance, so there is nowhere per-instance to read the lines back from.
    One runtime runs at a time, and each test resets the buffer before spawning.
    """

    captured: ClassVar[list[str]] = []

    def lines(self) -> Iterator[str]:
        for line in super().lines():
            type(self).captured.append(line)
            yield line


def _sanitize(line: str) -> str:
    """Strip the two things a live stream carries that a fixture must not: ids and $HOME."""
    return _ID.sub("sess-x", _HOME.sub("~", line))


def _version_tag(version: str | None) -> str:
    """A file-name-safe version: it comes from a live CLI, so it never shapes the path."""
    return _VERSION_CHARS.sub("-", version or "unknown").strip("-") or "unknown"


def _write_capture(runtime: str, status: CliRuntimeStatus, lines: list[str]) -> Path:
    out = Path(os.environ[CAPTURE]) / f"{runtime}-live-{_version_tag(status.version)}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# source: live {runtime} {status.version or 'unknown'} "
        f"on {status.scanned_at.date().isoformat()}; sanitized"
    )
    body = "\n".join([header, *(_sanitize(line) for line in lines)])
    out.write_text(body + "\n", encoding="utf-8")
    return out


@live_only
@pytest.mark.parametrize("runtime", ["codex", "claude"])
def test_live_cli_smoke(runtime: str) -> None:
    status = detect(RUNTIMES[runtime])
    if not status.routable:
        detail = "; ".join(status.diagnostics)
        reason = status.unavailable_reason or f"auth {status.auth_status}"
        pytest.skip(f"{runtime}: {reason}" + (f" ({detail})" if detail else ""))
    capture = os.environ.get(CAPTURE)
    _Capturing.captured.clear()
    spawn: SpawnFactory = _Capturing.spawn if capture else BoundedProcess.spawn
    provider = CliModelProvider(runtime, timeout=180, spawn=spawn, version=status.version)

    response = provider.complete(_request())

    assert isinstance(response.parsed, Verdict)
    assert response.provider == f"local_cli:{runtime}"
    assert response.request_fingerprint
    if capture:
        _write_capture(runtime, status, list(_Capturing.captured))

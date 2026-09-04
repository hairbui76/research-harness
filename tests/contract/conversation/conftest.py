"""A workspace opened as the researcher, and a fake `codex` on `PATH`.

Both fixtures are copies rather than imports: `tests/contract` must not depend on
`tests/e2e`, and the capabilities conftest one directory over serves a different suite.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.cli.detection import DEFAULT_CACHE
from tests.fixtures.cli.fakes import FakeCli

STREAMS = Path(__file__).resolve().parents[2] / "fixtures" / "cli" / "streams"
HELP = (
    "--sandbox --output-schema --json --ephemeral --skip-git-repo-check "
    "--ignore-user-config --ignore-rules"
)


def lines(name: str) -> list[str]:
    return [
        line
        for line in (STREAMS / name).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[CapabilityContext]:
    """An initialized workspace opened as the researcher."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="binding"))
    yield open_context(result.root, HUMAN_ACTOR)


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    """A fake `codex` that probes clean; nothing here ever spawns the real one."""
    DEFAULT_CACHE.clear()
    fake = FakeCli.install(
        tmp_path / "tools",
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[
            {"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"},
            {"args": ["exec", "--help"], "stdout": HELP},
            # An empty catalog, so the scan falls back to the runtime's declared models
            # rather than the fake answering the model probe on its `run` branch.
            {"args": ["debug", "models"], "stdout": "{}"},
        ],
        run={"lines": lines("codex-success.jsonl")},
    )
    monkeypatch.setenv("PATH", str(fake.bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return fake

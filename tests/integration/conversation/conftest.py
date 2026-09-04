"""A workspace, a scripted provider, a fake `codex`, and services wired to them.

The CLI fixtures are copies rather than imports: `tests/integration` must not depend on
`tests/e2e` or `tests/contract`, and nothing here ever spawns a real runtime.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.send import ScriptedProviders
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import EgressClass
from research_harness.providers.cli.detection import DEFAULT_CACHE
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.cli.fakes import FakeCli

ANSWER = "Batching reduced tail latency by nine percent across the pilot corpus."

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
def repo(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository.init(tmp_path / "project", "conversation-integration")


@pytest.fixture
def ctx(repo: WorkspaceRepository) -> CapabilityContext:
    return CapabilityContext(repo=repo)


def service_for(
    ctx: CapabilityContext,
    provider: ScriptedProvider,
    *,
    chunk_words: int = 3,
    egress: EgressClass = EgressClass.LOCAL,
) -> ConversationService:
    """A conversation service that answers from ``provider`` and sends nothing anywhere."""
    return ConversationService(
        ctx, providers=ScriptedProviders(provider, chunk_words=chunk_words, egress=egress)
    )


@pytest.fixture
def answering(ctx: CapabilityContext) -> Iterator[ConversationService]:
    """A service whose provider answers once, in three-word deltas."""
    yield service_for(ctx, ScriptedProvider([{"text": ANSWER}]))


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

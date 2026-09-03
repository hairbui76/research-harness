"""Which streaming face `session.send` picks, decided by configuration alone.

Selection is where a send meets a backend, and it happens before a byte is sent — so this
is checkable offline and worth checking: a hosted adapter that streams natively must be
used natively (otherwise `GET /runs/{id}/events` delivers one delta at the end of a call
that took a minute), and a served model that does not stream must still look identical to
the caller.

Nothing here contacts anything: `WorkspaceProviders.select` builds adapters, reads the
policy, and asks the router — all of which is configuration, not I/O.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.context import ContextBudget
from research_harness.conversation.send import SEND_ROLE, WorkspaceProviders
from research_harness.domain.conversation import EgressClass
from research_harness.providers.models.streaming import (
    CompletionStream,
    NativeStream,
    StreamingModelProvider,
)
from research_harness.workspace.repository import WorkspaceRepository

HOSTED = {
    "name": "hosted",
    "kind": "anthropic",
    "model": "claude-test-1",
    "priority": 10,
    "api_key_env": "ANTHROPIC_API_KEY",
}
SERVED = {
    "name": "on-box",
    "kind": "local_openai_compatible",
    "model": "llama-test",
    "base_url": "http://127.0.0.1:11434/v1",
    "priority": 20,
}


def workspace(root: Path, providers: list[dict[str, Any]]) -> Path:
    repo = WorkspaceRepository.init(root, "send-selection")
    config_path = repo.root / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["providers"] = providers
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return repo.root


def select(root: Path, model: str | None = None) -> Any:
    ctx = CapabilityContext(repo=WorkspaceRepository.open(root))
    return WorkspaceProviders().select(ctx, model=model, budget=ContextBudget(total=4000))


@pytest.fixture(autouse=True)
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used-because-nothing-is-sent")


def test_a_hosted_adapter_is_streamed_natively(tmp_path: Path) -> None:
    """The adapter has a `stream()`, so the wrapper hands it through rather than batching."""
    root = workspace(tmp_path / "hosted", [HOSTED, SERVED])

    selection = select(root)

    assert isinstance(selection.provider, NativeStream)
    assert isinstance(selection.provider, StreamingModelProvider)
    assert selection.profile.provider == "anthropic"
    assert selection.profile.egress is EgressClass.EXTERNAL


def test_a_served_model_that_cannot_stream_still_looks_like_a_stream(tmp_path: Path) -> None:
    """One protocol for the caller: a backend without `stream()` is a stream of length one."""
    root = workspace(tmp_path / "served", [SERVED])

    selection = select(root)

    assert isinstance(selection.provider, CompletionStream)
    assert selection.profile.egress is EgressClass.LOCAL


def test_naming_an_entry_selects_it_and_keeps_its_streaming_face(tmp_path: Path) -> None:
    root = workspace(tmp_path / "named", [HOSTED, SERVED])

    hosted = select(root, model="hosted")
    served = select(root, model="on-box")

    assert isinstance(hosted.provider, NativeStream)
    assert isinstance(served.provider, CompletionStream)
    assert served.profile.model == "llama-test"


def test_the_streaming_face_never_changes_what_routing_decided(tmp_path: Path) -> None:
    """The wrapper is presentation: the entry, its capabilities and its egress are the router's."""
    root = workspace(tmp_path / "routing", [HOSTED, SERVED])

    selection = select(root)

    assert selection.capabilities is not None
    assert selection.capabilities.max_context_tokens >= 4000
    assert selection.provider.name == "anthropic"
    assert [label for label, _ in selection.alternatives] == ["local/llama-test"]
    assert SEND_ROLE == "conversation"

"""A workspace, a scripted provider, and a service wired to both."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.send import ScriptedProviders
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import EgressClass
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workspace.repository import WorkspaceRepository

ANSWER = "Batching reduced tail latency by nine percent across the pilot corpus."


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
